"""Stock movement business logic: atomic, race-safe, idempotent."""
import logging

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Length
from django.utils import timezone

from audit.models import ActivityLog
from audit.utils import log_action

from .models import Carton, StockMovement
from .permissions import can_access_inventory

logger = logging.getLogger(__name__)

MAX_CARTONS_PER_MOVEMENT = 100_000


class StockError(Exception):
    pass


def next_receipt_no(movement_type, when):
    prefix = "SI" if movement_type == StockMovement.Type.IN else "SO"
    day = timezone.localtime(when).strftime("%Y%m%d")
    base = f"{prefix}-{day}-"
    last = (
        StockMovement.objects.filter(receipt_no__startswith=base)
        .order_by(Length("receipt_no").desc(), "-receipt_no")
        .values_list("receipt_no", flat=True)
        .first()
    )
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{base}{n:04d}"


def _validate_carton_status(carton, movement_type):
    if carton.status == Carton.Status.CLOSED:
        raise StockError("This carton is closed and cannot be moved.")
    if movement_type == StockMovement.Type.OUT and carton.status in (Carton.Status.ON_HOLD, Carton.Status.DAMAGED):
        raise StockError(f"Cannot stock out from a carton that is {carton.get_status_display().lower()}.")


def preview_movement(carton, movement_type, cartons):
    """Compute before/after without saving; raises StockError when invalid."""
    if cartons < 1:
        raise StockError("Enter at least 1 carton.")
    _validate_carton_status(carton, movement_type)
    before = carton.carton_count
    if movement_type == StockMovement.Type.OUT:
        if cartons > before:
            raise StockError(f"Not enough stock. Only {before} carton(s) available — you tried to remove {cartons}.")
        after = before - cartons
    else:
        after = before + cartons
    return {
        "cartons_before": before,
        "cartons_after": after,
        "stock_before": before * carton.qty_per_carton,
        "stock_after": after * carton.qty_per_carton,
        "qty_moved": cartons * carton.qty_per_carton,
    }


def record_movement(*, user, carton_id, movement_type, cartons, note="", reference="", idempotency_key=None, request=None):
    """Record a stock movement. Returns (movement, created)."""
    if movement_type not in StockMovement.Type.values:
        raise StockError("Invalid movement type.")
    if not isinstance(cartons, int) or cartons < 1:
        raise StockError("Enter at least 1 carton.")
    if cartons > MAX_CARTONS_PER_MOVEMENT:
        raise StockError("Quantity is too large.")

    if idempotency_key:
        existing = StockMovement.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing, False

    mv = None
    for attempt in range(5):
        try:
            with transaction.atomic():
                carton = (
                    Carton.objects.select_for_update()
                    .select_related("product", "inventory")
                    .filter(pk=carton_id, is_deleted=False)
                    .first()
                )
                if carton is None:
                    raise StockError("Carton not found.")
                if not can_access_inventory(user, carton.inventory):
                    raise StockError("You do not have access to this inventory.")
                if carton.inventory.is_archived:
                    raise StockError("This inventory is archived.")
                if carton.product.is_deleted:
                    raise StockError("This product has been deleted.")
                _validate_carton_status(carton, movement_type)

                # Atomic conditional update — can never go negative, even under concurrency.
                if movement_type == StockMovement.Type.OUT:
                    updated = Carton.objects.filter(pk=carton.pk, carton_count__gte=cartons).update(
                        carton_count=F("carton_count") - cartons, updated_at=timezone.now()
                    )
                    if not updated:
                        carton.refresh_from_db(fields=["carton_count"])
                        raise StockError(
                            f"Not enough stock. Only {carton.carton_count} carton(s) available — you tried to remove {cartons}."
                        )
                else:
                    Carton.objects.filter(pk=carton.pk).update(
                        carton_count=F("carton_count") + cartons, updated_at=timezone.now()
                    )
                carton.refresh_from_db(fields=["carton_count"])
                after = carton.carton_count
                before = after - cartons if movement_type == StockMovement.Type.IN else after + cartons
                q = carton.qty_per_carton
                now = timezone.now()
                mv = StockMovement.objects.create(
                    type=movement_type,
                    receipt_no=next_receipt_no(movement_type, now),
                    product=carton.product,
                    carton=carton,
                    inventory=carton.inventory,
                    cartons_moved=cartons,
                    qty_per_carton=q,
                    qty_moved=cartons * q,
                    cartons_before=before,
                    cartons_after=after,
                    stock_before=before * q,
                    stock_after=after * q,
                    note=note.strip(),
                    reference=reference.strip(),
                    user=user,
                    user_display=user.get_full_name(),
                    user_role=user.get_role_display(),
                    created_at=now,
                    idempotency_key=idempotency_key or None,
                )
                log_action(
                    request,
                    ActivityLog.Action.STOCK_IN if movement_type == StockMovement.Type.IN else ActivityLog.Action.STOCK_OUT,
                    user=user,
                    obj=mv,
                    entity_repr=f"{mv.receipt_no} · {carton.product.name}",
                    product=carton.product,
                    inventory=carton.inventory,
                    movement=mv,
                    quantity=mv.qty_moved,
                    before=mv.stock_before,
                    after=mv.stock_after,
                    note=" | ".join(x for x in (mv.reference, mv.note) if x),
                    new={
                        "carton": carton.carton_code,
                        "cartons_moved": cartons,
                        "cartons_before": before,
                        "cartons_after": after,
                    },
                )
            break
        except IntegrityError:
            if idempotency_key:
                existing = StockMovement.objects.filter(idempotency_key=idempotency_key).first()
                if existing:
                    return existing, False
            if attempt == 4:
                raise
            continue  # receipt number collision — retry

    return mv, True

