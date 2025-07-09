from django.db import models
from django.conf import settings
# Create your models here.
class ChatMessage(models.Model):
    user = models.ForeignKey('accounts.Account', on_delete=models.CASCADE)
    role = models.CharField(max_length=10)  # 'user' or 'agent'
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    # session_id = models.CharField(max_length=100, blank=True, null=True)  # Remove this field

    def __str__(self):
        return f"{self.user} ({self.role}): {self.message[:30]}"
    
class ChatSession(ChatMessage):
    class Meta:
        proxy = True
        verbose_name = "Chat Session"
        verbose_name_plural = "Chat Sessions"
