import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Shield, ShieldAlert } from "lucide-react";
import { PolicyEvent, subscribePolicy } from "../api/client";

type AggEvent = PolicyEvent & { count: number };

export function PolicyTicker() {
  const [events, setEvents] = useState<PolicyEvent[]>([]);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const dispose = subscribePolicy((e) => {
      // Skip internal SSH handshake chatter — it's not interesting on camera
      if (e.target.includes("10.42.0.") || e.target.includes("NSSH1")) return;
      setEvents((prev) => [e, ...prev].slice(0, 60));
    });
    return dispose;
  }, []);

  // Collapse consecutive events with the same verdict + target into a single
  // entry with a count badge.
  const aggregated = useMemo<AggEvent[]>(() => {
    const out: AggEvent[] = [];
    for (const e of events) {
      const last = out[out.length - 1];
      if (last && last.verdict === e.verdict && last.target === e.target) {
        last.count += 1;
      } else {
        out.push({ ...e, count: 1 });
      }
    }
    return out.slice(0, 30);
  }, [events]);

  const allowed = events.filter((e) => e.verdict === "ALLOWED").length;
  const denied = events.filter((e) => e.verdict === "DENIED").length;
  const track = aggregated.length > 0 ? [...aggregated, ...aggregated] : [];

  return (
    <div className={`flex items-stretch ${collapsed ? "h-8" : "h-10"} transition-all`}>
      <div className="flex shrink-0 items-center gap-4 border-r border-white/5 px-5 text-[12px]">
        <span className="text-ink-300">NemoClaw policy</span>
        <div className="flex items-center gap-3 font-mono">
          <span className="flex items-center gap-1 text-nv">
            <Shield className="h-3 w-3" /> {allowed}
          </span>
          <span className="flex items-center gap-1 text-danger">
            <ShieldAlert className="h-3 w-3" /> {denied}
          </span>
        </div>
      </div>

      {!collapsed && (
        <div className="relative flex-1 overflow-hidden">
          {aggregated.length === 0 ? (
            <div className="flex h-full items-center px-5 text-[12px] text-ink-400">
              Awaiting network activity…
            </div>
          ) : (
            <div className="ticker-flow items-center px-5 py-2">
              {track.map((e, i) => (
                <TickerItem key={`${e.ts}-${i}`} e={e} />
              ))}
            </div>
          )}
          <div className="pointer-events-none absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-ink-900 to-transparent" />
          <div className="pointer-events-none absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-ink-900 to-transparent" />
        </div>
      )}

      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex shrink-0 items-center gap-1.5 border-l border-white/5 px-4 text-[11px] text-ink-400 transition hover:text-nv"
        title={collapsed ? "Show policy ticker" : "Hide policy ticker"}
      >
        {collapsed ? (
          <>
            <ChevronUp className="h-3 w-3" />
            <span>Show ticker</span>
          </>
        ) : (
          <>
            <ChevronDown className="h-3 w-3" />
            <span>Hide</span>
          </>
        )}
      </button>
    </div>
  );
}

function TickerItem({ e }: { e: AggEvent }) {
  const denied = e.verdict === "DENIED";
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[12px] ${
        denied ? "text-danger" : "text-ink-200"
      }`}
    >
      <span className={denied ? "text-danger" : "text-nv"}>●</span>
      <span className="font-medium">{denied ? "Blocked" : "Allowed"}</span>
      <span className="text-ink-400">{shortTarget(e.target)}</span>
      {e.count > 1 && (
        <span
          className={`rounded-full px-1.5 py-px text-[10px] font-mono ${
            denied ? "bg-danger/20 text-danger" : "bg-nv/15 text-nv"
          }`}
        >
          ×{e.count}
        </span>
      )}
    </span>
  );
}

function shortTarget(t: string): string {
  // Trim :443, strip path fragments
  return t.replace(/:443(?!\d)/, "").replace(/\s*\[auth:.+\]\s*/, "");
}
