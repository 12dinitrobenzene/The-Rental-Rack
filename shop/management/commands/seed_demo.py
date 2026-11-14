import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import CustomerProfile, VendorEmployee
from accounts.roles import (
    CUSTOMER_GROUP,
    PLATFORM_ADMIN_GROUP,
    VENDOR_EMPLOYEE_GROUP,
)
from customer.models import CustomerProductInteraction, WishlistItem
from shop.models import (
    Category,
    CustomerStyleProfile,
    Product,
    ProductImage,
    ProductReview,
    ProductVariant,
    RentalItem,
    RentalOrder,
    RentalReturn,
    RentalSettlement,
    ReturnInspection,
    StyleTag,
    Vendor,
)
from shop.rental_rules import calculate_rental_totals


DEMO_PASSWORD = "Password"


class Command(BaseCommand):
    help = "Load the Nike catalogue and a repeatable set of demonstration data."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "This command creates demo logins and requires DEBUG=True."
            )

        self.seed_root = Path(settings.BASE_DIR) / "shop" / "seed_data"
        self.data = json.loads(
            (self.seed_root / "nike_catalogue.json").read_text()
        )
        self._validate_assets()

        with transaction.atomic():
            vendor = self._seed_vendor()
            users = self._seed_accounts(vendor)
            self._reset_demo_activity(users)
            products = self._seed_catalogue(vendor)
            self._seed_customer_data(users, products)
            workflow_counts = self._seed_rental_workflows(
                users,
                vendor,
                products,
            )

        product_count = len(self.data["products"])
        variant_count = sum(
            len(record["variants"])
            for record in self.data["products"]
        )
        image_count = sum(
            1
            for record in self.data["products"]
            for picture in record["images"]
            if picture["asset"]
        )
        self.stdout.write(self.style.SUCCESS(
            "Demo data is ready: "
            f"{product_count} products, {variant_count} variants, "
            f"{image_count} images, {workflow_counts['orders']} orders and "
            f"{workflow_counts['settlements']} settlements."
        ))
        self.stdout.write(
            "Accounts: platform_admin, platform_employee, nike_employee, "
            "demo_customer, demo_customer_2"
        )
        self.stdout.write(f"Password for every demo account: {DEMO_PASSWORD}")

    def _validate_assets(self):
        for product in self.data["products"]:
            for picture in product["images"]:
                asset = picture["asset"]
                if asset and not (self.seed_root / asset).is_file():
                    raise CommandError(f"Missing bundled image: {asset}")

    def _seed_vendor(self):
        vendor_data = dict(self.data["vendor"])
        vendor = (
            Vendor.objects
            .filter(name__iexact=vendor_data["name"])
            .order_by("pk")
            .first()
        )

        if vendor is None:
            return Vendor.objects.create(**vendor_data)

        for field, value in vendor_data.items():
            setattr(vendor, field, value)
        vendor.save(update_fields=list(vendor_data))
        return vendor

    def _seed_accounts(self, vendor):
        User = get_user_model()
        account_specs = {
            "platform_admin": {
                "first_name": "Master",
                "last_name": "Administrator",
                "email": "platform.admin@example.com",
                "is_staff": True,
                "is_superuser": True,
                "group": None,
            },
            "platform_employee": {
                "first_name": "Platform",
                "last_name": "Employee",
                "email": "platform.employee@example.com",
                "is_staff": False,
                "is_superuser": False,
                "group": PLATFORM_ADMIN_GROUP,
            },
            "nike_employee": {
                "first_name": "Nike",
                "last_name": "Manager",
                "email": "nike.manager@example.com",
                "is_staff": False,
                "is_superuser": False,
                "group": VENDOR_EMPLOYEE_GROUP,
            },
            "demo_customer": {
                "first_name": "Jamie",
                "last_name": "Tan",
                "email": "jamie.customer@example.com",
                "is_staff": False,
                "is_superuser": False,
                "group": CUSTOMER_GROUP,
            },
            "demo_customer_2": {
                "first_name": "Avery",
                "last_name": "Lim",
                "email": "avery.customer@example.com",
                "is_staff": False,
                "is_superuser": False,
                "group": CUSTOMER_GROUP,
            },
        }
        users = {}

        for username, spec in account_specs.items():
            group_name = spec.pop("group")
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    **spec,
                    "is_active": True,
                },
            )
            user.set_password(DEMO_PASSWORD)
            user.save()

            if group_name:
                group, _ = Group.objects.get_or_create(name=group_name)
                user.groups.set([group])
            else:
                user.groups.clear()
            users[username] = user

        non_customers = [
            users["platform_admin"],
            users["platform_employee"],
            users["nike_employee"],
        ]
        customers = [users["demo_customer"], users["demo_customer_2"]]
        CustomerProfile.objects.filter(user__in=non_customers).delete()
        VendorEmployee.objects.filter(
            user__in=[*non_customers[:2], *customers]
        ).delete()

        CustomerProfile.objects.update_or_create(
            user=users["demo_customer"],
            defaults={
                "phone_number": "91234567",
                "delivery_address": "1 Orchard Road, Singapore 238823",
            },
        )
        CustomerProfile.objects.update_or_create(
            user=users["demo_customer_2"],
            defaults={
                "phone_number": "92345678",
                "delivery_address": "10 Bayfront Avenue, Singapore 018956",
            },
        )
        VendorEmployee.objects.update_or_create(
            user=users["nike_employee"],
            defaults={
                "vendor": vendor,
                "is_vendor_admin": True,
            },
        )
        return users

    def _reset_demo_activity(self, users):
        customers = [users["demo_customer"], users["demo_customer_2"]]
        RentalOrder.objects.filter(customer__in=customers).delete()
        WishlistItem.objects.filter(customer__in=customers).delete()
        CustomerProductInteraction.objects.filter(
            customer__in=customers
        ).delete()
        CustomerStyleProfile.objects.filter(customer__in=customers).delete()

    def _seed_catalogue(self, vendor):
        products = {}

        for record in self.data["products"]:
            category, _ = Category.objects.get_or_create(
                name=record["category"]
            )
            fields = dict(record["fields"])
            name = fields.pop("name")
            fields["brand"] = vendor.name.title()
            fields["daily_rate"] = Decimal(fields["daily_rate"])
            product, _ = Product.objects.update_or_create(
                vendor=vendor,
                name=name,
                defaults={
                    **fields,
                    "category": category,
                },
            )
            products[name] = product

            tags = []
            for tag_data in record["style_tags"]:
                tag, _ = StyleTag.objects.update_or_create(
                    slug=tag_data["slug"],
                    defaults={
                        "display_name": tag_data["display_name"],
                    },
                )
                tags.append(tag)
            product.style_tags.set(tags)

            for variant_data in record["variants"]:
                variant_fields = dict(variant_data)
                size = variant_fields.pop("size")
                colour = variant_fields.pop("colour")
                ProductVariant.objects.update_or_create(
                    product=product,
                    size=size,
                    colour=colour,
                    defaults=variant_fields,
                )

            for picture in record["images"]:
                self._seed_product_image(product, picture)

        return products

    def _seed_product_image(self, product, picture):
        if not picture["asset"]:
            return

        target = f"seed/nike/{Path(picture['asset']).name}"
        storage = ProductImage._meta.get_field("image").storage

        if not storage.exists(target):
            with (self.seed_root / picture["asset"]).open("rb") as stream:
                target = storage.save(target, File(stream))

        ProductImage.objects.update_or_create(
            product=product,
            image=target,
            defaults={
                "alt_text": picture["alt_text"],
                "sort_order": picture["sort_order"],
            },
        )

    def _seed_customer_data(self, users, products):
        customer_one = users["demo_customer"]
        customer_two = users["demo_customer_2"]
        urban = StyleTag.objects.get(slug="urban_streetwear")
        minimalist = StyleTag.objects.get(slug="minimalist_clean")

        CustomerStyleProfile.objects.create(
            customer=customer_one,
            silhouette="oversized_relaxed",
            details="graphic_details",
            impression="cool_urban",
            styling_approach="layered_casual",
            statement_level="medium",
            palette="dark",
            predicted_style=urban,
            model_version="demo-seed",
        )
        CustomerStyleProfile.objects.create(
            customer=customer_two,
            silhouette="clean_fitted",
            details="minimal_details",
            impression="understated",
            styling_approach="simple_coordinated",
            statement_level="low",
            palette="neutral",
            predicted_style=minimalist,
            model_version="demo-seed",
        )

        interactions = (
            (customer_one, "nike urban streetwear", 6),
            (customer_one, "baggy jeans combo", 3),
            (customer_two, "nike minimalist clean", 5),
            (customer_two, "nike classic style", 2),
        )
        for customer, product_name, view_count in interactions:
            CustomerProductInteraction.objects.create(
                customer=customer,
                product=products[product_name],
                view_count=view_count,
            )

        for customer, product_names in (
            (
                customer_one,
                ("nike urban streetwear", "relaxed nike combo"),
            ),
            (
                customer_two,
                ("nike minimalist clean", "nike classic style"),
            ),
        ):
            WishlistItem.objects.bulk_create([
                WishlistItem(
                    customer=customer,
                    product=products[product_name],
                )
                for product_name in product_names
            ])

    def _seed_rental_workflows(self, users, vendor, products):
        customer_one = users["demo_customer"]
        customer_two = users["demo_customer_2"]
        manager = VendorEmployee.objects.get(user=users["nike_employee"])
        examples = (
            {
                "customer": customer_one,
                "product": "nike urban streetwear",
                "status": RentalItem.Status.CONFIRMED,
                "start": 3,
                "end": 4,
            },
            {
                "customer": customer_two,
                "product": "nike minimalist clean",
                "status": RentalItem.Status.PREPARING,
                "start": 2,
                "end": 3,
            },
            {
                "customer": customer_one,
                "product": "retro nike outfit",
                "status": RentalItem.Status.DISPATCHED,
                "start": 1,
                "end": 2,
            },
            {
                "customer": customer_two,
                "product": "relaxed nike combo",
                "status": RentalItem.Status.ACTIVE,
                "start": -1,
                "end": 1,
            },
            {
                "customer": customer_one,
                "product": "baggy jeans combo",
                "status": RentalItem.Status.OVERDUE,
                "start": -5,
                "end": -1,
            },
            {
                "customer": customer_two,
                "product": "nike experimental style",
                "status": RentalItem.Status.RETURNED,
                "start": -7,
                "end": -5,
                "inspection": ReturnInspection.Condition.READY,
            },
            {
                "customer": customer_one,
                "product": "nike classic style",
                "status": RentalItem.Status.RETURNED,
                "start": -6,
                "end": -3,
                "inspection": ReturnInspection.Condition.CLEANING,
            },
            {
                "customer": customer_one,
                "product": "nike formal dress down",
                "status": RentalItem.Status.COMPLETED,
                "start": -12,
                "end": -10,
                "inspection": ReturnInspection.Condition.READY,
                "review": True,
            },
            {
                "customer": customer_two,
                "product": "nike windrunner men pants",
                "status": RentalItem.Status.COMPLETED,
                "start": -15,
                "end": -13,
                "inspection": ReturnInspection.Condition.WRITTEN_OFF,
            },
            {
                "customer": customer_two,
                "product": "air jordan",
                "status": RentalItem.Status.CANCELLED,
                "start": 5,
                "end": 6,
            },
        )
        settlement_count = 0

        for index, example in enumerate(examples, start=1):
            item = self._create_rental_example(
                index=index,
                vendor=vendor,
                manager=manager,
                products=products,
                **example,
            )
            if hasattr(item, "settlement"):
                settlement_count += 1

        return {
            "orders": len(examples),
            "settlements": settlement_count,
        }

    def _create_rental_example(
        self,
        *,
        index,
        customer,
        vendor,
        manager,
        products,
        product,
        status,
        start,
        end,
        inspection=None,
        review=False,
    ):
        today = timezone.localdate()
        product_record = products[product]
        variant = product_record.variants.order_by("pk").first()
        start_date = today + timedelta(days=start)
        end_date = today + timedelta(days=end)
        rental_days, line_total = calculate_rental_totals(
            daily_rate=product_record.daily_rate,
            quantity=1,
            start_date=start_date,
            end_date=end_date,
        )
        payment_status = (
            RentalOrder.PaymentStatus.REFUNDED
            if status == RentalItem.Status.CANCELLED
            else RentalOrder.PaymentStatus.PAID
        )
        order = RentalOrder.objects.create(
            customer=customer,
            vendor=vendor,
            delivery_address=customer.customer_profile.delivery_address,
            payment_status=payment_status,
            total_amount=line_total,
        )
        initial_status = (
            RentalItem.Status.RETURNED
            if status == RentalItem.Status.COMPLETED
            else status
        )
        item = RentalItem(
            order=order,
            variant=variant,
            product_name_snapshot=product_record.name,
            daily_rate_snapshot=product_record.daily_rate,
            commission_rate_snapshot=Decimal("0.2000"),
            quantity=1,
            rental_start_date=start_date,
            rental_end_date=end_date,
            rental_days=rental_days,
            line_total=line_total,
            status=initial_status,
        )
        item.full_clean()
        item.save()

        if inspection:
            rental_return = RentalReturn(
                rental_item=item,
                returned_on=min(today, end_date + timedelta(days=1)),
                recorded_by=manager,
            )
            rental_return.full_clean()
            rental_return.save()
            is_written_off = (
                inspection == ReturnInspection.Condition.WRITTEN_OFF
            )
            return_inspection = ReturnInspection(
                rental_return=rental_return,
                condition=inspection,
                notes=f"Demo inspection for order {index}.",
                inspected_by=manager,
                write_off_applied_at=(
                    timezone.now() if is_written_off else None
                ),
            )
            return_inspection.full_clean()
            return_inspection.save()

            if is_written_off:
                stock_updated = ProductVariant.objects.filter(
                    pk=variant.pk,
                    total_quantity__gte=item.quantity,
                ).update(
                    total_quantity=F("total_quantity") - item.quantity
                )
                if not stock_updated:
                    raise CommandError(
                        f"Insufficient stock for seeded write-off: {product}"
                    )

        if status == RentalItem.Status.COMPLETED:
            item.status = RentalItem.Status.COMPLETED
            item.save(update_fields=["status"])
            settlement = RentalSettlement.build_for_item(item)
            settlement.full_clean()
            settlement.save()

        if review:
            product_review = ProductReview(
                rental_item=item,
                rating=5,
                review_text=(
                    "Great fit and an easy rental experience. "
                    "I would rent this again."
                ),
            )
            product_review.full_clean()
            product_review.save()

        return item
