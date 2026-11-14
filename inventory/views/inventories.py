from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from audit.models import ActivityLog
from audit.utils import diff, log_action, snapshot
from inventory.forms import InventoryForm, InventoryLimitedForm
from inventory.models import UNITS, Inventory
from inventory.permissions import allowed_inventories, can_access_inventory

from .common import paginate

INV_FIELDS = ["name", "code", "location", "low_stock_threshold", "notes", "is_archived", "managers"]
ALIVE = Q(cartons__is_deleted=False, cartons__product__is_deleted=False)


@login_required
def inventory_list(request):
    show_archived = request.GET.get("archived") == "1"
    qs = allowed_inventories(request.user).filter(is_archived=show_archived)
    qs = qs.annotate(
        total_cartons=Coalesce(Sum("cartons__carton_count", filter=ALIVE), 0),
        total_units=Coalesce(Sum(F("cartons__carton_count") * F("cartons__qty_per_carton"), filter=ALIVE), 0),
        carton_lines=Count("cartons", filter=ALIVE),
        low_count=Count("cartons", filter=ALIVE & Q(cartons__carton_count__lt=F("low_stock_threshold"))),
    ).prefetch_related("managers")
    return render(request, "inventory/inventory_list.html", {"inventories": qs, "show_archived": show_archived})


@login_required
def inventory_detail(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    if not can_access_inventory(request.user, inventory):
        raise PermissionDenied
    cartons = inventory.cartons.alive().filter(product__is_deleted=False).select_related("product")
    q = request.GET.get("q", "").strip()
    if q:
        cartons = cartons.filter(Q(carton_code__icontains=q) | Q(product__name__icontains=q) | Q(product__sku__icontains=q))
    totals = cartons.aggregate(c=Coalesce(Sum("carton_count"), 0), u=Coalesce(Sum(UNITS), 0), n=Count("id"))
    return render(
        request,
        "inventory/inventory_detail.html",
        {
            "inventory": inventory,
            "page": paginate(request, cartons.order_by("product__name", "carton_code"), 25),
            "totals": totals,
            "recent": inventory.movements.select_related("product", "carton")[:10],
            "can_edit": request.user.is_admin or can_access_inventory(request.user, inventory),
        },
    )


@admin_required
def inventory_create(request):
    form = InventoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        inv = form.save()
        log_action(request, ActivityLog.Action.CREATE, obj=inv, inventory=inv, new=snapshot(inv, INV_FIELDS))
        messages.success(request, f"Inventory “{inv.name}” created.")
        return redirect(inv)
    return render(request, "inventory/inventory_form.html", {"form": form, "title": "Add inventory"})


@login_required
def inventory_edit(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    if not can_access_inventory(request.user, inventory):
        raise PermissionDenied
    FormClass = InventoryForm if request.user.is_admin else InventoryLimitedForm
    old = snapshot(inventory, INV_FIELDS)
    form = FormClass(request.POST or None, instance=inventory)
    if request.method == "POST" and form.is_valid():
        inv = form.save()
        o, n = diff(old, snapshot(inv, INV_FIELDS))
        if n:
            log_action(request, ActivityLog.Action.UPDATE, obj=inv, inventory=inv, old=o, new=n)
        messages.success(request, "Inventory updated.")
        return redirect(inv)
    return render(
        request,
        "inventory/inventory_form.html",
        {"form": form, "title": f"Edit {inventory.name}", "inventory": inventory, "limited": not request.user.is_admin},
    )


@admin_required
@require_POST
def inventory_archive(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    inventory.is_archived = not inventory.is_archived
    inventory.save(update_fields=["is_archived", "updated_at"])
    action = ActivityLog.Action.ARCHIVE if inventory.is_archived else ActivityLog.Action.UNARCHIVE
    log_action(request, action, obj=inventory, inventory=inventory)
    messages.success(request, f"Inventory {'archived' if inventory.is_archived else 'restored'}.")
    return redirect(inventory)

