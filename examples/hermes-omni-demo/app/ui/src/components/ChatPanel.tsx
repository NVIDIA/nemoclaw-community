import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowUp,
  Loader2,
  Paperclip,
  Sparkles,
  Square,
  Film,
  AudioLines,
  FileText,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatEvent, streamChat } from "../api/client";
import { AudioRecorder } from "./AudioRecorder";

export type ChatHandle = {
  send: (prompt: string) => void;
  attach: (src: string, label: string, kind: "video" | "audio" | "document") => void;
};

type Message =
  | { role: "user" | "assistant" | "status" | "tool" | "error"; text: string; ts: number }
  | {
      role: "exec";
      cmd: string;
      duration: string;
      exit: number;
      ts: number;
      text?: undefined;
    }
  | {
      role: "attachment";
      src: string;
      label: string;
      kind: "video" | "audio" | "document";
      ts: number;
      text?: undefined;
    };

const VIDEO_PROMPTS = [
  "Summarize this video",
  "Who's speaking, and where?",
  "List any technical terms",
  "Try fetching google.com (it should be blocked)",
];

const AUDIO_PROMPTS = [
  "Transcribe this recording",
  "What's the main topic?",
  "Summarize the speaker's key points",
  "List any names or places mentioned",
];

const DOC_PROMPTS = [
  "Summarize this document",
  "List the key facts",
  "Who or what is mentioned by name?",
  "Extract any numbers, dates, or specs",
];

type Props = {
  videoPath: string | null;
  mediaKind?: "video" | "audio" | "document";
  onEvent?: (e: ChatEvent | { type: "start"; prompt: string }) => void;
  onPickFile?: (file: File) => void;
  onVoice?: (text: string) => void;
  uploading?: boolean;
};

