import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Shield,
  ShieldAlert,
  X,
  Globe,
  Lock,
  Loader2,
  Zap,
  PlayCircle,
  Check,
  AlertTriangle,
} from "lucide-react";
import {
  getPolicyRules,
  getToggles,
  setToggle,
  runRedTeam,
  type DemoToggle,
  type PolicyHost,
  type RedTeamEvent,
} from "../api/client";

type Props = {
  open: boolean;
  onClose: () => void;
};

const BLOCK_LABEL: Record<string, string> = {
  nvidia: "NVIDIA inference",
  wikipedia: "Wikipedia",
  free_dictionary: "Free Dictionary",
  pypi: "Python package index",
  brew: "Homebrew",
  huggingface: "Hugging Face",
  nous_research: "Nous Research",
  telegram: "Telegram",
  discord: "Discord",
  claude_code: "Claude",
  github: "GitHub",
  brave: "Brave Search",
  npm: "npm registry",
  demo_google_toggle: "Google (toggle)",
  demo_openai_toggle: "OpenAI (toggle)",
  demo_stackoverflow_toggle: "Stack Overflow (toggle)",
  demo_reddit_toggle: "Reddit (toggle)",
  demo_youtube_toggle: "YouTube (toggle)",
};

type RedTeamRow = {
  name: string;
  url: string;
  state: "pending" | "running" | "done";
  blocked?: boolean;
  http_code?: string;
  duration_ms?: number;
};

