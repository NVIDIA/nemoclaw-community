import { motion, AnimatePresence } from "framer-motion";
import { User, Cpu, Brain, Lock } from "lucide-react";

export type FlowNode = "idle" | "user" | "hermes" | "sandbox" | "omni";

type Props = {
  active: FlowNode;
  denyFlash: boolean;
  caption?: string;
};

const DEFAULT_CAPTIONS: Record<FlowNode, string> = {
  idle: "Ready · nothing in flight",
  user: "Sending your prompt",
  hermes: "Hermes asking Omni to pick a tool",
  sandbox: "Skill running · request crossing policy wall",
  omni: "Omni is analyzing and replying",
};

const DESCRIPTIONS: Record<FlowNode, string> = {
  idle:
    "Drop a video, audio, or PDF — then ask something. Nothing has left the sandbox yet.",
  user:
    "Your prompt is going into the NemoClaw sandbox. The sandbox is locked down with Landlock + seccomp + deny-by-default egress.",
  hermes:
    "Hermes doesn't reason on its own — it's calling Omni through the openshell gateway to decide which skill to invoke. This is the first of two Omni calls per turn.",
  sandbox:
    "Hermes picked a skill. Its script (video-analyze, jargon-lookup, …) is running inside the sandbox, and its outbound request is passing through the openshell policy wall. The key is injected here, never inside the sandbox.",
  omni:
    "Omni is seeing your attachment and streaming its answer back through the gateway. This is the second Omni call — with the actual media attached.",
};

const DENY_DESCRIPTION =
  "openshell blocked this request at the L7 proxy. Nothing left the sandbox — the policy allow-list doesn't include that destination.";

// Which visuals light up for each state.
// "primary" = the node is doing work
// "consulting" = the node is being queried but not the star of the moment
type Vis = { user: Heat; hermes: Heat; wall: Heat; omni: Heat };
type Heat = "off" | "consulting" | "primary" | "past";

const HEATMAP: Record<FlowNode, Vis> = {
  idle:    { user: "off",       hermes: "off",        wall: "off",        omni: "off" },
  user:    { user: "primary",   hermes: "off",        wall: "off",        omni: "off" },
  hermes:  { user: "past",      hermes: "primary",    wall: "off",        omni: "consulting" },
  sandbox: { user: "past",      hermes: "past",       wall: "primary",    omni: "consulting" },
  omni:    { user: "past",      hermes: "past",       wall: "past",       omni: "primary" },
};

