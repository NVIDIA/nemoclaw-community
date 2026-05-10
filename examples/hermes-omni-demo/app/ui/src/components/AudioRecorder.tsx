import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Mic, Square, Loader2 } from "lucide-react";
import { transcribeAudio } from "../api/client";

type Props = {
  onTranscribed: (text: string) => void;
  disabled?: boolean;
};

export function AudioRecorder({ onTranscribed, disabled }: Props) {
  const [state, setState] = useState<"idle" | "recording" | "transcribing">("idle");
  const [elapsed, setElapsed] = useState(0);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => () => cleanup(), []);

  function cleanup() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  }

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const rec = new MediaRecorder(stream, { mimeType: mime });
      rec.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      rec.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: mime });
        cleanup();
        setState("transcribing");
        const file = new File([blob], `voice-${Date.now()}.webm`, { type: mime });
        try {
          const text = await transcribeAudio(file);
          if (text) onTranscribed(text);
          else alert("Nothing was transcribed — try recording a bit louder.");
        } catch (err) {
          alert("transcription failed: " + (err as Error).message);
        } finally {
          setState("idle");
          setElapsed(0);
        }
      };
      rec.start(250);
      recRef.current = rec;
      setState("recording");
      setElapsed(0);
      timerRef.current = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    } catch (err) {
      alert("microphone unavailable: " + (err as Error).message);
    }
  }

  function stop() {
    recRef.current?.stop();
  }

  if (state === "idle") {
    return (
      <button
        onClick={start}
        disabled={disabled}
        className="group flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-ink-900 transition hover:border-nv/60 hover:bg-nv/10 hover:text-nv disabled:cursor-not-allowed disabled:opacity-50"
        title="Voice dictation — speak a question about the video"
        aria-label="Voice"
      >
        <Mic className="h-[18px] w-[18px] text-ink-200 group-hover:text-nv" />
      </button>
    );
  }

  if (state === "recording") {
    return (
      <motion.button
        onClick={stop}
        initial={{ scale: 0.95 }}
        animate={{ scale: 1 }}
        className="flex h-11 shrink-0 items-center gap-2 rounded-xl bg-danger px-3 text-black"
        title="Stop and transcribe"
      >
        <span className="relative flex h-2.5 w-2.5 items-center justify-center">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-white" />
        </span>
        <Square className="h-3.5 w-3.5" fill="currentColor" />
        <span className="font-mono text-[13px] font-semibold tabular-nums">
          {fmt(elapsed)}
        </span>
      </motion.button>
    );
  }

  return (
    <div className="flex h-11 shrink-0 items-center gap-2 rounded-xl border border-nv/40 bg-nv/10 px-3 text-nv">
      <Loader2 className="h-4 w-4 animate-spin" />
      <span className="text-[13px] font-medium">transcribing…</span>
    </div>
  );
}

function fmt(s: number): string {
  const m = Math.floor(s / 60);
  const ss = s % 60;
  return `${m}:${ss.toString().padStart(2, "0")}`;
}
