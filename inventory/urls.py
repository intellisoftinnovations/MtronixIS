from django.urls import path

from .views import cartons, dashboard, inventories, labels, offline, products, public, pwa, stock

app_name = "inventory"

urlpatterns = [
    path("", dashboard.dashboard, name="dashboard"),
    path("manifest.json", pwa.manifest_json, name="manifest_json"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline_page, name="offline_page"),
    path("api/offline/snapshot/", offline.offline_snapshot, name="offline_snapshot"),
    path("api/offline/sync/", offline.offline_sync, name="offline_sync"),
    path("api/dashboard/summary/", dashboard.dashboard_summary_api, name="dashboard_api"),
    # Products
    path("products/", products.product_list, name="product_list"),
    path("products/export.csv", products.product_export, name="product_export"),
    path("products/new/", products.product_create, name="product_create"),
    path("products/<int:pk>/", products.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", products.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", products.product_delete, name="product_delete"),
    path("products/<int:pk>/restore/", products.product_restore, name="product_restore"),
    path("products/<int:pk>/regenerate-qr/", products.product_regenerate_qr, name="product_regenerate_qr"),
    # Cartons
    path("cartons/", cartons.carton_list, name="carton_list"),
    path("cartons/export.csv", cartons.carton_export, name="carton_export"),
    path("cartons/new/", cartons.carton_create, name="carton_create"),
    path("cartons/<int:pk>/", cartons.carton_detail, name="carton_detail"),
    path("cartons/<int:pk>/edit/", cartons.carton_edit, name="carton_edit"),
    path("cartons/<int:pk>/delete/", cartons.carton_delete, name="carton_delete"),
    path("cartons/<int:pk>/restore/", cartons.carton_restore, name="carton_restore"),
    path("cartons/<int:pk>/regenerate-qr/", cartons.carton_regenerate_qr, name="carton_regenerate_qr"),
    # Inventories
    path("inventories/", inventories.inventory_list, name="inventory_list"),
    path("inventories/new/", inventories.inventory_create, name="inventory_create"),
    path("inventories/<int:pk>/", inventories.inventory_detail, name="inventory_detail"),
    path("inventories/<int:pk>/edit/", inventories.inventory_edit, name="inventory_edit"),
    path("inventories/<int:pk>/archive/", inventories.inventory_archive, name="inventory_archive"),
    # Scan & stock
    path("scan/", stock.scan, name="scan"),
    path("scan/lookup/", stock.scan_lookup, name="scan_lookup"),
    path("scan/<str:token>/", stock.scan_result, name="scan_result"),
    path("stock/confirm/", stock.stock_confirm, name="stock_confirm"),
    path("stock/commit/", stock.stock_commit, name="stock_commit"),
    path("stock/<int:pk>/", stock.movement_detail, name="movement_detail"),
    path("stock/<int:pk>/done/", stock.movement_done, name="movement_done"),
    path("stock/<int:pk>/pdf/", stock.movement_pdf, name="movement_pdf"),
    path("stock/<int:pk>/regenerate-pdf/", stock.movement_regenerate_pdf, name="movement_regenerate_pdf"),
    path("stock/verify/<str:token>/", stock.movement_verify, name="movement_verify"),
    # Labels / QR
    path("labels/print/", labels.labels_print, name="labels_print"),
    path("labels/qr/<str:token>.png", labels.qr_image, name="qr_image"),
    # Public
    path("q/<str:token>/", public.public_qr, name="public_qr"),
]

