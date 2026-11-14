from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from audit.models import ActivityLog
from audit.utils import diff, log_action, snapshot
from inventory.forms import ProductForm
from inventory.models import Carton, Product, new_token
from inventory.permissions import allowed_inventories, allowed_inventory_ids
from inventory.qr import public_qr_url, qr_data_uri

from .common import csv_response, date_range_filter, paginate, safe_int
from inventory.timeutils import format_bd, parse_date

PRODUCT_FIELDS = ["name", "sku", "description", "image"]
SORTS = {
    "name": "name", "-name": "-name", "sku": "sku", "-sku": "-sku",
    "created": "created_at", "-created": "-created_at", "stock": "total_units", "-stock": "-total_units",
}


def _filtered_products(request):
    user = request.user
    show_deleted = user.is_admin and request.GET.get("status") == "deleted"
    qs = Product.objects.filter(is_deleted=show_deleted)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(description__icontains=q))
    ids = allowed_inventory_ids(user)
    inv = safe_int(request.GET.get("inventory"))
    cond = Q(cartons__is_deleted=False, cartons__inventory_id__in=ids)
    if inv and inv in ids:
        qs = qs.filter(id__in=Carton.objects.alive().filter(inventory_id=inv).values("product_id"))
        cond &= Q(cartons__inventory_id=inv)
    qs = date_range_filter(qs, "created_at", parse_date(request.GET.get("from")), parse_date(request.GET.get("to")))
    qs = qs.annotate(
        total_cartons=Coalesce(Sum("cartons__carton_count", filter=cond), 0),
        total_units=Coalesce(Sum(F("cartons__carton_count") * F("cartons__qty_per_carton"), filter=cond), 0),
        carton_lines=Count("cartons", filter=cond),
    )
    sort = request.GET.get("sort", "name")
    return qs.order_by(SORTS.get(sort, "name"), "id")


@login_required
def product_list(request):
    qs = _filtered_products(request)
    return render(
        request,
        "inventory/product_list.html",
        {
            "page": paginate(request, qs),
            "inventories": allowed_inventories(request.user),
            "total": qs.count(),
        },
    )


@login_required
def product_export(request):
    qs = _filtered_products(request)
    log_action(request, ActivityLog.Action.EXPORT, entity_type="Product", entity_repr=f"Products CSV ({qs.count()} rows)")
    rows = (
        (p.name, p.sku, p.description, p.carton_lines, p.total_cartons, p.total_units, format_bd(p.created_at), "Deleted" if p.is_deleted else "Active")
        for p in qs
    )
    return csv_response(
        f"products-{timezone.localtime():%Y%m%d-%H%M}.csv",
        ["Name", "SKU", "Description", "Carton lines", "Cartons", "Total quantity", "Created (BD time)", "Status"],
        rows,
    )


@login_required
def product_detail(request, pk):
    qs = Product.objects.all() if request.user.is_admin else Product.objects.alive()
    product = get_object_or_404(qs, pk=pk)
    ids = allowed_inventory_ids(request.user)
    cartons = product.cartons.alive().filter(inventory_id__in=ids).select_related("inventory")
    totals = cartons.aggregate(c=Coalesce(Sum("carton_count"), 0), u=Coalesce(Sum(F("carton_count") * F("qty_per_carton")), 0))
    public_url = public_qr_url(product.qr_token, request)
    return render(
        request,
        "inventory/product_detail.html",
        {
            "product": product,
            "cartons": cartons,
            "totals": totals,
            "movements": product.movements.filter(inventory_id__in=ids).select_related("inventory", "carton")[:15],
            "public_url": public_url,
            "qr": qr_data_uri(public_url),
        },
    )


def _save_product(request, form, instance=None):
    old = snapshot(instance, PRODUCT_FIELDS) if instance else None
    old_image = instance.image.name if instance and instance.image else ""
    product = form.save(commit=False)
    if not product.pk:
        product.created_by = request.user
    product.save()
    if old_image and old_image != (product.image.name or ""):
        from django.core.files.storage import default_storage

        try:
            default_storage.delete(old_image)
        except Exception:
            pass
    new = snapshot(product, PRODUCT_FIELDS)
    if instance is None:
        log_action(request, ActivityLog.Action.CREATE, obj=product, product=product, new=new)
    else:
        o, n = diff(old, new)
        if n:
            log_action(request, ActivityLog.Action.UPDATE, obj=product, product=product, old=o, new=n)
    return product


@login_required
def product_create(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        product = _save_product(request, form)
        messages.success(request, f"Product “{product.name}” created.")
        return redirect(product)
    return render(request, "inventory/product_form.html", {"form": form, "title": "Add product"})


@login_required
def product_edit(request, pk):
    product = get_object_or_404(Product.objects.alive(), pk=pk)
    original = Product.objects.get(pk=pk)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == "POST" and form.is_valid():
        _save_product(request, form, instance=original)
        messages.success(request, "Product updated.")
        return redirect(product)
    return render(request, "inventory/product_form.html", {"form": form, "title": f"Edit {original.name}", "product": original})


@admin_required
@require_POST
def product_delete(request, pk):
    product = get_object_or_404(Product.objects.alive(), pk=pk)
    if product.cartons.alive().exists():
        messages.error(request, "This product still has cartons. Delete or close its cartons first.")
        return redirect(product)
    product.is_deleted = True
    product.deleted_at = timezone.now()
    product.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
    log_action(request, ActivityLog.Action.DELETE, obj=product, product=product, old=snapshot(product, PRODUCT_FIELDS))
    messages.success(request, f"Product “{product.name}” deleted. It can be restored from the deleted filter.")
    return redirect("inventory:product_list")


@admin_required
@require_POST
def product_restore(request, pk):
    product = get_object_or_404(Product.objects.deleted(), pk=pk)
    product.is_deleted = False
    product.deleted_at = None
    product.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
    log_action(request, ActivityLog.Action.RESTORE, obj=product, product=product)
    messages.success(request, "Product restored.")
    return redirect(product)


@admin_required
@require_POST
def product_regenerate_qr(request, pk):
    product = get_object_or_404(Product.objects.alive(), pk=pk)
    old = product.qr_token
    product.qr_token = new_token()
    product.save(update_fields=["qr_token", "updated_at"])
    log_action(
        request, ActivityLog.Action.QR_REGENERATE, obj=product, product=product,
        old={"qr_token": old[:6] + "…"}, new={"qr_token": product.qr_token[:6] + "…"},
        note="Old QR code revoked.",
    )
    messages.success(request, "New QR code generated. Old labels no longer work — reprint labels.")
    return redirect(product)

