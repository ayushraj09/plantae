from django.urls import path
from .views import ask_agent, clear_chat, get_chat_history, stt, tts, greet_agent, handle_variation_selection

urlpatterns = [
    path('ask/', ask_agent, name='ask-agent'),
    path('clear_chat/', clear_chat, name='clear_chat'),
    path('get_chat_history/', get_chat_history, name='get_chat_history'),
    path('stt/', stt, name='stt'),
    path('tts/', tts, name='tts'),
    path('greet/', greet_agent, name='greet-agent'),
    path('variation_selection/', handle_variation_selection, name='handle_variation_selection'),
]