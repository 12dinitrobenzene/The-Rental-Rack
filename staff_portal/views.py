from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import require_platform_admin
from shop.models import Vendor


@login_required(login_url="accounts:login")
def platform_admin_home(request):
    require_platform_admin(request.user)

    return render(request, "staff_portal/home.html")


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
