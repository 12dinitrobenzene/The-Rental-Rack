from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.roles import (
    CUSTOMER_GROUP,
    PLATFORM_ADMIN_GROUP,
    VENDOR_EMPLOYEE_GROUP,
)
from shop.models import Vendor


class PlatformAdminWorkspaceTests(TestCase):
    def setUp(self):
        self.url = reverse("staff_portal:home")

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
            "staff_portal/home.html",
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
        self.list_url = reverse("staff_portal:vendor_list")
        self.action_url = reverse(
            "staff_portal:vendor_action",
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
            "staff_portal/vendors.html",
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
