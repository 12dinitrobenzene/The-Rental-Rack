CUSTOMER_GROUP = "Customer"
VENDOR_EMPLOYEE_GROUP = "Vendor Employee"
PLATFORM_ADMIN_GROUP = "Platform Admin"

APPLICATION_ROLE_GROUPS = (
    CUSTOMER_GROUP,
    VENDOR_EMPLOYEE_GROUP,
    PLATFORM_ADMIN_GROUP,
)


ROLE_DESTINATIONS = {
    CUSTOMER_GROUP: "customer:home",
    VENDOR_EMPLOYEE_GROUP: "vendor_portal:home",
    PLATFORM_ADMIN_GROUP: "staff_portal:home",
}


def role_for_user(user):
    if not user.is_authenticated:
        return None

    if user.is_superuser:
        return PLATFORM_ADMIN_GROUP

    role_names = set(
        user.groups.filter(name__in=APPLICATION_ROLE_GROUPS).values_list(
            "name",
            flat=True,
        )
    )

    if len(role_names) != 1:
        return None

    return role_names.pop()


def destination_for_user(user):
    role_name = role_for_user(user)
    return ROLE_DESTINATIONS.get(role_name)


def user_has_role(user, role_name):
    return user.is_authenticated and user.groups.filter(name=role_name).exists()
