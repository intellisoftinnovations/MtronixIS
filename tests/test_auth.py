import pyotp
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts import security

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user_and_argon2_hash(self):
        user = User.objects.create_user(
            email="manager@mtronix.local",
            password="StrongPassword123!",
            name="Test Manager",
            role=User.Role.MANAGER,
        )
        self.assertEqual(user.email, "manager@mtronix.local")
        self.assertTrue(user.check_password("StrongPassword123!"))
        self.assertTrue(user.password.startswith("argon2"))
        self.assertFalse(user.is_admin)
        self.assertTrue(user.is_manager)

    def test_admin_mandatory_2fa_rule(self):
        admin = User.objects.create_user(
            email="admin@mtronix.local",
            password="StrongPassword123!",
            name="Test Admin",
            role=User.Role.ADMIN,
        )
        self.assertTrue(admin.is_admin)
        # Without totp_enabled, admin needs setup
        self.assertTrue(admin.needs_2fa_setup)

        # Once enabled, 2FA setup is complete
        admin.totp_secret = pyotp.random_base32()
        admin.totp_enabled = True
        admin.save()
        self.assertFalse(admin.needs_2fa_setup)

    def test_totp_generation_and_validation(self):
        secret = pyotp.random_base32()
        user = User.objects.create_user(
            email="totptest@mtronix.local",
            password="Password123!",
            totp_secret=secret,
            totp_enabled=True,
        )
        totp = pyotp.TOTP(secret)
        code = totp.now()
        # verify using User.verify_totp
        self.assertTrue(user.verify_totp(code))
        # Replay protection blocks reusing the same code
        self.assertFalse(user.verify_totp(code))
        # Invalid code fails
        self.assertFalse(user.verify_totp("000000"))

    def test_session_version_invalidation(self):
        user = User.objects.create_user(
            email="sessiontest@mtronix.local",
            password="Password123!",
            role=User.Role.MANAGER,
        )
        old_version = user.session_version
        user.session_version += 1
        user.save()
        user.refresh_from_db()
        self.assertNotEqual(user.session_version, old_version)


class SecurityRateLimitTests(TestCase):
    def test_rate_limiting(self):
        key = "test_rate_limit_key"
        security.reset(key)
        self.assertEqual(security.hit(key, window_seconds=10), 1)
        self.assertEqual(security.hit(key, window_seconds=10), 2)
        self.assertTrue(security.is_limited(key, limit=2))
        security.reset(key)
        self.assertFalse(security.is_limited(key, limit=2))


class SessionPersistenceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="persistent@mtronix.local",
            password="SecurePassword123!",
            name="Persistent User",
            role=User.Role.MANAGER,
        )

    def test_session_settings_configured_for_permanent_login(self):
        # Must not expire when browser closes
        self.assertFalse(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        # Cookie age must be at least 1 year (31,536,000s)
        self.assertGreaterEqual(settings.SESSION_COOKIE_AGE, 31536000)

    def test_login_persists_session_permanently(self):
        resp = self.client.post(
            reverse("accounts:login"),
            {"email": "persistent@mtronix.local", "password": "SecurePassword123!", "remember_me": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        # Check session expiry age
        session = self.client.session
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertGreaterEqual(session.get_expiry_age(), 31536000)

    def test_explicit_logout_terminates_session(self):
        self.client.post(
            reverse("accounts:login"),
            {"email": "persistent@mtronix.local", "password": "SecurePassword123!", "remember_me": "on"},
        )
        # Dashboard is accessible
        dash_resp = self.client.get(reverse("inventory:dashboard"))
        self.assertEqual(dash_resp.status_code, 200)

        # Explicit logout
        logout_resp = self.client.post(reverse("accounts:logout"))
        self.assertEqual(logout_resp.status_code, 302)

        # After logout, accessing dashboard redirects to login
        dash_after = self.client.get(reverse("inventory:dashboard"))
        self.assertEqual(dash_after.status_code, 302)
        self.assertIn(reverse("accounts:login"), dash_after.headers["Location"])

    def test_admin_force_logout_invalidates_persistent_session(self):
        self.client.post(
            reverse("accounts:login"),
            {"email": "persistent@mtronix.local", "password": "SecurePassword123!", "remember_me": "on"},
        )
        self.assertEqual(self.client.get(reverse("inventory:dashboard")).status_code, 200)

        # Admin bumps session_version to force logout this user
        self.user.session_version += 1
        self.user.save()

        # Next request must be terminated by SessionGuardMiddleware
        resp = self.client.get(reverse("inventory:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp.headers["Location"])

    def test_logout_rejects_get_request(self):
        self.client.post(
            reverse("accounts:login"),
            {"email": "persistent@mtronix.local", "password": "SecurePassword123!"},
        )
        resp = self.client.get(reverse("accounts:logout"))
        self.assertEqual(resp.status_code, 405)

    def test_admin_user_edit_logs_role_change_and_bumps_session_version(self):
        from audit.models import ActivityLog

        admin = User.objects.create_user(
            email="superadmin@mtronix.local",
            password="AdminPassword123!",
            name="Super Admin",
            role=User.Role.ADMIN,
            totp_secret=pyotp.random_base32(),
            totp_enabled=True,
        )
        self.client.force_login(admin)
        session = self.client.session
        session["session_version"] = admin.session_version
        session.save()

        old_version = self.user.session_version
        resp = self.client.post(
            reverse("accounts:user_edit", args=[self.user.pk]),
            {
                "name": self.user.name,
                "phone": "",
                "role": User.Role.ADMIN,
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.ADMIN)
        self.assertEqual(self.user.session_version, old_version + 1)
        self.assertTrue(
            ActivityLog.objects.filter(
                action=ActivityLog.Action.ROLE_CHANGE,
                entity_id=str(self.user.pk),
            ).exists()
        )
