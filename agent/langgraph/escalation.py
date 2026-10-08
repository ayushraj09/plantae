"""Human-in-the-loop escalation.

Two pieces live here:

1. ``escalation_intake_node`` - a node in the chat graph (thread ``user_<id>``).
   It collects the details staff will need, then opens an EscalationTicket.
2. ``escalation_graph`` - a separate graph that runs on thread ``esc_<ticket_id>``
   inside the django-q worker. It prepares a proposal for staff, pauses with
   ``interrupt`` until staff decide (Slack or admin), applies the decision and
   writes the customer-facing reply.

Keeping the staff wait on its own thread means the user can keep chatting with
the AI while staff take their time; a new message on a paused thread would
otherwise discard the pending interrupt.
"""
import difflib
import logging
import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Literal, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from .checkpointer import checkpointer
from .tools import find_product

logger = logging.getLogger("agent.hitl")

# --- Categories -------------------------------------------------------------

# Details the AI must collect before handing a request to staff.
REQUIRED_FIELDS: Dict[str, Dict[str, str]] = {
    "price_match": {
        "product_name": "which of our products it is",
        "competitor_price": "the price you found",
        "competitor_source": "where you found it (store name or link)",
    },
    "cancellation": {"order_number": "your order number"},
    "delivery": {"order_number": "your order number"},
    "payment_issue": {
        "amount": "the amount that was charged",
        "payment_date": "when you made the payment",
    },
    "damaged_item": {
        "order_number": "your order number",
        "issue_description": "what is wrong with the item (a photo helps too)",
    },
    "bulk_order": {
        "product_name": "which products you need",
        "quantity": "roughly how many",
    },
    "complaint": {"issue_description": "what went wrong"},
    "other": {"issue_description": "what you need help with"},
    "human_request": {},
}

# Staff approve/edit an AI proposal for these; everything else is handed to a
# human who chats with the user directly.
ASSIST_CATEGORIES = {"price_match", "cancellation", "delivery", "payment_issue"}

CATEGORY_LABELS = {
    "price_match": "price match",
    "cancellation": "cancellation",
    "delivery": "delivery",
    "payment_issue": "payment",
    "damaged_item": "damaged item",
    "bulk_order": "bulk order",
    "complaint": "complaint",
    "other": "support",
    "human_request": "support",
}

MAX_PRICE_MATCH_PERCENT = 15
# After this many follow-up questions, hand over with whatever we have.
MAX_INTAKE_QUESTIONS = 2


def mode_for(category: str) -> str:
    return "assist" if category in ASSIST_CATEGORIES else "takeover"


# --- Hard triggers (no LLM) -------------------------------------------------

HUMAN_REQUEST_RE = re.compile(
    r"\b(talk|speak|chat|connect)\s+(to|with)\s+(a\s+|an\s+|some\s*one|someone|your\s+)?"
    r"(human|person|real person|agent|manager|representative|someone|support|team|staff)\b"
    r"|\b(real|live)\s+(human|person|agent)\b"
    r"|\bcustomer\s+(care|support|service)\b",
    re.IGNORECASE,
)


def detect_hard_triggers(user_id: int, text: str) -> Optional[Dict[str, str]]:
    """Return {"category", "trigger"} when the turn must go to a human regardless of the LLM."""
    if text and HUMAN_REQUEST_RE.search(text):
        return {"category": "human_request", "trigger": "keyword"}

    from agent.error_logging import USER_FACING_ERROR
    from agent.models import ChatMessage

    recent = list(
        ChatMessage.objects.filter(user_id=user_id).order_by("-timestamp").values_list("role", "message")[:6]
    )
    agent_replies = [m for r, m in recent if r == "agent"][:2]
    if len(agent_replies) == 2 and all(m == USER_FACING_ERROR for m in agent_replies):
        return {"category": "other", "trigger": "repeated_errors"}

    # The same question asked a third time means the AI is not helping.
    normalized = (text or "").strip().lower()
    if len(normalized) > 10:
        previous = [m.strip().lower() for r, m in recent if r == "user"]
        repeats = sum(1 for p in previous if difflib.SequenceMatcher(None, p, normalized).ratio() > 0.9)
        if repeats >= 2:
            return {"category": "other", "trigger": "repeated_question"}
    return None


