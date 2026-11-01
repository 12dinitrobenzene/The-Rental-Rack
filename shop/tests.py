from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.models import VendorEmployee
from accounts.roles import (
    CUSTOMER_GROUP,
    PLATFORM_ADMIN_GROUP,
    VENDOR_EMPLOYEE_GROUP,
)

from .models import Category, Product, ProductVariant, Vendor


class CatalogueFilterTests(TestCase):
    def setUp(self):
        self.vendor = Vendor.objects.create(
            name="Pastel Wardrobe",
            contact_email="vendor@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )
        self.category = Category.objects.create(name="Tops")

        self.linen_small = self.create_product(
            "Linen Shirt",
            "Light linen shirt",
            "12.00",
            "Small",
        )
        self.linen_medium = self.create_product(
            "Linen Jacket",
            "Warm linen jacket",
            "25.00",
            "Medium",
        )
        self.cotton_small = self.create_product(
            "Cotton Shirt",
            "Cotton everyday shirt",
            "8.00",
            "Small",
        )

    def create_product(self, name, description, daily_rate, size):
        product = Product.objects.create(
            vendor=self.vendor,
            category=self.category,
            name=name,
            description=description,
            brand="Test brand",
            daily_rate=daily_rate,
        )
        ProductVariant.objects.create(
            product=product,
            sku=f"sku-{product.pk}",
            size=size,
            colour="Green",
            total_quantity=1,
        )
        return product

    def test_advanced_filters_can_be_combined(self):
        response = self.client.get(
            "/customer/catalogue/",
            {
                "q": "linen",
                "vendor": self.vendor.pk,
                "size": "Small",
                "min_price": "10",
                "max_price": "20",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.linen_small.name)
        self.assertNotContains(response, self.linen_medium.name)
        self.assertNotContains(response, self.cotton_small.name)

    def test_newest_and_price_sorts_are_available(self):
        response = self.client.get(
            "/customer/catalogue/",
            {"sort": "price_low"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="price_low" selected')
        self.assertLess(
            response.content.index(self.cotton_small.name.encode()),
            response.content.index(self.linen_small.name.encode()),
        )

        newest_response = self.client.get(
            "/customer/catalogue/",
            {"sort": "newest"},
        )
        self.assertEqual(newest_response.status_code, 200)
        self.assertContains(newest_response, 'value="newest" selected')

    def test_invalid_price_range_shows_validation_error(self):
        response = self.client.get(
            "/customer/catalogue/",
            {"min_price": "40", "max_price": "10"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Maximum price must be at least the minimum.",
        )


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
        response = self.client.get(reverse("shop:employee_home"))

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

        response = self.client.get(reverse("shop:employee_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own_product.name)
        self.assertNotContains(response, other_product.name)

    def test_user_without_employee_role_is_forbidden(self):
        self.user.groups.clear()
        self.client.force_login(self.user)

        response = self.client.get(reverse("shop:employee_home"))

        self.assertEqual(response.status_code, 403)

    def test_employee_product_detail_is_limited_to_their_vendor(self):
        own_product = self.create_product(self.vendor, "Owned product")
        other_product = self.create_product(self.other_vendor, "Other product")
        self.client.force_login(self.user)

        own_response = self.client.get(
            reverse("shop:employee_product_detail", args=[own_product.pk])
        )
        other_response = self.client.get(
            reverse("shop:employee_product_detail", args=[other_product.pk])
        )

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(other_response.status_code, 404)


class PlatformAdminWorkspaceTests(TestCase):
    def setUp(self):
        self.url = reverse("shop:platform_admin_home")

        self.user = get_user_model().objects.create_user(
            username="workspace-test-user",
            password="test-password",
        )

        self.groups = {
            name: Group.objects.get_or_create(name=name)[0]
            for name in (
                CUSTOMER_GROUP,
                VENDOR_EMPLOYEE_GROUP,
                PLATFORM_ADMIN_GROUP,
            )
        }

    def test_logged_out_user_is_redirected_to_login(self):
        response = self.client.get(self.url)

        expected = f"{reverse('accounts:login')}?next={self.url}"

        self.assertRedirects(
            response,
            expected,
            fetch_redirect_response=False,
        )

    def test_platform_admin_can_access_workspace(self):
        self.user.groups.add(self.groups[PLATFORM_ADMIN_GROUP])
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "shop/platform_admin/home.html",
        )
        self.assertContains(response, "Platform workspace")

    def test_other_roles_and_missing_role_are_forbidden(self):
        for role in (CUSTOMER_GROUP, VENDOR_EMPLOYEE_GROUP, None):
            with self.subTest(role=role):
                self.user.groups.clear()

                if role:
                    self.user.groups.add(self.groups[role])

                self.client.force_login(self.user)
                response = self.client.get(self.url)

                self.assertEqual(response.status_code, 403)

    def test_multiple_application_roles_are_forbidden(self):
        self.user.groups.add(
            self.groups[PLATFORM_ADMIN_GROUP],
            self.groups[CUSTOMER_GROUP],
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)


class PlatformVendorManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="vendor-management-admin",
            password="test-password",
        )
        self.admin_group = Group.objects.get_or_create(
            name=PLATFORM_ADMIN_GROUP
        )[0]
        self.admin.groups.add(self.admin_group)
        self.client.force_login(self.admin)

        self.vendor = Vendor.objects.create(
            name="Zeta Wardrobe",
            contact_email="zeta@example.com",
        )
        self.list_url = reverse("shop:platform_vendor_list")
        self.action_url = reverse(
            "shop:platform_vendor_action",
            args=[self.vendor.pk],
        )

    def test_vendor_list_is_ordered_and_has_post_action_forms(self):
        Vendor.objects.create(
            name="Alpha Wardrobe",
            contact_email="alpha@example.com",
        )

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "shop/platform_admin/vendors.html",
        )
        self.assertContains(
            response,
            'name="action"\n                                        value="approve"',
        )
        self.assertContains(
            response,
            'name="action"\n                                        value="suspend"',
        )
        self.assertLess(
            response.content.index(b"Alpha Wardrobe"),
            response.content.index(b"Zeta Wardrobe"),
        )

    def test_vendor_actions_only_change_their_own_status_field(self):
        scenarios = (
            (
                "approve",
                Vendor.ApprovalStatus.PENDING,
                True,
                Vendor.ApprovalStatus.APPROVED,
                True,
            ),
            (
                "suspend",
                Vendor.ApprovalStatus.PENDING,
                False,
                Vendor.ApprovalStatus.PENDING,
                True,
            ),
            (
                "restore",
                Vendor.ApprovalStatus.PENDING,
                True,
                Vendor.ApprovalStatus.PENDING,
                False,
            ),
        )

        for (
            action,
            approval,
            suspended,
            expected_approval,
            expected_suspended,
        ) in scenarios:
            with self.subTest(action=action):
                self.vendor.approval_status = approval
                self.vendor.is_suspended = suspended
                self.vendor.save(
                    update_fields=["approval_status", "is_suspended"]
                )

                response = self.client.post(
                    self.action_url,
                    {"action": action},
                )

                self.assertRedirects(response, self.list_url)
                self.vendor.refresh_from_db()
                self.assertEqual(self.vendor.approval_status, expected_approval)
                self.assertEqual(self.vendor.is_suspended, expected_suspended)

    def test_action_rejects_get_and_unknown_action(self):
        get_response = self.client.get(self.action_url)
        post_response = self.client.post(
            self.action_url,
            {"action": "delete"},
        )

        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(post_response.status_code, 400)
