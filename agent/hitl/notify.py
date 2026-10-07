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
