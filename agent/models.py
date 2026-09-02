from django.db import models
from django.conf import settings
# Create your models here.
class ChatMessage(models.Model):
    user = models.ForeignKey('accounts.Account', on_delete=models.CASCADE)
    role = models.CharField(max_length=10)  # 'user' or 'agent'
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} ({self.role}): {self.message[:30]}"
    
class ChatSession(ChatMessage):
    class Meta:
        proxy = True
        verbose_name = "Chat Session"
        verbose_name_plural = "Chat Sessions"

# New model for storing uploaded chat images
class ChatImage(models.Model):
    user = models.ForeignKey('accounts.Account', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='chat_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image by {self.user} at {self.uploaded_at}"


class AgentError(models.Model):
    """Records errors raised while handling an agent request so admins can
    review failures without exposing raw messages to end users."""
    user = models.ForeignKey('accounts.Account', on_delete=models.SET_NULL, null=True, blank=True)
    source = models.CharField(max_length=100, blank=True)  # e.g. 'ask_agent', 'run_supervisor_agent'
    user_message = models.TextField(blank=True)
    error_message = models.TextField()
    traceback = models.TextField(blank=True)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = "Agent Error"
        verbose_name_plural = "Agent Errors"

    def __str__(self):
        who = self.user.email if self.user else "anonymous"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {who}: {self.error_message[:60]}"
