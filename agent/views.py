from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from .models import ChatMessage, ChatImage
from .langgraph.agent import run_supervisor_agent, clear_user_memory
import json, os
from django.views.decorators.http import require_POST
import logging
from elevenlabs.client import ElevenLabs
from dotenv import load_dotenv
from django.core.cache import cache
from langchain_core.messages import HumanMessage, AIMessage
from django.utils import timezone
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
    # Get all images for this user
    image_qs = ChatImage.objects.filter(user=request.user).order_by("uploaded_at")
    images = [
        {
            "url": img.image.url,
            "timestamp": img.uploaded_at.strftime("%Y-%m-%d %H:%M:%S")
        }
        for img in image_qs
    ]
    return JsonResponse({
        "messages": messages,
        "images": images,
        "user_name": request.user.full_name()  # Add user name to response
    })

@csrf_exempt
@login_required(login_url='login')
def ask_agent(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Invalid request method."}, status=405)

    try:
        # Unified input parsing
        resume_data = None
        message = ""
        image = None
        save_only = False
        data = None
        content_type = request.content_type or ''
        if content_type.startswith('multipart/form-data'):
            message = request.POST.get("message", "")
            image = request.FILES.get("image")
            # Validate image type/size if present
            if image:
                if not image.content_type.startswith('image/'):
                    return JsonResponse({"error": "Invalid file type. Only images are allowed."}, status=400)
                if image.size > 5 * 1024 * 1024:
                    return JsonResponse({"error": "Image file too large (max 5MB)."}, status=400)
            if 'resume_data' in request.FILES:
                resume_data = json.loads(request.FILES['resume_data'].read().decode())
            elif 'resume_data' in request.POST:
                resume_data = json.loads(request.POST['resume_data'])
            save_only = request.POST.get('save_only', 'false') == 'true'
        elif content_type == 'application/json':
            data = json.loads(request.body)
            message = data.get("message", "")
            resume_data = data.get('resume_data')
            save_only = data.get('save_only', False)
        else:
            return JsonResponse({"error": "Unsupported content type."}, status=400)

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

        # Save only mode (for agent messages)
        if save_only:
            ChatMessage.objects.create(user=request.user, role="agent", message=message)
            return JsonResponse({"response": message, "interrupt": False, "saved_only": True})

        # Fetch full conversation history for context
        chat_history_qs = ChatMessage.objects.filter(user=request.user).order_by("timestamp")
        messages = []
        for msg in chat_history_qs:
            if msg.role == "user":
                messages.append(HumanMessage(content=msg.message))
            else:
                messages.append(AIMessage(content=msg.message))
        # Add the new user message to the context
        messages.append(HumanMessage(content=message))

        # Run agent logic with full context
        if resume_data is not None:
            result = run_supervisor_agent(user_id, message, thread_id=None, resume_data=resume_data, messages=messages)
        elif image:
            result = run_supervisor_agent(user_id, message, thread_id=None, image_file=image, messages=messages)
        else:
            result = run_supervisor_agent(user_id, message, thread_id=None, messages=messages)

        # Handle interrupt response
        if result.get("interrupt", False):
            ChatMessage.objects.create(user=request.user, role="user", message=message)
            return JsonResponse({
                "interrupt": True,
                "interrupt_data": result["interrupt_data"],
                "response": result["response"]
            })
        else:
            reply = result["response"]
            ChatMessage.objects.create(user=request.user, role="user", message=message)
            ChatMessage.objects.create(user=request.user, role="agent", message=reply)
            if message:
                cache.set(limit_key, message_count + 1, None)
            return JsonResponse({"response": reply, "interrupt": False})

    except Exception as e:
        logging.exception("Error in ask_agent")
        return JsonResponse({"response": f"Sorry, there was an error: {str(e)}", "interrupt": False}, status=500)

@csrf_exempt
@require_POST
@login_required(login_url='login')
def handle_variation_selection(request):
    """
    Handle variation selection from frontend and resume the agent execution.
    """
    try:
        data = json.loads(request.body)
        user_id = request.user.id
        selected_variations = data.get("variations", {})
        
        # Resume the agent with the selected variations
        result = run_supervisor_agent(
            user_id=user_id, 
            message="", 
            thread_id=None, 
            resume_data=selected_variations
        )
        
        if result.get("interrupt", False):
            return JsonResponse({
                "interrupt": True,
                "interrupt_data": result["interrupt_data"],
                "response": result["response"]
            })
        else:
            reply = result["response"]
            
            # Save agent response to DB
            ChatMessage.objects.create(user=request.user, role="agent", message=reply)
            
            return JsonResponse({
                "response": reply,
                "interrupt": False
            })
            
    except Exception as e:
        print(f"Error handling variation selection: {str(e)}")
        return JsonResponse({
            "response": "Sorry, there was an error processing your selection. Please try again.",
            "interrupt": False
        }, status=500)

@csrf_exempt
@login_required(login_url='login')
def clear_chat(request):
    try:
        # Delete all messages for this user
        deleted_count = ChatMessage.objects.filter(user=request.user).delete()
        # Delete all images for this user
        deleted_images = ChatImage.objects.filter(user=request.user).delete()
        # Clear agent memory for this user
        thread_id = f"user_{request.user.id}"
        clear_user_memory(request.user.id, thread_id=thread_id)
        return JsonResponse({
            "success": True, 
            "deleted_count": deleted_count[0] if deleted_count else 0,
            "deleted_images": deleted_images[0] if deleted_images else 0
        })
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
        logging.exception("TTS error")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
@login_required(login_url='login')
def greet_agent(request):
    try:
        if request.method == "POST":
            user = request.user
            # Use full name if available, else first_name, else username, else 'User'
            name = getattr(user, 'full_name', None)
            if callable(name):
                name = name()
            if not name:
                name = getattr(user, 'first_name', None)
            if not name:
                name = getattr(user, 'username', None)
            if not name:
                name = 'User'
            greet_msg = f"Hey {name}, this is your personal PLANTAE assistant. How can I assist you today?"

            # Always save the greet message to chat history
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