import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from inventory.models import Inventory, Product, Carton, StockMovement
from inventory.services import StockError, record_movement

User = get_user_model()


class InventoryServiceTests(TestCase):
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
            low_stock_threshold=10,
        )
        # Assign manager to this inventory
        self.inventory.managers.add(self.user)

        self.product = Product.objects.create(
            name="LED Monitor 24-inch",
            sku="MTR-LED-24",
        )
        self.carton = Carton.objects.create(
            inventory=self.inventory,
            product=self.product,
            carton_code="CTN-001",
            qty_per_carton=5,
            carton_count=20,
            status=Carton.Status.ACTIVE,
        )

    def test_carton_is_low_stock_and_closed_status(self):
        # Initial: count=20, threshold=10 -> not low
        self.assertFalse(self.carton.is_low)

        # When count < threshold -> low
        self.carton.carton_count = 5
        self.carton.save()
        self.assertTrue(self.carton.is_low)

        # When status is CLOSED, is_low must be False
        self.carton.status = Carton.Status.CLOSED
        self.carton.save()
        self.assertFalse(self.carton.is_low)

    def test_soft_delete_product(self):
        self.product.is_deleted = True
        self.product.deleted_at = timezone.now()
        self.product.save()

        self.assertTrue(self.product.is_deleted)
        self.assertFalse(Product.objects.alive().filter(pk=self.product.pk).exists())
        self.assertTrue(Product.objects.deleted().filter(pk=self.product.pk).exists())

    def test_stock_in_movement(self):
        initial_cartons = self.carton.carton_count
        mv, created = record_movement(
            user=self.user,
            carton_id=self.carton.pk,
            movement_type=StockMovement.Type.IN,
            cartons=5,
            note="Restock batch 1",
        )
        self.assertTrue(created)
        self.assertEqual(mv.type, StockMovement.Type.IN)
        self.assertEqual(mv.cartons_moved, 5)
        self.assertEqual(mv.cartons_before, initial_cartons)
        self.assertEqual(mv.cartons_after, initial_cartons + 5)
        self.assertEqual(mv.qty_moved, 5 * self.carton.qty_per_carton)

        self.carton.refresh_from_db()
        self.assertEqual(self.carton.carton_count, initial_cartons + 5)

    def test_stock_out_insufficient_stock_error(self):
        # Attempt to stock out 50 cartons when only 20 are available
        with self.assertRaises(StockError):
            record_movement(
                user=self.user,
                carton_id=self.carton.pk,
                movement_type=StockMovement.Type.OUT,
                cartons=50,
            )

    def test_idempotency_prevents_duplicate_movement(self):
        key = uuid.uuid4()
        mv1, created1 = record_movement(
            user=self.user,
            carton_id=self.carton.pk,
            movement_type=StockMovement.Type.OUT,
            cartons=2,
            idempotency_key=key,
        )
        self.assertTrue(created1)
        self.carton.refresh_from_db()
        self.assertEqual(self.carton.carton_count, 18)

        # Submitting with the exact same idempotency key must not subtract again
        mv2, created2 = record_movement(
            user=self.user,
            carton_id=self.carton.pk,
            movement_type=StockMovement.Type.OUT,
            cartons=2,
            idempotency_key=key,
        )
        self.assertFalse(created2)
        self.assertEqual(mv1.pk, mv2.pk)
        self.carton.refresh_from_db()
        self.assertEqual(self.carton.carton_count, 18)

    def test_large_image_resized_under_100kb(self):
        import io
        import os
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from inventory.images import process_product_image

        # Generate a high-entropy 1000x1000 JPEG (> 100 KB, < 5 MB)
        raw_rgb = os.urandom(1000 * 1000 * 3)
        big_img = Image.frombytes("RGB", (1000, 1000), raw_rgb)
        buf = io.BytesIO()
        big_img.save(buf, format="JPEG", quality=92)
        uploaded = SimpleUploadedFile("big.jpg", buf.getvalue(), content_type="image/jpeg")
        self.assertGreater(uploaded.size, 100 * 1024)

        processed = process_product_image(uploaded)
        self.assertLessEqual(processed.size, 100 * 1024)
        self.assertTrue(processed.name.endswith(".webp"))

        out_img = Image.open(io.BytesIO(processed.read()))
        self.assertEqual(out_img.format, "WEBP")

    def test_small_image_stays_under_100kb(self):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from inventory.images import process_product_image

        small_img = Image.new("RGB", (400, 400), color=(34, 51, 59))
        buf = io.BytesIO()
        small_img.save(buf, format="JPEG", quality=85)
        uploaded = SimpleUploadedFile("small.jpg", buf.getvalue(), content_type="image/jpeg")

        processed = process_product_image(uploaded)
        self.assertLessEqual(processed.size, 100 * 1024)
        out_img = Image.open(io.BytesIO(processed.read()))
        self.assertEqual(out_img.size, (400, 400))

    def test_auto_generate_sku_when_blank(self):
        from inventory.forms import ProductForm

        form = ProductForm(data={"name": "Solar Inverter", "sku": "", "description": ""})
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertTrue(product.sku.startswith("SOL-"))
        self.assertGreaterEqual(len(product.sku), 9)

        # Duplicate manual SKU is still rejected
        dup_form = ProductForm(data={"name": "Another", "sku": product.sku})
        self.assertFalse(dup_form.is_valid())
        self.assertIn("sku", dup_form.errors)

    def test_carton_edit_post_succeeds_and_allows_product_inventory_edit(self):
        from django.urls import reverse

        other_product = Product.objects.create(name="Power Supply 12V", sku="MTR-PSU-12")
        self.client.force_login(self.user)
        session = self.client.session
        session["session_version"] = self.user.session_version
        session.save()

        resp = self.client.post(
            reverse("inventory:carton_edit", args=[self.carton.pk]),
            {
                "product": other_product.pk,
                "inventory": self.inventory.pk,
                "carton_code": "CTN-01-EDITED",
                "qty_per_carton": 15,
                "status": Carton.Status.ON_HOLD,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.carton.refresh_from_db()
        self.assertEqual(self.carton.carton_code, "CTN-01-EDITED")
        self.assertEqual(self.carton.qty_per_carton, 15)
        self.assertEqual(self.carton.status, Carton.Status.ON_HOLD)
        self.assertEqual(self.carton.product_id, other_product.pk)
        self.assertEqual(self.carton.inventory_id, self.inventory.pk)
        # Disabled carton_count remains unchanged
        self.assertEqual(self.carton.carton_count, 20)

    def test_closed_on_hold_and_damaged_carton_status_blocks_movements(self):
        self.carton.status = Carton.Status.CLOSED
        self.carton.save(update_fields=["status"])
        with self.assertRaises(StockError):
            record_movement(user=self.user, carton_id=self.carton.pk, movement_type=StockMovement.Type.IN, cartons=1)
        with self.assertRaises(StockError):
            record_movement(user=self.user, carton_id=self.carton.pk, movement_type=StockMovement.Type.OUT, cartons=1)

        for blocked_out_status in (Carton.Status.ON_HOLD, Carton.Status.DAMAGED):
            self.carton.status = blocked_out_status
            self.carton.save(update_fields=["status"])
            with self.assertRaises(StockError):
                record_movement(user=self.user, carton_id=self.carton.pk, movement_type=StockMovement.Type.OUT, cartons=1)
