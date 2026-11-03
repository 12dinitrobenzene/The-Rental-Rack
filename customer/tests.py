from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

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

        ProductVariant.objects.create(
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
