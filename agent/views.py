from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from .models import ChatMessage
from .langgraph.agent import run_supervisor_agent, clear_user_memory, get_conversation_history
import json, os
from django.views.decorators.http import require_POST
import logging
from elevenlabs.client import ElevenLabs
from dotenv import load_dotenv
from django.utils import timezone
from django.core.cache import cache
load_dotenv()
elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Create your views here.

@login_required(login_url='login')
def chat_interface(request):
    name = request.user.full_name
    # Get all messages for this user
    chat_history_qs = ChatMessage.objects.filter(user=request.user).order_by("timestamp")
    chat_history = [
        {"role": msg.role, "message": msg.message, "timestamp": msg.timestamp.strftime("%Y-%m-%d %H:%M:%S")}
        for msg in chat_history_qs
    ]
    context = {
        'name': name,
        'chat_history': chat_history,
    }
    return render(request, "agent/chat.html", context)

@login_required(login_url='login')
def get_chat_history(request):
    # Get all messages for this user
    chat_history_qs = ChatMessage.objects.filter(user=request.user).order_by("timestamp")
    messages = [
        {
            "role": msg.role, 
            "content": msg.message, 
            "timestamp": msg.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }
        for msg in chat_history_qs
    ]
    return JsonResponse({
        "messages": messages,
        "user_name": request.user.full_name()  # Add user name to response
    })

@csrf_exempt
@login_required(login_url='login')
def ask_agent(request):
    if request.method == 'POST':
        if request.content_type.startswith('multipart/form-data'):
            message = request.POST.get("message", "")
            image = request.FILES.get("image")
        else:
            data = json.loads(request.body)
            message = data.get("message", "")
            image = None

        user_id = request.user.id
        limit_key = f"chat_limit_user_{user_id}"
        block_key = f"chat_blocked_{user_id}"

        # Check if user is already blocked
        if cache.get(block_key):
            return JsonResponse({"response": "You have reached the maximum of 10 messages and are now blocked from chatting."})

        # Get and check current count
        message_count = cache.get(limit_key, 0)
        if message_count >= 10:
            cache.set(block_key, True, None)  # Block permanently until reset
            return JsonResponse({"response": "You have reached the maximum of 10 messages and are now blocked from chatting."})

        try:
            print(f"Processing message: '{message}' for user {user_id}")

            if image:
                reply = run_supervisor_agent(user_id, message, thread_id=None, image_file=image)
            else:
                reply = run_supervisor_agent(user_id, message, thread_id=None)

            print(f"Agent response: '{reply}'")

            # Save to DB
            ChatMessage.objects.create(user=request.user, role="user", message=message)
            ChatMessage.objects.create(user=request.user, role="agent", message=reply)

            # Update rate limit counter
            cache.set(limit_key, message_count + 1, None)

            return JsonResponse({"response": reply})

        except Exception as e:
            print(f"Error: {str(e)}")
            return JsonResponse({"response": "Sorry, there was an error. Please try again."})

    return JsonResponse({"error": "Invalid request"}, status=400)

@csrf_exempt
@require_POST
@login_required(login_url='login')
def clear_chat(request):
    try:
        # Delete all messages for this user
        deleted_count = ChatMessage.objects.filter(user=request.user).delete()
        # Clear agent memory for this user (if needed)
        clear_user_memory(request.user.id, thread_id=None)
        return JsonResponse({"success": True, "deleted_count": deleted_count[0] if deleted_count else 0})
    except Exception as e:
        print(f"Error clearing chat: {str(e)}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)
    
@csrf_exempt
def stt(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    audio_file = request.FILES.get("audio")
    if not audio_file:
        return JsonResponse({"error": "No audio file provided"}, status=400)
    
    try:
        transcription = elevenlabs.speech_to_text.convert(
            file = audio_file,
            model_id="scribe_v1", # Model to use, for now only "scribe_v1" is supported
            tag_audio_events=True, # Tag audio events like laughter, applause, etc.
            language_code=['eng'], # Language of the audio file. If set to None, the model will detect the language automatically.
            diarize=True, # Whether to annotate who is speaking
        )
        return JsonResponse({"text": transcription.text})
    except Exception as e:
        logging.exception("STT error")
        return JsonResponse({"error": str(e)}, status=500)
    
@csrf_exempt
def tts(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    text = request.POST.get("text")
    if not text:
        return JsonResponse({"error": "No text provided"}, status=400)
    try:
        audio = elevenlabs.text_to_speech.convert(
            text=text,
            voice_id="cgSgspJ2msm6clMCkdW9",  # You can use any available voice_id
            model_id="eleven_flash_v2_5",
            output_format="mp3_44100_128",
        )
        return HttpResponse(audio, content_type="audio/mpeg")
    except Exception as e:
        logging.exception("STT error")
        import traceback
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
@login_required(login_url='login')
def greet_agent(request):
    try:
        if request.method == "POST":
            user = request.user
            greet_msg = f"Hey {user.first_name or 'User'}, this is your personal PLANTAE assistant. How can I assist you today?"

            # Check if any greet message exists for this user/role
            existing_greet = ChatMessage.objects.filter(
                user=user, role="agent", message__icontains="personal PLANTAE assistant"
            )
            if not existing_greet.exists():
                ChatMessage.objects.create(
                    user=user,
                    role="agent",
                    message=greet_msg,
                    timestamp=timezone.now()
                )
            return JsonResponse({"greet": greet_msg})
        return JsonResponse({"error": "POST only"}, status=405)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)