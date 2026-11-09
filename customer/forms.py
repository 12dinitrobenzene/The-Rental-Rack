"""Forms for customer catalogue workflows."""

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from shop.models import ProductVariant

from shop.rental_rules import calculate_rental_totals


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


class RentalPeriodForm(forms.Form):
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

    def __init__(self, *args, daily_rate, **kwargs):
        super().__init__(*args, **kwargs)
        self.daily_rate = daily_rate

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
                    daily_rate=self.daily_rate,
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


class RentalSelectionForm(RentalPeriodForm):
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

    def __init__(self, *args, product, **kwargs):
        super().__init__(
            *args,
            daily_rate=product.daily_rate,
            **kwargs,
        )
        self.product = product
        self.fields["variant_id"].queryset = (
            product.variants.filter(
                is_active=True,
                total_quantity__gt=0,
            )
        )


class CartUpdateForm(RentalPeriodForm):
    """Validate editable cart values without accepting any prices."""


class CheckoutForm(forms.Form):
    delivery_address = forms.CharField(
        label="Delivery address",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 4}
        ),
    )
    confirm_payment = forms.BooleanField(
        label="Confirm simulated payment",
        help_text="No payment-card details are required or stored.",
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input"}
        ),
    )


SILHOUETTE_CHOICES = (
    ("clean_fitted", "Clean and fitted"),
    ("tailored_structured", "Tailored and structured"),
    ("oversized_relaxed", "Oversized and relaxed"),
    ("soft_flowing", "Soft and flowing"),
    ("sculptural_asymmetric", "Sculptural or asymmetric"),
)

DETAIL_CHOICES = (
    ("minimal_details", "Minimal details"),
    ("refined_details", "Refined details"),
    ("graphic_details", "Graphic details"),
    ("delicate_details", "Delicate details"),
    ("experimental_details", "Experimental details"),
)

IMPRESSION_CHOICES = (
    ("understated", "Understated"),
    ("polished", "Polished"),
    ("cool_urban", "Cool and urban"),
    ("soft_playful", "Soft and playful"),
    ("bold_unforgettable", "Bold and unforgettable"),
)

STYLING_APPROACH_CHOICES = (
    ("simple_coordinated", "Simple and coordinated"),
    ("timeless_balanced", "Timeless and balanced"),
    ("layered_casual", "Layered and casual"),
    ("decorative_mix", "Decorative mix"),
    ("unexpected_contrast", "Unexpected contrasts"),
)

STATEMENT_LEVEL_CHOICES = (
    ("low", "Low — I prefer subtle outfits"),
    ("medium", "Medium — some statement pieces"),
    ("high", "High — I want to stand out"),
)

PALETTE_CHOICES = (
    ("neutral", "Neutral"),
    ("dark", "Dark"),
    ("earthy", "Earthy"),
    ("pastel", "Pastel"),
    ("bright_contrast", "Bright and contrasting"),
)


class StyleQuizForm(forms.Form):
    silhouette = forms.ChoiceField(
        label="Which silhouette feels most like you?",
        choices=SILHOUETTE_CHOICES,
        widget=forms.RadioSelect(
            attrs={"class": "form-check-input"}
        ),
    )

    details = forms.ChoiceField(
        label="Which clothing details attract you most?",
        choices=DETAIL_CHOICES,
        widget=forms.RadioSelect(
            attrs={"class": "form-check-input"}
        ),
    )

    impression = forms.ChoiceField(
        label="How do you want your outfit to make you feel?",
        choices=IMPRESSION_CHOICES,
        widget=forms.RadioSelect(
            attrs={"class": "form-check-input"}
        ),
    )

    styling_approach = forms.ChoiceField(
        label="How do you prefer to put an outfit together?",
        choices=STYLING_APPROACH_CHOICES,
        widget=forms.RadioSelect(
            attrs={"class": "form-check-input"}
        ),
    )

    statement_level = forms.ChoiceField(
        label="How much attention should your outfit attract?",
        choices=STATEMENT_LEVEL_CHOICES,
        widget=forms.RadioSelect(
            attrs={"class": "form-check-input"}
        ),
    )

    palette = forms.ChoiceField(
        label="Which colour palette would you most likely wear?",
        choices=PALETTE_CHOICES,
        widget=forms.RadioSelect(
            attrs={"class": "form-check-input"}
        ),
    )
