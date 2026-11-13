from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from accounts.permissions import require_customer
from accounts.roles import CUSTOMER_GROUP, role_for_user
from recommendations.services import (
    StyleModelError,
    predict_style,
    rank_recommended_products,
)
from shop.availability import available_quantity_by_day
from shop.models import (
    Category,
    CustomerStyleProfile,
    Product,
    ProductReview,
    ProductVariant,
    RentalItem,
    RentalOrder,
    StyleTag,
    Vendor,
)
from shop.rental_rules import calculate_rental_totals
from shop.visibility import visible_products

from .forms import (
    CartUpdateForm,
    CatalogueFilterForm,
    CheckoutForm,
    ProductReviewForm,
    RentalSelectionForm,
    StyleQuizForm,
)
from .models import CustomerProductInteraction, WishlistItem


RENTAL_CART_SESSION_KEY = "rental_cart"
CANCELLABLE_RENTAL_STATUSES = {
    RentalItem.Status.CONFIRMED,
    RentalItem.Status.PREPARING,
}


def _wishlist_product_ids(customer, product_ids=None):
    wishlist = WishlistItem.objects.filter(customer=customer)

    if product_ids is not None:
        wishlist = wishlist.filter(product_id__in=product_ids)

    return set(wishlist.values_list("product_id", flat=True))


def _with_wishlist_state(
    products,
    *,
    user,
    next_url,
    wishlist_product_ids=None,
):
    products = list(products)
    wishlist_enabled = role_for_user(user) == CUSTOMER_GROUP

    if wishlist_enabled and wishlist_product_ids is None:
        wishlist_product_ids = _wishlist_product_ids(
            user,
            [product.pk for product in products],
        )
    else:
        wishlist_product_ids = set(wishlist_product_ids or ())

    for product in products:
        product.wishlist_enabled = wishlist_enabled
        product.is_wishlisted = product.pk in wishlist_product_ids
        product.wishlist_next_url = next_url

    return products


def _redirect_after_wishlist_action(request):
    next_url = request.POST.get("next", "")

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)

    return redirect("customer:wishlist")


def catalogue(request):
    products = visible_products()
    categories = Category.objects.filter(products__in=products).distinct()
    vendors = Vendor.objects.filter(products__in=products).distinct().order_by("name")
    sizes = (
        ProductVariant.objects.filter(
            product__in=products,
            is_active=True,
            total_quantity__gt=0,
        )
        .values_list("size", flat=True)
        .distinct()
        .order_by("size")
    )
    filter_form = CatalogueFilterForm(
        request.GET,
        categories=categories,
        vendors=vendors,
        sizes=sizes,
    )

    if filter_form.is_valid():
        query = filter_form.cleaned_data["q"]
        selected_category = filter_form.cleaned_data["category"]
        selected_vendor = filter_form.cleaned_data["vendor"]
        selected_size = filter_form.cleaned_data["size"]
        min_price = filter_form.cleaned_data["min_price"]
        max_price = filter_form.cleaned_data["max_price"]
        sort = filter_form.cleaned_data["sort"]

        if selected_category:
            products = products.filter(category_id=selected_category)

        if selected_vendor:
            products = products.filter(vendor_id=selected_vendor)

        if selected_size:
            products = products.filter(
                variants__is_active=True,
                variants__total_quantity__gt=0,
                variants__size=selected_size,
            )

        if min_price is not None:
            products = products.filter(daily_rate__gte=min_price)

        if max_price is not None:
            products = products.filter(daily_rate__lte=max_price)

        if query:
            products = products.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
            )

        if sort == "newest":
            products = products.order_by("-created_at", "-pk")
        elif sort == "price_low":
            products = products.order_by("daily_rate", "-pk")
        elif sort == "price_high":
            products = products.order_by("-daily_rate", "-pk")
    else:
        products = products.none()

    products = _with_wishlist_state(
        products,
        user=request.user,
        next_url=request.get_full_path(),
    )

    return render(
        request,
        "customer/catalogue.html",
        {
            "products": products,
            "filter_form": filter_form,
        },
    )


