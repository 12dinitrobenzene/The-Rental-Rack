from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group
from django.db import transaction
from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from .forms import CustomerProfileForm, CustomerRegistrationForm
from .models import CustomerProfile
from .roles import CUSTOMER_GROUP, destination_for_user, user_has_role


def register(request):
    if request.user.is_authenticated:
        destination = destination_for_user(request.user)
        return redirect(destination or "customer:home")

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
