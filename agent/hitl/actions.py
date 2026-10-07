"""What an approved staff decision actually does.

Database changes for escalations only happen here, after a human approved them.
"""
import logging
from typing import Any, Dict

from django.db import transaction

logger = logging.getLogger("agent.hitl")

MAX_DISCOUNT_PERCENT = 50


def _cancel_order(ticket, params: Dict[str, Any]) -> str:
    from orders.models import Order

    with transaction.atomic():
        order = (Order.objects.select_for_update()
                 .filter(user=ticket.user, order_number=params.get("order_number")).first())
        if order is None:
            return "The order could not be found, so nothing was cancelled."
        if order.status != "Accepted":
            return f"Order {order.order_number} is already {order.status}, so it was not cancelled."
        order.status = "Cancelled"
        order.save(update_fields=["status", "updated_at"])
    return f"Order {order.order_number} has been cancelled. Any refund is processed to the original payment method."


def coupon_code_for(product, percent: int, user) -> str:
    """ROSE10, SNAKEPLANT15, ... unique per user (suffix -2, -3 on repeats)."""
    import re
    from carts.models import Coupon

    stem = re.sub(r"[^A-Z0-9]", "", product.product_name.upper())[:20] or "PLANT"
    base = f"{stem}{percent}"
    code, n = base, 2
    while Coupon.objects.filter(user=user, code__iexact=code).exists():
        code, n = f"{base}-{n}", n + 1
    return code


def _price_match(ticket, params: Dict[str, Any]) -> str:
    from datetime import timedelta
    from django.conf import settings
    from django.utils import timezone
    from carts.models import Coupon
    from agent.langgraph.tools import find_product

    percent = int(params.get("discount_percent") or 0)
    if not 0 < percent <= MAX_DISCOUNT_PERCENT:
        raise ValueError(f"discount_percent must be between 1 and {MAX_DISCOUNT_PERCENT}")
    product = find_product(params.get("product_name") or (ticket.collected_info or {}).get("product_name"))
    if product is None:
        raise ValueError("could not identify the product for the price match")

    coupon = Coupon.objects.create(
        code=coupon_code_for(product, percent, ticket.user),
        user=ticket.user,
        product=product,
        percent=percent,
        max_units=settings.PRICE_MATCH_MAX_UNITS,
        expires_at=timezone.now() + timedelta(days=settings.PRICE_MATCH_VALID_DAYS),
        ticket=ticket,
    )
    expires = timezone.localtime(coupon.expires_at).strftime("%d %b %Y")
    return (f"A {percent}% price match on {product.product_name} was approved. Coupon code {coupon.code} gives "
            f"{percent}% off up to {coupon.max_units} {product.product_name} in one order. It works only on this "
            f"customer's account: enter it in the coupon box on the cart or checkout page before paying. "
            f"Valid until {expires}, single use.")


def _note_only(ticket, params: Dict[str, Any]) -> str:
    return "Our team reviewed the request."


ACTION_HANDLERS = {
    "cancel_order": _cancel_order,
    "price_match": _price_match,
    "note_only": _note_only,
}


def apply_action(ticket, decision: Dict[str, Any]) -> str:
    """Run the approved (possibly staff-edited) action; returns an outcome sentence."""
    if decision.get("action") == "reject":
        return "Our team reviewed the request and was not able to approve it."
    proposal = {k: v for k, v in (ticket.proposed_action or {}).items() if k != "facts"}
    params = {**proposal, **(decision.get("params") or {})}
    if params.get("discount_percent") and params.get("type", "note_only") == "note_only":
        # Staff set a discount although the AI could not compute one.
        params["type"] = "price_match"
        params.setdefault("product_name", (ticket.collected_info or {}).get("product_name"))
    handler = ACTION_HANDLERS.get(params.get("type", "note_only"), _note_only)
    try:
        return handler(ticket, params)
    except Exception as exc:
        logger.exception("Action %s failed for ticket #%s", params.get("type"), ticket.pk)
        return f"Our team approved the request, but it could not be completed automatically ({exc}). They will follow up."
