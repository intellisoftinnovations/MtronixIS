from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("account/2fa/verify/", views.verify_2fa, name="2fa_verify"),
    path("account/2fa/setup/", views.setup_2fa, name="2fa_setup"),
    path("account/2fa/disable/", views.disable_2fa, name="2fa_disable"),
    path("account/profile/", views.profile, name="profile"),
    path("account/password/", views.change_password, name="change_password"),
    path("users/", views.user_list, name="user_list"),
    path("users/invite/", views.user_invite, name="user_invite"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/set-password/", views.user_admin_set_password, name="user_set_password"),
    path("users/<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("users/<int:pk>/force-logout/", views.user_force_logout, name="user_force_logout"),
    path("users/<int:pk>/reset-2fa/", views.user_reset_2fa, name="user_reset_2fa"),
    path("invite/<str:uidb64>/<str:token>/", views.user_accept_invite, name="user_accept_invite"),
]

