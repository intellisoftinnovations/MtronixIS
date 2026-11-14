from django import forms
from django.contrib.auth import get_user_model

from .images import process_product_image
from .models import Carton, Inventory, Product, StockMovement
from .permissions import allowed_inventories

User = get_user_model()


class StyledFormMixin:
    """Apply design-system classes to all widgets."""

    def _style(self):
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                w.attrs.setdefault("class", "check")
            elif isinstance(w, forms.ClearableFileInput):
                w.attrs.setdefault("class", "input file")
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "input select")
            else:
                w.attrs.setdefault("class", "input")
            if self.errors.get(name):
                w.attrs["class"] += " is-invalid"
                w.attrs["aria-invalid"] = "true"

    def full_clean(self):
        super().full_clean()
        self._style()


def generate_unique_sku(name=""):
    """Generate a short, human-readable, guaranteed-unique SKU."""
    import re
    import secrets

    prefix = re.sub(r"[^A-Z0-9]", "", (name or "").upper())[:3] or "MTX"
    for _ in range(25):
        suffix = f"{secrets.randbelow(90000) + 10000}"
        candidate = f"{prefix}-{suffix}"
        if not Product.objects.filter(sku__iexact=candidate).exists():
            return candidate
    return f"{prefix}-{secrets.token_hex(3).upper()}"


class ProductForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "sku", "description", "image"]
        widgets = {
            "sku": forms.TextInput(attrs={"placeholder": "Enter SKU or leave blank to auto-generate", "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "image": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp,image/gif"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sku"].required = False
        self._style()

    def clean_sku(self):
        sku = (self.cleaned_data.get("sku") or "").strip().upper()
        if not sku:
            return generate_unique_sku(self.cleaned_data.get("name", ""))
        qs = Product.objects.filter(sku__iexact=sku)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A product with this SKU already exists.")
        return sku

    def clean_image(self):
        img = self.cleaned_data.get("image")
        if img and hasattr(img, "content_type"):  # newly uploaded file
            return process_product_image(img)
        return img


class CartonForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Carton
        fields = ["product", "inventory", "carton_code", "qty_per_carton", "carton_count", "status"]
        labels = {
            "carton_code": "Carton number / code",
            "qty_per_carton": "Quantity per carton",
            "carton_count": "Number of cartons",
        }
        widgets = {
            "qty_per_carton": forms.NumberInput(attrs={"min": 1, "inputmode": "numeric"}),
            "carton_count": forms.NumberInput(attrs={"min": 0, "inputmode": "numeric"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["product"].queryset = Product.objects.alive()
        self.fields["inventory"].queryset = allowed_inventories(user, include_archived=False)
        if self.instance.pk:
            # Stock count is changed only through Stock In / Stock Out so every change gets a receipt.
            self.fields["carton_count"].disabled = True
            self.fields["carton_count"].help_text = "Use Scan QR → Stock In / Out to change stock."
        else:
            self.fields["carton_count"].help_text = "Opening stock. A Stock In receipt is created automatically."
        self._style()

    def clean_carton_code(self):
        return self.cleaned_data["carton_code"].strip().upper()

    def clean(self):
        data = super().clean()
        inv, code = data.get("inventory"), data.get("carton_code")
        if inv and code:
            qs = Carton.objects.alive().filter(inventory=inv, carton_code__iexact=code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("carton_code", "This carton code already exists in this inventory.")
        return data


class InventoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Inventory
        fields = ["name", "code", "location", "low_stock_threshold", "managers", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "managers": forms.CheckboxSelectMultiple,
        }
        labels = {"low_stock_threshold": "Low-stock threshold (cartons)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["managers"].queryset = User.objects.filter(role=User.Role.MANAGER, is_active=True)
        self.fields["managers"].required = False
        self._style()

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        qs = Inventory.objects.filter(code__iexact=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This inventory code is already used.")
        return code


class InventoryLimitedForm(StyledFormMixin, forms.ModelForm):
    """What a manager may edit on an assigned inventory."""

    class Meta:
        model = Inventory
        fields = ["low_stock_threshold", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}
        labels = {"low_stock_threshold": "Low-stock threshold (cartons)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class StockForm(forms.Form):
    carton_id = forms.IntegerField(widget=forms.HiddenInput)
    type = forms.ChoiceField(choices=StockMovement.Type.choices)
    cartons = forms.IntegerField(min_value=1, max_value=100_000, initial=1, label="Cartons")
    reference = forms.CharField(max_length=100, required=False, label="Reference (optional)")
    note = forms.CharField(max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note (optional)")
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

