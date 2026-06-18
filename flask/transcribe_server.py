from flask import Flask, request, jsonify, abort, redirect, url_for, render_template, Response
from flask_restx import Api, Resource, fields
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity, verify_jwt_in_request
from flask_bcrypt import Bcrypt
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename
from typing import Optional
import numpy as np
import threading
import logging
import collections
import logging
import io
import base64
import soundfile as sf
from supertonic import TTS
import json
import os
import queue
import signal
import sys
import threading
import time
import uuid


from dataclasses import dataclass
import subprocess
import signal
from datetime import timedelta
from dotenv import load_dotenv

from auth.routes import auth_bp, bcrypt
from auth.decorators import organizer_required
from flask_admin import Admin
from auth.admin_panel import SecureModelView, SecureAdminIndexView



from providers.registry import ProviderRegistry

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str) -> list:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

app = Flask(__name__)
api = Api(app, version='1.0', title='Transcription API',
          description='A simple Transcription API', doc='/swagger')

# CORS_ALLOWED_ORIGINS is a comma-separated list. Default is local-dev only.
# Use "*" explicitly if (and only if) you really want to allow any origin.
_cors_origins = _env_csv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5040,http://127.0.0.1:5040",
)
CORS(app, resources={r"/*": {"origins": _cors_origins}})  # type: ignore[arg-type]  # flask-cors 6.x stubs are outdated
logger.info(f"CORS allowed origins: {_cors_origins}")

# --- Database, Auth, JWT ---
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///susi.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "change-me")
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False  # set True in production (HTTPS only)
app.config["JWT_COOKIE_CSRF_PROTECT"] = False
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)

from auth.models import db
db.init_app(app)
JWTManager(app)
bcrypt.init_app(app)

# Register the auth blueprint (/auth/login, /auth/signup, /auth/api/*)
app.register_blueprint(auth_bp)

# Create DB tables if they don't exist yet (safe no-op if already created)
with app.app_context():
    db.create_all()


# Initialize Flask-Admin
from flask_admin.theme import Bootstrap4Theme
admin = Admin(app, name='SUSI Admin', theme=Bootstrap4Theme(swatch='flatly'), url='/admin', index_view=SecureAdminIndexView())
from auth.models import Organizer
admin.add_view(SecureModelView(Organizer, db, name="Users/Organizers"))


# Load all provider plugins — registers whisper_local, nllb_local
# into the ProviderRegistry factory table before any request arrives.
import providers.plugins  # noqa: F401  (side-effect import)


# Shared in-memory state

registry = ProviderRegistry()

# transcripts:  tenant_id -> { chunk_id -> {'transcript': str} }
transcriptd = {}
transcripts_lock = threading.Lock()

grabber_processes = {}  # tenant_id -> subprocess.Popen
grabber_lock = threading.Lock()

# FIFO queue of pending audio chunks awaiting transcription.
audio_stack = queue.Queue()

# Per-source "latest session" registry
VALID_SOURCES = {"mic", "file", "url", "stdin", "youtube"}
latest_session_by_source: dict[str, Optional[tuple[str, float]]] = {s: None for s in VALID_SOURCES}  # source -> (tenant_id, created_ts) or None
session_lock = threading.Lock()
SESSION_TTL_SECONDS = int(os.getenv('SESSION_TTL_SECONDS', '7200'))


# --- TTS HELPER ---
supertonic_tts = TTS(auto_download=True)

SUPERTONIC_SUPPORTED_LANGS = {
    "ar", "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", 
    "de", "el", "hi", "hu", "id", "it", "ja", "ko", "lv", "lt", 
    "pl", "pt", "ro", "ru", "sk", "sl", "es", "sv", "tr", "uk", "vi"
}

# Map specific languages to different Supertonic voice styles for variety
TTS_VOICE_STYLES = {
    "en": "M1",
    "de": "M2",
    "fr": "F1",
    "es": "F2",
    "hi": "M3",
    "ar": "M4",
    "pt": "F3",
    "ru": "F4",
    "ja": "F5",
    "ko": "M5",
    "it": "M1",
}

