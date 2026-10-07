"""Slack integration for escalations.

Needs a Slack app with bot scopes ``chat:write``, ``users:read``, ``users:read.email``
and ``channels:history`` (thread replies for takeover), Interactivity pointed at
``/agent/slack/interactions/`` and Event Subscriptions (``message.channels``)
pointed at ``/agent/slack/events/``.
"""
import json
import logging
from typing import Optional

from django.conf import settings

logger = logging.getLogger("agent.hitl")


def is_enabled() -> bool:
    return bool(settings.SLACK_BOT_TOKEN and settings.SLACK_ESCALATION_CHANNEL)


def client():
    from slack_sdk import WebClient
    return WebClient(token=settings.SLACK_BOT_TOKEN)


def verify_request(request) -> bool:
    if not settings.SLACK_SIGNING_SECRET:
        return False
    from slack_sdk.signature import SignatureVerifier
    return SignatureVerifier(settings.SLACK_SIGNING_SECRET).is_valid_request(request.body, dict(request.headers))


def staff_account(slack_user_id: str):
    """Map a Slack user to a staff Account by email (None if not found or not staff)."""
    from accounts.models import Account
    try:
        email = client().users_info(user=slack_user_id)["user"]["profile"].get("email")
    except Exception:
        logger.exception("Slack users_info failed for %s", slack_user_id)
        return None
    if not email:
        return None
    return Account.objects.filter(email__iexact=email, is_staff=True).first()


# --- Message blocks -----------------------------------------------------------

def _button(text, action_id, ticket_id, style=None):
    button = {"type": "button", "text": {"type": "plain_text", "text": text},
              "action_id": action_id, "value": str(ticket_id)}
    if style:
        button["style"] = style
    return button


def price_preview(ticket, percent) -> Optional[str]:
    """Final per-unit price for a price-match discount, compared with the competitor.

    Returns None when the ticket has no known product price (e.g. product not found).
    """
    import math
    from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

    from agent.langgraph.escalation import _to_decimal

    facts = (ticket.proposed_action or {}).get("facts") or {}
    info = ticket.collected_info or {}
    ours = _to_decimal(facts.get("our_price"))
    if not ours:
        return None
    try:
        pct = int(str(percent).strip())
    except (TypeError, ValueError, InvalidOperation):
        return "Enter a discount between 1 and 50 to see the final price."
    if not 1 <= pct <= 50:
        return "Enter a discount between 1 and 50 to see the final price."

    final = (ours * (100 - pct) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    product = facts.get("our_product") or info.get("product_name") or "the product"
    line = (f"{pct}% off ₹{ours:.2f} → *₹{final:.2f}* per unit (₹{ours - final:.2f} off), "
            f"up to {settings.PRICE_MATCH_MAX_UNITS} × {product}")
    theirs = _to_decimal(info.get("competitor_price"))
    if theirs:
        source = info.get("competitor_source") or "competitor"
        if final > theirs:
            line += f"\nCompetitor ({source}) ₹{theirs:.2f}: still ₹{final - theirs:.2f} *above* it"
        elif final == theirs:
            line += f"\nCompetitor ({source}) ₹{theirs:.2f}: *matches exactly*"
        else:
            line += f"\nCompetitor ({source}) ₹{theirs:.2f}: ₹{theirs - final:.2f} *below* it"
        if theirs < ours:
            exact = math.ceil((ours - theirs) / ours * 100)
            line += f"\n{exact}% matches the competitor price"
    return line


def _describe_proposal(proposed: dict) -> str:
    kind = proposed.get("type", "note_only")
    if kind == "price_match":
        return f"Price match *{proposed.get('discount_percent')}%* on {proposed.get('product_name')}"
    if kind == "cancel_order":
        return f"Cancel order *{proposed.get('order_number')}*"
    return "No automatic action. Review and add a note for the customer."


def ticket_blocks(ticket) -> list:
    from .notify import admin_url

    proposed = ticket.proposed_action or {}
    facts = proposed.get("facts") or {}
    header = f"#{ticket.pk} · {ticket.get_category_display()} · {ticket.get_status_display()}"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": ticket.summary or "_No summary_"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Customer*\n{ticket.user.first_name} {ticket.user.last_name}"},
            {"type": "mrkdwn", "text": f"*Trigger*\n{ticket.trigger or '-'}"},
        ]},
    ]
    if ticket.collected_info:
        details = "\n".join(f"• {k.replace('_', ' ')}: {v}" for k, v in ticket.collected_info.items())
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Details*\n{details}"[:2900]}})
    if facts:
        fact_lines = "\n".join(f"• {k.replace('_', ' ')}: {v}" for k, v in facts.items())
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*From our records*\n{fact_lines}"[:2900]}})

    if ticket.status == ticket.STATUS_AWAITING:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*AI proposal:* {_describe_proposal(proposed)}"}})
        preview = price_preview(ticket, proposed.get("discount_percent")) if proposed.get("type") == "price_match" else None
        if preview:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": preview}]})
        blocks.append({"type": "actions", "elements": [
            _button("Approve", "hitl_approve", ticket.pk, "primary"),
            _button("Edit & approve", "hitl_edit", ticket.pk),
            _button("Reject", "hitl_reject", ticket.pk, "danger"),
            _button("Take over chat", "hitl_takeover", ticket.pk),
        ]})
    elif ticket.status == ticket.STATUS_TAKEOVER:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
            "Reply *in this thread* to message the customer. Their messages appear here."}]})
        blocks.append({"type": "actions", "elements": [_button("Hand back to AI", "hitl_handback", ticket.pk, "primary")]})
    else:
        outcome = ticket.final_action or {}
        by = f" by {ticket.assigned_to.email}" if ticket.assigned_to else ""
        note = f"\n>{ticket.staff_note}" if ticket.staff_note else ""
        action = f" ({outcome['action']})" if outcome.get("action") else ""
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f"*{ticket.get_status_display()}*{by}{action}{note}"}})
        approved_pct = (outcome.get("params") or {}).get("discount_percent") or proposed.get("discount_percent")
        if ticket.status == ticket.STATUS_APPROVED and ticket.category == "price_match" and approved_pct:
            preview = price_preview(ticket, approved_pct)
            if preview:
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Approved: {preview}"}]})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{admin_url(ticket)}|Open in admin>"}]})
    return blocks


