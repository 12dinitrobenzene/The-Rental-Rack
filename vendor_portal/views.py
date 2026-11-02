from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import get_employee_for_user
from shop.models import Product

from .forms import ProductForm


def inventory_status(product):
    if product.is_archived:
        return "Archived", "secondary"
    if product.moderation_blocked:
        return "Blocked", "danger"
    if product.vendor.is_suspended:
        return "Vendor suspended", "warning"
    if product.is_active and product.is_published:
        return "Active", "success"
    return "Draft", "secondary"


def employee_product_or_404(employee, product_id):
    return get_object_or_404(
        Product.objects.select_related("category", "vendor"),
        pk=product_id,
        vendor=employee.vendor,
    )


@login_required(login_url="accounts:login")
def employee_home(request):
    employee = get_employee_for_user(request.user)

    products = list(
        Product.objects.filter(vendor=employee.vendor)
        .select_related("category", "vendor")
        .annotate(total_stock=Sum("variants__total_quantity"))
        .order_by("-created_at", "-pk")
    )

    for product in products:
        product.total_stock = product.total_stock or 0
        product.status_label, product.status_style = inventory_status(product)

    return render(
        request,
        "vendor_portal/home.html",
        {
            "vendor": employee.vendor,
            "employee": employee,
            "products": products,
        },
    )


@login_required(login_url="accounts:login")
def employee_product_detail(request, product_id):
    employee = get_employee_for_user(request.user)
    product = employee_product_or_404(employee, product_id)

    return render(
        request,
        "vendor_portal/product_detail.html",
        {
            "vendor": employee.vendor,
            "product": product,
        },
    )


@login_required(login_url="accounts:login")
def employee_product_create(request):
    employee = get_employee_for_user(request.user)
    form = ProductForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.vendor = employee.vendor
        # A newly created listing is eligible to be published by its employee.
        product.is_active = True
        product.save()
        messages.success(request, "Product created.")
        return redirect("vendor_portal:home")

    return render(
        request,
        "vendor_portal/product_form.html",
        {"vendor": employee.vendor, "form": form, "page_title": "Add product"},
    )


@login_required(login_url="accounts:login")
def employee_product_edit(request, product_id):
    employee = get_employee_for_user(request.user)
    product = employee_product_or_404(employee, product_id)
    form = ProductForm(request.POST or None, instance=product)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product updated.")
        return redirect("vendor_portal:home")

    return render(
        request,
        "vendor_portal/product_form.html",
        {
            "vendor": employee.vendor,
            "form": form,
            "product": product,
            "page_title": "Edit product",
        },
    )


@login_required(login_url="accounts:login")
@require_POST
def employee_product_archive(request, product_id):
    employee = get_employee_for_user(request.user)
    product = employee_product_or_404(employee, product_id)
    product.is_archived = True
    product.save(update_fields=["is_archived"])
    messages.success(request, f"{product.name} has been archived.")
    return redirect("vendor_portal:home")
