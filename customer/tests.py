from django.test import TestCase
from django.urls import reverse

from shop.models import Category, Product, ProductVariant, Vendor


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
