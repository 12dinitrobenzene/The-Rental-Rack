from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST, require_http_methods

from accounts.permissions import get_employee_for_user
from shop.models import (
    Product,
    ProductImage,
    ProductVariant,
    RentalItem,
    RentalOrder,
    RentalReturn,
    RentalSettlement,
    ReturnInspection,
)

from .forms import (
    ProductForm,
    ProductImageForm,
    ProductVariantForm,
    RentalReturnForm,
    RentalOrderFilterForm,
    ReturnInspectionForm,
)


FULFILMENT_ACTIONS = {
    "prepare": (
        RentalItem.Status.PREPARING,
        "Start preparing",
    ),
    "dispatch": (
        RentalItem.Status.DISPATCHED,
        "Mark dispatched",
    ),
    "activate": (
        RentalItem.Status.ACTIVE,
        "Mark active",
    ),
    "mark_overdue": (
        RentalItem.Status.OVERDUE,
        "Mark overdue",
    ),
}


def available_fulfilment_actions(rental_item):
    if rental_item.order.payment_status != RentalOrder.PaymentStatus.PAID:
        return []

    actions = []

    for action, (target_status, label) in FULFILMENT_ACTIONS.items():
        if not rental_item.can_transition_to(target_status):
            continue

        if (
            target_status == RentalItem.Status.OVERDUE
            and rental_item.rental_end_date >= timezone.localdate()
        ):
            continue

        actions.append({
            "action": action,
            "label": label,
        })

    return actions


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
        rental_item.order.payment_status
        == RentalOrder.PaymentStatus.PAID
        and rental_item.status == RentalItem.Status.RETURNED
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
            "fulfilment_actions": available_fulfilment_actions(rental_item),
        },
    )


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def employee_return_inspection(request, item_id):
    employee = get_employee_for_user(request.user)

    with transaction.atomic():
        rental_item = employee_rental_item_or_404(
            employee,
            item_id,
            for_update=request.method == "POST",
        )

        if (
            rental_item.order.payment_status
            != RentalOrder.PaymentStatus.PAID
            or rental_item.status != RentalItem.Status.RETURNED
        ):
            messages.error(
                request,
                "Only a paid, returned item can be inspected.",
            )
            return redirect(
                "vendor_portal:rental_detail",
                item_id=item_id,
            )

        if request.method == "POST":
            updated = RentalItem.objects.filter(
                pk=rental_item.pk,
                order__vendor=employee.vendor,
                status=RentalItem.Status.RETURNED,
                order__payment_status=RentalOrder.PaymentStatus.PAID,
            ).update(status=RentalItem.Status.RETURNED)

            if not updated:
                messages.error(
                    request,
                    "This rental changed. Reopen it and try again.",
                )
                return redirect(
                    "vendor_portal:rental_detail",
                    item_id=item_id,
                )

        rental_return = get_object_or_404(
            RentalReturn,
            rental_item=rental_item,
        )

        inspection = ReturnInspection.objects.filter(
            rental_return=rental_return
        ).first()

        if inspection and inspection.write_off_applied_at:
            messages.error(
                request,
                "This write-off has already been processed.",
            )
            return redirect(
                "vendor_portal:rental_detail",
                item_id=item_id,
            )

        if inspection is None:
            inspection = ReturnInspection(
                rental_return=rental_return,
            )

        inspection.inspected_by = employee

        form = ReturnInspectionForm(
            request.POST if request.method == "POST" else None,
            instance=inspection,
        )

        if request.method == "POST" and form.is_valid():
            inspection = form.save()
            ReturnInspection.objects.filter(
                pk=inspection.pk
            ).update(inspected_at=timezone.now())

            messages.success(
                request,
                "Inspection saved. Cleaning and damaged items remain "
                "on hold. Ready or written-off items can be completed.",
            )

            return redirect(
                "vendor_portal:rental_detail",
                item_id=item_id,
            )

    return render(
        request,
        "vendor_portal/return_inspection.html",
        {
            "vendor": employee.vendor,
            "rental_item": rental_item,
            "form": form,
        },
    )


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def employee_record_return(request, item_id):
    employee = get_employee_for_user(request.user)

    with transaction.atomic():
        rental_item = employee_rental_item_or_404(
            employee,
            item_id,
            for_update=request.method == "POST",
        )

        if (
            rental_item.order.payment_status
            != RentalOrder.PaymentStatus.PAID
            or rental_item.status not in {
                RentalItem.Status.ACTIVE,
                RentalItem.Status.OVERDUE,
            }
        ):
            messages.error(
                request,
                "Only a paid, active or overdue rental can be returned.",
            )
            return redirect(
                "vendor_portal:rental_detail",
                item_id=item_id,
            )

        if RentalReturn.objects.filter(
            rental_item=rental_item
        ).exists():
            messages.info(
                request,
                "A return has already been recorded for this item.",
            )
            return redirect(
                "vendor_portal:rental_detail",
                item_id=item_id,
            )

        return_record = RentalReturn(
            rental_item=rental_item,
            recorded_by=employee,
        )

        form = RentalReturnForm(
            request.POST if request.method == "POST" else None,
            instance=return_record,
        )

        if request.method == "POST" and form.is_valid():
            previous_status = rental_item.status
            rental_item.transition_to(RentalItem.Status.RETURNED)

            updated = RentalItem.objects.filter(
                pk=rental_item.pk,
                order__vendor=employee.vendor,
                order__payment_status=RentalOrder.PaymentStatus.PAID,
                status=previous_status,
            ).update(status=RentalItem.Status.RETURNED)

            if updated:
                form.save()

                messages.success(
                    request,
                    "Return recorded. The item remains unavailable "
                    "until inspection and completion.",
                )
                return redirect(
                    "vendor_portal:rental_detail",
                    item_id=item_id,
                )

            form.add_error(
                None,
                "This rental changed while you were working. "
                "Reopen the item and try again.",
            )

    return render(
        request,
        "vendor_portal/return_form.html",
        {
            "vendor": employee.vendor,
            "rental_item": rental_item,
            "form": form,
        },
    )