export const ChatPanel = forwardRef<ChatHandle, Props>(function ChatPanel(
  { videoPath, mediaKind = "video", onEvent, onPickFile, onVoice, uploading },
  ref
) {
  const quickPrompts =
    mediaKind === "audio"
      ? AUDIO_PROMPTS
      : mediaKind === "document"
      ? DOC_PROMPTS
      : VIDEO_PROMPTS;
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sessionIdRef = useRef<string | null>(null);
  // When the user drops a new file (different path from the last one we
  // sent against), we force the next /api/chat to start a fresh Hermes
  // session. Otherwise --continue makes Hermes summarize the prior file.
  const lastSentVideoPathRef = useRef<string | null>(null);
  const freshAttachmentRef = useRef<boolean>(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const disposerRef = useRef<(() => void) | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  useEffect(() => () => disposerRef.current?.(), []);

  useImperativeHandle(ref, () => ({
    send: (prompt: string) => send(prompt),
    attach: (src: string, label: string, kind: "video" | "audio" | "document") => {
      // Mark this as a fresh attachment so the next /api/chat starts a
      // new Hermes session — otherwise --continue makes the agent
      // summarize the prior file instead of running the analyzer on
      // this one (multi-attachment context bleed).
      freshAttachmentRef.current = true;
      setMessages((m) => [
        ...m,
        { role: "attachment", src, label, kind, ts: Date.now() },
      ]);
    },
  }));

  const stop = () => {
    disposerRef.current?.();
    disposerRef.current = null;
    setLoading(false);
    setMessages((m) => {
      const last = m[m.length - 1];
      if (last && last.role === "assistant" && !last.text.trim()) {
        return m.slice(0, -1);
      }
      return m;
    });
  };

  const send = (override?: string) => {
    const prompt = (override ?? input).trim();
    // Hard-block sending while a file upload is still in flight, so the
    // server gets the new sandbox_path before the chat call composes its
    // prompt. Without this, the user can attach a file and hit Enter
    // before /api/upload completes, the prompt goes out with a stale
    // (or null) video_path, and Hermes politely answers "no file
    // attached" — confusing, since the file is visible in the UI.
    if (!prompt || loading || uploading) return;
    setInput("");
    setLoading(true);
    const ts = Date.now();
    setMessages((m) => [
      ...m,
      { role: "user", text: prompt, ts },
      { role: "assistant", text: "", ts },
    ]);
    onEvent?.({ type: "start", prompt });

    // Force a new Hermes session if this turn carries a freshly-dropped
    // file that wasn't in the prior turn. Stops Hermes from answering
    // about the OLD file when the user uploads a NEW one mid-session.
    const isFreshFile =
      freshAttachmentRef.current ||
      (videoPath !== null && videoPath !== lastSentVideoPathRef.current);
    freshAttachmentRef.current = false;
    if (isFreshFile) {
      sessionIdRef.current = null;
    }
    lastSentVideoPathRef.current = videoPath;

    disposerRef.current = streamChat(
      prompt,
      videoPath,
      (e: ChatEvent) => {
      onEvent?.(e);
      if (e.type === "session") {
        sessionIdRef.current = e.id;
      }
      if (e.type === "token") {
        setMessages((m) => {
          const copy: Message[] = [...m];
          for (let i = copy.length - 1; i >= 0; i--) {
            const cur = copy[i];
            if (cur.role === "assistant") {
              copy[i] = { ...cur, text: cur.text + e.text };
              return copy;
            }
          }
          copy.push({ role: "assistant", text: e.text, ts: Date.now() });
          return copy;
        });
      } else if (e.type === "tool") {
        // If the previous bubble is an empty assistant placeholder, pull it
        // out before inserting the tool pill — otherwise it hangs around
        // forever as a ghost "Thinking…" row.
        setMessages((m) => {
          const trimmed =
            m.length &&
            m[m.length - 1].role === "assistant" &&
            !m[m.length - 1].text?.trim()
              ? m.slice(0, -1)
              : m;
          return [
            ...trimmed,
            { role: "tool", text: e.tool, ts: Date.now() },
            { role: "assistant", text: "", ts: Date.now() },
          ];
        });
      } else if (e.type === "exec") {
        setMessages((m) => [
          ...m,
          {
            role: "exec",
            cmd: e.cmd,
            duration: e.duration,
            exit: e.exit,
            ts: Date.now(),
          },
        ]);
      } else if (e.type === "status") {
        // Dedupe consecutive identical status pills
        setMessages((m) => {
          const last = m[m.length - 1];
          if (last && last.role === "status" && last.text === e.text) return m;
          return [...m, { role: "status", text: e.text, ts: Date.now() }];
        });
      } else if (e.type === "error") {
        // Prominent error card — preserves multi-line output from the
        // backend (e.g. last 20 lines of hermes stdout when the run
        // produced no visible answer).
        setMessages((m) => {
          // Drop any trailing empty assistant placeholder so the error
          // doesn't appear below a "Thinking…" ghost row.
          const trimmed =
            m.length &&
            m[m.length - 1].role === "assistant" &&
            !m[m.length - 1].text?.trim()
              ? m.slice(0, -1)
              : m;
          return [...trimmed, { role: "error", text: e.error, ts: Date.now() }];
        });
        setLoading(false);
      } else if (e.type === "done") {
        setMessages((m) => {
          const last = m[m.length - 1];
          if (last && last.role === "assistant" && !last.text.trim()) {
            return m.slice(0, -1);
          }
          return m;
        });
        setLoading(false);
      }
    },
    sessionIdRef.current,
    isFreshFile, // new_session: true forces /api/chat to drop --continue
    );
  };

  const resetConversation = () => {
    disposerRef.current?.();
    disposerRef.current = null;
    sessionIdRef.current = null;
    setMessages([]);
    setLoading(false);
  };

  return (
    <div className="surface flex w-full flex-col overflow-hidden">
      {/* thin header with session + new-chat */}
      <div className="flex items-center justify-between border-b border-white/5 px-6 py-2.5">
        <div className="flex items-center gap-2 text-[11.5px] text-ink-400">
          <span className="h-1.5 w-1.5 rounded-full bg-nv" />
          <span>
            {sessionIdRef.current ? (
              <>
                Continuing session{" "}
                <span className="font-mono text-ink-300">
                  {sessionIdRef.current.slice(-8)}
                </span>
              </>
            ) : (
              "New conversation"
            )}
          </span>
        </div>
        {messages.length > 0 && (
          <button
            onClick={resetConversation}
            className="rounded-md px-2 py-1 text-[11.5px] text-ink-400 transition hover:bg-white/5 hover:text-nv"
          >
            New chat
          </button>
        )}
      </div>
      {/* transcript */}
      <div ref={scrollRef} className="flex-1 space-y-6 overflow-y-auto px-8 py-7">
        {messages.length === 0 ? (
          <EmptyState onPick={(p) => send(p)} prompts={quickPrompts} mediaKind={mediaKind} />
        ) : (
          <AnimatePresence initial={false}>
            {messages.map((msg, i) => (
              <MessageRow key={i} msg={msg} isLast={i === messages.length - 1} loading={loading} />
            ))}
          </AnimatePresence>
        )}
      </div>

      {/* input */}
      <div className="border-t border-white/5 p-5">
        <input
          ref={fileInputRef}
          type="file"
          accept="video/*,audio/*,application/pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onPickFile?.(f);
            e.target.value = "";
          }}
        />
        <div className="chat-input flex items-center gap-2 px-3 py-2.5">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-ink-300 transition hover:bg-white/5 hover:text-nv disabled:opacity-40"
            title="Attach video or audio"
          >
            {uploading ? (
              <Loader2 className="h-4 w-4 animate-spin text-nv" />
            ) : (
              <Paperclip className="h-[18px] w-[18px]" />
            )}
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={
              uploading
                ? "Uploading… hold on a sec"
                : "Ask about a video, audio, or PDF — drag one in"
            }
            disabled={loading || uploading}
          />
          {onVoice && (
            <AudioRecorder onTranscribed={onVoice} disabled={uploading} />
          )}
          {loading ? (
            <button
              onClick={stop}
              className="btn-send flex h-9 w-9 items-center justify-center"
              aria-label="Stop generating"
              title="Stop"
            >
              <Square className="h-3.5 w-3.5" fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={() => send()}
              disabled={!input.trim()}
              className="btn-send flex h-9 w-9 items-center justify-center"
              aria-label="Send"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
        <div className="mt-2 px-2 text-[11px] text-ink-400">
          {loading ? "Omni is thinking · click ■ to stop" : "Enter to send · videos up to ~9 MB"}
        </div>
      </div>
    </div>
  );
});

function EmptyState({
  onPick,
  prompts,
  mediaKind,
}: {
  onPick: (p: string) => void;
  prompts: string[];
  mediaKind: "video" | "audio" | "document";
}) {
  const noun =
    mediaKind === "audio"
      ? "recording"
      : mediaKind === "document"
      ? "document"
      : "video";
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: 0.15 }}
      className="flex h-full flex-col items-center justify-center gap-6 py-10 text-center"
    >
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.2, type: "spring", damping: 16 }}
        className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-nv/25 to-nv/5 text-nv"
      >
        <Sparkles className="relative z-10 h-6 w-6" />
        <motion.div
          animate={{ scale: [1, 1.4, 1], opacity: [0.5, 0, 0.5] }}
          transition={{ duration: 2.2, repeat: Infinity }}
          className="absolute inset-0 rounded-2xl border border-nv/40"
        />
      </motion.div>
      <div className="space-y-1.5">
        <div className="text-[18px] font-semibold text-white">
          Ask Omni about a {noun}
        </div>
        <div className="text-[14px] text-ink-300 max-w-sm">
          Drop an mp4, audio, or PDF anywhere on the page, or click the paperclip. Use the mic to speak your question.
        </div>
      </div>
      <div className="flex w-full max-w-md flex-col gap-2">
        {prompts.map((p, i) => (
          <motion.button
            key={p}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 + i * 0.05 }}
            whileHover={{ x: 2 }}
            onClick={() => onPick(p)}
            className="group relative flex w-full items-center justify-between overflow-hidden rounded-xl border border-white/6 bg-ink-900 px-4 py-3 text-left text-[15px] text-ink-100 transition-all hover:border-nv/60 hover:bg-gradient-to-r hover:from-ink-800 hover:to-nv/5"
          >
            <span className="relative z-10">{p}</span>
            <span className="relative z-10 text-ink-400 transition-colors group-hover:text-nv">↵</span>
            <span
              aria-hidden
              className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-nv opacity-0 transition-opacity group-hover:opacity-100"
            />
          </motion.button>
        ))}
      </div>
    </motion.div>
  );
}

