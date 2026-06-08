import {
  AppBar,
  Button,
  Card,
  Panel,
  Text,
  TextArea,
  ThemeProvider,
} from "@nvidia/foundations-react-core";
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import nvidiaLogo from "./assets/nvidia_header.png";
import { Markdown } from "./Markdown";
import {
  Quote,
  SkillActivity,
  detectSkillActivity,
  formatMoney,
  formatPercent,
  parseSseBlock,
} from "./finance";

type Message = {
  id: string;
  role: "assistant" | "user";
  content: string;
  thinking?: boolean;
};

type RuntimeConfig = {
  model: string;
};

type ActivityStep = {
  id: string;
  label: string;
  detail: string;
  status: "queued" | "running" | "done" | "error";
};

const systemPrompt =
  "You are a finance-first NemoHermes financial assistant running inside an NVIDIA OpenShell sandbox managed by NemoClaw. Your default work is public market context, SEC company facts, concise analyst briefs, investment-committee prep, risk checks, and Outlook-style financial email drafts. Use installed finance skills internally when helpful, but do not display skill names, skill paths, tool names, tool paths, trace details, or implementation labels in normal responses unless the user explicitly asks for them. If asked what you are or what you can do, describe capabilities in plain business language without mentioning skills or tools. Separate facts from hypotheses with explicit labels when requested. If asked whether to buy or sell, explicitly say you cannot provide a buy/sell recommendation and reframe as research support. Do not provide investment advice. If asked about yourself, describe yourself as a financial assistant agent running in OpenShell, not as a generic Hermes assistant. Explain OpenShell config in API-agnostic terms. Never name provider IDs, internal routing labels, model IDs, endpoint URLs, base URLs, local hostnames, internal-only services, or secret values in normal answers. Say 'configured compatible API provider' instead. End finance answers with a brief caveat.";

const streamFirstTokenTimeoutMs = 90_000;
const streamIdleTimeoutMs = 18_000;

