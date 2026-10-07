from django.conf import settings


def chat_widget(request):
    """Version string appended to the chat widget's static URLs (cache busting)."""
    return {"CHAT_WIDGET_VERSION": settings.CHAT_WIDGET_VERSION}
