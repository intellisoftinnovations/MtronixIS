"""Offline snapshot & idempotent sync API for PWA mode."""
import json
import uuid

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from audit.models import ActivityLog
from audit.utils import log_action
from inventory.forms import generate_unique_sku
from inventory.images import process_product_image
from inventory.models import Product, StockMovement
from inventory.permissions import allowed_inventories, cartons_for
from inventory.services import StockError, record_movement


@login_required
@require_GET
def offline_snapshot(request):
    """Return the signed-in user's permitted inventories, products, and cartons for IndexedDB caching."""
    invs = list(
        allowed_inventories(request.user, include_archived=False)
        .order_by("name")
        .values("id", "name", "code", "location", "low_stock_threshold")
    )
    products = []
    for p in Product.objects.alive().order_by("name"):
        products.append(
            {
                "id": p.pk,
                "name": p.name,
                "sku": p.sku,
                "qr_token": p.qr_token,
                "description": p.description,
                "image_url": p.image.url if p.image else "",
            }
        )
    cartons = list(
        cartons_for(request.user)
        .filter(product__is_deleted=False, inventory__is_archived=False)
        .values(
            "id",
            "product_id",
            "inventory_id",
            "carton_code",
            "qr_token",
            "qty_per_carton",
            "carton_count",
            "status",
        )
    )
    return JsonResponse(
        {
            "generated_at": timezone.now().isoformat(),
            "user_id": request.user.pk,
            "is_admin": request.user.is_admin,
            "inventories": invs,
            "products": products,
            "cartons": cartons,
        }
    )


def _handle_stock_movement(request, item):
    try:
        carton_id = int(item.get("carton_id"))
        cartons = int(item.get("cartons"))
    except (TypeError, ValueError):
        return {"status": "error", "error": "Invalid carton or quantity."}

    movement_type = str(item.get("type", "")).upper()
    if movement_type not in StockMovement.Type.values:
        return {"status": "error", "error": "Invalid movement type."}

    idem_raw = item.get("idempotency_key")
    try:
        idem_key = uuid.UUID(str(idem_raw)) if idem_raw else None
    except ValueError:
        return {"status": "error", "error": "Invalid idempotency key."}

    try:
        mv, created = record_movement(
            user=request.user,
            carton_id=carton_id,
            movement_type=movement_type,
            cartons=cartons,
            note=str(item.get("note", ""))[:500],
            reference=str(item.get("reference", ""))[:100],
            idempotency_key=idem_key,
            request=request,
        )
    except StockError as exc:
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "created": created,
        "movement_id": mv.pk,
        "receipt_no": mv.receipt_no,
        "cartons_after": mv.cartons_after,
    }


def _handle_product_create(request, item, uploaded_image=None):
    name = str(item.get("name", "")).strip()
    if not name:
        return {"status": "error", "error": "Product name is required."}

    sku = str(item.get("sku", "")).strip().upper()
    if sku:
        if Product.objects.alive().filter(sku__iexact=sku).exists():
            return {"status": "error", "error": f"SKU '{sku}' already exists."}
    else:
        sku = generate_unique_sku(name)

    description = str(item.get("description", "")).strip()
    product = Product(name=name, sku=sku, description=description)

    if uploaded_image is not None:
        try:
            product.image = process_product_image(uploaded_image)
        except Exception as exc:
            return {"status": "error", "error": f"Invalid image: {exc}"}

    product.save()
    log_action(
        request,
        ActivityLog.Action.CREATE,
        obj=product,
        product=product,
        new={"name": product.name, "sku": product.sku, "description": product.description},
        note="Synced from offline queue",
    )
    return {
        "status": "ok",
        "product_id": product.pk,
        "sku": product.sku,
        "qr_token": product.qr_token,
        "image_url": product.image.url if product.image else "",
    }


@login_required
@require_POST
def offline_sync(request):
    """Sync one or more queued offline actions (stock_movement, product_create)."""
    content_type = request.content_type or ""
    if content_type.startswith("multipart/form-data"):
        raw_payload = request.POST.get("payload", "{}")
        try:
            item = json.loads(raw_payload)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON payload."}, status=400)
        kind = item.get("kind")
        client_id = item.get("id")
        if kind == "product_create":
            res = _handle_product_create(request, item, uploaded_image=request.FILES.get("image"))
        elif kind == "stock_movement":
            res = _handle_stock_movement(request, item)
        else:
            res = {"status": "error", "error": f"Unknown action kind: {kind}"}
        res["id"] = client_id
        return JsonResponse({"results": [res]})

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    items = body.get("items")
    if not isinstance(items, list):
        return JsonResponse({"error": "Expected 'items' list."}, status=400)

    results = []
    for item in items[:50]:
        kind = item.get("kind")
        client_id = item.get("id")
        if kind == "stock_movement":
            res = _handle_stock_movement(request, item)
        elif kind == "product_create":
            res = _handle_product_create(request, item)
        else:
            res = {"status": "error", "error": f"Unknown action kind: {kind}"}
        res["id"] = client_id
        results.append(res)

    return JsonResponse({"results": results})
