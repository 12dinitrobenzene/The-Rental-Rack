from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from customer.forms import RentalSelectionForm
from customer.models import RentalItem, RentalOrder
from shop.models import Category, Product, ProductVariant, Vendor


class RentalItemValidationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="renter",
            password="test-password",
        )
        self.vendor = Vendor.objects.create(
            name="Rental Vendor",
            contact_email="rental@example.com",
        )
        self.category = Category.objects.create(name="Rental Clothing")
        self.product = Product.objects.create(
            vendor=self.vendor,
            category=self.category,
            name="Rental Jacket",
            description="A rental jacket.",
            brand="Test",
            daily_rate="20.00",
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            sku="rental-jacket-m",
            size="M",
            colour="Blue",
        )
        self.order = RentalOrder.objects.create(
            customer=self.user,
            vendor=self.vendor,
            delivery_address="1 Test Street",
            total_amount="60.00",
        )

    def make_item(self, **overrides):
        values = {
            "order": self.order,
            "variant": self.variant,
            "product_name_snapshot": "Rental Jacket",
            "daily_rate_snapshot": Decimal("10.00"),
            "quantity": 2,
            "rental_start_date": date(2026, 11, 3),
            "rental_end_date": date(2026, 11, 5),
            "rental_days": 3,
            "line_total": Decimal("60.00"),
        }
        values.update(overrides)
        return RentalItem(**values)

    def test_clean_validates_totals_using_snapshot_rate(self):
        self.make_item().clean()

    def test_clean_reports_inconsistent_days_and_total(self):
        item = self.make_item(rental_days=2, line_total=Decimal("40.00"))

        with self.assertRaises(ValidationError) as raised:
            item.clean()

        self.assertEqual(
            set(raised.exception.message_dict),
            {"rental_days", "line_total"},
        )

    def test_clean_rejects_variant_from_another_vendor(self):
        other_vendor = Vendor.objects.create(
            name="Other Vendor",
            contact_email="other@example.com",
        )
        other_product = Product.objects.create(
            vendor=other_vendor,
            category=self.category,
            name="Other Jacket",
            description="Another rental jacket.",
            brand="Test",
            daily_rate="20.00",
        )
        other_variant = ProductVariant.objects.create(
            product=other_product,
            sku="other-jacket-m",
            size="M",
            colour="Blue",
        )

        with self.assertRaises(ValidationError) as raised:
            self.make_item(variant=other_variant).clean()

        self.assertIn("variant", raised.exception.message_dict)

    def test_same_day_rental_counts_as_one_day(self):
        item = self.make_item(
            rental_end_date=date(2026, 11, 3),
            rental_days=1,
            line_total=Decimal("20.00"),
        )

        item.full_clean()
        item.save()

        self.assertEqual(item.rental_days, 1)
        self.assertEqual(item.line_total, Decimal("20.00"))

    def test_seven_day_rental_is_accepted(self):
        item = self.make_item(
            rental_end_date=date(2026, 11, 9),
            rental_days=7,
            line_total=Decimal("140.00"),
        )

        item.full_clean()
        item.save()

        self.assertEqual(item.rental_days, 7)

    def test_eight_day_rental_is_rejected(self):
        item = self.make_item(
            rental_end_date=date(2026, 11, 10),
            rental_days=8,
            line_total=Decimal("160.00"),
        )

        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_zero_quantity_is_rejected(self):
        item = self.make_item(
            quantity=0,
            line_total=Decimal("0.00"),
        )

        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_reversed_dates_are_rejected(self):
        item = self.make_item(
            rental_end_date=date(2026, 11, 2),
        )

        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_product_changes_preserve_saved_snapshots(self):
        item = self.make_item()
        item.full_clean()
        item.save()

        # Change the current listing after the rental was recorded.
        self.product.name = "Renamed Jacket"
        self.product.daily_rate = Decimal("35.00")
        self.product.save()

        # Read the rental record again from the database.
        item.refresh_from_db()

        self.assertEqual(
            item.product_name_snapshot,
            "Rental Jacket",
        )
        self.assertEqual(
            item.daily_rate_snapshot,
            Decimal("10.00"),
        )
        self.assertEqual(
            item.line_total,
            Decimal("60.00"),
        )

    def test_order_supports_items_with_different_dates(self):
        first_item = self.make_item()
        first_item.full_clean()
        first_item.save()

        second_item = self.make_item(
            rental_start_date=date(2026, 11, 10),
            rental_end_date=date(2026, 11, 11),
            rental_days=2,
            line_total=Decimal("40.00"),
        )
        second_item.full_clean()
        second_item.save()

        self.order.total_amount = Decimal("100.00")
        self.order.save(update_fields=["total_amount"])

        self.assertEqual(self.order.items.count(), 2)

        saved_periods = set(
            self.order.items.values_list(
                "rental_start_date",
                "rental_end_date",
            )
        )

        self.assertEqual(
            saved_periods,
            {
                (date(2026, 11, 3), date(2026, 11, 5)),
                (date(2026, 11, 10), date(2026, 11, 11)),
            },
        )


