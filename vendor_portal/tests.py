from django.test import TestCase
from django.urls import reverse

from shop.test_helpers import (
    make_employee,
    make_rental_item,
    make_variant,
    make_vendor,
)


class VendorIsolationTests(TestCase):
    def test_employee_cannot_access_another_vendors_records(self):
        own_vendor = make_vendor("Own Vendor")
        other_vendor = make_vendor("Other Vendor")
        user, _ = make_employee("vendor-employee", own_vendor)
        _, own_product, own_variant = make_variant(
            "own",
            vendor=own_vendor,
        )
        _, other_product, other_variant = make_variant(
            "other",
            vendor=other_vendor,
        )
        _, own_item = make_rental_item(
            "own-rental",
            variant=own_variant,
        )
        _, other_item = make_rental_item(
            "other-rental",
            variant=other_variant,
        )
        self.client.force_login(user)

        self.assertEqual(
            self.client.get(
                reverse("vendor_portal:product_detail", args=[own_product.pk])
            ).status_code,
            200,
        )
        for route_name, object_id in (
            ("vendor_portal:product_detail", other_product.pk),
            ("vendor_portal:rental_detail", other_item.pk),
        ):
            with self.subTest(route=route_name):
                self.assertEqual(
                    self.client.get(reverse(route_name, args=[object_id])).status_code,
                    404,
                )

        self.assertEqual(
            self.client.get(
                reverse("vendor_portal:rental_detail", args=[own_item.pk])
            ).status_code,
            200,
        )
