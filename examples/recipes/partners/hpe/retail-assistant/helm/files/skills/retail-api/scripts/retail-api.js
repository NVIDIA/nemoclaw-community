#!/usr/bin/env node
// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
/**
 * retail-api.js — CLI wrapper for the Araz Retail API.
 *
 * Handles authentication, JSON parsing, and error handling internally
 * so the agent only needs to run a single command per request.
 *
 * Usage:  node retail-api.js <command> --email E --password P [options]
 *
 * The API base URL is read from .env (RETAIL_API_URL) or defaults to
 * http://host.openshell.internal:8001.
 */
const http = require("http");
const fs = require("fs");
const path = require("path");

// [v0.0.50 Fix #3] Node.js 22 built-in EnvHttpProxyAgent routes ALL requests
// through the OpenShell proxy (10.200.0.1:3128) when HTTP_PROXY is set.
// Create a direct agent to bypass it.
const directAgent = new http.Agent();

// ---------------------------------------------------------------------------
// Config: read API URL from .env or environment
// ---------------------------------------------------------------------------
const API_URL = (() => {
  try {
    const envPath = path.join(__dirname, "..", ".env");
    const lines = fs.readFileSync(envPath, "utf8").split("\n");
    for (const line of lines) {
      const m = line.match(/^RETAIL_API_URL=(.*)$/);
      if (m) return m[1].trim();
    }
  } catch {}
  return process.env.RETAIL_API_URL || "http://host.openshell.internal:8001";
})();

const parsed = new URL(API_URL);
const API_HOST = parsed.hostname;
const API_PORT = parseInt(parsed.port || "8001", 10);

// ---------------------------------------------------------------------------
// HTTP helper
// ---------------------------------------------------------------------------
function apiRequest(method, routePath, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const opts = {
      hostname: API_HOST,
      port: API_PORT,
      path: routePath,
      method,
      headers: { ...headers },
      agent: directAgent,
    };
    let payload;
    if (body && typeof body === "string") {
      // form-urlencoded
      opts.headers["Content-Type"] = "application/x-www-form-urlencoded";
      payload = body;
      opts.headers["Content-Length"] = Buffer.byteLength(payload);
    } else if (body) {
      payload = JSON.stringify(body);
      opts.headers["Content-Type"] = "application/json";
      opts.headers["Content-Length"] = Buffer.byteLength(payload);
    }
    const req = http.request(opts, (res) => {
      let buf = "";
      res.on("data", (d) => (buf += d));
      res.on("end", () => {
        if (res.statusCode >= 400) {
          let detail = buf;
          try { detail = JSON.parse(buf).detail || buf; } catch {}
          reject(new Error(`HTTP ${res.statusCode}: ${detail}`));
        } else {
          try { resolve(JSON.parse(buf)); }
          catch { resolve(buf); }
        }
      });
    });
    req.on("error", (e) =>
      reject(new Error(`API (${API_URL}) unreachable: ${e.message}`))
    );
    req.setTimeout(30000, () => {
      req.destroy();
      reject(new Error(`API (${API_URL}) timeout`));
    });
    if (payload) req.write(payload);
    req.end();
  });
}

// ---------------------------------------------------------------------------
// Auth: login and return JWT token
// ---------------------------------------------------------------------------
async function login(email, password) {
  const body = `username=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`;
  const resp = await apiRequest("POST", "/auth/login", body);
  return resp.access_token;
}

async function loginByTelegram(telegramId) {
  const resp = await apiRequest("POST", "/auth/login-telegram", { telegram_id: telegramId });
  return resp.access_token;
}

function authHeader(token) {
  return { Authorization: `Bearer ${token}` };
}

// ---------------------------------------------------------------------------
// Arg parsing
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const args = {};
  const positional = [];
  let i = 0;
  while (i < argv.length) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (!next || next.startsWith("--")) {
        args[key] = true;
        i++;
      } else {
        args[key] = next;
        i += 2;
      }
    } else {
      positional.push(a);
      i++;
    }
  }
  return { args, positional };
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

async function cmdMe(token) {
  return apiRequest("GET", "/auth/me", null, authHeader(token));
}

async function cmdProducts(token, args) {
  const params = new URLSearchParams();
  if (args.category) params.set("category", args.category);
  if (args.brand) params.set("brand", args.brand);
  if (args.season) params.set("season", args.season);
  const qs = params.toString();
  return apiRequest("GET", `/products${qs ? "?" + qs : ""}`, null, authHeader(token));
}

async function cmdInventory(token, args) {
  const params = new URLSearchParams();
  if (args.store) params.set("store_id", args.store);
  if (args.product) params.set("product_id", args.product);
  if (args["low-stock"]) params.set("low_stock_only", "true");
  const qs = params.toString();
  return apiRequest("GET", `/inventory${qs ? "?" + qs : ""}`, null, authHeader(token));
}

async function cmdCustomers(token, args) {
  const params = new URLSearchParams();
  if (args.id) params.set("customer_id", args.id);
  if (args["customer-email"]) params.set("email", args["customer-email"]);
  const qs = params.toString();
  return apiRequest("GET", `/customers${qs ? "?" + qs : ""}`, null, authHeader(token));
}