class RentalSelectionFormTests(TestCase):
    def setUp(self):
        self.vendor = Vendor.objects.create(
            name="Selection Vendor",
            contact_email="selection@example.com",
        )
        self.category = Category.objects.create(name="Selection Clothing")
        self.product = Product.objects.create(
            vendor=self.vendor,
            category=self.category,
            name="Selection Jacket",
            description="A rental jacket.",
            brand="Test",
            daily_rate=Decimal("20.00"),
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            sku="selection-jacket-m",
            size="M",
            colour="Blue",
            total_quantity=2,
        )

    @patch("customer.forms.timezone.localdate", return_value=date(2026, 11, 3))
    def test_valid_selection_calculates_inclusive_rental_total(self, localdate):
        form = RentalSelectionForm(
            data={
                "variant_id": str(self.variant.pk),
                "start_date": "2026-11-03",
                "end_date": "2026-11-05",
                "quantity": "2",
            },
            product=self.product,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["rental_days"], 3)
        self.assertEqual(form.cleaned_data["line_total"], Decimal("120.00"))
        self.assertEqual(
            form.fields["start_date"].widget.attrs["min"],
            "2026-11-03",
        )

    @patch("customer.forms.timezone.localdate", return_value=date(2026, 11, 3))
    def test_variant_from_another_product_is_rejected(self, localdate):
        other_product = Product.objects.create(
            vendor=self.vendor,
            category=self.category,
            name="Other Selection Jacket",
            description="Another rental jacket.",
            brand="Test",
            daily_rate="20.00",
        )
        other_variant = ProductVariant.objects.create(
            product=other_product,
            sku="other-selection-jacket-m",
            size="M",
            colour="Green",
            total_quantity=1,
        )
        form = RentalSelectionForm(
            data={
                "variant_id": str(other_variant.pk),
                "start_date": "2026-11-03",
                "end_date": "2026-11-03",
                "quantity": "1",
            },
            product=self.product,
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["variant_id"],
            ["That variant is not available."],
        )

    @patch("customer.forms.timezone.localdate", return_value=date(2026, 11, 3))
    def test_past_start_date_is_rejected(self, localdate):
        form = RentalSelectionForm(
            data={
                "variant_id": str(self.variant.pk),
                "start_date": "2026-11-02",
                "end_date": "2026-11-03",
                "quantity": "1",
            },
            product=self.product,
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Rental dates cannot start in the past.",
            form.errors["start_date"],
        )


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

    def create_product(
        self,
        name,
        description,
        daily_rate,
        size,
        is_active=True,
    ):
        product = Product.objects.create(
            vendor=self.vendor,
            category=self.category,
            name=name,
            description=description,
            brand="Test brand",
            daily_rate=daily_rate,
            is_active=is_active,
            is_published=True,
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

    def test_unpublished_products_are_hidden_from_public_views(self):
        unpublished_product = self.create_product(
            "Unpublished shirt",
            "Not yet published",
            "12.00",
            "Large",
            is_active=False,
        )

        catalogue_response = self.client.get("/customer/catalogue/")
        detail_response = self.client.get(
            reverse(
                "customer:product_detail",
                args=[unpublished_product.pk],
            )
        )

        self.assertNotContains(catalogue_response, unpublished_product.name)
        self.assertEqual(detail_response.status_code, 404)

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

class PublicProductVisibilityTests(TestCase):
    def setUp(self):
        self.vendor = Vendor.objects.create(
            name="Visibility Test Vendor",
            contact_email="visibility@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )

        category = Category.objects.create(name="Visibility Test")

        self.product = Product.objects.create(
            vendor=self.vendor,
            category=category,
            name="Visibility Test Shirt",
            description="A test rental shirt.",
            brand="Test",
            daily_rate="12.00",
            is_active=True,
            is_published=True,
        )

        self.variant = ProductVariant.objects.create(
            product=self.product,
            sku="visibility-shirt-m",
            size="M",
            colour="Green",
            is_active=True,
            total_quantity=2,
        )

    def assert_hidden_from_customers(self):
        for route in ("customer:catalogue", "customer:home"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))

                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, self.product.name)

        response = self.client.get(
            reverse("customer:product_detail", args=[self.product.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_eligible_product_is_visible(self):
        for route in ("customer:catalogue", "customer:home"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertContains(response, self.product.name)

        response = self.client.get(
            reverse("customer:product_detail", args=[self.product.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_product_detail_post_returns_available_rental_result(self):
        start = timezone.localdate()
        response = self.client.post(
            reverse("customer:product_detail", args=[self.product.pk]),
            {
                "variant_id": self.variant.pk,
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(days=1)).isoformat(),
                "quantity": "2",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["rental_result"],
            {
                "variant": self.variant,
                "quantity": 2,
                "rental_days": 2,
                "line_total": Decimal("48.00"),
                "available_quantity": 2,
            },
        )

    def test_product_detail_post_reports_insufficient_availability(self):
        start = timezone.localdate()
        response = self.client.post(
            reverse("customer:product_detail", args=[self.product.pk]),
            {
                "variant_id": self.variant.pk,
                "start_date": start.isoformat(),
                "end_date": start.isoformat(),
                "quantity": "3",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["rental_result"])
        self.assertIn(
            "Only 2 unit(s) are available for the entire selected period.",
            response.context["rental_form"].errors["quantity"],
        )

    def test_inactive_product_is_hidden(self):
        self.product.is_active = False
        self.product.save()
        self.assert_hidden_from_customers()

    def test_unpublished_product_is_hidden(self):
        self.product.is_published = False
        self.product.save(update_fields=["is_published"])
        self.assert_hidden_from_customers()

    def test_archived_product_is_hidden(self):
        self.product.is_archived = True
        self.product.save()
        self.assert_hidden_from_customers()

    def test_blocked_product_is_hidden(self):
        self.product.moderation_blocked = True
        self.product.save()
        self.assert_hidden_from_customers()

    def test_pending_vendor_product_is_hidden(self):
        self.vendor.approval_status = Vendor.ApprovalStatus.PENDING
        self.vendor.save()
        self.assert_hidden_from_customers()

    def test_rejected_vendor_product_is_hidden(self):
        self.vendor.approval_status = Vendor.ApprovalStatus.REJECTED
        self.vendor.save()
        self.assert_hidden_from_customers()

    def test_suspended_vendor_product_is_hidden(self):
        self.vendor.is_suspended = True
        self.vendor.save()
        self.assert_hidden_from_customers()

    def test_unblocking_does_not_publish_an_inactive_product(self):
        self.product.is_active = False
        self.product.moderation_blocked = True
        self.product.save()

        self.product.moderation_blocked = False
        self.product.save()

        self.assert_hidden_from_customers()


class RentalHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer_group, _ = Group.objects.get_or_create(
            name="Customer"
        )

        cls.customer = get_user_model().objects.create_user(
            username="history-owner"
        )
        cls.other_customer = get_user_model().objects.create_user(
            username="history-other"
        )

        cls.customer.groups.add(cls.customer_group)
        cls.other_customer.groups.add(cls.customer_group)

        vendor = Vendor.objects.create(
            name="History Vendor",
            contact_email="history@example.com",
        )
        category = Category.objects.create(name="History Clothing")

        cls.product = Product.objects.create(
            vendor=vendor,
            category=category,
            name="Original Jacket",
            description="Test clothing",
            brand="Test",
            daily_rate=Decimal("12.00"),
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.product,
            sku="history-jacket-m-blue",
            size="M",
            colour="Blue",
            total_quantity=5,
        )

        def create_order(customer, snapshot_name, address):
            order = RentalOrder.objects.create(
                customer=customer,
                vendor=vendor,
                delivery_address=address,
                payment_status=RentalOrder.PaymentStatus.PAID,
                total_amount=Decimal("72.00"),
            )

            item = RentalItem(
                order=order,
                variant=cls.variant,
                product_name_snapshot=snapshot_name,
                daily_rate_snapshot=Decimal("12.00"),
                quantity=2,
                rental_start_date=date(2026, 11, 10),
                rental_end_date=date(2026, 11, 12),
                rental_days=3,
                line_total=Decimal("72.00"),
                status=RentalItem.Status.CONFIRMED,
            )
            item.full_clean()
            item.save()

            return order, item

        cls.order, cls.item = create_order(
            cls.customer,
            "Snapshot Jacket",
            "Owner delivery address",
        )
        cls.other_order, _ = create_order(
            cls.other_customer,
            "Private rental item",
            "Private delivery address",
        )

    def order_urls(self, order):
        return [
            reverse(
                "customer:order_detail",
                kwargs={"order_id": order.pk},
            ),
            reverse(
                "customer:order_confirmation",
                kwargs={"order_id": order.pk},
            ),
        ]

    def protected_urls(self):
        return [
            reverse("customer:order_history"),
            reverse("customer:account"),
            *self.order_urls(self.order),
        ]

    def test_logged_out_users_are_redirected(self):
        for url in self.protected_urls():
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={url}",
                    fetch_redirect_response=False,
                )

    def test_employee_and_admin_roles_are_forbidden(self):
        for role in ("Vendor Employee", "Platform Admin"):
            group, _ = Group.objects.get_or_create(name=role)
            self.customer.groups.set([group])
            self.client.force_login(self.customer)

            for url in self.protected_urls():
                with self.subTest(role=role, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 403)

    def test_history_lists_only_the_customers_own_orders(self):
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse("customer:order_history")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["orders"]),
            [self.order],
        )

    def test_customer_can_view_own_details_and_paid_confirmation(self):
        self.client.force_login(self.customer)

        for url in self.order_urls(self.order):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["order"],
                    self.order,
                )

                for text in (
                    "Snapshot Jacket",
                    "History Vendor",
                    "Blue",
                    "10 Nov 2026",
                    "12 Nov 2026",
                    "Quantity: 2",
                    "SGD 12.00/day",
                    "Line total: SGD 72.00",
                    "Paid",
                    "Confirmed",
                ):
                    self.assertContains(response, text)

                self.assertNotContains(
                    response, "Private rental item"
                )
                self.assertNotContains(
                    response, "Private delivery address"
                )

    def test_another_customers_order_returns_404(self):
        self.client.force_login(self.customer)

        for url in self.order_urls(self.other_order):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)

    def test_unpaid_orders_cannot_show_successful_confirmation(self):
        self.client.force_login(self.customer)

        url = reverse(
            "customer:order_confirmation",
            kwargs={"order_id": self.order.pk},
        )

        for status in (
            RentalOrder.PaymentStatus.PENDING,
            RentalOrder.PaymentStatus.FAILED,
        ):
            with self.subTest(status=status):
                self.order.payment_status = status
                self.order.save(update_fields=["payment_status"])

                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)

    def test_customer_with_no_orders_sees_empty_history(self):
        empty_customer = get_user_model().objects.create_user(
            username="history-empty"
        )
        empty_customer.groups.add(self.customer_group)
        self.client.force_login(empty_customer)

        response = self.client.get(
            reverse("customer:order_history")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["orders"]), [])
        self.assertContains(response, "Browse clothing")

    def test_product_edits_do_not_change_displayed_snapshots(self):
        self.product.name = "Updated Live Listing"
        self.product.daily_rate = Decimal("40.00")
        self.product.save()

        self.client.force_login(self.customer)

        for url in self.order_urls(self.order):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertContains(response, "Snapshot Jacket")
                self.assertContains(response, "SGD 12.00/day")
                self.assertContains(
                    response, "Order total: SGD 72.00"
                )
                self.assertNotContains(
                    response, "Updated Live Listing"
                )
                self.assertNotContains(response, "SGD 40.00/day")

    def test_reopening_confirmation_does_not_create_orders_or_clear_cart(self):
        self.client.force_login(self.customer)

        cart = [{
            "variant_id": self.variant.pk,
            "quantity": 1,
            "start_date": "2026-11-15",
            "end_date": "2026-11-16",
        }]

        session = self.client.session
        session["rental_cart"] = cart
        session.save()

        before = (
            RentalOrder.objects.count(),
            RentalItem.objects.count(),
        )

        url = reverse(
            "customer:order_confirmation",
            kwargs={"order_id": self.order.pk},
        )

        for _ in range(2):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

        self.assertEqual(
            (
                RentalOrder.objects.count(),
                RentalItem.objects.count(),
            ),
            before,
        )
        self.assertEqual(
            self.client.session["rental_cart"],
            cart,
        )


class SessionRentalCartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        customer_group, _ = Group.objects.get_or_create(name="Customer")
        cls.customer = get_user_model().objects.create_user(
            username="cart-customer",
            password="test-password",
        )
        cls.customer.groups.add(customer_group)

        cls.vendor = Vendor.objects.create(
            name="Cart Vendor",
            contact_email="cart@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )
        cls.category = Category.objects.create(name="Cart Clothing")
        cls.product = cls.create_product(
            vendor=cls.vendor,
            name="Cart Jacket",
            sku="cart-jacket-m",
        )

        cls.other_vendor = Vendor.objects.create(
            name="Other Cart Vendor",
            contact_email="other-cart@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )
        cls.other_product = cls.create_product(
            vendor=cls.other_vendor,
            name="Other Cart Jacket",
            sku="other-cart-jacket-m",
        )

    @classmethod
    def create_product(cls, *, vendor, name, sku):
        product = Product.objects.create(
            vendor=vendor,
            category=cls.category,
            name=name,
            description="A cart test product.",
            brand="Test",
            daily_rate=Decimal("20.00"),
            is_active=True,
            is_published=True,
        )
        ProductVariant.objects.create(
            product=product,
            sku=sku,
            size="M",
            colour="Blue",
            total_quantity=3,
        )
        return product

    def setUp(self):
        self.client.force_login(self.customer)

    def add_product(self, product, *, start, end, quantity="1"):
        variant = product.variants.get()
        return self.client.post(
            reverse("customer:cart_add", args=[product.pk]),
            {
                "variant_id": variant.pk,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "quantity": quantity,
            },
        )

    def test_customer_can_add_a_valid_selection_to_the_session(self):
        start = timezone.localdate() + timedelta(days=1)
        response = self.add_product(
            self.product,
            start=start,
            end=start + timedelta(days=2),
            quantity="2",
        )

        self.assertRedirects(
            response,
            reverse("customer:product_detail", args=[self.product.pk]),
        )
        self.assertEqual(
            self.client.session["rental_cart"],
            [{
                "variant_id": self.product.variants.get().pk,
                "quantity": 2,
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(days=2)).isoformat(),
            }],
        )

    def test_cart_lines_keep_their_own_rental_dates(self):
        first_start = timezone.localdate() + timedelta(days=1)
        second_start = timezone.localdate() + timedelta(days=5)

        self.add_product(
            self.product,
            start=first_start,
            end=first_start + timedelta(days=1),
        )
        self.add_product(
            self.product,
            start=second_start,
            end=second_start + timedelta(days=2),
        )

        cart = self.client.session["rental_cart"]
        self.assertEqual(len(cart), 2)
        self.assertEqual(cart[0]["start_date"], first_start.isoformat())
        self.assertEqual(cart[1]["start_date"], second_start.isoformat())
        self.assertEqual(
            cart[1]["end_date"],
            (second_start + timedelta(days=2)).isoformat(),
        )

    def test_product_from_another_vendor_is_rejected(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(self.product, start=start, end=start)
        original_cart = self.client.session["rental_cart"]

        response = self.add_product(
            self.other_product,
            start=start,
            end=start,
        )

        self.assertRedirects(
            response,
            reverse(
                "customer:product_detail",
                args=[self.other_product.pk],
            ),
        )
        self.assertEqual(self.client.session["rental_cart"], original_cart)

    def test_adding_to_cart_does_not_create_a_reservation(self):
        start = timezone.localdate() + timedelta(days=1)

        self.add_product(self.product, start=start, end=start)

        self.assertEqual(RentalOrder.objects.count(), 0)
        self.assertEqual(RentalItem.objects.count(), 0)

    def test_anonymous_user_must_log_in_before_adding(self):
        self.client.logout()
        start = timezone.localdate() + timedelta(days=1)

        response = self.add_product(self.product, start=start, end=start)

        add_url = reverse("customer:cart_add", args=[self.product.pk])
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={add_url}",
            fetch_redirect_response=False,
        )
        self.assertNotIn("rental_cart", self.client.session)

    def test_cart_page_shows_server_side_prices_and_totals(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(
            self.product,
            start=start,
            end=start + timedelta(days=2),
            quantity="2",
        )
        self.add_product(
            self.product,
            start=start + timedelta(days=5),
            end=start + timedelta(days=5),
        )

        response = self.client.get(reverse("customer:cart"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cart_total"], Decimal("140.00"))
        self.assertEqual(len(response.context["cart_lines"]), 2)
        line = response.context["cart_lines"][0]
        self.assertEqual(line["rental_days"], 3)
        self.assertEqual(line["daily_rate"], Decimal("20.00"))
        self.assertEqual(line["line_total"], Decimal("120.00"))

        for text in (
            "Cart Jacket",
            "Cart Vendor",
            "M / Blue",
            "3 days",
            "SGD 20.00",
            "SGD 120.00",
            "SGD 140.00",
        ):
            self.assertContains(response, text)

    def test_cart_update_changes_values_and_ignores_submitted_prices(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(self.product, start=start, end=start)
        new_end = start + timedelta(days=1)

        response = self.client.post(
            reverse("customer:cart_update", args=[0]),
            {
                "line-0-start_date": start.isoformat(),
                "line-0-end_date": new_end.isoformat(),
                "line-0-quantity": "2",
                "daily_rate": "0.01",
                "line_total": "0.01",
                "cart_total": "0.01",
            },
        )

        self.assertRedirects(response, reverse("customer:cart"))
        self.assertEqual(
            self.client.session["rental_cart"][0],
            {
                "variant_id": self.product.variants.get().pk,
                "quantity": 2,
                "start_date": start.isoformat(),
                "end_date": new_end.isoformat(),
            },
        )

        cart_response = self.client.get(reverse("customer:cart"))
        self.assertEqual(
            cart_response.context["cart_total"],
            Decimal("80.00"),
        )

    def test_invalid_cart_update_leaves_the_line_unchanged(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(self.product, start=start, end=start)
        original_line = self.client.session["rental_cart"][0]

        response = self.client.post(
            reverse("customer:cart_update", args=[0]),
            {
                "line-0-start_date": start.isoformat(),
                "line-0-end_date": (start + timedelta(days=7)).isoformat(),
                "line-0-quantity": "1",
            },
        )

        self.assertRedirects(response, reverse("customer:cart"))
        self.assertEqual(
            self.client.session["rental_cart"][0],
            original_line,
        )

    def test_unavailable_cart_update_leaves_the_line_unchanged(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(self.product, start=start, end=start)
        original_line = self.client.session["rental_cart"][0]
        order = RentalOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            delivery_address="1 Test Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("40.00"),
        )
        item = RentalItem(
            order=order,
            variant=self.product.variants.get(),
            product_name_snapshot=self.product.name,
            daily_rate_snapshot=Decimal("20.00"),
            quantity=2,
            rental_start_date=start,
            rental_end_date=start,
            rental_days=1,
            line_total=Decimal("40.00"),
        )
        item.full_clean()
        item.save()

        response = self.client.post(
            reverse("customer:cart_update", args=[0]),
            {
                "line-0-start_date": start.isoformat(),
                "line-0-end_date": start.isoformat(),
                "line-0-quantity": "2",
            },
        )

        self.assertRedirects(response, reverse("customer:cart"))
        self.assertEqual(
            self.client.session["rental_cart"][0],
            original_line,
        )

    def test_customer_can_remove_a_cart_line(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(self.product, start=start, end=start)

        response = self.client.post(
            reverse("customer:cart_remove", args=[0]),
        )

        self.assertRedirects(response, reverse("customer:cart"))
        self.assertEqual(self.client.session["rental_cart"], [])

        empty_response = self.client.get(reverse("customer:cart"))
        self.assertContains(empty_response, "Your cart is empty")

    def test_anonymous_user_must_log_in_to_view_the_cart(self):
        self.client.logout()
        cart_url = reverse("customer:cart")

        response = self.client.get(cart_url)

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={cart_url}",
            fetch_redirect_response=False,
        )

    def test_checkout_page_shows_summary_without_card_fields(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(
            self.product,
            start=start,
            end=start + timedelta(days=1),
            quantity="2",
        )

        response = self.client.get(reverse("customer:checkout"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.context["form"].fields),
            {"delivery_address", "confirm_payment"},
        )
        self.assertEqual(response.context["cart_total"], Decimal("80.00"))
        self.assertContains(response, "Final order summary")
        self.assertContains(response, "No real payment-card details")

    def test_successful_checkout_creates_snapshots_and_clears_cart(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(
            self.product,
            start=start,
            end=start + timedelta(days=1),
            quantity="2",
        )

        response = self.client.post(
            reverse("customer:checkout"),
            {
                "delivery_address": "10 Checkout Street",
                "confirm_payment": "on",
                "daily_rate": "0.01",
                "total_amount": "0.01",
                "card_number": "not-stored",
            },
        )

        order = RentalOrder.objects.get()
        item = order.items.get()
        self.assertRedirects(
            response,
            reverse("customer:order_confirmation", args=[order.pk]),
        )
        self.assertEqual(order.customer, self.customer)
        self.assertEqual(order.vendor, self.vendor)
        self.assertEqual(order.delivery_address, "10 Checkout Street")
        self.assertEqual(
            order.payment_status,
            RentalOrder.PaymentStatus.PAID,
        )
        self.assertEqual(order.total_amount, Decimal("80.00"))
        self.assertEqual(item.product_name_snapshot, "Cart Jacket")
        self.assertEqual(item.daily_rate_snapshot, Decimal("20.00"))
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.rental_days, 2)
        self.assertEqual(item.line_total, Decimal("80.00"))
        self.assertEqual(item.status, RentalItem.Status.CONFIRMED)
        self.assertEqual(self.client.session["rental_cart"], [])

    def test_unconfirmed_payment_keeps_cart_and_creates_no_order(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(self.product, start=start, end=start)
        original_cart = self.client.session["rental_cart"]

        response = self.client.post(
            reverse("customer:checkout"),
            {"delivery_address": "10 Checkout Street"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "confirm_payment",
            "This field is required.",
        )
        self.assertEqual(RentalOrder.objects.count(), 0)
        self.assertEqual(RentalItem.objects.count(), 0)
        self.assertEqual(self.client.session["rental_cart"], original_cart)

    def test_checkout_rechecks_combined_overlapping_cart_quantity(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(
            self.product,
            start=start,
            end=start,
            quantity="2",
        )
        self.add_product(
            self.product,
            start=start,
            end=start,
            quantity="2",
        )
        original_cart = self.client.session["rental_cart"]

        response = self.client.post(
            reverse("customer:checkout"),
            {
                "delivery_address": "10 Checkout Street",
                "confirm_payment": "on",
            },
        )

        self.assertRedirects(response, reverse("customer:cart"))
        self.assertEqual(RentalOrder.objects.count(), 0)
        self.assertEqual(RentalItem.objects.count(), 0)
        self.assertEqual(self.client.session["rental_cart"], original_cart)

    def test_checkout_rechecks_rentals_created_after_cart_addition(self):
        start = timezone.localdate() + timedelta(days=1)
        self.add_product(
            self.product,
            start=start,
            end=start,
            quantity="2",
        )
        original_cart = self.client.session["rental_cart"]
        existing_order = RentalOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            delivery_address="Existing rental address",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("40.00"),
        )
        existing_item = RentalItem(
            order=existing_order,
            variant=self.product.variants.get(),
            product_name_snapshot=self.product.name,
            daily_rate_snapshot=Decimal("20.00"),
            quantity=2,
            rental_start_date=start,
            rental_end_date=start,
            rental_days=1,
            line_total=Decimal("40.00"),
        )
        existing_item.full_clean()
        existing_item.save()
        order_count = RentalOrder.objects.count()
        item_count = RentalItem.objects.count()

        response = self.client.post(
            reverse("customer:checkout"),
            {
                "delivery_address": "10 Checkout Street",
                "confirm_payment": "on",
            },
        )

        self.assertRedirects(response, reverse("customer:cart"))
        self.assertEqual(RentalOrder.objects.count(), order_count)
        self.assertEqual(RentalItem.objects.count(), item_count)
        self.assertEqual(self.client.session["rental_cart"], original_cart)

    def test_empty_cart_cannot_be_checked_out(self):
        response = self.client.get(reverse("customer:checkout"))

        self.assertRedirects(response, reverse("customer:cart"))
        self.assertEqual(RentalOrder.objects.count(), 0)
