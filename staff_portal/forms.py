from django import forms

from shop.models import RentalItem, Vendor


class PlatformRentalFilterForm(forms.Form):
    vendor = forms.ModelChoiceField(
        queryset=Vendor.objects.order_by("name", "pk"),
        required=False,
        empty_label="All vendors",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    customer = forms.CharField(
        required=False,
        label="Customer",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Username or email",
            }
        ),
    )
    status = forms.ChoiceField(
        required=False,
        label="Item status",
        choices=[("", "All statuses")] + list(RentalItem.Status.choices),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    date_from = forms.DateField(
        required=False,
        label="Rental period from",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"}
        ),
    )
    date_to = forms.DateField(
        required=False,
        label="Rental period to",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"}
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")

        if date_from and date_to and date_from > date_to:
            self.add_error(
                "date_to",
                "The To date must be on or after the From date.",
            )

        return cleaned_data


class SettlementFilterForm(forms.Form):
    vendor = forms.ModelChoiceField(
        queryset=Vendor.objects.order_by("name", "pk"),
        required=False,
        empty_label="All vendors",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    date_from = forms.DateField(
        required=False,
        label="Settled from",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"}
        ),
    )
    date_to = forms.DateField(
        required=False,
        label="Settled to",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control"}
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")

        if date_from and date_to and date_from > date_to:
            self.add_error(
                "date_to",
                "The To date must be on or after the From date.",
            )

        return cleaned_data


class ListingModerationFilterForm(forms.Form):
    STATUS_CHOICES = (
        ("", "All listings"),
        ("blocked", "Blocked only"),
        ("allowed", "Not blocked"),
    )

    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Product name or brand",
            }
        ),
    )
    vendor = forms.ModelChoiceField(
        queryset=Vendor.objects.order_by("name", "pk"),
        required=False,
        empty_label="All vendors",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    status = forms.ChoiceField(
        required=False,
        label="Moderation",
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class ListingModerationForm(forms.Form):
    action = forms.ChoiceField(
        choices=(("block", "Block"), ("unblock", "Unblock"))
    )
    reason = forms.CharField(required=False, max_length=500)

    def clean(self):
        cleaned_data = super().clean()
        reason = " ".join(cleaned_data.get("reason", "").split())
        cleaned_data["reason"] = reason

        if cleaned_data.get("action") == "block" and not reason:
            self.add_error("reason", "Enter a reason before blocking a listing.")

        return cleaned_data
