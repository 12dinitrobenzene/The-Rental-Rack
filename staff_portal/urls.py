from django.urls import path

from . import views


app_name = "staff_portal"

urlpatterns = [
    path("", views.platform_admin_home, name="home"),
    path("vendors/", views.platform_vendor_list, name="vendor_list"),
    path(
        "vendors/<int:vendor_id>/action/",
        views.platform_vendor_action,
        name="vendor_action",
    ),
]
