from decimal import Decimal

from django.db import migrations


def copy_customer_rentals_to_shop(apps, schema_editor):
    CustomerOrder = apps.get_model("customer", "RentalOrder")
    CustomerItem = apps.get_model("customer", "RentalItem")
    ShopOrder = apps.get_model("shop", "RentalOrder")
    ShopItem = apps.get_model("shop", "RentalItem")

    ShopOrder.objects.bulk_create(
        [
            ShopOrder(
                id=order.id,
                customer_id=order.customer_id,
                vendor_id=order.vendor_id,
                delivery_address=order.delivery_address,
                payment_status=order.payment_status,
                total_amount=order.total_amount,
                created_at=order.created_at,
            )
            for order in CustomerOrder.objects.all()
        ]
    )
    # auto_now_add is evaluated during bulk inserts, so restore the original
    # timestamps explicitly to keep order history unchanged.
    for order in CustomerOrder.objects.all().iterator():
        ShopOrder.objects.filter(pk=order.pk).update(
            created_at=order.created_at,
        )
    ShopItem.objects.bulk_create(
        [
            ShopItem(
                id=item.id,
                order_id=item.order_id,
                variant_id=item.variant_id,
                product_name_snapshot=item.product_name_snapshot,
                daily_rate_snapshot=item.daily_rate_snapshot,
                commission_rate_snapshot=Decimal("0.2000"),
                quantity=item.quantity,
                rental_start_date=item.rental_start_date,
                rental_end_date=item.rental_end_date,
                rental_days=item.rental_days,
                line_total=item.line_total,
                status=item.status,
            )
            for item in CustomerItem.objects.all()
        ]
    )


def copy_shop_rentals_to_customer(apps, schema_editor):
    CustomerOrder = apps.get_model("customer", "RentalOrder")
    CustomerItem = apps.get_model("customer", "RentalItem")
    ShopOrder = apps.get_model("shop", "RentalOrder")
    ShopItem = apps.get_model("shop", "RentalItem")

    CustomerOrder.objects.bulk_create(
        [
            CustomerOrder(
                id=order.id,
                customer_id=order.customer_id,
                vendor_id=order.vendor_id,
                delivery_address=order.delivery_address,
                payment_status=order.payment_status,
                total_amount=order.total_amount,
                created_at=order.created_at,
            )
            for order in ShopOrder.objects.all()
        ]
    )
    for order in ShopOrder.objects.all().iterator():
        CustomerOrder.objects.filter(pk=order.pk).update(
            created_at=order.created_at,
        )
    CustomerItem.objects.bulk_create(
        [
            CustomerItem(
                id=item.id,
                order_id=item.order_id,
                variant_id=item.variant_id,
                product_name_snapshot=item.product_name_snapshot,
                daily_rate_snapshot=item.daily_rate_snapshot,
                quantity=item.quantity,
                rental_start_date=item.rental_start_date,
                rental_end_date=item.rental_end_date,
                rental_days=item.rental_days,
                line_total=item.line_total,
                status=item.status,
            )
            for item in ShopItem.objects.all()
        ]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("customer", "0002_rentalitem"),
        (
            "shop",
            "0005_rentalorder_rentalitem_rentalreturn_rentalsettlement_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            copy_customer_rentals_to_shop,
            copy_shop_rentals_to_customer,
        ),
    ]
