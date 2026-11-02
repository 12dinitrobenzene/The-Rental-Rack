from django.urls import path

from . import views


app_name = "vendor_portal"

urlpatterns = [
    path("", views.employee_home, name="home"),
    path("products/add/", views.employee_product_create, name="product_create"),
    path(
        "products/<int:product_id>/",
        views.employee_product_detail,
        name="product_detail",
    ),
    path(
        "products/<int:product_id>/edit/",
        views.employee_product_edit,
        name="product_edit",
    ),
    path(
        "products/<int:product_id>/archive/",
        views.employee_product_archive,
        name="product_archive",
    ),
]
