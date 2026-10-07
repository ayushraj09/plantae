"""Ticket lifecycle for human-in-the-loop escalations.

Every channel (chat graph, Slack, Django admin, SLA sweep) goes through these
functions, so ticket state only changes in one place.
"""
import logging
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from agent.models import ChatMessage, EscalationTicket, TicketEvent

logger = logging.getLogger("agent.hitl")

VALID_ACTIONS = {"approve", "edit", "reject", "takeover"}


def _enqueue(func_path: str, *args):
    """Run a task in the django-q worker once the current transaction commits."""
    from django_q.tasks import async_task
    transaction.on_commit(lambda: async_task(func_path, *args))


def log_event(ticket, kind: str, source: str, actor=None, **payload) -> TicketEvent:
    return TicketEvent.objects.create(ticket=ticket, kind=kind, source=source, actor=actor, payload=payload)


# --- Queries ----------------------------------------------------------------

def active_ticket(user_id: int) -> Optional[EscalationTicket]:
    return (EscalationTicket.objects
            .filter(user_id=user_id, status__in=EscalationTicket.ACTIVE_STATUSES)
            .order_by("-created_at").first())


def active_takeover(user_id: int) -> Optional[EscalationTicket]:
    return (EscalationTicket.objects
            .filter(user_id=user_id, status=EscalationTicket.STATUS_TAKEOVER)
            .order_by("-created_at").first())


def widget_ticket(user_id: int) -> Optional[EscalationTicket]:
    """Ticket the chat widget should keep watching.

    Besides open tickets, this includes a ticket staff just approved/rejected whose
    AI reply is still being written in the worker; otherwise the widget could stop
    polling in that gap and never show the reply.
    """
    ticket = active_ticket(user_id)
    if ticket is not None:
        return ticket
    recent = (EscalationTicket.objects
              .filter(user_id=user_id, status__in=[EscalationTicket.STATUS_APPROVED, EscalationTicket.STATUS_REJECTED],
                      resolved_at__gte=timezone.now() - timezone.timedelta(minutes=5))
              .order_by("-resolved_at").first())
    if recent is not None and not recent.events.filter(kind="resolved", source="ai").exists():
        return recent
    return None


def ticket_payload(ticket: Optional[EscalationTicket]) -> Optional[Dict[str, Any]]:
    """What the chat widget needs to know about the user's open ticket."""
    if ticket is None:
        return None
    finishing = ticket.status in (EscalationTicket.STATUS_APPROVED, EscalationTicket.STATUS_REJECTED)
    return {"id": ticket.pk, "mode": ticket.mode, "status": ticket.status,
            # still "active" for the widget while the AI reply to a decision is being written
            "active": ticket.is_active or finishing,
            "category": ticket.get_category_display()}


# --- Chat memory --------------------------------------------------------------

def append_to_chat_memory(user_id: int, text: str) -> None:
    """Let the AI see staff messages/outcomes when the user keeps chatting later."""
    try:
        from langchain_core.messages import AIMessage
        from agent.langgraph.agent import supervisor_agent, chat_config
        config = chat_config(user_id)
        if supervisor_agent.get_state(config).values:
            supervisor_agent.update_state(config, {"messages": [AIMessage(content=text)]}, as_node="response")
    except Exception:
        logger.exception("Could not append to chat memory for user %s", user_id)


# --- Lifecycle ----------------------------------------------------------------

def create_ticket(*, user_id: int, category: str, collected: Dict[str, Any], trigger: str, mode: str) -> EscalationTicket:
    with transaction.atomic():
        ticket = EscalationTicket.objects.create(
            user_id=user_id,
            category=category,
            mode=mode,
            trigger=trigger,
            collected_info=collected,
            status=(EscalationTicket.STATUS_OPEN if mode == EscalationTicket.MODE_ASSIST
                    else EscalationTicket.STATUS_TAKEOVER),
        )
        ticket.graph_thread_id = f"esc_{ticket.pk}"
        ticket.save(update_fields=["graph_thread_id"])
        log_event(ticket, "created", "ai", category=category, trigger=trigger, mode=mode)
        _enqueue("agent.hitl.tasks.run_escalation", ticket.pk)
    logger.info("Escalation #%s opened (%s, %s, trigger=%s)", ticket.pk, category, mode, trigger)
    return ticket


def add_user_info(ticket: EscalationTicket, text: str) -> None:
    """User wrote more about an open assist ticket while waiting."""
    log_event(ticket, "message", "user", text=text)
    if ticket.slack_ts:
        _enqueue("agent.hitl.tasks.post_slack_thread", ticket.pk, f"*Customer added:* {text}")


def resolve_ticket(ticket_id: int, decision: Dict[str, Any], *, actor=None, source: str) -> EscalationTicket:
    """Apply a staff decision to an assist ticket that is waiting for review.

    decision = {"action": approve|edit|reject|takeover, "params": {...}, "note": str}
    Safe against double clicks: only the first decision for a ticket is used.
    """
    action = decision.get("action")
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unknown action {action!r}")

    with transaction.atomic():
        ticket = EscalationTicket.objects.select_for_update().get(pk=ticket_id)
        if ticket.status != EscalationTicket.STATUS_AWAITING:
            raise ValueError(f"Ticket #{ticket.pk} is {ticket.get_status_display().lower()}, not awaiting staff.")

        decision = {**decision, "actor_id": getattr(actor, "pk", None), "source": source}
        ticket.final_action = decision
        ticket.staff_note = decision.get("note") or ""
        ticket.assigned_to = actor or ticket.assigned_to
        if action == "takeover":
            _start_takeover_locked(ticket, actor, source)
        else:
            ticket.status = (EscalationTicket.STATUS_REJECTED if action == "reject"
                             else EscalationTicket.STATUS_APPROVED)
            ticket.resolved_at = timezone.now()
        ticket.save()
        log_event(ticket, {"approve": "approved", "edit": "edited", "reject": "rejected", "takeover": "takeover"}[action],
                  source, actor, decision=decision)
        _enqueue("agent.hitl.tasks.resume_escalation", ticket.pk, decision)
    return ticket


