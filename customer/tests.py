from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from accounts.roles import CUSTOMER_GROUP
from customer.forms import RentalSelectionForm, StyleQuizForm
from customer.models import CustomerProductInteraction, WishlistItem
from recommendations.services import (
    EXPECTED_LABELS,
    StyleModelError,
    load_style_artifact,
    predict_style,
    rank_recommended_products,
    recommendation_score,
)
from shop.availability import available_quantity_by_day
from shop.models import (
    Category,
    CustomerStyleProfile,
    Product,
    ProductReview,
    ProductVariant,
    RentalItem,
    RentalOrder,
    StyleTag,
    Vendor,
)


VALID_STYLE_QUIZ = {
    "silhouette": "sculptural_asymmetric",
    "details": "experimental_details",
    "impression": "bold_unforgettable",
    "styling_approach": "unexpected_contrast",
    "statement_level": "high",
    "palette": "neutral",
}


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
        customer_group, _ = Group.objects.get_or_create(name=CUSTOMER_GROUP)
        self.customer = get_user_model().objects.create_user(
            username="visibility-customer",
        )
        self.customer.groups.add(customer_group)
        self.client.force_login(self.customer)
        style_tag = StyleTag.objects.get(slug="minimalist_clean")
        CustomerStyleProfile.objects.create(
            customer=self.customer,
            silhouette="clean_fitted",
            details="minimal_details",
            impression="understated",
            styling_approach="simple_coordinated",
            statement_level="low",
            palette="neutral",
            predicted_style=style_tag,
            model_version="test",
        )
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
        self.product.style_tags.add(style_tag)

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
            reverse(
                "customer:order_cancel",
                kwargs={"order_id": self.order.pk},
            ),
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

    def test_tracking_pages_label_item_status_and_expected_return(self):
        self.client.force_login(self.customer)

        for url in (
            reverse("customer:order_history"),
            reverse(
                "customer:order_detail",
                kwargs={"order_id": self.order.pk},
            ),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertContains(response, "Confirmed")
                self.assertContains(response, "Rental starts")
                self.assertContains(response, "Expected return")
                self.assertContains(response, "10 Nov 2026")
                self.assertContains(response, "12 Nov 2026")

    def test_cancellable_order_shows_cancel_action(self):
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse(
                "customer:order_detail",
                kwargs={"order_id": self.order.pk},
            )
        )

        self.assertTrue(response.context["can_cancel"])
        self.assertContains(response, "Cancel order")

    def test_customer_can_cancel_entire_order_before_dispatch(self):
        second_item = RentalItem.objects.create(
            order=self.order,
            variant=self.variant,
            product_name_snapshot="Second Snapshot Jacket",
            daily_rate_snapshot=Decimal("12.00"),
            quantity=1,
            rental_start_date=date(2026, 11, 15),
            rental_end_date=date(2026, 11, 16),
            rental_days=2,
            line_total=Decimal("24.00"),
            status=RentalItem.Status.PREPARING,
        )
        self.item.status = RentalItem.Status.PREPARING
        self.item.save(update_fields=["status"])
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse(
                "customer:order_cancel",
                kwargs={"order_id": self.order.pk},
            )
        )

        self.assertRedirects(
            response,
            reverse(
                "customer:order_detail",
                kwargs={"order_id": self.order.pk},
            ),
        )
        self.order.refresh_from_db()
        self.item.refresh_from_db()
        second_item.refresh_from_db()
        self.assertEqual(
            self.order.payment_status,
            RentalOrder.PaymentStatus.REFUNDED,
        )
        self.assertEqual(self.item.status, RentalItem.Status.CANCELLED)
        self.assertEqual(second_item.status, RentalItem.Status.CANCELLED)

    def test_dispatched_item_blocks_the_whole_cancellation(self):
        self.item.status = RentalItem.Status.DISPATCHED
        self.item.save(update_fields=["status"])
        other_item = RentalItem.objects.create(
            order=self.order,
            variant=self.variant,
            product_name_snapshot="Still Confirmed Jacket",
            daily_rate_snapshot=Decimal("12.00"),
            quantity=1,
            rental_start_date=date(2026, 11, 15),
            rental_end_date=date(2026, 11, 16),
            rental_days=2,
            line_total=Decimal("24.00"),
            status=RentalItem.Status.CONFIRMED,
        )
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse(
                "customer:order_cancel",
                kwargs={"order_id": self.order.pk},
            )
        )

        self.assertRedirects(
            response,
            reverse(
                "customer:order_detail",
                kwargs={"order_id": self.order.pk},
            ),
        )
        self.order.refresh_from_db()
        self.item.refresh_from_db()
        other_item.refresh_from_db()
        self.assertEqual(
            self.order.payment_status,
            RentalOrder.PaymentStatus.PAID,
        )
        self.assertEqual(self.item.status, RentalItem.Status.DISPATCHED)
        self.assertEqual(other_item.status, RentalItem.Status.CONFIRMED)

    def test_cancelled_order_releases_rental_availability(self):
        before = available_quantity_by_day(
            variant=self.variant,
            start_date=self.item.rental_start_date,
            end_date=self.item.rental_end_date,
        )
        self.client.force_login(self.customer)

        self.client.post(
            reverse(
                "customer:order_cancel",
                kwargs={"order_id": self.order.pk},
            )
        )

        after = available_quantity_by_day(
            variant=self.variant,
            start_date=self.item.rental_start_date,
            end_date=self.item.rental_end_date,
        )
        for rental_date in before:
            with self.subTest(rental_date=rental_date):
                self.assertEqual(
                    after[rental_date],
                    before[rental_date] + self.item.quantity,
                )

    def test_customer_cannot_cancel_another_customers_order(self):
        self.client.force_login(self.other_customer)

        response = self.client.post(
            reverse(
                "customer:order_cancel",
                kwargs={"order_id": self.order.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
        self.order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(
            self.order.payment_status,
            RentalOrder.PaymentStatus.PAID,
        )
        self.assertEqual(self.item.status, RentalItem.Status.CONFIRMED)

    def test_cancellation_endpoint_rejects_get_requests(self):
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse(
                "customer:order_cancel",
                kwargs={"order_id": self.order.pk},
            )
        )

        self.assertEqual(response.status_code, 405)

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


class StyleQuizFormTests(TestCase):
    def test_valid_answers_are_accepted(self):
        form = StyleQuizForm(data=VALID_STYLE_QUIZ)

        self.assertTrue(form.is_valid())

    def test_unknown_choice_is_rejected(self):
        answers = {
            **VALID_STYLE_QUIZ,
            "silhouette": "invented_style",
        }

        form = StyleQuizForm(data=answers)

        self.assertFalse(form.is_valid())
        self.assertIn("silhouette", form.errors)

    def test_missing_answer_is_rejected(self):
        answers = {
            key: value
            for key, value in VALID_STYLE_QUIZ.items()
            if key != "palette"
        }

        form = StyleQuizForm(data=answers)

        self.assertFalse(form.is_valid())
        self.assertIn("palette", form.errors)


class StyleQuizViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer_group, _ = Group.objects.get_or_create(
            name=CUSTOMER_GROUP
        )

        cls.customer = get_user_model().objects.create_user(
            username="style-customer",
        )
        cls.customer.groups.add(cls.customer_group)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(
            reverse("customer:style_preferences")
        )

        self.assertRedirects(
            response,
            (
                reverse("accounts:login")
                + "?next="
                + reverse("customer:style_preferences")
            ),
        )

    def test_customer_can_view_quiz(self):
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse("customer:style_preferences")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "customer/style_preferences.html",
        )
        self.assertIsInstance(
            response.context["form"],
            StyleQuizForm,
        )

    def test_valid_quiz_submission_redirects(self):
        self.client.force_login(self.customer)

        with patch(
            "customer.views.predict_style",
            return_value={
                "style": "avant_garde_statement",
                "model_version": "test-version",
            },
        ):
            response = self.client.post(
                reverse("customer:style_preferences"),
                VALID_STYLE_QUIZ,
            )

        self.assertRedirects(
            response,
            reverse("customer:home"),
        )
        self.assertEqual(
            self.customer.style_profile.predicted_style.slug,
            "avant_garde_statement",
        )

    def test_retaking_quiz_updates_existing_profile(self):
        self.client.force_login(self.customer)

        with patch(
            "customer.views.predict_style",
            return_value={
                "style": "avant_garde_statement",
                "model_version": "test-version",
            },
        ):
            self.client.post(
                reverse("customer:style_preferences"),
                VALID_STYLE_QUIZ,
            )

        second_answers = {
            "silhouette": "clean_fitted",
            "details": "minimal_details",
            "impression": "understated",
            "styling_approach": "simple_coordinated",
            "statement_level": "low",
            "palette": "neutral",
        }

        with patch(
            "customer.views.predict_style",
            return_value={
                "style": "minimalist_clean",
                "model_version": "test-version",
            },
        ):
            self.client.post(
                reverse("customer:style_preferences"),
                second_answers,
            )

        self.assertEqual(
            CustomerStyleProfile.objects.filter(
                customer=self.customer
            ).count(),
            1,
        )
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.style_profile.silhouette,
            "clean_fitted",
        )

    def test_missing_model_shows_error_without_saving_profile(self):
        self.client.force_login(self.customer)

        with patch(
            "customer.views.predict_style",
            side_effect=StyleModelError("missing model"),
        ):
            response = self.client.post(
                reverse("customer:style_preferences"),
                VALID_STYLE_QUIZ,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "temporarily unavailable")
        self.assertFalse(
            CustomerStyleProfile.objects.filter(
                customer=self.customer
            ).exists()
        )

    def test_missing_predicted_style_tag_shows_error_without_saving(self):
        self.client.force_login(self.customer)

        with patch(
            "customer.views.predict_style",
            return_value={
                "style": "unconfigured_style",
                "model_version": "test-version",
            },
        ):
            response = self.client.post(
                reverse("customer:style_preferences"),
                VALID_STYLE_QUIZ,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "predicted style is not configured")
        self.assertFalse(
            CustomerStyleProfile.objects.filter(
                customer=self.customer
            ).exists()
        )

    def test_tampered_value_is_displayed_as_error(self):
        self.client.force_login(self.customer)

        answers = {
            **VALID_STYLE_QUIZ,
            "palette": "not-a-real-palette",
        }

        response = self.client.post(
            reverse("customer:style_preferences"),
            answers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Select a valid choice",
        )

    def test_non_customer_account_is_forbidden(self):
        vendor_group, _ = Group.objects.get_or_create(
            name="Vendor Employee"
        )
        vendor_user = get_user_model().objects.create_user(
            username="style-vendor",
        )
        vendor_user.groups.add(vendor_group)
        self.client.force_login(vendor_user)

        response = self.client.get(
            reverse("customer:style_preferences")
        )

        self.assertEqual(response.status_code, 403)

    def test_customer_without_profile_is_redirected_to_quiz(self):
        CustomerStyleProfile.objects.filter(customer=self.customer).delete()
        self.client.force_login(self.customer)

        response = self.client.get(reverse("customer:home"))

        self.assertRedirects(
            response,
            reverse("customer:style_preferences"),
        )

    def test_anonymous_user_is_redirected_from_for_you(self):
        response = self.client.get(reverse("customer:home"))

        self.assertRedirects(
            response,
            (
                reverse("accounts:login")
                + "?next="
                + reverse("customer:home")
            ),
        )

    def test_customer_product_views_are_aggregated(self):
        category = Category.objects.create(name="Viewed products")
        vendor = Vendor.objects.create(
            name="Viewed product vendor",
            contact_email="views@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )
        product = Product.objects.create(
            vendor=vendor,
            category=category,
            name="Viewed Jacket",
            description="A viewed product.",
            brand="Test",
            daily_rate=Decimal("10.00"),
            is_active=True,
            is_published=True,
        )
        ProductVariant.objects.create(
            product=product,
            sku="viewed-jacket-m",
            size="M",
            colour="Blue",
            total_quantity=1,
        )
        product_url = reverse(
            "customer:product_detail",
            args=[product.pk],
        )
        self.client.force_login(self.customer)

        self.client.get(product_url)
        self.client.get(product_url)
        self.client.logout()
        self.client.get(product_url)

        interaction = CustomerProductInteraction.objects.get(
            customer=self.customer,
            product=product,
        )
        self.assertEqual(interaction.view_count, 2)

    def test_for_you_filters_by_style_and_product_visibility(self):
        self.client.force_login(self.customer)
        CustomerStyleProfile.objects.create(
            customer=self.customer,
            silhouette="clean_fitted",
            details="minimal_details",
            impression="understated",
            styling_approach="simple_coordinated",
            statement_level="low",
            palette="neutral",
            predicted_style=StyleTag.objects.get(
                slug="minimalist_clean"
            ),
            model_version="test",
        )
        category = Category.objects.create(name="Style recommendation")
        vendor = Vendor.objects.create(
            name="Style recommendation vendor",
            contact_email="style-products@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )
        matching = Product.objects.create(
            vendor=vendor,
            category=category,
            name="Matching style jacket",
            description="Matching style.",
            brand="Test",
            daily_rate=Decimal("10.00"),
            is_active=True,
            is_published=True,
        )
        matching.style_tags.add(
            StyleTag.objects.get(slug="minimalist_clean")
        )
        ProductVariant.objects.create(
            product=matching,
            sku="matching-style-jacket",
            size="M",
            colour="Blue",
            total_quantity=1,
        )

        wrong_style = Product.objects.create(
            vendor=vendor,
            category=category,
            name="Wrong style jacket",
            description="Wrong style.",
            brand="Test",
            daily_rate=Decimal("10.00"),
            is_active=True,
            is_published=True,
        )
        wrong_style.style_tags.add(
            StyleTag.objects.get(slug="urban_streetwear")
        )
        ProductVariant.objects.create(
            product=wrong_style,
            sku="wrong-style-jacket",
            size="M",
            colour="Black",
            total_quantity=1,
        )

        blocked = Product.objects.create(
            vendor=vendor,
            category=category,
            name="Blocked matching jacket",
            description="Blocked matching style.",
            brand="Test",
            daily_rate=Decimal("10.00"),
            is_active=True,
            is_published=True,
            moderation_blocked=True,
        )
        blocked.style_tags.add(
            StyleTag.objects.get(slug="minimalist_clean")
        )
        ProductVariant.objects.create(
            product=blocked,
            sku="blocked-matching-jacket",
            size="M",
            colour="Green",
            total_quantity=1,
        )

        out_of_stock = Product.objects.create(
            vendor=vendor,
            category=category,
            name="Out of stock matching jacket",
            description="Unavailable matching style.",
            brand="Test",
            daily_rate=Decimal("10.00"),
            is_active=True,
            is_published=True,
        )
        out_of_stock.style_tags.add(
            StyleTag.objects.get(slug="minimalist_clean")
        )
        ProductVariant.objects.create(
            product=out_of_stock,
            sku="out-of-stock-matching-jacket",
            size="M",
            colour="White",
            total_quantity=0,
        )

        response = self.client.get(reverse("customer:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, matching.name)
        self.assertNotContains(response, wrong_style.name)
        self.assertNotContains(response, blocked.name)
        self.assertNotContains(response, out_of_stock.name)


class RecommendationRankingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        vendor = Vendor.objects.create(
            name="Ranking Vendor",
            contact_email="ranking@example.com",
        )
        category = Category.objects.create(name="Ranking Clothing")
        cls.predicted_style = StyleTag.objects.get(
            slug="minimalist_clean"
        )
        cls.completed_style = StyleTag.objects.get(
            slug="urban_streetwear"
        )

        def create_product(name, style_tag):
            product = Product.objects.create(
                vendor=vendor,
                category=category,
                name=name,
                description="Ranking test product.",
                brand="Test",
                daily_rate=Decimal("10.00"),
            )
            product.style_tags.add(style_tag)
            return product

        cls.predicted_product = create_product(
            "Predicted Style Product",
            cls.predicted_style,
        )
        cls.viewed_product = create_product(
            "Viewed Product",
            cls.completed_style,
        )
        cls.completed_style_product = create_product(
            "Completed Style Product",
            cls.completed_style,
        )

    def test_ranking_is_ml_led_capped_and_deterministic(self):
        products = list(
            Product.objects.filter(
                pk__in={
                    self.predicted_product.pk,
                    self.viewed_product.pk,
                    self.completed_style_product.pk,
                }
            ).prefetch_related("style_tags")
        )
        viewed_score = recommendation_score(
            self.viewed_product,
            predicted_style_id=self.predicted_style.pk,
            view_count=100,
        )
        completed_score = recommendation_score(
            self.completed_style_product,
            predicted_style_id=self.predicted_style.pk,
            completed_style_ids={self.completed_style.pk},
        )
        ranked = rank_recommended_products(
            products,
            predicted_style_id=self.predicted_style.pk,
            view_counts={self.viewed_product.pk: 100},
            completed_style_ids={self.completed_style.pk},
        )

        self.assertEqual(viewed_score, 10)
        self.assertEqual(completed_score, 10)
        self.assertEqual(ranked[0], self.predicted_product)


class WishlistTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        customer_group, _ = Group.objects.get_or_create(
            name=CUSTOMER_GROUP
        )
        cls.customer = get_user_model().objects.create_user(
            username="wishlist-customer",
        )
        cls.other_customer = get_user_model().objects.create_user(
            username="other-wishlist-customer",
        )
        cls.customer.groups.add(customer_group)
        cls.other_customer.groups.add(customer_group)
        cls.style_tag = StyleTag.objects.get(slug="minimalist_clean")
        CustomerStyleProfile.objects.create(
            customer=cls.customer,
            silhouette="clean_fitted",
            details="minimal_details",
            impression="understated",
            styling_approach="simple_coordinated",
            statement_level="low",
            palette="neutral",
            predicted_style=cls.style_tag,
            model_version="test",
        )
        vendor = Vendor.objects.create(
            name="Wishlist Vendor",
            contact_email="wishlist@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )
        category = Category.objects.create(name="Wishlist Clothing")

        def create_product(name, sku):
            product = Product.objects.create(
                vendor=vendor,
                category=category,
                name=name,
                description="Wishlist test product.",
                brand="Test",
                daily_rate=Decimal("10.00"),
                is_active=True,
                is_published=True,
            )
            product.style_tags.add(cls.style_tag)
            ProductVariant.objects.create(
                product=product,
                sku=sku,
                size="M",
                colour="Blue",
                total_quantity=1,
            )
            return product

        cls.older_product = create_product(
            "Older Wishlist Jacket",
            "older-wishlist-jacket",
        )
        cls.newer_product = create_product(
            "Newer Wishlist Jacket",
            "newer-wishlist-jacket",
        )

    def test_add_is_duplicate_safe_and_remove_is_repeatable(self):
        self.client.force_login(self.customer)
        add_url = reverse(
            "customer:wishlist_add",
            args=[self.older_product.pk],
        )
        remove_url = reverse(
            "customer:wishlist_remove",
            args=[self.older_product.pk],
        )

        self.client.post(add_url)
        self.client.post(add_url)

        self.assertEqual(
            WishlistItem.objects.filter(
                customer=self.customer,
                product=self.older_product,
            ).count(),
            1,
        )

        self.client.post(remove_url)
        self.client.post(remove_url)

        self.assertFalse(
            WishlistItem.objects.filter(
                customer=self.customer,
                product=self.older_product,
            ).exists()
        )

    def test_wishlist_page_is_protected_and_customer_specific(self):
        WishlistItem.objects.create(
            customer=self.customer,
            product=self.older_product,
        )
        other_item = WishlistItem.objects.create(
            customer=self.other_customer,
            product=self.newer_product,
        )
        wishlist_url = reverse("customer:wishlist")

        anonymous_response = self.client.get(wishlist_url)
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.customer)
        response = self.client.get(wishlist_url)
        self.client.post(
            reverse(
                "customer:wishlist_remove",
                args=[self.newer_product.pk],
            )
        )

        self.assertContains(response, self.older_product.name)
        self.assertContains(response, "Remove from wishlist")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertNotContains(response, self.newer_product.name)
        self.assertTrue(WishlistItem.objects.filter(pk=other_item.pk).exists())

    def test_wishlist_signal_adjusts_for_you_ranking(self):
        WishlistItem.objects.create(
            customer=self.customer,
            product=self.older_product,
        )
        self.client.force_login(self.customer)

        response = self.client.get(reverse("customer:home"))

        self.assertEqual(response.context["products"][0], self.older_product)


class StylePredictionServiceTests(TestCase):
    def tearDown(self):
        load_style_artifact.cache_clear()

    def test_real_saved_model_returns_supported_style(self):
        result = predict_style(VALID_STYLE_QUIZ)

        self.assertIn(result["style"], EXPECTED_LABELS)
        self.assertTrue(result["model_version"])

    def test_missing_model_file_raises_style_model_error(self):
        with TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "missing.joblib"

            with patch(
                "recommendations.services.MODEL_PATH",
                missing_path,
            ):
                with self.assertRaises(StyleModelError):
                    load_style_artifact()


class ProductReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        customer_group, _ = Group.objects.get_or_create(
            name=CUSTOMER_GROUP,
        )
        User = get_user_model()
        cls.customer = User.objects.create_user(
            username="review-customer",
            password="test-password",
        )
        cls.other_customer = User.objects.create_user(
            username="other-review-customer",
            password="test-password",
        )
        cls.customer.groups.add(customer_group)
        cls.other_customer.groups.add(customer_group)

        cls.vendor = Vendor.objects.create(
            name="Review Vendor",
            contact_email="reviews@example.com",
            approval_status=Vendor.ApprovalStatus.APPROVED,
        )
        category = Category.objects.create(name="Review Clothing")
        cls.product = Product.objects.create(
            vendor=cls.vendor,
            category=category,
            name="Review Jacket",
            description="A jacket customers can review.",
            brand="Test",
            daily_rate=Decimal("10.00"),
            is_active=True,
            is_published=True,
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.product,
            sku="review-jacket-m",
            size="M",
            colour="Blue",
            total_quantity=3,
        )
        cls.order = cls._create_order(cls.customer)
        cls.completed_item = cls._create_item(
            cls.order,
            RentalItem.Status.COMPLETED,
        )
        cls.active_item = cls._create_item(
            cls.order,
            RentalItem.Status.ACTIVE,
        )
        cls.other_order = cls._create_order(cls.other_customer)
        cls.other_completed_item = cls._create_item(
            cls.other_order,
            RentalItem.Status.COMPLETED,
        )

    @classmethod
    def _create_order(cls, customer):
        return RentalOrder.objects.create(
            customer=customer,
            vendor=cls.vendor,
            delivery_address="1 Review Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("10.00"),
        )

    @classmethod
    def _create_item(cls, order, status):
        rental_date = date.today()
        return RentalItem.objects.create(
            order=order,
            variant=cls.variant,
            product_name_snapshot=cls.product.name,
            daily_rate_snapshot=Decimal("10.00"),
            quantity=1,
            rental_start_date=rental_date,
            rental_end_date=rental_date,
            rental_days=1,
            line_total=Decimal("10.00"),
            status=status,
        )

    def test_only_owner_of_completed_item_can_submit_once(self):
        review_url = reverse(
            "customer:review_create",
            args=[self.completed_item.pk],
        )
        review_data = {
            "rating": 5,
            "review_text": "Excellent condition and a great fit.",
        }

        self.assertEqual(self.client.get(review_url).status_code, 302)

        self.client.force_login(self.customer)
        response = self.client.post(review_url, review_data)

        self.assertRedirects(
            response,
            reverse("customer:product_detail", args=[self.product.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            ProductReview.objects.filter(
                rental_item=self.completed_item,
            ).count(),
            1,
        )

        duplicate_response = self.client.post(
            review_url,
            review_data,
            follow=True,
        )
        self.assertContains(
            duplicate_response,
            "already reviewed this rental item",
        )
        self.assertEqual(ProductReview.objects.count(), 1)
        self.assertEqual(
            self.client.post(
                reverse(
                    "customer:review_create",
                    args=[self.active_item.pk],
                ),
                review_data,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "customer:review_create",
                    args=[self.other_completed_item.pk],
                ),
                review_data,
            ).status_code,
            404,
        )

    def test_product_detail_displays_reviews_and_average_rating(self):
        ProductReview.objects.create(
            rental_item=self.completed_item,
            rating=5,
            review_text="A polished rental experience.",
        )
        ProductReview.objects.create(
            rental_item=self.other_completed_item,
            rating=3,
            review_text="Good overall with a comfortable fit.",
        )

        response = self.client.get(
            reverse("customer:product_detail", args=[self.product.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["average_rating"], 4.0)
        self.assertEqual(response.context["review_count"], 2)
        self.assertContains(response, "4.0 / 5")
        self.assertContains(response, "A polished rental experience.")
        self.assertContains(
            response,
            "Good overall with a comfortable fit.",
        )

    def test_order_detail_shows_review_action_and_submitted_state(self):
        self.client.force_login(self.customer)
        order_url = reverse(
            "customer:order_detail",
            args=[self.order.pk],
        )

        response = self.client.get(order_url)

        self.assertContains(response, "Write a review", count=1)
        self.assertContains(
            response,
            reverse(
                "customer:review_create",
                args=[self.completed_item.pk],
            ),
        )

        ProductReview.objects.create(
            rental_item=self.completed_item,
            rating=4,
            review_text="Would rent this again.",
        )
        reviewed_response = self.client.get(order_url)

        self.assertContains(reviewed_response, "Review submitted")
        self.assertNotContains(reviewed_response, "Write a review")
