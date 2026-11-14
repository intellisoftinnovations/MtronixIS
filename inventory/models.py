import secrets
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone


def new_token():
    """128-bit unguessable URL-safe token used in QR codes."""
    return secrets.token_urlsafe(16)


def private_storage():
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


def product_image_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webp"
    return f"products/{uuid.uuid4().hex}.{ext}"


def receipt_path(instance, filename):
    local = timezone.localtime(instance.created_at)
    return f"receipts/{local:%Y/%m}/{instance.receipt_no}.pdf"


class AliveQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)


class Inventory(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30, unique=True)
    location = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    low_stock_threshold = models.PositiveIntegerField(
        default=5, help_text="Cartons below this number are flagged as low stock."
    )
    is_archived = models.BooleanField(default=False)
    managers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="managed_inventories")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "inventories"

    def __str__(self):
        return f"{self.name} ({self.code})"

    def get_absolute_url(self):
        return reverse("inventory:inventory_detail", args=[self.pk])


class Product(models.Model):
    name = models.CharField(max_length=150)
    sku = models.CharField("SKU", max_length=60, unique=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to=product_image_path, blank=True)
    qr_token = models.CharField(max_length=40, unique=True, default=new_token, editable=False)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AliveQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} [{self.sku}]"

    def get_absolute_url(self):
        return reverse("inventory:product_detail", args=[self.pk])


class Carton(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ON_HOLD = "hold", "On hold"
        DAMAGED = "damaged", "Damaged"
        CLOSED = "closed", "Closed"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="cartons")
    inventory = models.ForeignKey(Inventory, on_delete=models.PROTECT, related_name="cartons")
    carton_code = models.CharField(max_length=60)
    qty_per_carton = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    carton_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    qr_token = models.CharField(max_length=40, unique=True, default=new_token, editable=False)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AliveQuerySet.as_manager()

    class Meta:
        ordering = ["inventory__name", "product__name", "carton_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["inventory", "carton_code"],
                condition=Q(is_deleted=False),
                name="uniq_alive_carton_code_per_inventory",
            ),
            models.CheckConstraint(check=Q(carton_count__gte=0), name="carton_count_non_negative"),
            models.CheckConstraint(check=Q(qty_per_carton__gte=1), name="qty_per_carton_positive"),
        ]

    def __str__(self):
        return f"{self.carton_code} · {self.product.name}"

    def get_absolute_url(self):
        return reverse("inventory:carton_detail", args=[self.pk])

    @property
    def total_quantity(self):
        return self.carton_count * self.qty_per_carton

    @property
    def is_low(self):
        if self.status == self.Status.CLOSED:
            return False
        return self.carton_count < self.inventory.low_stock_threshold


class StockMovement(models.Model):
    class Type(models.TextChoices):
        IN = "IN", "Stock In"
        OUT = "OUT", "Stock Out"

    type = models.CharField(max_length=3, choices=Type.choices)
    receipt_no = models.CharField(max_length=30, unique=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    carton = models.ForeignKey(Carton, on_delete=models.PROTECT, related_name="movements")
    inventory = models.ForeignKey(Inventory, on_delete=models.PROTECT, related_name="movements")

    cartons_moved = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    qty_per_carton = models.PositiveIntegerField()
    qty_moved = models.PositiveIntegerField()
    cartons_before = models.PositiveIntegerField()
    cartons_after = models.PositiveIntegerField()
    stock_before = models.PositiveIntegerField(help_text="Units before")
    stock_after = models.PositiveIntegerField(help_text="Units after")

    note = models.TextField(blank=True)
    reference = models.CharField(max_length=100, blank=True)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movements")
    user_display = models.CharField(max_length=150)
    user_role = models.CharField(max_length=20)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    pdf = models.FileField(upload_to=receipt_path, storage=private_storage, blank=True)
    idempotency_key = models.UUIDField(unique=True, null=True, blank=True)
    verify_token = models.CharField(max_length=40, unique=True, default=new_token, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["inventory", "created_at"]), models.Index(fields=["type", "created_at"])]

    def __str__(self):
        return self.receipt_no

    def get_absolute_url(self):
        return reverse("inventory:movement_detail", args=[self.pk])

    @property
    def is_in(self):
        return self.type == self.Type.IN


# Expression helpers
UNITS = F("carton_count") * F("qty_per_carton")

