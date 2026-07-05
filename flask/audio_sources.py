"""
Audio source abstractions for the SUSI Translator audio grabber
"""

from __future__ import annotations

import subprocess
import sys
import time
import queue
from abc import ABC, abstractmethod
from typing import Generator, List, Optional
from urllib.parse import urlparse

_ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})
_FFMPEG_PROTOCOL_WHITELIST: str = "http,https,tcp,tls,crypto"
# deliberately *not* including ``http``/``https`` means a malicious upstream can't trick ffmpeg into chasing arbitrary URLs.
_FFMPEG_PROTOCOL_WHITELIST_PIPE: str = "pipe,crypto"


def _read_up_to(stream, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        piece = stream.read(n - len(buf))
        if not piece:
            break  # EOF
        buf.extend(piece)
    return bytes(buf)

class AudioSource(ABC):
    """
    Abstract base class for an audio source
    """

    SAMPLE_RATE: int = 16000
    SAMPLE_WIDTH: int = 2  # 16-bit
    CHANNELS: int = 1
    CHUNK_BYTES: int = SAMPLE_RATE * SAMPLE_WIDTH  # 1 second of audio

    @abstractmethod
    def start(self) -> None:
        """Open / initialize the underlying resource."""

    @abstractmethod
    def stop(self) -> None:
        """Stop / clean up the underlying resource. Safe to call multiple times."""

    @abstractmethod
    def read_chunk(self) -> Generator[bytes, None, None]:
        """Yield successive ~1-second chunks of PCM bytes until the source is exhausted or stop() is called."""

    def __enter__(self) -> "AudioSource":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

class MicrophoneSource(AudioSource):
    """
    Capture live audio from a microphone via PyAudio
    """

    def __init__(self, input_device_index: Optional[int] = None) -> None:
        self._input_device_index: Optional[int] = input_device_index
        self._audio = None  # type: ignore[assignment]
        self._stream = None  # type: ignore[assignment]
        self._queue: "queue.Queue[bytes]" = queue.Queue()
        self._running: bool = False
        self._pa_continue: int = 0 # will be set to pyaudio.paContinue in start()

    def start(self) -> None:
        # Imported lazily so that other sources work even if PyAudio is unavailable on the host (e.g. headless server with no audio libs).
        import pyaudio

        self._pa_continue = pyaudio.paContinue
        self._audio = pyaudio.PyAudio()
        self._stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=self.CHANNELS,
            rate=self.SAMPLE_RATE,
            input=True,
            input_device_index=self._input_device_index,
            frames_per_buffer=self.SAMPLE_RATE,  # 1 second per callback
            stream_callback=self._callback,
        )
        self._running = True
        self._stream.start_stream()

    def _callback(self, in_data, frame_count, time_info, status):  
        # PyAudio callback signature is fixed; we just enqueue and continue.
        if self._running and in_data:
            self._queue.put(in_data)
        return (None, self._pa_continue)

    def read_chunk(self) -> Generator[bytes, None, None]:
        # Block on the queue with a small timeout so stop() is responsive.
        while self._running:
            try:
                chunk = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if chunk:
                yield chunk

    def stop(self) -> None:
        self._running = False
        stream = self._stream
        audio = self._audio
        self._stream = None
        self._audio = None
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if audio is not None:
            try:
                audio.terminate()
            except Exception:
                pass
        # Drain the queue so a fresh start() starts clean.
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

class FileSource(AudioSource):
    """
    Read audio from a local file
    """

    def __init__(self, path: str, realtime: bool = False) -> None:
        self._path: str = path
        self._realtime: bool = realtime
        self._pcm: bytes = b""
        self._running: bool = False

    def start(self) -> None:
        from pydub import AudioSegment  # imported lazily

        seg = AudioSegment.from_file(self._path)
        seg = (
            seg.set_frame_rate(self.SAMPLE_RATE)
               .set_channels(self.CHANNELS)
               .set_sample_width(self.SAMPLE_WIDTH)
        )
        self._pcm = seg.raw_data
        self._running = True

    def read_chunk(self) -> Generator[bytes, None, None]:
        offset: int = 0
        chunk_bytes: int = self.CHUNK_BYTES
        total: int = len(self._pcm)
        while self._running and offset < total:
            chunk = self._pcm[offset:offset + chunk_bytes]
            offset += len(chunk)
            yield chunk
            if self._realtime:
                # 1 chunk ~= 1 second; sleep proportional to actual length.
                time.sleep(len(chunk) / float(chunk_bytes))
        self._running = False

    def stop(self) -> None:
        self._running = False
        self._pcm = b""



