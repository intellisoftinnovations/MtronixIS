import hashlib
import logging
import re
import urllib.request

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class ComplexityValidator:
    """Require letters and at least one digit or symbol."""

    def validate(self, password, user=None):
        if not re.search(r"[A-Za-z]", password) or not re.search(r"[^A-Za-z]", password):
            raise ValidationError(
                "Password must contain letters and at least one number or symbol.",
                code="password_too_simple",
            )

    def get_help_text(self):
        return "Use letters plus at least one number or symbol."


class PwnedPasswordValidator:
    """Reject passwords found in known breaches (HaveIBeenPwned k-anonymity API).

    Only the first 5 chars of the SHA-1 hash leave the server. Enabled with
    MTX_PWNED_PASSWORD_CHECK=true; fails open if the API is unreachable.
    """

    def validate(self, password, user=None):
        if not getattr(settings, "MTX_PWNED_PASSWORD_CHECK", False):
            return
        digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        try:
            req = urllib.request.Request(
                f"https://api.pwnedpasswords.com/range/{prefix}",
                headers={"User-Agent": "Mtronix-IS", "Add-Padding": "true"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = resp.read().decode("utf-8")
        except Exception:  # pragma: no cover - network dependent
            logger.warning("Pwned password check unavailable; skipping.")
            return
        for line in body.splitlines():
            h, _, cnt = line.partition(":")
            if h.strip() == suffix and int(cnt or 0) > 0:
                raise ValidationError(
                    "This password has appeared in a data breach. Please choose another.",
                    code="password_pwned",
                )

    def get_help_text(self):
        return "Your password must not appear in known data breaches."

