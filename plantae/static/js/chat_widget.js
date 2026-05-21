let chatHistory = [];
let first_name = typeof USER_FIRST_NAME !== 'undefined' ? USER_FIRST_NAME : 'User';

// Get icon URLs from data attributes
function getIconUrl(id, attr) {
  const el = document.getElementById(id);
  return el ? el.getAttribute(attr) : '';
}

function getWidgetData(attr) {
  const widget = document.getElementById('plantae-chat-widget');
  return widget ? widget.getAttribute(attr) : '';
}

// Icon paths
const IMAGE_IDLE_SRC = getWidgetData('data-image-idle');
const IMAGE_ACTIVE_SRC = getWidgetData('data-image-active');
const SEND_IDLE_SRC = getWidgetData('data-send-idle');
const SEND_ACTIVE_SRC = getWidgetData('data-send-active');
const MIC_IDLE_SRC = getWidgetData('data-mic-idle');
const MIC_RECORDING_SRC = getWidgetData('data-mic-recording');
const TOGGLE_IDLE_SRC = getWidgetData('data-toggle-idle');
const TOGGLE_ACTIVE_SRC = getWidgetData('data-toggle-active');

function getCSRFToken() {
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
  return csrfToken;
}

// Fixed: Single renderChatHistory function (removed duplicate)
function renderChatHistory() {
  const chatBox = document.getElementById("plantae-chat-body");
  if (!chatBox) return;
  console.log('[ChatWidget] Rendering chat history:', chatHistory);
  chatBox.innerHTML = "";
  
  if (!chatHistory || chatHistory.length === 0) {
    // Show default greeting when no chat history
    const greetMsg = `Hey ${first_name}, this is your personal PLANTAE assistant. How can I assist you today?`;
    chatBox.innerHTML += `
      <div class="d-flex justify-content-start my-2">
        <div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;">${greetMsg}</div>
      </div>
    `;
  } else {
    // Render chat history (text and images)
    for (let i = 0; i < chatHistory.length; i++) {
      const item = chatHistory[i];
      const alignment = item.role === "user" ? "end" : "start";
      const bgClass = item.role === "user" ? "bg-primary text-white" : "bg-light";
      let messageHtml = "";
      if (item.type === "image") {
        messageHtml = `
          <div class="d-flex justify-content-${alignment} my-2">
            <div class="${bgClass} rounded-3 p-2 px-3" style="max-width: 70%;">
              <img src="${item.content}" alt="uploaded" style="max-width:120px; max-height:120px; border-radius:8px;">
            </div>
          </div>
        `;
      } else {
        messageHtml = `
          <div class="d-flex justify-content-${alignment} my-2">
            <div class="${bgClass} rounded-3 p-2 px-3" style="max-width: 70%;">${
              item.role === "agent" ? DOMPurify.sanitize(marked.parse(item.content)) : item.content
            }</div>
          </div>
        `;
      }
      chatBox.innerHTML += messageHtml;
    }
  }
  chatBox.scrollTop = chatBox.scrollHeight;
}

// Fixed: Added missing fetchAndRenderChatHistory function
function fetchAndRenderChatHistory() {
  fetch("/agent/get_chat_history/", {
    method: "GET",
    credentials: "same-origin",
    headers: {
      "X-CSRFToken": getCSRFToken()
    }
  })
  .then(res => res.json())
  .then(data => {
    // Merge messages and images by timestamp
    const messages = data.messages || [];
    const images = data.images || [];
    let merged = messages.map(m => ({...m, type: "text"}));
    merged = merged.concat(images.map(img => ({
      role: "user", // <-- change from "agent" to "user"
      content: img.url,
      timestamp: img.timestamp,
      type: "image"
    })));
    // Sort by timestamp
    merged.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    chatHistory = merged;
    renderChatHistory();
  })
  .catch(error => {
    chatHistory = [];
    renderChatHistory();
  });
}

