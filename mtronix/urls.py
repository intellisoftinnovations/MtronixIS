from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("inventory.urls")),
    path("logs/", include("audit.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "inventory.views.errors.permission_denied"
handler404 = "inventory.views.errors.page_not_found"
handler500 = "inventory.views.errors.server_error"

