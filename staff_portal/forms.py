from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from shop.models import RentalItem, Vendor


User = get_user_model()


class PlatformAdminCreationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "first_name",
            "last_name",
            "username",
            "email",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account already uses this email address."
            )
        return email


class PlatformAdminUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["email"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        existing_users = User.objects.filter(email__iexact=email).exclude(
            pk=self.instance.pk,
        )
        if existing_users.exists():
            raise forms.ValidationError(
                "An account already uses this email address."
            )
        return email


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
        choices=(("block", "Block"), ("unblock", "Unblock")),
        widget=forms.HiddenInput(),
    )
    reason = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Explain why this listing should be blocked",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        reason = " ".join(cleaned_data.get("reason", "").split())
        cleaned_data["reason"] = reason

        if cleaned_data.get("action") == "block" and not reason:
            self.add_error("reason", "Enter a reason before blocking a listing.")

        return cleaned_data