// Image upload logic
const imageBtn = document.getElementById('imageBtn');
const imageIcon = document.getElementById('imageIcon');
const imageInput = document.getElementById('chat-image');
const imagePreview = document.getElementById('image-preview');
let selectedImage = null;

// Fixed: Added null checks for image elements
if (imageBtn && imageIcon && imageInput && imagePreview) {
  imageBtn.addEventListener('click', function() {
    imageIcon.src = IMAGE_ACTIVE_SRC;
    setTimeout(() => { imageIcon.src = IMAGE_IDLE_SRC; }, 2000);
    imageInput.click();
  });
  
  imageInput.addEventListener('change', function() {
    if (imageInput.files && imageInput.files[0]) {
      selectedImage = imageInput.files[0];
      const reader = new FileReader();
      reader.onload = function(e) {
        imagePreview.innerHTML = `<img src="${e.target.result}" alt="preview"><button id="remove-image-btn" title="Remove image">&times;</button>`;
        const removeBtn = document.getElementById('remove-image-btn');
        if (removeBtn) {
          removeBtn.onclick = function() {
            selectedImage = null;
            imageInput.value = "";
            imagePreview.innerHTML = '';
          };
        }
      };
      reader.readAsDataURL(selectedImage);
    } else {
      selectedImage = null;
      imagePreview.innerHTML = '';
    }
  });
}

const sendBtn = document.getElementById('sendBtn');
const sendIcon = document.getElementById('sendIcon');

