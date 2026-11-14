import re
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from audit.models import ActivityLog
from audit.utils import log_action
from inventory.forms import StockForm
from inventory.models import Product, StockMovement
from inventory.pdf import generate_receipt_pdf
from inventory.permissions import allowed_inventory_ids, can_access_inventory, cartons_for
from inventory.services import StockError, preview_movement, record_movement

TOKEN_IN_URL = re.compile(r"/q/([A-Za-z0-9_\-]{10,64})/?")


@login_required
def scan(request):
    return render(request, "inventory/scan.html")


@login_required
def scan_lookup(request):
    code = request.GET.get("code", "").strip()[:300]
    if not code:
        return redirect("inventory:scan")
    m = TOKEN_IN_URL.search(code)
    if m:
        code = m.group(1)
    cartons = cartons_for(request.user).filter(product__is_deleted=False)
    if cartons.filter(qr_token=code).exists() or Product.objects.alive().filter(qr_token=code).exists():
        return redirect("inventory:scan_result", token=code)
    by_code = list(cartons.filter(carton_code__iexact=code)[:20])
    if len(by_code) == 1:
        return redirect("inventory:scan_result", token=by_code[0].qr_token)
    if len(by_code) > 1:
        return render(request, "inventory/scan_choose.html", {"cartons": by_code, "code": code})
    product = Product.objects.alive().filter(sku__iexact=code).first()
    if product:
        return redirect("inventory:scan_result", token=product.qr_token)
    messages.error(request, f"No product or carton found for “{code[:60]}”, or you don’t have access to it.")
    return redirect("inventory:scan")


def _carton_context(request, carton, form=None, error=None):
    if form is None:
        form = StockForm(
            initial={
                "carton_id": carton.pk,
                "type": request.GET.get("type") if request.GET.get("type") in StockMovement.Type.values else "",
                "cartons": 1,
                "idempotency_key": uuid.uuid4(),
            }
        )
    return {"mode": "carton", "carton": carton, "product": carton.product, "form": form, "error": error}


@login_required
def scan_result(request, token):
    carton = cartons_for(request.user).filter(qr_token=token, product__is_deleted=False).first()
    if carton:
        return render(request, "inventory/scan_result.html", _carton_context(request, carton))
    product = Product.objects.alive().filter(qr_token=token).first()
    if product is None:
        raise Http404
    ids = allowed_inventory_ids(request.user)
    cartons = product.cartons.alive().filter(inventory_id__in=ids, inventory__is_archived=False).select_related("inventory")
    return render(request, "inventory/scan_result.html", {"mode": "product", "product": product, "cartons": cartons})


def _load_carton(request, form):
    carton = cartons_for(request.user).filter(pk=form.cleaned_data["carton_id"], product__is_deleted=False).first()
    if carton is None:
        raise Http404
    return carton


@login_required
@require_POST
def stock_confirm(request):
    form = StockForm(request.POST)
    if not form.is_valid():
        carton_id = request.POST.get("carton_id")
        carton = cartons_for(request.user).filter(pk=carton_id).first() if str(carton_id).isdigit() else None
        if carton is None:
            raise Http404
        return render(request, "inventory/scan_result.html", _carton_context(request, carton, form=form), status=400)
    carton = _load_carton(request, form)
    try:
        preview = preview_movement(carton, form.cleaned_data["type"], form.cleaned_data["cartons"])
    except StockError as e:
        return render(request, "inventory/scan_result.html", _carton_context(request, carton, form=form, error=str(e)), status=400)
    return render(
        request,
        "inventory/stock_confirm.html",
        {"form": form, "carton": carton, "product": carton.product, "preview": preview, "data": form.cleaned_data,
         "is_in": form.cleaned_data["type"] == StockMovement.Type.IN},
    )


@login_required
@require_POST
def stock_commit(request):
    form = StockForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Invalid submission. Please try again.")
        return redirect("inventory:scan")
    carton = _load_carton(request, form)
    d = form.cleaned_data
    try:
        mv, created = record_movement(
            user=request.user, carton_id=carton.pk, movement_type=d["type"], cartons=d["cartons"],
            note=d["note"], reference=d["reference"], idempotency_key=d["idempotency_key"], request=request,
        )
    except StockError as e:
        messages.error(request, str(e))
        return redirect("inventory:scan_result", token=carton.qr_token)
    if not created:
        messages.info(request, "This movement was already recorded — showing the existing receipt.")
    return redirect("inventory:movement_done", pk=mv.pk)


def _get_movement(request, pk):
    mv = get_object_or_404(StockMovement.objects.select_related("product", "inventory", "carton", "user"), pk=pk)
    if not can_access_inventory(request.user, mv.inventory):
        raise PermissionDenied
    return mv


@login_required
def movement_done(request, pk):
    return render(request, "inventory/stock_done.html", {"mv": _get_movement(request, pk)})


@login_required
def movement_detail(request, pk):
    return render(request, "inventory/movement_detail.html", {"mv": _get_movement(request, pk)})


def movement_verify(request, token):
    mv = get_object_or_404(
        StockMovement.objects.select_related("product", "inventory", "carton"),
        verify_token=token,
    )
    return render(request, "inventory/movement_verify.html", {"mv": mv})


@login_required
def movement_pdf(request, pk):
    mv = _get_movement(request, pk)
    if not mv.pdf or not mv.pdf.storage.exists(mv.pdf.name):
        generate_receipt_pdf(mv, request)
    response = FileResponse(
        mv.pdf.open("rb"),
        content_type="application/pdf",
        as_attachment=request.GET.get("download") == "1",
        filename=f"{mv.receipt_no}.pdf",
    )
    response["Cache-Control"] = "no-store, private"
    return response


@login_required
@require_POST
def movement_regenerate_pdf(request, pk):
    mv = _get_movement(request, pk)
    generate_receipt_pdf(mv, request)
    log_action(request, ActivityLog.Action.PDF_REGENERATE, obj=mv, entity_repr=mv.receipt_no,
               product=mv.product, inventory=mv.inventory, movement=mv)
    messages.success(request, f"PDF for {mv.receipt_no} regenerated.")
    return redirect(mv)