def generate_tts_sync(text, target_lang):
    if not text.strip():
        return None
    try:
        # Determine language (fallback to language-agnostic "na" if unsupported)
        lang_tag = target_lang if target_lang in SUPERTONIC_SUPPORTED_LANGS else "na"
        
        # Get voice style, fallback to F1 if not mapped
        style_name = TTS_VOICE_STYLES.get(target_lang, "F1")
        voice_style = supertonic_tts.get_voice_style(voice_name=style_name)
        
        wav, duration = supertonic_tts.synthesize(
            text=text, 
            lang=lang_tag, 
            voice_style=voice_style,
            total_steps=8,  # Default medium quality
            speed=1.0
        )
        
        # Supertonic outputs a numpy array. Convert to 16-bit PCM WAV.
        buf = io.BytesIO()
        sf.write(buf, wav.squeeze(), 44100, format='WAV', subtype='PCM_16')
        audio_bytes = buf.getvalue()
        
        return base64.b64encode(audio_bytes).decode('utf-8')
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return None


# Small helpers

def _parse_int_arg(args, name: str, default: Optional[int] = None, required: bool = False) -> Optional[int]:
    
    raw = args.get(name)
    if raw is None or raw == "":
        if required:
            abort(400, f"Missing required query parameter: {name}")
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        abort(400, f"Query parameter {name!r} must be an integer, got {raw!r}")


def _chunk_id_int(k):
   
    try:
        return int(k)
    except (TypeError, ValueError):
        return None


def _numeric_sorted_keys(transcripts, reverse: bool = False) -> list:
  
    pairs = []
    for k in transcripts.keys():
        n = _chunk_id_int(k)
        if n is not None:
            pairs.append((n, k))
    pairs.sort(reverse=reverse)
    return [k for _, k in pairs]


def _in_chunk_range(k, fromid: Optional[int], untilid: Optional[int]) -> bool:
    n = _chunk_id_int(k)
    return n is not None and fromid is not None and untilid is not None and fromid <= n <= untilid


def _resolve_tenant(args, default='0000'):
   
    explicit = args.get('tenant_id')
    if explicit:
        return explicit
    source = args.get('source')
    if source:
        if source not in VALID_SOURCES:
            abort(
                400,
                f"Invalid source '{source}'. "
                f"Must be one of: {sorted(VALID_SOURCES)}.",
            )
        now = time.time()
        with session_lock:
            entry = latest_session_by_source.get(source)
            if entry is None:
                return None
            tenant_id, created_ts = entry
            if now - created_ts > SESSION_TTL_SECONDS:
                # Expire stale session pointer.
                latest_session_by_source[source] = None
                return None
            return tenant_id
    return default




def _next_payload():
    
    tenant_id, chunk_id, audiob64 = audio_stack.get()
    while True:
        with audio_stack.mutex:
            has_newer = any(
                t == tenant_id and c == chunk_id
                for (t, c, _) in audio_stack.queue
            )
        if not has_newer:
            return tenant_id, chunk_id, audiob64
        # Current entry is stale; discard it (correctly accounted) and grab
        # the next one from the head.
        audio_stack.task_done()
        tenant_id, chunk_id, audiob64 = audio_stack.get()


def process_audio():
    while True:
        tenant_id, chunk_id, audiob64 = _next_payload()
        logger.debug(f"Queue length: {audio_stack.qsize()}")
        requeued = False
        try:
            # If the pipeline isn't ready yet (model still warming up),
            # put this chunk BACK on the queue and wait briefly.
            # This prevents losing file chunks that arrive before the model finishes loading.
            if not registry.is_pipeline_ready(tenant_id):
                logger.debug(f"Pipeline not ready for tenant {tenant_id}, requeueing chunk {chunk_id}")
                audio_stack.task_done()  # account for the get() above
                audio_stack.put((tenant_id, chunk_id, audiob64))
                requeued = True
                time.sleep(0.5)
                continue

            audio_data = base64.b64decode(audiob64)
            audio_int16 = np.frombuffer(audio_data, dtype=np.int16)

            if audio_int16.size == 0:
                logger.warning(f"Invalid audio data for chunk_id {chunk_id}")
                continue

            audio_float32 = audio_int16.astype(np.float32) / 32768.0
            if np.isnan(audio_float32).any():
                logger.warning(f"NaN values in audio array for chunk_id {chunk_id}")
                continue

            transcript = registry.transcribe(tenant_id, audio_float32)
            if transcript is None:
                logger.warning(f"Transcription provider unavailable for chunk_id {chunk_id}")
                continue

            if is_valid(transcript):
                logger.info(f"VALID transcript for chunk_id {chunk_id}: {transcript}")
                with transcripts_lock:
                    transcripts = transcriptd.get(tenant_id)
                    if not transcripts:
                        transcripts = {}
                        transcriptd[tenant_id] = transcripts

                    current_transcript = transcripts.get(chunk_id)
                    if current_transcript:
                        # buffer for the same chunk, so overwrite rather than concatenate.
                        current_transcript['transcript'] = transcript
                    else:
                        transcripts[chunk_id] = {'transcript': transcript}
            else:
                logger.warning(f"INVALID transcript for chunk_id {chunk_id}: {transcript}")

            # Periodic GC of stale tenants/chunks.
            clean_old_transcripts()

        except Exception:
            logger.error(f"Error processing audio chunk {chunk_id}", exc_info=True)
        finally:
            if not requeued:
                audio_stack.task_done()




