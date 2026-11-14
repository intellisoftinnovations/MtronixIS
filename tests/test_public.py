from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from inventory.models import Inventory, Product, Carton, StockMovement
from inventory.services import record_movement

User = get_user_model()


class PublicEndpointsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="manager@mtronix.local",
            password="Password123!",
            name="Warehouse Manager",
            role=User.Role.MANAGER,
        )
        self.inventory = Inventory.objects.create(
            name="Confidential Vault Warehouse",
            code="VAULT-99",
            location="Secret Location",
        )
        self.inventory.managers.add(self.user)
        self.product = Product.objects.create(
            name="Lithium Battery Pack 48V",
            sku="MTR-LITH-48V",
        )
        self.carton = Carton.objects.create(
            inventory=self.inventory,
            product=self.product,
            carton_code="CTN-VAULT-01",
            qty_per_carton=4,
            carton_count=150,
            status=Carton.Status.ACTIVE,
        )
        self.movement, _ = record_movement(
            user=self.user,
            carton_id=self.carton.pk,
            movement_type=StockMovement.Type.IN,
            cartons=20,
            note="Internal transfer confidential",
            reference="REF-SEC-001",
        )

    def test_public_qr_does_not_leak_warehouse_or_stock(self):
        url = reverse("inventory:public_qr", args=[self.product.qr_token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        # Product name must be shown
        self.assertIn("Lithium Battery Pack 48V", content)
        # Warehouse name and stock quantities MUST NOT be revealed to public
        self.assertNotIn("Confidential Vault Warehouse", content)
        self.assertNotIn("VAULT-99", content)
        self.assertNotIn("150 cartons", content)

    def test_public_qr_invalid_token(self):
        url = reverse("inventory:public_qr", args=["non-existent-token-12345"])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_public_receipt_verification(self):
        url = reverse("inventory:movement_verify", args=[self.movement.verify_token])
        # Unauthenticated request
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        # Receipt details verified
        self.assertIn("Verified Authentic Receipt", content)
        self.assertIn(self.movement.receipt_no, content)
        self.assertIn("Lithium Battery Pack 48V", content)
        self.assertIn("MTR-LITH-48V", content)
        self.assertIn("Staff Login", content)

    def test_authenticated_receipt_verification_has_system_link(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["session_version"] = self.user.session_version
        session.save()
        url = reverse("inventory:movement_verify", args=[self.movement.verify_token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn("Open in System", content)
