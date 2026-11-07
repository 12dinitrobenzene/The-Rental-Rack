from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.decorators.http import require_POST

from accounts.permissions import get_employee_for_user
from shop.models import (
    Product,
    ProductImage,
    ProductVariant,
    RentalItem,
    RentalReturn,
    RentalSettlement,
    ReturnInspection,
)

from .forms import ProductForm, ProductImageForm, ProductVariantForm


def inventory_status(product):
    if product.vendor.is_suspended:
        return "Vendor Suspended", "warning"
    if product.is_archived:
        return "Archived", "secondary"
    if product.moderation_blocked:
        return "Blocked", "danger"
    if product.is_active and product.is_published:
        return "Active", "success"
    return "Draft", "secondary"


def employee_product_or_404(employee, product_id):
    return get_object_or_404(
        Product.objects.select_related("category", "vendor").prefetch_related(
            "variants", "images"
        ),
        pk=product_id,
        vendor=employee.vendor,
    )


def product_variant_or_404(product, variant_id):
    return get_object_or_404(
        ProductVariant,
        pk=variant_id,
        product=product,
    )


def product_image_or_404(product, image_id):
    return get_object_or_404(
        ProductImage,
        pk=image_id,
        product=product,
    )


def employee_rental_item_or_404(employee, item_id, *, for_update=False):
    rental_items = RentalItem.objects.select_related(
        "order",
        "order__customer",
        "order__vendor",
        "variant",
        "variant__product",
    ).filter(order__vendor=employee.vendor)

    if for_update:
        rental_items = rental_items.select_for_update()
    else:
        rental_items = rental_items.select_related(
            "rental_return__inspection",
            "settlement",
        )

    return get_object_or_404(rental_items, pk=item_id)


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

    rental_items = (
        RentalItem.objects.filter(order__vendor=employee.vendor)
        .select_related(
            "order",
            "order__customer",
            "variant",
            "settlement",
        )
        .order_by("-order__created_at", "pk")
    )

    return render(
        request,
        "vendor_portal/home.html",
        {
            "vendor": employee.vendor,
            "employee": employee,
            "products": products,
            "rental_items": rental_items,
        },
    )


@login_required(login_url="accounts:login")
def employee_rental_detail(request, item_id):
    employee = get_employee_for_user(request.user)
    rental_item = employee_rental_item_or_404(employee, item_id)
    can_complete_and_settle = (
        rental_item.status == RentalItem.Status.RETURNED
        and RentalSettlement.has_eligible_inspection(rental_item)
        and not hasattr(rental_item, "settlement")
    )

    return render(
        request,
        "vendor_portal/rental_detail.html",
        {
            "vendor": employee.vendor,
            "rental_item": rental_item,
            "can_complete_and_settle": can_complete_and_settle,
        },
    )


class CompleteRentalView(LoginRequiredMixin, View):
    login_url = "accounts:login"

    def post(self, request, item_id):
        employee = get_employee_for_user(request.user)

        with transaction.atomic():
            rental_item = employee_rental_item_or_404(
                employee,
                item_id,
                for_update=True,
            )
            RentalReturn.objects.select_for_update().filter(
                rental_item=rental_item
            ).first()
            ReturnInspection.objects.select_for_update().filter(
                rental_return__rental_item=rental_item
            ).first()
            existing_settlement = (
                RentalSettlement.objects.select_for_update()
                .filter(rental_item=rental_item)
                .first()
            )

            if existing_settlement:
                messages.info(
                    request,
                    "This rental item already has a simulated settlement.",
                )
                return redirect(
                    "vendor_portal:rental_detail",
                    item_id=rental_item.pk,
                )

            if rental_item.status not in {
                RentalItem.Status.RETURNED,
                RentalItem.Status.COMPLETED,
            }:
                messages.error(
                    request,
                    "Only an inspected returned item can be completed.",
                )
                return redirect(
                    "vendor_portal:rental_detail",
                    item_id=rental_item.pk,
                )

            if not RentalSettlement.has_eligible_inspection(rental_item):
                messages.error(
                    request,
                    "Complete the return inspection before settlement.",
                )
                return redirect(
                    "vendor_portal:rental_detail",
                    item_id=rental_item.pk,
                )

            if rental_item.status == RentalItem.Status.RETURNED:
                rental_item.transition_to(RentalItem.Status.COMPLETED)

            settlement = RentalSettlement.build_for_item(rental_item)
            settlement.full_clean()
            rental_item.save(update_fields=["status"])
            settlement.save()

        messages.success(
            request,
            "Rental completed and simulated settlement recorded.",
        )
        return redirect(
            "vendor_portal:rental_detail",
            item_id=rental_item.pk,
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


@login_required(login_url="accounts:login")
def employee_variant_create(request, product_id):
    employee = get_employee_for_user(request.user)
    product = employee_product_or_404(employee, product_id)
    form = ProductVariantForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        variant = form.save(commit=False)
        variant.product = product
        variant.save()
        messages.success(request, "Variant added.")
        return redirect("vendor_portal:product_detail", product_id=product.pk)

    return render(
        request,
        "vendor_portal/variant_form.html",
        {"vendor": employee.vendor, "product": product, "form": form, "page_title": "Add variant"},
    )


@login_required(login_url="accounts:login")
def employee_variant_edit(request, product_id, variant_id):
    employee = get_employee_for_user(request.user)
    product = employee_product_or_404(employee, product_id)
    variant = product_variant_or_404(product, variant_id)
    form = ProductVariantForm(request.POST or None, instance=variant)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Variant updated.")
        return redirect("vendor_portal:product_detail", product_id=product.pk)

    return render(
        request,
        "vendor_portal/variant_form.html",
        {
            "vendor": employee.vendor,
            "product": product,
            "variant": variant,
            "form": form,
            "page_title": "Edit variant",
        },
    )


@login_required(login_url="accounts:login")
def employee_image_create(request, product_id):
    employee = get_employee_for_user(request.user)
    product = employee_product_or_404(employee, product_id)
    form = ProductImageForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        image = form.save(commit=False)
        image.product = product
        image.save()
        messages.success(request, "Product image added.")
        return redirect("vendor_portal:product_detail", product_id=product.pk)

    return render(
        request,
        "vendor_portal/image_form.html",
        {"vendor": employee.vendor, "product": product, "form": form, "page_title": "Add image"},
    )


@login_required(login_url="accounts:login")
def employee_image_edit(request, product_id, image_id):
    employee = get_employee_for_user(request.user)
    product = employee_product_or_404(employee, product_id)
    image = product_image_or_404(product, image_id)
    form = ProductImageForm(
        request.POST or None,
        request.FILES or None,
        instance=image,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product image updated.")
        return redirect("vendor_portal:product_detail", product_id=product.pk)

    return render(
        request,
        "vendor_portal/image_form.html",
        {
            "vendor": employee.vendor,
            "product": product,
            "product_image": image,
            "form": form,
            "page_title": "Edit image",
        },
    )
