from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from accounts.models import CustomerProfile, VendorEmployee
from accounts.roles import CUSTOMER_GROUP, VENDOR_EMPLOYEE_GROUP
from shop.models import (
    Category,
    Product,
    ProductVariant,
    RentalItem,
    RentalOrder,
    Vendor,
)


TEST_PASSWORD = "Test-pass-7429!"


def make_user(username, role=CUSTOMER_GROUP):
    user = get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password=TEST_PASSWORD,
    )
    if role:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)
    if role == CUSTOMER_GROUP:
        CustomerProfile.objects.create(user=user)
    return user


def make_vendor(name="Test Vendor"):
    return Vendor.objects.create(
        name=name,
        contact_email=f"{name.lower().replace(' ', '-')}@example.com",
        approval_status=Vendor.ApprovalStatus.APPROVED,
    )


def make_employee(username, vendor, *, is_vendor_admin=False):
    user = make_user(username, VENDOR_EMPLOYEE_GROUP)
    employee = VendorEmployee.objects.create(
        user=user,
        vendor=vendor,
        is_vendor_admin=is_vendor_admin,
    )
    return user, employee


def make_variant(prefix, *, vendor=None, rate="10.00", stock=3):
    vendor = vendor or make_vendor(f"{prefix} Vendor")
    category, _ = Category.objects.get_or_create(name="Test Clothing")
    product = Product.objects.create(
        vendor=vendor,
        category=category,
        name=f"{prefix} Product",
        description="Test rental product",
        brand=vendor.name,
        daily_rate=Decimal(rate),
        is_active=True,
        is_published=True,
    )
    variant = ProductVariant.objects.create(
        product=product,
        sku=f"{prefix}-sku",
        size="M",
        colour="Black",
        total_quantity=stock,
    )
    return vendor, product, variant


def make_rental_item(
    prefix,
    *,
    customer=None,
    vendor=None,
    variant=None,
    status=RentalItem.Status.CONFIRMED,
    quantity=1,
):
    customer = customer or make_user(f"{prefix}-customer")
    if variant is None:
        vendor, _, variant = make_variant(prefix, vendor=vendor)
    else:
        vendor = vendor or variant.product.vendor

    start = timezone.localdate() + timedelta(days=1)
    end = start + timedelta(days=1)
    line_total = variant.product.daily_rate * quantity * 2
    order = RentalOrder.objects.create(
        customer=customer,
        vendor=vendor,
        delivery_address="1 Test Street",
        payment_status=RentalOrder.PaymentStatus.PAID,
        total_amount=line_total,
    )
    item = RentalItem.objects.create(
        order=order,
        variant=variant,
        product_name_snapshot=variant.product.name,
        daily_rate_snapshot=variant.product.daily_rate,
        quantity=quantity,
        rental_start_date=start,
        rental_end_date=end,
        rental_days=2,
        line_total=line_total,
        status=status,
    )
    return order, item