# Check if the transcript is valid: Contains at least one alphanumeric character and no forbidden words
def is_valid(transcript):
    transcript_lower = transcript.lower()
    # Check for at least one alphanumeric character (supports all languages including non-Latin scripts)
    has_alpha_num = any(char.isalnum() for char in transcript)

    # Check for forbidden phrases (case insensitive)
    forbidden_phrases = {"click, click", "click click", "cough cough", "뉴", "스", "김", "수", "근", "입", "니", "다"}
    contains_forbidden_phrases = any(word in transcript_lower for word in forbidden_phrases)

    # Reject if the entire transcript exactly matches a forbidden string
    forbidden_strings = {"eh.", "you", "it's fine"}
    is_forbidden_string = any(word == transcript_lower for word in forbidden_strings)

    # Reject hallucinated outputs: a single repeated word taking up > 40 chars
    contains_long_words = any(len(word) > 40 for word in transcript.split())

    # Valid only if it has real content and none of the rejection criteria apply
    return has_alpha_num and not contains_forbidden_phrases and not is_forbidden_string and not contains_long_words


# Clean old transcripts: remove all chunks older than two hours and any tenants
def clean_old_transcripts():
    current_time_ms = int(time.time() * 1000)
    two_hours_ago_ms = current_time_ms - (2 * 60 * 60 * 1000)

    with transcripts_lock:
        empty_tenants = []
        # Snapshot the tenant ids before iterating; we mutate inside the loop.
        for tenant_id in list(transcriptd.keys()):
            transcripts = transcriptd.get(tenant_id)
            if not transcripts:
                empty_tenants.append(tenant_id)
                continue

            # Snapshot chunk ids; some chunk_ids may be non-numeric in principle, so we defensively skip those rather than crashing the worker thread.
            stale_chunks = []
            for chunk_id in list(transcripts.keys()):
                try:
                    if int(chunk_id) < two_hours_ago_ms:
                        stale_chunks.append(chunk_id)
                except (TypeError, ValueError):
                    # Unknown id format -> leave it alone.
                    continue

            for chunk_id in stale_chunks:
                transcripts.pop(chunk_id, None)

            if not transcripts:
                empty_tenants.append(tenant_id)

        for tenant_id in empty_tenants:
            transcriptd.pop(tenant_id, None)

def merge_and_split_transcripts(transcripts):
    """
    Take a ``{chunk_id: {'transcript': str}}`` mapping and produce a new
    mapping of the same shape where text has been re-flowed onto sentence
    boundaries (``.``, ``!``, ``?``).

    The output preserves chunk_ids from the input (a subset of them: only
    the chunk_ids at which a sentence boundary actually falls, plus the
    last chunk for any trailing fragment). Values are dicts with a
    ``'transcript'`` key so callers can use the same access pattern as
    the underlying ``transcriptd`` store.
    """
    sec = ".!?"
    merged = ""
    result = {}
    keys = list(transcripts.keys())
    for key in keys:
        raw = transcripts[key]
        text = ((raw.get('transcript') or '') if isinstance(raw, dict) else str(raw or '')).strip()

        if not merged:
            merged += text
        else:
            if len(text) > 1:
                merged += " " + text[0].lower() + text[1:]
            elif text:
                merged += " " + text

        # Drain every complete sentence currently in `merged` onto this key.
        while any(char in sec for char in merged):
            index = next(i for i, c in enumerate(merged) if c in sec)
            head = merged[:index + 1].strip()
            head = head[0].capitalize() + head[1:] if len(head) > 1 else head
            existing = result.get(key, {}).get('transcript')
            if existing:
                result[key] = {'transcript': existing + " " + head}
            else:
                result[key] = {'transcript': head}
            merged = merged[index + 1:].strip()

    # Any leftover (no terminal punctuation) attaches to the final input key.
    if merged and keys:
        last_key = keys[-1]
        existing = result.get(last_key, {}).get('transcript')
        if existing:
            result[last_key] = {'transcript': existing + " " + merged}
        else:
            result[last_key] = {'transcript': merged}

    return result



#flask-restx models


