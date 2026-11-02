from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.models import VendorEmployee
from accounts.roles import VENDOR_EMPLOYEE_GROUP
from shop.models import Category, Product, Vendor


class EmployeeHomeTests(TestCase):
    def setUp(self):
        self.employee_group, _ = Group.objects.get_or_create(
            name=VENDOR_EMPLOYEE_GROUP
        )
        self.vendor = Vendor.objects.create(
            name="Employee Vendor",
            contact_email="employee-vendor@example.com",
        )
        self.other_vendor = Vendor.objects.create(
            name="Other Vendor",
            contact_email="other-vendor@example.com",
        )
        self.category = Category.objects.create(name="Employee test category")
        self.user = get_user_model().objects.create_user(
            username="vendor-employee",
            password="test-password",
        )
        self.user.groups.add(self.employee_group)
        VendorEmployee.objects.create(user=self.user, vendor=self.vendor)

    def create_product(self, vendor, name, **extra_fields):
        return Product.objects.create(
            vendor=vendor,
            category=self.category,
            name=name,
            description="Test product",
            brand="Test brand",
            daily_rate="12.00",
            **extra_fields,
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("vendor_portal:home"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_employee_sees_only_products_owned_by_their_vendor(self):
        own_product = self.create_product(
            self.vendor,
            "Owned archived product",
            is_archived=True,
        )
        other_product = self.create_product(self.other_vendor, "Other vendor product")
        self.client.force_login(self.user)

        response = self.client.get(reverse("vendor_portal:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own_product.name)
        self.assertNotContains(response, other_product.name)

    def test_user_without_employee_role_is_forbidden(self):
        self.user.groups.clear()
        self.client.force_login(self.user)

        response = self.client.get(reverse("vendor_portal:home"))

        self.assertEqual(response.status_code, 403)

    def test_employee_product_detail_is_limited_to_their_vendor(self):
        own_product = self.create_product(self.vendor, "Owned product")
        other_product = self.create_product(self.other_vendor, "Other product")
        self.client.force_login(self.user)

        own_response = self.client.get(
            reverse("vendor_portal:product_detail", args=[own_product.pk])
        )
        other_response = self.client.get(
            reverse("vendor_portal:product_detail", args=[other_product.pk])
        )

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(other_response.status_code, 404)
