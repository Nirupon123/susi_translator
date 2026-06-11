function toggleTranslation() {
    const checkbox = document.getElementById('translation-toggle');
    const section = document.getElementById('translation-section');
    if (checkbox.checked) {
        section.classList.remove('hidden');
    } else {
        section.classList.add('hidden');
    }
}

function onTranscriptionModelChange() {
    const model = document.getElementById('transcription-model').value;
    const apikeyGroup = document.getElementById('transcription-apikey-group');
    const whisperSizeGroup = document.getElementById('whisper-size-group');

    // Show API key field for any cloud API model (Groq, OpenAI, etc.)
    const needsApiKey = ['groq_whisper', 'deepl', 'openai'].includes(model);
    apikeyGroup.classList.toggle('hidden', !needsApiKey);

    // Show model size only for local Whisper
    const isWhisperLocal = model === 'whisper_local';
    whisperSizeGroup.classList.toggle('hidden', !isWhisperLocal);

    // Update the API key label to reflect which service
    const label = apikeyGroup.querySelector('label');
    if (model === 'groq_whisper') {
        label.textContent = 'Groq API Key';
    } else {
        label.textContent = 'API Key / HF Token';
    }
}

function onTranslationModelChange() {
    const model = document.getElementById('translation-model').value;
    const apikeyGroup = document.getElementById('translation-apikey-group');

    // Groq Llama and DeepL both need an API key; local NLLB does not.
    const needsApiKey = ['groq_llama', 'deepl'].includes(model);
    apikeyGroup.classList.toggle('hidden', !needsApiKey);

    // Update the API key label to reflect which service
    const label = apikeyGroup.querySelector('label');
    if (model === 'groq_llama') {
        label.textContent = 'Groq API Key';
    } else {
        label.textContent = 'API Key';
    }
}

// --- API Key Visual Masking ---
// After the user pastes/types a key and moves away from the field,
// we replace the visible text with asterisks so someone looking over
// their shoulder can't read the key. The real key is kept in a data
// attribute and used during form submission.
function _maskKeyField(inputEl) {
    inputEl.addEventListener('blur', () => {
        const realVal = inputEl.value;
        // Only update if the field actually has a value and it's not currently showing the masked dots
        if (realVal && inputEl.dataset.masked !== 'true') {
            inputEl.dataset.realKey = realVal;
            inputEl.value = '●'.repeat(Math.min(realVal.length, 24));
            inputEl.dataset.masked = 'true';
        }
    });
    inputEl.addEventListener('focus', () => {
        if (inputEl.dataset.masked === 'true') {
            inputEl.value = inputEl.dataset.realKey || '';
            inputEl.dataset.masked = 'false';
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    // Auto-redirect if the room was already configured (e.g. user pressed back button)
    // unless they explicitly arrived here via the Edit button.
    const urlParams = new URLSearchParams(window.location.search);
    if (!urlParams.has('edit')) {
        let rooms = JSON.parse(localStorage.getItem('susi_rooms') || '[]');
        let room = rooms.find(r => r.tenant_id === TENANT_ID);
        if (room && room.configured && room.videoUrl) {
            window.location.replace(`/stream/${TENANT_ID}?url=${encodeURIComponent(room.videoUrl)}`);
            return;
        }
    }

    _maskKeyField(document.getElementById('transcription-apikey'));
    _maskKeyField(document.getElementById('translation-apikey'));
});


document.getElementById('config-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const streamUrl = document.getElementById('stream-url').value.trim();
    const sourceLang = document.getElementById('source-lang').value;
    const transcriptionModel = document.getElementById('transcription-model').value;
    const modelSize = document.getElementById('model-size').value;
    const transcriptionApiKey = (() => {
        const el = document.getElementById('transcription-apikey');
        return el.dataset.realKey || el.value.trim();
    })();
    const translationEnabled = document.getElementById('translation-toggle').checked;

    // build transcription block
    const transcriptionBlock = {
        provider_name: transcriptionModel,
        config: { model_size: modelSize }
    };
    if (transcriptionApiKey) {
        transcriptionBlock.config.api_key = transcriptionApiKey;
    }

    // build configure payload
    const payload = {
        tenant_id: TENANT_ID,
        stream_url: streamUrl,
        transcription: transcriptionBlock,
    };

    // add translation block only if enabled
    if (translationEnabled) {
        const translationModel = document.getElementById('translation-model').value;
        const translationApiKey = (() => {
            const el = document.getElementById('translation-apikey');
            return el.dataset.realKey || el.value.trim();
        })();

        // target_lang is intentionally omitted — each viewer selects their own
        // language from the stream room. source_lang tells the model what the
        // speaker is speaking; target is decided per viewer at SSE connection time.
        payload.translation = {
            provider_name: translationModel,
            source_lang: sourceLang,
            config: {}
        };
        if (translationApiKey) {
            payload.translation.config.api_key = translationApiKey;
        }
    }

    try {
        const loadingOverlay = document.getElementById('loading-overlay');
        const submitBtn = document.querySelector('.start-btn');
        loadingOverlay.classList.remove('hidden');
        submitBtn.disabled = true;

        // Send the configuration to the server
        const response = await fetch('/api/v1/translate/configure', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (data.status === 'success') {
            // logic for loading screen and polling for readiness
            const pollInterval = setInterval(async () => {
                try {
                    const statusRes = await fetch(`/api/v1/translate/status/${TENANT_ID}`);
                    const statusData = await statusRes.json();

                    if (statusData.status === 'ready') {
                        // 3. Models are loaded! Stop polling and redirect.
                        clearInterval(pollInterval);
                        document.getElementById('loading-title').innerText = "Models Loaded!";
                        document.getElementById('loading-subtitle').innerText = "Entering Stream Room...";
                        setTimeout(() => {
                            let rooms = JSON.parse(localStorage.getItem('susi_rooms') || '[]');
                            rooms = rooms.map(r => {
                                if (r.tenant_id === TENANT_ID) {
                                    r.configured = true;
                                    r.videoUrl = streamUrl;
                                }
                                return r;
                            });
                            localStorage.setItem('susi_rooms', JSON.stringify(rooms));

                            window.location.replace(`/stream/${TENANT_ID}?url=${encodeURIComponent(streamUrl)}`);
                        }, 500);
                    }
                } catch (err) {
                    console.error("Polling error", err);
                }
            }, 1000);

        } else {
            loadingOverlay.classList.add('hidden');
            submitBtn.disabled = false;
            alert('Configuration failed: ' + data.message);
        }
    } catch (error) {
        document.getElementById('loading-overlay').classList.add('hidden');
        document.querySelector('.start-btn').disabled = false;
        alert('Network Error: Could not reach the translation server.');
}
});