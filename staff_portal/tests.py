from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.roles import PLATFORM_ADMIN_GROUP
from shop.test_helpers import TEST_PASSWORD, make_employee, make_user, make_vendor


class PlatformRoleTests(TestCase):
    def test_platform_and_master_admin_permissions_are_separate(self):
        vendor = make_vendor()
        customer = make_user("customer")
        employee, _ = make_employee("employee", vendor)
        platform_admin = make_user("platform-admin", PLATFORM_ADMIN_GROUP)
        home_url = reverse("staff_portal:home")

        for user, expected_status in (
            (customer, 403),
            (employee, 403),
            (platform_admin, 200),
        ):
            with self.subTest(username=user.username):
                self.client.force_login(user)
                self.assertEqual(
                    self.client.get(home_url).status_code,
                    expected_status,
                )

        master = get_user_model().objects.create_superuser(
            username="master-admin",
            email="master@example.com",
            password=TEST_PASSWORD,
        )
        self.client.force_login(master)
        response = self.client.post(
            reverse("staff_portal:admin_create"),
            {
                "first_name": "New",
                "last_name": "Admin",
                "username": "new-admin",
                "email": "new-admin@example.com",
                "password1": TEST_PASSWORD,
                "password2": TEST_PASSWORD,
            },
        )

        self.assertRedirects(response, reverse("staff_portal:admin_list"))
        new_admin = get_user_model().objects.get(username="new-admin")
        self.assertTrue(
            new_admin.groups.filter(name=PLATFORM_ADMIN_GROUP).exists()
        )
        self.assertFalse(new_admin.is_superuser)
        self.client.force_login(new_admin)
        self.assertEqual(
            self.client.get(reverse("staff_portal:admin_list")).status_code,
            403,
        )