@login_required(login_url="accounts:login")
def customer_home(request):
    require_customer(request.user)

    try:
        style_profile = (
            CustomerStyleProfile.objects
            .select_related("predicted_style")
            .get(customer=request.user)
        )
    except CustomerStyleProfile.DoesNotExist:
        return redirect("customer:style_preferences")

    eligible_products = list(
        visible_products().prefetch_related("style_tags")
    )
    eligible_product_ids = [
        product.pk
        for product in eligible_products
    ]
    wishlist_product_ids = _wishlist_product_ids(
        request.user,
        eligible_product_ids,
    )
    view_counts = dict(
        CustomerProductInteraction.objects.filter(
            customer=request.user,
            product_id__in=eligible_product_ids,
        ).values_list("product_id", "view_count")
    )
    completed_style_ids = set(
        RentalItem.objects.filter(
            order__customer=request.user,
            status=RentalItem.Status.COMPLETED,
            variant__product__style_tags__isnull=False,
        ).values_list(
            "variant__product__style_tags__pk",
            flat=True,
        )
    )
    products = rank_recommended_products(
        eligible_products,
        predicted_style_id=style_profile.predicted_style_id,
        view_counts=view_counts,
        completed_style_ids=completed_style_ids,
        wishlist_product_ids=wishlist_product_ids,
    )
    products = _with_wishlist_state(
        products,
        user=request.user,
        next_url=request.get_full_path(),
        wishlist_product_ids=wishlist_product_ids,
    )

    featured_vendors = (
        Vendor.objects
        .filter(products__in=products)
        .order_by("name")
        .distinct()[:4]
    )

    return render(
        request,
        "customer/home.html",
        {
            "products": products,
            "featured_vendors": featured_vendors,
            "style_profile": style_profile,
        },
    )


def customer_placeholder(request, title, message):
    return render(
        request,
        "customer/placeholder.html",
        {
            "title": title,
            "message": message,
        },
    )


def about_us(request):
    return render(
        request,
        "customer/about_us.html",
        {
            "shop_name": "The Rental Rack",
        },
    )


def customer_guide(request):
    return render(
        request,
        "customer/guide.html",
        {
            "shop_name": "The Rental Rack",
        },
    )


def vendor_info(request):
    return render(
        request,
        "customer/vendor_info.html",
    )


def product_detail(request, product_id):
    product = get_object_or_404(
        visible_products(),
        pk=product_id,
    )

    if (
        request.method == "GET"
        and role_for_user(request.user) == CUSTOMER_GROUP
    ):
        interaction, created = (
            CustomerProductInteraction.objects.get_or_create(
                customer=request.user,
                product=product,
            )
        )

        if not created:
            CustomerProductInteraction.objects.filter(
                pk=interaction.pk
            ).update(
                view_count=F("view_count") + 1,
                last_viewed_at=timezone.now(),
            )

    rental_form = RentalSelectionForm(
        request.POST if request.method == "POST" else None,
        product=product,
    )

    rental_result = None

    if request.method == "POST" and rental_form.is_valid():
        data = rental_form.cleaned_data
        variant = data["variant_id"]

        availability = available_quantity_by_day(
            variant=variant,
            start_date=data["start_date"],
            end_date=data["end_date"],
        )

        available_quantity = min(availability.values())

        if data["quantity"] > available_quantity:
            rental_form.add_error(
                "quantity",
                (
                    f"Only {available_quantity} unit(s) are available "
                    "for the entire selected period."
                ),
            )
        else:
            rental_result = {
                "variant": variant,
                "quantity": data["quantity"],
                "rental_days": data["rental_days"],
                "line_total": data["line_total"],
                "available_quantity": available_quantity,
            }

    related_products = (
        visible_products()
        .filter(category=product.category)
        .exclude(pk=product.pk)[:4]
    )
    product = _with_wishlist_state(
        [product],
        user=request.user,
        next_url=request.get_full_path(),
    )[0]
    related_products = _with_wishlist_state(
        related_products,
        user=request.user,
        next_url=request.get_full_path(),
    )

    total_stock = sum(
        variant.total_quantity
        for variant in product.active_variants
    )

    available_colours = []
    seen_colours = set()

    for variant in product.active_variants:
        colour_key = variant.colour.strip().casefold()

        if colour_key not in seen_colours:
            seen_colours.add(colour_key)
            available_colours.append(
                {
                    "name": variant.colour,
                    "hex": variant.colour_hex,
                }
            )

    default_colour = (
        available_colours[0]["name"]
        if available_colours
        else ""
    )

    reviews = ProductReview.objects.filter(
        rental_item__variant__product=product,
    ).select_related(
        "rental_item__order__customer",
    )
    review_summary = reviews.aggregate(
        average_rating=Avg("rating"),
        review_count=Count("pk"),
    )

    return render(
        request,
        "customer/product_detail.html",
        {
            "product": product,
            "related_products": related_products,
            "total_stock": total_stock,
            "available_colours": available_colours,
            "default_colour": default_colour,
            "rental_form": rental_form,
            "rental_result": rental_result,
            "reviews": reviews,
            **review_summary,
        },
    )


