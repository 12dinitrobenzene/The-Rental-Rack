from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
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


class StyleTag(models.Model):
    slug = models.SlugField(unique=True)
    display_name = models.CharField(max_length=100)

    class Meta:
        ordering = ["display_name", "pk"]

    def __str__(self):
        return self.display_name


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
    style_tags = models.ManyToManyField(
        StyleTag,
        related_name="products",
        blank=True,
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


class CustomerStyleProfile(models.Model):
    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="style_profile",
    )

    silhouette = models.CharField(max_length=50)
    details = models.CharField(max_length=50)
    impression = models.CharField(max_length=50)
    styling_approach = models.CharField(max_length=50)
    statement_level = models.CharField(max_length=20)
    palette = models.CharField(max_length=30)

    predicted_style = models.ForeignKey(
        StyleTag,
        on_delete=models.PROTECT,
        related_name="customer_profiles",
    )

    model_version = models.CharField(max_length=30)
    predicted_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Style profile for {self.customer}"


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


class RentalOrder(models.Model):
    class PaymentStatus(models.TextChoices):
        PENDING = "Pending", "Pending"
        PAID = "Paid", "Paid"
        FAILED = "Failed", "Failed"
        REFUNDED = "Refunded", "Refunded"

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rental_orders",
    )
    vendor = models.ForeignKey(
        Vendor,
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
    OPEN_ENDED_RESERVING_STATUSES = (
        Status.OVERDUE,
        Status.RETURNED,
    )
    ALLOWED_STATUS_TRANSITIONS = {
        Status.CONFIRMED: {Status.PREPARING, Status.CANCELLED},
        Status.PREPARING: {Status.DISPATCHED, Status.CANCELLED},
        Status.DISPATCHED: {Status.ACTIVE},
        Status.ACTIVE: {Status.RETURNED, Status.OVERDUE},
        Status.OVERDUE: {Status.RETURNED},
        Status.RETURNED: {Status.COMPLETED},
        Status.COMPLETED: set(),
        Status.CANCELLED: set(),
    }

    order = models.ForeignKey(
        RentalOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.PROTECT,
        related_name="rental_items",
    )
    product_name_snapshot = models.CharField(max_length=150)
    daily_rate_snapshot = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    commission_rate_snapshot = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.2000"),
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
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
            models.CheckConstraint(
                condition=(
                    models.Q(commission_rate_snapshot__gte=0)
                    & models.Q(commission_rate_snapshot__lte=1)
                ),
                name="rental_item_commission_rate_valid",
            ),
        ]

    def can_transition_to(self, new_status):
        return new_status in self.ALLOWED_STATUS_TRANSITIONS.get(
            self.status,
            set(),
        )

    def transition_to(self, new_status):
        if not self.can_transition_to(new_status):
            raise ValidationError({
                "status": (
                    f"Cannot move a rental item from {self.status} "
                    f"to {new_status}."
                ),
            })

        self.status = new_status

    def clean(self):
        super().clean()

        if (
            self.rental_start_date
            and self.rental_end_date
            and self.quantity is not None
            and self.daily_rate_snapshot is not None
        ):
            from .rental_rules import calculate_rental_totals

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


