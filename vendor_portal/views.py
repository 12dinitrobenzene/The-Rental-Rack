from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from accounts.permissions import get_employee_for_user
from shop.models import Product


@login_required(login_url="accounts:login")
def employee_home(request):
    employee = get_employee_for_user(request.user)

    products = Product.objects.filter(
        vendor=employee.vendor
    ).order_by("-created_at", "-pk")

    return render(
        request,
        "vendor_portal/home.html",
        {
            "vendor": employee.vendor,
            "products": products,
        },
    )


@login_required(login_url="accounts:login")
def employee_product_detail(request, product_id):
    employee = get_employee_for_user(request.user)
    product = get_object_or_404(
        Product.objects.select_related("category", "vendor"),
        pk=product_id,
        vendor=employee.vendor,
    )

    return render(
        request,
        "vendor_portal/product_detail.html",
        {
            "vendor": employee.vendor,
            "product": product,
        },
    )
