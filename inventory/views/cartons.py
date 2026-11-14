from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from audit.models import ActivityLog
from audit.utils import diff, log_action, snapshot
from inventory.forms import CartonForm
from inventory.models import UNITS, Carton, Product, StockMovement, new_token
from inventory.permissions import allowed_inventories, cartons_for
from inventory.qr import public_qr_url, qr_data_uri
from inventory.services import StockError, record_movement
from inventory.timeutils import format_bd, parse_date

from .common import csv_response, date_range_filter, paginate, safe_int

CARTON_FIELDS = ["product", "inventory", "carton_code", "qty_per_carton", "carton_count", "status"]
SORTS = {
    "code": "carton_code", "-code": "-carton_code", "product": "product__name", "-product": "-product__name",
    "inventory": "inventory__name", "-inventory": "-inventory__name", "count": "carton_count", "-count": "-carton_count",
    "created": "created_at", "-created": "-created_at", "updated": "updated_at", "-updated": "-updated_at",
}


def _filtered_cartons(request):
    user = request.user
    show_deleted = user.is_admin and request.GET.get("deleted") == "1"
    qs = cartons_for(user, include_deleted=True).filter(is_deleted=show_deleted)
    if not show_deleted:
        qs = qs.filter(product__is_deleted=False)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(carton_code__icontains=q) | Q(product__name__icontains=q) | Q(product__sku__icontains=q))
    if inv := safe_int(request.GET.get("inventory")):
        qs = qs.filter(inventory_id=inv)
    if prod := safe_int(request.GET.get("product")):
        qs = qs.filter(product_id=prod)
    status = request.GET.get("status")
    if status in Carton.Status.values:
        qs = qs.filter(status=status)
    if request.GET.get("low") == "1":
        qs = qs.filter(carton_count__lt=F("inventory__low_stock_threshold"))
    qs = date_range_filter(qs, "created_at", parse_date(request.GET.get("from")), parse_date(request.GET.get("to")))
    return qs.order_by(SORTS.get(request.GET.get("sort", ""), "inventory__name"), "product__name", "carton_code")


@login_required
def carton_list(request):
    qs = _filtered_cartons(request)
    totals = qs.aggregate(c=Coalesce(Sum("carton_count"), 0), u=Coalesce(Sum(UNITS), 0))
    return render(
        request,
        "inventory/carton_list.html",
        {
            "page": paginate(request, qs),
            "totals": totals,
            "total": qs.count(),
            "inventories": allowed_inventories(request.user),
            "products": Product.objects.alive().only("id", "name", "sku"),
            "statuses": Carton.Status.choices,
        },
    )


@login_required
def carton_export(request):
    qs = _filtered_cartons(request)
    log_action(request, ActivityLog.Action.EXPORT, entity_type="Carton", entity_repr=f"Cartons CSV ({qs.count()} rows)")
    rows = (
        (
            c.carton_code, c.product.name, c.product.sku, c.inventory.name, c.inventory.code, c.qty_per_carton,
            c.carton_count, c.total_quantity, c.get_status_display(), format_bd(c.created_at), format_bd(c.updated_at),
        )
        for c in qs
    )
    return csv_response(
        f"cartons-{timezone.localtime():%Y%m%d-%H%M}.csv",
        ["Carton code", "Product", "SKU", "Inventory", "Inventory code", "Qty per carton", "Cartons", "Total quantity",
         "Status", "Created (BD time)", "Updated (BD time)"],
        rows,
    )


@login_required
def carton_detail(request, pk):
    carton = get_object_or_404(cartons_for(request.user, include_deleted=request.user.is_admin), pk=pk)
    public_url = public_qr_url(carton.qr_token, request)
    return render(
        request,
        "inventory/carton_detail.html",
        {
            "carton": carton,
            "movements": carton.movements.select_related("user")[:25],
            "public_url": public_url,
            "qr": qr_data_uri(public_url),
        },
    )