function MessageRow({
  msg,
  isLast,
  loading,
}: {
  msg: Message;
  isLast: boolean;
  loading: boolean;
}) {
  if (msg.role === "attachment") {
    return <AttachmentBubble src={msg.src} label={msg.label} kind={msg.kind} />;
  }
  if (msg.role === "exec") {
    return <ExecCard cmd={msg.cmd} duration={msg.duration} exit={msg.exit} />;
  }
  if (msg.role === "status") {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center justify-center gap-2 text-[12px] text-ink-400"
      >
        <span className="h-1 w-1 rounded-full bg-ink-400" />
        {msg.text}
      </motion.div>
    );
  }
  if (msg.role === "error") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-xl border border-danger/40 bg-danger/5 p-4 text-[13px]"
      >
        <div className="mb-2 flex items-center gap-2 text-danger">
          <span className="h-1.5 w-1.5 rounded-full bg-danger" />
          <span className="font-semibold">Error</span>
        </div>
        <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-snug text-ink-100">
          {msg.text}
        </pre>
      </motion.div>
    );
  }
  if (msg.role === "tool") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-center"
      >
        <div className="flex items-center gap-2 rounded-full border border-nv/30 bg-nv/5 px-3 py-1 text-[11px] font-medium text-nv">
          <span className="h-1.5 w-1.5 rounded-full bg-nv animate-pulse-soft" />
          Using {msg.text}
        </div>
      </motion.div>
    );
  }
  if (msg.role === "user") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex justify-end"
      >
        <div className="bubble-user max-w-[75%] px-5 py-3 text-[16px] leading-relaxed text-white">
          {msg.text}
        </div>
      </motion.div>
    );
  }

  const streaming = isLast && loading;
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex justify-start"
    >
      <div className="bubble-ai max-w-[82%] px-5 py-3.5 text-[16px] leading-relaxed text-ink-100">
        {msg.text ? (
          <div className="md">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
            {streaming && <span className="stream-caret" />}
          </div>
        ) : (
          <span className="inline-flex items-center gap-2 text-ink-300">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-nv" />
            Thinking…
          </span>
        )}
      </div>
    </motion.div>
  );
}

