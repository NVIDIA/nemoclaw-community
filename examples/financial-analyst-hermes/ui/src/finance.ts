export type SkillName =
  | "financial-market-snapshot"
  | "sec-company-facts"
  | "financial-analyst-brief"
  | "financial-analyst-playbook"
  | "outlook-finance-bridge";

export type SkillActivity = {
  id: string;
  name: SkillName | string;
  status: "planned" | "streaming" | "used" | "error";
  reason: string;
  detail?: string;
};

export type Quote = {
  symbol: string;
  ok: boolean;
  price?: number;
  previous_close?: number;
  change?: number;
  change_percent?: number;
  currency?: string;
  exchange?: string;
  market_state?: string;
  error?: string;
};

export type TraceEvent = {
  id: string;
  event: string;
  source: string;
};

const skillRules: Array<{
  name: SkillName;
  patterns: RegExp[];
  reason: string;
}> = [
  {
    name: "financial-market-snapshot",
    patterns: [
      /market snapshot/i,
      /watchlist/i,
      /quote/i,
      /price/i,
      /NVDA|MSFT|AAPL|AMD|AVGO/i,
    ],
    reason: "Public quote context and watchlist checks",
  },
  {
    name: "sec-company-facts",
    patterns: [
      /SEC/i,
      /company facts/i,
      /revenue/i,
      /net income/i,
      /assets/i,
      /cash flow/i,
      /filing/i,
    ],
    reason: "SEC company facts and financial statement context",
  },
  {
    name: "financial-analyst-brief",
    patterns: [
      /analyst brief/i,
      /earnings/i,
      /investment committee|IC memo/i,
      /hypotheses/i,
      /catalyst/i,
    ],
    reason: "Brief synthesis with facts, hypotheses, checks, and caveats",
  },
  {
    name: "financial-analyst-playbook",
    patterns: [
      /playbook/i,
      /preferred format/i,
      /remember/i,
      /checklist/i,
      /reusable/i,
    ],
    reason: "Session briefing format and follow-up discipline",
  },
  {
    name: "outlook-finance-bridge",
    patterns: [/email/i, /outlook/i, /reply/i, /inbox/i],
    reason: "Outlook-style triage and response drafting",
  },
];

export function detectSkillActivity(prompt: string): SkillActivity[] {
  const matches = skillRules.filter((rule) =>
    rule.patterns.some((pattern) => pattern.test(prompt)),
  );
  return matches.map((rule) => ({
    id: `${rule.name}-${Date.now()}`,
    name: rule.name,
    status: "planned",
    reason: rule.reason,
  }));
}

export function reconcileSkillActivity(
  current: SkillActivity[],
  text: string,
): SkillActivity[] {
  const lower = text.toLowerCase();
  const merged = [...current];
  for (const rule of skillRules) {
    const explicit =
      lower.includes(rule.name) ||
      lower.includes(rule.name.replaceAll("-", " "));
    if (!explicit) continue;
    const index = merged.findIndex((item) => item.name === rule.name);
    if (index >= 0) {
      merged[index] = {
        ...merged[index],
        status: "used",
        detail: "Mentioned in streamed output / skill path",
      };
    }
  }
  return merged;
}

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

function tokenText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return "";
}

export function parseSseBlock(block: string): {
  token: string;
  done: boolean;
  rawTool?: string;
} {
  let token = "";
  let done = false;
  let rawTool = "";

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
      const choice = payload?.choices?.[0] || {};
      token += tokenText(choice?.delta?.content);
      token += tokenText(choice?.message?.content);
      token += tokenText(choice?.text);
      if (choice?.finish_reason) {
        done = true;
      }
      const functionToolName = choice?.delta?.tool_calls?.[0]?.function?.name;
      const eventToolName =
        payload?.tool_name || payload?.name || payload?.event;
      const toolName =
        typeof functionToolName === "string"
          ? functionToolName
          : typeof eventToolName === "string" &&
              /tool|skill|terminal|function|call/i.test(eventToolName)
            ? eventToolName
            : "";
      if (toolName) {
        rawTool = toolName;
      }
    } catch {
      if (!data.startsWith("{") && !data.startsWith("[")) token += data;
    }
  }

  return { token, done, rawTool };
}
