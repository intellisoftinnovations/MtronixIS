from django.contrib.auth import get_user_model
from django.test import TestCase

from audit.models import ActivityLog, ImmutableLogError

User = get_user_model()


class AuditLogImmutabilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="auditor@mtronix.local",
            password="Password123!",
            name="Audit User",
            role=User.Role.ADMIN,
        )
        self.log = ActivityLog.objects.create(
            user=self.user,
            user_display="Audit User (admin)",
            action=ActivityLog.Action.LOGIN,
            entity_type="User",
            entity_id=str(self.user.pk),
            entity_repr=self.user.email,
        )

    def test_log_instance_cannot_be_updated(self):
        self.log.note = "Attempting modification"
        with self.assertRaises(ImmutableLogError):
            self.log.save()

    def test_log_instance_cannot_be_deleted(self):
        with self.assertRaises(ImmutableLogError):
            self.log.delete()

    def test_queryset_update_blocked(self):
        with self.assertRaises(ImmutableLogError):
            ActivityLog.objects.filter(pk=self.log.pk).update(note="Blocked update")

    def test_queryset_delete_blocked(self):
        with self.assertRaises(ImmutableLogError):
            ActivityLog.objects.filter(pk=self.log.pk).delete()

