"""Forms for customer catalogue workflows."""

from decimal import Decimal

from django import forms


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
