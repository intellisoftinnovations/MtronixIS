from django.conf import settings
from django.db import models
from django.utils import timezone


class ImmutableLogError(Exception):
    pass


class ActivityLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableLogError("Activity logs cannot be edited.")

    def delete(self):
        raise ImmutableLogError("Activity logs cannot be deleted.")

    def bulk_update(self, *args, **kwargs):
        raise ImmutableLogError("Activity logs cannot be edited.")


class ActivityLog(models.Model):
    """Append-only audit trail. Updates/deletes are blocked in Python AND by DB triggers."""

    class Action(models.TextChoices):
        STOCK_IN = "STOCK_IN", "Stock In"
        STOCK_OUT = "STOCK_OUT", "Stock Out"
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Edit"
        DELETE = "DELETE", "Delete"
        RESTORE = "RESTORE", "Restore"
        ARCHIVE = "ARCHIVE", "Archive"
        UNARCHIVE = "UNARCHIVE", "Unarchive"
        LOGIN = "LOGIN", "Login"
        LOGIN_FAILED = "LOGIN_FAILED", "Login failed"
        LOGOUT = "LOGOUT", "Logout"
        ROLE_CHANGE = "ROLE_CHANGE", "Role change"
        USER_INVITE = "USER_INVITE", "User invite"
        USER_DISABLE = "USER_DISABLE", "User disabled"
        USER_ENABLE = "USER_ENABLE", "User enabled"
        FORCE_LOGOUT = "FORCE_LOGOUT", "Force logout"
        PASSWORD_CHANGE = "PASSWORD_CHANGE", "Password change"
        PASSWORD_SET = "PASSWORD_SET", "Password set"
        TWOFA_ENABLE = "TWOFA_ENABLE", "2FA enabled"
        TWOFA_DISABLE = "TWOFA_DISABLE", "2FA disabled"
        TWOFA_RESET = "TWOFA_RESET", "2FA reset"
        QR_REGENERATE = "QR_REGENERATE", "QR regenerate"
        PDF_REGENERATE = "PDF_REGENERATE", "PDF regenerate"
        EXPORT = "EXPORT", "Export"

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    user_display = models.CharField(max_length=200, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)

    entity_type = models.CharField(max_length=40, blank=True)
    entity_id = models.CharField(max_length=40, blank=True)
    entity_repr = models.CharField(max_length=255, blank=True)

    product = models.ForeignKey("inventory.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    inventory = models.ForeignKey("inventory.Inventory", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    movement = models.ForeignKey("inventory.StockMovement", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    quantity = models.IntegerField(null=True, blank=True)
    before = models.IntegerField(null=True, blank=True)
    after = models.IntegerField(null=True, blank=True)
    note = models.TextField(blank=True)

    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)

    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    objects = ActivityLogQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["inventory", "created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.user_display} {self.action}"

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise ImmutableLogError("Activity logs cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableLogError("Activity logs cannot be deleted.")

    @property
    def badge(self):
        a = self.Action
        if self.action == a.STOCK_IN:
            return "success"
        if self.action == a.STOCK_OUT:
            return "danger"
        if self.action in (a.DELETE, a.USER_DISABLE, a.LOGIN_FAILED, a.ARCHIVE):
            return "danger-outline"
        if self.action in (a.UPDATE, a.ROLE_CHANGE, a.RESTORE, a.UNARCHIVE):
            return "info"
        if self.action == a.CREATE:
            return "accent"
        return "muted"

    @property
    def changes(self):
        """List of (field, old, new) for edit entries."""
        old, new = self.old_value or {}, self.new_value or {}
        if not isinstance(old, dict) or not isinstance(new, dict):
            return []
        keys = list(dict.fromkeys(list(old.keys()) + list(new.keys())))
        return [(k, old.get(k), new.get(k)) for k in keys if old.get(k) != new.get(k)]

