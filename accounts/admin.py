from django.contrib import admin
from django.core.cache import cache
from .models import Account, UserProfile
from agent.models import ChatMessage
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html

# Admin action to reset chat limits
@admin.action(description="Reset chat message limit for selected users")
def reset_chat_limit(modeladmin, request, queryset):
    for user in queryset:
        cache.delete(f"chat_limit_user_{user.id}")
        cache.delete(f"chat_blocked_{user.id}")
        # Optionally clear old messages to avoid confusion
        ChatMessage.objects.filter(user=user).delete()
    modeladmin.message_user(request, "Chat limits reset for selected users.")

class AccountAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'is_active')
    list_display_links = ('email', 'first_name', 'last_name')
    readonly_fields = ('last_login', 'date_joined')
    ordering = ('-date_joined',)
    list_filter = ('is_active',)
    actions = [reset_chat_limit]
    fieldsets = (
        (None, {'fields': ('email', 'first_name', 'last_name', 'password')}),
    )

class UserProfileAdmin(admin.ModelAdmin):
    def thumbnail(self, object):
        return format_html('<img src="{}" width="30" style="border-radius:50%;">'.format(object.profile_picture.url))
    thumbnail.short_description = 'Profile Picture'
    list_display = ('thumbnail', 'user', 'city', 'state', 'country')

admin.site.register(Account, AccountAdmin)
admin.site.register(UserProfile, UserProfileAdmin)
