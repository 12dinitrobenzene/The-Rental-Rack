from django.urls import path

from . import views


app_name = "vendor_portal"

urlpatterns = [
    path("", views.employee_home, name="home"),
    path(
        "analytics/",
        views.employee_analytics,
        name="analytics",
    ),
    path(
        "rentals/<int:item_id>/",
        views.employee_rental_detail,
        name="rental_detail",
    ),
    path(
        "rentals/<int:item_id>/transition/",
        views.employee_rental_transition,
        name="rental_transition",
    ),
    path(
        "rentals/<int:item_id>/return/",
        views.employee_record_return,
        name="rental_return",
    ),
    path(
        "rentals/<int:item_id>/inspection/",
        views.employee_return_inspection,
        name="return_inspection",
    ),
    path(
        "rentals/<int:item_id>/complete/",
        views.CompleteRentalView.as_view(),
        name="rental_complete",
    ),
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
    path(
        "products/<int:product_id>/variants/add/",
        views.employee_variant_create,
        name="variant_create",
    ),
    path(
        "products/<int:product_id>/variants/<int:variant_id>/edit/",
        views.employee_variant_edit,
        name="variant_edit",
    ),
    path(
        "products/<int:product_id>/images/add/",
        views.employee_image_create,
        name="image_create",
    ),
    path(
        "products/<int:product_id>/images/<int:image_id>/edit/",
        views.employee_image_edit,
        name="image_edit",
    ),
    path("rentals/", views.employee_rental_order_list, name="rental_order_list"),
    path(
        "rentals/orders/<int:order_id>/",
        views.employee_rental_order_detail,
        name="order_detail",
    ),
]
