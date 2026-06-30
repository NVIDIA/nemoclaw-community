// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Activity, ArrowUp, ExternalLink } from "lucide-react";
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import nvidiaLogo from "./assets/nvidia_header.png";
import { Markdown } from "./Markdown";
import {
  formatMoney,
  formatPercent,
  parseSseBlock,
  Quote,
  TraceSpan,
} from "./finance";

type Message = {
  id: string;
  role: "assistant" | "user";
  content: string;
  thinking?: boolean;
};

type ActivityStep = {
  id: string;
  label: string;
  detail: string;
  status: "running" | "done" | "error";
};

const firstTokenTimeoutMs = 180_000;
const streamIdleTimeoutMs = 120_000;

function makeId(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 7)}`;
}

function readStreamChunk(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  timeoutMs: number,
) {
  return new Promise<
    | (ReadableStreamReadResult<Uint8Array> & { timedOut: false })
    | { done: true; value?: undefined; timedOut: true }
  >((resolve, reject) => {
    const timer = window.setTimeout(
      () => resolve({ done: true, timedOut: true }),
      timeoutMs,
    );
    reader.read().then(
      (result) => {
        window.clearTimeout(timer);
        resolve({ ...result, timedOut: false });
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function assistantContent(payload: unknown): string {
  const data = payload as {
    choices?: Array<{ message?: { content?: string } }>;
    message?: string;
  };
  return (
    data?.choices?.[0]?.message?.content ??
    data?.message ??
    "(No assistant message returned.)"
  );
}

function activityLabel(span: TraceSpan) {
  const kind = span.kind.toLowerCase();
  if (kind === "tool") return "Tool call";
  if (kind === "llm") return "Model call";
  if (kind === "agent") return "Agent turn";
  return "Trace span";
}

export function App() {
  const [model, setModel] = useState("financial-assistant");
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [quoteStatus, setQuoteStatus] = useState("Loading market data");
  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [activitySteps, setActivitySteps] = useState<ActivityStep[]>([]);
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);
  const promptRef = useRef<HTMLTextAreaElement | null>(null);
  const activeRunRef = useRef<string | null>(null);

  useEffect(
    () => () => {
      activeRunRef.current = null;
    },
    [],
  );

  useEffect(() => {
    fetch("/config")
      .then((response) => (response.ok ? response.json() : null))
      .then((config) => setModel(config?.model || "financial-assistant"))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadQuotes() {
      try {
        const response = await fetch(
          "/api/quotes?symbols=NVDA,MSFT,AAPL,AMD,AVGO",
        );
        const payload = await response.json();
        if (cancelled) return;
        setQuotes(payload.quotes ?? []);
        setQuoteStatus(
          payload.ok ? "Public market snapshot" : "Market data unavailable",
        );
      } catch {
        if (!cancelled) setQuoteStatus("Market data unavailable");
      }
    }
    void loadQuotes();
    const timer = window.setInterval(loadQuotes, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const node = conversationRef.current;
    if (!node) return;
    const scroll = () => {
      node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
      conversationEndRef.current?.scrollIntoView({ block: "end" });
    };
    scroll();
    const frame = window.requestAnimationFrame(scroll);
    return () => window.cancelAnimationFrame(frame);
  }, [messages]);

  function addToolActivity(runId: string, toolName: string) {
    const activityId = `${runId}-tool-${toolName}`;
    setActivitySteps((current) =>
      current.some((step) => step.id === activityId)
        ? current
        : [
            ...current,
            {
              id: activityId,
              label: "Tool call",
              detail: toolName,
              status: "done",
            },
          ],
    );
  }

  async function loadTraceActivity(runId: string, startedAt: number) {
    for (let attempt = 0; attempt < 8; attempt += 1) {
      if (activeRunRef.current !== runId) return;
      try {
        const since = encodeURIComponent(new Date(startedAt).toISOString());
        const response = await fetch(`/api/phoenix/recent?since=${since}`);
        const payload = await response.json();
        const spans: TraceSpan[] = payload.spans ?? [];
        if (spans.length && activeRunRef.current === runId) {
          setActivitySteps((current) => [
            ...current.filter((step) => !step.id.startsWith(`${runId}-span-`)),
            ...spans.slice(0, 8).map((span, index) => ({
              id: `${runId}-span-${span.trace_id}-${index}`,
              label: activityLabel(span),
              detail: span.name,
              status:
                span.status === "ERROR"
                  ? ("error" as const)
                  : ("done" as const),
            })),
          ]);
          return;
        }
      } catch {
        // Phoenix is supplementary; chat remains usable while it catches up.
      }
      await new Promise((resolve) => window.setTimeout(resolve, 750));
    }
  }

  async function submit() {
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt || isBusy) return;

    const runId = `run-${Date.now().toString(36)}`;
    activeRunRef.current = runId;
    const startedAt = Date.now();
    const assistantId = makeId("assistant");
    const history = messages
      .filter((message) => !message.thinking && message.content)
      .map(({ role, content }) => ({ role, content }));

    setPrompt("");
    setIsBusy(true);
    setActivitySteps([
      {
        id: `${runId}-request`,
        label: "Request sent",
        detail: "Hermes accepted the conversation turn.",
        status: "running",
      },
    ]);
    setMessages((current) => [
      ...current,
      { id: makeId("user"), role: "user", content: cleanPrompt },
      { id: assistantId, role: "assistant", content: "", thinking: true },
    ]);

    const controller = new AbortController();
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      const response = await fetch("/v1/chat/completions", {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model,
          stream: true,
          messages: [...history, { role: "user", content: cleanPrompt }],
          max_tokens: 16_384,
          reasoning_effort: "high",
        }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(
          payload?.error?.message || `Hermes returned HTTP ${response.status}`,
        );
      }

      setActivitySteps((current) =>
        current.map((step) =>
          step.id === `${runId}-request`
            ? { ...step, label: "Hermes connected", status: "done" }
            : step,
        ),
      );

      if (
        !response.body ||
        !response.headers.get("content-type")?.includes("text/event-stream")
      ) {
        const payload = await response.json();
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  content: assistantContent(payload),
                  thinking: false,
                }
              : message,
          ),
        );
        return;
      }

      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let output = "";
      let chunks = 0;
      let finished = false;

      setActivitySteps((current) => [
        ...current,
        {
          id: `${runId}-stream`,
          label: "Response streaming",
          detail: "Waiting for the first response token.",
          status: "running",
        },
      ]);

      while (!finished) {
        const result = await readStreamChunk(
          reader,
          output ? streamIdleTimeoutMs : firstTokenTimeoutMs,
        );
        if (result.timedOut) {
          await reader.cancel();
          throw new Error(
            output
              ? "The response stream stopped before completion."
              : "Timed out waiting for the first response token.",
          );
        }
        if (result.done) break;
        if (!result.value) continue;

        buffer = (
          buffer + decoder.decode(result.value, { stream: true })
        ).replaceAll("\r\n", "\n");
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const parsed = parseSseBlock(block);
          parsed.toolNames.forEach((name) => addToolActivity(runId, name));
          if (parsed.token) {
            output += parsed.token;
            chunks += 1;
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, content: output, thinking: false }
                  : message,
              ),
            );
            setActivitySteps((current) =>
              current.map((step) =>
                step.id === `${runId}-stream`
                  ? { ...step, detail: `${chunks} streamed chunks received.` }
                  : step,
              ),
            );
          }
          finished ||= parsed.done;
        }
      }

      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: output || "(No assistant message returned.)",
                thinking: false,
              }
            : message,
        ),
      );
      setActivitySteps((current) =>
        current.map((step) =>
          step.id === `${runId}-stream`
            ? { ...step, detail: "Response complete.", status: "done" }
            : step,
        ),
      );
      void loadTraceActivity(runId, startedAt);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: `Request failed: ${detail}`,
                thinking: false,
              }
            : message,
        ),
      );
      setActivitySteps((current) =>
        current.map((step) =>
          step.status === "running"
            ? { ...step, detail, status: "error" }
            : step,
        ),
      );
    } finally {
      controller.abort();
      reader?.releaseLock();
      setIsBusy(false);
      window.setTimeout(
        () => promptRef.current?.focus({ preventScroll: true }),
        50,
      );
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  function onPromptKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    ) {
      return;
    }
    event.preventDefault();
    void submit();
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <img alt="NVIDIA" className="nvidia-logo" src={nvidiaLogo} />
          <div>
            <strong>NemoHermes Financial Desk</strong>
            <span>Public-market research assistant</span>
          </div>
        </div>
        <nav className="resource-links" aria-label="Demo resources">
          <a href="https://build.nvidia.com/" rel="noreferrer" target="_blank">
            🚀 Build
          </a>
          <a
            href="https://github.com/NVIDIA/NemoClaw"
            rel="noreferrer"
            target="_blank"
          >
            🧰 NemoClaw
          </a>
          <a
            href="https://github.com/NVIDIA/OpenShell"
            rel="noreferrer"
            target="_blank"
          >
            🖥️ OpenShell
          </a>
          <a
            href="https://github.com/NVIDIA/nemoclaw-community"
            rel="noreferrer"
            target="_blank"
          >
            📦 Community
          </a>
        </nav>
      </header>

      <main className="desk-grid">
        <aside className="market-panel" aria-label="Market watch">
          <div className="panel-heading">
            <div>
              <h2>Market Watch</h2>
              <p>{quoteStatus}</p>
            </div>
            <span className="live-dot" aria-label="Live" />
          </div>
          <div className="quote-list">
            {quotes.map((quote) => (
              <div className="quote-row" key={quote.symbol}>
                <div>
                  <strong>{quote.symbol}</strong>
                  <span>
                    {quote.exchange || quote.market_state || "Public quote"}
                  </span>
                </div>
                <div>
                  <strong>
                    {quote.ok ? formatMoney(quote.price, quote.currency) : "--"}
                  </strong>
                  <span
                    className={
                      (quote.change_percent ?? 0) >= 0 ? "positive" : "negative"
                    }
                  >
                    {quote.ok
                      ? formatPercent(quote.change_percent)
                      : "Unavailable"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </aside>

        <section className="workspace">
          <header className="workspace-heading">
            <div>
              <p>Financial research workspace</p>
              <h1>Financial assistant</h1>
              <span>
                Market snapshots, SEC facts, earnings prep, and concise analyst
                briefs.
              </span>
            </div>
            <span className={`run-state ${isBusy ? "busy" : ""}`}>
              {isBusy ? "Working" : "Ready"}
            </span>
          </header>

          <div
            className="conversation"
            ref={conversationRef}
            aria-live="polite"
          >
            {messages.length === 0 && (
              <div className="welcome">
                <h2>Research public companies with a traceable assistant.</h2>
                <p>
                  Ask for current market context, SEC company facts, an earnings
                  brief, a risk checklist, or a financial email draft.
                </p>
              </div>
            )}
            {messages.map((message) => (
              <article className={`message ${message.role}`} key={message.id}>
                <strong>
                  {message.role === "user" ? "You" : "Financial assistant"}
                </strong>
                {message.thinking ? (
                  <div className="thinking" aria-label="Assistant is thinking">
                    Thinking<span>.</span>
                    <span>.</span>
                    <span>.</span>
                  </div>
                ) : (
                  <Markdown text={message.content} />
                )}
              </article>
            ))}
            <div ref={conversationEndRef} aria-hidden="true" />
          </div>

          <form className="composer" onSubmit={onSubmit}>
            <textarea
              aria-label="Message the financial assistant"
              onChange={(event) => setPrompt(event.currentTarget.value)}
              onKeyDown={onPromptKeyDown}
              placeholder="Message the financial assistant"
              ref={promptRef}
              rows={3}
              value={prompt}
            />
            <button disabled={isBusy || !prompt.trim()} type="submit">
              <ArrowUp aria-hidden="true" size={18} />
              <span>Send</span>
            </button>
          </form>
        </section>

        <aside className="activity-panel" aria-label="Agent activity">
          <div className="panel-heading">
            <div>
              <h2>Activity</h2>
              <p>Observed run events</p>
            </div>
            <Activity aria-hidden="true" size={19} />
          </div>
          <div className="activity-list">
            {activitySteps.length === 0 ? (
              <p className="activity-empty">
                Run activity and trace spans will appear here.
              </p>
            ) : (
              activitySteps.map((step) => (
                <div
                  className="activity-row"
                  data-status={step.status}
                  key={step.id}
                >
                  <span aria-hidden="true" />
                  <div>
                    <strong>{step.label}</strong>
                    <p>{step.detail}</p>
                  </div>
                </div>
              ))
            )}
          </div>
          <a
            className="phoenix-link"
            href="http://127.0.0.1:6006"
            target="_blank"
            rel="noreferrer"
          >
            Open Phoenix on port 6006{" "}
            <ExternalLink aria-hidden="true" size={14} />
          </a>
        </aside>
      </main>
    </div>
  );
}
