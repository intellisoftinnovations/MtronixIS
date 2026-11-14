import base64
import io

import qrcode
from django.conf import settings
from django.urls import reverse
from qrcode.constants import ERROR_CORRECT_M


def qr_png(data, box_size=10, border=2):
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_data_uri(data, box_size=8, border=2):
    return "data:image/png;base64," + base64.b64encode(qr_png(data, box_size, border)).decode()


def absolute_url(path, request=None):
    base = (settings.MTX_SITE_URL or "").rstrip("/")
    if base:
        return base + path
    if request is not None:
        return request.build_absolute_uri(path)
    return "http://localhost:8000" + path


def public_qr_url(token, request=None):
    return absolute_url(reverse("inventory:public_qr", args=[token]), request)