function sendMessage() {
  const input = document.getElementById("chat-input");
  const chatBox = document.getElementById("plantae-chat-body");
  
  if (!input || !chatBox) {
    return;
  }
  
  const message = input.value.trim();
  if (!message && !selectedImage) return;
  if (selectedImage) {
    console.log('[ChatWidget] Uploading image:', selectedImage);
  }
  
  // Add user's message and image to UI
  let userMsgHtml = `<div class="d-flex justify-content-end my-2"><div class="bg-primary text-white rounded-3 p-2 px-3" style="max-width: 70%;">`;
  if (selectedImage) {
    const imgURL = URL.createObjectURL(selectedImage);
    userMsgHtml += `<img src='${imgURL}' alt='img' style='max-width:80px; max-height:80px; border-radius:8px; margin-bottom:4px; display:block;'>`;
  }
  userMsgHtml += `${message}</div></div>`;
  chatBox.innerHTML += userMsgHtml;
  
  // Clear input and image
  input.value = "";
  if (imageInput) {
    imageInput.value = "";
  }
  if (imagePreview) {
    imagePreview.innerHTML = '';
  }
  chatBox.scrollTop = chatBox.scrollHeight;
  
  // Add loading placeholder
  const loadingId = `agent-reply-${Date.now()}`;
  chatBox.innerHTML += `<div class="d-flex justify-content-start my-2" id="${loadingId}"><div class="bg-light text-muted rounded-3 p-2 px-3" style="max-width: 70%;"><em>Agent is typing...</em></div></div>`;
  chatBox.scrollTop = chatBox.scrollHeight;
  
  // Send to backend
  const formData = new FormData();
  formData.append('message', message);
  if (selectedImage) {
    formData.append('image', selectedImage);
  }
  
  // Set send icon to active
  if (sendIcon) sendIcon.src = SEND_ACTIVE_SRC;

  fetch("/agent/ask/", {
    method: "POST",
    headers: { "X-CSRFToken": getCSRFToken() },
    credentials: "same-origin",
    body: formData
  })
  .then(res => {
    console.log('[ChatWidget] /agent/ask/ response:', res);
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  })
  .then(data => {
    console.log('[ChatWidget] /agent/ask/ data:', data);
    const reply = data.response;
    const replyEl = document.getElementById(loadingId);
    if (replyEl) {
      replyEl.innerHTML = `<div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;">${DOMPurify.sanitize(marked.parse(reply))}</div>`;
      chatBox.scrollTop = chatBox.scrollHeight;
    }

    // Handle interrupt for variation selection
    if (data.interrupt && data.interrupt_data && data.interrupt_data.type === "variation_selection") {
      const { product_name, variation_dict, message } = data.interrupt_data;
      const variations = variation_dict; // for backward compatibility with rest of code
      // Improved Bootstrap styling for dropdown
      let variationHtml = `<div class="card shadow-sm border-0 mb-2" style="max-width: 100%; background: #f8f9fa;">`;
      variationHtml += `<div class="card-body p-3">`;
      variationHtml += `<h6 class="fw-bold mb-3">${message}</h6>`;
      variationHtml += `<form class="row g-2 align-items-center">`;
      for (const [varType, options] of Object.entries(variations)) {
        variationHtml += `<div class="col-12 col-md-6 mb-2">`;
        variationHtml += `<label class="form-label fw-semibold me-2" for="variation-select-${varType}">${varType.charAt(0).toUpperCase() + varType.slice(1)}:</label>`;
        variationHtml += `<select id="variation-select-${varType}" class="form-select form-select-sm d-inline-block w-auto ms-2">`;
        for (const opt of options) {
          variationHtml += `<option value="${opt}">${opt}</option>`;
        }
        variationHtml += `</select>`;
        variationHtml += `</div>`;
      }
      variationHtml += `<div class="col-12 mt-2">`;
      variationHtml += `<button id="variation-submit-btn" type="button" class="btn btn-success btn-sm px-4 py-2 fw-bold shadow-sm">Submit</button>`;
      variationHtml += `</div>`;
      variationHtml += `</form>`;
      variationHtml += `</div></div>`;
      chatBox.innerHTML += variationHtml;
      chatBox.scrollTop = chatBox.scrollHeight;

      document.getElementById('variation-submit-btn').onclick = function() {
        const selections = {};
        for (const varType of Object.keys(variations)) {
          selections[varType] = document.getElementById(`variation-select-${varType}`).value;
        }
        // Remove the variation dropdown card (the last .card in chatBox)
        const cards = chatBox.querySelectorAll('.card');
        if (cards.length > 0) {
          cards[cards.length - 1].remove();
        }
        // Show chosen variation as a normal chat message
        let chosenText = `Chosen variation for <b>${product_name}</b>:`;
        const varList = Object.entries(selections).map(([k, v]) => `${k.charAt(0).toUpperCase() + k.slice(1)}: <b>${v}</b>`).join(', ');
        chosenText += ' ' + varList;
        chatBox.innerHTML += `<div class="d-flex justify-content-start my-2"><div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;">${chosenText}</div></div>`;
        chatBox.scrollTop = chatBox.scrollHeight;
        // Save chosen variation message to chat history
        fetch("/agent/ask/", {
          method: "POST",
          headers: { "X-CSRFToken": getCSRFToken(), "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ message: chosenText, save_only: true })
        });
        // Send the selection as a resume to the backend
        const formData = new FormData();
        formData.append('resume_data', JSON.stringify(selections));
        fetch("/agent/ask/", {
          method: "POST",
          headers: { "X-CSRFToken": getCSRFToken() },
          credentials: "same-origin",
          body: formData
        })
        .then(res => {
          console.log('[ChatWidget] /agent/ask/ (resume) response:', res);
          return res.json();
        })
        .then(data => {
          console.log('[ChatWidget] /agent/ask/ (resume) data:', data);
          // Render the agent's follow-up response
          chatBox.innerHTML += `<div class="d-flex justify-content-start my-2"><div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;">${DOMPurify.sanitize(marked.parse(data.response))}</div></div>`;
          chatBox.scrollTop = chatBox.scrollHeight;
        })
        .catch(error => {
          console.error('[ChatWidget] Error submitting variation selections:', error);
        });
      };
    }
    
    // Only play TTS if last message was from STT
    if (lastMessageWasSTT && typeof playTTS === 'function') {
      playTTS(reply);
      lastMessageWasSTT = false; // Reset flag
    }

    // After message is sent and response is received, revert to idle icon
    if (sendIcon) sendIcon.src = SEND_IDLE_SRC;
  })
  .catch(error => {
    console.error('[ChatWidget] Error sending message:', error);
    const replyEl = document.getElementById(loadingId);
    if (replyEl) {
      replyEl.innerHTML = `<div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;"><em>Sorry, there was an error processing your request. Please try again.</em></div>`;
      chatBox.scrollTop = chatBox.scrollHeight;
    }

    // After message is sent and response is received, revert to idle icon
    if (sendIcon) sendIcon.src = SEND_IDLE_SRC;
  });
  
  selectedImage = null;
}

// Fixed: Added Enter key support for chat input
document.addEventListener('keydown', function(event) {
  if (event.key === 'Enter' && event.target.id === 'chat-input') {
    event.preventDefault();
    sendMessage();
  }
});

window.addEventListener("DOMContentLoaded", function() {
  fetchAndRenderChatHistory();
});

// Toggle chat widget
const chatWidget = document.getElementById('plantae-chat-widget');
const chatBox = document.getElementById('plantae-chat-box');
const chatToggle = document.getElementById('plantae-chat-toggle');
const chatClose = document.getElementById('plantae-chat-close');

// Fixed: Added null checks for chat elements
if (chatToggle && chatBox) {
  chatToggle.addEventListener('click', function() {
    console.log('Chat toggle button clicked');
    chatBox.classList.add('open');
    chatToggle.style.display = 'none';
    // Hide the tooltip when chat is opened
    if (helpTooltip) helpTooltip.style.display = 'none';
    
    setTimeout(() => {
      const chatInput = document.getElementById('chat-input');
      if (chatInput) {
        chatInput.focus();
      }
      // Scroll chat body to bottom after opening
      const chatBody = document.getElementById('plantae-chat-body');
      if (chatBody) {
        chatBody.scrollTop = chatBody.scrollHeight;
      }
    }, 200);

    // Check condition
    const shouldCallGreet = !chatHistory || chatHistory.length === 0;
    
    if (shouldCallGreet) {
      fetch("/agent/greet/", {
        method: "POST",
        headers: { "X-CSRFToken": getCSRFToken() },
        credentials: "same-origin"
      })
      .then(res => {
        if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
        }
        return res.json();
      })
      .then(data => {
        if (data.greet) {
          // Fixed: Update local chatHistory and render
          chatHistory.push({
            role: "agent",
            content: data.greet,
            timestamp: new Date().toISOString().slice(0, 19).replace('T', ' ')
          });
          renderChatHistory();
        }
      })
      .catch(error => {
        // Fallback to default greeting
        renderChatHistory();
      });
    }
  });
}

