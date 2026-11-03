from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from .rental_rules import calculate_rental_totals


class RentalOrder(models.Model):
    class PaymentStatus(models.TextChoices):
        PENDING = "Pending", "Pending"
        PAID = "Paid", "Paid"
        FAILED = "Failed", "Failed"

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rental_orders",
    )
    vendor = models.ForeignKey(
        "shop.Vendor",
        on_delete=models.PROTECT,
        related_name="rental_orders",
    )

    delivery_address = models.TextField()

    payment_status = models.CharField(
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="rental_order_total_nonnegative",
            ),
        ]

    def __str__(self):
        return f"Rental order #{self.pk}"


class RentalItem(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "Confirmed", "Confirmed"
        PREPARING = "Preparing", "Preparing"
        DISPATCHED = "Dispatched", "Dispatched"
        ACTIVE = "Active", "Active"
        RETURNED = "Returned", "Returned"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"
        OVERDUE = "Overdue", "Overdue"

    DATE_BOUND_RESERVING_STATUSES = (
        Status.CONFIRMED,
        Status.PREPARING,
        Status.DISPATCHED,
        Status.ACTIVE,
    )

    order = models.ForeignKey(
        RentalOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )

    variant = models.ForeignKey(
        "shop.ProductVariant",
        on_delete=models.PROTECT,
        related_name="rental_items",
    )

    product_name_snapshot = models.CharField(max_length=150)

    daily_rate_snapshot = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    quantity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )

    rental_start_date = models.DateField()
    rental_end_date = models.DateField()

    rental_days = models.PositiveSmallIntegerField()

    line_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="rental_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(rental_days__gte=1)
                    & models.Q(rental_days__lte=7)
                ),
                name="rental_item_days_1_to_7",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    rental_end_date__gte=models.F("rental_start_date")
                ),
                name="rental_item_dates_in_order",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(daily_rate_snapshot__gt=0)
                    & models.Q(line_total__gte=0)
                ),
                name="rental_item_amounts_valid",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.rental_start_date
            and self.rental_end_date
            and self.quantity is not None
            and self.daily_rate_snapshot is not None
        ):
            expected_days, expected_total = calculate_rental_totals(
                daily_rate=self.daily_rate_snapshot,
                quantity=self.quantity,
                start_date=self.rental_start_date,
                end_date=self.rental_end_date,
            )

            errors = {}

            if self.rental_days != expected_days:
                errors["rental_days"] = (
                    "Rental days must match the inclusive date range."
                )

            if self.line_total != expected_total:
                errors["line_total"] = (
                    "Line total must match rate × quantity × rental days."
                )

            if errors:
                raise ValidationError(errors)

        if (
            self.order_id
            and self.variant_id
            and self.order.vendor_id != self.variant.product.vendor_id
        ):
            raise ValidationError({
                "variant": "This variant belongs to another vendor.",
            })

    def __str__(self):
        return f"{self.product_name_snapshot} × {self.quantity}"