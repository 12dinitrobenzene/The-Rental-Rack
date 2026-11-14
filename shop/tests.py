from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from shop.models import (
    RentalItem,
    RentalSettlement,
    ReturnInspection,
)
from shop.test_helpers import make_employee, make_rental_item, make_variant


class RentalLifecycleTests(TestCase):
    def test_return_writeoff_updates_stock_and_settles_only_once(self):
        vendor, _, variant = make_variant("writeoff", stock=2)
        user, _ = make_employee("inspector", vendor)
        _, item = make_rental_item(
            "writeoff-rental",
            variant=variant,
            status=RentalItem.Status.ACTIVE,
        )
        today = timezone.localdate()
        item.rental_start_date = today - timedelta(days=2)
        item.rental_end_date = today - timedelta(days=1)
        item.save(update_fields=["rental_start_date", "rental_end_date"])
        self.client.force_login(user)

        self.client.post(
            reverse("vendor_portal:rental_return", args=[item.pk]),
            {"returned_on": today.isoformat()},
        )
        self.client.post(
            reverse("vendor_portal:return_inspection", args=[item.pk]),
            {
                "condition": ReturnInspection.Condition.WRITTEN_OFF,
                "notes": "Cannot be reused",
            },
        )
        complete_url = reverse(
            "vendor_portal:rental_complete",
            args=[item.pk],
        )
        self.client.post(complete_url)
        self.client.post(complete_url)

        item.refresh_from_db()
        variant.refresh_from_db()
        settlement = RentalSettlement.objects.get(rental_item=item)
        self.assertEqual(item.status, RentalItem.Status.COMPLETED)
        self.assertEqual(variant.total_quantity, 1)
        self.assertEqual(RentalSettlement.objects.filter(rental_item=item).count(), 1)
        self.assertEqual(settlement.platform_amount, Decimal("4.00"))
        self.assertEqual(settlement.vendor_amount, Decimal("16.00"))

    def test_invalid_transition_and_ineligible_settlement_are_rejected(self):
        _, item = make_rental_item("invalid-rental")

        with self.assertRaises(ValidationError):
            item.transition_to(RentalItem.Status.COMPLETED)

        settlement = RentalSettlement.build_for_item(item)
        with self.assertRaises(ValidationError):
            settlement.full_clean()
