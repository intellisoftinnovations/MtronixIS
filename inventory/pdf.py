"""PDF receipt generation (ReportLab). Print-friendly, white background."""
import io
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.urls import reverse
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from .qr import absolute_url, qr_png
from .timeutils import format_bd

logger = logging.getLogger(__name__)

PRIMARY = colors.HexColor("#22333B")
ACCENT = colors.HexColor("#C6AC8E")
GREEN = colors.HexColor("#15803D")
RED = colors.HexColor("#B91C1C")
LIGHT = colors.HexColor("#F3F5F6")
BORDER = colors.HexColor("#D6DCDF")
MUTED = colors.HexColor("#5B6B72")


def _p(text, size=9.5, bold=False, color=colors.black):
    style = ParagraphStyle(
        "c", fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, leading=size * 1.3,
        textColor=color, alignment=TA_LEFT,
    )
    from xml.sax.saxutils import escape

    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


def build_receipt_pdf(mv, request=None):
    buf = io.BytesIO()
    W, H = A4
    M = 40
    c = canvas.Canvas(buf, pagesize=A4)
    title = "STOCK IN RECEIPT" if mv.is_in else "STOCK OUT RECEIPT"
    c.setTitle(f"{title} {mv.receipt_no}")
    c.setAuthor(settings.MTX_SYSTEM_NAME)
    c.setSubject(title)

    # ---- header band -----------------------------------------------------
    c.setFillColor(PRIMARY)
    c.rect(0, H - 92, W, 92, stroke=0, fill=1)
    c.setFillColor(ACCENT)
    c.rect(0, H - 95, W, 3, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(M, H - 48, settings.MTX_COMPANY_NAME)
    c.setFont("Helvetica", 9.5)
    c.setFillColor(colors.HexColor("#D9E1E4"))
    c.drawString(M, H - 66, f"{settings.MTX_SYSTEM_NAME} · Carton Inventory System")
    c.setFillColor(colors.HexColor("#D9E1E4"))
    c.setFont("Helvetica", 9)
    c.drawRightString(W - M, H - 40, "RECEIPT NO.")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(W - M, H - 60, mv.receipt_no)

    # ---- title badge -----------------------------------------------------
    badge_color = GREEN if mv.is_in else RED
    c.setFont("Helvetica-Bold", 13)
    tw = c.stringWidth(title, "Helvetica-Bold", 13)
    c.setFillColor(badge_color)
    c.roundRect(M, H - 140, tw + 34, 28, 7, stroke=0, fill=1)
    c.setFillColor(colors.white)
    arrow = "IN" if mv.is_in else "OUT"
    c.drawString(M + 17, H - 131, title)

    # ---- date & time (Bangladesh) ---------------------------------------
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(M, H - 162, "DATE & TIME (BANGLADESH)")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(M, H - 181, format_bd(mv.created_at))

    # ---- verification QR (top-right) ------------------------------------
    verify_url = absolute_url(reverse("inventory:movement_verify", args=[mv.verify_token]), request)
    qr_size = 104
    qx, qy = W - M - qr_size, H - 112 - qr_size
    c.drawImage(ImageReader(io.BytesIO(qr_png(verify_url, box_size=6, border=1))), qx, qy, qr_size, qr_size)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawCentredString(qx + qr_size / 2, qy - 10, "Scan to verify receipt")

    # ---- product block --------------------------------------------------
    top = H - 240
    box = 92
    c.setStrokeColor(BORDER)
    c.setFillColor(LIGHT)
    c.roundRect(M, top - box, box, box, 8, stroke=1, fill=1)
    product = mv.product
    if product.image:
        try:
            img = ImageReader(product.image.path)
            iw, ih = img.getSize()
            scale = min((box - 10) / iw, (box - 10) / ih)
            dw, dh = iw * scale, ih * scale
            c.drawImage(img, M + (box - dw) / 2, top - box + (box - dh) / 2, dw, dh, mask="auto")
        except Exception:  # missing/corrupt image must never block a receipt
            logger.warning("Could not embed product image for %s", mv.receipt_no)
    else:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 8)
        c.drawCentredString(M + box / 2, top - box / 2, "No image")

    tx = M + box + 18
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(tx, top - 22, product.name[:60])
    c.setFont("Helvetica", 10)
    c.setFillColor(MUTED)
    c.drawString(tx, top - 40, f"SKU: {product.sku}")
    c.drawString(tx, top - 56, f"Inventory: {mv.inventory.name} ({mv.inventory.code})")
    c.drawString(tx, top - 72, f"Carton: {mv.carton.carton_code}")

    # ---- details table --------------------------------------------------
    sign = "+" if mv.is_in else "-"
    rows = [
        ("Receipt number", mv.receipt_no),
        ("Movement type", "Stock In" if mv.is_in else "Stock Out"),
        ("Date & time", format_bd(mv.created_at)),
        ("Product", product.name),
        ("SKU", product.sku),
        ("Inventory", f"{mv.inventory.name} ({mv.inventory.code})"),
        ("Carton code", mv.carton.carton_code),
        ("Cartons moved", f"{sign}{mv.cartons_moved:,}"),
        ("Quantity per carton", f"{mv.qty_per_carton:,}"),
        ("Total quantity", f"{sign}{mv.qty_moved:,} units"),
        ("Stock before", f"{mv.cartons_before:,} cartons · {mv.stock_before:,} units"),
        ("Stock after", f"{mv.cartons_after:,} cartons · {mv.stock_after:,} units"),
        ("Performed by", f"{mv.user_display} ({mv.user_role})"),
        ("Reference", mv.reference or "—"),
        ("Note", mv.note or "—"),
    ]
    data = [[_p(k, 9, True, MUTED), _p(v, 10, k in ("Total quantity", "Stock after"))] for k, v in rows]
    table = Table(data, colWidths=[140, W - 2 * M - 140])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER),
                ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (1, 9), (1, 9), colors.HexColor("#ECFDF3") if mv.is_in else colors.HexColor("#FEF2F2")),
            ]
        )
    )
    tw_, th_ = table.wrapOn(c, W - 2 * M, H)
    table_top = top - box - 22
    table.drawOn(c, M, table_top - th_)

    # ---- signatures -----------------------------------------------------
    sig_y = max(table_top - th_ - 60, 95)
    c.setStrokeColor(colors.HexColor("#9AA5AA"))
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8.5)
    for i, label in enumerate(("Prepared by", "Received / Delivered by", "Authorized by")):
        x = M + i * ((W - 2 * M) / 3)
        c.line(x, sig_y, x + 140, sig_y)
        c.drawString(x, sig_y - 12, label)

    # ---- footer ---------------------------------------------------------
    c.setStrokeColor(BORDER)
    c.line(M, 58, W - M, 58)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(PRIMARY)
    c.drawCentredString(W / 2, 44, "System generated document")
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawCentredString(W / 2, 32, f"{settings.MTX_SYSTEM_NAME} · {mv.receipt_no} · {arrow} · Times shown in Bangladesh time (UTC+6)")

    c.showPage()
    c.save()
    return buf.getvalue()


