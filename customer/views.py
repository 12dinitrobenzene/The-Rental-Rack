from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, render

from accounts.permissions import require_customer
from shop.models import Category, Product, ProductVariant, Vendor
from shop.visibility import visible_products

from .availability import available_quantity_by_day
from .forms import CatalogueFilterForm, RentalSelectionForm
from .models import RentalItem, RentalOrder


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
