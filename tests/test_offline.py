import io
import json
import uuid

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from inventory.models import Carton, Inventory, Product, StockMovement

User = get_user_model()


class OfflinePWATests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            email="offline.mgr@mtronix.local",
            password="Password123!",
            name="Offline Manager",
            role=User.Role.MANAGER,
        )
        self.inv_allowed = Inventory.objects.create(name="Warehouse A", code="WH-A")
        self.inv_allowed.managers.add(self.manager)
        self.inv_other = Inventory.objects.create(name="Warehouse B", code="WH-B")

        self.product = Product.objects.create(name="Relay Module", sku="REL-10001")
        self.carton_allowed = Carton.objects.create(
            inventory=self.inv_allowed,
            product=self.product,
            carton_code="CTN-A1",
            qty_per_carton=10,
            carton_count=15,
            status=Carton.Status.ACTIVE,
        )
        self.carton_other = Carton.objects.create(
            inventory=self.inv_other,
            product=self.product,
            carton_code="CTN-B1",
            qty_per_carton=10,
            carton_count=5,
            status=Carton.Status.ACTIVE,
        )

    def _login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["session_version"] = user.session_version
        session.save()

    def test_pwa_manifest_sw_and_offline_page(self):
        resp_m = self.client.get(reverse("inventory:manifest_json"))
        self.assertEqual(resp_m.status_code, 200)
        self.assertIn("application/manifest+json", resp_m["Content-Type"])
        data = resp_m.json()
        self.assertEqual(data["display"], "standalone")
        self.assertGreaterEqual(len(data["icons"]), 2)

        resp_sw = self.client.get(reverse("inventory:service_worker"))
        self.assertEqual(resp_sw.status_code, 200)
        self.assertEqual(resp_sw["Service-Worker-Allowed"], "/")
        self.assertIn(b"PRECACHE_URLS", resp_sw.content)

        resp_off = self.client.get(reverse("inventory:offline_page"))
        self.assertEqual(resp_off.status_code, 200)

    def test_offline_snapshot_respects_manager_permissions(self):
        self._login(self.manager)
        resp = self.client.get(reverse("inventory:offline_snapshot"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        inv_ids = [i["id"] for i in data["inventories"]]
        carton_ids = [c["id"] for c in data["cartons"]]
        self.assertIn(self.inv_allowed.pk, inv_ids)
        self.assertNotIn(self.inv_other.pk, inv_ids)
        self.assertIn(self.carton_allowed.pk, carton_ids)
        self.assertNotIn(self.carton_other.pk, carton_ids)

    def test_offline_sync_stock_movement_is_idempotent(self):
        self._login(self.manager)
        idem = str(uuid.uuid4())
        payload = {
            "items": [
                {
                    "id": "client-1",
                    "kind": "stock_movement",
                    "carton_id": self.carton_allowed.pk,
                    "type": "IN",
                    "cartons": 4,
                    "reference": "OFF-REF-1",
                    "note": "Queued offline",
                    "idempotency_key": idem,
                }
            ]
        }

        resp1 = self.client.post(
            reverse("inventory:offline_sync"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp1.status_code, 200)
        r1 = resp1.json()["results"][0]
        self.assertEqual(r1["status"], "ok")
        self.assertTrue(r1["created"])
        self.assertEqual(r1["cartons_after"], 19)

        # Retry with the same idempotency key must not double-count
        resp2 = self.client.post(
            reverse("inventory:offline_sync"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 200)
        r2 = resp2.json()["results"][0]
        self.assertEqual(r2["status"], "ok")
        self.assertFalse(r2["created"])
        self.carton_allowed.refresh_from_db()
        self.assertEqual(self.carton_allowed.carton_count, 19)
        self.assertEqual(StockMovement.objects.filter(carton=self.carton_allowed).count(), 1)

    def test_offline_sync_product_create_with_photo(self):
        self._login(self.manager)
        buf = io.BytesIO()
        Image.new("RGB", (600, 400), (40, 90, 120)).save(buf, format="JPEG")
        upload = SimpleUploadedFile("offline-cam.jpg", buf.getvalue(), content_type="image/jpeg")

        payload = {
            "id": "client-prod-1",
            "kind": "product_create",
            "name": "Offline Sensor Board",
            "sku": "",
            "description": "Captured while offline",
        }
        resp = self.client.post(
            reverse("inventory:offline_sync"),
            data={"payload": json.dumps(payload), "image": upload},
        )
        self.assertEqual(resp.status_code, 200)
        r = resp.json()["results"][0]
        self.assertEqual(r["status"], "ok")
        prod = Product.objects.get(pk=r["product_id"])
        self.assertEqual(prod.name, "Offline Sensor Board")
        self.assertTrue(prod.sku.startswith("OFF-"))
        self.assertTrue(bool(prod.image))
        self.assertLessEqual(prod.image.size, 100 * 1024)
