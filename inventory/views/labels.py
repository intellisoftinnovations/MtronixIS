from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from inventory.models import Product
from inventory.pdf import build_labels_pdf
from inventory.permissions import cartons_for
from inventory.qr import public_qr_url, qr_data_uri, qr_png

from .common import safe_int

MAX_SELECTED = 300
MAX_COPIES = 500
MAX_TOTAL_LABELS = 1000

LABEL_SIZES = {
    "62x36": (62, 36, "62 × 36 mm (Standard)"),
    "50x30": (50, 30, "50 × 30 mm (Small Roll)"),
    "40x30": (40, 30, "40 × 30 mm (Compact)"),
    "80x50": (80, 50, "80 × 50 mm (Large)"),
    "100x50": (100, 50, "100 × 50 mm (4×2 in)"),
}


@login_required
def labels_print(request):
    carton_ids = [i for i in (safe_int(v) for v in request.GET.getlist("c")) if i][:MAX_SELECTED]
    product_ids = [i for i in (safe_int(v) for v in request.GET.getlist("p")) if i][:MAX_SELECTED]
    copies = min(max(safe_int(request.GET.get("copies"), 1), 1), MAX_COPIES)

    mode = request.GET.get("mode", "a4")
    if mode not in ("a4", "roll"):
        mode = "a4"

    default_cols = 1 if mode == "roll" else 3
    cols = min(max(safe_int(request.GET.get("cols"), default_cols), 1), 6)

    size_key = request.GET.get("size", "62x36")
    if size_key not in LABEL_SIZES:
        size_key = "62x36"
    label_w_mm, label_h_mm, _ = LABEL_SIZES[size_key]

    labels = []
    for c in cartons_for(request.user).filter(pk__in=carton_ids).order_by("inventory__name", "carton_code"):
        url = public_qr_url(c.qr_token, request)
        labels.append(
            {
                "title": c.product.name,
                "sku": c.product.sku,
                "code": c.carton_code,
                "inventory": c.inventory.name,
                "qty": c.qty_per_carton,
                "qr": qr_data_uri(url, 8, 1),
                "url": url,
            }
        )
    for p in Product.objects.alive().filter(pk__in=product_ids).order_by("name"):
        url = public_qr_url(p.qr_token, request)
        labels.append(
            {
                "title": p.name,
                "sku": p.sku,
                "code": "",
                "inventory": "",
                "qty": None,
                "qr": qr_data_uri(url, 8, 1),
                "url": url,
            }
        )

    expanded_labels = [lab for lab in labels for _ in range(copies)][:MAX_TOTAL_LABELS]

    if request.GET.get("format") == "pdf":
        pdf_bytes = build_labels_pdf(
            expanded_labels,
            mode=mode,
            cols=cols,
            label_w_mm=label_w_mm,
            label_h_mm=label_h_mm,
        )
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        disposition = "attachment" if request.GET.get("download") == "1" else "inline"
        resp["Content-Disposition"] = f'{disposition}; filename="qr-labels.pdf"'
        return resp

    gap_x_mm = 2 if (mode == "roll" and cols > 1) else (0 if mode == "roll" else 4)
    page_w_mm = cols * label_w_mm + (cols - 1) * gap_x_mm
    qr_mm = min(label_h_mm - 5, int(label_w_mm * 0.42))

    # Group into rows for clean row-based page breaks in Thermal Roll mode
    rows = [expanded_labels[i : i + cols] for i in range(0, len(expanded_labels), cols)]

    return render(
        request,
        "inventory/labels_print.html",
        {
            "labels": expanded_labels,
            "rows": rows,
            "unique_count": len(labels),
            "copies": copies,
            "mode": mode,
            "cols": cols,
            "size_key": size_key,
            "label_sizes": LABEL_SIZES,
            "label_w_mm": label_w_mm,
            "label_h_mm": label_h_mm,
            "page_w_mm": page_w_mm,
            "qr_mm": qr_mm,
            "carton_ids": carton_ids,
            "product_ids": product_ids,
        },
    )


@login_required
def qr_image(request, token):
    """PNG of the public QR URL (only for tokens the user can see)."""
    from django.http import Http404

    exists = (
        cartons_for(request.user).filter(qr_token=token).exists()
        or Product.objects.alive().filter(qr_token=token).exists()
    )
    if not exists:
        raise Http404
    png = qr_png(public_qr_url(token, request), box_size=10, border=2)
    resp = HttpResponse(png, content_type="image/png")
    if request.GET.get("download") == "1":
        resp["Content-Disposition"] = f'attachment; filename="qr-{token[:8]}.png"'
    resp["Cache-Control"] = "private, max-age=300"
    return resp
