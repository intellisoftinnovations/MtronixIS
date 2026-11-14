"""Small helpers: client IP, device parsing and cache-based rate limiting."""
import re

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    if request is None:
        return None
    if settings.MTX_TRUST_X_FORWARDED_FOR:
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if fwd:
            return fwd.split(",")[0].strip()[:45] or None
    return request.META.get("REMOTE_ADDR") or None


def user_agent(request):
    if request is None:
        return ""
    return (request.META.get("HTTP_USER_AGENT") or "")[:255]


def describe_device(ua):
    ua = ua or ""
    os_name = "Unknown OS"
    for pattern, label in (
        (r"iPhone|iPad", "iOS"),
        (r"Android", "Android"),
        (r"Windows", "Windows"),
        (r"Mac OS X|Macintosh", "macOS"),
        (r"Linux", "Linux"),
    ):
        if re.search(pattern, ua):
            os_name = label
            break
    browser = "Browser"
    for pattern, label in (
        (r"Edg/", "Edge"),
        (r"OPR/|Opera", "Opera"),
        (r"Firefox/", "Firefox"),
        (r"Chrome/", "Chrome"),
        (r"Safari/", "Safari"),
    ):
        if re.search(pattern, ua):
            browser = label
            break
    return f"{browser} on {os_name}"


# ---- rate limiting ----------------------------------------------------------
def _k(key):
    return f"mtx:rl:{key}"


def hit(key, window_seconds):
    """Increment a counter; returns the new count."""
    k = _k(key)
    cache.add(k, 0, timeout=window_seconds)
    try:
        return cache.incr(k)
    except ValueError:  # expired between add and incr
        cache.set(k, 1, timeout=window_seconds)
        return 1


def count(key):
    return cache.get(_k(key), 0)


def reset(key):
    cache.delete(_k(key))


def is_limited(key, limit):
    return count(key) >= limit

