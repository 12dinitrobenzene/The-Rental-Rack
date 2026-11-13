from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Prefetch, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from accounts.permissions import require_platform_admin
from shop.models import (
    Product,
    RentalItem,
    RentalOrder,
    RentalSettlement,
    Vendor,
)
from shop.visibility import visible_products

from .forms import (
    ListingModerationFilterForm,
    ListingModerationForm,
    PlatformRentalFilterForm,
    SettlementFilterForm,
)

# Drafts stay with the vendor until published; blocked listings stay reachable
# so platform admins can always unblock them.
MODERATABLE_LISTINGS = (
    Q(is_published=True)
    | Q(is_archived=True)
    | Q(moderation_blocked=True)
)


def platform_financial_totals():
    totals = RentalSettlement.objects.aggregate(
        platform_commission=Sum("platform_amount"),
        vendor_payout=Sum("vendor_amount"),
    )
    platform_commission = (
        totals["platform_commission"] or Decimal("0.00")
    )
    vendor_payout = totals["vendor_payout"] or Decimal("0.00")

    return {
        "platform_commission": platform_commission,
        "vendor_payout": vendor_payout,
        "settled_gross": platform_commission + vendor_payout,
    }


@login_required(login_url="accounts:login")
def platform_admin_home(request):
    require_platform_admin(request.user)
    financial_totals = platform_financial_totals()

    return render(
        request,
        "staff_portal/home.html",
        {
            "approved_vendors": Vendor.objects.filter(
                approval_status=Vendor.ApprovalStatus.APPROVED,
            ).count(),
            "pending_vendors": Vendor.objects.filter(
                approval_status=Vendor.ApprovalStatus.PENDING,
            ).count(),
            "suspended_vendors": Vendor.objects.filter(
                is_suspended=True,
            ).count(),
            "visible_listings": visible_products().count(),
            "blocked_listings": Product.objects.filter(
                moderation_blocked=True,
            ).count(),
            "rental_orders": RentalOrder.objects.count(),
            "active_rental_items": RentalItem.objects.filter(
                status__in=[
                    RentalItem.Status.ACTIVE,
                    RentalItem.Status.OVERDUE,
                ],
            ).count(),
            "completed_rental_items": RentalItem.objects.filter(
                status=RentalItem.Status.COMPLETED,
            ).count(),
            "payment_count": RentalSettlement.objects.count(),
            **financial_totals,
        },
    )


@login_required(login_url="accounts:login")
def platform_performance(request):
    require_platform_admin(request.user)

    vendor_performance = (
        Vendor.objects.annotate(
            settled_items=Count("rental_orders__items__settlement"),
            platform_commission=Sum(
                "rental_orders__items__settlement__platform_amount",
                default=Decimal("0.00"),
            ),
            vendor_payout=Sum(
                "rental_orders__items__settlement__vendor_amount",
                default=Decimal("0.00"),
            ),
        )
        .annotate(
            settled_gross=F("platform_commission") + F("vendor_payout"),
        )
        .order_by("-settled_gross", "name", "pk")
    )

    category_performance = (
        RentalSettlement.objects
        .values(
            category_name=F("rental_item__variant__product__category__name"),
        )
        .annotate(
            settled_items=Count("pk"),
            rented_units=Sum("rental_item__quantity"),
            platform_commission=Sum("platform_amount"),
            vendor_payout=Sum("vendor_amount"),
        )
        .annotate(
            settled_gross=F("platform_commission") + F("vendor_payout"),
        )
        .order_by("-settled_gross", "category_name")
    )

    monthly_trend = list(
        RentalSettlement.objects
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(
            settled_items=Count("pk"),
            platform_commission=Sum("platform_amount"),
            vendor_payout=Sum("vendor_amount"),
        )
        .annotate(
            settled_gross=F("platform_commission") + F("vendor_payout"),
        )
        .order_by("month")
    )

    previous_gross = None

    for month in monthly_trend:
        month["change"] = (
            None
            if previous_gross is None
            else month["settled_gross"] - previous_gross
        )
        previous_gross = month["settled_gross"]

    recent_orders = (
        RentalOrder.objects.select_related("customer", "vendor")
        .annotate(item_count=Count("items"))
        .order_by("-created_at", "-pk")[:5]
    )

    return render(
        request,
        "staff_portal/performance.html",
        {
            "vendor_performance": vendor_performance,
            "category_performance": category_performance,
            "monthly_trend": monthly_trend,
            "recent_orders": recent_orders,
            **platform_financial_totals(),
        },
    )


@login_required(login_url="accounts:login")
def platform_vendor_list(request):
    require_platform_admin(request.user)

    vendors = Vendor.objects.order_by("name", "pk")
    vendor_view = request.GET.get("view", "all")

    if vendor_view == "new":
        vendors = vendors.filter(
            approval_status=Vendor.ApprovalStatus.PENDING,
            is_suspended=False,
        )
    elif vendor_view == "current":
        vendors = vendors.filter(
            approval_status=Vendor.ApprovalStatus.APPROVED,
            is_suspended=False,
        )
    elif vendor_view == "suspended":
        vendors = vendors.filter(is_suspended=True)
    else:
        vendor_view = "all"

    return render(
        request,
        "staff_portal/vendors.html",
        {"vendors": vendors, "vendor_view": vendor_view},
    )