configure_input_model = api.model('ConfigureRequest', {
    'tenant_id': fields.String(required=True, description='Tenant ID for the session'),
    'provider_name': fields.String(required=True, description='Canonical name of the provider (deepl, whisper, openai)'),
    'config': fields.Raw(
        required=False,
        description=(
            'Nested provider-specific settings (e.g. {"api_key": "...", "model_size": "large"}). '
            'When present, these values are passed directly to the provider factory. '
            'Alternatively, settings may be supplied as top-level keys in the request body '
            '(legacy flat format); if "config" is present it takes precedence.'
        ),
    )
})

configure_response_model = api.model('ConfigureResponse', {
    'status': fields.String(description='Success or error status'),
    'message': fields.String(description='Status details')
})


transcribe_input_model = api.model('Transcribe', {
    'audio_b64': fields.String(required=True, description='Base64 encoded audio data'),
    'chunk_id': fields.String(required=True, description='ID of the audio chunk'),
    'tenant_id': fields.String(required=False, description='Tenant ID', default='0000')
})

transcribe_response_model = api.model('TranscribeAck', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'tenant_id': fields.String(description='Tenant ID'),
    'status': fields.String(description='processing flag')
})

transcript_response_model = api.model('Transcript', {
    'chunk_id': fields.String(description='ID of the audio chunk'),
    'transcript': fields.String(description='The transcribed text')
})

list_transcripts_response_model = api.model('ListTranscriptsResponse', {
    'transcripts': fields.List(fields.Nested(transcript_response_model), description='List of transcripts')
})

size_response_model = api.model('SizeResponse', {
    'size': fields.Integer(description='The number of transcripts')
})

session_input_model = api.model('SessionRequest', {
    'source': fields.String(
        required=True,
        description='Input source name; one of: mic, file, url, stdin, youtube',
        enum=sorted(VALID_SOURCES),
    ),
})

session_response_model = api.model('SessionResponse', {
    'tenant_id': fields.String(description='Server-minted tenant ID for this run'),
    'source': fields.String(description='Source name this session is registered under'),
})

