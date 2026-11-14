from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from audit.models import ActivityLog
from inventory.models import Product
from inventory.permissions import allowed_inventories, inventory_filter_q
from inventory.views.common import csv_response, date_range_filter, paginate, safe_int
from inventory.timeutils import format_bd, parse_date


def _filtered_logs(request):
    user = request.user
    qs = ActivityLog.objects.select_related("user", "product", "inventory", "movement")
    if not user.is_admin:
        qs = qs.filter(Q(inventory__isnull=True, user=user) | inventory_filter_q(user))

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(entity_repr__icontains=q) | Q(user_display__icontains=q) | Q(note__icontains=q)
        )
    action = request.GET.get("action")
    if action and action in ActivityLog.Action.values:
        qs = qs.filter(action=action)
    if uid := safe_int(request.GET.get("user")):
        qs = qs.filter(user_id=uid)
    if inv := safe_int(request.GET.get("inventory")):
        qs = qs.filter(inventory_id=inv)
    if prod := safe_int(request.GET.get("product")):
        qs = qs.filter(product_id=prod)
    return date_range_filter(qs, "created_at", parse_date(request.GET.get("from")), parse_date(request.GET.get("to")))


@login_required
def log_list(request):
    user = request.user
    qs = _filtered_logs(request)

    User = get_user_model()
    users = User.objects.all().order_by("name") if user.is_admin else None
    inventories = allowed_inventories(user, include_archived=True).order_by("name")
    products = Product.objects.alive().order_by("name")

    return render(request, "audit/log_list.html", {
        "page": paginate(request, qs, 30),
        "total": qs.count(),
        "actions": ActivityLog.Action.choices,
        "users": users,
        "inventories": inventories,
        "products": products,
    })


@login_required
def log_export(request):
    qs = _filtered_logs(request).order_by("-created_at")

    from audit.utils import log_action
    log_action(request, ActivityLog.Action.EXPORT, entity_type="ActivityLog", entity_repr=f"Activity Log CSV ({qs.count()} rows)")

    rows = (
        (
            format_bd(e.created_at), e.user_display, e.get_action_display(),
            e.entity_type, e.entity_repr, str(e.inventory or ""),
            str(e.product or ""), e.quantity or "", e.before or "", e.after or "", e.note,
        )
        for e in qs[:5000]
    )
    return csv_response(
        "activity-log.csv",
        ["Date (BD time)", "User", "Action", "Entity type", "Entity", "Inventory", "Product",
         "Quantity", "Before", "After", "Note"],
        rows,
    )
