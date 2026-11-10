from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import require_platform_admin
from shop.models import (
    RentalItem,
    RentalOrder,
    RentalSettlement,
    Vendor,
)
from shop.visibility import visible_products


@login_required(login_url="accounts:login")
def platform_admin_home(request):
    require_platform_admin(request.user)

    settlement_totals = RentalSettlement.objects.aggregate(
        platform_commission=Sum("platform_amount"),
        vendor_payout=Sum("vendor_amount"),
    )
    platform_commission = (
        settlement_totals["platform_commission"]
        or Decimal("0.00")
    )
    vendor_payout = (
        settlement_totals["vendor_payout"]
        or Decimal("0.00")
    )

    vendor_performance = (
        Vendor.objects.annotate(
            settled_items=Count(
                "rental_orders__items__settlement",
            ),
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
            settled_gross=(
                F("platform_commission") + F("vendor_payout")
            ),
        )
        .order_by("-settled_gross", "name", "pk")
    )

    recent_orders = (
        RentalOrder.objects.select_related("customer", "vendor")
        .annotate(item_count=Count("items"))
        .order_by("-created_at", "-pk")[:5]
    )

    return render(
        request,
        "staff_portal/home.html",
        {
            "approved_vendors": Vendor.objects.filter(
                approval_status=Vendor.ApprovalStatus.APPROVED,
            ).count(),
            "suspended_vendors": Vendor.objects.filter(
                is_suspended=True,
            ).count(),
            "visible_listings": visible_products().count(),
            "rental_orders": RentalOrder.objects.count(),
            "completed_rental_items": RentalItem.objects.filter(
                status=RentalItem.Status.COMPLETED,
            ).count(),
            "platform_commission": platform_commission,
            "vendor_payout": vendor_payout,
            "settled_gross": platform_commission + vendor_payout,
            "vendor_performance": vendor_performance,
            "recent_orders": recent_orders,
        },
    )


@login_required(login_url="accounts:login")
def platform_vendor_list(request):
    require_platform_admin(request.user)

    vendors = Vendor.objects.order_by("name", "pk")

    return render(
        request,
        "staff_portal/vendors.html",
        {"vendors": vendors},
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
