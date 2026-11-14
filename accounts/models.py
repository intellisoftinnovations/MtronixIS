import hmac
import time

import pyotp
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
            user.password_set_at = timezone.now()
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("role", User.Role.MANAGER)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra["role"] = User.Role.ADMIN
        extra["is_staff"] = True
        extra["is_superuser"] = True
        extra.setdefault("name", "Administrator")
        return self._create_user(email, password, **extra)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"

    email = models.EmailField("email", unique=True)
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MANAGER)

    totp_secret = models.CharField(max_length=64, blank=True)
    totp_enabled = models.BooleanField(default=False)
    totp_last_counter = models.BigIntegerField(default=0)  # replay protection

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    session_version = models.PositiveIntegerField(default=1)  # bump → force logout everywhere

    date_joined = models.DateTimeField(default=timezone.now)
    invited_at = models.DateTimeField(null=True, blank=True)
    password_set_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["name", "email"]

    def __str__(self):
        return self.name or self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)

    # ---- roles -----------------------------------------------------------
    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

    def get_full_name(self):
        return self.name or self.email

    def get_short_name(self):
        return (self.name or self.email).split(" ")[0]

    @property
    def initials(self):
        parts = (self.name or self.email).split()
        return "".join(p[0] for p in parts[:2]).upper()

    @property
    def needs_2fa_setup(self):
        return self.is_admin and not self.totp_enabled

    @property
    def has_pending_invite(self):
        return not self.has_usable_password()

    # ---- TOTP ------------------------------------------------------------
    def verify_totp(self, code, secret=None):
        """Verify a 6-digit TOTP code (±30s window) and block code reuse."""
        secret = secret or self.totp_secret
        if not secret:
            return False
        code = (code or "").replace(" ", "").strip()
        if len(code) != 6 or not code.isdigit():
            return False
        totp = pyotp.TOTP(secret)
        base = int(time.time()) // totp.interval
        for counter in (base - 1, base, base + 1):
            if counter <= self.totp_last_counter:
                continue
            if hmac.compare_digest(totp.generate_otp(counter), code):
                self.totp_last_counter = counter
                if self.pk:
                    User.objects.filter(pk=self.pk).update(totp_last_counter=counter)
                return True
        return False

    def totp_uri(self, secret):
        return pyotp.TOTP(secret).provisioning_uri(name=self.email, issuer_name="Mtronix IS")


class LoginHistory(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="login_history")
    email_attempted = models.CharField(max_length=254, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    device = models.CharField(max_length=80, blank=True)
    success = models.BooleanField(default=False)
    reason = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "login history"

    def __str__(self):
        return f"{self.email_attempted} {'OK' if self.success else 'FAIL'} {self.created_at:%Y-%m-%d %H:%M}"

