from django.urls import path

from . import views


app_name = "customer"

urlpatterns = [
    path("", views.customer_home, name="home"),
    path("catalogue/", views.catalogue, name="catalogue"),
    path("products/<int:product_id>/", views.product_detail, name="product_detail"),
    path("preferences/", views.style_preferences, name="style_preferences"),
    path(
        "cart/",
        views.customer_placeholder,
        {
            "title": "Your cart",
            "message": "Your selected rental items will appear here.",
        },
        name="cart",
    ),
    path(
        "account/",
        views.customer_placeholder,
        {
            "title": "Your account",
            "message": "Your account details and rental history will appear here.",
        },
        name="account",
    ),
    path(
        "wishlist/",
        views.customer_placeholder,
        {
            "title": "Your wishlist",
            "message": "Your saved clothing will appear here.",
        },
        name="wishlist",
    ),
    path(
        "about_us/",
        views.customer_placeholder,
        {
            "title": "About us",
            "message": "Discover our story and our approach to clothing rental.",
        },
        name="about",
    ),
    path(
        "guide/",
        views.customer_placeholder,
        {
            "title": "How it works",
            "message": (
                "Our guide to choosing, renting and returning clothing is coming soon."
            ),
        },
        name="guide",
    ),
    path(
        "vendor_info/",
        views.customer_placeholder,
        {
            "title": "Become a vendor",
            "message": "Learn about joining our marketplace and renting out your collection.",
        },
        name="vendor_info",
    ),
]