@app.route('/api/v1/translate/upload_file', methods=['POST'])
def upload_file():
    if 'audio_file' not in request.files:
        return jsonify({"status": "error", "message": "No audio_file provided"}), 400
        
    file = request.files['audio_file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400
        
    if file:
        filename = secure_filename(file.filename)
        upload_dir = os.path.join(app.instance_path, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        
        return jsonify({
            "status": "success",
            "file_path": file_path
        })



@app.route('/api/v1/translate/configure', methods=['POST'])
def configure_provider():
    data = request.get_json(silent=True) or {}

    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return jsonify({"status": "error", "message": "Missing 'tenant_id'"}), 400

    transcription = data.get("transcription")
    translation = data.get("translation")

    if not transcription and not translation:
        return jsonify({
            "status": "error",
            "message": "At least one of 'transcription' or 'translation' must be provided.",
        }), 400

    try:
        registry.configure(
            tenant_id=tenant_id,
            transcription=transcription,
            translation=translation,
        )
        configured = []
        if transcription:
            configured.append(f"transcription='{transcription.get('provider_name')}'")
        if translation:
            configured.append(f"translation='{translation.get('provider_name')}'")

        stream_type = data.get("stream_type", "youtube")
        stream_url = data.get("stream_url")
        if stream_url or stream_type == "mic":
            with grabber_lock:
                old_proc = grabber_processes.pop(tenant_id, None)
                if old_proc:
                    try:
                        logger.info(f"Killing existing audio_grabber for tenant {tenant_id} before respawning")
                        os.killpg(os.getpgid(old_proc.pid), signal.SIGTERM)
                        old_proc.wait(timeout=3)
                    except Exception as e:
                        logger.warning(f"Failed to cleanly kill old grabber for {tenant_id}: {e}")

            with transcripts_lock:
                transcriptd.pop(tenant_id, None)

            with audio_stack.mutex:
                audio_stack.queue = type(audio_stack.queue)(
                    [item for item in audio_stack.queue if item[0] != tenant_id]
                )

            if stream_type != "mic":
                logger.info(f"Spawning audio_grabber for tenant {tenant_id} with source {stream_type}")
                cmd = [
                    sys.executable,
                    "audio_grabber.py",
                    "--tenant", tenant_id,
                    stream_type
                ]
                
                if stream_type == "youtube":
                    cmd.extend(["--url", stream_url])
                    cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "youtubecookies.txt")
                    if os.path.exists(cookies_path):
                        logger.info(f"Using YouTube cookies file found at {cookies_path}")
                        cmd.extend(["--cookies", cookies_path])
                elif stream_type == "url":
                    cmd.extend(["--url", stream_url])
                elif stream_type == "file":
                    cmd.extend(["--path", stream_url, "--realtime"])

                proc = subprocess.Popen(
                    cmd, 
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    preexec_fn=os.setsid
                )
                with grabber_lock:
                    grabber_processes[tenant_id] = proc

        return jsonify({
            "status": "success",
            "message": f"Configured {', '.join(configured)} for tenant '{tenant_id}'.",
        }), 200
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Configuration failed: {str(e)}", "traceback": str(e)}), 500


@app.route('/api/v1/translate/stream', methods=['GET'])
def translate_stream():
    """
    SSE Endpoint for real-time captions.
    Streams back new transcripts (and on-the-fly translations) as they arrive.
    """
    tenant_id = _resolve_tenant(request.args)
    target_lang = request.args.get('target_lang')
    want_audio = request.args.get('audio', 'false').lower() == 'true'
    last_chunk_id = _parse_int_arg(request.args, 'last_chunk_id', default=0)

    def event_stream():
        sent_transcripts = {}
        translated_transcripts = {}
        sent_audio = {}
        last_translations = {}
        last_translation_time = 0.0

        yield f"data: {json.dumps({'status': 'connected'})}\n\n"

        while True:
            with transcripts_lock:
                tenant_transcripts = dict(transcriptd.get(tenant_id, {}))
            
            now = time.time()
            provider_name = registry.get_provider_name(tenant_id, "translation")
            throttle_interval = 0.0
            can_translate = (now - last_translation_time) >= throttle_interval
            
            events_to_send = []

            for cid in _numeric_sorted_keys(tenant_transcripts):
                cid_int = _chunk_id_int(cid)
                if cid_int is not None and cid_int >= (last_chunk_id or 0):
                    text = tenant_transcripts[cid]['transcript']
                    
                    needs_tx_update = sent_transcripts.get(cid) != text
                    needs_tl_update = target_lang and (translated_transcripts.get(cid) != text)
                    
                    if needs_tx_update or needs_tl_update:
                        translation = last_translations.get(cid, "")
                        
                        if needs_tl_update and can_translate:
                            try:
                                lang_config = registry.get_language_config(tenant_id)
                                source_lang = lang_config.get('source_lang', 'en')
                                new_tl = registry.translate(tenant_id, text, source_lang, target_lang)
                                if new_tl:
                                    translation = new_tl
                                last_translations[cid] = translation
                                translated_transcripts[cid] = text
                                last_translation_time = time.time()
                                can_translate = False  # Only 1 translation per loop to spread load
                            except Exception as e:
                                logger.error(f"Stream translation error for {tenant_id}: {e}")
                                
                        # We send an event if the transcription changed, 
                        # or if we just successfully translated it to match the current transcription
                        if needs_tx_update or (needs_tl_update and translated_transcripts.get(cid) == text):
                            payload = {
                                "chunk_id": cid,
                                "transcript": text,
                                "translation": translation
                            }
                            events_to_send.append(payload)
                            sent_transcripts[cid] = text
            
            # 1. Yield all text updates instantly so the UI is real-time
            for payload in events_to_send:
                yield f"data: {json.dumps(payload)}\n\n"
                
            # 2. Then generate and yield audio updates for those same chunks
            for payload in events_to_send:
                cid = payload["chunk_id"]
                translation = payload.get("translation")
                text = payload.get("transcript")
                
                if want_audio and translation and target_lang:
                    if sent_audio.get(cid) != translation:
                        audio_b64 = generate_tts_sync(translation, target_lang)
                        if audio_b64:
                            audio_payload = {
                                "chunk_id": cid,
                                "transcript": text,
                                "translation": translation,
                                "audio_b64": audio_b64
                            }
                            yield f"data: {json.dumps(audio_payload)}\n\n"
                            sent_audio[cid] = translation
            
            time.sleep(0.2)

    return Response(event_stream(), mimetype="text/event-stream")


@app.route('/stop_event/<tenant_id>', methods=['POST'])
def stop_event(tenant_id):
    """Kills background workers, clears memory, and deletes transcripts for a room."""
    with grabber_lock:
        proc = grabber_processes.pop(tenant_id, None)
        if proc:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=3)
            except Exception as e:
                app.logger.warning(f"Error handling task for {tenant_id}: {e}")

    registry.remove(tenant_id)

    with transcripts_lock:
        transcriptd.pop(tenant_id, None)
        
    return jsonify({"status": "success", "message": f"Event {tenant_id} stopped"}), 200


