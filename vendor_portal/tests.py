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
    StyleTag,
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

    def create_variant(self, product, sku, total_quantity=1):
        return ProductVariant.objects.create(
            product=product,
            sku=sku,
            size="M",
            colour="Blue",
            total_quantity=total_quantity,
        )

    def create_order(
        self,
        vendor=None,
        payment_status=RentalOrder.PaymentStatus.PAID,
    ):
        return RentalOrder.objects.create(
            customer=self.user,
            vendor=vendor or self.vendor,
            delivery_address="1 Test Street",
            payment_status=payment_status,
            total_amount=Decimal("100.00"),
        )

    def create_rental_item(
        self,
        order,
        variant,
        status,
        name="Test rental item",
    ):
        return RentalItem.objects.create(
            order=order,
            variant=variant,
            product_name_snapshot=name,
            daily_rate_snapshot=Decimal("10.00"),
            quantity=1,
            rental_start_date=date(2026, 11, 1),
            rental_end_date=date(2026, 11, 1),
            rental_days=1,
            line_total=Decimal("10.00"),
            status=status,
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

    def test_workspace_uses_the_rental_order_queue(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("vendor_portal:home"))

        self.assertContains(
            response,
            reverse("vendor_portal:rental_order_list"),
        )
        self.assertContains(response, "Rental orders")
        self.assertNotContains(response, "Rental fulfilment")

    def test_analytics_page_renders_for_vendor_employee(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("vendor_portal:analytics"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "vendor_portal/analytics.html",
        )
        self.assertContains(response, "Performance summary")
        self.assertContains(response, "Popular products")
        self.assertContains(response, "Popular categories")
        self.assertContains(response, "Popular sizes")

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

    def test_workspace_metrics_are_scoped_to_paid_vendor_rentals(self):
        self.vendor.approval_status = Vendor.ApprovalStatus.APPROVED
        self.vendor.save(update_fields=["approval_status"])
        product = self.create_product(
            self.vendor,
            "Visible metrics product",
            is_active=True,
            is_published=True,
        )
        variant = ProductVariant.objects.create(
            product=product,
            sku="metrics-product-m",
            size="M",
            colour="Blue",
            total_quantity=4,
        )
        paid_order = RentalOrder.objects.create(
            customer=self.user,
            vendor=self.vendor,
            delivery_address="1 Metrics Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("30.00"),
        )

        for index, status in enumerate(
            (
                RentalItem.Status.CONFIRMED,
                RentalItem.Status.OVERDUE,
                RentalItem.Status.RETURNED,
            )
        ):
            RentalItem.objects.create(
                order=paid_order,
                variant=variant,
                product_name_snapshot=f"Metrics item {index}",
                daily_rate_snapshot=Decimal("10.00"),
                quantity=1,
                rental_start_date=date(2026, 11, 1),
                rental_end_date=date(2026, 11, 2),
                rental_days=2,
                line_total=Decimal("10.00"),
                status=status,
            )

        unpaid_order = RentalOrder.objects.create(
            customer=self.user,
            vendor=self.vendor,
            delivery_address="1 Unpaid Street",
            payment_status=RentalOrder.PaymentStatus.PENDING,
            total_amount=Decimal("10.00"),
        )
        RentalItem.objects.create(
            order=unpaid_order,
            variant=variant,
            product_name_snapshot="Unpaid metrics item",
            daily_rate_snapshot=Decimal("10.00"),
            quantity=1,
            rental_start_date=date(2026, 11, 1),
            rental_end_date=date(2026, 11, 2),
            rental_days=2,
            line_total=Decimal("10.00"),
            status=RentalItem.Status.OVERDUE,
        )

        other_product = self.create_product(
            self.other_vendor,
            "Other vendor metrics product",
        )
        other_variant = ProductVariant.objects.create(
            product=other_product,
            sku="other-metrics-product-m",
            size="M",
            colour="Black",
            total_quantity=1,
        )
        other_order = RentalOrder.objects.create(
            customer=self.user,
            vendor=self.other_vendor,
            delivery_address="2 Metrics Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("10.00"),
        )
        RentalItem.objects.create(
            order=other_order,
            variant=other_variant,
            product_name_snapshot="Other vendor metrics item",
            daily_rate_snapshot=Decimal("10.00"),
            quantity=1,
            rental_start_date=date(2026, 11, 1),
            rental_end_date=date(2026, 11, 2),
            rental_days=2,
            line_total=Decimal("10.00"),
            status=RentalItem.Status.OVERDUE,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("vendor_portal:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["rental_metrics"],
            {
                "active_rentals": 3,
                "awaiting_fulfilment": 1,
                "overdue_rentals": 1,
                "awaiting_completion": 1,
            },
        )
        self.assertEqual(response.context["active_listings"], 1)
        self.assertEqual(response.context["total_physical_stock"], 4)
        self.assertEqual(response.context["active_rentals"], 3)
        self.assertEqual(response.context["awaiting_fulfilment"], 1)
        self.assertEqual(response.context["overdue_rentals"], 1)
        self.assertEqual(response.context["awaiting_completion"], 1)
        for label in (
            "Operational summary",
            "Active rentals",
            "Awaiting fulfilment",
            "Overdue rentals",
            "Awaiting completion",
            "Active listings",
            "Physical stock",
        ):
            self.assertContains(response, label)

    def test_each_status_appears_in_the_correct_metric(self):
        product = self.create_product(
            self.vendor,
            "Status metrics product",
        )
        variant = self.create_variant(
            product,
            "status-metrics-variant",
        )
        order = self.create_order()

        statuses = [
            RentalItem.Status.CONFIRMED,
            RentalItem.Status.PREPARING,
            RentalItem.Status.DISPATCHED,
            RentalItem.Status.ACTIVE,
            RentalItem.Status.OVERDUE,
            RentalItem.Status.RETURNED,
            RentalItem.Status.COMPLETED,
            RentalItem.Status.CANCELLED,
        ]

        for status in statuses:
            self.create_rental_item(
                order,
                variant,
                status,
                name=f"{status} item",
            )

        self.client.force_login(self.user)
        response = self.client.get(reverse("vendor_portal:home"))
        metrics = response.context["rental_metrics"]

        self.assertEqual(metrics["active_rentals"], 6)
        self.assertEqual(metrics["awaiting_fulfilment"], 2)
        self.assertEqual(metrics["overdue_rentals"], 1)
        self.assertEqual(metrics["awaiting_completion"], 1)

    def test_returned_item_with_settlement_is_not_awaiting_completion(self):
        product = self.create_product(
            self.vendor,
            "Settlement metrics product",
        )
        variant = self.create_variant(
            product,
            "settlement-metrics-variant",
        )
        order = self.create_order()

        unsettled_item = self.create_rental_item(
            order,
            variant,
            RentalItem.Status.RETURNED,
            name="Unsettled returned item",
        )
        settled_item = self.create_rental_item(
            order,
            variant,
            RentalItem.Status.RETURNED,
            name="Settled returned item",
        )

        RentalSettlement.objects.create(
            rental_item=settled_item,
            commission_rate_snapshot=Decimal("0.2000"),
            platform_amount=Decimal("2.00"),
            vendor_amount=Decimal("8.00"),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("vendor_portal:home"))

        self.assertEqual(response.context["awaiting_completion"], 1)
        self.assertFalse(hasattr(unsettled_item, "settlement"))

    def test_suspended_vendor_has_zero_active_listings(self):
        self.vendor.approval_status = Vendor.ApprovalStatus.APPROVED
        self.vendor.save(update_fields=["approval_status"])

        product = self.create_product(
            self.vendor,
            "Visible product",
            is_active=True,
            is_published=True,
        )
        self.create_variant(product, "visible-product-variant")

        self.client.force_login(self.user)

        active_response = self.client.get(
            reverse("vendor_portal:home")
        )
        self.assertEqual(active_response.context["active_listings"], 1)

        self.vendor.is_suspended = True
        self.vendor.save(update_fields=["is_suspended"])

        suspended_response = self.client.get(
            reverse("vendor_portal:home")
        )
        self.assertEqual(suspended_response.context["active_listings"], 0)

    def test_vendor_without_variants_has_zero_physical_stock(self):
        self.create_product(
            self.vendor,
            "Product without variants",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("vendor_portal:home"))

        self.assertEqual(response.context["total_physical_stock"], 0)

    def test_physical_stock_sums_all_vendor_variants(self):
        product = self.create_product(
            self.vendor,
            "Multi-variant product",
        )
        self.create_variant(
            product,
            "multi-variant-small",
            total_quantity=2,
        )
        ProductVariant.objects.create(
            product=product,
            sku="multi-variant-medium",
            size="L",
            colour="Blue",
            total_quantity=5,
        )

        other_product = self.create_product(
            self.other_vendor,
            "Other vendor stock",
        )
        self.create_variant(
            other_product,
            "other-vendor-variant",
            total_quantity=100,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("vendor_portal:home"))

        self.assertEqual(
            response.context["total_physical_stock"],
            7,
        )

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
                "style_tags",
            },
        )

    def test_employee_product_form_assigns_style_tags(self):
        style_tag = StyleTag.objects.get(slug="minimalist_clean")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("vendor_portal:product_create"),
            {
                "name": "Tagged product",
                "category": self.category.pk,
                "brand": "Vendor brand",
                "description": "A style-tagged product.",
                "daily_rate": "15.00",
                "style_tags": [style_tag.pk],
            },
        )

        self.assertRedirects(response, reverse("vendor_portal:home"))
        product = Product.objects.get(name="Tagged product")
        self.assertEqual(list(product.style_tags.all()), [style_tag])

    def test_shared_style_tags_are_seeded(self):
        self.assertEqual(
            set(StyleTag.objects.values_list("slug", flat=True)),
            {
                "minimalist_clean",
                "classic_polished",
                "urban_streetwear",
                "romantic_expressive",
                "avant_garde_statement",
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


class VendorAnalyticsTests(TestCase):
    def setUp(self):
        employee_group, _ = Group.objects.get_or_create(
            name=VENDOR_EMPLOYEE_GROUP
        )
        self.user = get_user_model().objects.create_user(
            username="analytics-employee",
            password="test-pass-123",
        )
        self.user.groups.add(employee_group)
        self.customer = get_user_model().objects.create_user(
            username="analytics-customer",
            password="test-pass-123",
        )
        self.vendor = Vendor.objects.create(
            name="Analytics Vendor",
            contact_email="analytics@example.com",
        )
        self.other_vendor = Vendor.objects.create(
            name="Other Analytics Vendor",
            contact_email="other-analytics@example.com",
        )
        VendorEmployee.objects.create(
            user=self.user,
            vendor=self.vendor,
        )
        self.category = Category.objects.create(name="Analytics Category")
        self.client.force_login(self.user)

    def create_product(self, vendor, name, category=None):
        return Product.objects.create(
            vendor=vendor,
            category=category or self.category,
            name=name,
            description="Analytics test product",
            brand="Test brand",
            daily_rate=Decimal("10.00"),
        )

    def create_variant(self, product, sku, size="M"):
        return ProductVariant.objects.create(
            product=product,
            sku=sku,
            size=size,
            colour="Blue",
            total_quantity=10,
        )

    def create_completed_item(
        self,
        vendor,
        variant,
        *,
        quantity=1,
        name="Analytics rental item",
    ):
        order = RentalOrder.objects.create(
            customer=self.customer,
            vendor=vendor,
            delivery_address="1 Analytics Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("100.00"),
        )
        return RentalItem.objects.create(
            order=order,
            variant=variant,
            product_name_snapshot=name,
            daily_rate_snapshot=Decimal("10.00"),
            quantity=quantity,
            rental_start_date=date(2026, 11, 1),
            rental_end_date=date(2026, 11, 1),
            rental_days=1,
            line_total=Decimal("10.00"),
            status=RentalItem.Status.COMPLETED,
        )

    def test_other_vendor_completed_items_and_settlements_are_excluded(self):
        own_product = self.create_product(self.vendor, "Own analytics product")
        own_variant = self.create_variant(
            own_product,
            "own-analytics-variant",
        )
        own_item = self.create_completed_item(self.vendor, own_variant)
        RentalSettlement.objects.create(
            rental_item=own_item,
            commission_rate_snapshot=Decimal("0.2000"),
            platform_amount=Decimal("2.00"),
            vendor_amount=Decimal("8.00"),
        )

        other_product = self.create_product(
            self.other_vendor,
            "Other vendor analytics product",
        )
        other_variant = self.create_variant(
            other_product,
            "other-analytics-variant",
        )
        other_item = self.create_completed_item(
            self.other_vendor,
            other_variant,
            quantity=9,
        )
        RentalSettlement.objects.create(
            rental_item=other_item,
            commission_rate_snapshot=Decimal("0.2000"),
            platform_amount=Decimal("90.00"),
            vendor_amount=Decimal("10.00"),
        )

        response = self.client.get(reverse("vendor_portal:analytics"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["completed_rental_quantity"], 1)
        self.assertEqual(
            list(response.context["popular_products"].values_list(
                "product_name",
                flat=True,
            )),
            ["Own analytics product"],
        )
        self.assertEqual(
            response.context["platform_commission"],
            Decimal("2.00"),
        )
        self.assertEqual(
            response.context["vendor_payout"],
            Decimal("8.00"),
        )
        self.assertEqual(
            response.context["settled_gross_value"],
            response.context["platform_commission"]
            + response.context["vendor_payout"],
        )

    def test_rankings_use_total_quantity_instead_of_row_count(self):
        lower_category = Category.objects.create(
            name="Lower volume category",
        )
        higher_category = Category.objects.create(
            name="Higher volume category",
        )
        lower_product = self.create_product(
            self.vendor,
            "Lower quantity product",
            lower_category,
        )
        lower_variant = self.create_variant(
            lower_product,
            "lower-quantity-variant",
            size="M",
        )
        self.create_completed_item(
            self.vendor,
            lower_variant,
            name="First lower quantity item",
        )
        self.create_completed_item(
            self.vendor,
            lower_variant,
            name="Second lower quantity item",
        )

        higher_product = self.create_product(
            self.vendor,
            "Higher quantity product",
            higher_category,
        )
        higher_variant = self.create_variant(
            higher_product,
            "higher-quantity-variant",
            size="L",
        )
        self.create_completed_item(
            self.vendor,
            higher_variant,
            quantity=5,
            name="Higher quantity item",
        )

        response = self.client.get(reverse("vendor_portal:analytics"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["popular_products"].values_list(
                "product_name",
                "rental_quantity",
            )),
            [
                ("Higher quantity product", 5),
                ("Lower quantity product", 2),
            ],
        )
        self.assertEqual(
            list(response.context["popular_categories"].values_list(
                "category_name",
                "rental_quantity",
            )),
            [
                ("Higher volume category", 5),
                ("Lower volume category", 2),
            ],
        )
        self.assertEqual(
            list(response.context["popular_sizes"].values_list(
                "size",
                "rental_quantity",
            )),
            [("L", 5), ("M", 2)],
        )

    def test_end_date_before_start_date_displays_validation_error(self):
        response = self.client.get(
            reverse("vendor_portal:analytics"),
            {
                "start_date": "2026-11-02",
                "end_date": "2026-11-01",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertContains(
            response,
            "The end date must be on or after the start date.",
        )


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

    def inspection_url(self, item=None):
        return reverse(
            "vendor_portal:return_inspection",
            args=[(item or self.item).pk],
        )

    def test_employee_can_open_own_rental_and_see_completion_action(self):
        self.client.force_login(self.employee_user)

        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Settlement Jacket")
        self.assertContains(response, "Ready for reuse")
        self.assertContains(response, "Complete and record settlement")
        self.assertContains(
            response,
            reverse(
                "vendor_portal:order_detail",
                args=[self.order.pk],
            ),
        )

    def test_completion_creates_exact_20_80_settlement(self):
        self.client.force_login(self.employee_user)

        response = self.client.post(self.complete_url())

        self.assertRedirects(response, self.detail_url())
        self.item.refresh_from_db()
        self.variant.refresh_from_db()
        settlement = RentalSettlement.objects.get(rental_item=self.item)
        self.assertEqual(self.item.status, RentalItem.Status.COMPLETED)
        self.assertEqual(self.variant.total_quantity, 2)
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

    def order_list_url(self):
        return reverse("vendor_portal:rental_order_list")

    def order_detail_url(self, order_id):
        return reverse(
            "vendor_portal:order_detail",
            args=[order_id],
        )

    def test_order_pages_are_isolated_for_both_vendors(self):
        other_employee_user = get_user_model().objects.create_user(
            username="other-queue-employee",
        )
        other_employee_user.groups.add(
            Group.objects.get(name=VENDOR_EMPLOYEE_GROUP)
        )
        VendorEmployee.objects.create(
            user=other_employee_user,
            vendor=self.other_vendor,
        )

        cases = [
            (
                self.employee_user,
                self.order.pk,
                self.other_item.order_id,
            ),
            (
                other_employee_user,
                self.other_item.order_id,
                self.order.pk,
            ),
        ]

        for user, own_order_id, foreign_order_id in cases:
            with self.subTest(user=user.username):
                self.client.force_login(user)

                for params in ({}, {"status": "Returned"}):
                    response = self.client.get(
                        self.order_list_url(), params
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        [order.pk for order in response.context["orders"]],
                        [own_order_id],
                    )

                response = self.client.get(
                    self.order_detail_url(own_order_id)
                )
                self.assertEqual(response.status_code, 200)

                response = self.client.get(
                    self.order_detail_url(foreign_order_id)
                )
                self.assertEqual(response.status_code, 404)

    def test_customer_cannot_access_order_pages(self):
        customer_group, _ = Group.objects.get_or_create(name="Customer")
        self.customer.groups.add(customer_group)
        self.client.force_login(self.customer)

        for url in (
            self.order_list_url(),
            self.order_detail_url(self.order.pk),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_from_order_pages(self):
        for url in (
            self.order_list_url(),
            self.order_detail_url(self.order.pk),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={url}",
                    fetch_redirect_response=False,
                )

    def test_order_filters(self):
        self.client.force_login(self.employee_user)

        cases = [
            ({}, True),
            ({"status": "Returned"}, True),
            ({"status": "Preparing"}, False),
            ({"date_from": "2026-11-05"}, True),
            ({"date_from": "2026-11-06"}, False),
            ({"date_to": "2026-11-01"}, True),
            ({"date_to": "2026-10-31"}, False),
            (
                {
                    "status": "Returned",
                    "date_from": "2026-11-03",
                    "date_to": "2026-11-04",
                },
                True,
            ),
        ]

        for params, should_match in cases:
            with self.subTest(params=params):
                response = self.client.get(
                    self.order_list_url(), params
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [order.pk for order in response.context["orders"]],
                    [self.order.pk] if should_match else [],
                )

    def test_invalid_order_filters_show_errors(self):
        self.client.force_login(self.employee_user)

        cases = [
            ({"status": "Unknown"}, "status"),
            ({"date_from": "not-a-date"}, "date_from"),
            (
                {
                    "date_from": "2026-11-05",
                    "date_to": "2026-11-01",
                },
                "date_to",
            ),
        ]

        for params, error_field in cases:
            with self.subTest(params=params):
                response = self.client.get(
                    self.order_list_url(), params
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    error_field,
                    response.context["filter_form"].errors,
                )
                self.assertEqual(
                    list(response.context["orders"]), []
                )

    def add_queue_item(self, *, status, rental_date):
        item = RentalItem.objects.create(
            order=self.order,
            variant=self.variant,
            product_name_snapshot="Extra queue item",
            daily_rate_snapshot=Decimal("10.00"),
            quantity=1,
            rental_start_date=rental_date,
            rental_end_date=rental_date,
            rental_days=1,
            line_total=Decimal("10.00"),
            status=status,
        )
        self.order.total_amount += item.line_total
        self.order.save(update_fields=["total_amount"])
        return item

    def test_multiple_matching_items_do_not_duplicate_order(self):
        self.add_queue_item(
            status=RentalItem.Status.RETURNED,
            rental_date=date(2026, 11, 3),
        )
        self.client.force_login(self.employee_user)

        response = self.client.get(
            self.order_list_url(),
            {
                "status": "Returned",
                "date_from": "2026-11-03",
                "date_to": "2026-11-03",
            },
        )

        self.assertEqual(
            [order.pk for order in response.context["orders"]],
            [self.order.pk],
        )

    def test_status_and_dates_must_match_the_same_item(self):
        self.add_queue_item(
            status=RentalItem.Status.PREPARING,
            rental_date=date(2026, 11, 10),
        )
        self.client.force_login(self.employee_user)

        response = self.client.get(
            self.order_list_url(),
            {
                "status": "Returned",
                "date_from": "2026-11-10",
                "date_to": "2026-11-10",
            },
        )

        self.assertEqual(list(response.context["orders"]), [])

    def test_inspection_updates_existing_inspection(self):
        self.inspection.condition = ReturnInspection.Condition.CLEANING
        self.inspection.save(update_fields=["condition"])
        self.client.force_login(self.employee_user)

        get_response = self.client.get(self.inspection_url())
        self.assertEqual(get_response.status_code, 200)

        response = self.client.post(
            self.inspection_url(),
            {
                "condition": ReturnInspection.Condition.READY,
                "notes": "Cleaned and ready for reuse.",
            },
        )

        self.assertRedirects(response, self.detail_url())
        self.inspection.refresh_from_db()
        self.assertEqual(
            self.inspection.condition,
            ReturnInspection.Condition.READY,
        )
        self.assertEqual(self.inspection.notes, "Cleaned and ready for reuse.")
        self.assertEqual(self.inspection.inspected_by, self.employee)
        self.assertEqual(
            ReturnInspection.objects.filter(
                rental_return=self.rental_return
            ).count(),
            1,
        )

    def test_written_off_item_deducts_stock_once_on_completion(self):
        self.inspection.condition = ReturnInspection.Condition.WRITTEN_OFF
        self.inspection.save(update_fields=["condition"])
        self.client.force_login(self.employee_user)

        response = self.client.post(self.complete_url())

        self.assertRedirects(response, self.detail_url())
        self.item.refresh_from_db()
        self.variant.refresh_from_db()
        self.inspection.refresh_from_db()
        self.assertEqual(self.item.status, RentalItem.Status.COMPLETED)
        self.assertEqual(self.variant.total_quantity, 0)
        self.assertIsNotNone(self.inspection.write_off_applied_at)
        self.assertTrue(
            RentalSettlement.objects.filter(rental_item=self.item).exists()
        )

        self.client.post(self.complete_url())
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.total_quantity, 0)

    def test_insufficient_stock_rolls_back_writeoff_completion(self):
        self.inspection.condition = ReturnInspection.Condition.WRITTEN_OFF
        self.inspection.save(update_fields=["condition"])
        self.variant.total_quantity = 1
        self.variant.save(update_fields=["total_quantity"])
        self.client.force_login(self.employee_user)

        self.client.post(self.complete_url())

        self.item.refresh_from_db()
        self.variant.refresh_from_db()
        self.inspection.refresh_from_db()
        self.assertEqual(self.item.status, RentalItem.Status.RETURNED)
        self.assertEqual(self.variant.total_quantity, 1)
        self.assertIsNone(self.inspection.write_off_applied_at)
        self.assertFalse(
            RentalSettlement.objects.filter(rental_item=self.item).exists()
        )

    def test_unpaid_order_cannot_be_completed_or_inspected(self):
        self.order.payment_status = RentalOrder.PaymentStatus.PENDING
        self.order.save(update_fields=["payment_status"])
        self.client.force_login(self.employee_user)

        completion_response = self.client.post(self.complete_url())
        inspection_response = self.client.get(self.inspection_url())

        self.assertRedirects(completion_response, self.detail_url())
        self.assertRedirects(inspection_response, self.detail_url())
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, RentalItem.Status.RETURNED)
        self.assertFalse(
            RentalSettlement.objects.filter(rental_item=self.item).exists()
        )
