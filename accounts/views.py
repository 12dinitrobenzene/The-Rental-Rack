from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group
from django.db import transaction
from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from .forms import (
    CustomerProfileForm,
    CustomerRegistrationForm,
    VendorEmployeeRegistrationForm,
    VendorRegistrationForm,
)
from .models import CustomerProfile, VendorEmployee
from .permissions import get_vendor_admin_for_user
from .roles import (
    CUSTOMER_GROUP,
    VENDOR_EMPLOYEE_GROUP,
    destination_for_user,
    user_has_role,
)
from shop.models import Vendor


def register(request):
    if request.user.is_authenticated:
        destination = destination_for_user(request.user)
        return redirect(destination or "landing")

    return render(request, "accounts/register_choice.html")


def register_customer(request):
    if request.user.is_authenticated:
        destination = destination_for_user(request.user)
        return redirect(destination or "landing")

    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                user = form.save()
                customer_group = Group.objects.get(name=CUSTOMER_GROUP)
                user.groups.add(customer_group)
                CustomerProfile.objects.create(user=user)

            messages.success(
                request,
                "Your customer account has been created. Sign in to continue.",
            )
            return redirect("landing")
    else:
        form = CustomerRegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


def register_vendor(request):
    if request.user.is_authenticated:
        destination = destination_for_user(request.user)
        return redirect(destination or "landing")

    form = VendorRegistrationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            vendor = Vendor.objects.create(
                name=form.cleaned_data["company_name"],
                contact_email=form.cleaned_data["company_email"],
                contact_phone=form.cleaned_data["contact_phone"],
                address=form.cleaned_data["address"],
            )
            vendor_group = Group.objects.get(name=VENDOR_EMPLOYEE_GROUP)
            user.groups.add(vendor_group)
            VendorEmployee.objects.create(
                user=user,
                vendor=vendor,
                is_vendor_admin=True,
            )

        messages.success(
            request,
            "Your company account has been created and is awaiting approval.",
        )
        return redirect("accounts:login")

    return render(request, "accounts/register_vendor.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        destination = destination_for_user(request.user)
        return redirect(destination or "landing")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)

        if form.is_valid():
            user = form.get_user()
            destination = destination_for_user(user)

            if destination:
                login(request, user)
                return redirect(destination)

            form.add_error(
                None,
                "This account does not have exactly one application role.",
            )
    else:
        form = AuthenticationForm(request)

    return render(request, "accounts/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "You have been signed out.")
    return redirect("landing")


@login_required(login_url="accounts:login")
def profile(request):
    if not user_has_role(request.user, CUSTOMER_GROUP):
        messages.error(request, "Only customer accounts can edit a customer profile.")
        return redirect(destination_for_user(request.user) or "landing")

    customer_profile, _ = CustomerProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = CustomerProfileForm(
            request.POST,
            instance=customer_profile,
            user=request.user,
        )

        if form.is_valid():
            with transaction.atomic():
                form.save()

            messages.success(request, "Your profile has been updated.")
            return redirect("accounts:profile")
    else:
        form = CustomerProfileForm(
            instance=customer_profile,
            user=request.user,
        )

    return render(request, "accounts/profile.html", {"form": form})


@login_required(login_url="accounts:login")
def vendor_team(request):
    employee = get_vendor_admin_for_user(request.user)
    employees = employee.vendor.employees.select_related("user").order_by(
        "user__first_name",
        "user__last_name",
        "user__username",
    )

    return render(
        request,
        "accounts/vendor_team.html",
        {"vendor": employee.vendor, "employees": employees},
    )


@login_required(login_url="accounts:login")
def vendor_team_add_employee(request):
    manager = get_vendor_admin_for_user(request.user)
    form = VendorEmployeeRegistrationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            vendor_group = Group.objects.get(name=VENDOR_EMPLOYEE_GROUP)
            user.groups.add(vendor_group)
            VendorEmployee.objects.create(user=user, vendor=manager.vendor)

        messages.success(request, "Employee account created.")
        return redirect("accounts:vendor_team")

    return render(
        request,
        "accounts/vendor_team_employee_form.html",
        {"vendor": manager.vendor, "form": form},
    )