# --- Intake (chat graph node) -----------------------------------------------

class IntakeExtraction(BaseModel):
    """Details extracted from the conversation for a support request."""
    product_name: Optional[str] = Field(None, description="Product the user is talking about")
    competitor_price: Optional[str] = Field(None, description="Price the user found elsewhere, digits only")
    competitor_source: Optional[str] = Field(None, description="Store or link where the user saw the other price")
    order_number: Optional[str] = Field(None, description="Order number / order ID")
    quantity: Optional[str] = Field(None, description="Quantity for bulk orders")
    amount: Optional[str] = Field(None, description="Amount charged, for payment issues")
    payment_date: Optional[str] = Field(None, description="When the payment was made")
    issue_description: Optional[str] = Field(None, description="Short description of the problem in the user's words")
    user_withdrew: bool = Field(False, description="True only if the user's LATEST message says they no longer need help with this request (e.g. 'never mind', 'forget it')")


def extract_intake(messages, category: str) -> IntakeExtraction:
    from .agent import make_llm

    transcript = "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
        for m in messages[-8:]
        if getattr(m, "content", None)
    )
    llm = make_llm().with_structured_output(IntakeExtraction, method="function_calling")
    return llm.invoke([
        SystemMessage(content=(
            "Extract support-request details for a plant store. The request category is "
            f"'{category}'. Only fill a field if the user actually stated it; never guess."
        )),
        HumanMessage(content=transcript),
    ])


def _missing_fields(category: str, collected: Dict[str, Any]):
    return [f for f in REQUIRED_FIELDS.get(category, {}) if not collected.get(f)]


def escalation_intake_node(state) -> Dict[str, Any]:
    from agent.hitl import service

    user_id = state["user_id"]
    pending = dict(state.get("pending_escalation") or {})
    decision = state.get("escalation") or {}
    category = pending.get("category") or decision.get("escalation_category") or "other"
    trigger = pending.get("trigger") or decision.get("trigger") or "supervisor"
    collected = dict(pending.get("collected") or {})
    questions_asked = int(pending.get("questions_asked", 0))
    # A frustrated customer goes straight to a person instead of answering questions.
    angry = decision.get("sentiment") == "angry" or pending.get("angry", False)

    active = service.active_ticket(user_id)
    if active is not None:
        service.add_user_info(active, state["messages"][-1].content)
        return {
            "pending_escalation": {},
            "intermediate_results": {"escalation": (
                f"Your {CATEGORY_LABELS.get(active.category, 'support')} request (#{active.pk}) is already with "
                "our team. I've added your message to it, and they'll reply right here in this chat."
            )},
        }

    if REQUIRED_FIELDS.get(category):
        extraction = extract_intake(state["messages"], category)
        if extraction.user_withdrew and pending:
            return {
                "pending_escalation": {},
                "intermediate_results": {"escalation": "No problem, I won't pass this to the team. Anything else I can help with?"},
            }
        for key, value in extraction.model_dump(exclude={"user_withdrew"}).items():
            if value and not collected.get(key):
                collected[key] = str(value).strip()
        if state.get("image_b64"):
            collected["photo_attached"] = "yes"

    missing = _missing_fields(category, collected)
    if missing and questions_asked < MAX_INTAKE_QUESTIONS and not angry:
        asks = [REQUIRED_FIELDS[category][f] for f in missing]
        ask_text = asks[0] if len(asks) == 1 else ", ".join(asks[:-1]) + " and " + asks[-1]
        return {
            "pending_escalation": {
                "category": category,
                "trigger": trigger,
                "collected": collected,
                "questions_asked": questions_asked + 1,
            },
            "intermediate_results": {"escalation": (
                f"I'll get our team to help with this. Could you tell me {ask_text}?"
            )},
        }

    ticket = service.create_ticket(
        user_id=user_id,
        category=category,
        collected=collected,
        trigger="angry_sentiment" if angry and trigger == "supervisor" else trigger,
        mode="takeover" if angry else mode_for(category),
    )
    if ticket.mode == "takeover":
        reply = (
            "I'm connecting you with a member of the Plantae team. They'll reply right here in this chat. "
            "You can keep typing and they'll see your messages."
        )
        if angry:
            reply = "I'm really sorry about this. " + reply
    else:
        reply = (
            f"Thanks! I've passed your {CATEGORY_LABELS.get(category, 'support')} request (#{ticket.pk}) to our team. "
            "They'll review it and you'll get an answer right here in this chat."
        )
    return {"pending_escalation": {}, "intermediate_results": {"escalation": reply}}