export function FlowDiagram({ active, denyFlash, caption }: Props) {
  const description = denyFlash ? DENY_DESCRIPTION : DESCRIPTIONS[active];
  const effectiveCaption = caption || DEFAULT_CAPTIONS[active];
  const heat = HEATMAP[active];

  // Wire states
  const wireInToSandbox: WireState =
    active === "user"
      ? "traveling-right"
      : active === "hermes" || active === "sandbox" || active === "omni"
      ? "lit"
      : "off";
  // Sandbox ↔ Omni — bidirectional during hermes (ask/answer) and sandbox (outbound request), directional during omni (response streaming)
  const wireSandboxOmni: WireState =
    denyFlash
      ? "deny"
      : active === "hermes"
      ? "bidirectional"
      : active === "sandbox"
      ? "traveling-right"
      : active === "omni"
      ? "traveling-left"
      : "off";

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.25 }}
      className="relative overflow-hidden rounded-2xl border border-white/5 bg-gradient-to-b from-ink-900/60 to-ink-900/40 px-6 py-6 backdrop-blur"
    >
      {/* subtle grid */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.035]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.8) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.8) 1px, transparent 1px)",
          backgroundSize: "24px 24px",
        }}
      />

      <AnimatePresence>
        {denyFlash && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.5 }}
            className="pointer-events-none absolute inset-0 bg-danger/15"
          />
        )}
      </AnimatePresence>

      <div className="relative flex items-stretch gap-4">
        {/* YOU */}
        <Node
          label="You"
          sub="prompt"
          icon={<User className="h-4 w-4" />}
          heat={heat.user}
          tone="neutral"
        />

        <Wire state={wireInToSandbox} />

        {/* SANDBOX GROUP */}
        <motion.div
          animate={{
            borderColor: denyFlash
              ? "rgba(242,107,58,0.8)"
              : heat.hermes === "primary" || heat.wall === "primary"
              ? "rgba(118,185,0,0.85)"
              : "rgba(118,185,0,0.35)",
            boxShadow: denyFlash
              ? "0 0 0 1px rgba(242,107,58,0.4), 0 0 36px -10px rgba(242,107,58,0.5)"
              : heat.hermes === "primary" || heat.wall === "primary"
              ? "0 0 0 1px rgba(118,185,0,0.25), 0 0 42px -14px rgba(118,185,0,0.6)"
              : "0 0 0 1px rgba(118,185,0,0)",
          }}
          transition={{ duration: 0.4 }}
          className="relative flex flex-1 min-w-[340px] items-stretch rounded-2xl border bg-nv/[0.04] px-5 py-4"
        >
          <span
            className={`absolute -top-2.5 left-5 bg-ink-900 px-2 text-[10px] font-semibold uppercase tracking-[0.18em] ${
              denyFlash ? "text-danger" : heat.hermes !== "off" || heat.wall !== "off" ? "text-nv" : "text-nv/70"
            }`}
          >
            NemoClaw Sandbox
          </span>
          <div className="flex flex-1 items-center justify-between gap-3">
            <Node
              label="Hermes"
              sub="agent"
              icon={<Cpu className="h-4 w-4" />}
              heat={heat.hermes}
              tone="hermes"
            />

            <div className="relative mx-1 flex h-7 flex-1 items-center">
              <div
                className={`h-px flex-1 ${
                  heat.wall !== "off" || heat.omni !== "off"
                    ? "bg-gradient-to-r from-hermes to-nv"
                    : "bg-white/10"
                }`}
              />
            </div>

            <motion.div
              animate={{ scale: heat.wall === "primary" ? [1, 1.06, 1] : 1 }}
              transition={{ duration: 0.8, repeat: heat.wall === "primary" ? Infinity : 0 }}
              className={`flex flex-col items-center gap-1 rounded-lg border px-2.5 py-2 ${
                denyFlash
                  ? "border-danger/60 bg-danger/10 text-danger"
                  : heat.wall === "primary"
                  ? "border-nv bg-nv/15 text-white"
                  : heat.wall === "past"
                  ? "border-nv/40 bg-nv/8 text-nv"
                  : "border-nv/25 bg-nv/5 text-nv/80"
              }`}
            >
              <Lock className="h-3.5 w-3.5" />
              <div className="text-[10px] font-semibold uppercase tracking-wide">
                Policy
              </div>
              <div className="text-[9px] opacity-80">wall</div>
            </motion.div>
          </div>
        </motion.div>

        <Wire state={wireSandboxOmni} />

        {/* OMNI */}
        <Node
          label="Omni"
          sub="NVIDIA cloud"
          icon={<Brain className="h-4 w-4" />}
          heat={heat.omni}
          tone="neutral"
        />
      </div>

      {/* Caption */}
      <div className="relative mt-5 flex items-center justify-between gap-4 border-t border-white/5 pt-4">
        <div className="flex items-start gap-3">
          <div className="mt-[5px] flex h-2.5 w-2.5 shrink-0 items-center justify-center">
            <span
              className={`relative h-2 w-2 rounded-full ${
                denyFlash
                  ? "bg-danger"
                  : active === "idle"
                  ? "bg-ink-400"
                  : "bg-nv"
              }`}
            >
              {active !== "idle" && !denyFlash && (
                <span className="absolute inset-0 animate-ping rounded-full bg-nv opacity-60" />
              )}
            </span>
          </div>
          <AnimatePresence mode="wait">
            <motion.p
              key={description}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.22 }}
              className={`text-[14px] leading-relaxed ${
                denyFlash ? "text-danger/90" : "text-ink-200"
              }`}
            >
              {description}
            </motion.p>
          </AnimatePresence>
        </div>
        <div className="hidden shrink-0 md:block">
          <AnimatePresence mode="wait">
            <motion.span
              key={effectiveCaption}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2 }}
              className={`font-mono text-[11px] uppercase tracking-[0.18em] ${
                denyFlash ? "text-danger" : active === "idle" ? "text-ink-400" : "text-nv"
              }`}
            >
              {denyFlash ? "policy denied" : effectiveCaption}
            </motion.span>
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}

