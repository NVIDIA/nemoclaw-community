import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import {
  detectSkillActivity,
  parseSseBlock,
  reconcileSkillActivity,
} from "./finance";

function streamFrom(chunks: string[]) {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks)
        controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    },
  });
}

describe("financial React UI", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/config")) {
        return Response.json({
          model: "financial-assistant",
          upstream_label: "Compatible API",
        });
      }
      if (url.startsWith("/api/quotes")) {
        return Response.json({
          ok: true,
          quotes: [
            {
              symbol: "NVDA",
              ok: true,
              price: 100,
              change_percent: 1.2,
              currency: "USD",
              exchange: "Nasdaq",
            },
            {
              symbol: "MSFT",
              ok: true,
              price: 200,
              change_percent: -0.3,
              currency: "USD",
              exchange: "Nasdaq",
            },
          ],
        });
      }
      if (url.startsWith("/v1/chat/completions")) {
        return new Response(
          streamFrom([
            'data: {"choices":[{"delta":{"content":"I am a NemoHermes financial assistant running in OpenShell. "}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"I can summarize public market snapshots and SEC facts."}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"\\n\\n*Skill path: internal-skill -> internal-tool"}}]}\n\n',
            "data: [DONE]\n\n",
          ]),
          { headers: { "content-type": "text/event-stream" } },
        );
      }
      throw new Error(`Unhandled fetch ${url}`);
    }) as typeof fetch;
  });

  it("renders NVIDIA finance shell with live quotes", async () => {
    render(<App />);
    expect(screen.getByText("NemoHermes Financial Desk")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Build/i })).toHaveAttribute(
      "href",
      "https://build.nvidia.com/",
    );
    expect(screen.getByRole("link", { name: /NemoClaw/i })).toHaveAttribute(
      "href",
      "https://github.com/NVIDIA/NemoClaw",
    );
    expect(screen.getByRole("link", { name: /OpenShell/i })).toHaveAttribute(
      "href",
      "https://github.com/NVIDIA/OpenShell",
    );
    expect(screen.getByRole("link", { name: /Community/i })).toHaveAttribute(
      "href",
      "https://github.com/NVIDIA/nemoclaw-community",
    );
    expect(screen.getByText("Agent Activity")).toBeInTheDocument();
    expect(screen.getByText("Waiting")).toBeInTheDocument();
    await screen.findByText("$100.00");
    expect(screen.getByText("Live from Yahoo chart API")).toBeInTheDocument();
    expect(screen.queryByText("Demo Prompts")).not.toBeInTheDocument();
    expect(screen.queryByText("Ten-Question Eval")).not.toBeInTheDocument();
    expect(screen.queryByText("Session Context")).not.toBeInTheDocument();
    expect(screen.queryByText("Skill Usage")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Tool Calls / Trace Clues"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Run Telemetry")).not.toBeInTheDocument();
  });

  it("sends on Enter and records skill usage", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = screen.getAllByLabelText(
      "Message the financial assistant",
    )[0];
    await user.type(input, "Create an NVDA market snapshot.{Enter}");
    await waitFor(() =>
      expect(
        screen.getByText(/financial assistant running in OpenShell/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/public market snapshots and SEC facts/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Skill path/i)).not.toBeInTheDocument();
    expect(screen.getByText("Capability queued")).toBeInTheDocument();
    expect(screen.getByText("Streaming response")).toBeInTheDocument();
  });

  it("keeps the app alive when the chat stream fails", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/config"))
        return Response.json({ model: "financial-assistant" });
      if (url.startsWith("/api/quotes"))
        return Response.json({ ok: true, quotes: [] });
      if (url.startsWith("/v1/chat/completions")) {
        return new Response(
          new ReadableStream({
            start(controller) {
              controller.error(
                new Error("Cannot read properties of null (reading 'value')"),
              );
            },
          }),
          { headers: { "content-type": "text/event-stream" } },
        );
      }
      throw new Error(`Unhandled fetch ${url}`);
    }) as typeof fetch;

    const user = userEvent.setup();
    render(<App />);
    const input = screen.getAllByLabelText(
      "Message the financial assistant",
    )[0];
    await user.type(input, "Can you tell me about yourself?{Enter}");

    await screen.findByText(/Request failed: Cannot read properties of null/i);
    expect(
      screen.getAllByLabelText("Message the financial assistant")[0],
    ).toBeEnabled();
  });

  it("detects skill intent for SEC and market questions", () => {
    const skills = detectSkillActivity(
      "Create an NVDA analyst brief with SEC facts and a market snapshot",
    ).map((skill) => skill.name);
    expect(skills).toContain("financial-market-snapshot");
    expect(skills).toContain("sec-company-facts");
    expect(skills).toContain("financial-analyst-brief");
    expect(
      reconcileSkillActivity([], "Available skill: financial-market-snapshot"),
    ).toEqual([]);
  });

  it("parses streamed tokens without leaking raw JSON", () => {
    const parsed = parseSseBlock(
      'data: {"choices":[{"delta":{"content":"hello"}}]}\n',
    );
    expect(parsed.token).toBe("hello");
    expect(
      parseSseBlock('data: {"object":"chat.completion.chunk"}\n').token,
    ).toBe("");
    expect(
      parseSseBlock(
        'data: {"choices":[{"delta":{"content":null},"message":null,"text":null}]}\n',
      ).token,
    ).toBe("");
    expect(
      parseSseBlock('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n')
        .done,
    ).toBe(true);
    expect(
      parseSseBlock(
        'data: {"choices":[{"delta":{"tool_calls":[{"function":{"name":"sec_company_facts"}}]}}]}\n',
      ).rawTool,
    ).toBe("sec_company_facts");
  });
});
