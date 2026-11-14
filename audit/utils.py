import datetime
import decimal
import uuid

from django.db.models import Model
from django.db.models.fields.files import FieldFile

from accounts.security import client_ip, user_agent

from .models import ActivityLog


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, (decimal.Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, FieldFile):
        return value.name or ""
    if isinstance(value, Model):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def snapshot(instance, fields):
    """JSON-safe dict of selected fields (FKs rendered via str())."""
    data = {}
    for f in fields:
        val = getattr(instance, f, None)
        if hasattr(val, "all") and callable(val.all):  # m2m manager
            val = sorted(str(v) for v in val.all())
        data[f] = _jsonable(val)
    return data


def diff(old, new):
    """Return (old_changed, new_changed) containing only changed keys."""
    keys = [k for k in new if old.get(k) != new.get(k)]
    return {k: old.get(k) for k in keys}, {k: new.get(k) for k in keys}


def log_action(
    request,
    action,
    *,
    user=None,
    obj=None,
    entity_type="",
    entity_id="",
    entity_repr="",
    product=None,
    inventory=None,
    movement=None,
    quantity=None,
    before=None,
    after=None,
    note="",
    old=None,
    new=None,
):
    if user is None and request is not None and getattr(request, "user", None) is not None:
        if request.user.is_authenticated:
            user = request.user
    if obj is not None:
        entity_type = entity_type or obj.__class__.__name__
        entity_id = entity_id or str(obj.pk)
        entity_repr = entity_repr or str(obj)
    display = ""
    if user is not None:
        display = f"{user.get_full_name()} ({user.get_role_display()})"
    return ActivityLog.objects.create(
        user=user,
        user_display=display[:200],
        action=action,
        entity_type=entity_type[:40],
        entity_id=str(entity_id)[:40],
        entity_repr=str(entity_repr)[:255],
        product=product,
        inventory=inventory,
        movement=movement,
        quantity=quantity,
        before=before,
        after=after,
        note=note or "",
        old_value=_jsonable(old) if old is not None else None,
        new_value=_jsonable(new) if new is not None else None,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )

