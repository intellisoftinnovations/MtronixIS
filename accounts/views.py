import pyotp
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from accounts.security import client_ip, describe_device, hit, is_limited, reset, user_agent
from audit.models import ActivityLog
from audit.utils import log_action
from inventory.qr import qr_data_uri

from .forms import InviteForm, LoginForm, ProfileForm, TOTPForm, UserAdminSetPasswordForm, UserEditForm
from .models import LoginHistory, User

# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

def _record_login(request, email, user, success, reason=""):
    ua = user_agent(request)
    LoginHistory.objects.create(
        user=user, email_attempted=email[:254], ip=client_ip(request),
        user_agent=ua[:255], device=describe_device(ua), success=success, reason=reason,
    )


def login_view(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    form = LoginForm(request.POST or None)
    if request.method != "POST" or not form.is_valid():
        return render(request, "accounts/login.html", {"form": form})

    email = form.cleaned_data["email"].lower().strip()
    password = form.cleaned_data["password"]
    ip = client_ip(request) or "unknown"

    # Rate limiting
    if is_limited(f"login:email:{email}", settings.MTX_LOGIN_MAX_ATTEMPTS):
        _record_login(request, email, None, False, "rate-limited (email)")
        messages.error(request, f"Too many attempts. Try again in {settings.MTX_LOCKOUT_MINUTES} minutes.")
        return render(request, "accounts/login.html", {"form": form})
    if is_limited(f"login:ip:{ip}", settings.MTX_LOGIN_MAX_ATTEMPTS_IP):
        _record_login(request, email, None, False, "rate-limited (IP)")
        messages.error(request, "Too many attempts from this address.")
        return render(request, "accounts/login.html", {"form": form})

    user = authenticate(request, username=email, password=password)
    if user is None:
        hit(f"login:email:{email}", settings.MTX_LOCKOUT_MINUTES * 60)
        hit(f"login:ip:{ip}", settings.MTX_LOCKOUT_MINUTES * 60)
        _record_login(request, email, None, False, "bad credentials")
        messages.error(request, "Invalid email or password.")
        return render(request, "accounts/login.html", {"form": form})

    if not user.is_active:
        _record_login(request, email, user, False, "disabled")
        messages.error(request, "Your account has been disabled.")
        return render(request, "accounts/login.html", {"form": form})

    remember_me = form.cleaned_data.get("remember_me", True)

    # 2FA check
    if user.totp_enabled:
        request.session["pending_2fa_user"] = user.pk
        request.session["pending_2fa_email"] = email
        request.session["pending_2fa_remember"] = remember_me
        return redirect("accounts:2fa_verify")

    _finish_login(request, user, email, remember_me=remember_me)
    return redirect(settings.LOGIN_REDIRECT_URL)


def _finish_login(request, user, email, remember_me=True):
    login(request, user)
    request.session["session_version"] = user.session_version
    if remember_me:
        # Persistent session: keep logged in across device restarts until explicit logout
        request.session.set_expiry(settings.SESSION_COOKIE_AGE)
    else:
        request.session.set_expiry(0)
    reset(f"login:email:{email}")
    _record_login(request, email, user, True)
    log_action(request, ActivityLog.Action.LOGIN, user=user, entity_type="User", entity_repr=str(user))


def verify_2fa(request):
    uid = request.session.get("pending_2fa_user")
    if not uid:
        return redirect("accounts:login")
    user = User.objects.filter(pk=uid, is_active=True).first()
    if not user:
        return redirect("accounts:login")
    form = TOTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if user.verify_totp(form.cleaned_data["code"]):
            del request.session["pending_2fa_user"]
            request.session.pop("pending_2fa_email", None)
            remember_me = request.session.pop("pending_2fa_remember", True)
            _finish_login(request, user, user.email, remember_me=remember_me)
            return redirect(settings.LOGIN_REDIRECT_URL)
        messages.error(request, "Invalid code. Try again.")
    return render(request, "accounts/2fa_verify.html", {"form": form})


@login_required
@require_POST
def logout_view(request):
    log_action(request, ActivityLog.Action.LOGOUT, entity_type="User", entity_repr=str(request.user))
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("accounts:login")


# ---------------------------------------------------------------------------
# 2FA Setup
# ---------------------------------------------------------------------------

@login_required
def setup_2fa(request):
    user = request.user
    if user.totp_enabled:
        messages.info(request, "Two-factor authentication is already enabled.")
        return redirect("accounts:profile")
    secret = request.session.get("2fa_setup_secret")
    if not secret:
        secret = pyotp.random_base32()
        request.session["2fa_setup_secret"] = secret
    uri = user.totp_uri(secret)
    qr_code = qr_data_uri(uri)
    form = TOTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if user.verify_totp(form.cleaned_data["code"], secret=secret):
            user.totp_secret = secret
            user.totp_enabled = True
            user.save(update_fields=["totp_secret", "totp_enabled"])
            request.session.pop("2fa_setup_secret", None)
            log_action(request, ActivityLog.Action.TWOFA_ENABLE, obj=user)
            messages.success(request, "Two-factor authentication enabled.")
            return redirect("accounts:profile")
        messages.error(request, "Invalid code. Scan the QR code again and enter the current code.")
    return render(request, "accounts/2fa_setup.html", {"form": form, "secret": secret, "uri": uri, "qr_code": qr_code})


@login_required
@require_POST
def disable_2fa(request):
    user = request.user
    if user.is_admin:
        messages.error(request, "Admin accounts must keep 2FA enabled.")
        return redirect("accounts:profile")
    user.totp_enabled = False
    user.totp_secret = ""
    user.totp_last_counter = 0
    user.save(update_fields=["totp_enabled", "totp_secret", "totp_last_counter"])
    log_action(request, ActivityLog.Action.TWOFA_DISABLE, obj=user)
    messages.success(request, "Two-factor authentication disabled.")
    return redirect("accounts:profile")


# ---------------------------------------------------------------------------
# Profile & security
# ---------------------------------------------------------------------------

@login_required
def profile(request):
    user = request.user
    form = ProfileForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    history = user.login_history.all()[:20]
    return render(request, "accounts/profile.html", {"form": form, "history": history})


@login_required
def change_password(request):
    form = SetPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.password_set_at = timezone.now()
        user.save(update_fields=["password_set_at"])
        update_session_auth_hash(request, user)
        log_action(request, ActivityLog.Action.PASSWORD_CHANGE, obj=user)
        messages.success(request, "Password changed.")
        return redirect("accounts:profile")
    return render(request, "accounts/change_password.html", {"form": form})


# ---------------------------------------------------------------------------
# User management (Admin)
# ---------------------------------------------------------------------------

@admin_required
def user_list(request):
    qs = User.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q))
    role = request.GET.get("role")
    if role in User.Role.values:
        qs = qs.filter(role=role)
    status = request.GET.get("status")
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "disabled":
        qs = qs.filter(is_active=False)
    return render(request, "accounts/user_list.html", {"users": qs})


@admin_required
def user_invite(request):
    form = InviteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        init_pwd = form.cleaned_data.get("initial_password")
        if init_pwd:
            user.set_password(init_pwd)
            user.password_set_at = timezone.now()
        else:
            user.set_unusable_password()
        user.invited_at = timezone.now()
        user.created_by = request.user
        user.save()
        form.save_m2m()
        log_action(request, ActivityLog.Action.USER_INVITE, obj=user,
                   new={"email": user.email, "role": user.role, "name": user.name})

        if init_pwd:
            messages.success(request, f"User {user.email} created with password. They can sign in immediately.")
            return redirect("accounts:user_list")

        # Generate invite / activation link
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        invite_url = request.build_absolute_uri(reverse("accounts:user_accept_invite", args=[uid, token]))
        return render(request, "accounts/user_invite_done.html", {"user": user, "invite_url": invite_url})

    return render(request, "accounts/user_invite.html", {"form": form})


@admin_required
def user_admin_set_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = UserAdminSetPasswordForm(target, request.POST or None)
    if request.method == "POST" and form.is_valid():
        target.set_password(form.cleaned_data["password"])
        target.password_set_at = timezone.now()
        target.session_version += 1
        target.save(update_fields=["password", "password_set_at", "session_version"])
        reset(f"login:email:{target.email.lower()}")
        log_action(request, ActivityLog.Action.PASSWORD_CHANGE, obj=target,
                   note="Password set by admin", entity_repr=str(target))
        messages.success(request, f"Password updated for {target.name or target.email}. They can now sign in.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_set_password.html", {"form": form, "target": target})


def user_accept_invite(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        return render(request, "accounts/invite_invalid.html")

    form = SetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.password_set_at = timezone.now()
        user.save(update_fields=["password_set_at"])
        reset(f"login:email:{user.email.lower()}")
        log_action(request, ActivityLog.Action.PASSWORD_SET, obj=user, note="User accepted invite and set password")
        messages.success(request, "Your password has been set. Please sign in.")
        return redirect("accounts:login")

    return render(request, "accounts/invite_accept.html", {"form": form, "user": user})


@admin_required
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    old_role = target.role
    form = UserEditForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if old_role != user.role:
            user.session_version += 1
            user.save(update_fields=["session_version"])
            log_action(request, ActivityLog.Action.ROLE_CHANGE, obj=user,
                       old={"role": old_role}, new={"role": user.role})
        messages.success(request, "User updated.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_edit.html", {"form": form, "target": target})


@admin_required
@require_POST
def user_toggle_active(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, "You cannot disable your own account.")
        return redirect("accounts:user_list")
    target.is_active = not target.is_active
    target.save(update_fields=["is_active"])
    if not target.is_active:
        target.session_version += 1
        target.save(update_fields=["session_version"])
    action = ActivityLog.Action.USER_ENABLE if target.is_active else ActivityLog.Action.USER_DISABLE
    log_action(request, action, obj=target, entity_repr=str(target))
    messages.success(request, f"User {'enabled' if target.is_active else 'disabled'}.")
    return redirect("accounts:user_list")


@admin_required
@require_POST
def user_force_logout(request, pk):
    target = get_object_or_404(User, pk=pk)
    target.session_version += 1
    target.save(update_fields=["session_version"])
    log_action(request, ActivityLog.Action.FORCE_LOGOUT, obj=target, entity_repr=str(target))
    messages.success(request, f"All sessions for {target.name} have been ended.")
    return redirect("accounts:user_list")


@admin_required
@require_POST
def user_reset_2fa(request, pk):
    target = get_object_or_404(User, pk=pk)
    target.totp_enabled = False
    target.totp_secret = ""
    target.totp_last_counter = 0
    target.session_version += 1
    target.save(update_fields=["totp_enabled", "totp_secret", "totp_last_counter", "session_version"])
    log_action(request, ActivityLog.Action.TWOFA_RESET, obj=target, entity_repr=str(target))
    messages.success(request, f"2FA reset for {target.name}. They will need to set it up again on next login.")
    return redirect("accounts:user_list")