class WishlistView(LoginRequiredMixin, View):
    login_url = "accounts:login"

    def get(self, request):
        require_customer(request.user)
        products = list(
            visible_products()
            .filter(wishlist_items__customer=request.user)
            .order_by("-wishlist_items__created_at", "-pk")
            .distinct()
        )
        products = _with_wishlist_state(
            products,
            user=request.user,
            next_url=request.get_full_path(),
            wishlist_product_ids={
                product.pk
                for product in products
            },
        )
        return render(
            request,
            "customer/wishlist.html",
            {"products": products},
        )


class WishlistAddView(LoginRequiredMixin, View):
    login_url = "accounts:login"
    http_method_names = ["post"]

    def post(self, request, product_id):
        require_customer(request.user)
        product = get_object_or_404(
            visible_products(),
            pk=product_id,
        )
        _, created = WishlistItem.objects.get_or_create(
            customer=request.user,
            product=product,
        )

        if created:
            messages.success(
                request,
                f"{product.name} was added to your wishlist.",
            )
        else:
            messages.info(
                request,
                f"{product.name} is already in your wishlist.",
            )

        return _redirect_after_wishlist_action(request)


class WishlistRemoveView(LoginRequiredMixin, View):
    login_url = "accounts:login"
    http_method_names = ["post"]

    def post(self, request, product_id):
        require_customer(request.user)
        deleted, _ = WishlistItem.objects.filter(
            customer=request.user,
            product_id=product_id,
        ).delete()

        if deleted:
            messages.success(request, "The product was removed from your wishlist.")

        return _redirect_after_wishlist_action(request)


class AddToCartView(LoginRequiredMixin, View):
    """Add one validated rental selection to the session cart."""

    login_url = "accounts:login"
    http_method_names = ["post"]

    def post(self, request, product_id):
        require_customer(request.user)

        product = get_object_or_404(
            visible_products(),
            pk=product_id,
        )
        form = RentalSelectionForm(request.POST, product=product)

        if not form.is_valid():
            first_error = next(
                error
                for errors in form.errors.values()
                for error in errors
            )
            messages.error(request, first_error)
            return redirect("customer:product_detail", product_id=product.pk)

        selection = form.cleaned_data
        variant = selection["variant_id"]
        availability = available_quantity_by_day(
            variant=variant,
            start_date=selection["start_date"],
            end_date=selection["end_date"],
        )
        available_quantity = min(availability.values())

        if selection["quantity"] > available_quantity:
            messages.error(
                request,
                (
                    f"Only {available_quantity} unit(s) are available "
                    "for the entire selected period."
                ),
            )
            return redirect("customer:product_detail", product_id=product.pk)

        cart = request.session.get(RENTAL_CART_SESSION_KEY, [])

        if cart:
            existing_variant = (
                ProductVariant.objects.select_related("product")
                .filter(pk=cart[0].get("variant_id"))
                .first()
            )

            if (
                existing_variant
                and existing_variant.product.vendor_id != product.vendor_id
            ):
                messages.error(
                    request,
                    (
                        "Your cart can contain rentals from only one vendor. "
                        "Empty the cart before choosing another vendor."
                    ),
                )
                return redirect(
                    "customer:product_detail",
                    product_id=product.pk,
                )

        cart.append({
            "variant_id": variant.pk,
            "quantity": selection["quantity"],
            "start_date": selection["start_date"].isoformat(),
            "end_date": selection["end_date"].isoformat(),
        })
        request.session[RENTAL_CART_SESSION_KEY] = cart

        messages.success(request, f"{product.name} was added to your cart.")
        return redirect("customer:product_detail", product_id=product.pk)


def _get_cart_line(cart, line_index):
    if line_index < 0 or line_index >= len(cart):
        raise Http404("Cart line not found.")

    return cart[line_index]