@login_required(login_url="accounts:login")
@require_POST
def employee_rental_transition(request, item_id):
    employee = get_employee_for_user(request.user)
    action = request.POST.get("action")

    with transaction.atomic():
        rental_item = employee_rental_item_or_404(
            employee,
            item_id,
            for_update=True,
        )

        allowed_actions = {
            entry["action"]
            for entry in available_fulfilment_actions(rental_item)
        }

        if action not in allowed_actions:
            messages.error(
                request,
                "That action is not available for this rental item's "
                "current status.",
            )
            return redirect(
                "vendor_portal:rental_detail",
                item_id=rental_item.pk,
            )

        previous_status = rental_item.status
        target_status, _ = FULFILMENT_ACTIONS[action]
        rental_item.transition_to(target_status)

        updated = RentalItem.objects.filter(
            pk=rental_item.pk,
            order__vendor=employee.vendor,
            order__payment_status=RentalOrder.PaymentStatus.PAID,
            status=previous_status,
        ).update(status=rental_item.status)

        if updated:
            messages.success(
                request,
                f"Rental item marked {rental_item.get_status_display()}.",
            )
        else:
            messages.error(
                request,
                "This rental changed while you were working. "
                "Review its current status and try again.",
            )

    return redirect(
        "vendor_portal:rental_detail",
        item_id=item_id,
    )


