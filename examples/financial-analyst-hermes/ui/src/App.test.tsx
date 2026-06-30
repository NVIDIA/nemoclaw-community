// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { Markdown } from "./Markdown";
import { parseSseBlock } from "./finance";

function streamFrom(chunks: string[]) {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(new TextEncoder().encode(chunk));
      }
      controller.close();
    },
  });
}

function chatStream(answer: string) {
  return new Response(
    streamFrom([
      'data: {"choices":[{"delta":{"tool_calls":[{"function":{"name":"terminal"}}]}}]}\n\n',
      `data: ${JSON.stringify({ choices: [{ delta: { content: answer } }] })}\n\n`,
      "data: [DONE]\n\n",
    ]),
    { headers: { "content-type": "text/event-stream" } },
  );
}

describe("financial React UI", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/config")) {
        return Response.json({ model: "financial-assistant" });
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
      if (url.startsWith("/api/phoenix/recent")) {
        return Response.json({
          ok: true,
          spans: [
            {
              name: "terminal",
              kind: "tool",
              status: "OK",
              trace_id: "abc123",
              started_at: new Date().toISOString(),
            },
          ],
        });
      }
      if (url.startsWith("/v1/chat/completions")) {
        return chatStream("A concise financial research response.");
      }
      throw new Error(`Unhandled fetch ${url}`);
    }) as typeof fetch;
  });

  it("renders the finance workspace with an empty composer and live quotes", async () => {
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
    expect(screen.getByText("Activity")).toBeInTheDocument();
    expect(screen.getByText(/Research public companies/i)).toBeInTheDocument();
    expect(
      screen.getByLabelText("Message the financial assistant"),
    ).toHaveValue("");
    await screen.findByText("$100.00");
    expect(screen.getByText("Public market snapshot")).toBeInTheDocument();
    expect(screen.queryByText("Session Context")).not.toBeInTheDocument();
    expect(screen.queryByText("Skill Usage")).not.toBeInTheDocument();
    expect(screen.queryByText("Run Telemetry")).not.toBeInTheDocument();
  });

  it("sends on Enter with high reasoning and records observed tool activity", async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = screen.getByLabelText("Message the financial assistant");
    await user.type(input, "Create an NVDA market snapshot.{Enter}");

    await screen.findByText("A concise financial research response.");
    expect(screen.getAllByText("Tool call").length).toBeGreaterThan(0);
    const chatCall = vi
      .mocked(global.fetch)
      .mock.calls.find(([request]) =>
        String(request).startsWith("/v1/chat/completions"),
      );
    const body = JSON.parse(String(chatCall?.[1]?.body));
    expect(body.max_tokens).toBe(16_384);
    expect(body.reasoning_effort).toBe("high");
    expect(body.messages).toEqual([
      { role: "user", content: "Create an NVDA market snapshot." },
    ]);
    expect(
      body.messages.some(
        (message: { role: string }) => message.role === "system",
      ),
    ).toBe(false);
  });

  it("includes prior turns in the next request", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = screen.getByLabelText("Message the financial assistant");

    await user.type(input, "First question{Enter}");
    await screen.findByText("A concise financial research response.");
    await user.type(input, "Follow up{Enter}");
    await waitFor(() =>
      expect(
        vi
          .mocked(global.fetch)
          .mock.calls.filter(([request]) =>
            String(request).startsWith("/v1/chat/completions"),
          ),
      ).toHaveLength(2),
    );

    const chatCalls = vi
      .mocked(global.fetch)
      .mock.calls.filter(([request]) =>
        String(request).startsWith("/v1/chat/completions"),
      );
    const body = JSON.parse(String(chatCalls[1][1]?.body));
    expect(body.messages).toEqual([
      { role: "user", content: "First question" },
      { role: "assistant", content: "A concise financial research response." },
      { role: "user", content: "Follow up" },
    ]);
  });

  it("reports stream failures and leaves the composer usable", async () => {
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
              controller.error(new Error("connection closed"));
            },
          }),
          { headers: { "content-type": "text/event-stream" } },
        );
      }
      throw new Error(`Unhandled fetch ${url}`);
    }) as typeof fetch;

    const user = userEvent.setup();
    render(<App />);
    const input = screen.getByLabelText("Message the financial assistant");
    await user.type(input, "What are you?{Enter}");

    await screen.findByText(/Request failed: connection closed/i);
    expect(input).toBeEnabled();
  });

  it("parses content, finish reasons, and real tool names from SSE", () => {
    expect(
      parseSseBlock('data: {"choices":[{"delta":{"content":"hello"}}]}\n')
        .token,
    ).toBe("hello");
    expect(
      parseSseBlock('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n')
        .done,
    ).toBe(true);
    expect(
      parseSseBlock(
        'data: {"choices":[{"delta":{"tool_calls":[{"function":{"name":"sec_company_facts"}}]}}]}\n',
      ).toolNames,
    ).toEqual(["sec_company_facts"]);
  });

  it("renders loose Markdown tables", () => {
    render(
      <Markdown
        text={[
          "Skill | What it is for",
          "financial-market-snapshot | Pull public quote snapshots",
          "sec-company-facts | Summarize SEC company facts",
        ].join("\n")}
      />,
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Skill" }),
    ).toBeInTheDocument();
  });

  it("renders safe model HTML and removes unsafe HTML", () => {
    const { container } = render(
      <Markdown
        text={
          '<h3>Skills</h3><p><strong>Market snapshots</strong></p><img src=x onerror="alert(1)"><script>alert(1)</script>'
        }
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Skills", level: 3 }),
    ).toBeInTheDocument();
    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect(container.querySelector("img")?.getAttribute("onerror")).toBeNull();
  });
});
