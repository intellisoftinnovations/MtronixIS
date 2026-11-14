from django.db.models import Q

from .models import Carton, Inventory


def allowed_inventories(user, include_archived=True):
    qs = Inventory.objects.all()
    if not user.is_admin:
        qs = qs.filter(managers=user)
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return qs


def allowed_inventory_ids(user):
    return list(allowed_inventories(user).values_list("id", flat=True))


def can_access_inventory(user, inventory):
    if user.is_admin:
        return True
    return inventory.managers.filter(pk=user.pk).exists()


def cartons_for(user, include_deleted=False):
    qs = Carton.objects.select_related("product", "inventory")
    if not include_deleted:
        qs = qs.filter(is_deleted=False)
    if not user.is_admin:
        qs = qs.filter(inventory__managers=user)
    return qs


def inventory_filter_q(user, field="inventory"):
    if user.is_admin:
        return Q()
    return Q(**{f"{field}__managers": user})