@login_required
def carton_create(request):
    initial = {}
    if p := safe_int(request.GET.get("product")):
        initial["product"] = p
    if i := safe_int(request.GET.get("inventory")):
        initial["inventory"] = i
    form = CartonForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        opening = form.cleaned_data.get("carton_count") or 0
        carton = form.save(commit=False)
        carton.carton_count = 0
        carton.created_by = request.user
        carton.save()
        log_action(request, ActivityLog.Action.CREATE, obj=carton, product=carton.product, inventory=carton.inventory,
                   new=snapshot(carton, CARTON_FIELDS) | {"opening_stock": opening})
        if opening:
            try:
                mv, _ = record_movement(
                    user=request.user, carton_id=carton.pk, movement_type=StockMovement.Type.IN,
                    cartons=opening, note="Opening stock", request=request,
                )
                messages.success(request, f"Carton {carton.carton_code} created with opening stock. Receipt {mv.receipt_no}.")
            except StockError as e:
                messages.warning(request, f"Carton created, but opening stock failed: {e}")
        else:
            messages.success(request, f"Carton {carton.carton_code} created.")
        return redirect(carton)
    return render(request, "inventory/carton_form.html", {"form": form, "title": "Add carton"})


@login_required
def carton_edit(request, pk):
    carton = get_object_or_404(cartons_for(request.user), pk=pk)
    old = snapshot(carton, CARTON_FIELDS)
    form = CartonForm(request.POST or None, instance=carton, user=request.user)
    if request.method == "POST" and form.is_valid():
        carton = form.save()
        o, n = diff(old, snapshot(carton, CARTON_FIELDS))
        if n:
            log_action(request, ActivityLog.Action.UPDATE, obj=carton, product=carton.product, inventory=carton.inventory, old=o, new=n)
        messages.success(request, "Carton updated.")
        return redirect(carton)
    return render(request, "inventory/carton_form.html", {"form": form, "title": f"Edit carton {carton.carton_code}", "carton": carton})


@admin_required
@require_POST
def carton_delete(request, pk):
    carton = get_object_or_404(Carton.objects.alive().select_related("product", "inventory"), pk=pk)
    carton.is_deleted = True
    carton.deleted_at = timezone.now()
    carton.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
    log_action(request, ActivityLog.Action.DELETE, obj=carton, product=carton.product, inventory=carton.inventory,
               old=snapshot(carton, CARTON_FIELDS), quantity=carton.total_quantity)
    messages.success(request, f"Carton {carton.carton_code} deleted. It can be restored by an admin.")
    return redirect("inventory:carton_list")


@admin_required
@require_POST
def carton_restore(request, pk):
    carton = get_object_or_404(Carton.objects.deleted().select_related("product", "inventory"), pk=pk)
    if Carton.objects.alive().filter(inventory=carton.inventory, carton_code__iexact=carton.carton_code).exists():
        messages.error(request, "Another active carton already uses this code in the same inventory.")
        return redirect(carton)
    if carton.product.is_deleted:
        messages.error(request, "Restore the product first.")
        return redirect(carton)
    carton.is_deleted = False
    carton.deleted_at = None
    carton.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
    log_action(request, ActivityLog.Action.RESTORE, obj=carton, product=carton.product, inventory=carton.inventory)
    messages.success(request, "Carton restored.")
    return redirect(carton)


@admin_required
@require_POST
def carton_regenerate_qr(request, pk):
    carton = get_object_or_404(Carton.objects.alive(), pk=pk)
    old = carton.qr_token
    carton.qr_token = new_token()
    carton.save(update_fields=["qr_token", "updated_at"])
    log_action(
        request, ActivityLog.Action.QR_REGENERATE, obj=carton, product=carton.product, inventory=carton.inventory,
        old={"qr_token": old[:6] + "…"}, new={"qr_token": carton.qr_token[:6] + "…"}, note="Old QR code revoked.",
    )
    messages.success(request, "New QR code generated. Old labels no longer work — reprint the label.")
    return redirect(carton)

