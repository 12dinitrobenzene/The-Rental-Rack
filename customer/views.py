from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from accounts.permissions import require_customer
from shop.models import Category, Product, ProductVariant, Vendor
from shop.visibility import visible_products

from .availability import available_quantity_by_day
from .forms import (
    CartUpdateForm,
    CatalogueFilterForm,
    CheckoutForm,
    RentalSelectionForm,
)
from .models import RentalItem, RentalOrder
from .rental_rules import calculate_rental_totals


RENTAL_CART_SESSION_KEY = "rental_cart"


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

    return render(
        request,
        "customer/catalogue.html",
        {
            "products": products,
            "filter_form": filter_form,
        },
    )


def customer_home(request):
    # Temporary selection until ML workflow is done ok - ck
    available_products = visible_products().order_by("-pk")
    products = available_products[:8]
    featured_vendors = Vendor.objects.filter(
        products__in=available_products,
    ).order_by("name").distinct()[:4]

    return render(
        request,
        "customer/home.html",
        {
            "products": products,
            "featured_vendors": featured_vendors,
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


def product_detail(request, product_id):
    product = get_object_or_404(
        visible_products(),
        pk=product_id,
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
        },
    )


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


def style_preferences(request):
    return render(
        request,
        "public/section_placeholder.html",
        {
            "title": "Style preferences",
            "message": "Personal style preferences will be available here.",
        },
    )


def _orders_for_customer(user):
    return (
        RentalOrder.objects.filter(customer=user)
        .select_related("vendor")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=RentalItem.objects.select_related("variant"),
            )
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

    return render(
        request,
        "customer/order_detail.html",
        {"order": order},
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
