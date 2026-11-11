from django.urls import path

from . import views


app_name = "customer"

urlpatterns = [
    path("", views.customer_home, name="home"),
    path("catalogue/", views.catalogue, name="catalogue"),
    path("products/<int:product_id>/", views.product_detail, name="product_detail"),
    path(
        "products/<int:product_id>/cart/add/",
        views.AddToCartView.as_view(),
        name="cart_add",
    ),
    path(
        "orders/",
        views.order_history,
        name="order_history",
    ),
    path(
        "orders/<int:order_id>/",
        views.order_detail,
        name="order_detail",
    ),
    path(
        "orders/<int:order_id>/cancel/",
        views.OrderCancelView.as_view(),
        name="order_cancel",
    ),
    path(
        "rentals/<int:rental_item_id>/review/",
        views.ReviewCreateView.as_view(),
        name="review_create",
    ),
    path(
        "orders/<int:order_id>/confirmation/",
        views.order_confirmation,
        name="order_confirmation",
    ),
    path("preferences/", views.style_preferences, name="style_preferences"),
    path(
        "cart/",
        views.CartView.as_view(),
        name="cart",
    ),
    path(
        "cart/<int:line_index>/update/",
        views.CartUpdateView.as_view(),
        name="cart_update",
    ),
    path(
        "cart/<int:line_index>/remove/",
        views.CartRemoveView.as_view(),
        name="cart_remove",
    ),
    path(
        "checkout/",
        views.CheckoutView.as_view(),
        name="checkout",
    ),
    path(
        "account/",
        views.order_history,
        name="account",
    ),
    path(
        "wishlist/",
        views.WishlistView.as_view(),
        name="wishlist",
    ),
    path(
        "wishlist/<int:product_id>/add/",
        views.WishlistAddView.as_view(),
        name="wishlist_add",
    ),
    path(
        "wishlist/<int:product_id>/remove/",
        views.WishlistRemoveView.as_view(),
        name="wishlist_remove",
    ),
    path(
        "about_us/",
        views.about_us,
        name="about",
    ),
    path(
        "guide/",
        views.customer_guide,
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
