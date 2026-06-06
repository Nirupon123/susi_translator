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

    // show api key field only for models that need it
    const needsApiKey = ['deepl', 'openai'].includes(model);
    apikeyGroup.classList.toggle('hidden', !needsApiKey);

    // show model size only for whisper 
    //right now only for whisper , in future will be changed
    const isWhisper = model === 'whisper_local';
    whisperSizeGroup.classList.toggle('hidden', !isWhisper);
}

function onTranslationModelChange() {
    const model = document.getElementById('translation-model').value;
    const apikeyGroup = document.getElementById('translation-apikey-group');

    // nllb_local needs no api key, deepl does
    const needsApiKey = model !== 'nllb_local';
    apikeyGroup.classList.toggle('hidden', !needsApiKey);
}

document.getElementById('config-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const streamUrl = document.getElementById('stream-url').value.trim();
    const sourceLang = document.getElementById('source-lang').value;
    const transcriptionModel = document.getElementById('transcription-model').value;
    const modelSize = document.getElementById('model-size').value;
    const transcriptionApiKey = document.getElementById('transcription-apikey').value.trim();
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
        transcription: transcriptionBlock,
    };

    // add translation block only if enabled
    if (translationEnabled) {
        const targetLang = document.getElementById('target-lang').value;
        const translationModel = document.getElementById('translation-model').value;
        const translationApiKey = document.getElementById('translation-apikey').value.trim();

        payload.translation = {
            provider_name: translationModel,
            source_lang: sourceLang,
            target_lang: targetLang,
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
                        // Models are loaded! Stop polling.
                        clearInterval(pollInterval);
                 
                        document.getElementById('loading-title').innerText = "Room Successfully Configured!";
                        document.getElementById('loading-subtitle').innerText = `Tenant ID: ${TENANT_ID} is ready for API connections.`;
                        
                        // Hide the spinning animation
                        document.querySelector('.spinner').style.display = 'none';
                        
                        // We DO NOT redirect anymore.
                        // window.location.href = `/stream/...`; 
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