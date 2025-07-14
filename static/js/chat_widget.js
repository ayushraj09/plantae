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
    // Render chat history
    for (let i = 0; i < chatHistory.length; i++) {
      const item = chatHistory[i];
      const alignment = item.role === "user" ? "end" : "start";
      const bgClass = item.role === "user" ? "bg-primary text-white" : "bg-light";
      const messageHtml = `
        <div class="d-flex justify-content-${alignment} my-2">
          <div class="${bgClass} rounded-3 p-2 px-3" style="max-width: 70%;">${
            item.role === "agent" ? DOMPurify.sanitize(marked.parse(item.content)) : item.content
          }</div>
        </div>
      `;
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
  .then(res => {
    if (!res.ok) {
      throw new Error(`HTTP error! status: ${res.status}`);
    }
    return res.json();
  })
  .then(data => {
    chatHistory = data.messages || [];
    renderChatHistory();
  })
  .catch(error => {
    // Fallback to empty chat history
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
  
  // Set send icon to active (gif)
  if (sendIcon) sendIcon.src = SEND_ACTIVE_SRC;

  fetch("/agent/ask/", {
    method: "POST",
    headers: { "X-CSRFToken": getCSRFToken() },
    credentials: "same-origin",
    body: formData
  })
  .then(res => {
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  })
  .then(data => {
    // Handle interrupt response for variation selection
    if (data.interrupt && data.interrupt_data && data.interrupt_data.type === "variation_selection") {
      const replyEl = document.getElementById(loadingId);
      if (replyEl) {
        // Create variation selection UI
        const variationHtml = createVariationSelectionUI(data.interrupt_data);
        replyEl.innerHTML = `<div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;">${variationHtml}</div>`;
        chatBox.scrollTop = chatBox.scrollHeight;
      }
      
      // After message is sent and response is received, revert to idle icon
      if (sendIcon) sendIcon.src = SEND_IDLE_SRC;
      selectedImage = null;
      return;
    }
    
    const reply = data.response;
    const replyEl = document.getElementById(loadingId);
    if (replyEl) {
      replyEl.innerHTML = `<div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;">${DOMPurify.sanitize(marked.parse(reply))}</div>`;
      chatBox.scrollTop = chatBox.scrollHeight;
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
    console.error('Error sending message:', error);
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
  
  fetch("/agent/tts/", {
    method: "POST",
    headers: { "X-CSRFToken": getCSRFToken() },
    credentials: "same-origin",
    body: formData
  })
  .then(res => {
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.blob();
  })
  .then(blob => {
    const audio = new Audio(URL.createObjectURL(blob));
    audio.play();
  })
  .catch(error => {
    console.error("TTS error:", error);
  });
}

// Function to create variation selection UI
function createVariationSelectionUI(interruptData) {
  const productName = interruptData.product_name;
  const variations = interruptData.variations;
  const message = interruptData.message;
  
  let html = `
    <div class="variation-selection-container">
      <p class="mb-3"><strong>${message}</strong></p>
      <form id="variation-form" class="mb-3">
  `;
  
  // Create dropdowns for each variation category
  Object.keys(variations).forEach(category => {
    const values = variations[category];
    html += `
      <div class="form-group mb-3">
        <label for="${category}-select" class="font-weight-bold" style="margin-bottom: 8px; display: block;">
          Select ${category.charAt(0).toUpperCase() + category.slice(1)}
        </label>
        <select name="${category}" id="${category}-select" class="form-control" required style="max-width: 250px;">
          <option value="" disabled selected>Choose ${category}</option>
    `;
    
    values.forEach(value => {
      html += `<option value="${value.toLowerCase()}">${value}</option>`;
    });
    
    html += `
        </select>
      </div>
    `;
  });
  
  html += `
        <div class="d-flex gap-2">
          <button type="submit" class="btn btn-primary btn-sm">
            Continue
          </button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="cancelVariationSelection()">
            Cancel
          </button>
        </div>
      </form>
    </div>
  `;
  
  return html;
}

// Function to handle variation submission
function handleVariationSubmission(event) {
  event.preventDefault();
  
  const form = event.target;
  const formData = new FormData(form);
  const variations = {};
  
  // Collect all selected variations
  for (let [key, value] of formData.entries()) {
    if (value) {
      variations[key] = value;
    }
  }
  
  // Validate that all required variations are selected
  const selects = form.querySelectorAll('select[required]');
  let allSelected = true;
  selects.forEach(select => {
    if (!select.value) {
      allSelected = false;
      select.classList.add('is-invalid');
    } else {
      select.classList.remove('is-invalid');
    }
  });
  
  if (!allSelected) {
    alert('Please select all required variations.');
    return;
  }
  
  // Show loading state
  const submitBtn = form.querySelector('button[type="submit"]');
  const originalText = submitBtn.textContent;
  submitBtn.textContent = 'Processing...';
  submitBtn.disabled = true;
  
  // Send variation selection to backend
  fetch("/agent/variation_selection/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCSRFToken()
    },
    credentials: "same-origin",
    body: JSON.stringify({ variations: variations })
  })
  .then(res => {
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    return res.json();
  })
  .then(data => {
    // Handle response
    const variationContainer = form.closest('.variation-selection-container');
    const parentDiv = variationContainer.parentElement;
    
    if (data.interrupt) {
      // Handle another interrupt (shouldn't happen in normal flow)
      parentDiv.innerHTML = `<div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;">${data.response}</div>`;
    } else {
      // Show success response
      parentDiv.innerHTML = `<div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;">${DOMPurify.sanitize(marked.parse(data.response))}</div>`;
    }
    
    // Scroll to bottom
    const chatBox = document.getElementById("plantae-chat-body");
    if (chatBox) {
      chatBox.scrollTop = chatBox.scrollHeight;
    }
  })
  .catch(error => {
    console.error("Error submitting variations:", error);
    submitBtn.textContent = originalText;
    submitBtn.disabled = false;
    alert('Error submitting variations. Please try again.');
  });
}

// Function to cancel variation selection
function cancelVariationSelection() {
  const variationContainer = document.querySelector('.variation-selection-container');
  if (variationContainer) {
    const parentDiv = variationContainer.parentElement;
    parentDiv.innerHTML = `<div class="bg-light rounded-3 p-2 px-3" style="max-width: 70%;"><em>Variation selection cancelled.</em></div>`;
    
    // Scroll to bottom
    const chatBox = document.getElementById("plantae-chat-body");
    if (chatBox) {
      chatBox.scrollTop = chatBox.scrollHeight;
    }
  }
}

// Add event listener for variation form submission
document.addEventListener('submit', function(event) {
  if (event.target.id === 'variation-form') {
    handleVariationSubmission(event);
  }
});

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