def _start_takeover_locked(ticket: EscalationTicket, actor, source: str) -> None:
    ticket.mode = EscalationTicket.MODE_TAKEOVER
    ticket.status = EscalationTicket.STATUS_TAKEOVER
    ticket.assigned_to = actor or ticket.assigned_to
    name = actor.first_name if actor and actor.first_name else "A member of the Plantae team"
    ChatMessage.objects.create(user=ticket.user, role="staff", ticket=ticket, author=actor,
                               message=f"{name} has joined the chat and will help you from here.")


def start_takeover(ticket_id: int, *, actor=None, source: str) -> EscalationTicket:
    with transaction.atomic():
        ticket = EscalationTicket.objects.select_for_update().get(pk=ticket_id)
        if ticket.status == EscalationTicket.STATUS_AWAITING:
            # Goes through resolve_ticket so the paused graph is closed cleanly.
            return resolve_ticket(ticket_id, {"action": "takeover"}, actor=actor, source=source)
        if not ticket.is_active:
            raise ValueError(f"Ticket #{ticket.pk} is already {ticket.get_status_display().lower()}.")
        if ticket.status != EscalationTicket.STATUS_TAKEOVER or ticket.assigned_to_id is None:
            _start_takeover_locked(ticket, actor, source)
            ticket.save()
            log_event(ticket, "takeover", source, actor)
            _enqueue("agent.hitl.tasks.refresh_slack_card", ticket.pk)
    return ticket


def end_takeover(ticket_id: int, *, actor=None, source: str, note: str = "") -> EscalationTicket:
    """Staff are done: close the ticket and let the AI answer again."""
    with transaction.atomic():
        ticket = EscalationTicket.objects.select_for_update().get(pk=ticket_id)
        if not ticket.is_active:
            raise ValueError(f"Ticket #{ticket.pk} is already {ticket.get_status_display().lower()}.")
        ticket.status = EscalationTicket.STATUS_RESOLVED
        ticket.resolved_at = timezone.now()
        ticket.assigned_to = ticket.assigned_to or actor
        if note:
            ticket.staff_note = note
        ticket.save()
        log_event(ticket, "handback", source, actor, note=note)
        text = "Thanks for your patience! You're back with the Plantae assistant. Anything else I can help with?"
        ChatMessage.objects.create(user=ticket.user, role="agent", ticket=ticket, message=text)
        _enqueue("agent.hitl.tasks.refresh_slack_card", ticket.pk)
    append_to_chat_memory(ticket.user_id, f"[Support ticket #{ticket.pk} was resolved by the Plantae team. {note}]".strip())
    return ticket


def relay_user_message(ticket: EscalationTicket, text: str) -> ChatMessage:
    """During takeover the AI is muted; the user's message goes to staff."""
    msg = ChatMessage.objects.create(user=ticket.user, role="user", ticket=ticket, message=text)
    log_event(ticket, "message", "user", text=text)
    _enqueue("agent.hitl.tasks.relay_message_to_slack", ticket.pk, msg.pk)
    return msg


def post_staff_message(ticket: EscalationTicket, text: str, *, actor=None, source: str) -> ChatMessage:
    msg = ChatMessage.objects.create(user=ticket.user, role="staff", ticket=ticket, author=actor, message=text)
    log_event(ticket, "message", source, actor, text=text)
    if ticket.assigned_to_id is None and actor is not None:
        EscalationTicket.objects.filter(pk=ticket.pk).update(assigned_to=actor)
    if source != "slack" and ticket.slack_ts:
        _enqueue("agent.hitl.tasks.post_slack_thread", ticket.pk, f"*Staff ({source}):* {text}")
    append_to_chat_memory(ticket.user_id, f"[Plantae team]: {text}")
    return msg


def post_ai_reply(ticket: EscalationTicket, text: str) -> ChatMessage:
    """Final AI message after staff decided an assist ticket."""
    msg = ChatMessage.objects.create(user=ticket.user, role="agent", ticket=ticket, message=text)
    log_event(ticket, "resolved", "ai", reply=text)
    append_to_chat_memory(ticket.user_id, text)
    return msg


def expire_ticket(ticket: EscalationTicket) -> None:
    with transaction.atomic():
        ticket = EscalationTicket.objects.select_for_update().get(pk=ticket.pk)
        if not ticket.is_active:
            return
        ticket.status = EscalationTicket.STATUS_EXPIRED
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "resolved_at", "updated_at"])
        log_event(ticket, "expired", "system")
        ChatMessage.objects.create(
            user=ticket.user, role="agent", ticket=ticket,
            message=(f"Sorry for the wait on request #{ticket.pk}. Our team couldn't get to it in chat, "
                     f"so they'll follow up by email at {ticket.user.email}."),
        )
        _enqueue("agent.hitl.tasks.refresh_slack_card", ticket.pk)
