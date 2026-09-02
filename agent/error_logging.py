"""Central place for recording agent failures.

End users should never see raw exception text (API error codes, stack traces,
model names, etc.). Anything that goes wrong while handling an agent request is
persisted to the ``AgentError`` model so it shows up in the admin panel, and is
also sent to the standard logging pipeline.
"""
import logging
import traceback

logger = logging.getLogger("agent.errors")

# Shown to the user in place of any internal error detail.
USER_FACING_ERROR = (
    "Sorry, something went wrong while processing your request. "
    "Our team has been notified. Please try again in a little while."
)


def log_agent_error(exc, *, source="", user=None, user_id=None, user_message=""):
    """Record ``exc`` against the given user. Never raises."""
    try:
        from .models import AgentError

        if user is None and user_id is not None:
            try:
                from accounts.models import Account
                user = Account.objects.filter(id=user_id).first()
            except Exception:
                user = None

        AgentError.objects.create(
            user=user,
            source=source or "",
            user_message=(user_message or "")[:5000],
            error_message=str(exc)[:5000],
            traceback="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )[:20000],
        )
    except Exception:  # logging must never break the request flow
        logger.exception("Failed to persist AgentError")

    logger.error("Agent error in %s: %s", source or "unknown", exc, exc_info=exc)
