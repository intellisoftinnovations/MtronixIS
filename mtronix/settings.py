"""
Django settings for Mtronix IS.

All configuration that differs between environments is read from environment
variables (see .env.example). Defaults are safe for local development only.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me-in-production-0123456789")
if not DEBUG and SECRET_KEY.startswith("dev-only"):
    raise RuntimeError("Set DJANGO_SECRET_KEY in production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "*") if DEBUG else env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "accounts.apps.AccountsConfig",
    "inventory.apps.InventoryConfig",
    "audit.apps.AuditConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "accounts.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "accounts.middleware.SessionGuardMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mtronix.urls"
WSGI_APPLICATION = "mtronix.wsgi.application"
ASGI_APPLICATION = "mtronix.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "inventory.context_processors.mtronix",
            ],
            "builtins": ["inventory.templatetags.mtx"],
        },
    },
]

# --------------------------------------------------------------------------
# Database — SQLite by default, PostgreSQL when POSTGRES_DB is set.
# --------------------------------------------------------------------------
if env("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER", "postgres"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
            "ATOMIC_REQUESTS": False,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {"timeout": 20},
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Authentication & passwords
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "inventory:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "accounts.validators.ComplexityValidator"},
    {"NAME": "accounts.validators.PwnedPasswordValidator"},
]

# Invite / password-set links stay valid for 3 days.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 3

# --------------------------------------------------------------------------
# Sessions & cookies (HttpOnly, SameSite, Secure in production)
# --------------------------------------------------------------------------
# Persistent sessions: keep logged in across device restarts until explicit logout
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = int(env("MTX_SESSION_COOKIE_AGE", str(10 * 365 * 24 * 60 * 60)))  # 10 years
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"  # Lax so QR links opened from a camera app keep the session
SESSION_COOKIE_NAME = "mtx_session"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "mtx_csrf"
CSRF_FAILURE_VIEW = "django.views.csrf.csrf_failure"

# --------------------------------------------------------------------------
# Security headers
# --------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
    if env_bool("DJANGO_BEHIND_PROXY", True):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

MTX_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' blob: mediastream:; "
    "connect-src 'self'; "
    "worker-src 'self'; "
    "manifest-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# --------------------------------------------------------------------------
# Cache (used for rate limiting). Use Redis/Memcached when running >1 process.
# --------------------------------------------------------------------------
if env("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": env("REDIS_URL")}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "mtronix"}}

# --------------------------------------------------------------------------
# I18N / time — store UTC, display Asia/Dhaka
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static, media & private files
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MTX_MEDIA_ROOT", BASE_DIR / "media"))
# PDF receipts are NOT web-served; they are streamed through an authenticated view.
PRIVATE_MEDIA_ROOT = Path(env("MTX_PRIVATE_MEDIA_ROOT", BASE_DIR / "private"))

FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o644

# --------------------------------------------------------------------------
# Email (invites). Console backend for development.
# --------------------------------------------------------------------------
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "25"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Mtronix IS <no-reply@mtronix.local>")

# --------------------------------------------------------------------------
# Mtronix IS application settings
# --------------------------------------------------------------------------
MTX_SYSTEM_NAME = "Mtronix IS"
MTX_COMPANY_NAME = env("MTX_COMPANY_NAME", "Mtronix")
MTX_SITE_URL = env("MTX_SITE_URL", "")  # e.g. https://inventory.mtronix.com — used in QR codes / PDFs
MTX_LOGIN_MAX_ATTEMPTS = int(env("MTX_LOGIN_MAX_ATTEMPTS", "5"))  # per email
MTX_LOGIN_MAX_ATTEMPTS_IP = int(env("MTX_LOGIN_MAX_ATTEMPTS_IP", "20"))  # per IP
MTX_LOCKOUT_MINUTES = int(env("MTX_LOCKOUT_MINUTES", "15"))
MTX_PUBLIC_QR_RATE = int(env("MTX_PUBLIC_QR_RATE", "60"))  # requests per minute per IP
MTX_TRUST_X_FORWARDED_FOR = env_bool("MTX_TRUST_X_FORWARDED_FOR", False)
MTX_PWNED_PASSWORD_CHECK = env_bool("MTX_PWNED_PASSWORD_CHECK", False)  # HIBP k-anonymity API
MTX_MAX_IMAGE_MB = int(env("MTX_MAX_IMAGE_MB", "5"))
MTX_IMAGE_MAX_DIMENSION = 1200
MTX_IMAGE_TARGET_MAX_KB = int(env("MTX_IMAGE_TARGET_MAX_KB", "100"))
MTX_WEEK_START = int(env("MTX_WEEK_START", "5"))  # 0=Mon … 5=Sat (Bangladesh)
MTX_DEFAULT_LOW_STOCK = 5

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}

