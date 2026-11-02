from django.conf import settings
from django.db import models


class CustomerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )
    phone_number = models.CharField(max_length=30, blank=True)
    delivery_address = models.TextField(blank=True)

    def __str__(self):
        return f"Customer profile for {self.user.username}"


class VendorEmployee(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vendor_employee",
    )
    vendor = models.ForeignKey(
        "shop.Vendor",
        on_delete=models.PROTECT,
        related_name="employees",
    )
    is_vendor_admin = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.vendor.name}"
