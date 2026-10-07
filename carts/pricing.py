"""Single source of truth for cart totals (cart page, checkout, order, Razorpay amount).

Coupons are user-specific and product-specific: ``percent`` off at most
``max_units`` units of the coupon's product; tax (18%) is charged on the
discounted amount.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple

from django.utils import timezone

from .models import Coupon

TAX_RATE = Decimal("0.18")
SESSION_KEY = "coupon_code"
CENT = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class CartPricing:
    total: Decimal = Decimal("0.00")          # before discount
    quantity: int = 0
    discount: Decimal = Decimal("0.00")
    tax: Decimal = Decimal("0.00")
    grand_total: Decimal = Decimal("0.00")
    coupon: Optional[Coupon] = None
    # cart_item.id -> discount applied to that line
    line_discounts: Dict[int, Decimal] = field(default_factory=dict)

    @property
    def taxable(self) -> Decimal:
        return self.total - self.discount


def find_coupon(code: str, user) -> Optional[Coupon]:
    if not code or not getattr(user, "is_authenticated", False):
        return None
    return Coupon.objects.filter(user=user, code__iexact=code.strip()).select_related("product").first()


def check_coupon(coupon: Optional[Coupon], cart_items) -> Optional[str]:
    """Return None if the coupon can be used with these cart items, else a reason for the user."""
    if coupon is None:
        return "That coupon code isn't valid for your account."
    if coupon.used_at:
        return f"Coupon {coupon.code} has already been used."
    if coupon.expires_at <= timezone.now():
        return f"Coupon {coupon.code} expired on {timezone.localtime(coupon.expires_at):%d %b %Y}."
    if not any(item.product_id == coupon.product_id for item in cart_items):
        return f"Coupon {coupon.code} only applies to {coupon.product.product_name}. Add it to your cart to use it."
    return None


def price_cart(cart_items, coupon: Optional[Coupon] = None) -> CartPricing:
    items = list(cart_items)
    pricing = CartPricing()
    for item in items:
        pricing.total += Decimal(item.product.price) * item.quantity
        pricing.quantity += item.quantity

    if coupon is not None and check_coupon(coupon, items) is None:
        units_left = coupon.max_units
        rate = Decimal(coupon.percent) / 100
        for item in items:
            if item.product_id != coupon.product_id or units_left <= 0:
                continue
            units = min(item.quantity, units_left)
            line_discount = _money(Decimal(item.product.price) * units * rate)
            pricing.line_discounts[item.id] = line_discount
            pricing.discount += line_discount
            units_left -= units
        pricing.coupon = coupon

    pricing.total = _money(pricing.total)
    pricing.discount = _money(pricing.discount)
    pricing.tax = _money(pricing.taxable * TAX_RATE)
    pricing.grand_total = _money(pricing.taxable + pricing.tax)
    return pricing


def session_coupon(request, cart_items) -> Tuple[Optional[Coupon], Optional[str]]:
    """Coupon saved in the session, re-validated against the current cart.

    An invalid coupon is dropped from the session; the reason is returned so the
    page can tell the user.
    """
    code = request.session.get(SESSION_KEY)
    if not code:
        return None, None
    coupon = find_coupon(code, request.user)
    problem = check_coupon(coupon, list(cart_items))
    if problem:
        request.session.pop(SESSION_KEY, None)
        return None, problem
    return coupon, None


def pricing_context(pricing: CartPricing) -> dict:
    return {
        "total": pricing.total,
        "quantity": pricing.quantity,
        "discount": pricing.discount,
        "tax": pricing.tax,
        "grand_total": pricing.grand_total,
        "coupon": pricing.coupon,
    }