function ExecCard({
  cmd,
  duration,
  exit,
}: {
  cmd: string;
  duration: string;
  exit: number;
}) {
  const failed = exit !== 0;
  // Shortened display: strip common prefixes so the interesting part is visible
  const display = cmd
    .replace(/^python3\s+/, "")
    .replace(/\/sandbox\/\.hermes-data\/workspace\//, "");
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex"
    >
      <div
        className={`w-full overflow-hidden rounded-xl border font-mono text-[12px] ${
          failed
            ? "border-danger/40 bg-danger/5"
            : "border-white/8 bg-ink-900/70"
        }`}
      >
        <div className="flex items-center justify-between px-3 py-1.5 text-[10px] uppercase tracking-wide text-ink-400">
          <div className="flex items-center gap-2">
            <span className={failed ? "text-danger" : "text-nv"}>
              {failed ? "●" : "▸"}
            </span>
            <span>ran in sandbox</span>
            <span className="text-white/20">·</span>
            <span>{duration}</span>
            {failed && (
              <>
                <span className="text-white/20">·</span>
                <span className="text-danger">exit {exit}</span>
              </>
            )}
          </div>
          <span className="text-ink-500">terminal</span>
        </div>
        <div className="flex items-start gap-2 border-t border-white/5 bg-black/30 px-3 py-2">
          <span className={failed ? "text-danger" : "text-nv"}>$</span>
          <span className="flex-1 break-all text-ink-100">{display}</span>
        </div>
      </div>
    </motion.div>
  );
}

function AttachmentBubble({
  src,
  label,
  kind,
}: {
  src: string;
  label: string;
  kind: "video" | "audio" | "document";
}) {
  const Icon = kind === "audio" ? AudioLines : kind === "document" ? FileText : Film;
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96, y: 8 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: "spring", damping: 22, stiffness: 300 }}
      className="flex justify-end"
    >
      <div className="overflow-hidden rounded-2xl border border-nv/30 bg-ink-800/80 shadow-soft w-[min(520px,75%)]">
        <div className="flex items-center gap-2 border-b border-white/5 px-3 py-2">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-nv/20 text-nv">
            <Icon className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0 flex-1 truncate text-[13px] font-medium text-white">
            {label}
          </div>
          <div className="shrink-0 text-[11px] text-nv/80">attached · {kind}</div>
        </div>
        {kind === "audio" ? (
          <div className="bg-ink-900/80 p-3">
            <audio src={src} controls className="w-full" />
          </div>
        ) : kind === "document" ? (
          <div className="flex items-center gap-3 bg-ink-900/80 px-4 py-5">
            <div className="flex h-14 w-11 shrink-0 items-center justify-center rounded-md border border-nv/30 bg-nv/10 text-nv">
              <FileText className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-[15px] font-semibold text-white">
                {label}
              </div>
              <div className="mt-0.5 text-[12px] text-ink-300">
                PDF · rendered pages sent to Omni as images
              </div>
            </div>
          </div>
        ) : (
          <div className="bg-black">
            <video
              src={src}
              controls
              playsInline
              className="block w-full max-h-[360px]"
            />
          </div>
        )}
      </div>
    </motion.div>
  );
}
