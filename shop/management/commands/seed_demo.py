import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import CustomerProfile, VendorEmployee
from accounts.roles import CUSTOMER_GROUP, PLATFORM_ADMIN_GROUP, VENDOR_EMPLOYEE_GROUP
from shop.models import Category, Product, ProductImage, ProductVariant, StyleTag, Vendor


class Command(BaseCommand):
    help = "Load the exported Nike catalogue and three local demo accounts."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command creates demo logins and requires DEBUG=True.")

        seed_root = Path(settings.BASE_DIR) / "shop" / "seed_data"
        data = json.loads((seed_root / "nike_catalogue.json").read_text())

        # Validate bundled assets before making database changes.
        for product in data["products"]:
            for picture in product["images"]:
                asset = picture["asset"]
                if asset and not (seed_root / asset).is_file():
                    raise CommandError(f"Missing bundled image: {asset}")

        with transaction.atomic():
            vendor_data = dict(data["vendor"])
            email = vendor_data.pop("contact_email")
            vendor, _ = Vendor.objects.update_or_create(
                contact_email=email, defaults=vendor_data
            )

            User = get_user_model()
            users = {}
            for username, role in [
                ("demo_customer", CUSTOMER_GROUP),
                ("nike_employee", VENDOR_EMPLOYEE_GROUP),
                ("platform_admin", PLATFORM_ADMIN_GROUP),
            ]:
                user, _ = User.objects.update_or_create(
                    username=username,
                    defaults={
                        "is_active": True,
                        "is_staff": False,
                        "is_superuser": False,
                    },
                )
                user.set_password("Password")
                user.save()
                group, _ = Group.objects.get_or_create(name=role)
                user.groups.set([group])
                users[username] = user

            CustomerProfile.objects.get_or_create(user=users["demo_customer"])
            VendorEmployee.objects.update_or_create(
                user=users["nike_employee"],
                defaults={
                    "vendor": vendor,
                    "is_vendor_admin": data["employee_is_vendor_admin"],
                },
            )

            for record in data["products"]:
                category, _ = Category.objects.get_or_create(name=record["category"])
                fields = dict(record["fields"])
                name = fields.pop("name")
                product, _ = Product.objects.update_or_create(
                    vendor=vendor, name=name,
                    defaults={**fields, "category": category},
                )
                tags = []
                for tag_data in record["style_tags"]:
                    tag, _ = StyleTag.objects.get_or_create(
                        slug=tag_data["slug"],
                        defaults={"display_name": tag_data["display_name"]},
                    )
                    tags.append(tag)
                product.style_tags.set(tags)

                for variant_data in record["variants"]:
                    fields = dict(variant_data)
                    size = fields.pop("size")
                    colour = fields.pop("colour")
                    ProductVariant.objects.update_or_create(
                        product=product, size=size, colour=colour, defaults=fields
                    )

                for picture in record["images"]:
                    if not picture["asset"]:
                        self.stdout.write(self.style.WARNING(
                            f"Skipped missing source image for {name}: "
                            f"{picture['original_path']}"
                        ))
                        continue

                    # Stable storage paths make rerunning the snapshot repeatable.
                    target = f"seed/nike/{Path(picture['asset']).name}"
                    storage = ProductImage._meta.get_field("image").storage
                    if not storage.exists(target):
                        with (seed_root / picture["asset"]).open("rb") as stream:
                            target = storage.save(target, File(stream))
                    ProductImage.objects.update_or_create(
                        product=product, image=target,
                        defaults={
                            "alt_text": picture["alt_text"],
                            "sort_order": picture["sort_order"],
                        },
                    )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(data['products'])} Nike products and three demo accounts."
        ))
        self.stdout.write("demo_customer / nike_employee / platform_admin")
        self.stdout.write("Password for each account: Password")
