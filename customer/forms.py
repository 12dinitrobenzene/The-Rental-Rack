"""Forms for customer catalogue workflows."""

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from shop.models import ProductVariant

from .rental_rules import calculate_rental_totals


class CatalogueFilterForm(forms.Form):
    q = forms.CharField(
        label="Search clothing",
        required=False,
        widget=forms.SearchInput(
            attrs={
                "class": "form-control",
                "placeholder": "Search names or descriptions",
            }
        ),
    )
    category = forms.ChoiceField(
        label="Category",
        required=False,
        choices=(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    vendor = forms.ChoiceField(
        label="Vendor",
        required=False,
        choices=(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    size = forms.ChoiceField(
        label="Size",
        required=False,
        choices=(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    min_price = forms.DecimalField(
        label="Minimum daily price (SGD)",
        required=False,
        min_value=Decimal("3.00"),
        max_value=Decimal("50.00"),
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.01", "min": "3", "max": "50"}
        ),
    )
    max_price = forms.DecimalField(
        label="Maximum daily price (SGD)",
        required=False,
        min_value=Decimal("3.00"),
        max_value=Decimal("50.00"),
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.01", "min": "3", "max": "50"}
        ),
    )
    sort = forms.ChoiceField(
        label="Sort by",
        required=False,
        choices=(
            ("", "Recommended"),
            ("newest", "Newest"),
            ("price_low", "Price: low to high"),
            ("price_high", "Price: high to low"),
        ),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, categories, vendors, sizes, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = [("", "All categories")] + [
            (str(category.pk), category.name) for category in categories
        ]
        self.fields["vendor"].choices = [("", "All vendors")] + [
            (str(vendor.pk), vendor.name) for vendor in vendors
        ]
        self.fields["size"].choices = [("", "All sizes")] + [
            (size, size) for size in sizes
        ]

    def clean(self):
        cleaned_data = super().clean()
        min_price = cleaned_data.get("min_price")
        max_price = cleaned_data.get("max_price")

        if min_price is not None and max_price is not None and min_price > max_price:
            self.add_error("max_price", "Maximum price must be at least the minimum.")

        return cleaned_data


class RentalSelectionForm(forms.Form):
    variant_id = forms.ModelChoiceField(
        queryset=ProductVariant.objects.none(),
        widget=forms.HiddenInput(
            attrs={"data-variant-input": ""}
        ),
        error_messages={
            "required": "Please choose a colour and size.",
            "invalid_choice": "That variant is not available.",
        },
    )

    start_date = forms.DateField(
        label="Rental start",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"}
        ),
    )

    end_date = forms.DateField(
        label="Rental end",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"}
        ),
    )

    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": 1}
        ),
    )

    def __init__(self, *args, product, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product

        self.fields["variant_id"].queryset = (
            product.variants.filter(
                is_active=True,
                total_quantity__gt=0,
            )
        )

        today = timezone.localdate().isoformat()

        for name in ("start_date", "end_date"):
            self.fields[name].widget.attrs["min"] = today

    def clean(self):
        data = super().clean()

        start = data.get("start_date")
        end = data.get("end_date")
        quantity = data.get("quantity")

        if start and start < timezone.localdate():
            self.add_error(
                "start_date",
                "Rental dates cannot start in the past.",
            )
            return data

        if start and end and quantity is not None:
            try:
                days, total = calculate_rental_totals(
                    daily_rate=self.product.daily_rate,
                    quantity=quantity,
                    start_date=start,
                    end_date=end,
                )
            except ValidationError as error:
                self.add_error("end_date", error)
            else:
                data["rental_days"] = days
                data["line_total"] = total

        return data
