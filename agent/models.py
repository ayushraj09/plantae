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