@app.route('/api/v1/translate/status/<tenant_id>', methods=['GET'])
def provider_status(tenant_id):
    """
    Check if the models for a given tenant are fully loaded and ready.
    The frontend polls this during the loading screen.
    """
    if registry.is_pipeline_ready(tenant_id):
        return jsonify({"status": "ready"}), 200
    else:
        return jsonify({"status": "warming_up"}), 200


@api.route('/session')
class Session(Resource):
    @api.expect(session_input_model)
    @api.response(200, 'Success', session_response_model)
    @api.response(400, 'Invalid source')
    def post(self):
        '''
        Start a new transcription session for an input source.

        The grabber calls this once per run, passing its source name
        (mic/file/url/stdin/youtube). The server mints a fresh tenant_id
        (uuid) and records it as the latest session for that source.
        Subsequent read requests using ?source=<name> resolve to this
        tenant_id, so the user never has to know or type the uuid.
        '''
        try:
            data = request.get_json(force=True, silent=True) or {}
            source = data.get('source') or request.args.get('source')
            if source not in VALID_SOURCES:
                return {
                    "error": f"source must be one of {sorted(VALID_SOURCES)}",
                }, 400

            new_tenant_id = uuid.uuid4().hex
            with session_lock:
                assert source is not None  # already validated above by `source not in VALID_SOURCES` check
                latest_session_by_source[source] = (new_tenant_id, time.time())

            logger.info(f"New session for source={source}: tenant_id={new_tenant_id}")
            return {"tenant_id": new_tenant_id, "source": source}, 200
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error in /session", exc_info=True)
            return {"error": str(e)}, 500


@api.route('/transcribe')
class Transcribe(Resource):
    @api.expect(transcribe_input_model)
    @api.response(200, 'Success', transcribe_response_model)
    @api.response(404, 'Transcript Not Found')
    def post(self):
        try:
            # `silent=True` makes get_json() return None on a malformed body
            # instead of raising werkzeug.BadRequest. We then translate the
            # missing/invalid body into a clean 400 ourselves rather than
            # letting the broad `except Exception` below convert it into 500.
            data = request.get_json(force=True, silent=True)

            if not data:
                return {"error": "No JSON payload received"}, 400

            audio_b64 = data.get('audio_b64')
            chunk_id = data.get('chunk_id')
            tenant_id = data.get('tenant_id', '0000')

            if not audio_b64 or not chunk_id:
                return {"error": "Missing required fields"}, 400

            # push to processing queue
            audio_stack.put((tenant_id, chunk_id, audio_b64))

            response_data = {
                "chunk_id": chunk_id,
                "tenant_id": tenant_id,
                "status": "processing"
            }

            return response_data, 200

        except HTTPException:
            # Let abort()/HTTPException-derived errors keep their status code.
            raise
        except Exception as e:
            logger.error("Error in /transcribe", exc_info=True)
            return {"error": str(e)}, 500

@api.route('/get_transcript')
class GetTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'chunk_id' : {'description': 'Chunk ID'},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        The /get_transcript endpoint allows clients to retrieve the transcript for a given chunk_id.
        If the chunk_id is not found, an empty transcript is returned.
        '''
        tenant_id = _resolve_tenant(request.args)
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
            if sentences: t = merge_and_split_transcripts(t)
            chunk_id = request.args.get('chunk_id')
            if chunk_id in t:
                return jsonify({'chunk_id': chunk_id, 'transcript': t[chunk_id]['transcript']})
            else:
                return jsonify({'chunk_id': chunk_id, 'transcript': ''})

@api.route('/get_first_transcript')
class GetFirstTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        Get first transcript endpoint: Retrieve the first transcript for a given tenant_id
        '''
        tenant_id = _resolve_tenant(request.args)
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
            if sentences: t = merge_and_split_transcripts(t)
            fromid = _parse_int_arg(request.args, 'from', default=0)
            first_chunk_id = next(
                (k for k in _numeric_sorted_keys(t) if (_chunk_id_int(k) or 0) >= (fromid or 0)),
                None,
            )
            if first_chunk_id is None:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            first_transcript = t[first_chunk_id]['transcript']
            return jsonify({'chunk_id': first_chunk_id, 'transcript': first_transcript})

