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


def peak_reserved_quantity(*, variant, today=None):
    """Return the most units of this variant held on any day from today on."""

    today = today or timezone.localdate()

    bookings = list(
        RentalItem.objects.filter(
            variant=variant,
            order__payment_status=RentalOrder.PaymentStatus.PAID,
        )
        .filter(
            Q(
                status__in=RentalItem.DATE_BOUND_RESERVING_STATUSES,
                rental_end_date__gte=today,
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

    held_every_day = sum(
        item.quantity
        for item in bookings
        if item.status in RentalItem.OPEN_ENDED_RESERVING_STATUSES
        or item.rental_end_date < today
    )
    dated = [
        item
        for item in bookings
        if item.status not in RentalItem.OPEN_ENDED_RESERVING_STATUSES
        and item.rental_end_date >= today
    ]

    peak_dated = 0
    day = today
    last_day = max((item.rental_end_date for item in dated), default=today)

    while day <= last_day:
        held_today = sum(
            item.quantity
            for item in dated
            if item.rental_start_date <= day <= item.rental_end_date
        )
        peak_dated = max(peak_dated, held_today)
        day += timedelta(days=1)

    return held_every_day + peak_dated