def _build_cart_summary(cart):
    variant_ids = [line["variant_id"] for line in cart]
    variants = {
        variant.pk: variant
        for variant in ProductVariant.objects.filter(pk__in=variant_ids)
        .select_related("product", "product__vendor")
    }
    cart_lines = []
    cart_total = Decimal("0.00")

    for line_index, line in enumerate(cart):
        variant = variants.get(line["variant_id"])

        if variant is None:
            continue

        start_date = date.fromisoformat(line["start_date"])
        end_date = date.fromisoformat(line["end_date"])
        rental_days, line_total = calculate_rental_totals(
            daily_rate=variant.product.daily_rate,
            quantity=line["quantity"],
            start_date=start_date,
            end_date=end_date,
        )
        cart_total += line_total
        cart_lines.append({
            "line_index": line_index,
            "variant": variant,
            "start_date": start_date,
            "end_date": end_date,
            "rental_days": rental_days,
            "quantity": line["quantity"],
            "daily_rate": variant.product.daily_rate,
            "line_total": line_total,
        })

    return cart_lines, cart_total


class CartView(LoginRequiredMixin, View):
    login_url = "accounts:login"

    def get(self, request):
        require_customer(request.user)
        cart = request.session.get(RENTAL_CART_SESSION_KEY, [])
        cart_lines, cart_total = _build_cart_summary(cart)

        for line in cart_lines:
            line["update_form"] = CartUpdateForm(
                daily_rate=line["daily_rate"],
                prefix=f"line-{line['line_index']}",
                initial={
                    "start_date": line["start_date"],
                    "end_date": line["end_date"],
                    "quantity": line["quantity"],
                },
            )

        return render(
            request,
            "customer/cart.html",
            {
                "cart_lines": cart_lines,
                "cart_total": cart_total,
            },
        )


class CartUpdateView(LoginRequiredMixin, View):
    login_url = "accounts:login"
    http_method_names = ["post"]

    def post(self, request, line_index):
        require_customer(request.user)
        cart = request.session.get(RENTAL_CART_SESSION_KEY, [])
        line = _get_cart_line(cart, line_index)
        variant = get_object_or_404(
            ProductVariant.objects.select_related("product"),
            pk=line["variant_id"],
        )
        form = CartUpdateForm(
            request.POST,
            daily_rate=variant.product.daily_rate,
            prefix=f"line-{line_index}",
        )

        if form.is_valid():
            update = form.cleaned_data
            availability = available_quantity_by_day(
                variant=variant,
                start_date=update["start_date"],
                end_date=update["end_date"],
            )
            available_quantity = min(availability.values())

            if update["quantity"] <= available_quantity:
                cart[line_index] = {
                    "variant_id": variant.pk,
                    "quantity": update["quantity"],
                    "start_date": update["start_date"].isoformat(),
                    "end_date": update["end_date"].isoformat(),
                }
                request.session[RENTAL_CART_SESSION_KEY] = cart
                messages.success(request, "Your cart was updated.")
                return redirect("customer:cart")

            messages.error(
                request,
                (
                    f"Only {available_quantity} unit(s) are available "
                    "for the entire selected period."
                ),
            )
        else:
            first_error = next(
                error
                for errors in form.errors.values()
                for error in errors
            )
            messages.error(request, first_error)

        return redirect("customer:cart")


class CartRemoveView(LoginRequiredMixin, View):
    login_url = "accounts:login"
    http_method_names = ["post"]

    def post(self, request, line_index):
        require_customer(request.user)
        cart = request.session.get(RENTAL_CART_SESSION_KEY, [])
        _get_cart_line(cart, line_index)
        cart.pop(line_index)
        request.session[RENTAL_CART_SESSION_KEY] = cart
        messages.success(request, "The rental item was removed from your cart.")
        return redirect("customer:cart")


