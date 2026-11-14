from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class SecurityHeadersMiddleware:
    """Adds CSP and Permissions-Policy headers to every response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", settings.MTX_CSP)
        response.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=(), payment=()")
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            response.setdefault("Cache-Control", "no-store, private")
        return response


class SessionGuardMiddleware:
    """Enforces force-logout (session_version) and mandatory admin 2FA."""

    ALLOWED_PREFIXES_WITHOUT_2FA = ("/account/2fa/setup/", "/logout/", "/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            if request.session.get("session_version") != user.session_version:
                logout(request)
                messages.warning(request, "Your session has ended. Please sign in again.")
                return redirect(settings.LOGIN_URL)
            if user.needs_2fa_setup and not request.path.startswith(self.ALLOWED_PREFIXES_WITHOUT_2FA):
                messages.info(request, "Two-factor authentication is mandatory for Admin accounts. Set it up to continue.")
                return redirect(reverse("accounts:2fa_setup"))
        return self.get_response(request)