@api.route('/pop_first_transcript')
class PopFirstTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def delete(self):
        '''
        Pop first transcript: retrieve and remove the first transcript for a given tenant_id.

        DELETE is the canonical method for this destructive operation.
        '''
        return self._pop_first()

    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.deprecated
    def get(self):
        '''
        DEPRECATED: use DELETE /pop_first_transcript instead. GET on a
        destructive endpoint violates the HTTP "GET is safe" contract and
        is incompatible with caching proxies. Kept for backward compat.
        '''
        logger.warning("Deprecated GET /pop_first_transcript called; use DELETE.")
        return self._pop_first()

    def _pop_first(self):
        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        fromid = _parse_int_arg(request.args, 'from', default=0)

        with transcripts_lock:
            stored = transcriptd.get(tenant_id)
            if not stored:
                return jsonify({'chunk_id': '-1', 'transcript': ''})

            view = merge_and_split_transcripts(stored) if sentences else stored
            first_chunk_id = next(
                (k for k in _numeric_sorted_keys(view) if (_chunk_id_int(k) or 0) >= (fromid or 0)),
                None,
            )
            if first_chunk_id is None:
                return jsonify({'chunk_id': '-1', 'transcript': ''})

            entry = stored.pop(first_chunk_id, None)
            if sentences:
                first_transcript = view[first_chunk_id]['transcript']
            else:
                first_transcript = entry['transcript'] if entry else ''
        return jsonify({'chunk_id': first_chunk_id, 'transcript': first_transcript})

@api.route('/get_latest_transcript')
class GetLatestTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'until': {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        Get latest transcript endpoint: Retrieve the latest transcript for a given tenant_id
        '''
        tenant_id = _resolve_tenant(request.args)
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if len(t) == 0:
            return jsonify({'chunk_id': '-1', 'transcript': ''})
        else:
            sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
            if sentences: t = merge_and_split_transcripts(t)
            untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
            latest_chunk_id = next(
                (k for k in _numeric_sorted_keys(t, reverse=True) if (_chunk_id_int(k) or 0) < (untilid or 0)),
                None,
            )
            if latest_chunk_id is None:
                return jsonify({'chunk_id': '-1', 'transcript': ''})
            latest_transcript = t[latest_chunk_id]['transcript']
            return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@api.route('/pop_latest_transcript')
class PopLatestTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'until': {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def delete(self):
        '''
        Pop latest transcript: retrieve and remove the latest transcript for a given tenant_id.

        DELETE is the canonical method for this destructive operation.
        '''
        return self._pop_latest()

    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'until': {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.deprecated
    def get(self):
        '''
        DEPRECATED: use DELETE /pop_latest_transcript instead. GET on a
        destructive endpoint violates the HTTP "GET is safe" contract and
        is incompatible with caching proxies. Kept for backward compat.
        '''
        logger.warning("Deprecated GET /pop_latest_transcript called; use DELETE.")
        return self._pop_latest()

    def _pop_latest(self):
        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))

        with transcripts_lock:
            stored = transcriptd.get(tenant_id)
            if not stored:
                return jsonify({'chunk_id': '-1', 'transcript': ''})

            view = merge_and_split_transcripts(stored) if sentences else stored
            latest_chunk_id = next(
                (k for k in _numeric_sorted_keys(view, reverse=True) if (_chunk_id_int(k) or 0) < (untilid or 0)),
                None,
            )
            if latest_chunk_id is None:
                return jsonify({'chunk_id': '-1', 'transcript': ''})

            entry = stored.pop(latest_chunk_id, None)
            if sentences:
                latest_transcript = view[latest_chunk_id]['transcript']
            else:
                latest_transcript = entry['transcript'] if entry else ''
        return jsonify({'chunk_id': latest_chunk_id, 'transcript': latest_transcript})

@api.route('/delete_transcript')
class DeleteTranscript(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'chunk_id' : {'description': 'Chunk ID', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.response(404, 'Transcript Not Found')
    def delete(self):
        '''
        Delete a transcript for a given tenant_id and chunk_id.

