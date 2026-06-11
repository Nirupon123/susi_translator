document.addEventListener('DOMContentLoaded', () => {

    //Embed the YouTube Video
    const ytPlayer = document.getElementById('yt-player');

    const extractYtId = (url) => {
        const match = url.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([^&?]+)/);
        return match ? match[1] : null;
    };

    const extractTwitchId = (url) => {
        const match = url.match(/(?:twitch\.tv\/)([^&?\/]+)/);
        return match ? match[1] : null;
    };

    const extractVimeoId = (url) => {
        const match = url.match(/(?:vimeo\.com\/)(?:channels\/(?:\w+\/)?|groups\/(?:[^\/]+\/)?videos\/|video\/|)(\d+)(?:|\/\?)/);
        return match ? match[1] : null;
    };

    if (VIDEO_URL) {
        const ytId = extractYtId(VIDEO_URL);
        const twitchId = extractTwitchId(VIDEO_URL);
        const vimeoId = extractVimeoId(VIDEO_URL);
        
        if (ytId) {
            ytPlayer.src = `https://www.youtube.com/embed/${ytId}?autoplay=1&mute=1`;
        } else if (twitchId) {
            const currentHost = window.location.hostname;
            ytPlayer.src = `https://player.twitch.tv/?channel=${twitchId}&parent=${currentHost}&autoplay=true&muted=true`;
        } else if (vimeoId) {
            ytPlayer.src = `https://player.vimeo.com/video/${vimeoId}?autoplay=1&muted=1`;
        } else {
            console.error("Invalid Video URL provided");
            ytPlayer.parentElement.innerHTML = '<div style="padding: 40px; text-align: center; color: #ef4444;">Invalid Video URL. Cannot load video.</div>';
        }
    }

    // SSE Connection — viewer-driven, reconnects when language changes
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

    // Clear Button
    document.getElementById('clear-btn').addEventListener('click', () => {
        captionsBox.innerHTML = '';
    });

    // Download Button
    document.getElementById('download-btn').addEventListener('click', () => {
        let content = "Event Transcript and Translations\n";
        content += "===================================\n\n";
        
        const blocks = captionsBox.querySelectorAll('.caption-block');
        if (blocks.length === 0) {
            alert("No transcripts available to download yet.");
            return;
        }

        blocks.forEach(block => {
            const tx = block.querySelector('.transcript-text').innerText.trim();
            const tlEl = block.querySelector('.translation-text');
            const tl = tlEl && tlEl.style.display !== 'none' ? tlEl.innerText.trim() : null;

            if (tx) {
                content += `[Original]: ${tx}\n`;
                if (tl) {
                    content += `[Translated]: ${tl}\n`;
                }
                content += "\n";
            }
        });

        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const lang = langSelect.value ? `_${langSelect.value}` : '';
        a.download = `room_${TENANT_ID}_transcript${lang}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });
});