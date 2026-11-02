from django.db.models import Prefetch

from .models import Product, ProductVariant, Vendor


def visible_products():
    return (
        Product.objects.filter(
            is_active=True,
            is_archived=False,
            moderation_blocked=False,
            vendor__approval_status=Vendor.ApprovalStatus.APPROVED,
            vendor__is_suspended=False,
            variants__is_active=True,
        )
        .select_related("vendor", "category")
        .prefetch_related(
            "images",
            Prefetch(
                "variants",
                queryset=ProductVariant.objects.filter(
                    is_active=True,
                    total_quantity__gt=0,
                ),
                to_attr="active_variants",
            ),
        )
        .distinct()
    )