class CheckoutView(LoginRequiredMixin, View):
    login_url = "accounts:login"
    template_name = "customer/checkout.html"

    def get(self, request):
        require_customer(request.user)
        cart = request.session.get(RENTAL_CART_SESSION_KEY, [])

        if not cart:
            messages.info(request, "Your cart is empty.")
            return redirect("customer:cart")

        cart_lines, cart_total = _build_cart_summary(cart)
        profile = getattr(request.user, "customer_profile", None)
        form = CheckoutForm(initial={
            "delivery_address": (
                profile.delivery_address if profile else ""
            ),
        })
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "cart_lines": cart_lines,
                "cart_total": cart_total,
            },
        )

    def post(self, request):
        require_customer(request.user)
        cart = request.session.get(RENTAL_CART_SESSION_KEY, [])

        if not cart:
            messages.info(request, "Your cart is empty.")
            return redirect("customer:cart")

        form = CheckoutForm(request.POST)
        cart_lines, cart_total = _build_cart_summary(cart)

        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "cart_lines": cart_lines,
                    "cart_total": cart_total,
                },
            )

        with transaction.atomic():
            cart_lines, cart_total = _build_cart_summary(cart)

            if len(cart_lines) != len(cart):
                messages.error(
                    request,
                    "A product in your cart is no longer available.",
                )
                return redirect("customer:cart")

            orderable_variant_ids = set(
                ProductVariant.objects.filter(
                    pk__in=[line["variant"].pk for line in cart_lines],
                    is_active=True,
                    total_quantity__gt=0,
                    product__in=visible_products(),
                ).values_list("pk", flat=True)
            )

            if any(
                line["variant"].pk not in orderable_variant_ids
                for line in cart_lines
            ):
                messages.error(
                    request,
                    "A product in your cart is no longer available. "
                    "Remove it before checking out.",
                )
                return redirect("customer:cart")

            vendor_ids = {
                line["variant"].product.vendor_id
                for line in cart_lines
            }

            if len(vendor_ids) != 1:
                messages.error(
                    request,
                    "Your cart must contain products from one vendor.",
                )
                return redirect("customer:cart")

            requested_by_variant_day = {}

            for line in cart_lines:
                availability = available_quantity_by_day(
                    variant=line["variant"],
                    start_date=line["start_date"],
                    end_date=line["end_date"],
                )

                for rental_date, available_quantity in availability.items():
                    key = (line["variant"].pk, rental_date)
                    requested_by_variant_day[key] = (
                        requested_by_variant_day.get(key, 0)
                        + line["quantity"]
                    )

                    if requested_by_variant_day[key] > available_quantity:
                        messages.error(
                            request,
                            (
                                "An item is no longer available in the "
                                "requested quantity. Please update your cart."
                            ),
                        )
                        return redirect("customer:cart")

            order = RentalOrder.objects.create(
                customer=request.user,
                vendor_id=vendor_ids.pop(),
                delivery_address=form.cleaned_data["delivery_address"],
                payment_status=RentalOrder.PaymentStatus.PAID,
                total_amount=cart_total,
            )

            for line in cart_lines:
                item = RentalItem(
                    order=order,
                    variant=line["variant"],
                    product_name_snapshot=line["variant"].product.name,
                    daily_rate_snapshot=line["daily_rate"],
                    quantity=line["quantity"],
                    rental_start_date=line["start_date"],
                    rental_end_date=line["end_date"],
                    rental_days=line["rental_days"],
                    line_total=line["line_total"],
                    status=RentalItem.Status.CONFIRMED,
                )
                item.full_clean()
                item.save()

        request.session[RENTAL_CART_SESSION_KEY] = []
        return redirect("customer:order_confirmation", order_id=order.pk)


@login_required(login_url="accounts:login")
def style_preferences(request):
    require_customer(request.user)

    if request.method == "POST":
        form = StyleQuizForm(request.POST)

        if form.is_valid():
            try:
                prediction = predict_style(form.cleaned_data)

                style_tag = StyleTag.objects.get(
                    slug=prediction["style"]
                )
            except StyleTag.DoesNotExist:
                form.add_error(
                    None,
                    "The predicted style is not configured.",
                )
            except StyleModelError:
                form.add_error(
                    None,
                    (
                        "Style recommendations are temporarily "
                        "unavailable. Please try again later."
                    ),
                )
            else:
                CustomerStyleProfile.objects.update_or_create(
                    customer=request.user,
                    defaults={
                        "silhouette": form.cleaned_data["silhouette"],
                        "details": form.cleaned_data["details"],
                        "impression": form.cleaned_data["impression"],
                        "styling_approach": (
                            form.cleaned_data["styling_approach"]
                        ),
                        "statement_level": (
                            form.cleaned_data["statement_level"]
                        ),
                        "palette": form.cleaned_data["palette"],
                        "predicted_style": style_tag,
                        "model_version": prediction["model_version"],
                    },
                )

                messages.success(
                    request,
                    (
                        "Your style profile has been updated. "
                        f"We identified your style as "
                        f"{style_tag.display_name}."
                    ),
                )

                return redirect("customer:home")
    else:
        form = StyleQuizForm()

    return render(
        request,
        "customer/style_preferences.html",
        {
            "form": form,
        },
    )


def _orders_for_customer(user):
    return (
        RentalOrder.objects.filter(customer=user)
        .select_related("vendor")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=RentalItem.objects.select_related(
                    "variant__product",
                    "review",
                ),
            )
        )
    )


