from decimal import Decimal

from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models


class Vendor(models.Model):
    class ApprovalStatus(models.TextChoices):
        PENDING = "Pending", "Pending"
        APPROVED = "Approved", "Approved"
        REJECTED = "Rejected", "Rejected"

    name = models.CharField(max_length=150)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)

    approval_status = models.CharField(
        max_length=10,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    is_suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="products",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )

    name = models.CharField(max_length=150)
    description = models.TextField()
    brand = models.CharField(max_length=100)

    daily_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("3.00")),
            MaxValueValidator(Decimal("50.00")),
        ],
    )

    is_active = models.BooleanField(default=False)
    # Controlled by the vendor employee. Platform moderation must not alter it.
    is_published = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    moderation_blocked = models.BooleanField(default=False)
    moderation_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(daily_rate__gte=Decimal("3.00"))
                    & models.Q(daily_rate__lte=Decimal("50.00"))
                ),
                name="product_daily_rate_3_to_50",
            ),
        ]

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
    )

    sku = models.CharField(max_length=64, unique=True)
    size = models.CharField(max_length=20)
    colour = models.CharField(max_length=50)
    colour_hex = models.CharField(
        max_length=7,
        default="#A0A0A0",
        validators=[
            RegexValidator(
                regex=r"^#[0-9A-Fa-f]{6}$",
                message="Enter a colour such as #A9C77D.",
            ),
        ],
    )

    # Physical stock owned, not date-specific rental availability.
    total_quantity = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["size", "colour", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "size", "colour"],
                name="unique_product_size_colour",
            ),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.size} - {self.colour}"


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
    )

    image = models.ImageField(upload_to="products/%Y/%m/")
    alt_text = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"Image for {self.product.name}"