async function cmdPromotions(token, args) {
  const params = new URLSearchParams();
  if (args.all) params.set("active_only", "false");
  const qs = params.toString();
  return apiRequest("GET", `/promotions${qs ? "?" + qs : ""}`, null, authHeader(token));
}

async function cmdSales(token, args) {
  const params = new URLSearchParams();
  if (args.store) params.set("store_id", args.store);
  const qs = params.toString();
  return apiRequest("GET", `/sales-performance${qs ? "?" + qs : ""}`, null, authHeader(token));
}

async function cmdQuery(token, args, positional) {
  const sql = positional[0] || args.sql;
  if (!sql) {
    throw new Error("Usage: query \"SELECT ...\"");
  }
  return apiRequest("POST", "/query", { sql }, authHeader(token));
}

async function resolveProductId(token, nameOrId) {
  const n = parseInt(nameOrId);
  if (!isNaN(n)) return n;
  // Treat as product name — look up the id
  const resp = await apiRequest(
    "POST", "/query",
    { sql: `SELECT id FROM products WHERE product_name ILIKE '%${nameOrId.replace(/'/g, "''")}%' LIMIT 1` },
    authHeader(token),
  );
  const rows = resp.rows || resp;
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error(`No product found matching "${nameOrId}"`);
  }
  return rows[0].id;
}

async function cmdTransfer(token, args) {
  if (!args.product || !args["to-store"] || !args.quantity) {
    throw new Error("Required: --product N --to-store N --quantity N");
  }
  const productId = await resolveProductId(token, args.product);
  const body = {
    product_id: productId,
    to_store_id: parseInt(args["to-store"]),
    quantity: parseInt(args.quantity),
  };
  if (args.size) body.size = args.size;
  if (args.color) body.color = args.color;
  if (args.notes) body.notes = args.notes;
  if (args["from-store"]) body.from_store_id = parseInt(args["from-store"]);
  return apiRequest("POST", "/inventory/transfer", body, authHeader(token));
}

async function cmdReorder(token, args) {
  if (!args.product || !args.quantity) {
    throw new Error("Required: --product N --quantity N");
  }
  const productId = await resolveProductId(token, args.product);
  const body = {
    product_id: productId,
    requested_quantity: parseInt(args.quantity),
    triggered_by: args["triggered-by"] || "manual",
  };
  if (args.size) body.size = args.size;
  if (args.color) body.color = args.color;
  if (args.store) body.store_id = parseInt(args.store);
  return apiRequest("POST", "/reorder", body, authHeader(token));
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const USAGE = `
Araz Retail API CLI

Usage: node retail-api.js <command> --telegram-id TID [options]
       node retail-api.js <command> --email E --password P [options]

Commands:
  me                                          Current user info
  products  [--category X] [--brand X] [--season X]
  inventory [--store N] [--product N] [--low-stock]
  customers [--id N] [--customer-email X]
  promotions [--all]
  sales     [--store N]
  query     "SQL statement"                   Run a custom SQL query
  transfer  --product ID_OR_NAME --to-store N --quantity N [--size S] [--color C] [--from-store N] [--notes T]
  reorder   --product ID_OR_NAME --quantity N [--store N] [--size S] [--color C]

Auth (one of the following):
  --telegram-id TID   Authenticate via Telegram user ID (preferred)
  --email EMAIL       Employee email (requires --password)
  --password PASS     Employee password (requires --email)
`.trim();

async function main() {
  const raw = process.argv.slice(2);
  if (raw.length === 0 || raw.includes("--help") || raw.includes("-h")) {
    console.log(USAGE);
    process.exit(0);
  }

  const command = raw[0];
  const { args, positional } = parseArgs(raw.slice(1));

  if (!args["telegram-id"] && (!args.email || !args.password)) {
    console.error("Error: --telegram-id or (--email and --password) are required for all commands.");
    process.exit(1);
  }

  let token;
  try {
    if (args["telegram-id"]) {
      token = await loginByTelegram(args["telegram-id"]);
    } else {
      token = await login(args.email, args.password);
    }
  } catch (e) {
    console.error("[RETAIL-API-ERROR] Login failed:", e.message);
    process.exit(1);
  }

  let result;
  try {
    switch (command) {
      case "me":
        result = await cmdMe(token);
        break;
      case "products":
        result = await cmdProducts(token, args);
        break;
      case "inventory":
        result = await cmdInventory(token, args);
        break;
      case "customers":
        result = await cmdCustomers(token, args);
        break;
      case "promotions":
        result = await cmdPromotions(token, args);
        break;
      case "sales":
        result = await cmdSales(token, args);
        break;
      case "query":
        result = await cmdQuery(token, args, positional);
        break;
      case "transfer":
        result = await cmdTransfer(token, args);
        break;
      case "reorder":
        result = await cmdReorder(token, args);
        break;
      default:
        console.error(`Unknown command: ${command}\n`);
        console.log(USAGE);
        process.exit(1);
    }
  } catch (e) {
    console.error("[RETAIL-API-ERROR]", e.message);
    process.exit(1);
  }

  console.log("[RETAIL-API-OK]");
  console.log(JSON.stringify(result, null, 2));
}

main();