def _can_cancel_order(order, items=None):
    order_items = list(items if items is not None else order.items.all())
    return (
        order.payment_status == RentalOrder.PaymentStatus.PAID
        and bool(order_items)
        and all(
            item.status in CANCELLABLE_RENTAL_STATUSES
            for item in order_items
        )
    )


@login_required(login_url="accounts:login")
def order_history(request):
    require_customer(request.user)

    orders = _orders_for_customer(request.user).order_by(
        "-created_at",
        "-pk",
    )

    return render(
        request,
        "customer/order_history.html",
        {"orders": orders},
    )


@login_required(login_url="accounts:login")
def order_detail(request, order_id):
    require_customer(request.user)

    order = get_object_or_404(
        _orders_for_customer(request.user),
        pk=order_id,
    )

    for item in order.items.all():
        item.review_submitted = hasattr(item, "review")
        item.can_review = (
            item.status == RentalItem.Status.COMPLETED
            and not item.review_submitted
        )

    return render(
        request,
        "customer/order_detail.html",
        {
            "order": order,
            "can_cancel": _can_cancel_order(order),
        },
    )


class ReviewCreateView(LoginRequiredMixin, View):
    login_url = "accounts:login"

    def _rental_item(self, request, rental_item_id):
        require_customer(request.user)
        return get_object_or_404(
            RentalItem.objects.select_related(
                "order",
                "variant__product",
            ),
            pk=rental_item_id,
            order__customer=request.user,
            order__payment_status=RentalOrder.PaymentStatus.PAID,
            status=RentalItem.Status.COMPLETED,
        )

    def _already_reviewed(self, request, rental_item):
        if not ProductReview.objects.filter(
            rental_item=rental_item,
        ).exists():
            return None

        messages.info(
            request,
            "You have already reviewed this rental item.",
        )
        return redirect(
            "customer:product_detail",
            product_id=rental_item.variant.product_id,
        )

    def get(self, request, rental_item_id):
        rental_item = self._rental_item(request, rental_item_id)
        reviewed_response = self._already_reviewed(
            request,
            rental_item,
        )

        if reviewed_response:
            return reviewed_response

        return render(
            request,
            "customer/review_form.html",
            {
                "form": ProductReviewForm(),
                "rental_item": rental_item,
                "product": rental_item.variant.product,
            },
        )

    def post(self, request, rental_item_id):
        rental_item = self._rental_item(request, rental_item_id)
        reviewed_response = self._already_reviewed(
            request,
            rental_item,
        )

        if reviewed_response:
            return reviewed_response

        form = ProductReviewForm(request.POST)

        if form.is_valid():
            review = form.save(commit=False)
            review.rental_item = rental_item

            try:
                with transaction.atomic():
                    review.save()
            except IntegrityError:
                messages.info(
                    request,
                    "You have already reviewed this rental item.",
                )
            else:
                messages.success(
                    request,
                    "Your review was submitted.",
                )

            return redirect(
                "customer:product_detail",
                product_id=rental_item.variant.product_id,
            )

        return render(
            request,
            "customer/review_form.html",
            {
                "form": form,
                "rental_item": rental_item,
                "product": rental_item.variant.product,
            },
        )


class OrderCancelView(LoginRequiredMixin, View):
    login_url = "accounts:login"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            require_customer(request.user)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, order_id):
        with transaction.atomic():
            order = get_object_or_404(
                RentalOrder.objects.select_for_update(),
                pk=order_id,
                customer=request.user,
            )
            items = list(
                RentalItem.objects.select_for_update()
                .filter(order=order)
                .order_by("pk")
            )

            if not _can_cancel_order(order, items):
                messages.error(
                    request,
                    "This order can no longer be cancelled.",
                )
                return redirect(
                    "customer:order_detail",
                    order_id=order.pk,
                )

            for item in items:
                item.transition_to(RentalItem.Status.CANCELLED)

            RentalItem.objects.bulk_update(items, ["status"])
            order.payment_status = RentalOrder.PaymentStatus.REFUNDED
            order.save(update_fields=["payment_status"])

        messages.success(
            request,
            "Your order was cancelled and the simulated payment was refunded.",
        )
        return redirect(
            "customer:order_detail",
            order_id=order.pk,
        )


@login_required(login_url="accounts:login")
def order_confirmation(request, order_id):
    require_customer(request.user)

    order = get_object_or_404(
        _orders_for_customer(request.user),
        pk=order_id,
        payment_status=RentalOrder.PaymentStatus.PAID,
    )

    return render(
        request,
        "customer/order_confirmation.html",
        {"order": order},
    )
