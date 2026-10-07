"""Slack webhooks for escalations. Authenticated by Slack's request signature, not a login."""
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .hitl import service, slack
from .models import EscalationTicket

logger = logging.getLogger("agent.hitl")


def _ephemeral(payload, text):
    if payload.get("response_url"):
        from slack_sdk.webhook import WebhookClient
        try:
            WebhookClient(payload["response_url"]).send(text=text, response_type="ephemeral", replace_original=False)
        except Exception:
            logger.exception("Slack ephemeral reply failed")


@csrf_exempt
@require_POST
def slack_interactions(request):
    if not slack.verify_request(request):
        return HttpResponse(status=403)
    payload = json.loads(request.POST.get("payload", "{}"))
    slack_user = payload.get("user", {})
    actor = slack.staff_account(slack_user.get("id", ""))
    who = {"slack_user": slack_user.get("username") or slack_user.get("name") or slack_user.get("id")}

    if payload.get("type") == "block_actions":
        action = payload["actions"][0]
        action_id = action["action_id"]
        ticket = EscalationTicket.objects.get(pk=int(action["value"]))
        try:
            if action_id in ("hitl_edit", "hitl_reject"):
                slack.open_modal(payload["trigger_id"], slack.edit_modal(ticket, action_id))
            elif action_id == "hitl_approve":
                service.resolve_ticket(ticket.pk, {"action": "approve", **who}, actor=actor, source="slack")
            elif action_id == "hitl_takeover":
                service.start_takeover(ticket.pk, actor=actor, source="slack")
            elif action_id == "hitl_handback":
                service.end_takeover(ticket.pk, actor=actor, source="slack")
        except ValueError as exc:
            _ephemeral(payload, str(exc))
        return HttpResponse(status=200)

    if payload.get("type") == "view_submission" and payload["view"].get("callback_id") == "hitl_decision":
        meta = json.loads(payload["view"]["private_metadata"])
        values = payload["view"]["state"]["values"]
        decision = {"action": meta["action"], "note": (values.get("note", {}).get("value", {}).get("value") or ""), **who}
        if "discount" in values:
            decision["params"] = {"discount_percent": int(values["discount"]["value"]["value"])}
        try:
            service.resolve_ticket(meta["ticket_id"], decision, actor=actor, source="slack")
        except ValueError as exc:
            return JsonResponse({"response_action": "errors", "errors": {"note": str(exc)}})
        return HttpResponse(status=200)

    return HttpResponse(status=200)


@csrf_exempt
@require_POST
def slack_events(request):
    # Slack retries when we are slow; the first delivery was already handled.
    if request.headers.get("X-Slack-Retry-Num"):
        return HttpResponse(status=200)
    if not slack.verify_request(request):
        return HttpResponse(status=403)
    body = json.loads(request.body or b"{}")
    if body.get("type") == "url_verification":
        return JsonResponse({"challenge": body.get("challenge")})

    event = body.get("event", {})
    is_staff_thread_reply = (event.get("type") == "message" and event.get("thread_ts")
                             and event.get("thread_ts") != event.get("ts")
                             and not event.get("bot_id") and not event.get("subtype"))
    if is_staff_thread_reply:
        ticket = EscalationTicket.objects.filter(slack_ts=event["thread_ts"], slack_channel=event.get("channel")).first()
        if ticket is not None:
            if ticket.status == EscalationTicket.STATUS_TAKEOVER:
                actor = slack.staff_account(event.get("user", ""))
                service.post_staff_message(ticket, event.get("text", ""), actor=actor, source="slack")
            else:
                # Discussion among staff before a decision: keep it internal.
                service.log_event(ticket, "note", "slack", text=event.get("text", ""), slack_user=event.get("user"))
    return HttpResponse(status=200)