def generate_receipt_pdf(mv, request=None):
    """Build the PDF and store it in private storage; returns the movement."""
    from .models import StockMovement

    content = build_receipt_pdf(mv, request)
    if mv.pdf:
        try:
            mv.pdf.delete(save=False)
        except Exception:
            pass
    mv.pdf.save(f"{mv.receipt_no}.pdf", ContentFile(content), save=False)
    StockMovement.objects.filter(pk=mv.pk).update(pdf=mv.pdf.name)
    return mv


def build_labels_pdf(labels, mode="a4", cols=3, label_w_mm=62, label_h_mm=36):
    """Build a print-ready PDF of QR labels for either A4 sheets or thermal label printers (roll).

    mode='roll': each row of `cols` labels is its own PDF page sized to the label roll.
    mode='a4':   packs `cols` columns onto A4 pages.
    """
    from reportlab.lib.units import mm

    buf = io.BytesIO()
    cols = max(1, min(int(cols or 3), 6))
    label_w = max(25, min(int(label_w_mm or 62), 150)) * mm
    label_h = max(20, min(int(label_h_mm or 36), 150)) * mm
    is_roll = (mode == "roll")

    if is_roll:
        gap_x = (2 * mm) if cols > 1 else 0
        page_w = cols * label_w + (cols - 1) * gap_x
        page_h = label_h
        c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    else:
        page_w, page_h = A4
        c = canvas.Canvas(buf, pagesize=A4)
        gap_x = 4 * mm
        gap_y = 4 * mm
        margin_y = 10 * mm
        rows = max(1, int((page_h - 2 * margin_y + gap_y) // (label_h + gap_y)))
        per_page = cols * rows
        grid_w = cols * label_w + (cols - 1) * gap_x
        margin_x = max(5 * mm, (page_w - grid_w) / 2)

    c.setTitle(f"{settings.MTX_SYSTEM_NAME} - QR Labels")
    c.setAuthor(settings.MTX_SYSTEM_NAME)

    if not labels:
        c.setFont("Helvetica", 10)
        c.drawCentredString(page_w / 2, page_h / 2, "No labels selected.")
        c.showPage()
        c.save()
        return buf.getvalue()

    qr_cache = {}

    def _get_qr_reader(url):
        reader = qr_cache.get(url)
        if reader is None:
            reader = ImageReader(io.BytesIO(qr_png(url, box_size=8, border=1)))
            qr_cache[url] = reader
        return reader

    def _draw_label(x, y, lab):
        if not is_roll:
            c.setStrokeColor(BORDER)
            c.setLineWidth(0.75)
            c.roundRect(x, y, label_w, label_h, 2.5 * mm, stroke=1, fill=0)

        pad = 2 * mm
        qr_size = min(label_h - 2 * pad, label_w * 0.44)
        qr_x = x + pad
        qr_y = y + (label_h - qr_size) / 2
        c.drawImage(_get_qr_reader(lab["url"]), qr_x, qr_y, qr_size, qr_size)

        tx = qr_x + qr_size + 2 * mm
        max_tw = max(10, x + label_w - tx - pad)

        title_size = 9 if label_h >= 34 * mm else 7.5
        body_size = 7.8 if label_h >= 34 * mm else 6.6
        line_step = 4.0 * mm if label_h >= 34 * mm else 3.3 * mm

        def _fit(text, font, size):
            s = str(text or "")
            while s and c.stringWidth(s, font, size) > max_tw:
                s = s[:-1]
            return s

        ty = y + label_h - pad - title_size * 0.35 - 1.5 * mm
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", title_size)
        c.drawString(tx, ty, _fit(lab.get("title", ""), "Helvetica-Bold", title_size))

        c.setFont("Helvetica", body_size)
        c.setFillColor(MUTED)
        lines = []
        if lab.get("sku"):
            lines.append(f"SKU: {lab['sku']}")
        if lab.get("code"):
            lines.append(f"Ctn: {lab['code']}")
        if lab.get("inventory"):
            lines.append(str(lab["inventory"]))
        if lab.get("qty"):
            lines.append(f"Qty/ctn: {lab['qty']:,}" if isinstance(lab["qty"], int) else f"Qty: {lab['qty']}")

        for line in lines:
            ty -= line_step
            if ty < y + pad:
                break
            c.drawString(tx, ty, _fit(line, "Helvetica", body_size))

    if is_roll:
        for idx, lab in enumerate(labels):
            col = idx % cols
            if idx > 0 and col == 0:
                c.showPage()
            x = col * (label_w + gap_x)
            _draw_label(x, 0, lab)
    else:
        for idx, lab in enumerate(labels):
            pos = idx % per_page
            if idx > 0 and pos == 0:
                c.showPage()
            col = pos % cols
            row = pos // cols
            x = margin_x + col * (label_w + gap_x)
            y = page_h - margin_y - (row + 1) * label_h - row * gap_y
            _draw_label(x, y, lab)

    c.showPage()
    c.save()
    return buf.getvalue()


