"""URL patterns for the shop application."""

from django.urls import path

from . import views

app_name = "shop"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("customer/", views.customer_home, name="catalogue"),
    path("customer/catalogue/", views.catalogue, name="full_catalogue"),
    path("employee/", views.employee_home, name="employee_home"),
    path(
        "employee/products/<int:product_id>/",
        views.employee_product_detail,
        name="employee_product_detail",
    ),
    path("platform_admin/", views.platform_admin_home, name="platform_admin_home"),
    path(
        "platform_admin/vendors/",
        views.platform_vendor_list,
        name="platform_vendor_list",
    ),
    path(
        "platform_admin/vendors/<int:vendor_id>/action/",
        views.platform_vendor_action,
        name="platform_vendor_action",
    ),
    path(
        "customer/products/<int:product_id>/",
        views.product_detail,
        name="product_detail",
    ),
    path(
        "customer/preferences/",
        views.style_preferences,
        name="style_preferences",
    ),
    path(
        "customer/cart/",
        views.customer_placeholder,
        {
            "title": "Your cart",
            "message": "Your selected rental items will appear here.",
        },
        name="customer_cart",
    ),
    path(
        "customer/account/",
        views.customer_placeholder,
        {
            "title": "Your account",
            "message": "Your account details and rental history will appear here.",
        },
        name="customer_account",
    ),
    path(
        "customer/wishlist/",
        views.customer_placeholder,
        {
            "title": "Your wishlist",
            "message": "Your saved clothing will appear here.",
        },
        name="customer_wishlist",
    ),
    path(
        "customer/about_us/",
        views.customer_placeholder,
        {
            "title": "About us",
            "message": "Discover our story and our approach to clothing rental.",
        },
        name="customer_about",
    ),
    path(
        "customer/guide/",
        views.customer_placeholder,
        {
            "title": "How it works",
            "message": "Our guide to choosing, renting and returning clothing is coming soon.",
        },
        name="customer_guide",
    ),
    path(
        "customer/vendor_info/",
        views.customer_placeholder,
        {
            "title": "Become a vendor",
            "message": "Learn about joining our marketplace and renting out your collection.",
        },
        name="customer_vendor_info",
    ),
]