if (chatClose && chatBox && chatToggle) {
  chatClose.addEventListener('click', function() {
    chatBox.classList.remove('open');
    chatToggle.style.display = 'flex';
  });
}

// Clear chat
const clearBtn = document.getElementById('plantae-clear-btn');
if (clearBtn) {
  clearBtn.addEventListener('click', function() {
    fetch("/agent/clear_chat/", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken()
      }
    })
    .then(res => {
      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
      }
      return res.json();
    })
    .then(data => {
      if (data.success) {
        chatHistory = [];
        renderChatHistory();
      } else {
        alert('Failed to clear chat: ' + (data.error || 'Unknown error'));
      }
    })
    .catch(error => {
      alert('Error clearing chat: ' + error.message);
    });
  });
}

// STT - ElevenLabs
let mediaRecorder, audioChunks = [], silenceTimer = null, audioContext, analyser, microphone, dataArray, silenceDetectionActive = false;
let lastMessageWasSTT = false;

function startVoiceRecording() {
  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      
      mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
      mediaRecorder.onstop = () => {
        // Clean up
        stream.getTracks().forEach(track => track.stop());
        if (audioContext && audioContext.state !== "closed") {
          audioContext.close();
        }
        silenceDetectionActive = false;
        
        const voiceIcon = document.getElementById('voiceIcon');
        if (voiceIcon) {
          voiceIcon.src = MIC_IDLE_SRC;
        }
        
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('audio', audioBlob, 'audio.webm');
        
        fetch('/agent/stt/', {
          method: 'POST',
          headers: { "X-CSRFToken": getCSRFToken() },
          body: formData
        })
        .then(res => {
          if (!res.ok) {
            throw new Error(`HTTP error! status: ${res.status}`);
          }
          return res.json();
        })
        .then(data => {
          if (data.text) {
            const chatInput = document.getElementById('chat-input');
            if (chatInput) {
              chatInput.value = data.text;
              lastMessageWasSTT = true; // Set flag
              sendMessage();
            }
          } else {
            alert('STT error: ' + (data.error || 'Unknown error'));
          }
        })
        .catch(error => {
          console.error('STT error:', error);
          alert('STT error: ' + error.message);
        });
      };
      
      // Set up audio analysis
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      microphone = audioContext.createMediaStreamSource(stream);
      analyser = audioContext.createAnalyser();
      microphone.connect(analyser);
      dataArray = new Uint8Array(analyser.fftSize);
      silenceDetectionActive = true;
      
      function checkSilence() {
        if (!silenceDetectionActive) return;
        
        analyser.getByteTimeDomainData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          let val = (dataArray[i] - 128) / 128;
          sum += val * val;
        }
        let rms = Math.sqrt(sum / dataArray.length);
        
        if (rms < 0.01) {
          if (!silenceTimer) {
            silenceTimer = setTimeout(() => {
              if (mediaRecorder.state === 'recording') {
                mediaRecorder.stop();
              }
              silenceDetectionActive = false;
              silenceTimer = null;
            }, 1300);
          }
        } else {
          if (silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
          }
        }
        
        if (mediaRecorder.state === 'recording') {
          requestAnimationFrame(checkSilence);
        }
      }
      
      mediaRecorder.start();
      const voiceIcon = document.getElementById('voiceIcon');
      if (voiceIcon) {
        voiceIcon.src = MIC_RECORDING_SRC;
      }
      checkSilence();
    })
    .catch(error => {
      console.error('Error accessing microphone:', error);
      alert('Error accessing microphone: ' + error.message);
    });
}

