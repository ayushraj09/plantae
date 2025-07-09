from django.contrib import admin
from django.db.models import Max
from .models import ChatMessage

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
        messages = ChatMessage.objects.filter(user=obj.user).order_by('timestamp')
        return " | ".join(f"[{m.role}] {m.message}" for m in messages)
    concatenated_messages.short_description = "All Messages"

    def latest_timestamp(self, obj):
        return obj.timestamp
    latest_timestamp.short_description = "Latest Message Time"

    def full_message_history(self, obj):
        messages = ChatMessage.objects.filter(user=obj.user).order_by('timestamp')
        return "\n".join(f"[{m.role}]: {m.message} :: ({m.timestamp.strftime('%Y-%m-%d %H:%M:%S')})" for m in messages)
    full_message_history.short_description = "Full Message History"
    full_message_history.allow_tags = False

admin.site.register(ChatMessage, UserChatSummaryAdmin)