function id(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 7)}`;
}

function readInputValue(event: {
  currentTarget?: EventTarget | null;
  target?: EventTarget | null;
}): string {
  const source = event.currentTarget || event.target;
  if (source && "value" in source && typeof source.value === "string")
    return source.value;
  return "";
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

function skillLabel(skill: SkillActivity) {
  return skill.name
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function cleanAssistantText(text: string) {
  return text
    .split(/\r?\n/)
    .filter((line) => !/^\s*\*?\s*(skill|tool)\s+path\s*:/i.test(line))
    .join("\n")
    .trim();
}

export function App() {
  const [runtime, setRuntime] = useState<RuntimeConfig>({
    model: "financial-assistant",
  });
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [quoteStatus, setQuoteStatus] = useState("Loading live prices");
  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [chunks, setChunks] = useState(0);
  const [latency, setLatency] = useState("0.0s");
  const [activitySteps, setActivitySteps] = useState<ActivityStep[]>([
    {
      id: "idle",
      label: "Waiting",
      detail:
        "Send a finance question to see the assistant's observable steps.",
      status: "queued",
    },
  ]);
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);
  const activityRef = useRef<HTMLDivElement | null>(null);
  const promptRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    fetch("/config")
      .then((response) => (response.ok ? response.json() : null))
      .then((config) => {
        if (!config) return;
        setRuntime({
          model: config.model || "financial-assistant",
        });
      })
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
        setQuotes(payload.quotes || []);
        setQuoteStatus(
          payload.ok ? "Live from Yahoo chart API" : "Quote feed unavailable",
        );
      } catch (error) {
        if (!cancelled)
          setQuoteStatus(
            error instanceof Error ? error.message : "Quote feed unavailable",
          );
      }
    }
    loadQuotes();
    const timer = window.setInterval(loadQuotes, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const node = conversationRef.current;
    if (!node) return;

    const behavior: ScrollBehavior = isBusy ? "smooth" : "auto";
    const scrollToEnd = () => {
      node.scrollTo({ top: node.scrollHeight, behavior });
      conversationEndRef.current?.scrollIntoView({ block: "end", behavior });
    };

    scrollToEnd();
    const frame = window.requestAnimationFrame(scrollToEnd);
    const timer = window.setTimeout(scrollToEnd, 80);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [messages, chunks, isBusy]);

  useEffect(() => {
    const node = activityRef.current;
    if (!node) return;
    node.scrollTo({
      top: node.scrollHeight,
      behavior: isBusy ? "smooth" : "auto",
    });
  }, [activitySteps, isBusy]);

  async function submit(nextPrompt = prompt, nextChannel = "web") {
    const cleanPrompt = nextPrompt.trim();
    if (!cleanPrompt || isBusy) return;

    const traceId = `run-${Date.now().toString(36).slice(-7)}`;
    const started = performance.now();
    const assistantId = id("assistant");
    const plannedSkills = detectSkillActivity(cleanPrompt).slice(0, 4);

    setPrompt("");
    setIsBusy(true);
    setChunks(0);
    setLatency("0.0s");
    setActivitySteps([
      {
        id: `${traceId}-received`,
        label: "Request received",
        detail:
          nextChannel === "web"
            ? "Web chat message accepted."
            : `${nextChannel} message accepted.`,
        status: "done",
      },
      ...plannedSkills.map((skill) => ({
        id: `${traceId}-${skill.name}`,
        label: "Capability queued",
        detail: `${skillLabel(skill)}: ${skill.reason}.`,
        status: "queued" as const,
      })),
      {
        id: `${traceId}-model`,
        label: "Model call",
        detail: "Sending request to the configured compatible API provider.",
        status: "running",
      },
      {
        id: `${traceId}-stream`,
        label: "Streaming response",
        detail: "Waiting for first token.",
        status: "queued",
      },
    ]);
    setMessages((current) => [
      ...current,
      { id: id("user"), role: "user", content: cleanPrompt },
      { id: assistantId, role: "assistant", content: "", thinking: true },
    ]);

    try {
      const controller = new AbortController();
      const responseTimer = window.setTimeout(
        () => controller.abort(),
        streamFirstTokenTimeoutMs,
      );
      const response = await fetch("/v1/chat/completions", {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          "X-Finance-Run-Id": traceId,
          "X-Finance-Channel": nextChannel,
        },
        body: JSON.stringify({
          model: runtime.model,
          stream: true,
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: cleanPrompt },
          ],
          temperature: 0.2,
          max_tokens: 1000,
        }),
      });
      window.clearTimeout(responseTimer);

      if (!response.ok || !response.body) {
        throw new Error(`API returned HTTP ${response.status}`);
      }

      const contentType = response.headers.get("content-type") || "";
      setActivitySteps((current) =>
        current.map((step) =>
          step.id === `${traceId}-model`
            ? { ...step, status: "done", detail: "Model request accepted." }
            : step.id === `${traceId}-stream`
              ? {
                  ...step,
                  status: "running",
                  detail: "Receiving streamed tokens.",
                }
              : step,
        ),
      );
      if (!contentType.includes("text/event-stream")) {
        const payload = await response.json();
        const content = cleanAssistantText(
          payload?.choices?.[0]?.message?.content ||
            payload?.message ||
            "(No assistant message returned.)",
        );
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? { ...message, content, thinking: false }
              : message,
          ),
        );
        setChunks(1);
        setActivitySteps((current) =>
          current.map((step) =>
            step.id === `${traceId}-stream`
              ? {
                  ...step,
                  status: "done",
                  detail: "Non-streamed assistant message received.",
                }
              : step,
          ),
        );
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let output = "";
      let chunkCount = 0;
      let shouldStop = false;

      while (!shouldStop) {
        const { done, timedOut, value } = await readStreamChunk(
          reader,
          output ? streamIdleTimeoutMs : streamFirstTokenTimeoutMs,
        );
        if (timedOut) {
          if (!output)
            throw new Error("Timed out waiting for streamed response");
          break;
        }
        if (done) break;
        if (!value) continue;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const parsed = parseSseBlock(block);
          if (parsed.rawTool) {
            setActivitySteps((current) => {
              const toolId = `${traceId}-tool-${parsed.rawTool}`;
              if (current.some((step) => step.id === toolId)) return current;
              return [
                ...current,
                {
                  id: toolId,
                  label: "Tool event",
                  detail: parsed.rawTool,
                  status: "done",
                },
              ];
            });
          }
          if (parsed.token) {
            output += parsed.token;
            chunkCount += 1;
            setChunks(chunkCount);
            setActivitySteps((current) =>
              current.map((step) =>
                step.id === `${traceId}-stream`
                  ? {
                      ...step,
                      status: "running",
                      detail: `${chunkCount} streamed token chunk${chunkCount === 1 ? "" : "s"} received.`,
                    }
                  : step,
              ),
            );
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? {
                      ...message,
                      content: cleanAssistantText(output),
                      thinking: false,
                    }
                  : message,
              ),
            );
            setLatency(`${((performance.now() - started) / 1000).toFixed(1)}s`);
          }
          if (parsed.done) {
            shouldStop = true;
            break;
          }
        }
      }
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content:
                  cleanAssistantText(output) ||
                  "(No assistant message returned.)",
                thinking: false,
              }
            : message,
        ),
      );
      setActivitySteps((current) =>
        current.map((step) =>
          step.id === `${traceId}-stream`
            ? {
                ...step,
                status: "done",
                detail: output
                  ? `Response complete in ${((performance.now() - started) / 1000).toFixed(1)}s.`
                  : "Response finished.",
              }
            : step.status === "queued" && step.id.startsWith(traceId)
              ? { ...step, status: "done" }
              : step,
        ),
      );
      fetch("/api/phoenix/recent")
        .then((response) => (response.ok ? response.json() : null))
        .then((payload) => {
          if (!payload?.spans?.length) return;
          setActivitySteps((current) => [
            ...current.filter((step) => step.id !== `${traceId}-trace`),
            {
              id: `${traceId}-trace`,
              label: "Trace captured",
              detail:
                "Phoenix has recent agent, LLM, or tool spans for inspection.",
              status: "done",
            },
          ]);
        })
        .catch(() => undefined);
    } catch (error) {
      const message =
        error instanceof DOMException && error.name === "AbortError"
          ? "Timed out waiting for API response"
          : error instanceof Error
            ? error.message
            : String(error);
      setMessages((current) =>
        current.map((item) =>
          item.id === assistantId
            ? {
                ...item,
                content: `Request failed: ${message}`,
                thinking: false,
              }
            : item,
        ),
      );
      setActivitySteps((current) =>
        current.map((step) =>
          step.status === "running" || step.status === "queued"
            ? { ...step, status: "error", detail: message }
            : step,
        ),
      );
    } finally {
      setIsBusy(false);
      window.setTimeout(() => {
        const node = conversationRef.current;
        if (node) node.scrollTo({ top: node.scrollHeight, behavior: "auto" });
        conversationEndRef.current?.scrollIntoView({
          block: "end",
          behavior: "auto",
        });
        promptRef.current?.focus({ preventScroll: true });
      }, 100);
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
    )
      return;
    event.preventDefault();
    void submit();
  }

  return (
    <ThemeProvider density="compact" theme="dark">
      <div className="app-shell">
        <AppBar
          className="nv-appbar"
          slotStart={
            <div className="brand-lockup">
              <img alt="NVIDIA" className="nvidia-logo" src={nvidiaLogo} />
              <span>NemoHermes Financial Desk</span>
            </div>
          }
        />
        <main className="desk-grid">
          <aside className="left-column">
            <Panel
              slotHeading="Market Watch"
              className="panel-frame market-watch"
            >
              <p className="panel-caption">{quoteStatus}</p>
              <div className="quote-list" aria-label="Live stock prices">
                {quotes.map((quote) => (
                  <div
                    className="quote-row"
                    data-direction={
                      (quote.change_percent || 0) >= 0 ? "up" : "down"
                    }
                    key={quote.symbol}
                  >
                    <div>
                      <strong>{quote.symbol}</strong>
                      <span>
                        {quote.exchange || quote.market_state || "Public quote"}
                      </span>
                    </div>
                    <div>
                      <strong>
                        {quote.ok
                          ? formatMoney(quote.price, quote.currency)
                          : "--"}
                      </strong>
                      <span>
                        {quote.ok
                          ? formatPercent(quote.change_percent)
                          : quote.error}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel
              slotHeading="Agent Activity"
              className="panel-frame activity-panel"
            >
              <p className="panel-caption">
                Observable steps only. Private model reasoning is not displayed.
              </p>
              <div
                className="activity-list"
                aria-label="Agent activity"
                ref={activityRef}
              >
                {activitySteps.map((step) => (
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
                ))}
              </div>
            </Panel>
          </aside>

          <section className="chat-column">
            <Card className="hero-card">
              <div>
                <Text kind="label/semibold/md">Market research workspace</Text>
                <h1>Financial assistant agent</h1>
                <p>
                  Public-company research, SEC facts, market snapshots, earnings
                  prep, and concise analyst briefs.
                </p>
              </div>
              <span id="status" className="sr-only">
                {isBusy ? "Streaming" : "Ready"}
              </span>
            </Card>

            <div
              className="conversation"
              ref={conversationRef}
              aria-live="polite"
            >
              {messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <strong>
                    {message.role === "user" ? "You" : "Assistant"}
                  </strong>
                  {message.thinking ? (
                    <div className="thinking">
                      Thinking<span>.</span>
                      <span>.</span>
                      <span>.</span>
                    </div>
                  ) : (
                    <Markdown text={message.content} />
                  )}
                </article>
              ))}
              <div
                ref={conversationEndRef}
                aria-hidden="true"
                className="conversation-end"
              />
            </div>

            <form className="composer" onSubmit={onSubmit}>
              <TextArea
                aria-label="Message the financial assistant"
                onChange={(event) => setPrompt(readInputValue(event))}
                onKeyDown={onPromptKeyDown}
                placeholder="Message the financial assistant"
                ref={promptRef}
                rows={4}
                value={prompt}
              />
              <Button
                color="brand"
                disabled={isBusy || !prompt.trim()}
                type="submit"
              >
                Send
              </Button>
            </form>
          </section>
        </main>
      </div>
    </ThemeProvider>
  );
}