function Node({
  label,
  sub,
  icon,
  heat,
  tone = "neutral",
}: {
  label: string;
  sub: string;
  icon: React.ReactNode;
  heat: Heat;
  tone?: "neutral" | "hermes";
}) {
  const isHermes = tone === "hermes";

  const palettes = isHermes
    ? {
        primary:
          "border-hermes bg-hermes/20 text-white shadow-[0_0_0_1px_rgba(244,196,48,0.25),0_0_38px_-10px_rgba(244,196,48,0.65)]",
        consulting:
          "border-hermes/60 bg-hermes/12 text-hermes-bright",
        past: "border-hermes/50 bg-hermes/10 text-hermes-bright",
        off: "border-hermes/25 bg-hermes/[0.06] text-hermes/90",
        dot: "bg-hermes",
      }
    : {
        primary:
          "border-nv bg-nv/15 text-white shadow-[0_0_0_1px_rgba(118,185,0,0.25),0_0_38px_-10px_rgba(118,185,0,0.6)]",
        consulting:
          "border-nv/55 bg-nv/10 text-nv",
        past: "border-nv/45 bg-nv/8 text-nv",
        off: "border-white/10 bg-ink-800 text-ink-300",
        dot: "bg-nv",
      };

  const cls = palettes[heat as keyof typeof palettes] || palettes.off;

  return (
    <motion.div
      animate={{ scale: heat === "primary" ? 1.035 : 1 }}
      className={`relative z-10 flex shrink-0 items-center gap-3 rounded-xl border px-4 py-3 transition-colors ${cls}`}
    >
      <span className="relative">{icon}</span>
      <div className="relative leading-tight">
        <div className="text-[14px] font-semibold">{label}</div>
        <div
          className={`text-[10.5px] ${
            isHermes
              ? heat !== "off"
                ? "text-hermes/80"
                : "text-hermes/60"
              : heat !== "off"
              ? "text-nv/80"
              : "text-ink-400"
          }`}
        >
          {heat === "consulting" ? (
            <span className="text-nv">↔ consulting</span>
          ) : (
            sub
          )}
        </div>
      </div>
      {heat === "primary" && (
        <motion.span
          animate={{ opacity: [0.45, 1, 0.45] }}
          transition={{ duration: 1.3, repeat: Infinity }}
          className={`ml-1 h-1.5 w-1.5 rounded-full ${palettes.dot} shadow-[0_0_10px_rgba(255,255,255,0.6)]`}
        />
      )}
      {heat === "consulting" && (
        <motion.span
          animate={{ opacity: [0.3, 0.9, 0.3] }}
          transition={{ duration: 1.0, repeat: Infinity }}
          className={`ml-1 h-1 w-1 rounded-full ${palettes.dot}`}
        />
      )}
    </motion.div>
  );
}

type WireState =
  | "off"
  | "lit"
  | "traveling-right"
  | "traveling-left"
  | "bidirectional"
  | "deny";

function Wire({ state }: { state: WireState }) {
  const lit =
    state === "lit" ||
    state === "traveling-right" ||
    state === "traveling-left" ||
    state === "bidirectional";

  return (
    <div className="relative flex shrink-0 items-center px-1" style={{ minWidth: 44 }}>
      <div
        className={`h-px w-full rounded-full ${
          state === "deny"
            ? "bg-danger/50"
            : lit
            ? "bg-gradient-to-r from-nv/50 via-nv to-nv/50"
            : "bg-white/10"
        }`}
      />
      {(state === "traveling-right" || state === "bidirectional") && (
        <motion.span
          initial={{ left: "-10%", opacity: 0 }}
          animate={{ left: "110%", opacity: [0, 1, 0] }}
          transition={{
            duration: 0.85,
            ease: "easeOut",
            repeat: Infinity,
            repeatDelay: state === "bidirectional" ? 0.4 : 0.2,
          }}
          className="absolute top-1/2 h-1.5 w-8 -translate-y-1/2 rounded-full bg-nv blur-[3px]"
        />
      )}
      {(state === "traveling-left" || state === "bidirectional") && (
        <motion.span
          initial={{ right: "-10%", opacity: 0 }}
          animate={{ right: "110%", opacity: [0, 1, 0] }}
          transition={{
            duration: 0.85,
            ease: "easeOut",
            repeat: Infinity,
            repeatDelay: state === "bidirectional" ? 0.4 : 0.2,
            delay: state === "bidirectional" ? 0.42 : 0,
          }}
          className="absolute top-1/2 h-1.5 w-8 -translate-y-1/2 rounded-full bg-nv blur-[3px]"
        />
      )}
    </div>
  );
}
