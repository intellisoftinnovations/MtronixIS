"""Product image validation & compression."""
import io
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000  # guard against decompression bombs

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


def _encode_webp(img, quality):
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=quality, method=4)
    return out.getvalue()


def process_product_image(uploaded):
    """Validate type & size, fix orientation, resize and re-encode as WebP under target KB.

    Re-encoding strips metadata (EXIF/GPS) and any embedded payloads.
    """
    max_bytes = settings.MTX_MAX_IMAGE_MB * 1024 * 1024
    if uploaded.size > max_bytes:
        raise ValidationError(f"Image is too large (max {settings.MTX_MAX_IMAGE_MB} MB).")
    try:
        uploaded.seek(0)
        probe = Image.open(uploaded)
        fmt = probe.format
        probe.verify()
        uploaded.seek(0)
        img = Image.open(uploaded)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise ValidationError("Upload a valid image (JPG, PNG, WebP or GIF).")
    if fmt not in ALLOWED_FORMATS:
        raise ValidationError("Unsupported image type. Use JPG, PNG, WebP or GIF.")

    img = ImageOps.exif_transpose(img)
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    dim = settings.MTX_IMAGE_MAX_DIMENSION
    img.thumbnail((dim, dim), Image.Resampling.LANCZOS)

    target_bytes = settings.MTX_IMAGE_TARGET_MAX_KB * 1024
    best = _encode_webp(img, quality=82)

    if len(best) > target_bytes:
        for q in (72, 62, 52, 42, 34, 26):
            best = _encode_webp(img, quality=q)
            if len(best) <= target_bytes:
                break

    while len(best) > target_bytes and max(img.size) > 120:
        new_w = max(120, int(img.width * 0.78))
        new_h = max(120, int(img.height * 0.78))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        for q in (65, 50, 38, 28, 20):
            best = _encode_webp(img, quality=q)
            if len(best) <= target_bytes:
                break

    return ContentFile(best, name=f"{uuid.uuid4().hex}.webp")
