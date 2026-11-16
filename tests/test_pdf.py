import datetime
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from inventory.models import Inventory, Product, Carton, StockMovement
from inventory.pdf import build_receipt_pdf, generate_receipt_pdf
from inventory.services import record_movement
from inventory.timeutils import DHAKA, format_bd

User = get_user_model()


class PDFReceiptTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="manager@mtronix.local",
            password="Password123!",
            name="Warehouse Manager",
            role=User.Role.MANAGER,
        )
        self.inventory = Inventory.objects.create(
            name="Main Warehouse",
            code="MW-01",
            location="Dhaka",
        )
        self.inventory.managers.add(self.user)
        self.product = Product.objects.create(
            name="Solar Inverter 5kW",
            sku="MTR-INV-5KW",
        )
        self.carton = Carton.objects.create(
            inventory=self.inventory,
            product=self.product,
            carton_code="CTN-INV-01",
            qty_per_carton=2,
            carton_count=10,
            status=Carton.Status.ACTIVE,
        )

    def test_bangladesh_time_formatting(self):
        # 2026-11-12 10:00:00 UTC -> 2026-11-12 16:00:00 BST (UTC+6)
        utc_dt = datetime.datetime(2026, 11, 12, 10, 0, 0, tzinfo=datetime.timezone.utc)
        bd_str = format_bd(utc_dt)
        self.assertIn("12 Nov 2026", bd_str)
        self.assertIn("04:00 PM", bd_str)
        self.assertIn("BST", bd_str)

    def test_pdf_generation(self):
        from django.urls import reverse

        mv, _ = record_movement(
            user=self.user,
            carton_id=self.carton.pk,
            movement_type=StockMovement.Type.IN,
            cartons=4,
            note="Regular replenishment",
        )
        mv.refresh_from_db()
        # Receipt PDFs are generated on demand and must not be stored on disk
        self.assertFalse(bool(mv.pdf))

        pdf_bytes = build_receipt_pdf(mv)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1000)

        self.client.force_login(self.user)
        session = self.client.session
        session["session_version"] = self.user.session_version
        session.save()

        resp = self.client.get(reverse("inventory:movement_pdf", args=[mv.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        body = b"".join(resp.streaming_content)
        self.assertTrue(body.startswith(b"%PDF-"))
        mv.refresh_from_db()
        self.assertFalse(bool(mv.pdf))

    def test_labels_print_html_and_pdf(self):
        from django.urls import reverse

        self.client.force_login(self.user)
        session = self.client.session
        session["session_version"] = self.user.session_version
        session.save()

        url = reverse("inventory:labels_print")
        resp_html = self.client.get(f"{url}?c={self.carton.pk}&p={self.product.pk}&copies=2")
        self.assertEqual(resp_html.status_code, 200)
        self.assertContains(resp_html, "CTN-INV-01")
        self.assertContains(resp_html, "Label Printer (Roll)")

        resp_pdf = self.client.get(f"{url}?c={self.carton.pk}&p={self.product.pk}&copies=2&format=pdf&download=1")
        self.assertEqual(resp_pdf.status_code, 200)
        self.assertEqual(resp_pdf["Content-Type"], "application/pdf")
        self.assertTrue(resp_pdf.content.startswith(b"%PDF-"))
        self.assertIn("attachment", resp_pdf["Content-Disposition"])

        # Thermal label printer roll mode with 2 columns and 100 copies
        resp_roll_html = self.client.get(f"{url}?c={self.carton.pk}&mode=roll&cols=2&size=50x30&copies=100")
        self.assertEqual(resp_roll_html.status_code, 200)
        self.assertContains(resp_roll_html, "100 labels")

        resp_roll_pdf = self.client.get(f"{url}?c={self.carton.pk}&mode=roll&cols=2&size=50x30&copies=100&format=pdf")
        self.assertEqual(resp_roll_pdf.status_code, 200)
        self.assertEqual(resp_roll_pdf["Content-Type"], "application/pdf")
        self.assertTrue(resp_roll_pdf.content.startswith(b"%PDF-"))
