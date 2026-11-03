from django.core.exceptions import PermissionDenied

from .models import VendorEmployee
from .roles import (
    CUSTOMER_GROUP,
    PLATFORM_ADMIN_GROUP,
    VENDOR_EMPLOYEE_GROUP,
    role_for_user,
)


def get_employee_for_user(user):
    if (
        not user.is_authenticated
        or not user.is_active
        or role_for_user(user) != VENDOR_EMPLOYEE_GROUP
    ):
        raise PermissionDenied("Vendor employee access is required.")

    try:
        return VendorEmployee.objects.select_related("vendor").get(
            user=user
        )
    except VendorEmployee.DoesNotExist:
        raise PermissionDenied(
            "Your account is not linked to a vendor."
        )


def get_vendor_admin_for_user(user):
    employee = get_employee_for_user(user)

    if not employee.is_vendor_admin:
        raise PermissionDenied("Vendor manager access is required.")

    return employee


def require_platform_admin(user):
    if (
        not user.is_authenticated
        or not user.is_active
        or role_for_user(user) != PLATFORM_ADMIN_GROUP
    ):
        raise PermissionDenied(
            "Platform administrator access is required."
        )


def require_customer(user):
    if (
        not user.is_authenticated
        or not user.is_active
        or role_for_user(user) != CUSTOMER_GROUP
    ):
        raise PermissionDenied("Customer access is required.")