        DELETE is the canonical method for this destructive operation.
        '''
        return self._delete()

    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'chunk_id' : {'description': 'Chunk ID', 'type': 'string'}
    })
    @api.response(200, 'Success', transcript_response_model)
    @api.deprecated
    def get(self):
        '''
        DEPRECATED: use DELETE /delete_transcript instead. GET on a
        destructive endpoint violates the HTTP "GET is safe" contract and
        is incompatible with caching proxies. Kept for backward compat.
        '''
        logger.warning("Deprecated GET /delete_transcript called; use DELETE.")
        return self._delete()

    def _delete(self):
        tenant_id = _resolve_tenant(request.args)
        chunk_id = request.args.get('chunk_id')
        with transcripts_lock:
            stored = transcriptd.get(tenant_id, {})
            if chunk_id in stored:
                entry = stored.pop(chunk_id, None)
                return jsonify({'chunk_id': chunk_id, 'transcript': entry['transcript']})
        return jsonify({'chunk_id': chunk_id, 'transcript': ''})

@api.route('/list_transcripts')
class ListTranscripts(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'},
        'until'    : {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', list_transcripts_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        list all transcripts for a given tenant_id
        '''
        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        fromid = _parse_int_arg(request.args, 'from', default=0)
        untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if sentences: t = merge_and_split_transcripts(t)
        result = {k: v for k, v in t.items() if _in_chunk_range(k, fromid, untilid)}
        return jsonify(result)

@api.route('/transcripts_size')
class TranscriptsSize(Resource):
    @api.doc(params={
        'tenant_id': {'description': 'Tenant ID', 'default': '0000'},
        'source':    {'description': 'Resolve to the latest session for a source (mic|file|url|stdin). Ignored if tenant_id is given. Unknown values return HTTP 400.', 'type': 'string', 'enum': ['mic', 'file', 'url', 'stdin', 'youtube']},
        'sentences': {'description': 'Merge and split transcripts into sentences', 'type': 'boolean', 'default': False},
        'from'     : {'description': 'Starting chunk ID', 'type': 'string', 'default': '0'},
        'until'    : {'description': 'End chunk ID (defaults to "now" in ms)', 'type': 'string'}
    })
    @api.response(200, 'Success', size_response_model)
    @api.response(404, 'Transcript Not Found')
    def get(self):
        '''
        get the size of the transcripts for a given tenant_id
        '''
        tenant_id = _resolve_tenant(request.args)
        sentences = request.args.get('sentences', default='false').strip().lower() == 'true'
        fromid = _parse_int_arg(request.args, 'from', default=0)
        untilid = _parse_int_arg(request.args, 'until', default=int(time.time() * 1000))
        with transcripts_lock:
            t = dict(transcriptd.get(tenant_id, {}))
        if sentences: t = merge_and_split_transcripts(t)
        t = {k: v for k, v in t.items() if _in_chunk_range(k, fromid, untilid)}
        return jsonify({'size': len(t)})

_worker_thread = None
_worker_lock = threading.Lock()


def _start_worker_once():
    """Start the audio-worker thread exactly once per process. Idempotent."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return _worker_thread
        _worker_thread = threading.Thread(
            target=process_audio,
            name="audio-worker",
            daemon=True,
        )
        _worker_thread.start()
        logger.info("Audio worker thread started")
        return _worker_thread


if _env_bool('TRANSCRIBE_AUTOSTART_WORKER', True):
    _start_worker_once()


# ---------------------------------------------------------------------------
# Page routes (web UI)
# ---------------------------------------------------------------------------

def _require_login():
    """Return a redirect to /auth/login if the request has no valid JWT cookie."""
    try:
        verify_jwt_in_request(locations=["cookies"])
        return None  # authenticated — let the view proceed
    except Exception:
        return redirect(url_for("auth.login_page"))


@app.before_request
def redirect_root():
    """Intercept root URL and forcefully redirect to home."""
    if request.path == "/":
        return redirect(url_for("home"))


@app.route("/home")
def home():
    """Dashboard / lobby — requires login."""
    redir = _require_login()
    if redir:
        return redir
    return render_template("create-room.html")


@app.route("/config/<tenant_id>")
def config_page(tenant_id: str):
    """Room configuration page — requires login."""
    redir = _require_login()
    if redir:
        return redir
    return render_template("config.html", tenant_id=tenant_id)


@app.route("/stream/<tenant_id>")
def stream_page(tenant_id: str):
    """Live stream / caption viewer page — requires login."""
    redir = _require_login()
    if redir:
        return redir
    video_url = request.args.get("url", "")
    stream_type = request.args.get("type", "youtube")
    return render_template("stream.html", tenant_id=tenant_id, video_url=video_url, stream_type=stream_type)



if __name__ == '__main__':
    # Server bind config is env-driven so the defaults are SAFE:
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', '5040'))
    debug = _env_bool('FLASK_DEBUG', False)

    if debug and host not in ('127.0.0.1', 'localhost'):
        logger.warning(
            "FLASK_DEBUG=true with host=%s exposes the Werkzeug debugger to "
            "the network. This is remote-code-execution. Set FLASK_HOST=127.0.0.1 "
            "or disable debug.",
            host,
        )

    # use_reloader=False because the audio-worker thread above must not be spawned twice (the reloader runs the module twice, which would otherwise create a duplicate consumer on the queue).
    app.run(host=host, port=port, debug=debug, use_reloader=False)