class RentalReturn(models.Model):
    rental_item = models.OneToOneField(
        RentalItem,
        on_delete=models.CASCADE,
        related_name="rental_return",
    )
    returned_on = models.DateField()
    recorded_by = models.ForeignKey(
        "accounts.VendorEmployee",
        on_delete=models.PROTECT,
        related_name="recorded_returns",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.rental_item_id
            and self.returned_on
            and self.returned_on < self.rental_item.rental_start_date
        ):
            errors["returned_on"] = (
                "Return date cannot be before the rental start date."
            )

        if (
            self.rental_item_id
            and self.recorded_by_id
            and self.recorded_by.vendor_id
            != self.rental_item.order.vendor_id
        ):
            errors["recorded_by"] = (
                "The return must be recorded by this order's vendor."
            )

        if (
            self.rental_item_id
            and self.rental_item.status
            not in {
                RentalItem.Status.ACTIVE,
                RentalItem.Status.OVERDUE,
                RentalItem.Status.RETURNED,
            }
        ):
            errors["rental_item"] = (
                "Only active, overdue or returned items can record a return."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Return for rental item #{self.rental_item_id}"


class ReturnInspection(models.Model):
    class Condition(models.TextChoices):
        READY = "Ready", "Ready for reuse"
        CLEANING = "Cleaning", "Cleaning required"
        DAMAGED = "Damaged", "Damaged"
        WRITTEN_OFF = "WrittenOff", "Written off"

    rental_return = models.OneToOneField(
        RentalReturn,
        on_delete=models.CASCADE,
        related_name="inspection",
    )
    condition = models.CharField(
        max_length=12,
        choices=Condition.choices,
    )
    notes = models.TextField(blank=True)
    inspected_by = models.ForeignKey(
        "accounts.VendorEmployee",
        on_delete=models.PROTECT,
        related_name="return_inspections",
    )
    inspected_at = models.DateTimeField(auto_now_add=True)
    write_off_applied_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(write_off_applied_at__isnull=True)
                    | models.Q(condition="WrittenOff")
                ),
                name="inspection_writeoff_timestamp_valid",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.rental_return_id
            and self.inspected_by_id
            and self.inspected_by.vendor_id
            != self.rental_return.rental_item.order.vendor_id
        ):
            errors["inspected_by"] = (
                "The inspection must be performed by this order's vendor."
            )

        if (
            self.write_off_applied_at
            and self.condition != self.Condition.WRITTEN_OFF
        ):
            errors["write_off_applied_at"] = (
                "Stock adjustment applies only to written-off items."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Inspection for rental item #{self.rental_return.rental_item_id}"


class RentalSettlement(models.Model):
    rental_item = models.OneToOneField(
        RentalItem,
        on_delete=models.CASCADE,
        related_name="settlement",
    )
    commission_rate_snapshot = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[
            MinValueValidator(Decimal("0.0000")),
            MaxValueValidator(Decimal("1.0000")),
        ],
    )
    platform_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    vendor_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(commission_rate_snapshot__gte=0)
                    & models.Q(commission_rate_snapshot__lte=1)
                ),
                name="settlement_commission_rate_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(platform_amount__gte=0)
                    & models.Q(vendor_amount__gte=0)
                ),
                name="settlement_amounts_nonnegative",
            ),
        ]

    @classmethod
    def has_eligible_inspection(cls, rental_item):
        rental_return = getattr(rental_item, "rental_return", None)
        inspection = (
            getattr(rental_return, "inspection", None)
            if rental_return
            else None
        )
        return (
            inspection is not None
            and inspection.condition
            in {
                ReturnInspection.Condition.READY,
                ReturnInspection.Condition.WRITTEN_OFF,
            }
        )

    @classmethod
    def calculate_amounts(cls, rental_item):
        platform_amount = (
            rental_item.line_total
            * rental_item.commission_rate_snapshot
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        vendor_amount = rental_item.line_total - platform_amount
        return platform_amount, vendor_amount

    @classmethod
    def build_for_item(cls, rental_item):
        platform_amount, vendor_amount = cls.calculate_amounts(rental_item)
        return cls(
            rental_item=rental_item,
            commission_rate_snapshot=(
                rental_item.commission_rate_snapshot
            ),
            platform_amount=platform_amount,
            vendor_amount=vendor_amount,
        )

    @property
    def platform_percentage(self):
        return self.commission_rate_snapshot * Decimal("100")

    @property
    def vendor_percentage(self):
        return Decimal("100") - self.platform_percentage

    def clean(self):
        super().clean()
        errors = {}

        if self.rental_item_id:
            rental_item = self.rental_item
            rental_return = getattr(
                rental_item,
                "rental_return",
                None,
            )
            inspection = (
                getattr(rental_return, "inspection", None)
                if rental_return
                else None
            )

            if (
                inspection is not None
                and inspection.condition
                == ReturnInspection.Condition.WRITTEN_OFF
                and inspection.write_off_applied_at is None
            ):
                errors["rental_item"] = (
                    "Process the write-off before creating settlement."
                )

            if rental_item.status != RentalItem.Status.COMPLETED:
                errors["rental_item"] = (
                    "Settlement requires a completed rental item."
                )

            if not self.has_eligible_inspection(rental_item):
                errors["rental_item"] = (
                    "Settlement requires an eligible return inspection."
                )

            if (
                self.commission_rate_snapshot is not None
                and self.commission_rate_snapshot
                != rental_item.commission_rate_snapshot
            ):
                errors["commission_rate_snapshot"] = (
                    "Settlement rate must match the rental item snapshot."
                )

            if (
                self.commission_rate_snapshot is not None
                and rental_item.line_total is not None
            ):
                expected_platform, expected_vendor = (
                    self.calculate_amounts(rental_item)
                )

                if self.platform_amount != expected_platform:
                    errors["platform_amount"] = (
                        "Platform amount does not match the saved rate."
                    )

                if self.vendor_amount != expected_vendor:
                    errors["vendor_amount"] = (
                        "Vendor amount must reconcile with the line total."
                    )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Settlement for rental item #{self.rental_item_id}"
