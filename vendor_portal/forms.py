from django import forms
from django.utils import timezone

from shop.models import (
    Category,
    Product,
    ProductImage,
    ProductVariant,
    RentalItem,
    RentalReturn,
    ReturnInspection,
)


class ProductForm(forms.ModelForm):
    category_mode = forms.ChoiceField(
        choices=[
            ("existing", "Choose an existing category"),
            ("new", "Create a new category"),
        ],
        initial="existing",
        required=False,
        widget=forms.RadioSelect,
    )
    new_category = forms.CharField(
        required=False,
        max_length=100,
        label="New category name",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "e.g. Formal wear",
            }
        ),
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "brand",
            "description",
            "daily_rate",
            "is_published",
            "style_tags",
        ]
        labels = {
            "daily_rate": "Daily rental rate (SGD)",
            "is_published": "Publish this listing",
            "style_tags": "Style tags",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "brand": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 5}
            ),
            "daily_rate": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "style_tags": forms.SelectMultiple(
                attrs={"class": "form-select"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].required = False
        self.fields["category"].empty_label = "Select a category"

    def clean(self):
        cleaned_data = super().clean()

        mode = cleaned_data.get("category_mode") or "existing"
        category = cleaned_data.get("category")
        new_category = " ".join(
            cleaned_data.get("new_category", "").split()
        )

        cleaned_data["category_mode"] = mode
        cleaned_data["new_category"] = new_category

        if mode == "existing":
            if category is None:
                self.add_error(
                    "category",
                    "Select an existing category.",
                )

        elif mode == "new":
            cleaned_data["category"] = None

            if not new_category:
                self.add_error(
                    "new_category",
                    "Enter a name for the new category.",
                )
            elif Category.objects.filter(
                name__iexact=new_category
            ).exists():
                self.add_error(
                    "new_category",
                    (
                        "That category already exists. "
                        "Choose it from the existing categories."
                    ),
                )

        return cleaned_data

    def save(self, commit=True):
        if self.cleaned_data["category_mode"] == "new":
            category, _ = Category.objects.get_or_create(
                name=self.cleaned_data["new_category"]
            )
            self.instance.category = category

        return super().save(commit=commit)


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = [
            "sku",
            "size",
            "colour",
            "colour_hex",
            "total_quantity",
            "is_active",
        ]
        labels = {
            "colour_hex": "Colour hex code",
            "total_quantity": "Stock quantity",
            "is_active": "Available for rental",
        }
        widgets = {
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "size": forms.TextInput(attrs={"class": "form-control"}),
            "colour": forms.TextInput(attrs={"class": "form-control"}),
            "colour_hex": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "#A9C77D"}
            ),
            "total_quantity": forms.NumberInput(
                attrs={"class": "form-control", "min": 0}
            ),
        }


class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ["image", "alt_text", "sort_order"]
        labels = {
            "image": "Product image",
            "alt_text": "Image description",
            "sort_order": "Display order",
        }
        widgets = {
            "image": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "alt_text": forms.TextInput(attrs={"class": "form-control"}),
            "sort_order": forms.NumberInput(
                attrs={"class": "form-control", "min": 0}
            ),
        }


class RentalOrderFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False,
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


class VendorAnalyticsFilterForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        label="From",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
    )
    end_date = forms.DateField(
        required=False,
        label="To",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if start_date and end_date and end_date < start_date:
            self.add_error(
                "end_date",
                "The end date must be on or after the start date.",
            )

        return cleaned_data


class RentalReturnForm(forms.ModelForm):
    class Meta:
        model = RentalReturn
        fields = ["returned_on"]
        labels = {
            "returned_on": "Actual return date",
        }
        widgets = {
            "returned_on": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "type": "date",
                    "class": "form-control",
                },
            ),
        }

    def clean_returned_on(self):
        returned_on = self.cleaned_data["returned_on"]

        if returned_on > timezone.localdate():
            raise forms.ValidationError(
                "The actual return date cannot be in the future."
            )

        return returned_on


class ReturnInspectionForm(forms.ModelForm):
    class Meta:
        model = ReturnInspection
        fields = ["condition", "notes"]
        widgets = {
            "condition": forms.Select(
                attrs={"class": "form-select"}
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                }
            ),
        }
