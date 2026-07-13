// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
"use strict";

const $ = (sel) => document.querySelector(sel);
const fmtAmt = (a, ccy) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: ccy || "USD" }).format(a || 0);
const esc = (value) => String(value || "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[ch]));

let PAYMENTS = [];
let SCREEN = {}; // id -> screening result

async function api(path, body) {
  const opts = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const res = await fetch(path, opts);
  return { status: res.status, data: await res.json() };
}

function audit(text, kind) {
  const row = document.createElement("div");
  row.className = "row " + (kind || "");
  const ts = new Date().toLocaleTimeString();
  row.textContent = `${ts}  ${text}`;
  $("#audit").prepend(row);
}

function renderQueue() {
  const wrap = $("#queue");
  wrap.innerHTML = "";
  PAYMENTS.forEach((p) => {
    const card = document.createElement("button");
    card.className = "pay-card";
    card.dataset.id = p.id;
    const decision = SCREEN[p.id]?.decision;
    const dot = decision === "CLEARED_FOR_REVIEW" ? "cleared" : decision === "HOLD" ? "hold" : "";
    card.innerHTML =
      `<span class="dot ${dot}"></span>` +
      `<div class="id">${p.id} · ${p.rail}</div>` +
      `<div class="who">${p.beneficiary_name}</div>` +
      `<div class="amt">${fmtAmt(p.amount, p.currency)}</div>`;
    card.onclick = () => select(p.id);
    wrap.appendChild(card);
  });
  $("#queueCount").textContent = `${PAYMENTS.length} items`;
}

function markActive(id) {
  document.querySelectorAll(".pay-card").forEach((c) =>
    c.classList.toggle("active", c.dataset.id === id));
}

async function select(id) {
  markActive(id);
  $("#selected").textContent = `${id} · FinGuard screening in sandbox…`;
  const { status, data } = await api("/api/screen", { id });
  if (status >= 400 || data.error) {
    $("#detail").innerHTML = `<div class="banner blocked">${data.error || "Agent screening failed"}</div>`;
    $("#selected").textContent = id;
    return;
  }
  SCREEN[id] = data;
  renderQueue();
  markActive(id);
  renderDetail(data);
  updateScreened();
  $("#selected").textContent = `${id} · evidenced by Hermes + NeMo Relay`;
  audit(`agent.screen ${id} · Hermes tool execution traced`, "allow");
}

function renderDetail(r) {
  const cleared = r.decision === "CLEARED_FOR_REVIEW";
  const checks = r.checks
    .map((c) => {
      const hit =
        c.name === "sanctions" && c.hits && c.hits.length
          ? ` — <code>${c.hits[0].sdn_name}</code> [${c.hits[0].programs || "OFAC SDN"}]`
          : "";
      return (
        `<div class="check ${c.passed ? "pass" : "fail"}">` +
        `<span class="mark">${c.passed ? "✓" : "✕"}</span>` +
        `<span class="name">${c.name}</span>` +
        `<span class="why">${c.detail}${hit}</span></div>`
      );
    })
    .join("");

  let actions = "";
  if (cleared) {
    actions =
      `<div class="actions">` +
      `<button class="btn danger" id="agentRelease">Agent: Release</button>` +
      `<input id="approver" placeholder="Approver name" value="Jane Ops" />` +
      `<button class="btn go" id="humanRelease">Human approver: Release</button>` +
      `</div><div id="outcome"></div>`;
  } else {
    actions = `<div class="banner blocked">HOLD — FinGuard will not prepare a release packet. ` +
      `Route to the appropriate human queue.</div>`;
  }

  $("#detail").innerHTML =
    `<div class="decision"><span class="badge ${cleared ? "cleared" : "hold"}">${r.decision}</span></div>` +
    `<div class="head-line">${r.payment_id} · ${r.rail} · ` +
    `<span class="money">${fmtAmt(r.amount, r.currency)}</span> → ${r.beneficiary_name}</div>` +
    `<div class="checks">${checks}</div>` +
    `<div class="banner"><b>Agent evidence:</b><br>${esc(r.agent_summary || "Hermes screening completed.")}</div>` +
    actions;

  if (cleared) {
    $("#agentRelease").onclick = () => agentRelease(r.payment_id);
    $("#humanRelease").onclick = () => humanRelease(r.payment_id);
  }
}

async function agentRelease(id) {
  $("#outcome").innerHTML = `<div class="banner">Running the negative control through FinGuard…</div>`;
  const { status, data } = await api("/api/agent-release", { id });
  if (status >= 500 || data.error) {
    $("#outcome").innerHTML = `<div class="banner blocked">${data.error || "Boundary test failed"}</div>`;
    return;
  }
  $("#outcome").innerHTML =
    `<div class="banner blocked"><b>RELEASE BLOCKED BY SANDBOX POLICY.</b><br>` +
    `${data.actor} tried to release ${id}. ${data.reason}.<br>` +
    `The agent cannot move money — a human approver must release on the host.<br><br>` +
    `<b>Agent evidence:</b> ${esc(data.agent_evidence || "OpenShell denied the control request.")}</div>`;
  audit(`policy.deny ${id} · real sandbox control test traced`, "deny");
}

async function humanRelease(id) {
  const approver = ($("#approver").value || "").trim();
  const { status, data } = await api("/api/human-release", { id, approver });
  if (data.released) {
    $("#outcome").innerHTML =
      `<div class="banner released"><b>RELEASED.</b><br>` +
      `${data.actor} released ${id} for ${fmtAmt(data.record.amount)}.</div>`;
    audit(`release.ok  ${id}  by ${approver}  (host)`, "allow");
    refreshLedger();
  } else {
    $("#outcome").innerHTML = `<div class="banner blocked">${data.reason}.</div>`;
  }
}

function updateScreened() {
  $("#screenedN").textContent = String(Object.keys(SCREEN).length);
}

async function refreshLedger() {
  const { data } = await api("/api/ledger");
  $("#ledgerCount").textContent = `${data.count} released`;
  $("#releasedN").textContent = String(data.count);
}

async function screenAll() {
  $("#selected").textContent = "FinGuard screening complete queue in sandbox…";
  const { status, data } = await api("/api/screen-all", {});
  if (status >= 400 || data.error) {
    $("#detail").innerHTML = `<div class="banner blocked">${data.error || "Queue screening failed"}</div>`;
    return;
  }
  for (const result of data.results) {
    SCREEN[result.payment_id] = result;
  }
  renderQueue();
  updateScreened();
  $("#selected").textContent = "Queue screening evidenced by Hermes + NeMo Relay";
  $("#detail").innerHTML = `<div class="banner"><b>Agent queue summary:</b><br>${esc(data.agent_summary)}</div>`;
  audit("agent.screen.queue · Hermes tool execution traced", "allow");
}

// ---- Ask FinGuard chat (proxied to Hermes via the server) ----
const CHAT = [];

function setMode(m) {
  $("#tabScreen").classList.toggle("active", m === "screen");
  $("#tabChat").classList.toggle("active", m === "chat");
  $("#detail").hidden = m !== "screen";
  $("#chatlog").hidden = m !== "chat";
  $("#composer").hidden = m !== "chat";
  $("#selected").textContent =
    m === "chat" ? "Ask FinGuard about the queue or itself" : "Select a payment to screen";
  if (m === "chat") $("#chatInput").focus();
}

function addMsg(role, text) {
  const d = document.createElement("div");
  d.className = "msg" + (role === "user" ? " user" : "");
  d.innerHTML = `<div class="role">${role === "user" ? "You" : "FinGuard"}</div><div class="body"></div>`;
  d.querySelector(".body").textContent = text;
  $("#chatlog").appendChild(d);
  $("#chatlog").scrollTop = $("#chatlog").scrollHeight;
  return d.querySelector(".body");
}

async function sendChat() {
  const t = $("#chatInput").value.trim();
  if (!t) return;
  $("#chatInput").value = "";
  CHAT.push({ role: "user", content: t });
  addMsg("user", t);
  const body = addMsg("assistant", "…");
  try {
    const res = await fetch("/v1/chat/completions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: CHAT }),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      body.textContent = "⚠ " + (e.error || "HTTP " + res.status);
      return;
    }
    // Default path: non-streaming JSON (survives reverse proxies like the Brev URL).
    const ctype = res.headers.get("content-type") || "";
    if (ctype.includes("application/json")) {
      const j = await res.json();
      const txt = j.choices?.[0]?.message?.content || JSON.stringify(j);
      body.textContent = txt;
      CHAT.push({ role: "assistant", content: txt });
      audit("chat turn → Hermes (traced)", "allow");
      return;
    }
    // Fallback: streamed SSE (e.g. when explicitly enabled over an SSH tunnel).
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "", asst = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (data === "[DONE]") continue;
        try {
          const j = JSON.parse(data);
          const d = j.choices?.[0]?.delta?.content || "";
          if (d) { asst += d; body.textContent = asst; $("#chatlog").scrollTop = $("#chatlog").scrollHeight; }
        } catch (_) { /* ignore keep-alives */ }
      }
    }
    CHAT.push({ role: "assistant", content: asst || body.textContent });
    audit("chat turn → Hermes (traced)", "allow");
  } catch (err) {
    body.textContent = "⚠ " + err;
  }
}

async function init() {
  $("#runId").textContent = "po-" + Date.now().toString(36);
  $("#tabScreen").onclick = () => setMode("screen");
  $("#tabChat").onclick = () => setMode("chat");
  $("#chatSend").onclick = sendChat;
  $("#chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
  const { data } = await api("/api/queue");
  PAYMENTS = data.payments;
  renderQueue();
  $("#screenAll").onclick = screenAll;
  refreshLedger();
  audit("FinGuard initialized · policy: deny-by-default · rail not allowed");
}

init();