# --- Escalation graph (worker, thread esc_<ticket_id>) ----------------------

class EscalationState(TypedDict, total=False):
    ticket_id: int
    decision: Dict[str, Any]
    action_result: str


def _to_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    digits = re.sub(r"[^\d.]", "", str(value))
    try:
        return Decimal(digits) if digits else None
    except InvalidOperation:
        return None


def build_proposal(ticket) -> Dict[str, Any]:
    """Rule-based proposal + facts from the DB. Staff can always edit or reject it."""
    from orders.models import Order

    info = ticket.collected_info or {}
    facts: Dict[str, Any] = {}
    proposal: Dict[str, Any] = {"type": "note_only"}

    order = None
    if info.get("order_number"):
        order = Order.objects.filter(user=ticket.user, order_number=info["order_number"].strip()).first()
        facts["order_found"] = bool(order)
        if order:
            facts.update(order_status=order.status, order_total=str(order.order_total),
                         order_date=order.created_at.strftime("%Y-%m-%d"))

    if ticket.category == "price_match":
        product = find_product(info.get("product_name"))
        theirs = _to_decimal(info.get("competitor_price"))
        if product:
            facts.update(our_product=product.product_name, our_price=str(product.price))
        if product and theirs and theirs < product.price:
            gap = (Decimal(product.price) - theirs) / Decimal(product.price) * 100
            percent = min(math.ceil(gap), MAX_PRICE_MATCH_PERCENT)
            proposal = {"type": "price_match", "product_name": product.product_name, "discount_percent": percent}
            facts["price_gap_percent"] = round(float(gap), 1)
            if gap > MAX_PRICE_MATCH_PERCENT:
                facts["note"] = f"Gap exceeds the {MAX_PRICE_MATCH_PERCENT}% cap; proposal is capped."
        else:
            facts["note"] = "Could not compute a valid price gap (product not found, or their price is not lower)."
    elif ticket.category == "cancellation":
        if order and order.status == "Accepted":
            proposal = {"type": "cancel_order", "order_number": order.order_number}
        elif order:
            facts["note"] = f"Order is already {order.status}; it cannot simply be cancelled."
    return {"proposal": proposal, "facts": facts}


def summarize_ticket(ticket, facts: Dict[str, Any]) -> str:
    from agent.models import ChatMessage
    from .agent import make_llm

    from agent.models import EscalationTicket
    # Only this request: ignore conversation that belonged to the customer's earlier tickets.
    previous = (EscalationTicket.objects.filter(user=ticket.user, created_at__lt=ticket.created_at,
                                                resolved_at__isnull=False)
                .order_by("-resolved_at").values_list("resolved_at", flat=True).first())
    messages = ChatMessage.objects.filter(user=ticket.user)
    if previous:
        messages = messages.filter(timestamp__gt=previous)
    history = messages.order_by("-timestamp")[:10][::-1]
    transcript = "\n".join(f"{m.role}: {m.message[:500]}" for m in history)
    response = make_llm().invoke([
        SystemMessage(content=(
            "You brief customer-support staff of an online plant store. In at most 3 short sentences, "
            "say what the customer wants and the key facts. No greeting, no advice to the customer."
        )),
        HumanMessage(content=(
            f"Category: {ticket.category}\nDetails: {ticket.collected_info}\nFacts from our DB: {facts}\n"
            f"Recent chat:\n{transcript}"
        )),
    ])
    return response.content.strip()