export function PolicyDrawer({ open, onClose }: Props) {
  const [hosts, setHosts] = useState<PolicyHost[] | null>(null);
  const [toggles, setToggles] = useState<DemoToggle[]>([]);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Red team state
  const [rtRunning, setRtRunning] = useState(false);
  const [rtRows, setRtRows] = useState<RedTeamRow[]>([]);

  async function refresh() {
    setLoading(true);
    try {
      const [rules, toggleData] = await Promise.all([
        getPolicyRules(),
        getToggles(),
      ]);
      setHosts(rules.hosts);
      setToggles(toggleData);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) refresh();
  }, [open]);

  async function onFlip(key: string, enabled: boolean) {
    setPendingKey(key);
    try {
      await setToggle(key, enabled);
      setToggles((ts) =>
        ts.map((t) => (t.key === key ? { ...t, enabled } : t))
      );
      // Refresh the host list so the new block appears
      const rules = await getPolicyRules();
      setHosts(rules.hosts);
    } catch (e) {
      alert("toggle failed: " + (e as Error).message);
    } finally {
      setPendingKey(null);
    }
  }

  function startRedTeam() {
    if (rtRunning) return;
    setRtRunning(true);
    setRtRows([]);
    runRedTeam((ev: RedTeamEvent) => {
      if (ev.type === "start") {
        setRtRows([]);
      } else if (ev.type === "running") {
        setRtRows((r) => {
          const existing = r.find((row) => row.url === ev.url);
          if (existing) {
            return r.map((row) =>
              row.url === ev.url ? { ...row, state: "running" } : row
            );
          }
          return [...r, { name: ev.name, url: ev.url, state: "running" }];
        });
      } else if (ev.type === "result") {
        setRtRows((r) =>
          r.map((row) =>
            row.url === ev.url
              ? {
                  ...row,
                  state: "done",
                  blocked: ev.blocked,
                  http_code: ev.http_code,
                  duration_ms: ev.duration_ms,
                }
              : row
          )
        );
      } else if (ev.type === "done") {
        setRtRunning(false);
      }
    });
  }

  const grouped = groupByBlock(hosts || []);

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
            className="fixed right-0 top-0 z-50 flex h-screen w-full max-w-[520px] flex-col border-l border-white/8 bg-ink-900 shadow-2xl"
          >
            {/* HEADER */}
            <header className="flex shrink-0 items-center justify-between border-b border-white/6 px-6 py-5">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-nv/15 text-nv">
                  <Shield className="h-[18px] w-[18px]" />
                </div>
                <div>
                  <div className="text-[16px] font-semibold text-white">
                    Network policy
                  </div>
                  <div className="text-[12px] text-ink-300">
                    Hot-swap what the sandbox can reach
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
              {/* TOGGLES */}
              <section>
                <SectionTitle title="Hot-swap allow-list" subtitle="Flip hosts in or out of the live policy" />
                <div className="mt-3 space-y-2">
                  {toggles.map((t) => (
                    <ToggleRow
                      key={t.key}
                      toggle={t}
                      busy={pendingKey === t.key}
                      onFlip={() => onFlip(t.key, !t.enabled)}
                    />
                  ))}
                </div>
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-nv/20 bg-nv/5 px-3 py-2.5 text-[12px] text-ink-200">
                  <Zap className="mt-0.5 h-3.5 w-3.5 shrink-0 text-nv" />
                  <span>
                    Each flip hot-swaps the NemoClaw policy. Takes ~5-10s to propagate — the switch stays "applying" until the new policy is loaded.
                  </span>
                </div>
              </section>

              {/* RED TEAM */}
              <section>
                <div className="mb-3 flex items-center justify-between">
                  <SectionTitle
                    title="Security check"
                    subtitle="Fire curl at 7 URLs from inside the sandbox"
                  />
                </div>
                <button
                  onClick={startRedTeam}
                  disabled={rtRunning}
                  className={`group flex w-full items-center justify-between rounded-xl border px-4 py-3 transition ${
                    rtRunning
                      ? "border-nv/40 bg-nv/10"
                      : "border-nv/35 bg-nv/10 hover:border-nv hover:bg-nv/20"
                  } disabled:cursor-wait`}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                        rtRunning ? "bg-nv/30 text-nv" : "bg-nv text-black"
                      }`}
                    >
                      {rtRunning ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <PlayCircle className="h-4 w-4" />
                      )}
                    </div>
                    <div className="text-left">
                      <div className="text-[14px] font-semibold text-white">
                        {rtRunning ? "Running attempts…" : "Run security check"}
                      </div>
                      <div className="text-[11.5px] text-ink-300">
                        {rtRunning
                          ? "firing curl inside the sandbox"
                          : "observes each call hit the policy wall"}
                      </div>
                    </div>
                  </div>
                  {!rtRunning && <span className="text-[13px] text-nv">▸</span>}
                </button>

                {rtRows.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    <AnimatePresence initial={false}>
                      {rtRows.map((row) => (
                        <motion.div
                          key={row.url}
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-[12.5px] ${
                            row.state === "running"
                              ? "border-nv/40 bg-nv/8"
                              : row.blocked
                              ? "border-danger/30 bg-danger/5"
                              : "border-nv/30 bg-nv/5"
                          }`}
                        >
                          <div className="flex h-5 w-5 shrink-0 items-center justify-center">
                            {row.state === "running" ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin text-nv" />
                            ) : row.blocked ? (
                              <ShieldAlert className="h-3.5 w-3.5 text-danger" />
                            ) : (
                              <Check className="h-3.5 w-3.5 text-nv" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-[13px] text-white">
                              {row.name}
                            </div>
                            <div className="truncate font-mono text-[11px] text-ink-400">
                              $ curl {stripProto(row.url)}
                            </div>
                          </div>
                          <div className="shrink-0 text-right">
                            <div
                              className={`font-mono text-[11px] font-semibold ${
                                row.state === "running"
                                  ? "text-nv/80"
                                  : row.blocked
                                  ? "text-danger"
                                  : "text-nv"
                              }`}
                            >
                              {row.state === "running"
                                ? "…"
                                : row.blocked
                                ? "BLOCKED"
                                : "OK"}
                            </div>
                            <div className="font-mono text-[10px] text-ink-500">
                              {row.http_code !== undefined
                                ? `${row.http_code} · ${row.duration_ms}ms`
                                : ""}
                            </div>
                          </div>
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                )}
              </section>

              {/* ALLOWED HOSTS */}
              <section>
                <SectionTitle
                  title="Allowed hosts"
                  subtitle={hosts ? `${hosts.length} rules · deny by default` : ""}
                />
                {loading && !hosts ? (
                  <div className="mt-3 flex items-center gap-2 text-[13px] text-ink-300">
                    <Loader2 className="h-4 w-4 animate-spin text-nv" />
                    reading live policy…
                  </div>
                ) : (
                  <div className="mt-3 space-y-2">
                    {Object.entries(grouped).map(([block, items], i) => (
                      <motion.div
                        key={block}
                        initial={{ opacity: 0, y: 3 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.02 }}
                        className={`rounded-xl border p-3 ${
                          block.startsWith("demo_")
                            ? "border-nv/50 bg-nv/5"
                            : "border-white/5 bg-ink-800"
                        }`}
                      >
                        <div className="mb-1.5 flex items-center gap-2">
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              block.startsWith("demo_")
                                ? "bg-nv animate-pulse-soft"
                                : "bg-nv/70"
                            }`}
                          />
                          <div className="text-[12.5px] font-semibold text-white">
                            {BLOCK_LABEL[block] || block}
                          </div>
                        </div>
                        <ul className="space-y-0.5">
                          {items.map((h) => (
                            <li
                              key={`${h.host}-${h.port}`}
                              className="text-[11.5px]"
                            >
                              <div className="flex items-baseline justify-between gap-2">
                                <span className="truncate font-mono text-nv/90">
                                  {h.host}
                                </span>
                                <span className="shrink-0 text-ink-400">
                                  :{h.port}
                                </span>
                              </div>
                            </li>
                          ))}
                        </ul>
                      </motion.div>
                    ))}
                  </div>
                )}
              </section>

              {/* Deny footer */}
              <div className="flex items-start gap-2 rounded-xl border border-danger/20 bg-danger/5 p-3">
                <ShieldAlert className="mt-0.5 h-4 w-4 text-danger" />
                <div className="text-[12.5px] leading-relaxed text-ink-200">
                  <span className="font-medium text-danger">
                    Deny by default.
                  </span>{" "}
                  Any host or binary not explicitly allowed returns a 403 at the L7 proxy, even from inside a running agent.
                </div>
              </div>
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

function ToggleRow({
  toggle,
  busy,
  onFlip,
}: {
  toggle: DemoToggle;
  busy: boolean;
  onFlip: () => void;
}) {
  return (
    <motion.button
      type="button"
      onClick={busy ? undefined : onFlip}
      disabled={busy}
      whileHover={{ scale: busy ? 1 : 1.005 }}
      whileTap={{ scale: busy ? 1 : 0.99 }}
      animate={{
        borderColor: toggle.enabled
          ? "rgba(118,185,0,0.7)"
          : "rgba(255,255,255,0.08)",
        backgroundColor: toggle.enabled
          ? "rgba(118,185,0,0.1)"
          : "rgba(23,23,23,1)",
      }}
      className="group flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-3 text-left transition-colors hover:bg-white/5 disabled:cursor-wait"
    >
      <div className="flex min-w-0 items-center gap-3">
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors ${
            toggle.enabled ? "bg-nv text-black" : "bg-ink-700 text-ink-300"
          }`}
        >
          <Globe className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <div className="truncate text-[14px] font-semibold text-white">
            {toggle.name}
          </div>
          <div className="flex items-center gap-1 text-[11.5px] text-ink-400">
            {busy ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin text-nv" />
                <span className="text-nv">applying policy…</span>
              </>
            ) : toggle.enabled ? (
              <>
                <Zap className="h-3 w-3 text-nv" />
                <span className="text-nv">curl allowed</span>
              </>
            ) : (
              <>
                <Lock className="h-3 w-3 text-ink-400" />
                <span>blocked · click to enable</span>
              </>
            )}
          </div>
        </div>
      </div>
      <BigSwitch checked={toggle.enabled} busy={busy} />
    </motion.button>
  );
}

function BigSwitch({ checked, busy }: { checked: boolean; busy: boolean }) {
  return (
    <div
      className={`flex h-8 w-16 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold uppercase tracking-[0.18em] transition-colors ${
        checked
          ? "border-nv bg-nv/15 text-nv shadow-[0_0_0_1px_rgba(118,185,0,0.25),0_0_18px_-6px_rgba(118,185,0,0.6)]"
          : "border-white/15 bg-ink-700 text-ink-300 group-hover:border-white/30"
      } ${busy ? "opacity-60" : ""}`}
    >
      {busy ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <span>{checked ? "on" : "off"}</span>
      )}
    </div>
  );
}

function groupByBlock(hosts: PolicyHost[]): Record<string, PolicyHost[]> {
  const g: Record<string, PolicyHost[]> = {};
  for (const h of hosts) (g[h.block] ||= []).push(h);
  return g;
}

function stripProto(url: string): string {
  return url.replace(/^https?:\/\//, "");
}
