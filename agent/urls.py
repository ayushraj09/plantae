from django.urls import path
from .views import ask_agent, clear_chat, get_chat_history, stt, tts, greet_agent, handle_variation_selection, chat_updates, request_human
from .views_slack import slack_interactions, slack_events

urlpatterns = [
    path('ask/', ask_agent, name='ask-agent'),
    path('clear_chat/', clear_chat, name='clear_chat'),
    path('get_chat_history/', get_chat_history, name='get_chat_history'),
    path('stt/', stt, name='stt'),
    path('tts/', tts, name='tts'),
    path('greet/', greet_agent, name='greet-agent'),
    path('variation_selection/', handle_variation_selection, name='handle_variation_selection'),
    path('updates/', chat_updates, name='chat_updates'),
    path('escalate/', request_human, name='request_human'),
    path('slack/interactions/', slack_interactions, name='slack_interactions'),
    path('slack/events/', slack_events, name='slack_events'),
]