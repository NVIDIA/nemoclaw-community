import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Shield, Download, Brain } from "lucide-react";
import { ChatPanel, type ChatHandle } from "./components/ChatPanel";
import { PolicyTicker } from "./components/PolicyTicker";
import { PolicyDrawer } from "./components/PolicyDrawer";
import { MemoryDrawer } from "./components/MemoryDrawer";
import { FlowDiagram, type FlowNode } from "./components/FlowDiagram";
import { subscribePolicy, uploadFile } from "./api/client";

export default function App() {
  const [videoPath, setVideoPath] = useState<string | null>(null);
  const [mediaKind, setMediaKind] = useState<"video" | "audio" | "document">("video");
  const [uploading, setUploading] = useState(false);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [flowActive, setFlowActive] = useState<FlowNode>("idle");
  const [denyFlash, setDenyFlash] = useState(false);
  const [flowCaption, setFlowCaption] = useState<string | undefined>();
  const [uploadError, setUploadError] = useState<string | null>(null);

  const chatRef = useRef<ChatHandle>(null);
  const dragDepth = useRef(0);
  const denyTimerRef = useRef<number | null>(null);
  const idleTimerRef = useRef<number | null>(null);

  // Global drag-and-drop
  useEffect(() => {
    const isFileDrag = (e: DragEvent) =>
      !!e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files");
    const onDragEnter = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      dragDepth.current += 1;
      setDragOver(true);
    };
    const onDragLeave = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      dragDepth.current -= 1;
      if (dragDepth.current <= 0) {
        dragDepth.current = 0;
        setDragOver(false);
      }
    };
    const onDragOver = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
    };
    const onDrop = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      dragDepth.current = 0;
      setDragOver(false);
      const file = e.dataTransfer?.files?.[0];
      if (file) handleFile(file);
    };
    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("drop", onDrop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFile = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      // Guess kind from MIME or extension for the optimistic UI
      const isPdf =
        file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
      const optimisticKind: "audio" | "video" | "document" = isPdf
        ? "document"
        : file.type.startsWith("audio/")
        ? "audio"
        : "video";
      const localSrc = isPdf ? "" : URL.createObjectURL(file);
      chatRef.current?.attach(localSrc, file.name, optimisticKind);

      const result = await uploadFile(file);
      setVideoPath(result.sandbox_path);
      setMediaKind((result.kind as any) || optimisticKind);
    } catch (e: any) {
      // Surface the actual response body in a toast (auto-dismiss after 8s).
      // Was an `alert()` previously — UI now shows non-2xx upload errors
      // inline with full server-side detail so users see what failed.
      setUploadError(e?.message || String(e));
      window.setTimeout(() => setUploadError(null), 8000);
    } finally {
      setUploading(false);
    }
  };

  const handleVoice = (text: string) => {
    chatRef.current?.send(text);
  };

  // Policy stream for deny flashes
  useEffect(() => {
    return subscribePolicy((e) => {
      if (e.verdict === "DENIED") {
        setDenyFlash(true);
        if (denyTimerRef.current) clearTimeout(denyTimerRef.current);
        denyTimerRef.current = window.setTimeout(() => setDenyFlash(false), 1500);
      }
    });
  }, []);

  const handleChatEvent = (
    e:
      | { type: "start"; prompt: string }
      | { type: "token"; text: string }
      | { type: "tool"; tool: string }
      | { type: "status"; text: string }
      | { type: "exec"; cmd: string; duration: string; exit: number }
      | { type: "session"; id: string }
      | { type: "done" }
      | { type: "error"; error: string }
  ) => {
    if (e.type === "session") return;
    if (idleTimerRef.current) {
      clearTimeout(idleTimerRef.current);
      idleTimerRef.current = null;
    }
    if (e.type === "start") {
      setFlowActive("user");
      setFlowCaption("Sending your question");
      setTimeout(() => setFlowActive("hermes"), 350);
    } else if (e.type === "status") {
      setFlowActive("sandbox");
      setFlowCaption(e.text || "running inside sandbox");
    } else if (e.type === "tool") {
      setFlowActive("sandbox");
      setFlowCaption(`invoking ${e.tool}`);
    } else if (e.type === "exec") {
      setFlowActive("sandbox");
      setFlowCaption("running in sandbox");
    } else if (e.type === "token") {
      setFlowActive("omni");
      setFlowCaption("Omni is reasoning");
    } else if (e.type === "done" || e.type === "error") {
      idleTimerRef.current = window.setTimeout(() => {
        setFlowActive("idle");
        setFlowCaption(undefined);
      }, 900);
    }
  };

  return (
    <div className="relative min-h-screen font-sans text-ink-100">
      {/* atmosphere */}
      <div className="ambient-glow" />
      <div className="atmo-floor" />

      <PolicyDrawer open={policyOpen} onClose={() => setPolicyOpen(false)} />
      <MemoryDrawer open={memoryOpen} onClose={() => setMemoryOpen(false)} />

      {/* Upload error toast — surfaces non-2xx /api/upload responses */}
      <AnimatePresence>
        {uploadError && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className="fixed bottom-20 right-6 z-50 max-w-md rounded-xl border border-danger/40 bg-ink-900/95 p-4 shadow-glow backdrop-blur"
          >
            <div className="mb-1 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-[13px] font-semibold text-danger">
                <span className="h-1.5 w-1.5 rounded-full bg-danger" />
                Upload failed
              </div>
              <button
                onClick={() => setUploadError(null)}
                className="text-ink-300 hover:text-ink-100 text-lg leading-none"
                aria-label="Dismiss"
              >
                ×
              </button>
            </div>
            <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-snug text-ink-100">
              {uploadError}
            </pre>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Global drag overlay */}
      <AnimatePresence>
        {dragOver && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center bg-nv/10 backdrop-blur-sm"
          >
            <motion.div
              initial={{ scale: 0.94 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.94 }}
              className="relative mx-8 flex max-w-2xl flex-col items-center gap-4 rounded-3xl border-2 border-dashed border-nv bg-ink-900/90 p-14 shadow-glow"
            >
              <div className="absolute inset-4 rounded-2xl border border-nv/30" />
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-nv text-black">
                <Download className="h-8 w-8" strokeWidth={2.4} />
              </div>
              <div className="text-center">
                <div className="text-[22px] font-semibold text-white">
                  Drop to attach
                </div>
                <div className="mt-1 text-[14px] text-ink-300">
                  Video · audio · PDF — Omni sees all three
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="relative z-10 mx-auto flex min-h-screen max-w-[1180px] flex-col px-6 pb-16 pt-8">
        {/* HEADER */}
        <motion.header
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: "easeOut" }}
          className="mb-6 flex items-center justify-between"
        >
          <div className="flex items-center gap-3">
            <motion.div
              initial={{ scale: 0.6, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.05, type: "spring", damping: 14 }}
              className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-nv-bright to-nv shadow-glow"
            >
              <div className="h-3 w-3 rounded-[3px] bg-black" />
              <motion.div
                animate={{ opacity: [0.15, 0.5, 0.15] }}
                transition={{ duration: 2.8, repeat: Infinity }}
                className="absolute -inset-[3px] rounded-xl bg-nv/30 blur-md"
              />
            </motion.div>
            <div>
              <div className="text-[17px] font-semibold leading-tight text-white">
                Omni
              </div>
              <div className="text-[12px] leading-tight text-ink-300">
                Drop a video · speak a question · get an answer
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <motion.button
              onClick={() => setMemoryOpen(true)}
              whileHover={{ y: -1 }}
              whileTap={{ scale: 0.97 }}
              className="flex items-center gap-2 rounded-full border border-nv/30 bg-nv/5 px-3.5 py-1.5 text-[13px] font-medium text-nv transition hover:border-nv hover:bg-nv/15"
            >
              <Brain className="h-3.5 w-3.5" />
              <span>Memory</span>
            </motion.button>
            <motion.button
              onClick={() => setPolicyOpen(true)}
              whileHover={{ y: -1 }}
              whileTap={{ scale: 0.97 }}
              className="flex items-center gap-2 rounded-full border border-nv/30 bg-nv/5 px-3.5 py-1.5 text-[13px] font-medium text-nv transition hover:border-nv hover:bg-nv/15"
            >
              <Shield className="h-3.5 w-3.5" />
              <span>Policy</span>
            </motion.button>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.2 }}
              className="relative flex items-center gap-2 overflow-hidden rounded-full border border-nv/25 bg-ink-800/60 px-3.5 py-1.5 backdrop-blur"
            >
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-nv opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-nv" />
              </span>
              <span className="text-[12px] font-medium text-ink-100">
                Live · Nemotron Omni 30B
              </span>
              <span
                aria-hidden
                className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,transparent,rgba(118,185,0,0.18),transparent)] bg-[length:200%_100%] animate-shimmer"
              />
            </motion.div>
          </div>
        </motion.header>

        {/* FLOW DIAGRAM */}
        <div className="mb-6">
          <FlowDiagram
            active={flowActive}
            denyFlash={denyFlash}
            caption={flowCaption}
          />
        </div>

        {/* CHAT (the whole thing) */}
        <motion.main
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.12, ease: [0.2, 0.7, 0.2, 1] }}
          className="flex min-h-[640px] flex-1"
        >
          <ChatPanel
            ref={chatRef}
            videoPath={videoPath}
            mediaKind={mediaKind}
            onEvent={handleChatEvent}
            onPickFile={handleFile}
            onVoice={handleVoice}
            uploading={uploading}
          />
        </motion.main>
      </div>

      <motion.footer
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.5 }}
        className="ticker-shell fixed bottom-0 left-0 right-0 z-10"
      >
        <PolicyTicker />
      </motion.footer>
    </div>
  );
}