def edit_modal(ticket, action_id: str, percent=None) -> dict:
    """Edit/Reject dialog. For price matches the discount box updates a live price preview."""
    proposed = ticket.proposed_action or {}
    blocks = []
    if action_id == "hitl_edit" and proposed.get("type") == "price_match":
        current = percent if percent not in (None, "") else (proposed.get("discount_percent") or 5)
        blocks.append({"type": "input", "block_id": "discount", "dispatch_action": True,
                       "label": {"type": "plain_text", "text": "Discount %"},
                       "element": {"type": "number_input", "is_decimal_allowed": False, "action_id": "value",
                                   "min_value": "1", "max_value": "50", "initial_value": str(current),
                                   "dispatch_action_config": {"trigger_actions_on": ["on_character_entered"]}}})
        preview = price_preview(ticket, current)
        if preview:
            blocks.append({"type": "context", "block_id": "price_preview",
                           "elements": [{"type": "mrkdwn", "text": preview}]})
    blocks.append({"type": "input", "block_id": "note", "optional": action_id != "hitl_reject",
                   "label": {"type": "plain_text", "text": "Note for the customer"},
                   "element": {"type": "plain_text_input", "multiline": True, "action_id": "value"}})
    return {
        "type": "modal",
        "callback_id": "hitl_decision",
        "private_metadata": json.dumps({"ticket_id": ticket.pk, "action": "reject" if action_id == "hitl_reject" else "edit"}),
        "title": {"type": "plain_text", "text": f"Ticket #{ticket.pk}"},
        "submit": {"type": "plain_text", "text": "Reject" if action_id == "hitl_reject" else "Approve"},
        "blocks": blocks,
    }


def update_modal(view_id: str, view_hash: str, view: dict) -> None:
    client().views_update(view_id=view_id, hash=view_hash, view=view)


# --- API calls ------------------------------------------------------------------

def post_ticket(ticket) -> Optional[str]:
    resp = client().chat_postMessage(channel=settings.SLACK_ESCALATION_CHANNEL,
                                     text=f"New escalation #{ticket.pk}: {ticket.get_category_display()}",
                                     blocks=ticket_blocks(ticket))
    return resp["ts"], resp["channel"]


def update_ticket(ticket) -> None:
    client().chat_update(channel=ticket.slack_channel, ts=ticket.slack_ts,
                         text=f"Escalation #{ticket.pk}: {ticket.get_status_display()}",
                         blocks=ticket_blocks(ticket))


def post_thread(ticket, text: str) -> None:
    client().chat_postMessage(channel=ticket.slack_channel, thread_ts=ticket.slack_ts, text=text)


def open_modal(trigger_id: str, view: dict) -> None:
    client().views_open(trigger_id=trigger_id, view=view)
