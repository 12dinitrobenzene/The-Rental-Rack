from django.urls import path

from . import views


app_name = "vendor_portal"

urlpatterns = [
    path("", views.employee_home, name="home"),
    path(
        "products/<int:product_id>/",
        views.employee_product_detail,
        name="product_detail",
    ),
]
