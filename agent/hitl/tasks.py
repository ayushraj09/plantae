"""django-q tasks (run by ``python manage.py qcluster``)."""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from django.db import transaction

from agent.models import ChatMessage, EscalationTicket, TicketEvent

from . import slack
from .notify import email_customer_expired, email_staff, email_staff_expired
from .service import expire_ticket, expiry_deadline, log_event

logger = logging.getLogger("agent.hitl")


def _notify_staff(ticket) -> None:
    if slack.is_enabled():
        try:
            ts, channel = slack.post_ticket(ticket)
            EscalationTicket.objects.filter(pk=ticket.pk).update(slack_ts=ts, slack_channel=channel)
            log_event(ticket, "posted", "system", channel="slack", ts=ts)
            # Customer messages sent before the card existed had no thread to go to.
            for message_id in ChatMessage.objects.filter(ticket=ticket, role="user").order_by("id").values_list("id", flat=True):
                relay_message_to_slack(ticket.pk, message_id)
            return
        except Exception:
            logger.exception("Slack post failed for #%s; falling back to email", ticket.pk)
    sent = email_staff(ticket)
    log_event(ticket, "posted", "system", channel="email" if sent else "admin_only")


def run_escalation(ticket_id: int) -> None:
    """Prepare the proposal, pause for staff (assist) and notify staff."""
    from agent.error_logging import log_agent_error
    from agent.langgraph.escalation import escalation_config, escalation_graph

    ticket = EscalationTicket.objects.get(pk=ticket_id)
    try:
        escalation_graph.invoke({"ticket_id": ticket.pk}, config=escalation_config(ticket))
    except Exception as exc:
        log_agent_error(exc, source="run_escalation", user=ticket.user, user_message=f"ticket #{ticket.pk}")
        # Staff still need to see it even if the AI part failed.
        EscalationTicket.objects.filter(pk=ticket.pk, status=EscalationTicket.STATUS_OPEN).update(
            status=EscalationTicket.STATUS_TAKEOVER, mode=EscalationTicket.MODE_TAKEOVER)
    ticket.refresh_from_db()
    _notify_staff(ticket)


def resume_escalation(ticket_id: int, decision: dict) -> None:
    from langgraph.types import Command
    from agent.error_logging import log_agent_error
    from agent.langgraph.escalation import escalation_config, escalation_graph

    ticket = EscalationTicket.objects.get(pk=ticket_id)
    try:
        escalation_graph.invoke(Command(resume=decision), config=escalation_config(ticket))
    except Exception as exc:
        log_agent_error(exc, source="resume_escalation", user=ticket.user, user_message=f"ticket #{ticket.pk}")
    refresh_slack_card(ticket_id)


def refresh_slack_card(ticket_id: int) -> None:
    ticket = EscalationTicket.objects.select_related("user", "assigned_to").get(pk=ticket_id)
    if slack.is_enabled() and ticket.slack_ts:
        try:
            slack.update_ticket(ticket)
        except Exception:
            logger.exception("Slack card update failed for #%s", ticket_id)


def relay_message_to_slack(ticket_id: int, message_id: int) -> None:
    """Post one customer message to the ticket's Slack thread, exactly once.

    Does nothing until the card exists; the card post then catches up on earlier messages.
    """
    if not slack.is_enabled():
        return
    with transaction.atomic():
        ticket = EscalationTicket.objects.select_for_update().select_related("user").get(pk=ticket_id)
        if not ticket.slack_ts:
            return
        if TicketEvent.objects.filter(ticket=ticket, kind="relayed", payload__message_id=message_id).exists():
            return
        msg = ChatMessage.objects.get(pk=message_id)
        event = ticket.events.filter(kind="message", source="user", payload__text=msg.message).order_by("-id").first()
        photo = (event.payload.get("photo_url") if event else "") or ""
        text = msg.message if not photo else f"{msg.message if msg.message != '📷 Photo' else ''}\n[Photo: {photo}]".strip()
        try:
            slack.post_thread(ticket, f"*{ticket.user.first_name or 'Customer'}:* {text}")
        except Exception:
            logger.exception("Slack relay failed for #%s message %s", ticket_id, message_id)
            return
        log_event(ticket, "relayed", "system", message_id=message_id)


def post_slack_thread(ticket_id: int, text: str) -> None:
    ticket = EscalationTicket.objects.get(pk=ticket_id)
    if slack.is_enabled() and ticket.slack_ts:
        try:
            slack.post_thread(ticket, text)
        except Exception:
            logger.exception("Slack thread post failed for #%s", ticket_id)


def send_expiry_emails(ticket_id: int) -> None:
    ticket = EscalationTicket.objects.select_related("user").get(pk=ticket_id)
    customer = email_customer_expired(ticket)
    staff = email_staff_expired(ticket)
    log_event(ticket, "emailed", "system", customer=customer, staff=staff)


def sla_sweep() -> None:
    """Scheduled every 5 minutes: remind staff, then expire tickets nobody picked up."""
    now = timezone.now()
    waiting = EscalationTicket.objects.filter(status__in=[EscalationTicket.STATUS_AWAITING, EscalationTicket.STATUS_TAKEOVER])

    # Expire only tickets with no staff reply for HITL_EXPIRE_HOURS, so a live conversation never expires.
    for ticket in waiting.filter(created_at__lte=now - timedelta(hours=settings.HITL_EXPIRE_HOURS)):
        if expiry_deadline(ticket) <= now:
            expire_ticket(ticket)

    overdue = waiting.filter(created_at__lte=now - timedelta(minutes=settings.HITL_SLA_MINUTES),
                             sla_reminded_at__isnull=True)
    # Takeover tickets someone already picked up are not overdue.
    overdue = overdue.exclude(status=EscalationTicket.STATUS_TAKEOVER, assigned_to__isnull=False)
    for ticket in overdue:
        EscalationTicket.objects.filter(pk=ticket.pk).update(sla_reminded_at=now)
        log_event(ticket, "sla", "system")
        if slack.is_enabled() and ticket.slack_ts:
            post_slack_thread(ticket.pk, f"<!here> Ticket #{ticket.pk} has waited over {settings.HITL_SLA_MINUTES} minutes.")
        email_staff(ticket, subject_prefix="Overdue")
