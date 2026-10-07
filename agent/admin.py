from django import forms
from django.contrib import admin, messages
from django.db.models import Max
from django.utils.html import format_html, format_html_join
from .models import ChatMessage, ChatSession, ChatImage, AgentError, EscalationTicket, TicketEvent
from .hitl import service as hitl

class UserChatSummaryAdmin(admin.ModelAdmin):
    list_display = ('user', 'concatenated_messages', 'latest_timestamp')
    search_fields = ('user__email',)
    list_filter = ('user',)
    readonly_fields = ('full_message_history',)
    fieldsets = (
        (None, {'fields': ('user', 'full_message_history')}),
    )

    def get_queryset(self, request):
        # Get the latest ChatMessage for each user
        subquery = ChatMessage.objects.values('user').annotate(
            latest_id=Max('id')
        ).values_list('latest_id', flat=True)
        return ChatMessage.objects.filter(id__in=subquery)

    def concatenated_messages(self, obj):
        # Limit to last 20 messages for performance
        messages = ChatMessage.objects.filter(user=obj.user).order_by('-timestamp')[:20][::-1]
        result = " | ".join(f"[{m.role}] {m.message}" for m in messages)
        total = ChatMessage.objects.filter(user=obj.user).count()
        if total > 20:
            result += f" | ... (showing last 20 of {total})"
        return result
    concatenated_messages.short_description = "All Messages"

    def latest_timestamp(self, obj):
        return obj.timestamp
    latest_timestamp.short_description = "Latest Message Time"

    def full_message_history(self, obj):
        # Limit to last 20 messages for performance
        messages = ChatMessage.objects.filter(user=obj.user).order_by('-timestamp')[:20][::-1]
        result = "\n".join(f"[{m.role}]: {m.message} :: ({m.timestamp.strftime('%Y-%m-%d %H:%M:%S')})" for m in messages)
        total = ChatMessage.objects.filter(user=obj.user).count()
        if total > 20:
            result += f"\n... (showing last 20 of {total})"
        return result
    full_message_history.short_description = "Full Message History"
    full_message_history.allow_tags = False

@admin.register(AgentError)
class AgentErrorAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'source', 'short_error', 'is_resolved')
    list_filter = ('is_resolved', 'source', 'created_at')
    search_fields = ('user__email', 'error_message', 'user_message')
    readonly_fields = ('user', 'source', 'user_message', 'error_message', 'traceback', 'created_at')
    list_editable = ('is_resolved',)
    date_hierarchy = 'created_at'

    def short_error(self, obj):
        return obj.error_message[:80]
    short_error.short_description = "Error"

    def has_add_permission(self, request):
        return False


class EscalationTicketForm(forms.ModelForm):
    """Staff decide from the ticket page; the extra fields are not model fields."""
    DECISIONS = (
        ("", "- no decision -"),
        ("approve", "Approve AI proposal"),
        ("edit", "Approve with my changes (discount % below)"),
        ("reject", "Reject"),
        ("takeover", "Take over the chat"),
        ("handback", "Resolve and hand back to AI"),
    )
    decision = forms.ChoiceField(choices=DECISIONS, required=False)
    discount_percent = forms.IntegerField(required=False, min_value=1, max_value=50,
                                          help_text="Only for 'Approve with my changes' on price-match tickets.")
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False,
                           label="Note for the customer (used by the AI in its reply)")
    reply_to_user = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False,
                                    help_text="Sent to the customer's chat as a 'Plantae team' message (takeover tickets).")

    class Meta:
        model = EscalationTicket
        fields = ("assigned_to",)


class TicketEventInline(admin.TabularInline):
    model = TicketEvent
    extra = 0
    can_delete = False
    readonly_fields = ("created_at", "kind", "source", "actor", "payload")
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(EscalationTicket)
class EscalationTicketAdmin(admin.ModelAdmin):
    form = EscalationTicketForm
    list_display = ("id", "created_at", "user", "category", "mode", "status", "assigned_to", "trigger")
    list_filter = ("status", "mode", "category", "trigger")
    search_fields = ("user__email", "summary", "staff_note")
    date_hierarchy = "created_at"
    inlines = [TicketEventInline]
    readonly_fields = ("user", "category", "mode", "status", "trigger", "summary", "details", "proposal",
                       "final_action", "staff_note", "recent_chat", "created_at", "resolved_at", "slack_ts")
    fieldsets = (
        (None, {"fields": ("user", "category", "mode", "status", "trigger", "assigned_to", "created_at", "resolved_at")}),
        ("What the customer needs", {"fields": ("summary", "details", "proposal", "recent_chat")}),
        ("Decide", {"fields": ("decision", "discount_percent", "note", "reply_to_user")}),
        ("Outcome", {"fields": ("final_action", "staff_note", "slack_ts")}),
    )

    def has_add_permission(self, request):
        return False

    def details(self, obj):
        return format_html("<ul>{}</ul>", format_html_join("", "<li><b>{}</b>: {}</li>", (obj.collected_info or {}).items()))

    def proposal(self, obj):
        proposed = dict(obj.proposed_action or {})
        facts = proposed.pop("facts", {})
        return format_html("<b>{}</b><br>{}<ul>{}</ul>", proposed.get("type", "-"),
                           ", ".join(f"{k}={v}" for k, v in proposed.items() if k != "type"),
                           format_html_join("", "<li>{}: {}</li>", facts.items()))

    def recent_chat(self, obj):
        msgs = ChatMessage.objects.filter(user=obj.user).order_by("-timestamp")[:15][::-1]
        return format_html("<div style='max-height:300px;overflow:auto'>{}</div>", format_html_join(
            "", "<p><b>[{}]</b> {} <small>{}</small></p>",
            ((m.role, m.message, m.timestamp.strftime("%Y-%m-%d %H:%M")) for m in msgs)))

    def save_model(self, request, obj, form, change):
        # Only assigned_to is editable; status etc. are owned by the service layer.
        obj.save(update_fields=["assigned_to", "updated_at"])
        data = form.cleaned_data
        decision, note, reply = data.get("decision"), data.get("note") or "", data.get("reply_to_user") or ""
        try:
            if decision in ("approve", "edit", "reject"):
                payload = {"action": decision, "note": note}
                if decision == "edit" and data.get("discount_percent"):
                    payload["params"] = {"discount_percent": data["discount_percent"]}
                hitl.resolve_ticket(obj.pk, payload, actor=request.user, source="admin")
                self.message_user(request, f"Decision '{decision}' sent. The AI will reply to the customer shortly.")
            elif decision == "takeover":
                hitl.start_takeover(obj.pk, actor=request.user, source="admin")
            if reply:
                obj.refresh_from_db()
                hitl.post_staff_message(obj, reply, actor=request.user, source="admin")
            if decision == "handback":
                hitl.end_takeover(obj.pk, actor=request.user, source="admin", note=note)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)


admin.site.register(ChatMessage, UserChatSummaryAdmin)
admin.site.register(ChatSession)
admin.site.register(ChatImage)