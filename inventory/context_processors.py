import os

from django.conf import settings


def _css_version():
    """Cache-busting token: the stylesheet's last-modified time.

    Browsers (especially mobile) cache style.css aggressively; appending
    ?v=<mtime> forces a fresh download whenever the file changes.
    """
    try:
        path = os.path.join(settings.BASE_DIR, "static", "css", "style.css")
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "1"


def mtronix(request):
    return {
        "SYSTEM_NAME": settings.MTX_SYSTEM_NAME,
        "COMPANY_NAME": settings.MTX_COMPANY_NAME,
        "IDLE_TIMEOUT_SECONDS": settings.SESSION_COOKIE_AGE,
        "CSS_VERSION": _css_version(),
    }
