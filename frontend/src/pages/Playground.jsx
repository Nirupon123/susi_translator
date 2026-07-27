import { useEffect, useRef, useState } from "react";
import { DotLottieReact } from '@lottiefiles/dotlottie-react';
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import ReactPlayer from "react-player";
import {
  Languages,
  Mic,
  Square,
  Upload,
  Link2,
  Volume2,
  Play,
  Loader2,
  ArrowLeft,
  Lock,
  Sparkles,
  Waves,
  LogOut,
  X,
  FileAudio,
  Settings2,
  ChevronDown,
  Activity,
  ArrowRight
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "@/components/ui/sonner";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

const SOURCE_LANGS = [
  { code: "auto", label: "Auto-detect" },
  { code: "en", label: "English" },
  { code: "hi", label: "Hindi" },
  { code: "es", label: "Spanish" },
  { code: "fr", label: "French" },
  { code: "ar", label: "Arabic" },
  { code: "ja", label: "Japanese" },
  { code: "zh", label: "Mandarin Chinese" },
];

const TARGETS = [
  { code: "hi", name: "Hindi", country: "in", rtl: false },
  { code: "es", name: "Spanish", country: "es" },
  { code: "ja", name: "Japanese", country: "jp" },
  { code: "ar", name: "Arabic", country: "sa", rtl: true },
  { code: "fr", name: "French", country: "fr" },
  { code: "zh", name: "Mandarin", country: "cn" },
];

const SEGMENTS = [
  {
    en: "Welcome everyone to the global summit.",
    t: { hi: "वैश्विक शिखर सम्मेलन में सभी का स्वागत है।", es: "Bienvenidos todos a la cumbre global.", ja: "グローバルサミットへようこそ。", ar: "مرحبًا بالجميع في القمة العالمية.", fr: "Bienvenue à tous au sommet mondial.", zh: "欢迎大家参加全球峰会。" },
  },
  {
    en: "Today we connect people across every language.",
    t: { hi: "आज हम हर भाषा में लोगों को जोड़ते हैं।", es: "Hoy conectamos a las personas en todos los idiomas.", ja: "今日、私たちはあらゆる言語で人々をつなぎます。", ar: "اليوم نربط الناس عبر كل لغة.", fr: "Aujourd'hui, nous connectons les gens dans toutes les langues.", zh: "今天我们跨越每一种语言连接人们。" },
  },
  {
    en: "Real-time understanding, for everyone.",
    t: { hi: "वास्तविक समय में समझ, सबके लिए।", es: "Comprensión en tiempo real, para todos.", ja: "リアルタイムの理解を、すべての人に。", ar: "فهم فوري، للجميع.", fr: "Une compréhension en temps réel, pour tous.", zh: "为每个人提供实时理解。" },
  },
];

export default function Playground() {
  const { isAuthenticated, logout } = useAuth();
  
  const [roomState, setRoomState] = useState("config"); 

  const [tab, setTab] = useState("mic");
  const [sourceLang, setSourceLang] = useState("en");
  const [sttModel] = useState("whisper_local");
  const [enableTranslation, setEnableTranslation] = useState(true);
  const [translationModel, setTranslationModel] = useState("nllb_local");
  const [targets, setTargets] = useState([]);
  const targetLang = targets[0] || "";
  const setTargetLang = (code) => setTargets(code ? [code] : []);
  // displayLang is what the viewer sees in the live room dropdown.
  // It is decoupled from the WS target_lang so switching the dropdown
  // does NOT reconnect the socket or re-translate old segments.
  const [displayLang, setDisplayLang] = useState("original");
  const [enableTTS, setEnableTTS] = useState(false);
  const [ttsModel, setTtsModel] = useState("supertonic");
  const [ttsVoice, setTtsVoice] = useState("aria");

  const TTS_VOICES = [
    { value: "aria",    label: "Aria" },
    { value: "nova",    label: "Nova" },
    { value: "ryan",    label: "Ryan" },
    { value: "james",   label: "James" },
    { value: "elena",   label: "Elena" },
    { value: "marcus",  label: "Marcus" },
  ];

  const [fileName, setFileName] = useState("");
  const [fileObj, setFileObj] = useState(null);
  const [tenantId, setTenantId] = useState("");
  const [loadingMsg, setLoadingMsg] = useState("Starting engine...");
  const [link, setLink] = useState("");
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  const [running, setRunning] = useState(false);
  const [feed, setFeed] = useState([]);

  const mediaRef = useRef(null);
  const timerRef = useRef(null);
  const feedRef = useRef(null);
  const tenantIdRef = useRef("");

  
  const getCsrfToken = () => {
    const match = document.cookie.match(new RegExp('(^| )csrf_access_token=([^;]+)'));
    return match ? match[2] : '';
  };

  const toggleTarget = (code) =>
    setTargets((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      mediaRef.current = { rec, stream };
      rec.start();
      setRecording(true);
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
      toast.success("Microphone connected, capturing audio");
    } catch (e) {
      toast.error("Microphone access denied. Check browser permissions.");
    }
  };

  const stopRecording = () => {
    const m = mediaRef.current;
    if (m) {
      m.rec.stop();
      m.stream.getTracks().forEach((t) => t.stop());
      mediaRef.current = null;
    }
    clearInterval(timerRef.current);
    setRecording(false);
  };

  useEffect(() => {
    const handler = (e) => {
      if (e.reason && e.reason.message && e.reason.message.includes("play() request was interrupted")) {
        e.preventDefault();
      }
    };
    window.addEventListener("unhandledrejection", handler);

    return () => {
      window.removeEventListener("unhandledrejection", handler);
      clearInterval(timerRef.current);
      if (mediaRef.current) {
        mediaRef.current.stream.getTracks().forEach((t) => t.stop());
      }
      if (tenantIdRef.current) {
        fetch(`/stop_event/${tenantIdRef.current}`, {
          method: "POST",
          headers: { "X-CSRF-TOKEN": getCsrfToken() },
          keepalive: true
        }).catch(e => console.error("Cleanup error", e));
      }
    };
  }, []);

  const inputReady =
    (tab === "mic") ||
    (tab === "file" && fileName) ||
    (tab === "link" && link.trim().length > 5);


  const launchLiveRoom = async () => {
    if (!inputReady) {
      toast.error("Add an input first (record, upload a file, or paste a link).");
      return;
    }

    setRoomState("loading");
    setLoadingMsg("Starting engine...");
    setFeed([]);
    
    try {
      let streamUrl = "";
      if (tab === "link") {
        streamUrl = link;
      } else if (tab === "file" && fileObj) {
        setLoadingMsg("Uploading audio securely...");
        const formData = new FormData();
        formData.append("audio_file", fileObj);
        
        const uploadRes = await fetch("/api/v1/translate/upload_file", {
          method: "POST",
          headers: { "X-CSRF-TOKEN": getCsrfToken() },
          body: formData
        });
        const uploadData = await uploadRes.json();
        if (uploadData.status === "success") {
          streamUrl = uploadData.file_path;
        } else {
          toast.error("File upload failed: " + uploadData.message);
          setRoomState("config");
          return;
        }
      }

      setLoadingMsg("Creating room...");
      const sessRes = await fetch("/session", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-TOKEN": getCsrfToken()
        },
        body: JSON.stringify({ source: tab === "link" ? "youtube" : tab })
      });
      const sessData = await sessRes.json();
      if (!sessRes.ok || !sessData.tenant_id) {
        toast.error("Failed to create room: " + (sessData.message || "Unknown error"));
        setRoomState("config");
        return;
      }
      const newTenantId = sessData.tenant_id;
      tenantIdRef.current = newTenantId; // set ref synchronously so WebSocket effect sees it immediately
      setTenantId(newTenantId);

      setLoadingMsg("Configuring models...");
      const payload = {
        tenant_id: newTenantId,
        stream_type: tab === "link" ? "youtube" : tab,
        stream_url: streamUrl,
        transcription: {
          provider_name: sttModel,
          config: { model_size: "base" }
        }
      };
      if (enableTranslation) {
        payload.translation = {
          provider_name: translationModel,
          source_lang: sourceLang,
          config: {}
        };
      }

      const res = await fetch("/api/v1/translate/configure", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-TOKEN": getCsrfToken()
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      
      if (data.status !== "success") {
        toast.error("Configuration failed: " + data.message);
        setRoomState("config");
        return;
      }

      if (data.pipeline_ready === true) {
        setRoomState("live");
        return;
      }

      setLoadingMsg("Waiting for models to load...");
      let pollCount = 0;
      const MAX_POLLS = 30;
      const pollInterval = setInterval(async () => {
        pollCount++;
        if (pollCount > MAX_POLLS) {
          clearInterval(pollInterval);
          setRoomState("live"); 
          return;
        }
        try {
          const statusRes = await fetch(`/api/v1/translate/status/${newTenantId}`);
          const statusData = await statusRes.json();
          if (statusData.status === "ready") {
            clearInterval(pollInterval);
            setRoomState("live");
          } else if (statusData.status === "failed") {
            clearInterval(pollInterval);
            toast.error("Stream Error: " + (statusData.message || "Failed to start audio grabber"));
            setRoomState("config");
          }
        } catch (err) {
          console.error("Polling error", err);
        }
      }, 1000);
      
    } catch (e) {
      toast.error("Network Error: Could not reach the server.");
      setRoomState("config");
    }
  };
  const reconfigureRoom = async () => {
    try {
      if (tenantId) {
        await fetch(`/stop_event/${tenantId}`, {
          method: "POST",
          headers: { "X-CSRF-TOKEN": getCsrfToken() }
        });
      }
    } catch (e) {
      console.error("Failed to stop event", e);
    }
    setRoomState("config");
    setRunning(false);
    if (recording) {
      stopRecording();
    }
  };

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [feed]);

  const latestCaption = feed.length > 0 ? feed[feed.length - 1] : null;
  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;


  // WebSocket Logic
  useEffect(() => {
    if (roomState !== "live") return;
    if (!tenantId) return; // Wait until tenantId is populated
    
    let ws = null;
    const connectWs = () => {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;

      const wsTargetLang = displayLang || 'original';
      const tid = tenantIdRef.current || tenantId;
      const url = `${proto}//${host}/ws/v1/translate/stream?tenant_id=${tid}&source=${tab}&audio=${enableTTS}&target_lang=${wsTargetLang}`;
      console.log("[Websocket] Connecting to:", url);
      
      ws = new WebSocket(url);
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.status === "connected") return;
          if (data.status === "error") {
            toast.error("Stream connection error");
            return;
          }
          
          if (data.transcript) {
            setFeed(prev => {
              const idx = prev.findIndex(item => item.chunk_id === data.chunk_id);
              const newFeed = [...prev];
              const existing = idx >= 0 ? newFeed[idx] : {};
              // "Lock in" the language this segment was originally rendered in so it doesn't
              // magically swap if the user changes the dropdown later.
              const renderedLang = existing.renderedLang || wsTargetLang;
              const incomingT = data.translation && wsTargetLang !== 'original'
                ? { [wsTargetLang]: data.translation }
                : {};
              const payload = {
                chunk_id: data.chunk_id,
                en: data.transcript,
                t: { ...(existing.t || {}), ...incomingT },
                renderedLang,
                audio_b64: data.audio_b64
              };
              if (idx >= 0) newFeed[idx] = payload;
              else newFeed.push(payload);
              return newFeed;
            });
          }
          
          if (enableTTS && data.audio_b64) {
            const audio = new Audio(`data:audio/wav;base64,${data.audio_b64}`);
            audio.play().catch(e => console.error("Audio play failed:", e));
          }
        } catch (e) {
          console.error("WS Parse error", e);
        }
      };
    };
    
    connectWs();
    
    return () => {
      if (ws) ws.close();
    };
  }, [roomState, enableTTS, tab, tenantId, displayLang]);

  // Web Mic Logic
  useEffect(() => {
    if (roomState !== "live" || tab !== "mic") return;
    
    let audioCtx = null;
    let mediaStream = null;
    let processor = null;
    
    const initMic = async () => {
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ 
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
        });
        audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const source = audioCtx.createMediaStreamSource(mediaStream);
        processor = audioCtx.createScriptProcessor(4096, 1, 1);
        
        source.connect(processor);
        processor.connect(audioCtx.destination);
        
        let tempBuffer = [];
        let activeBuffer = [];
        let currentChunkId = Date.now().toString();
        
        processor.onaudioprocess = (e) => {
          const data = e.inputBuffer.getChannelData(0);
          for(let i=0; i<data.length; i++) tempBuffer.push(data[i]);
          
          if (tempBuffer.length >= 16000) {
            let maxVal = 0;
            for(let i=0; i<tempBuffer.length; i++) {
              if (Math.abs(tempBuffer[i]) > maxVal) maxVal = Math.abs(tempBuffer[i]);
            }
            
            const isSilent = maxVal <= 500/32768;
            
            if (isSilent) {
              // Silence detected: mark the end of the current utterance
              activeBuffer = [];
              currentChunkId = Date.now().toString();
            } else {
              // Voice active: append the 1s block to our running buffer
              activeBuffer.push(...tempBuffer);

              const int16 = new Int16Array(activeBuffer.map(n => n * 32767));
              const blob = new Blob([int16.buffer], { type: "audio/wav" });
              const reader = new FileReader();
              reader.onloadend = () => {
                const b64 = reader.result.split(',')[1];
                fetch('/transcripts', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': getCsrfToken() },
                  body: JSON.stringify({ chunk_id: currentChunkId, audio_b64: b64, tenant_id: tenantIdRef.current })
                }).catch(console.error);
              };
              reader.readAsDataURL(blob);

              // Hard cutoff at 10 seconds to avoid endlessly growing buffers
              if (activeBuffer.length >= 160000) {
                activeBuffer = [];
                currentChunkId = Date.now().toString();
              }
            }
            tempBuffer = [];
          }
        };
        setRecording(true);
      } catch (e) {
        toast.error("Mic access denied");
      }
    };
    
    initMic();
    
    return () => {
      if (processor) { processor.disconnect(); processor = null; }
      if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
      if (audioCtx) { audioCtx.close(); audioCtx = null; }
      setRecording(false);
    };
  }, [roomState, tab, tenantId]);

  return (

    <div className="min-h-screen bg-[#f8fafc]" data-testid="playground-page">
      <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-xl border-b border-slate-200">
        <div className="mx-auto flex h-[60px] max-w-7xl items-center justify-between px-5 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5" data-testid="pg-logo">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#0a52ff] text-white">
              <Languages className="h-4 w-4" />
            </span>
            <span className="font-display text-base font-extrabold tracking-tight text-slate-900">
              SUSI<span className="text-[#0a52ff]">.</span>Translator
              {roomState === "config" && <span className="ml-2 font-normal text-slate-400 italic font-serif">playground</span>}
            </span>
          </Link>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-600 sm:flex">
              <Sparkles className="h-3.5 w-3.5" /> Demo mode
            </span>
            <button onClick={reconfigureRoom} className="hidden items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-slate-900 sm:flex">
              <ArrowLeft className="h-4 w-4" /> Exit Room
            </button>
            {isAuthenticated ? (
              <Button
                variant="outline"
                className="h-8 rounded-full text-slate-600 hover:text-slate-900"
                onClick={logout}
              >
                <LogOut className="h-3.5 w-3.5 mr-1.5" /> Log out
              </Button>
            ) : (
              <Button
                variant="outline"
                className="h-8 rounded-full text-slate-600 hover:text-slate-900"
                data-testid="pg-signin-btn"
                onClick={() => toast("Sign-in connects to your SUSI backend.", { icon: "🔒" })}
              >
                <Lock className="h-3.5 w-3.5" /> Sign in
              </Button>
            )}
          </div>
        </div>
      </header>

{roomState === "config" ? (
        /* --- CONFIGURATION STEP --- */
        <div className="relative flex min-h-[calc(100vh-60px)] items-center justify-center overflow-hidden bg-slate-50 p-6">
          <div className="pointer-events-none absolute left-1/2 top-1/2 h-[800px] w-[800px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-400/20 opacity-60 blur-[120px]" />
          <div className="pointer-events-none absolute left-[-10%] top-1/2 h-[600px] w-[600px] -translate-y-1/2 rounded-full bg-cyan-300/20 opacity-50 blur-[100px]" />
          <div className="pointer-events-none absolute right-[-10%] top-1/2 h-[600px] w-[600px] -translate-y-1/2 rounded-full bg-[#0a52ff]/10 opacity-50 blur-[100px]" />

          <div className="relative z-10 w-full max-w-4xl rounded-[2.5rem] bg-white/90 backdrop-blur-xl p-8 sm:p-12 shadow-[0_8px_40px_-12px_rgba(0,0,0,0.1)] ring-1 ring-slate-200/50">
            <div className="mb-10 text-center sm:text-left">
              <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1.5 mb-5">
                <Settings2 className="h-3.5 w-3.5 text-[#0a52ff]" />
                <span className="text-[11px] font-bold uppercase tracking-wider text-[#0a52ff]">Live room setup</span>
              </div>
              <h1 className="font-display font-black text-4xl sm:text-5xl tracking-tighter text-slate-900">
                Set the <span className="font-serif-editorial font-normal italic tracking-normal text-[#0a52ff]">stage.</span>
              </h1>
              <p className="mt-4 text-[15px] leading-relaxed text-slate-500 max-w-lg mx-auto sm:mx-0">
                Pick a source, choose your models, and launch a real-time room that captions and translates for everyone.
              </p>
            </div>

            <div className="grid gap-8 lg:grid-cols-2">
              <div>
                <Label className="text-xs font-bold uppercase tracking-widest text-slate-400">
                  Input source
                </Label>
                <Tabs value={tab} onValueChange={setTab} className="mt-3">
                  <TabsList className="grid w-full grid-cols-3 h-12 rounded-full bg-slate-50 p-1 border border-slate-100">
                    <TabsTrigger value="mic" className="rounded-full data-[state=active]:bg-[#0a52ff] data-[state=active]:text-white transition-all duration-200">
                      <Mic className="mr-2 h-4 w-4" /> Mic
                    </TabsTrigger>
                    <TabsTrigger value="file" className="rounded-full data-[state=active]:bg-[#0a52ff] data-[state=active]:text-white transition-all duration-200">
                      <Upload className="mr-2 h-4 w-4" /> File
                    </TabsTrigger>
                    <TabsTrigger value="link" className="rounded-full data-[state=active]:bg-[#0a52ff] data-[state=active]:text-white transition-all duration-200">
                      <Link2 className="mr-2 h-4 w-4" /> Link
                    </TabsTrigger>
                  </TabsList>
                  
                  <div className="mt-4 min-h-[60px]">
                    <TabsContent value="mic" className="m-0">
                      <button
                        onClick={recording ? stopRecording : startRecording}
                        className={`flex w-full items-center justify-center gap-2 rounded-xl py-3.5 text-sm font-bold text-white transition-all shadow-md hover:opacity-90 ${
                          recording ? "bg-[#ef4444]" : "bg-[#0f172a]"
                        }`}
                      >
                        {recording ? (
                          <>
                            <Square className="h-4 w-4" /> Recording - {mmss}
                          </>
                        ) : (
                          <>
                            <Mic className="h-4 w-4" /> Tap to record from your mic
                          </>
                        )}
                      </button>
                    </TabsContent>

                    <TabsContent value="file" className="m-0">
                      {fileName ? (
                        <div className="relative flex w-full items-center justify-between rounded-2xl border border-[#0a52ff]/20 bg-[#0a52ff]/[0.02] p-4 px-5">
                          <div className="flex items-center gap-3 overflow-hidden">
                            <FileAudio className="h-5 w-5 text-[#0a52ff] shrink-0" />
                            <span className="truncate text-sm font-semibold text-slate-800">{fileName}</span>
                          </div>
                          <button
                            type="button"
                            onClick={() => { setFileName(""); toast("File removed"); }}
                            className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 shrink-0"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>
                      ) : (
                        <label className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-4 hover:border-[#0a52ff] hover:bg-blue-50/30 transition-all">
                          <Upload className="h-5 w-5 text-slate-400" />
                          <span className="text-sm font-medium text-slate-600">Select audio file...</span>
                          <input
                            type="file"
                            accept="audio/*,.mp3,.wav,.m4a,.ogg,.flac"
                            className="hidden"
                            onChange={(e) => {
                              const f = e.target.files?.[0];
                              if (f) { setFileName(f.name); setFileObj(f); toast.success(`Loaded ${f.name}`); }
                              e.target.value = "";
                            }}
                          />
                        </label>
                      )}
                    </TabsContent>

                    <TabsContent value="link" className="m-0">
                      <Input
                        value={link}
                        onChange={(e) => setLink(e.target.value)}
                        placeholder="Paste HLS .m3u8, Vimeo or Twitch URL..."
                        className="h-12 rounded-xl border-slate-200 px-4 focus-visible:ring-[#0a52ff]"
                      />
                    </TabsContent>
                  </div>
                </Tabs>

                <div className="mt-8 grid grid-cols-2 gap-4">
                  <div>
                    <Label className="text-xs font-bold uppercase tracking-widest text-slate-400">
                      Source language
                    </Label>
                    <Select value={sourceLang} onValueChange={setSourceLang}>
                      <SelectTrigger className="mt-3 h-11 rounded-xl">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SOURCE_LANGS.map((l) => (
                          <SelectItem key={l.code} value={l.code}>{l.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-xs font-bold uppercase tracking-widest text-slate-400">
                      Transcription
                    </Label>
                    <Select value={sttModel} disabled>
                      <SelectTrigger className="mt-3 h-11 rounded-xl">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="whisper_local">Whisper Local</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-4">
                <div className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm ring-1 ring-slate-100">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <Languages className="h-4 w-4 text-[#0a52ff]" />
                      <span className="font-semibold text-slate-900">Translation</span>
                    </div>
                    <Switch
                      checked={enableTranslation}
                      onCheckedChange={setEnableTranslation}
                      className="data-[state=checked]:bg-[#0a52ff]"
                    />
                  </div>
                  <AnimatePresence>
                    {enableTranslation && (
                      <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                        <div className="mt-5">
                          <Label className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                            Model
                          </Label>
                          <Select value={translationModel} onValueChange={setTranslationModel}>
                            <SelectTrigger className="mt-2 h-10 rounded-lg">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="nllb_local">NLLB Local</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                <div className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm ring-1 ring-slate-100">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <Volume2 className="h-4 w-4 text-[#0a52ff]" />
                      <span className="font-semibold text-slate-900">Text-to-speech</span>
                    </div>
                    <Switch
                      checked={enableTTS}
                      onCheckedChange={setEnableTTS}
                      className="data-[state=checked]:bg-[#0a52ff]"
                    />
                  </div>
                  <AnimatePresence>
                    {enableTTS && (
                      <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                        <div className="mt-5">
                          <Label className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                            Voice model
                          </Label>
                          <Select value={ttsModel} onValueChange={setTtsModel}>
                            <SelectTrigger className="mt-2 h-10 rounded-lg">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="supertonic">Supertonic</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </div>
            </div>

            <Button
              onClick={launchLiveRoom}
              className="mt-10 h-14 w-full rounded-full bg-[#0a52ff] text-base font-bold text-white hover:bg-[#0a52ff]/90 shadow-md shadow-blue-500/20"
            >
              <Play className="mr-2 h-5 w-5 fill-current" /> Launch live room <ArrowRight className="ml-1 h-5 w-5" />
            </Button>
          </div>
        </div>
      ) : roomState === "loading" ? (
        <div className="relative flex min-h-[calc(100vh-60px)] items-center justify-center overflow-hidden bg-slate-50 p-6">
          <div className="pointer-events-none absolute left-1/2 top-1/2 h-[800px] w-[800px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-400/20 opacity-60 blur-[120px] animate-pulse" />
          <div className="flex flex-col items-center justify-center relative z-10 space-y-6">
            <div className="w-48 h-48 -mb-4">
              <DotLottieReact
                src="https://lottie.host/d3ce39bd-5457-4f0d-bf5d-9f6147bd1117/Twl946zLQ0.lottie"
                loop
                autoplay
              />
            </div>
            <div className="text-center">
              <h2 className="text-2xl font-bold text-slate-900 mb-2">Preparing Live Room</h2>
              <p className="text-slate-500">{loadingMsg}</p>
            </div>
          </div>
        </div>
      ) : roomState === "live" ? (
        /* --- LIVE ROOM STEP --- */
        <div className="flex flex-col mx-auto max-w-[1600px] px-4 py-6 h-[calc(100vh-60px)]">
          <div className="mb-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex items-center gap-1.5 rounded-full bg-red-50 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider text-red-600">
                <span className="h-1.5 w-1.5 rounded-full bg-red-600 animate-pulse" /> LIVE
              </span>
              
              <div className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
                {tab === "mic" ? <Mic className="h-4 w-4 text-[#0a52ff]" /> : tab === "link" ? <Activity className="h-4 w-4 text-[#0a52ff]" /> : <FileAudio className="h-4 w-4 text-[#0a52ff]" />}
                {tab === "mic" ? "Microphone" : tab === "link" ? "Stream" : "Audio File"}
              </div>

              <div className="flex items-center gap-2 text-sm">
                <span className="text-slate-500">{SOURCE_LANGS.find(l => l.code === sourceLang)?.label || "English"}</span>
                <ArrowRight className="h-3.5 w-3.5 text-slate-300" />
                
                {enableTranslation ? (
                  <span className="text-slate-900 font-semibold text-sm">
                    {displayLang && displayLang !== 'original' ? TARGETS.find(t => t.code === displayLang)?.name : "Original"}
                  </span>
                ) : (
                  <span className="text-slate-400 text-xs italic">Translation off</span>
                )}
              </div>
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={reconfigureRoom}
              className="rounded-full font-semibold border-slate-200 text-slate-700 hover:bg-slate-50"
            >
              <Settings2 className="mr-1.5 h-4 w-4" /> Reconfigure
            </Button>
          </div>

          <div className="grid h-full grid-cols-1 lg:grid-cols-[1fr_450px] xl:grid-cols-[1fr_550px] gap-6 overflow-hidden pb-4">
            
            <div className="relative rounded-3xl overflow-hidden bg-[#030712] flex items-center justify-center shadow-lg">
              {tab === "link" && link && (
                <div className="absolute inset-0 w-full h-full">
                  <ReactPlayer
                    url={link}
                    playing={true}
                    controls
                    width="100%"
                    height="100%"
                    style={{ objectFit: "contain" }}
                  />
                </div>
              )}

              {tab === "mic" && (
                <div className="flex flex-col items-center justify-center gap-6 z-10 w-full h-full p-8">
                  <div className="flex items-center gap-1.5 h-16">
                    {[...Array(20)].map((_, i) => (
                      <motion.div
                        key={i}
                        animate={{ height: [10, Math.random() * 40 + 20, 10] }}
                        transition={{ repeat: Infinity, duration: 0.5 + Math.random() * 0.7 }}
                        className="w-2 rounded-full bg-[#0a52ff]"
                      />
                    ))}
                  </div>
                  <p className="text-slate-400 font-medium">Listening to your microphone...</p>
                </div>
              )}

              {tab === "file" && (
                <div className="flex flex-col items-center justify-center gap-5 z-10 w-full h-full p-8">
                  <div className="flex h-24 w-24 items-center justify-center rounded-full bg-[#0a52ff]/20">
                    <FileAudio className="h-12 w-12 text-[#0a52ff]" />
                  </div>
                  <div className="text-center">
                    <p className="text-xl font-bold text-white mb-1">{fileName}</p>
                    <p className="text-slate-400 font-medium">Processing audio file...</p>
                  </div>
                </div>
              )}

              {latestCaption?.en && (() => {
                const hasTranslation = enableTranslation && latestCaption.renderedLang && latestCaption.renderedLang !== 'original' && latestCaption.t?.[latestCaption.renderedLang];
                return (
                  <div className="absolute bottom-10 w-full px-12 text-center z-20 pointer-events-none flex flex-col items-center">
                    <p className={`${hasTranslation ? "text-xl md:text-2xl" : "text-2xl md:text-3xl"} font-semibold text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)] leading-tight transition-all`}>
                      {latestCaption.en}
                    </p>
                    {hasTranslation && (
                      <p dir={TARGETS.find(t => t.code === latestCaption.renderedLang)?.rtl ? "rtl" : "ltr"} className="mt-2 text-lg md:text-xl font-bold text-yellow-300 drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)] leading-tight transition-all">
                        {latestCaption.t[latestCaption.renderedLang]}
                      </p>
                    )}
                  </div>
                );
              })()}
            </div>

            <div className="flex flex-col overflow-hidden rounded-3xl bg-white border border-slate-200 shadow-sm">
              <div className="px-5 pt-4 pb-3 border-b border-slate-100 space-y-3">
                <div className="flex items-center gap-2">
                  <Settings2 className="h-4 w-4 text-[#0a52ff] rotate-90" />
                  <h3 className="font-display font-bold text-slate-900 text-sm">Captions & translations</h3>
                </div>

                <div className="flex items-center gap-2 py-1">
                  {enableTranslation && (
                    <div className={`min-w-0 transition-all duration-300 ease-in-out ${enableTTS ? "flex-[1.2]" : "flex-1"}`}>
                      <Select value={displayLang} onValueChange={setDisplayLang}>
                        <SelectTrigger className="h-8 rounded-lg text-xs border-slate-200 bg-slate-50 w-full focus:ring-0 focus:ring-offset-0 transition-all duration-300">
                          <SelectValue placeholder="Select language" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="original">Original</SelectItem>
                          {TARGETS.map((t) => (
                            <SelectItem key={t.code} value={t.code}>
                              {t.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  <AnimatePresence>
                    {enableTTS && (
                      <motion.div
                        initial={{ opacity: 0, width: 0, marginLeft: -8 }}
                        animate={{ opacity: 1, width: "auto", marginLeft: 0 }}
                        exit={{ opacity: 0, width: 0, marginLeft: -8 }}
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                        className="flex-1 min-w-0 overflow-hidden"
                      >
                        <div className="min-w-[120px]">
                          <Select value={ttsVoice} onValueChange={setTtsVoice}>
                            <SelectTrigger className="h-8 rounded-lg text-xs border-slate-200 bg-slate-50 w-full focus:ring-0 focus:ring-offset-0">
                              <SelectValue placeholder="Voice" />
                            </SelectTrigger>
                            <SelectContent>
                              {TTS_VOICES.map((v) => (
                                <SelectItem key={v.value} value={v.value}>
                                  {v.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  <div className="flex items-center gap-1.5 shrink-0 pl-1">
                    <Volume2 className="h-3.5 w-3.5 text-slate-500" />
                    <span className="text-xs font-medium text-slate-600">TTS</span>
                    <Switch
                      checked={enableTTS}
                      onCheckedChange={setEnableTTS}
                      className="data-[state=checked]:bg-[#0a52ff] scale-90"
                    />
                  </div>
                </div>
              </div>

              <div ref={feedRef} className="flex-1 overflow-y-auto p-5 space-y-6">
                {feed.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-full text-slate-400 py-10">
                    <Loader2 className="h-8 w-8 animate-spin mb-4 text-slate-300" />
                    <p className="text-sm">Connecting to stream...</p>
                  </div>
                )}
                {feed.map((seg, idx) => {
                  if (!seg) return null;
                  return (
                    <motion.div key={idx} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="group">
                      <p className="text-base font-semibold text-slate-900 mb-3">{seg.en}</p>

                      {enableTranslation && seg.renderedLang && seg.renderedLang !== 'original' && seg.t?.[seg.renderedLang] && (
                        <div className="rounded-2xl bg-slate-50 px-4 py-3 border border-slate-100/80">
                          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">
                            {TARGETS.find(t => t.code === seg.renderedLang)?.name ?? seg.renderedLang}
                          </div>
                          <p dir={TARGETS.find(t => t.code === seg.renderedLang)?.rtl ? "rtl" : "ltr"} className="text-sm font-medium text-slate-800">
                            {seg.t[seg.renderedLang]}
                          </p>
                        </div>
                      )}
                    </motion.div>
                  );
                })}
              </div>
            </div>

          </div>
        </div>
      ) : null}
    </div>
  );
}