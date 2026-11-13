from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import RentalItem, RentalOrder


def available_quantity_by_day(*, variant, start_date, end_date):
    """Return remaining units per day for an already-validated period."""

    if end_date < start_date:
        raise ValidationError("End date cannot be before start date.")

    today = timezone.localdate()

    bookings = list(
        RentalItem.objects.filter(
            variant=variant,
            order__payment_status=RentalOrder.PaymentStatus.PAID,
        )
        .filter(
            Q(
                status__in=RentalItem.DATE_BOUND_RESERVING_STATUSES,
                rental_start_date__lte=end_date,
                rental_end_date__gte=start_date,
            )
            | Q(status__in=RentalItem.OPEN_ENDED_RESERVING_STATUSES)
            | Q(
                status=RentalItem.Status.ACTIVE,
                rental_end_date__lt=today,
            )
        )
        .only(
            "status",
            "quantity",
            "rental_start_date",
            "rental_end_date",
        )
    )

    availability = {}
    day = start_date

    while day <= end_date:
        reserved = sum(
            item.quantity
            for item in bookings
            if (
                item.status in RentalItem.OPEN_ENDED_RESERVING_STATUSES
                or (
                    item.status == RentalItem.Status.ACTIVE
                    and item.rental_end_date < today
                )
                or item.rental_start_date <= day <= item.rental_end_date
            )
        )

        availability[day] = max(
            variant.total_quantity - reserved,
            0,
        )

        day += timedelta(days=1)

    return availability
