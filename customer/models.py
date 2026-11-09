from django.conf import settings
from django.db import models


class CustomerProductInteraction(models.Model):
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_interactions",
    )
    product = models.ForeignKey(
        "shop.Product",
        on_delete=models.CASCADE,
        related_name="customer_interactions",
    )
    view_count = models.PositiveIntegerField(default=1)
    last_viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "product"],
                name="unique_customer_product_interaction",
            ),
        ]

    def __str__(self):
        return f"{self.customer} viewed {self.product}"
