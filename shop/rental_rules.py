from django.core.exceptions import ValidationError


def calculate_rental_totals(
    *,
    daily_rate,
    quantity,
    start_date,
    end_date,
):
    if quantity < 1:
        raise ValidationError("Quantity must be at least 1.")

    rental_days = (end_date - start_date).days + 1

    if not 1 <= rental_days <= 7:
        raise ValidationError("Rentals must last between 1 and 7 days.")

    line_total = daily_rate * quantity * rental_days

    return rental_days, line_total


def mark_overdue_rentals(*, vendor=None, today=None):
    """Move paid Active items whose end date has passed to Overdue."""

    from django.utils import timezone

    from .models import RentalItem, RentalOrder

    today = today or timezone.localdate()
    late_items = RentalItem.objects.filter(
        status=RentalItem.Status.ACTIVE,
        rental_end_date__lt=today,
        order__payment_status=RentalOrder.PaymentStatus.PAID,
    )

    if vendor is not None:
        late_items = late_items.filter(order__vendor=vendor)

    return late_items.update(status=RentalItem.Status.OVERDUE)
