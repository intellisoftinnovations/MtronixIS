"""PWA endpoints: Web App Manifest, root-scoped Service Worker, and offline fallback page."""
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static


def manifest_json(request):
    data = {
        "name": settings.MTX_SYSTEM_NAME,
        "short_name": "Mtronix",
        "description": "Mtronix Inventory Management System — offline-capable QR scanning & stock tracking.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#161F24",
        "theme_color": "#161F24",
        "icons": [
            {
                "src": static("icons/icon-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": static("icons/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    resp = JsonResponse(data, content_type="application/manifest+json")
    resp["Cache-Control"] = "public, max-age=3600"
    return resp


def service_worker(request):
    sw_path = Path(settings.BASE_DIR) / "static" / "sw.js"
    content = sw_path.read_text(encoding="utf-8")
    resp = HttpResponse(content, content_type="application/javascript; charset=utf-8")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp


def offline_page(request):
    return render(request, "offline.html")