def prepare_proposal_node(state: EscalationState) -> Dict[str, Any]:
    from agent.models import EscalationTicket

    ticket = EscalationTicket.objects.get(pk=state["ticket_id"])
    built = build_proposal(ticket)
    try:
        summary = summarize_ticket(ticket, built["facts"])
    except Exception:
        logger.exception("Ticket summary failed for #%s", ticket.pk)
        summary = f"{ticket.get_category_display()}: {ticket.collected_info}"

    # Conditional updates: staff may already have acted on the ticket (e.g. resolved
    # a takeover) before the worker got here, and that must not be undone.
    EscalationTicket.objects.filter(pk=ticket.pk).update(
        summary=summary, proposed_action={**built["proposal"], "facts": built["facts"]})
    if ticket.mode == EscalationTicket.MODE_ASSIST:
        EscalationTicket.objects.filter(pk=ticket.pk, status=EscalationTicket.STATUS_OPEN).update(
            status=EscalationTicket.STATUS_AWAITING)
    return {}


def staff_review_node(state: EscalationState) -> Dict[str, Any]:
    from agent.models import EscalationTicket

    ticket = EscalationTicket.objects.get(pk=state["ticket_id"])
    decision = interrupt({
        "type": "staff_approval",
        "ticket_id": ticket.pk,
        "summary": ticket.summary,
        "proposed_action": ticket.proposed_action,
    })
    return {"decision": decision}


def apply_decision_node(state: EscalationState) -> Dict[str, Any]:
    from agent.hitl.actions import apply_action
    from agent.models import EscalationTicket

    ticket = EscalationTicket.objects.get(pk=state["ticket_id"])
    return {"action_result": apply_action(ticket, state["decision"])}


def compose_customer_reply(ticket, decision: Dict[str, Any], action_result: str) -> str:
    from .agent import make_llm

    response = make_llm().invoke([
        SystemMessage(content=(
            "You are the Plantae plant-store assistant replying in the customer's chat after our support "
            "team reviewed their request. Write 2-4 friendly sentences. State the outcome exactly as given; "
            "do not invent discounts, codes, dates or promises that are not in the outcome or staff note. "
            "If the outcome contains a coupon code, repeat the code exactly, where to enter it, and its validity. "
            "If the request was declined, be kind and mention the staff note's reason if any."
        )),
        HumanMessage(content=(
            f"Request: {ticket.get_category_display()} - {ticket.collected_info}\n"
            f"Staff decision: {decision.get('action')}\nOutcome: {action_result}\n"
            f"Staff note for the customer: {decision.get('note') or '(none)'}"
        )),
    ])
    return response.content.strip()


def compose_reply_node(state: EscalationState) -> Dict[str, Any]:
    from agent.hitl import service
    from agent.models import EscalationTicket

    ticket = EscalationTicket.objects.get(pk=state["ticket_id"])
    decision = state["decision"]
    try:
        reply = compose_customer_reply(ticket, decision, state.get("action_result", ""))
    except Exception:
        logger.exception("Reply composition failed for #%s", ticket.pk)
        reply = f"Update on your request #{ticket.pk}: {state.get('action_result', '')}"
        if decision.get("note"):
            reply += f" Note from our team: {decision['note']}"
    service.post_ai_reply(ticket, reply)
    return {}


def _after_prepare(state: EscalationState) -> str:
    from agent.models import EscalationTicket

    status = EscalationTicket.objects.values_list("status", flat=True).get(pk=state["ticket_id"])
    return "staff_review" if status == EscalationTicket.STATUS_AWAITING else END


def _after_review(state: EscalationState) -> str:
    return END if state["decision"].get("action") == "takeover" else "apply_decision"


def create_escalation_graph():
    workflow = StateGraph(EscalationState)
    workflow.add_node("prepare_proposal", prepare_proposal_node)
    workflow.add_node("staff_review", staff_review_node)
    workflow.add_node("apply_decision", apply_decision_node)
    workflow.add_node("compose_reply", compose_reply_node)
    workflow.set_entry_point("prepare_proposal")
    workflow.add_conditional_edges("prepare_proposal", _after_prepare, ["staff_review", END])
    workflow.add_conditional_edges("staff_review", _after_review, ["apply_decision", END])
    workflow.add_edge("apply_decision", "compose_reply")
    workflow.add_edge("compose_reply", END)
    return workflow.compile(checkpointer=checkpointer)


escalation_graph = create_escalation_graph()


def escalation_config(ticket) -> Dict[str, Any]:
    return {"configurable": {"thread_id": ticket.graph_thread_id}}
