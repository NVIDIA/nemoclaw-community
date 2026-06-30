// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export type Quote = {
  symbol: string;
  ok: boolean;
  price?: number;
  change_percent?: number;
  currency?: string;
  exchange?: string;
  market_state?: string;
  error?: string;
};

export type TraceSpan = {
  name: string;
  kind: string;
  status: string;
  trace_id: string;
  span_id: string;
  parent_id: string;
  started_at: string;
};

export function formatMoney(value?: number, currency = "USD"): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value?: number): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function textContent(value: unknown): string {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return "";
  return value
    .map((part) =>
      part && typeof part === "object" && "text" in part
        ? String(part.text ?? "")
        : "",
    )
    .join("");
}

export function parseSseBlock(block: string): {
  token: string;
  done: boolean;
  toolNames: string[];
} {
  let token = "";
  let done = false;
  const toolNames = new Set<string>();

  for (const line of block.split("\n")) {
    if (!line.startsWith("data:")) continue;
    const data = line.slice(5).trim();
    if (!data) continue;
    if (data === "[DONE]") {
      done = true;
      continue;
    }

    try {
      const payload = JSON.parse(data);
      const choice = payload?.choices?.[0] ?? {};
      token += textContent(choice?.delta?.content);
      token += textContent(choice?.message?.content);
      token += textContent(choice?.text);
      done ||= Boolean(choice?.finish_reason);

      for (const call of choice?.delta?.tool_calls ?? []) {
        if (typeof call?.function?.name === "string") {
          toolNames.add(call.function.name);
        }
      }
      const eventName = payload?.tool_name ?? payload?.name ?? payload?.event;
      if (
        typeof eventName === "string" &&
        /(?:^|[._:-])(tool|terminal|function|skill)(?:$|[._:-])/i.test(
          eventName,
        )
      ) {
        toolNames.add(eventName);
      }
    } catch {
      // Ignore non-JSON event metadata. Hermes content arrives as JSON chunks.
    }
  }

  return { token, done, toolNames: [...toolNames] };
}
