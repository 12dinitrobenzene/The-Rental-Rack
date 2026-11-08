from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import VendorEmployee
from shop.availability import available_quantity_by_day
from shop.models import (
    Category,
    Product,
    ProductVariant,
    RentalItem,
    RentalOrder,
    RentalReturn,
    RentalSettlement,
    ReturnInspection,
    Vendor,
)


class RentalLifecycleModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="lifecycle-customer",
            password="test-password",
        )
        employee_user = User.objects.create_user(
            username="lifecycle-employee",
            password="test-password",
        )
        other_employee_user = User.objects.create_user(
            username="other-lifecycle-employee",
            password="test-password",
        )
        self.vendor = Vendor.objects.create(
            name="Lifecycle Vendor",
            contact_email="lifecycle@example.com",
        )
        self.other_vendor = Vendor.objects.create(
            name="Other Lifecycle Vendor",
            contact_email="other-lifecycle@example.com",
        )
        self.employee = VendorEmployee.objects.create(
            user=employee_user,
            vendor=self.vendor,
        )
        self.other_employee = VendorEmployee.objects.create(
            user=other_employee_user,
            vendor=self.other_vendor,
        )
        category = Category.objects.create(name="Lifecycle Clothing")
        product = Product.objects.create(
            vendor=self.vendor,
            category=category,
            name="Lifecycle Jacket",
            description="A jacket for rental lifecycle tests.",
            brand="Test",
            daily_rate=Decimal("10.00"),
        )
        self.variant = ProductVariant.objects.create(
            product=product,
            sku="lifecycle-jacket-m",
            size="M",
            colour="Blue",
            total_quantity=3,
        )
        self.order = RentalOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            delivery_address="1 Test Street",
            payment_status=RentalOrder.PaymentStatus.PAID,
            total_amount=Decimal("20.00"),
        )
        self.item = RentalItem.objects.create(
            order=self.order,
            variant=self.variant,
            product_name_snapshot="Lifecycle Jacket",
            daily_rate_snapshot=Decimal("10.00"),
            quantity=1,
            rental_start_date=date(2026, 11, 1),
            rental_end_date=date(2026, 11, 2),
            rental_days=2,
            line_total=Decimal("20.00"),
            status=RentalItem.Status.ACTIVE,
        )

    def test_status_transitions_follow_the_rental_lifecycle(self):
        self.assertTrue(
            self.item.can_transition_to(RentalItem.Status.RETURNED)
        )
        self.assertTrue(
            self.item.can_transition_to(RentalItem.Status.OVERDUE)
        )
        self.assertFalse(
            self.item.can_transition_to(RentalItem.Status.COMPLETED)
        )

        self.item.transition_to(RentalItem.Status.RETURNED)

        self.assertEqual(self.item.status, RentalItem.Status.RETURNED)

    def test_invalid_status_transition_is_rejected(self):
        with self.assertRaises(ValidationError) as raised:
            self.item.transition_to(RentalItem.Status.COMPLETED)

        self.assertIn("status", raised.exception.message_dict)
        self.assertEqual(self.item.status, RentalItem.Status.ACTIVE)

    def test_return_must_be_recorded_by_the_orders_vendor(self):
        rental_return = RentalReturn(
            rental_item=self.item,
            returned_on=date(2026, 11, 3),
            recorded_by=self.other_employee,
        )

        with self.assertRaises(ValidationError) as raised:
            rental_return.full_clean()

        self.assertIn("recorded_by", raised.exception.message_dict)

    def test_inspection_must_be_performed_by_the_orders_vendor(self):
        rental_return = RentalReturn.objects.create(
            rental_item=self.item,
            returned_on=date(2026, 11, 3),
            recorded_by=self.employee,
        )
        inspection = ReturnInspection(
            rental_return=rental_return,
            condition=ReturnInspection.Condition.READY,
            inspected_by=self.other_employee,
        )

        with self.assertRaises(ValidationError) as raised:
            inspection.full_clean()

        self.assertIn("inspected_by", raised.exception.message_dict)

    def test_returned_item_stays_unavailable_until_inspection_completes(self):
        self.item.status = RentalItem.Status.RETURNED
        self.item.save(update_fields=["status"])

        availability = available_quantity_by_day(
            variant=self.variant,
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 1),
        )

        self.assertEqual(availability[date(2026, 12, 1)], 2)

    def test_eligible_completed_item_reconciles_80_20_settlement(self):
        self.item.status = RentalItem.Status.RETURNED
        self.item.save(update_fields=["status"])
        rental_return = RentalReturn.objects.create(
            rental_item=self.item,
            returned_on=date(2026, 11, 3),
            recorded_by=self.employee,
        )
        ReturnInspection.objects.create(
            rental_return=rental_return,
            condition=ReturnInspection.Condition.READY,
            inspected_by=self.employee,
        )
        self.item.status = RentalItem.Status.COMPLETED
        self.item.save(update_fields=["status"])
        settlement = RentalSettlement.build_for_item(self.item)

        settlement.full_clean()
        settlement.save()

        self.assertEqual(settlement.platform_amount, Decimal("4.00"))
        self.assertEqual(settlement.vendor_amount, Decimal("16.00"))

    def test_settlement_rounding_still_reconciles_to_line_total(self):
        self.item.line_total = Decimal("10.03")

        platform_amount, vendor_amount = (
            RentalSettlement.calculate_amounts(self.item)
        )

        self.assertEqual(platform_amount, Decimal("2.01"))
        self.assertEqual(vendor_amount, Decimal("8.02"))
        self.assertEqual(
            platform_amount + vendor_amount,
            self.item.line_total,
        )

    def test_settlement_rejects_ineligible_or_incorrect_amounts(self):
        settlement = RentalSettlement(
            rental_item=self.item,
            commission_rate_snapshot=Decimal("0.2000"),
            platform_amount=Decimal("5.00"),
            vendor_amount=Decimal("15.00"),
        )

        with self.assertRaises(ValidationError) as raised:
            settlement.full_clean()

        self.assertIn("rental_item", raised.exception.message_dict)
        self.assertIn("platform_amount", raised.exception.message_dict)
        self.assertIn("vendor_amount", raised.exception.message_dict)

    def test_settlement_rejects_unprocessed_written_off_inspection(self):
        rental_return = RentalReturn.objects.create(
            rental_item=self.item,
            returned_on=date(2026, 11, 3),
            recorded_by=self.employee,
        )
        self.item.status = RentalItem.Status.COMPLETED
        self.item.save(update_fields=["status"])
        inspection = ReturnInspection.objects.create(
            rental_return=rental_return,
            condition=ReturnInspection.Condition.WRITTEN_OFF,
            inspected_by=self.employee,
        )
        settlement = RentalSettlement.build_for_item(self.item)

        with self.assertRaises(ValidationError) as raised:
            settlement.full_clean()

        self.assertIn("rental_item", raised.exception.message_dict)
        self.assertIn(
            "Process the write-off before creating settlement.",
            raised.exception.message_dict["rental_item"],
        )

        inspection.write_off_applied_at = timezone.now()
        inspection.save(update_fields=["write_off_applied_at"])
        settlement.full_clean()
