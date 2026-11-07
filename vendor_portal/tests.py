from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import VendorEmployee
from accounts.roles import VENDOR_EMPLOYEE_GROUP
from shop.models import (
    Category,
    Product,
    ProductImage,
    ProductVariant,
    RentalItem,
    RentalOrder,
    RentalReturn,
    RentalSettlement,
    ReturnInspection,
    Vendor,
)
from vendor_portal.forms import ProductForm, ProductImageForm, ProductVariantForm


class EmployeeHomeTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.media_settings = override_settings(
            MEDIA_ROOT=self.media_directory.name
        )
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.addCleanup(self.media_directory.cleanup)
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

    def image_file(self, name="product.gif"):
        return SimpleUploadedFile(
            name,
            (
                b"GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
                b"\xff\xff\xff!\xf9\x04\x01\n\x00\x01\x00,\x00\x00"
                b"\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;"
            ),
            content_type="image/gif",
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("vendor_portal:home"))

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

        response = self.client.get(reverse("vendor_portal:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own_product.name)
        self.assertNotContains(response, other_product.name)

    def test_user_without_employee_role_is_forbidden(self):
        self.user.groups.clear()
        self.client.force_login(self.user)

        response = self.client.get(reverse("vendor_portal:home"))

        self.assertEqual(response.status_code, 403)

    def test_employee_product_detail_is_limited_to_their_vendor(self):
        own_product = self.create_product(self.vendor, "Owned product")
        other_product = self.create_product(self.other_vendor, "Other product")
        self.client.force_login(self.user)

        own_response = self.client.get(
            reverse("vendor_portal:product_detail", args=[own_product.pk])
        )
        other_response = self.client.get(
            reverse("vendor_portal:product_detail", args=[other_product.pk])
        )

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(other_response.status_code, 404)

    def test_inventory_shows_product_details_stock_and_status(self):
        product = self.create_product(
            self.vendor,
            "Published product",
            is_active=True,
            is_published=True,
        )
        ProductVariant.objects.create(
            product=product,
            sku="inventory-product-m-green",
            size="M",
            colour="Green",
            total_quantity=4,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("vendor_portal:home"))

        self.assertContains(response, "Category")
        self.assertContains(response, "Price")
        self.assertContains(response, "Stock")
        self.assertContains(response, "4")
        self.assertContains(response, "Active")

    def test_inventory_uses_clear_status_labels(self):
        active_product = self.create_product(
            self.vendor,
            "Active product",
            is_active=True,
            is_published=True,
        )
        archived_product = self.create_product(
            self.vendor,
            "Archived product",
            is_archived=True,
        )
        blocked_product = self.create_product(
            self.vendor,
            "Blocked product",
            moderation_blocked=True,
        )
        draft_product = self.create_product(self.vendor, "Draft product")
        self.client.force_login(self.user)

        response = self.client.get(reverse("vendor_portal:home"))

        self.assertContains(response, active_product.name)
        self.assertContains(response, archived_product.name)
        self.assertContains(response, blocked_product.name)
        self.assertContains(response, draft_product.name)
        self.assertContains(response, "Active")
        self.assertContains(response, "Archived")
        self.assertContains(response, "Blocked")
        self.assertContains(response, "Draft")

        self.vendor.is_suspended = True
        self.vendor.save(update_fields=["is_suspended"])
        suspended_response = self.client.get(reverse("vendor_portal:home"))

        self.assertContains(suspended_response, "Vendor Suspended", count=4)

    def test_employee_can_create_a_product_for_their_own_vendor(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("vendor_portal:product_create"),
            {
                "name": "New vendor product",
                "category": self.category.pk,
                "brand": "Vendor brand",
                "description": "A newly listed product.",
                "daily_rate": "15.00",
                "is_published": "on",
            },
        )

        self.assertRedirects(response, reverse("vendor_portal:home"))
        product = Product.objects.get(name="New vendor product")
        self.assertEqual(product.vendor, self.vendor)
        self.assertTrue(product.is_active)
        self.assertTrue(product.is_published)

    def test_product_form_excludes_vendor_and_moderation_fields(self):
        self.assertEqual(
            set(ProductForm.Meta.fields),
            {
                "name",
                "category",
                "brand",
                "description",
                "daily_rate",
                "is_published",
            },
        )

    def test_employee_can_edit_only_their_own_product(self):
        own_product = self.create_product(self.vendor, "Original name")
        other_product = self.create_product(self.other_vendor, "Other product")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("vendor_portal:product_edit", args=[own_product.pk]),
            {
                "name": "Updated name",
                "category": self.category.pk,
                "brand": own_product.brand,
                "description": own_product.description,
                "daily_rate": "20.00",
            },
        )
        other_response = self.client.get(
            reverse("vendor_portal:product_edit", args=[other_product.pk])
        )

        self.assertRedirects(response, reverse("vendor_portal:home"))
        own_product.refresh_from_db()
        self.assertEqual(own_product.name, "Updated name")
        self.assertEqual(other_response.status_code, 404)

    def test_employee_can_archive_only_their_own_product(self):
        own_product = self.create_product(self.vendor, "Product to archive")
        other_product = self.create_product(self.other_vendor, "Other product")
        self.client.force_login(self.user)

        get_response = self.client.get(
            reverse("vendor_portal:product_archive", args=[own_product.pk])
        )
        response = self.client.post(
            reverse("vendor_portal:product_archive", args=[own_product.pk])
        )
        other_response = self.client.post(
            reverse("vendor_portal:product_archive", args=[other_product.pk])
        )

        self.assertEqual(get_response.status_code, 405)
        self.assertRedirects(response, reverse("vendor_portal:home"))
        own_product.refresh_from_db()
        self.assertTrue(own_product.is_archived)
        self.assertEqual(other_response.status_code, 404)

    def test_employee_can_create_and_edit_only_their_own_variant(self):
        product = self.create_product(self.vendor, "Variant product")
        other_product = self.create_product(self.other_vendor, "Other product")
        other_variant = ProductVariant.objects.create(
            product=other_product,
            sku="other-variant",
            size="M",
            colour="Blue",
            total_quantity=1,
        )
        self.client.force_login(self.user)

        create_response = self.client.post(
            reverse("vendor_portal:variant_create", args=[product.pk]),
            {
                "sku": "variant-product-s-green",
                "size": "S",
                "colour": "Green",
                "colour_hex": "#00AA00",
                "total_quantity": 3,
                "is_active": "on",
            },
        )
        variant = ProductVariant.objects.get(sku="variant-product-s-green")
        edit_response = self.client.post(
            reverse(
                "vendor_portal:variant_edit",
                args=[product.pk, variant.pk],
            ),
            {
                "sku": variant.sku,
                "size": "S",
                "colour": "Green",
                "colour_hex": "#00AA00",
                "total_quantity": 5,
                "is_active": "on",
            },
        )
        other_response = self.client.get(
            reverse(
                "vendor_portal:variant_edit",
                args=[other_product.pk, other_variant.pk],
            )
        )

        self.assertRedirects(
            create_response,
            reverse("vendor_portal:product_detail", args=[product.pk]),
        )
        self.assertEqual(variant.product, product)
        self.assertRedirects(
            edit_response,
            reverse("vendor_portal:product_detail", args=[product.pk]),
        )
        variant.refresh_from_db()
        self.assertEqual(variant.total_quantity, 5)
        self.assertEqual(other_response.status_code, 404)

    def test_employee_can_create_and_edit_only_their_own_product_image(self):
        product = self.create_product(self.vendor, "Image product")
        other_product = self.create_product(self.other_vendor, "Other product")
        other_image = ProductImage.objects.create(
            product=other_product,
            image=self.image_file("other.gif"),
        )
        self.client.force_login(self.user)

        create_response = self.client.post(
            reverse("vendor_portal:image_create", args=[product.pk]),
            {
                "image": self.image_file(),
                "alt_text": "Front view",
                "sort_order": 1,
            },
        )
        product_image = ProductImage.objects.get(product=product)
        edit_response = self.client.post(
            reverse(
                "vendor_portal:image_edit",
                args=[product.pk, product_image.pk],
            ),
            {
                "image": self.image_file("updated.gif"),
                "alt_text": "Updated front view",
                "sort_order": 2,
            },
        )
        other_response = self.client.get(
            reverse(
                "vendor_portal:image_edit",
                args=[other_product.pk, other_image.pk],
            )
        )

        self.assertRedirects(
            create_response,
            reverse("vendor_portal:product_detail", args=[product.pk]),
        )
        self.assertRedirects(
            edit_response,
            reverse("vendor_portal:product_detail", args=[product.pk]),
        )
        product_image.refresh_from_db()
        self.assertEqual(product_image.alt_text, "Updated front view")
        self.assertEqual(product_image.sort_order, 2)
        self.assertEqual(other_response.status_code, 404)

    def test_variant_and_image_forms_do_not_expose_a_product_field(self):
        self.assertNotIn("product", ProductVariantForm.Meta.fields)
        self.assertNotIn("product", ProductImageForm.Meta.fields)


class RentalSettlementWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        employee_group, _ = Group.objects.get_or_create(
            name=VENDOR_EMPLOYEE_GROUP
        )
        User = get_user_model()
        cls.employee_user = User.objects.create_user(
            username="settlement-employee",
            password="test-password",
        )
        cls.employee_user.groups.add(employee_group)
        cls.customer = User.objects.create_user(
            username="settlement-customer",
            password="test-password",
        )
        cls.vendor = Vendor.objects.create(
            name="Settlement Vendor",
            contact_email="settlement@example.com",
        )
        cls.other_vendor = Vendor.objects.create(
            name="Other Settlement Vendor",
            contact_email="other-settlement@example.com",
        )
        cls.employee = VendorEmployee.objects.create(
            user=cls.employee_user,
            vendor=cls.vendor,
        )
        category = Category.objects.create(name="Settlement Clothing")
        product = Product.objects.create(
            vendor=cls.vendor,
            category=category,
            name="Settlement Jacket",
            description="Settlement test product.",
            brand="Test",
            daily_rate=Decimal("10.00"),
        )
        cls.variant = ProductVariant.objects.create(
            product=product,
            sku="settlement-jacket-m",
            size="M",
            colour="Blue",
            total_quantity=2,
        )
        cls.order = RentalOrder.objects.create(
            customer=cls.customer,
            vendor=cls.vendor,
            delivery_address="1 Settlement Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("100.00"),
        )
        cls.item = RentalItem.objects.create(
            order=cls.order,
            variant=cls.variant,
            product_name_snapshot="Settlement Jacket",
            daily_rate_snapshot=Decimal("10.00"),
            commission_rate_snapshot=Decimal("0.2000"),
            quantity=2,
            rental_start_date=date(2026, 11, 1),
            rental_end_date=date(2026, 11, 5),
            rental_days=5,
            line_total=Decimal("100.00"),
            status=RentalItem.Status.RETURNED,
        )
        cls.rental_return = RentalReturn.objects.create(
            rental_item=cls.item,
            returned_on=date(2026, 11, 6),
            recorded_by=cls.employee,
        )
        cls.inspection = ReturnInspection.objects.create(
            rental_return=cls.rental_return,
            condition=ReturnInspection.Condition.READY,
            inspected_by=cls.employee,
        )

        other_product = Product.objects.create(
            vendor=cls.other_vendor,
            category=category,
            name="Other Settlement Jacket",
            description="Another vendor's product.",
            brand="Test",
            daily_rate=Decimal("10.00"),
        )
        other_variant = ProductVariant.objects.create(
            product=other_product,
            sku="other-settlement-jacket-m",
            size="M",
            colour="Black",
            total_quantity=1,
        )
        other_order = RentalOrder.objects.create(
            customer=cls.customer,
            vendor=cls.other_vendor,
            delivery_address="2 Settlement Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("10.00"),
        )
        cls.other_item = RentalItem.objects.create(
            order=other_order,
            variant=other_variant,
            product_name_snapshot="Other Settlement Jacket",
            daily_rate_snapshot=Decimal("10.00"),
            quantity=1,
            rental_start_date=date(2026, 11, 1),
            rental_end_date=date(2026, 11, 1),
            rental_days=1,
            line_total=Decimal("10.00"),
            status=RentalItem.Status.RETURNED,
        )

    def detail_url(self, item=None):
        return reverse(
            "vendor_portal:rental_detail",
            args=[(item or self.item).pk],
        )

    def complete_url(self, item=None):
        return reverse(
            "vendor_portal:rental_complete",
            args=[(item or self.item).pk],
        )

    def test_employee_can_open_own_rental_and_see_completion_action(self):
        self.client.force_login(self.employee_user)

        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Settlement Jacket")
        self.assertContains(response, "Ready for reuse")
        self.assertContains(response, "Complete and record settlement")

    def test_employee_workspace_lists_only_own_vendor_rentals(self):
        self.client.force_login(self.employee_user)

        response = self.client.get(reverse("vendor_portal:home"))

        self.assertContains(response, "Settlement Jacket")
        self.assertNotContains(response, "Other Settlement Jacket")

    def test_completion_creates_exact_20_80_settlement(self):
        self.client.force_login(self.employee_user)

        response = self.client.post(self.complete_url())

        self.assertRedirects(response, self.detail_url())
        self.item.refresh_from_db()
        settlement = RentalSettlement.objects.get(rental_item=self.item)
        self.assertEqual(self.item.status, RentalItem.Status.COMPLETED)
        self.assertEqual(
            settlement.commission_rate_snapshot,
            Decimal("0.2000"),
        )
        self.assertEqual(settlement.platform_amount, Decimal("20.00"))
        self.assertEqual(settlement.vendor_amount, Decimal("80.00"))

    def test_repeated_completion_does_not_duplicate_settlement(self):
        self.client.force_login(self.employee_user)

        self.client.post(self.complete_url())
        self.client.post(self.complete_url())

        self.assertEqual(
            RentalSettlement.objects.filter(rental_item=self.item).count(),
            1,
        )

    def test_settlement_is_displayed_as_read_only_simulation(self):
        self.client.force_login(self.employee_user)
        self.client.post(self.complete_url())

        response = self.client.get(self.detail_url())

        for text in (
            "Simulated settlement",
            "No real funds were transferred",
            "20%",
            "SGD 20.00",
            "80%",
            "SGD 80.00",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, "Complete and record settlement")

    def test_cancelled_item_produces_no_settlement(self):
        self.item.status = RentalItem.Status.CANCELLED
        self.item.save(update_fields=["status"])
        self.client.force_login(self.employee_user)

        response = self.client.post(self.complete_url())

        self.assertRedirects(response, self.detail_url())
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, RentalItem.Status.CANCELLED)
        self.assertFalse(
            RentalSettlement.objects.filter(rental_item=self.item).exists()
        )

    def test_unresolved_inspection_produces_no_settlement(self):
        self.inspection.condition = ReturnInspection.Condition.CLEANING
        self.inspection.save(update_fields=["condition"])
        self.client.force_login(self.employee_user)

        response = self.client.post(self.complete_url())

        self.assertRedirects(response, self.detail_url())
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, RentalItem.Status.RETURNED)
        self.assertFalse(
            RentalSettlement.objects.filter(rental_item=self.item).exists()
        )

    def test_employee_cannot_access_another_vendors_rental(self):
        self.client.force_login(self.employee_user)

        detail_response = self.client.get(self.detail_url(self.other_item))
        complete_response = self.client.post(
            self.complete_url(self.other_item)
        )

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(complete_response.status_code, 404)
        self.assertFalse(
            RentalSettlement.objects.filter(
                rental_item=self.other_item
            ).exists()
        )

    def test_non_employee_cannot_view_or_complete_rental(self):
        self.client.force_login(self.customer)

        detail_response = self.client.get(self.detail_url())
        complete_response = self.client.post(self.complete_url())

        self.assertEqual(detail_response.status_code, 403)
        self.assertEqual(complete_response.status_code, 403)

    def test_completion_endpoint_rejects_get_requests(self):
        self.client.force_login(self.employee_user)

        response = self.client.get(self.complete_url())

        self.assertEqual(response.status_code, 405)

    def test_anonymous_user_is_redirected_from_rental_pages(self):
        for url, method in (
            (self.detail_url(), self.client.get),
            (self.complete_url(), self.client.post),
        ):
            with self.subTest(url=url):
                response = method(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response.url)