// Fixed: Added null check for voice button
const voiceBtn = document.getElementById('voiceBtn');
const voiceIcon = document.getElementById('voiceIcon');

if (voiceBtn && voiceIcon) {
  voiceBtn.addEventListener('click', function() {
    startVoiceRecording();
  });
}

// TTS - ElevenLabs
function playTTS(text) {
  const formData = new FormData();
  formData.append('text', text);
  
  fetch('/agent/tts/', {
    method: 'POST',
    headers: { "X-CSRFToken": getCSRFToken() },
    body: formData
  })
  .then(res => {
    if (!res.ok) {
      throw new Error(`HTTP error! status: ${res.status}`);
    }
    return res.blob();
  })
  .then(blob => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.play().catch(error => {
      console.error('Error playing TTS audio:', error);
    });
  })
  .catch(error => {
    console.error('TTS error:', error);
  });
}

if (sendBtn && sendIcon) {
  sendBtn.addEventListener('click', function() {
    sendIcon.src = SEND_ACTIVE_SRC;
    setTimeout(() => { sendIcon.src = SEND_IDLE_SRC; }, 2000);
    sendMessage();
  });
}

const chatToggleIcon = document.getElementById('plantae-chat-toggle-icon');
const helpTooltip = document.getElementById('plantae-help-tooltip');

// For toggle button
if (chatToggle && chatToggleIcon) {
  chatToggle.addEventListener('mouseenter', function() {
    chatToggleIcon.src = TOGGLE_ACTIVE_SRC;
  });
  chatToggle.addEventListener('mouseleave', function() {
    chatToggleIcon.src = TOGGLE_IDLE_SRC;
  });
  chatToggle.addEventListener('focus', function() {
    chatToggleIcon.src = TOGGLE_ACTIVE_SRC;
  });
  chatToggle.addEventListener('blur', function() {
    chatToggleIcon.src = TOGGLE_IDLE_SRC;
  });
}