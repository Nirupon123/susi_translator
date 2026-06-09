document.addEventListener('DOMContentLoaded', () => {

    // 1. Embed the YouTube Video
    const ytPlayer = document.getElementById('yt-player');

    const extractYtId = (url) => {
        const match = url.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([^&?]+)/);
        return match ? match[1] : null;
    };

    if (VIDEO_URL) {
        const ytId = extractYtId(VIDEO_URL);
        if (ytId) {
            ytPlayer.src = `https://www.youtube.com/embed/${ytId}?autoplay=1&mute=1`;
        } else {
            console.error("Invalid YouTube URL provided");
            ytPlayer.parentElement.innerHTML = '<div style="padding: 40px; text-align: center; color: #ef4444;">Invalid YouTube URL. Cannot load video.</div>';
        }
    }

    // 2. SSE Connection — viewer-driven, reconnects when language changes
    const captionsBox = document.getElementById('captions-box');
    const statusText = document.getElementById('connection-status');
    const pulseDot = document.querySelector('.pulse-dot');
    const langSelect = document.getElementById('viewer-lang-select');

    // Restore previously chosen language from localStorage (per-room preference)
    const savedLang = localStorage.getItem(`susi_lang_${TENANT_ID}`);
    if (savedLang) langSelect.value = savedLang;

    let eventSource = null;
    let lastChunkId = 0;

    function buildSseUrl(targetLang) {
        let url = `/api/v1/translate/stream?tenant_id=${TENANT_ID}&source=youtube&last_chunk_id=${lastChunkId}`;
        if (targetLang) url += `&target_lang=${encodeURIComponent(targetLang)}`;
        return url;
    }

    function connect() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }

        const targetLang = langSelect.value;
        statusText.innerText = 'Connecting...';
        pulseDot.classList.remove('connected', 'error');

        eventSource = new EventSource(buildSseUrl(targetLang));

        eventSource.onopen = () => {
            statusText.innerText = targetLang
                ? `Connected — translating to ${langSelect.options[langSelect.selectedIndex].text}`
                : 'Connected — transcript only';
            pulseDot.classList.add('connected');
        };

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            // Clear default placeholder on first real data
            const systemMsg = document.querySelector('.system-msg');
            if (systemMsg) systemMsg.remove();

            if (data.status === 'connected') return;

            if (data.status === 'error') {
                statusText.innerText = 'Stream Error';
                pulseDot.classList.remove('connected');
                pulseDot.classList.add('error');
                return;
            }

            // Track the highest chunk we've received for reconnect continuity
            const chunkInt = parseInt(data.chunk_id, 10);
            if (!isNaN(chunkInt) && chunkInt > lastChunkId) {
                lastChunkId = chunkInt;
            }

            // 3. Render transcript + translation blocks
            let block = document.getElementById(`chunk-${data.chunk_id}`);

            if (!block) {
                block = document.createElement('div');
                block.id = `chunk-${data.chunk_id}`;
                block.className = 'caption-block';

                const transcriptEl = document.createElement('p');
                transcriptEl.className = 'transcript-text';

                const translationEl = document.createElement('p');
                translationEl.className = 'translation-text';

                block.appendChild(transcriptEl);
                block.appendChild(translationEl);
                captionsBox.appendChild(block);
            }

            block.querySelector('.transcript-text').innerText = data.transcript;
            const translEl = block.querySelector('.translation-text');
            if (data.translation) {
                translEl.innerText = data.translation;
                translEl.style.display = '';
            } else {
                translEl.style.display = 'none';
            }

            // Auto-scroll to bottom
            captionsBox.scrollTop = captionsBox.scrollHeight;
        };

        eventSource.onerror = () => {
            statusText.innerText = 'Connection Lost. Reconnecting...';
            pulseDot.classList.remove('connected');
        };
    }

    // Initial connection
    connect();

    // Reconnect when viewer picks a different language.
    // We keep lastChunkId so they don't re-receive all old chunks,
    // but existing rendered blocks stay on screen for context.
    langSelect.addEventListener('change', () => {
        const chosen = langSelect.value;
        localStorage.setItem(`susi_lang_${TENANT_ID}`, chosen);
        connect();
    });

    // 4. Clear Button
    document.getElementById('clear-btn').addEventListener('click', () => {
        captionsBox.innerHTML = '';
    });
});