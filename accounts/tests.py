from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import CustomerProfile
from .roles import CUSTOMER_GROUP


User = get_user_model()


class CustomerRegistrationTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name=CUSTOMER_GROUP)
        Group.objects.get_or_create(name="Vendor Employee")
        Group.objects.get_or_create(name="Platform Admin")
        self.url = reverse("accounts:register")
        self.valid_data = {
            "first_name": "Elgin",
            "last_name": "Tan",
            "username": "elgin_demo",
            "email": "elgin@example.com",
            "password1": "A-safe-password-2026!",
            "password2": "A-safe-password-2026!",
        }

    def test_valid_registration_creates_customer_account(self):
        response = self.client.post(
            self.url,
            {**self.valid_data, "role": "Platform Admin"},
        )

        user = User.objects.get(username="elgin_demo")
        self.assertRedirects(response, reverse("landing"))
        self.assertTrue(user.check_password("A-safe-password-2026!"))
        self.assertTrue(user.groups.filter(name=CUSTOMER_GROUP).exists())
        self.assertFalse(user.groups.filter(name="Platform Admin").exists())
        self.assertEqual(user.customer_profile.phone_number, "")
        self.assertEqual(user.customer_profile.delivery_address, "")

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(
            username="existing",
            email="elgin@example.com",
            password="A-safe-password-2026!",
        )

        response = self.client.post(self.url, self.valid_data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "An account already uses this email address.")
        self.assertEqual(User.objects.filter(username="elgin_demo").count(), 0)

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(
            self.url,
            {**self.valid_data, "password2": "Another-safe-password-2026!"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CustomerProfile.objects.count(), 0)

    def test_authenticated_user_cannot_register_again(self):
        user = User.objects.create_user(
            username="existing",
            password="A-safe-password-2026!",
        )
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse("customer:home"))
