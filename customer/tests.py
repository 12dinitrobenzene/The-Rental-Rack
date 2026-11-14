from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from customer.views import RENTAL_CART_SESSION_KEY
from shop.models import (
    CustomerStyleProfile,
    RentalItem,
    RentalOrder,
    StyleTag,
)
from shop.test_helpers import make_rental_item, make_user, make_variant


class CustomerRentalTests(TestCase):
    def setUp(self):
        self.customer = make_user("renter")
        self.client.force_login(self.customer)
        self.start = timezone.localdate() + timedelta(days=2)
        self.end = self.start + timedelta(days=1)

    def _cart_line(self, variant, quantity=1):
        return {
            "variant_id": variant.pk,
            "quantity": quantity,
            "start_date": self.start.isoformat(),
            "end_date": self.end.isoformat(),
        }

    def test_cart_uses_server_prices_and_allows_only_one_vendor(self):
        _, product, variant = make_variant("cart", rate="10.00")
        _, other_product, other_variant = make_variant("other-cart")
        payload = {
            "variant_id": variant.pk,
            "quantity": 1,
            "start_date": self.start.isoformat(),
            "end_date": self.end.isoformat(),
        }
        self.client.post(
            reverse("customer:cart_add", args=[product.pk]),
            payload,
        )

        self.assertEqual(RentalOrder.objects.count(), 0)
        product.daily_rate = Decimal("12.50")
        product.save(update_fields=["daily_rate"])
        response = self.client.get(reverse("customer:cart"))
        self.assertEqual(response.context["cart_total"], Decimal("25.00"))

        payload["variant_id"] = other_variant.pk
        self.client.post(
            reverse("customer:cart_add", args=[other_product.pk]),
            payload,
        )
        self.assertEqual(
            len(self.client.session[RENTAL_CART_SESSION_KEY]),
            1,
        )

    def test_checkout_is_atomic_and_rechecks_availability(self):
        _, _, variant = make_variant("checkout", stock=1)
        session = self.client.session
        session[RENTAL_CART_SESSION_KEY] = [self._cart_line(variant)]
        session.save()
        response = self.client.post(
            reverse("customer:checkout"),
            {
                "delivery_address": "1 Checkout Street",
                "confirm_payment": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        order = RentalOrder.objects.get(customer=self.customer)
        self.assertEqual(order.total_amount, Decimal("20.00"))
        self.assertEqual(order.items.get().daily_rate_snapshot, Decimal("10.00"))
        self.assertEqual(self.client.session[RENTAL_CART_SESSION_KEY], [])

        second_customer = make_user("second-renter")
        self.client.force_login(second_customer)
        session = self.client.session
        session[RENTAL_CART_SESSION_KEY] = [self._cart_line(variant)]
        session.save()
        self.client.post(
            reverse("customer:checkout"),
            {
                "delivery_address": "2 Checkout Street",
                "confirm_payment": "on",
            },
        )
        self.assertFalse(
            RentalOrder.objects.filter(customer=second_customer).exists()
        )
        self.assertEqual(
            len(self.client.session[RENTAL_CART_SESSION_KEY]),
            1,
        )

    def test_cancellation_is_blocked_after_dispatch(self):
        cancellable_order, cancellable_item = make_rental_item(
            "cancellable",
            customer=self.customer,
        )
        self.client.post(
            reverse("customer:order_cancel", args=[cancellable_order.pk])
        )
        cancellable_order.refresh_from_db()
        cancellable_item.refresh_from_db()
        self.assertEqual(
            cancellable_order.payment_status,
            RentalOrder.PaymentStatus.REFUNDED,
        )
        self.assertEqual(cancellable_item.status, RentalItem.Status.CANCELLED)

        dispatched_order, dispatched_item = make_rental_item(
            "dispatched",
            customer=self.customer,
            status=RentalItem.Status.DISPATCHED,
        )
        self.client.post(
            reverse("customer:order_cancel", args=[dispatched_order.pk])
        )
        dispatched_order.refresh_from_db()
        dispatched_item.refresh_from_db()
        self.assertEqual(
            dispatched_order.payment_status,
            RentalOrder.PaymentStatus.PAID,
        )
        self.assertEqual(dispatched_item.status, RentalItem.Status.DISPATCHED)


class PersonalisationTests(TestCase):
    def test_quiz_prediction_creates_profile_and_recommendation(self):
        customer = make_user("style-customer")
        for slug in (
            "minimalist_clean",
            "classic_polished",
            "urban_streetwear",
            "romantic_expressive",
            "avant_garde_statement",
        ):
            StyleTag.objects.get_or_create(
                slug=slug,
                defaults={
                    "display_name": slug.replace("_", " ").title(),
                },
            )
        self.client.force_login(customer)
        response = self.client.post(
            reverse("customer:style_preferences"),
            {
                "silhouette": "sculptural_asymmetric",
                "details": "experimental_details",
                "impression": "bold_unforgettable",
                "styling_approach": "unexpected_contrast",
                "statement_level": "high",
                "palette": "neutral",
            },
        )

        self.assertRedirects(response, reverse("customer:home"))
        profile = CustomerStyleProfile.objects.get(customer=customer)
        _, product, _ = make_variant("recommended")
        product.style_tags.add(profile.predicted_style)
        response = self.client.get(reverse("customer:home"))
        self.assertIn(product, response.context["products"])