class CompleteRentalView(LoginRequiredMixin, View):
    login_url = "accounts:login"

    def post(self, request, item_id):
        employee = get_employee_for_user(request.user)

        try:
            with transaction.atomic():
                rental_item = employee_rental_item_or_404(
                    employee,
                    item_id,
                    for_update=True,
                )

                if RentalSettlement.objects.filter(
                    rental_item=rental_item
                ).exists():
                    messages.info(
                        request,
                        "This rental already has a simulated settlement.",
                    )
                    return redirect(
                        "vendor_portal:rental_detail",
                        item_id=item_id,
                    )

                if (
                    rental_item.order.payment_status
                    != RentalOrder.PaymentStatus.PAID
                    or rental_item.status != RentalItem.Status.RETURNED
                ):
                    raise ValidationError(
                        "Only a paid, returned item can be completed."
                    )

                rental_item.transition_to(RentalItem.Status.COMPLETED)

                updated = RentalItem.objects.filter(
                    pk=rental_item.pk,
                    order__vendor=employee.vendor,
                    status=RentalItem.Status.RETURNED,
                    order__payment_status=RentalOrder.PaymentStatus.PAID,
                ).update(status=RentalItem.Status.COMPLETED)

                if not updated:
                    raise ValidationError(
                        "This rental changed. Reopen it and try again."
                    )

                inspection = (
                    ReturnInspection.objects
                    .select_for_update()
                    .filter(rental_return__rental_item=rental_item)
                    .first()
                )

                if (
                    inspection is None
                    or inspection.condition not in {
                        ReturnInspection.Condition.READY,
                        ReturnInspection.Condition.WRITTEN_OFF,
                    }
                ):
                    raise ValidationError(
                        "Inspection must be Ready or Written Off."
                    )

                if (
                    inspection.condition
                    == ReturnInspection.Condition.WRITTEN_OFF
                    and inspection.write_off_applied_at is None
                ):
                    claimed = ReturnInspection.objects.filter(
                        pk=inspection.pk,
                        condition=ReturnInspection.Condition.WRITTEN_OFF,
                        write_off_applied_at__isnull=True,
                    ).update(write_off_applied_at=timezone.now())

                    if not claimed:
                        raise ValidationError(
                            "The inspection changed. Reopen it and try again."
                        )

                    stock_updated = ProductVariant.objects.filter(
                        pk=rental_item.variant_id,
                        total_quantity__gte=rental_item.quantity,
                    ).update(
                        total_quantity=(
                            F("total_quantity") - rental_item.quantity
                        )
                    )

                    if not stock_updated:
                        raise ValidationError(
                            "Physical stock is lower than the write-off "
                            "quantity. Check inventory before completing."
                        )

                settlement = RentalSettlement.build_for_item(rental_item)
                settlement.full_clean()
                settlement.save()

        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
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
        form.save_m2m()
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

@login_required(login_url="accounts:login")
def employee_rental_order_list(request):
    employee = get_employee_for_user(request.user)
    filter_form = RentalOrderFilterForm(request.GET)

    orders = (
        RentalOrder.objects
        .filter(vendor=employee.vendor)
        .select_related("customer")
        .prefetch_related("items__variant")
        .order_by("-created_at", "-pk")
    )

    if filter_form.is_valid():
        status = filter_form.cleaned_data["status"]
        date_from = filter_form.cleaned_data["date_from"]
        date_to = filter_form.cleaned_data["date_to"]

        item_filters = {}

        if status:
            item_filters["items__status"] = status

        if date_from:
            item_filters["items__rental_end_date__gte"] = date_from

        if date_to:
            item_filters["items__rental_start_date__lte"] = date_to

        if item_filters:
            orders = orders.filter(**item_filters).distinct()
    else:
        orders = orders.none()

    return render(
        request,
        "vendor_portal/rental_order_list.html",
        {
            "vendor": employee.vendor,
            "orders": orders,
            "filter_form": filter_form,
        },
    )


@login_required(login_url="accounts:login")
def employee_rental_order_detail(request, order_id):
    employee = get_employee_for_user(request.user)

    order = get_object_or_404(
        RentalOrder.objects
        .filter(vendor=employee.vendor)
        .select_related("customer")
        .prefetch_related("items__variant"),
        pk=order_id,
    )

    return render(
        request,
        "vendor_portal/rental_order_detail.html",
        {
            "vendor": employee.vendor,
            "order": order,
        },
    )