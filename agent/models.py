from django.db import models
from django.conf import settings
# Create your models here.
class ChatMessage(models.Model):
    user = models.ForeignKey('accounts.Account', on_delete=models.CASCADE)
    role = models.CharField(max_length=10)  # 'user', 'agent' or 'staff'
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    # Set when the message belongs to a human-in-the-loop escalation.
    ticket = models.ForeignKey('EscalationTicket', on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_messages')
    # Staff member who wrote the message (role == 'staff').
    author = models.ForeignKey('accounts.Account', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_chat_messages')

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


class EscalationTicket(models.Model):
    """A conversation the AI agent handed over to a human.

    ``assist`` tickets pause a dedicated LangGraph thread (``graph_thread_id``)
    until staff approve, edit or reject the AI's proposed action.
    ``takeover`` tickets mute the AI and relay messages between the user and staff.
    """
    CATEGORY_CHOICES = (
        ('price_match', 'Price match / better deal'),
        ('bulk_order', 'Bulk or custom order'),
        ('cancellation', 'Order cancellation'),
        ('damaged_item', 'Damaged / wrong item'),
        ('payment_issue', 'Payment issue'),
        ('delivery', 'Delivery issue'),
        ('human_request', 'Asked for a human'),
        ('complaint', 'Complaint'),
        ('other', 'Other'),
    )
    MODE_ASSIST = 'assist'
    MODE_TAKEOVER = 'takeover'
    MODE_CHOICES = (
        (MODE_ASSIST, 'Staff approve AI proposal'),
        (MODE_TAKEOVER, 'Staff chat with user'),
    )
    STATUS_OPEN = 'open'
    STATUS_AWAITING = 'awaiting_staff'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_TAKEOVER = 'in_takeover'
    STATUS_RESOLVED = 'resolved'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = (
        (STATUS_OPEN, 'Open'),
        (STATUS_AWAITING, 'Awaiting staff'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_TAKEOVER, 'In takeover'),
        (STATUS_RESOLVED, 'Resolved'),
        (STATUS_EXPIRED, 'Expired'),
    )
    ACTIVE_STATUSES = (STATUS_OPEN, STATUS_AWAITING, STATUS_TAKEOVER)

    user = models.ForeignKey('accounts.Account', on_delete=models.CASCADE, related_name='escalation_tickets')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_ASSIST)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    trigger = models.CharField(max_length=50, blank=True)  # e.g. 'supervisor', 'keyword', 'repeated_errors'
    summary = models.TextField(blank=True)
    collected_info = models.JSONField(default=dict, blank=True)
    proposed_action = models.JSONField(default=dict, blank=True)
    final_action = models.JSONField(null=True, blank=True)
    staff_note = models.TextField(blank=True)
    graph_thread_id = models.CharField(max_length=64, blank=True)
    slack_channel = models.CharField(max_length=64, blank=True)
    slack_ts = models.CharField(max_length=32, blank=True, db_index=True)
    assigned_to = models.ForeignKey('accounts.Account', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    sla_reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = "Escalation Ticket"
        verbose_name_plural = "Escalation Tickets"

    def __str__(self):
        return f"#{self.pk} {self.get_category_display()} ({self.get_status_display()}) - {self.user}"

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES


class TicketEvent(models.Model):
    """Audit trail for everything that happens to an EscalationTicket."""
    SOURCE_CHOICES = (('ai', 'AI'), ('slack', 'Slack'), ('admin', 'Admin'), ('system', 'System'), ('user', 'User'))

    ticket = models.ForeignKey(EscalationTicket, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey('accounts.Account', on_delete=models.SET_NULL, null=True, blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    kind = models.CharField(max_length=20)  # created, posted, approved, edited, rejected, takeover, message, handback, resolved, sla, expired
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at',)

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] #{self.ticket_id} {self.kind} via {self.source}"