class URLSource(AudioSource):
    """
    Decode a remote audio stream (HTTP/HTTPS URL, including live streams)
    by piping it through ``ffmpeg``.

    System requirements
    -------------------
    - The ``ffmpeg`` binary on PATH.

    On start(), ffmpeg converts the stream to 16 kHz, 16-bit mono PCM.
    read_chunk() returns 1-second PCM chunks until the stream ends or
    stop() is called.
    """

    def __init__(self, url: str) -> None:
        self._url: str = self._validate_url(url)
        self._proc: Optional[subprocess.Popen] = None
        self._running: bool = False

    @staticmethod
    def _validate_url(url: str) -> str:
        """
        Validate that the URL is a safe HTTP/HTTPS network URL before passing it to ffmpeg.
        """
        if not isinstance(url, str) or not url:
            raise ValueError("URLSource: url must be a non-empty string")
        # Reject anything that could be parsed as an option flag by ffmpeg
        if url.startswith("-"):
            raise ValueError("URLSource: url must not start with '-'")
        parsed = urlparse(url)
        if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
            raise ValueError(
                f"URLSource: unsupported URL scheme {parsed.scheme!r}; "
                f"allowed schemes are {sorted(_ALLOWED_URL_SCHEMES)}"
            )
        if not parsed.netloc:
            raise ValueError("URLSource: url must include a host")
        return url

    def start(self) -> None:
        # SECURITY: self._url is validated, ffmpeg runs with shell=False and a protocol whitelist, preventing unsafe redirects and command injection.
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-protocol_whitelist", _FFMPEG_PROTOCOL_WHITELIST,
            "-i", self._url,
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", str(self.CHANNELS),
            "-ar", str(self.SAMPLE_RATE),
            "-",  # write to stdout
        ]
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        # Safe: self._url is validated by _validate_url() (scheme whitelist,
        # no leading '-', host required); argv is a fixed list with shell=False.
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        self._running = True

    def read_chunk(self) -> Generator[bytes, None, None]:
        if self._proc is None or self._proc.stdout is None:
            return
        chunk_bytes: int = self.CHUNK_BYTES
        stream = self._proc.stdout
        while self._running:
            buf = _read_up_to(stream, chunk_bytes)
            if not buf:
                break  # ffmpeg exited / stream ended
            yield buf
        self._running = False

    def stop(self) -> None:
        self._running = False
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

class StdinSource(AudioSource):
    """
    Read raw 16 kHz, 16-bit mono PCM audio from stdin.

    Example:
        ffmpeg -i input.flac -f s16le -ac 1 -ar 16000 - | \
            python audio_grabber.py stdin --server http://localhost:5040

    The input must already be in the required PCM format; no decoding or
    resampling is performed.
    """

    def __init__(self) -> None:
        self._running: bool = False
        self._stream = None  # type: ignore[assignment]

    def start(self) -> None:
        # Use the underlying binary buffer to avoid newline translation on Windows.
        self._stream = sys.stdin.buffer
        self._running = True

    def read_chunk(self) -> Generator[bytes, None, None]:
        if self._stream is None:
            return
        chunk_bytes: int = self.CHUNK_BYTES
        while self._running:
            buf = _read_up_to(self._stream, chunk_bytes)
            if not buf:
                break  # EOF
            yield buf
        self._running = False

    def stop(self) -> None:
        self._running = False
        self._stream = None

