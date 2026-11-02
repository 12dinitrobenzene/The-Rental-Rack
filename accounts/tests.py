from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import CustomerProfile, VendorEmployee
from .roles import CUSTOMER_GROUP, VENDOR_EMPLOYEE_GROUP
from shop.models import Vendor


User = get_user_model()


class CustomerRegistrationTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name=CUSTOMER_GROUP)
        Group.objects.get_or_create(name="Vendor Employee")
        Group.objects.get_or_create(name="Platform Admin")
        self.url = reverse("accounts:register_customer")
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

    def test_register_page_offers_customer_and_company_choices(self):
        response = self.client.get(reverse("accounts:register"))

        self.assertContains(response, "Customer")
        self.assertContains(response, "Register your company")

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


class VendorRegistrationTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name=VENDOR_EMPLOYEE_GROUP)
        self.url = reverse("accounts:register_vendor")
        self.valid_data = {
            "first_name": "Aisha",
            "last_name": "Lim",
            "username": "aisha_vendor",
            "email": "aisha@example.com",
            "company_name": "Aisha Wardrobe",
            "company_email": "hello@aishawardrobe.example.com",
            "contact_phone": "61234567",
            "address": "1 Orchard Road",
            "password1": "A-safe-password-2026!",
            "password2": "A-safe-password-2026!",
        }

    def test_vendor_registration_creates_pending_company_and_manager(self):
        response = self.client.post(self.url, self.valid_data)

        self.assertRedirects(response, reverse("accounts:login"))
        vendor = Vendor.objects.get(name="Aisha Wardrobe")
        employee = VendorEmployee.objects.get(user__username="aisha_vendor")
        self.assertEqual(vendor.approval_status, Vendor.ApprovalStatus.PENDING)
        self.assertEqual(employee.vendor, vendor)
        self.assertTrue(employee.is_vendor_admin)
        self.assertTrue(
            employee.user.groups.filter(name=VENDOR_EMPLOYEE_GROUP).exists()
        )

    def test_duplicate_company_name_is_rejected(self):
        Vendor.objects.create(
            name="Aisha Wardrobe",
            contact_email="existing@example.com",
        )

        response = self.client.post(self.url, self.valid_data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "A vendor company with this name already exists.",
        )
        self.assertFalse(User.objects.filter(username="aisha_vendor").exists())


class VendorTeamManagementTests(TestCase):
    def setUp(self):
        self.group, _ = Group.objects.get_or_create(
            name=VENDOR_EMPLOYEE_GROUP
        )
        self.vendor = Vendor.objects.create(
            name="Team Vendor",
            contact_email="team@example.com",
        )
        self.manager = User.objects.create_user(
            username="team-manager",
            password="A-safe-password-2026!",
        )
        self.manager.groups.add(self.group)
        VendorEmployee.objects.create(
            user=self.manager,
            vendor=self.vendor,
            is_vendor_admin=True,
        )
        self.employee = User.objects.create_user(
            username="regular-employee",
            password="A-safe-password-2026!",
        )
        self.employee.groups.add(self.group)
        VendorEmployee.objects.create(user=self.employee, vendor=self.vendor)

    def test_only_company_manager_can_view_the_team(self):
        self.client.force_login(self.manager)
        manager_response = self.client.get(reverse("accounts:vendor_team"))

        self.client.force_login(self.employee)
        employee_response = self.client.get(reverse("accounts:vendor_team"))

        self.assertEqual(manager_response.status_code, 200)
        self.assertContains(manager_response, "regular-employee")
        self.assertEqual(employee_response.status_code, 403)

    def test_manager_adds_employee_to_their_own_vendor(self):
        self.client.force_login(self.manager)

        form_response = self.client.get(
            reverse("accounts:vendor_team_add_employee")
        )

        response = self.client.post(
            reverse("accounts:vendor_team_add_employee"),
            {
                "first_name": "Jamie",
                "last_name": "Lee",
                "username": "jamie-team",
                "email": "jamie@example.com",
                "password1": "A-safe-password-2026!",
                "password2": "A-safe-password-2026!",
            },
        )

        self.assertEqual(form_response.status_code, 200)
        self.assertContains(
            form_response,
            "This account will be added to Team Vendor automatically.",
        )
        self.assertRedirects(response, reverse("accounts:vendor_team"))
        employee = VendorEmployee.objects.get(user__username="jamie-team")
        self.assertEqual(employee.vendor, self.vendor)
        self.assertFalse(employee.is_vendor_admin)
