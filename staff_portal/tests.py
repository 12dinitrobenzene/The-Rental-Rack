from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import (
    CUSTOMER_GROUP,
    PLATFORM_ADMIN_GROUP,
    VENDOR_EMPLOYEE_GROUP,
)
from shop.models import (
    Category,
    Product,
    ProductVariant,
    RentalItem,
    RentalOrder,
    RentalSettlement,
    Vendor,
)


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


class PlatformDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        admin_group = Group.objects.get_or_create(
            name=PLATFORM_ADMIN_GROUP,
        )[0]
        cls.admin = get_user_model().objects.create_user(
            username="dashboard-admin",
            password="test-password",
        )
        cls.admin.groups.add(admin_group)
        cls.customer = get_user_model().objects.create_user(
            username="dashboard-customer",
            password="test-password",
        )
        cls.category = Category.objects.create(name="Dashboard Clothing")

        cls.vendor_a = Vendor.objects.create(
            name="Alpha Rentals",
            contact_email="alpha@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )
        cls.vendor_b = Vendor.objects.create(
            name="Beta Rentals",
            contact_email="beta@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )
        cls.suspended_vendor = Vendor.objects.create(
            name="Suspended Rentals",
            contact_email="suspended@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
            is_suspended=True,
        )

        visible_variant = cls._create_variant(
            cls.vendor_a,
            "Visible Jacket",
            "visible-jacket",
            is_active=True,
            is_published=True,
        )
        cls._create_variant(
            cls.vendor_a,
            "Archived Jacket",
            "archived-jacket",
            is_active=True,
            is_published=True,
            is_archived=True,
        )
        beta_variant = cls._create_variant(
            cls.vendor_b,
            "Draft Coat",
            "draft-coat",
        )
        cls._create_variant(
            cls.suspended_vendor,
            "Suspended Blazer",
            "suspended-blazer",
            is_active=True,
            is_published=True,
        )

        cls.alpha_order, alpha_item = cls._create_order_item(
            cls.vendor_a,
            visible_variant,
            RentalItem.Status.COMPLETED,
            quantity=1,
            line_total=Decimal("10.00"),
        )
        RentalSettlement.objects.create(
            rental_item=alpha_item,
            commission_rate_snapshot=Decimal("0.2000"),
            platform_amount=Decimal("2.00"),
            vendor_amount=Decimal("8.00"),
        )

        cls.beta_order, beta_item = cls._create_order_item(
            cls.vendor_b,
            beta_variant,
            RentalItem.Status.COMPLETED,
            quantity=2,
            line_total=Decimal("20.00"),
        )
        RentalSettlement.objects.create(
            rental_item=beta_item,
            commission_rate_snapshot=Decimal("0.2000"),
            platform_amount=Decimal("4.00"),
            vendor_amount=Decimal("16.00"),
        )

        cls.cancelled_order, _ = cls._create_order_item(
            cls.vendor_a,
            visible_variant,
            RentalItem.Status.CANCELLED,
            quantity=1,
            line_total=Decimal("10.00"),
        )

    @classmethod
    def _create_variant(
        cls,
        vendor,
        name,
        sku,
        **product_fields,
    ):
        product = Product.objects.create(
            vendor=vendor,
            category=cls.category,
            name=name,
            description="Dashboard test clothing.",
            brand="Test",
            daily_rate=Decimal("10.00"),
            **product_fields,
        )
        return ProductVariant.objects.create(
            product=product,
            sku=sku,
            size="M",
            colour="Black",
            total_quantity=3,
        )

    @classmethod
    def _create_order_item(
        cls,
        vendor,
        variant,
        status,
        *,
        quantity,
        line_total,
    ):
        order = RentalOrder.objects.create(
            customer=cls.customer,
            vendor=vendor,
            delivery_address="1 Dashboard Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=line_total,
        )
        item = RentalItem.objects.create(
            order=order,
            variant=variant,
            product_name_snapshot=variant.product.name,
            daily_rate_snapshot=Decimal("10.00"),
            quantity=quantity,
            rental_start_date=date(2026, 11, 1),
            rental_end_date=date(2026, 11, 1),
            rental_days=1,
            line_total=line_total,
            status=status,
        )
        return order, item

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("staff_portal:home")

    def test_dashboard_metrics_use_marketplace_and_settlement_records(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["approved_vendors"], 3)
        self.assertEqual(response.context["suspended_vendors"], 1)
        self.assertEqual(response.context["visible_listings"], 1)
        self.assertEqual(response.context["rental_orders"], 3)
        self.assertEqual(response.context["completed_rental_items"], 2)
        self.assertEqual(
            response.context["platform_commission"],
            Decimal("6.00"),
        )
        self.assertEqual(
            response.context["vendor_payout"],
            Decimal("24.00"),
        )
        self.assertEqual(
            response.context["settled_gross"],
            Decimal("30.00"),
        )
        self.assertContains(response, "Marketplace summary")
        self.assertContains(response, "Catalogue-visible listings")
        self.assertContains(response, "Vendor performance")

    def test_vendor_performance_and_recent_orders_are_ordered(self):
        extra_order_ids = []

        for _ in range(4):
            order = RentalOrder.objects.create(
                customer=self.customer,
                vendor=self.vendor_a,
                delivery_address="2 Dashboard Street",
                payment_status=RentalOrder.PaymentStatus.PENDING,
                total_amount=Decimal("0.00"),
            )
            extra_order_ids.append(order.pk)

        response = self.client.get(self.url)
        vendor_rows = list(response.context["vendor_performance"])
        recent_orders = list(response.context["recent_orders"])

        self.assertEqual(
            [vendor.name for vendor in vendor_rows],
            ["Beta Rentals", "Alpha Rentals", "Suspended Rentals"],
        )
        self.assertEqual(vendor_rows[0].settled_items, 1)
        self.assertEqual(vendor_rows[0].settled_gross, Decimal("20.00"))
        self.assertEqual(vendor_rows[-1].settled_items, 0)
        self.assertEqual(vendor_rows[-1].settled_gross, Decimal("0.00"))
        self.assertEqual(len(recent_orders), 5)
        self.assertEqual(
            [order.pk for order in recent_orders],
            list(reversed(extra_order_ids))
            + [self.cancelled_order.pk],
        )


class PlatformRentalMonitoringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        groups = {
            name: Group.objects.get_or_create(name=name)[0]
            for name in (
                CUSTOMER_GROUP,
                VENDOR_EMPLOYEE_GROUP,
                PLATFORM_ADMIN_GROUP,
            )
        }
        User = get_user_model()
        cls.admin = User.objects.create_user(
            username="monitoring-admin",
            password="test-password",
        )
        cls.admin.groups.add(groups[PLATFORM_ADMIN_GROUP])
        cls.customer_one = User.objects.create_user(
            username="first-customer",
            email="first@example.com",
            password="test-password",
        )
        cls.customer_one.groups.add(groups[CUSTOMER_GROUP])
        cls.customer_two = User.objects.create_user(
            username="second-customer",
            email="second@example.com",
            password="test-password",
        )
        cls.customer_two.groups.add(groups[CUSTOMER_GROUP])
        cls.employee = User.objects.create_user(
            username="monitoring-employee",
            password="test-password",
        )
        cls.employee.groups.add(groups[VENDOR_EMPLOYEE_GROUP])

        cls.vendor_one = Vendor.objects.create(
            name="First Monitoring Vendor",
            contact_email="first-vendor@example.com",
        )
        cls.vendor_two = Vendor.objects.create(
            name="Second Monitoring Vendor",
            contact_email="second-vendor@example.com",
        )
        category = Category.objects.create(name="Monitoring Clothing")
        first_product = Product.objects.create(
            vendor=cls.vendor_one,
            category=category,
            name="Monitoring Jacket",
            description="A jacket used for monitoring tests.",
            brand="Test",
            daily_rate=Decimal("10.00"),
        )
        second_product = Product.objects.create(
            vendor=cls.vendor_two,
            category=category,
            name="Monitoring Coat",
            description="A coat used for monitoring tests.",
            brand="Test",
            daily_rate=Decimal("10.00"),
        )
        first_variant = ProductVariant.objects.create(
            product=first_product,
            sku="monitoring-jacket-m",
            size="M",
            colour="Blue",
            total_quantity=3,
        )
        second_variant = ProductVariant.objects.create(
            product=second_product,
            sku="monitoring-coat-l",
            size="L",
            colour="Black",
            total_quantity=2,
        )

        cls.first_order = RentalOrder.objects.create(
            customer=cls.customer_one,
            vendor=cls.vendor_one,
            delivery_address="1 Monitoring Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("70.00"),
        )
        cls._create_item(
            cls.first_order,
            first_variant,
            "Active Monitoring Jacket",
            RentalItem.Status.ACTIVE,
            date(2026, 11, 1),
            date(2026, 11, 3),
            Decimal("30.00"),
        )
        cls._create_item(
            cls.first_order,
            first_variant,
            "Returned Monitoring Jacket",
            RentalItem.Status.RETURNED,
            date(2026, 11, 10),
            date(2026, 11, 12),
            Decimal("30.00"),
        )
        cls._create_item(
            cls.first_order,
            first_variant,
            "Second Active Jacket",
            RentalItem.Status.ACTIVE,
            date(2026, 11, 2),
            date(2026, 11, 2),
            Decimal("10.00"),
        )

        cls.second_order = RentalOrder.objects.create(
            customer=cls.customer_two,
            vendor=cls.vendor_two,
            delivery_address="2 Monitoring Street",
            payment_status=RentalOrder.PaymentStatus.PENDING,
            total_amount=Decimal("30.00"),
        )
        cls._create_item(
            cls.second_order,
            second_variant,
            "Returned Monitoring Coat",
            RentalItem.Status.RETURNED,
            date(2026, 11, 1),
            date(2026, 11, 3),
            Decimal("30.00"),
        )

    @classmethod
    def _create_item(
        cls,
        order,
        variant,
        product_name,
        status,
        start_date,
        end_date,
        line_total,
    ):
        return RentalItem.objects.create(
            order=order,
            variant=variant,
            product_name_snapshot=product_name,
            daily_rate_snapshot=Decimal("10.00"),
            quantity=1,
            rental_start_date=start_date,
            rental_end_date=end_date,
            rental_days=(end_date - start_date).days + 1,
            line_total=line_total,
            status=status,
        )

    def setUp(self):
        self.url = reverse("staff_portal:rental_order_list")

    def test_page_is_protected_read_only_and_displays_item_details(self):
        anonymous_response = self.client.get(self.url)
        self.assertEqual(anonymous_response.status_code, 302)

        for user in (self.customer_one, self.employee):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "staff_portal/rental_orders.html",
        )
        for expected_text in (
            "First Monitoring Vendor",
            "first-customer",
            "Active Monitoring Jacket",
            "01 Nov 2026",
            "03 Nov 2026",
            "Paid",
            "Active",
        ):
            self.assertContains(response, expected_text)
        self.assertNotContains(response, "Mark dispatched")
        self.assertNotContains(response, "Complete and record settlement")

    def test_filters_are_combined_without_duplicates(self):
        self.client.force_login(self.admin)

        vendor_response = self.client.get(
            self.url,
            {"vendor": self.vendor_one.pk},
        )
        self.assertEqual(
            [order.pk for order in vendor_response.context["orders"]],
            [self.first_order.pk],
        )

        customer_response = self.client.get(
            self.url,
            {"customer": "second@example.com"},
        )
        self.assertEqual(
            [order.pk for order in customer_response.context["orders"]],
            [self.second_order.pk],
        )

        same_item_response = self.client.get(
            self.url,
            {
                "status": RentalItem.Status.ACTIVE,
                "date_from": "2026-11-10",
                "date_to": "2026-11-12",
            },
        )
        self.assertEqual(list(same_item_response.context["orders"]), [])

        matching_response = self.client.get(
            self.url,
            {
                "status": RentalItem.Status.ACTIVE,
                "date_from": "2026-11-01",
                "date_to": "2026-11-03",
            },
        )
        self.assertEqual(
            [order.pk for order in matching_response.context["orders"]],
            [self.first_order.pk],
        )

        invalid_response = self.client.get(
            self.url,
            {
                "date_from": "2026-11-12",
                "date_to": "2026-11-10",
            },
        )
        self.assertFalse(invalid_response.context["filter_form"].is_valid())
        self.assertEqual(list(invalid_response.context["orders"]), [])
        self.assertContains(
            invalid_response,
            "The To date must be on or after the From date.",
        )


class PlatformSettlementOverviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        groups = {
            name: Group.objects.get_or_create(name=name)[0]
            for name in (
                CUSTOMER_GROUP,
                PLATFORM_ADMIN_GROUP,
            )
        }
        User = get_user_model()
        cls.admin = User.objects.create_user(
            username="settlement-admin",
            password="test-password",
        )
        cls.admin.groups.add(groups[PLATFORM_ADMIN_GROUP])
        cls.customer = User.objects.create_user(
            username="settlement-customer",
            password="test-password",
        )
        cls.customer.groups.add(groups[CUSTOMER_GROUP])

        cls.vendor_one = Vendor.objects.create(
            name="Settlement Studio",
            contact_email="settlement-studio@example.com",
        )
        cls.vendor_two = Vendor.objects.create(
            name="Payout Wardrobe",
            contact_email="payout-wardrobe@example.com",
        )
        category = Category.objects.create(name="Settlement Clothing")

        cls.first_settlement = cls._create_settlement(
            cls.vendor_one,
            category,
            "Settlement Blazer",
            "settlement-blazer-m",
            Decimal("20.00"),
            Decimal("0.2500"),
            Decimal("5.00"),
            Decimal("15.00"),
        )
        cls.second_settlement = cls._create_settlement(
            cls.vendor_two,
            category,
            "Payout Coat",
            "payout-coat-l",
            Decimal("30.00"),
            Decimal("0.2000"),
            Decimal("6.00"),
            Decimal("24.00"),
        )

        RentalSettlement.objects.filter(
            pk=cls.first_settlement.pk,
        ).update(
            created_at=timezone.make_aware(
                datetime(2026, 10, 10, 10, 0),
            ),
        )
        RentalSettlement.objects.filter(
            pk=cls.second_settlement.pk,
        ).update(
            created_at=timezone.make_aware(
                datetime(2026, 11, 10, 10, 0),
            ),
        )

    @classmethod
    def _create_settlement(
        cls,
        vendor,
        category,
        product_name,
        sku,
        line_total,
        commission_rate,
        platform_amount,
        vendor_amount,
    ):
        product = Product.objects.create(
            vendor=vendor,
            category=category,
            name=product_name,
            description="Clothing used for settlement tests.",
            brand="Test",
            daily_rate=line_total,
        )
        variant = ProductVariant.objects.create(
            product=product,
            sku=sku,
            size="M",
            colour="Black",
            total_quantity=1,
        )
        order = RentalOrder.objects.create(
            customer=cls.customer,
            vendor=vendor,
            delivery_address="1 Settlement Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=line_total,
        )
        item = RentalItem.objects.create(
            order=order,
            variant=variant,
            product_name_snapshot=product_name,
            daily_rate_snapshot=line_total,
            commission_rate_snapshot=commission_rate,
            quantity=1,
            rental_start_date=date(2026, 10, 1),
            rental_end_date=date(2026, 10, 1),
            rental_days=1,
            line_total=line_total,
            status=RentalItem.Status.COMPLETED,
        )
        return RentalSettlement.objects.create(
            rental_item=item,
            commission_rate_snapshot=commission_rate,
            platform_amount=platform_amount,
            vendor_amount=vendor_amount,
        )

    def setUp(self):
        self.url = reverse("staff_portal:settlement_list")

    def test_page_is_admin_only_read_only_and_uses_saved_amounts(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.url).status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff_portal/settlements.html")
        self.assertEqual(response.context["settlement_count"], 2)
        self.assertEqual(response.context["gross_amount"], Decimal("50.00"))
        self.assertEqual(
            response.context["platform_amount"],
            Decimal("11.00"),
        )
        self.assertEqual(
            response.context["vendor_amount"],
            Decimal("39.00"),
        )
        for expected_text in (
            "Settlement Blazer",
            "Settlement Studio",
            "settlement-customer",
            "25.00%",
            "Read-only financial record",
        ):
            self.assertContains(response, expected_text)
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_vendor_and_settlement_date_filters_update_results_and_totals(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            self.url,
            {
                "vendor": self.vendor_two.pk,
                "date_from": "2026-11-01",
                "date_to": "2026-11-30",
            },
        )

        self.assertEqual(
            list(response.context["settlements"]),
            [self.second_settlement],
        )
        self.assertEqual(response.context["settlement_count"], 1)
        self.assertEqual(response.context["gross_amount"], Decimal("30.00"))
        self.assertNotContains(response, "Settlement Blazer")

        invalid_response = self.client.get(
            self.url,
            {
                "date_from": "2026-11-30",
                "date_to": "2026-11-01",
            },
        )
        self.assertFalse(invalid_response.context["filter_form"].is_valid())
        self.assertEqual(
            list(invalid_response.context["settlements"]),
            [],
        )
        self.assertContains(
            invalid_response,
            "The To date must be on or after the From date.",
        )


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