@login_required(login_url="accounts:login")
def platform_rental_order_list(request):
    require_platform_admin(request.user)
    filter_form = PlatformRentalFilterForm(request.GET)

    orders = (
        RentalOrder.objects.select_related("customer", "vendor")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=RentalItem.objects.select_related(
                    "variant__product",
                ),
            )
        )
        .order_by("-created_at", "-pk")
    )

    if filter_form.is_valid():
        vendor = filter_form.cleaned_data["vendor"]
        customer = filter_form.cleaned_data["customer"]
        status = filter_form.cleaned_data["status"]
        date_from = filter_form.cleaned_data["date_from"]
        date_to = filter_form.cleaned_data["date_to"]

        if vendor:
            orders = orders.filter(vendor=vendor)

        if customer:
            orders = orders.filter(
                Q(customer__username__icontains=customer)
                | Q(customer__email__icontains=customer)
            )

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
        "staff_portal/rental_orders.html",
        {
            "filter_form": filter_form,
            "orders": orders,
        },
    )


@login_required(login_url="accounts:login")
@require_GET
def platform_settlement_list(request):
    require_platform_admin(request.user)
    filter_form = SettlementFilterForm(request.GET)

    settlements = RentalSettlement.objects.select_related(
        "rental_item__order__customer",
        "rental_item__order__vendor",
        "rental_item__variant",
    ).order_by("-created_at", "-pk")

    if filter_form.is_valid():
        vendor = filter_form.cleaned_data["vendor"]
        date_from = filter_form.cleaned_data["date_from"]
        date_to = filter_form.cleaned_data["date_to"]

        if vendor:
            settlements = settlements.filter(
                rental_item__order__vendor=vendor,
            )

        if date_from:
            settlements = settlements.filter(
                created_at__date__gte=date_from,
            )

        if date_to:
            settlements = settlements.filter(
                created_at__date__lte=date_to,
            )
    else:
        settlements = settlements.none()

    totals = settlements.aggregate(
        platform_amount=Sum("platform_amount"),
        vendor_amount=Sum("vendor_amount"),
    )
    platform_amount = totals["platform_amount"] or Decimal("0.00")
    vendor_amount = totals["vendor_amount"] or Decimal("0.00")

    return render(
        request,
        "staff_portal/settlements.html",
        {
            "filter_form": filter_form,
            "settlements": settlements,
            "settlement_count": settlements.count(),
            "gross_amount": platform_amount + vendor_amount,
            "platform_amount": platform_amount,
            "vendor_amount": vendor_amount,
        },
    )


@login_required(login_url="accounts:login")
@require_POST
def platform_vendor_action(request, vendor_id):
    require_platform_admin(request.user)

    vendor = get_object_or_404(Vendor, pk=vendor_id)
    action = request.POST.get("action")

    if action == "approve":
        vendor.approval_status = Vendor.ApprovalStatus.APPROVED
        vendor.save(update_fields=["approval_status"])

        messages.success(request, f"{vendor.name} has been approved.")

    elif action == "suspend":
        vendor.is_suspended = True
        vendor.save(update_fields=["is_suspended"])

        messages.success(request, f"{vendor.name} has been suspended.")

    elif action == "restore":
        vendor.is_suspended = False
        vendor.save(update_fields=["is_suspended"])

        messages.success(request, f"{vendor.name} has been restored.")

    else:
        return HttpResponseBadRequest("Unknown vendor action.")

    return redirect("staff_portal:vendor_list")


@login_required(login_url="accounts:login")
@require_GET
def platform_listing_list(request):
    require_platform_admin(request.user)
    filter_form = ListingModerationFilterForm(request.GET)

    products = (
        Product.objects.filter(MODERATABLE_LISTINGS)
        .select_related("vendor", "category")
        .order_by("-moderation_blocked", "vendor__name", "name", "pk")
    )

    if filter_form.is_valid():
        query = filter_form.cleaned_data["q"]
        vendor = filter_form.cleaned_data["vendor"]
        status = filter_form.cleaned_data["status"]

        if query:
            products = products.filter(
                Q(name__icontains=query) | Q(brand__icontains=query)
            )
        if vendor:
            products = products.filter(vendor=vendor)
        if status == "blocked":
            products = products.filter(moderation_blocked=True)
        elif status == "allowed":
            products = products.filter(moderation_blocked=False)
    else:
        products = products.none()

    return render(
        request,
        "staff_portal/listings.html",
        {"filter_form": filter_form, "products": products},
    )


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def platform_listing_moderate(request, product_id):
    require_platform_admin(request.user)

    product = get_object_or_404(
        Product.objects.select_related("vendor", "category").filter(
            MODERATABLE_LISTINGS,
        ),
        pk=product_id,
    )

    if request.method == "GET":
        return render(
            request,
            "staff_portal/listing_review.html",
            {"product": product},
        )

    form = ListingModerationForm(request.POST)

    if not form.is_valid():
        first_error = next(
            error
            for errors in form.errors.values()
            for error in errors
        )
        messages.error(request, first_error)
        return redirect("staff_portal:listing_list")

    if form.cleaned_data["action"] == "block":
        product.moderation_blocked = True
        product.moderation_reason = form.cleaned_data["reason"]
        message = f"{product.name} has been blocked."
    else:
        product.moderation_blocked = False
        product.moderation_reason = ""
        message = f"{product.name} has been unblocked."

    product.save(
        update_fields=["moderation_blocked", "moderation_reason", "updated_at"]
    )
    messages.success(request, message)
    return redirect("staff_portal:listing_list")
