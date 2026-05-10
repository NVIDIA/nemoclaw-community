import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Brain,
  X,
  MessageSquare,
  Wrench,
  Paperclip,
  Calendar,
  Loader2,
  Sparkles,
} from "lucide-react";
import {
  getMemorySummary,
  type MemorySummary,
  type MemorySession,
} from "../api/client";

type Props = {
  open: boolean;
  onClose: () => void;
};

export function MemoryDrawer({ open, onClose }: Props) {
  const [data, setData] = useState<MemorySummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    getMemorySummary(40)
      .then(setData)
      .catch((e) => console.error(e))
      .finally(() => setLoading(false));
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm"
          />
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 32, stiffness: 320 }}
            className="fixed right-0 top-0 z-50 flex h-screen w-full max-w-[540px] flex-col border-l border-white/8 bg-ink-900 shadow-2xl"
          >
            <header className="flex shrink-0 items-center justify-between border-b border-white/6 px-6 py-5">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-nv/15 text-nv">
                  <Brain className="h-[18px] w-[18px]" />
                </div>
                <div>
                  <div className="text-[16px] font-semibold text-white">
                    Memory
                  </div>
                  <div className="text-[12px] text-ink-300">
                    What you've asked Hermes across every session
                  </div>
                </div>
              </div>
              <button
                onClick={onClose}
                className="rounded-lg p-1.5 text-ink-300 transition hover:bg-white/5 hover:text-white"
                aria-label="Close"
              >
                <X className="h-5 w-5" />
              </button>
            </header>

            <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
              {loading && !data ? (
                <div className="flex items-center gap-2 py-4 text-[13px] text-ink-300">
                  <Loader2 className="h-4 w-4 animate-spin text-nv" />
                  reading session history…
                </div>
              ) : data ? (
                <>
                  {/* Stats grid */}
                  <section>
                    <SectionTitle title="At a glance" />
                    <div className="mt-3 grid grid-cols-2 gap-3">
                      <StatCard
                        icon={<Sparkles className="h-4 w-4" />}
                        value={data.stats.total_sessions}
                        label="sessions"
                      />
                      <StatCard
                        icon={<MessageSquare className="h-4 w-4" />}
                        value={data.stats.total_turns}
                        label="questions asked"
                      />
                      <StatCard
                        icon={<Wrench className="h-4 w-4" />}
                        value={data.stats.total_tool_calls}
                        label="tools invoked"
                      />
                      <StatCard
                        icon={<Paperclip className="h-4 w-4" />}
                        value={data.stats.total_attachments}
                        label="files attached"
                      />
                    </div>
                    {data.stats.oldest && (
                      <div className="mt-3 flex items-center gap-2 text-[12px] text-ink-400">
                        <Calendar className="h-3.5 w-3.5" />
                        first seen {fmtRel(data.stats.oldest)}
                      </div>
                    )}
                  </section>

                  {/* Top tools */}
                  <section>
                    <SectionTitle title="Tools Hermes used most" />
                    <div className="mt-3 space-y-1.5">
                      {data.top_tools.map((t) => {
                        const max = Math.max(...data.top_tools.map((x) => x.count));
                        const pct = max > 0 ? (t.count / max) * 100 : 0;
                        return (
                          <div key={t.name} className="relative">
                            <div className="absolute inset-0 overflow-hidden rounded-md">
                              <div
                                className="h-full bg-nv/10"
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <div className="relative flex items-center justify-between px-3 py-2">
                              <div className="text-[13px] text-white">{t.name}</div>
                              <div className="font-mono text-[11.5px] text-nv">
                                {t.count}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </section>

                  {/* Recent sessions */}
                  <section>
                    <SectionTitle
                      title="Recent conversations"
                      subtitle={`${data.recent.length} shown`}
                    />
                    <div className="mt-3 space-y-2">
                      {data.recent.map((s) => (
                        <SessionRow
                          key={s.id}
                          s={s}
                          expanded={expandedId === s.id}
                          onToggle={() =>
                            setExpandedId(expandedId === s.id ? null : s.id)
                          }
                        />
                      ))}
                    </div>
                  </section>
                </>
              ) : null}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-nv/70">
        {title}
      </div>
      {subtitle && <div className="text-[11px] text-ink-400">{subtitle}</div>}
    </div>
  );
}

function StatCard({
  icon,
  value,
  label,
}: {
  icon: React.ReactNode;
  value: number;
  label: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="relative overflow-hidden rounded-xl border border-white/6 bg-ink-800 px-4 py-3"
    >
      <div className="flex items-center gap-2 text-nv">
        {icon}
        <span className="text-[11px] uppercase tracking-[0.12em] text-nv/70">
          {label}
        </span>
      </div>
      <div className="mt-1 font-mono text-[26px] font-semibold leading-none text-white">
        {value}
      </div>
    </motion.div>
  );
}

function SessionRow({
  s,
  expanded,
  onToggle,
}: {
  s: MemorySession;
  expanded: boolean;
  onToggle: () => void;
}) {
  const preview = cleanPrompt(s.first_prompt) || "(no user messages)";
  return (
    <motion.div
      animate={{
        borderColor: expanded ? "rgba(118,185,0,0.4)" : "rgba(255,255,255,0.06)",
      }}
      className="overflow-hidden rounded-xl border bg-ink-800"
    >
      <button
        onClick={onToggle}
        className="group flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-white/5"
      >
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-nv/10 text-nv">
          <MessageSquare className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13.5px] font-medium text-white">
            {preview}
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-[11px] text-ink-400">
            <span>{fmtRel(s.updated || s.started)}</span>
            <span>·</span>
            <span>
              {s.turns} question{s.turns === 1 ? "" : "s"}
            </span>
            {s.tool_calls > 0 && (
              <>
                <span>·</span>
                <span>
                  {s.tool_calls} tool call{s.tool_calls === 1 ? "" : "s"}
                </span>
              </>
            )}
            {s.attachment_count > 0 && (
              <>
                <span>·</span>
                <span>
                  {s.attachment_count} attachment{s.attachment_count === 1 ? "" : "s"}
                </span>
              </>
            )}
          </div>
        </div>
        <div className="shrink-0 font-mono text-[10px] text-ink-500">
          {s.id.slice(-6)}
        </div>
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="space-y-2.5 border-t border-white/5 bg-ink-900/60 px-4 py-3 text-[12.5px]">
              <Row label="first" value={cleanPrompt(s.first_prompt)} />
              {s.last_prompt &&
                s.last_prompt !== s.first_prompt && (
                  <Row label="last" value={cleanPrompt(s.last_prompt)} />
                )}
              {s.tools.length > 0 && (
                <Row label="tools" value={s.tools.join(" · ")} mono />
              )}
              {s.model && <Row label="model" value={shortModel(s.model)} mono />}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  if (!value) return null;
  return (
    <div className="flex gap-3">
      <div className="w-10 shrink-0 font-mono text-[10px] uppercase tracking-wide text-nv/60">
        {label}
      </div>
      <div className={`flex-1 text-ink-100 ${mono ? "font-mono text-[11.5px]" : ""}`}>
        {value}
      </div>
    </div>
  );
}

function cleanPrompt(s: string): string {
  // Strip our orchestration preamble so the user's actual ask shows
  const marker = "User question:";
  const idx = s.indexOf(marker);
  if (idx >= 0) return s.slice(idx + marker.length).trim();
  return s.trim();
}

function shortModel(m: string): string {
  return m.replace(/^private\//, "").replace(/^nvidia\//, "");
}

function fmtRel(iso: string | null): string {
  if (!iso) return "unknown";
  try {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    const sec = Math.round(diff / 1000);
    if (sec < 60) return `${sec}s ago`;
    const min = Math.round(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const day = Math.round(hr / 24);
    if (day < 7) return `${day}d ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return iso.slice(0, 10);
  }
}
