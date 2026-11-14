from django.conf import settings
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts import security
from inventory.models import Carton, Product
from inventory.permissions import can_access_inventory


@require_GET
@never_cache
def public_qr(request, token):
    """PUBLIC: shows ONLY the product image and name. No stock, prices or inventory info."""
    ip = security.client_ip(request) or "unknown"
    if security.hit(f"pubqr:{ip}", 60) > settings.MTX_PUBLIC_QR_RATE:
        return render(request, "errors/429.html", status=429)

    token = (token or "")[:64]
    carton = Carton.objects.alive().select_related("product", "inventory").filter(qr_token=token, product__is_deleted=False).first()
    product = carton.product if carton else Product.objects.alive().filter(qr_token=token).first()

    if product and request.user.is_authenticated:
        if carton is None or can_access_inventory(request.user, carton.inventory):
            return redirect("inventory:scan_result", token=token)

    if product is None:
        return render(request, "public/qr_invalid.html", status=404)
    return render(request, "public/qr.html", {"name": product.name, "image": product.image})

