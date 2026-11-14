from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class LoginForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "input", "placeholder": "Email", "autofocus": True, "autocomplete": "email"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Password", "autocomplete": "current-password"}))
    remember_me = forms.BooleanField(required=False, initial=True, label="Remember this device (Stay signed in)")


class TOTPForm(forms.Form):
    code = forms.CharField(
        max_length=6, min_length=6,
        widget=forms.TextInput(attrs={"class": "input totp-input", "placeholder": "000000", "inputmode": "numeric",
                                       "autocomplete": "one-time-code", "autofocus": True, "pattern": "[0-9]{6}"}),
        label="Authentication code",
    )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "input"})}


class InviteForm(forms.ModelForm):
    initial_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Initial password (leave blank to send invite link)", "autocomplete": "new-password"}),
        label="Initial password (optional)",
        help_text="If set, the user can log in immediately. If left empty, an invite link will be generated.",
    )

    class Meta:
        model = User
        fields = ["email", "name", "role"]
        widgets = {
            "email": forms.EmailInput(attrs={"class": "input"}),
            "name": forms.TextInput(attrs={"class": "input"}),
            "role": forms.Select(attrs={"class": "input select"}),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_initial_password(self):
        pwd = self.cleaned_data.get("initial_password")
        if pwd:
            validate_password(pwd)
        return pwd


class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["name", "role", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "role": forms.Select(attrs={"class": "input select"}),
        }


class UserAdminSetPasswordForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "New password (min 10 chars)"}),
        label="New password",
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Confirm new password"}),
        label="Confirm password",
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        pwd = self.cleaned_data.get("password")
        if pwd:
            validate_password(pwd, user=self.user)
        return pwd

    def clean(self):
        data = super().clean()
        p1 = data.get("password")
        p2 = data.get("confirm_password")
        if p1 and p2 and p1 != p2:
            self.add_error("confirm_password", "Passwords do not match.")
        return data

