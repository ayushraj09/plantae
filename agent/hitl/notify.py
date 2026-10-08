"""Email fallback for escalations (used when Slack is not configured or for SLA reminders)."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger("agent.hitl")


def admin_url(ticket) -> str:
    return settings.SITE_URL.rstrip("/") + reverse("admin:agent_escalationticket_change", args=[ticket.pk])


def email_staff(ticket, subject_prefix: str = "New") -> bool:
    if not settings.HITL_STAFF_EMAILS:
        return False
    body = (
        f"{ticket.get_category_display()} from {ticket.user.email} ({ticket.get_mode_display()})\n\n"
        f"{ticket.summary or ticket.collected_info}\n\n"
        f"Proposed: {ticket.proposed_action}\n\nOpen: {admin_url(ticket)}"
    )
    try:
        send_mail(f"[Plantae] {subject_prefix} escalation #{ticket.pk}", body,
                  settings.DEFAULT_FROM_EMAIL, settings.HITL_STAFF_EMAILS, fail_silently=False)
        return True
    except Exception:
        logger.exception("Escalation email failed for #%s", ticket.pk)
        return False


def email_customer_expired(ticket) -> bool:
    """The team couldn't reply in chat in time: confirm to the customer that they'll follow up by email."""
    if not ticket.user.email:
        return False
    body = (
        f"Hi {ticket.user.first_name or 'there'},\n\n"
        f"Thanks for contacting Plantae. We're sorry we couldn't reply to your request #{ticket.pk} "
        f"({ticket.get_category_display().lower()}) in the chat in time.\n\n"
        f"Our team has your request and will follow up with you by email. You can simply reply to this "
        f"message to add any details.\n\n"
        f"The Plantae team\n{settings.SITE_URL}"
    )
    try:
        send_mail(f"Your Plantae request #{ticket.pk}", body, settings.DEFAULT_FROM_EMAIL, [ticket.user.email],
                  fail_silently=False)
        return True
    except Exception:
        logger.exception("Customer expiry email failed for #%s", ticket.pk)
        return False


def email_staff_expired(ticket) -> bool:
    """Hand the expired ticket to staff by email, with the recent conversation."""
    if not settings.HITL_STAFF_EMAILS:
        return False
    from agent.models import ChatMessage
    recent = ChatMessage.objects.filter(ticket=ticket).order_by("timestamp")[:30]
    transcript = "\n".join(f"[{m.timestamp:%d %b %H:%M}] {m.role}: {m.message}" for m in recent)
    body = (
        f"Ticket #{ticket.pk} expired without a reply in chat. Please follow up by email.\n\n"
        f"Customer: {ticket.user.first_name} {ticket.user.last_name} <{ticket.user.email}>\n"
        f"Category: {ticket.get_category_display()}\n\n{ticket.summary or ticket.collected_info}\n\n"
        f"Conversation:\n{transcript}\n\nOpen: {admin_url(ticket)}"
    )
    try:
        send_mail(f"[Plantae] Expired escalation #{ticket.pk}: follow up by email", body,
                  settings.DEFAULT_FROM_EMAIL, settings.HITL_STAFF_EMAILS, fail_silently=False)
        return True
    except Exception:
        logger.exception("Staff expiry email failed for #%s", ticket.pk)
        return False
