from django.contrib import admin

from django.contrib import admin

from .models import (
    Category,
    Product,
    ProductImage,
    ProductVariant,
    StyleTag,
    Vendor,
)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "vendor",
        "category",
        "daily_rate",
        "is_archived",
        "moderation_blocked",
    )
    inlines = [ProductVariantInline, ProductImageInline]


admin.site.register(Vendor)
admin.site.register(Category)
admin.site.register(StyleTag)
