from django.urls import path

from . import views


app_name = "staff_portal"

urlpatterns = [
    path("", views.platform_admin_home, name="home"),
    path(
        "admins/",
        views.PlatformAdminListView.as_view(),
        name="admin_list",
    ),
    path(
        "admins/create/",
        views.PlatformAdminCreateView.as_view(),
        name="admin_create",
    ),
    path(
        "admins/<int:pk>/edit/",
        views.PlatformAdminUpdateView.as_view(),
        name="admin_update",
    ),
    path(
        "admins/<int:user_id>/status/",
        views.platform_admin_status_action,
        name="admin_status",
    ),
    path(
        "performance/",
        views.platform_performance,
        name="performance",
    ),
    path("vendors/", views.platform_vendor_list, name="vendor_list"),
    path(
        "rentals/",
        views.platform_rental_order_list,
        name="rental_order_list",
    ),
    path(
        "settlements/",
        views.platform_settlement_list,
        name="settlement_list",
    ),
    path("listings/", views.platform_listing_list, name="listing_list"),
    path(
        "listings/<int:product_id>/moderate/",
        views.platform_listing_moderate,
        name="listing_moderate",
    ),
    path(
        "vendors/<int:vendor_id>/action/",
        views.platform_vendor_action,
        name="vendor_action",
    ),
]