class PlatformSource(AudioSource):
    """
    Decode a platform (YouTube/Twitch/Vimeo) URL by getting the URL from ``yt-dlp`` into ``ffmpeg``.
    by chaining two subprocesses::

        yt-dlp -f <fmt> -o - <url>  |  ffmpeg -i pipe:0 ... -f s16le -

    See the README for requirements (yt-dlp + ffmpeg on PATH) and cookie-based auth.
    """

    _ALLOWED_HOSTS: frozenset[str] = frozenset({
        "twitch.tv",
        "www.twitch.tv",
        "vimeo.com",
        "www.vimeo.com",
        "player.vimeo.com",
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    })

    def __init__(
        self,
        url: str,
        format_selector: str = "bestaudio/best",
        cookies_path: Optional[str] = None,
        cookies_from_browser: Optional[str] = None,
    ) -> None:
        # yt-dlp silently honours only one, so reject both up front.
        if cookies_path and cookies_from_browser:
            raise ValueError(
                "PlatformSource: pass at most one of cookies_path or "
                "cookies_from_browser, not both"
            )
        self._watch_url: str = self._validate_url(url)
        self._format_selector: str = format_selector
        self._cookies_path: Optional[str] = cookies_path
        self._cookies_from_browser: Optional[str] = cookies_from_browser
        self._ydl_proc: Optional[subprocess.Popen] = None
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._running: bool = False


    @classmethod
    def _validate_url(cls, url: str) -> str:
        """Reject bad input before any subprocess: must be an http(s) URL
        with a recognised YouTube host and no leading ``-``."""
        if not isinstance(url, str) or not url:
            raise ValueError("PlatformSource: url must be a non-empty string")
        if url.startswith("-"):
            raise ValueError("PlatformSource: url must not start with '-'")
        parsed = urlparse(url)
        if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
            raise ValueError(
                f"PlatformSource: unsupported URL scheme {parsed.scheme!r}; "
                f"allowed schemes are {sorted(_ALLOWED_URL_SCHEMES)}"
            )
        if not parsed.netloc:
            raise ValueError("PlatformSource: url must include a host")
        host = (parsed.hostname or "").lower()
        if host not in cls._ALLOWED_HOSTS:
            raise ValueError(
                f"PlatformSource: host {host!r} is not a recognised platform "
                f"domain. Allowed hosts: {sorted(cls._ALLOWED_HOSTS)}"
            )
        return url




    def start(self) -> None:
        ydl_argv = [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "-f", self._format_selector,
            "--get-url"
        ]
        if self._cookies_path:
            ydl_argv += ["--cookies", self._cookies_path]
        elif self._cookies_from_browser:
            ydl_argv += ["--cookies-from-browser", self._cookies_from_browser]
        ydl_argv += ["--", self._watch_url]

        try:
            url_output = subprocess.check_output(
                ydl_argv,
                stderr=subprocess.DEVNULL,
                text=True,
                shell=False
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"yt-dlp failed to get URL: {exc}")

        lines = [line.strip() for line in url_output.splitlines() if line.strip()]
        if not lines:
            raise ValueError("yt-dlp returned no URL")
        stream_url = lines[-1]

        ff_argv = [
            "ffmpeg",
            "-loglevel", "error",
            "-protocol_whitelist", _FFMPEG_PROTOCOL_WHITELIST,
            "-i", stream_url,
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", str(self.CHANNELS),
            "-ar", str(self.SAMPLE_RATE),
            "-",
        ]

        self._ffmpeg_proc = subprocess.Popen(
            ff_argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        self._running = True

    def read_chunk(self) -> Generator[bytes, None, None]:
        chunk_bytes: int = self.CHUNK_BYTES
        while self._running:
            proc = self._ffmpeg_proc
            if proc is None or proc.stdout is None:
                break
            buf = _read_up_to(proc.stdout, chunk_bytes)
            if not buf:
                break
            yield buf
        self._running = False

    def _terminate_procs(self) -> None:
        for attr in ("_ffmpeg_proc",):
            proc: Optional[subprocess.Popen] = getattr(self, attr, None)
            setattr(self, attr, None)
            if proc is None:
                continue
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def stop(self) -> None:
        self._running = False
        self._terminate_procs()
