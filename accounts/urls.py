from django.urls import path

from . import views


app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("register/customer/", views.register_customer, name="register_customer"),
    path("register/company/", views.register_vendor, name="register_vendor"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("team/", views.vendor_team, name="vendor_team"),
    path(
        "team/add/",
        views.vendor_team_add_employee,
        name="vendor_team_add_employee",
    ),
]
