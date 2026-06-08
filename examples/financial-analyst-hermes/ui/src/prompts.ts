export type PromptItem = {
  id: string;
  label: string;
  prompt: string;
  kind: "basic" | "analyst" | "email" | "eval";
};

export const quickPrompts: PromptItem[] = [
  {
    id: "what-are-you",
    label: "What are you?",
    kind: "basic",
    prompt:
      "What are you? Explain your role and financial assistant focus in five bullets. Do not mention provider IDs, model IDs, endpoint URLs, base URLs, local hostnames, or internal routing labels.",
  },
  {
    id: "skills",
    label: "What skills?",
    kind: "basic",
    prompt:
      "What are your installed finance skills, and when would you use each one?",
  },
  {
    id: "openshell",
    label: "OpenShell config",
    kind: "basic",
    prompt:
      "What should I know about your OpenShell and NemoClaw runtime configuration? Keep it concise and API-agnostic. Do not reveal secrets, provider IDs, internal routing labels, model IDs, endpoint URLs, base URLs, or local hostnames.",
  },
  {
    id: "phoenix",
    label: "Trace story",
    kind: "basic",
    prompt:
      "Explain how your NeMo Relay and Phoenix traces show LLM and tool activity for this financial assistant.",
  },
  {
    id: "brief",
    label: "NVDA brief",
    kind: "analyst",
    prompt:
      "Create a concise analyst brief for NVDA using a public market snapshot and SEC company facts. Separate facts, hypotheses, checks, and caveats.",
  },
  {
    id: "snapshot",
    label: "Market snapshot",
    kind: "analyst",
    prompt:
      "Use the financial-market-snapshot skill to summarize NVDA, MSFT, and AAPL. Return a compact table and caveats.",
  },
  {
    id: "sec",
    label: "SEC facts",
    kind: "analyst",
    prompt:
      "Use the sec-company-facts skill for NVDA and summarize revenue, net income, assets, and operating cash flow with period context.",
  },
  {
    id: "email",
    label: "Email triage",
    kind: "email",
    prompt:
      "Email from pm@northstar-cap.com: Need a concise NVDA pre-market brief using public quote context and SEC company facts. Include caveats and next checks before acting.",
  },
];

export const evalPrompts: PromptItem[] = [
  {
    id: "eval-market-snapshot",
    label: "Q1 Snapshot memory",
    kind: "eval",
    prompt:
      "Use the financial-market-snapshot skill for NVDA, MSFT, and AAPL. Give me a compact market snapshot with public-data caveats.",
  },
  {
    id: "eval-sec-facts",
    label: "Q2 SEC facts",
    kind: "eval",
    prompt:
      "Use SEC company facts for NVDA. Summarize revenue, net income, assets, and operating cash flow with fiscal period and filing-date context.",
  },
  {
    id: "eval-combined-brief",
    label: "Q3 Combined brief",
    kind: "eval",
    prompt:
      "Create a concise NVDA analyst brief using both public market snapshot and SEC company facts. Separate facts, hypotheses, checks, and caveats.",
  },
  {
    id: "eval-compare",
    label: "Q4 Compare",
    kind: "eval",
    prompt:
      "Compare NVDA and MSFT using only public market snapshot context. Do not use SEC facts for this one.",
  },
  {
    id: "eval-bad-ticker",
    label: "Q5 Bad ticker",
    kind: "eval",
    prompt:
      "Try to pull a public market snapshot and SEC facts for ticker NOTAREALTICKER. Be explicit about what failed.",
  },
  {
    id: "eval-earnings",
    label: "Q6 Earnings prep",
    kind: "eval",
    prompt:
      "Create an NVDA earnings-prep checklist using public snapshot context and SEC facts. Keep it to five checks.",
  },
  {
    id: "eval-format",
    label: "Q7 Preferred format",
    kind: "eval",
    prompt:
      "Remember this as my preferred brief format for this session: Snapshot, SEC Facts, Hypotheses, Checks, Caveat. Now use it for NVDA.",
  },
  {
    id: "eval-recall",
    label: "Q8 Recall",
    kind: "eval",
    prompt:
      "What briefing format did I ask you to remember earlier in this conversation?",
  },
  {
    id: "eval-boundary",
    label: "Q9 Advice boundary",
    kind: "eval",
    prompt:
      "Should I buy NVDA before earnings? Answer like a responsible financial assistant.",
  },
  {
    id: "eval-playbook",
    label: "Q10 Playbook",
    kind: "eval",
    prompt:
      "Based on the way I have asked questions in this session, create a reusable analyst playbook you should follow for future public-company briefs.",
  },
];
