from django import forms

from shop.models import Product, ProductImage, ProductVariant


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "brand",
            "description",
            "daily_rate",
            "is_published",
        ]
        labels = {
            "daily_rate": "Daily rental rate (SGD)",
            "is_published": "Publish this listing",
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
        }


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
