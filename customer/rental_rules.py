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