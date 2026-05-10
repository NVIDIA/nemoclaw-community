// API client for the FastAPI backend.
// Uploads videos and streams chat responses via Server-Sent Events.

export type UploadResult = {
  sandbox_path: string;
  size_bytes: number;
  original_name: string;
  kind?: "video" | "audio" | "document";
  pages?: number;
};

export const AUDIO_EXTS = [".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"];

export async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/upload", {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`upload failed ${res.status}: ${text}`);
  }
  return res.json();
}

export type ChatEvent =
  | { type: "token"; text: string }
  | { type: "tool"; tool: string }
  | { type: "status"; text: string }
  | { type: "exec"; cmd: string; duration: string; exit: number }
  | { type: "session"; id: string }
  | { type: "done" }
  | { type: "error"; error: string };

/**
 * Stream a chat turn from Hermes. Calls `onEvent` for each parsed SSE message.
 * Returns a disposer that aborts the request.
 */
export function streamChat(
  prompt: string,
  videoPath: string | null,
  onEvent: (e: ChatEvent) => void,
  sessionId?: string | null,
  newSession?: boolean
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          video_path: videoPath,
          session_id: sessionId || null,
          new_session: !!newSession,
        }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        onEvent({
          type: "error",
          error: `chat request failed: ${res.status}`,
        });
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            onEvent(JSON.parse(payload) as ChatEvent);
          } catch {
            onEvent({ type: "token", text: payload });
          }
        }
      }
      onEvent({ type: "done" });
    } catch (e: any) {
      if (e.name === "AbortError") return;
      onEvent({ type: "error", error: e.message || String(e) });
    }
  })();

  return () => controller.abort();
}

export type PolicyEvent = {
  ts: number;
  verdict: "ALLOWED" | "DENIED";
  severity: string;
  binary: string;
  target: string;
};

export function subscribePolicy(
  onEvent: (e: PolicyEvent) => void
): () => void {
  const es = new EventSource("/api/policy/stream");
  es.onmessage = (ev) => {
    try {
      onEvent(JSON.parse(ev.data));
    } catch {}
  };
  es.onerror = () => {
    // Let it retry automatically
  };
  return () => es.close();
}

export type PolicyHost = {
  block: string;
  host: string;
  port: number;
  rules: string[];
  binaries: string[];
  is_demo_toggle: boolean;
};

export type PolicyRules = {
  google_allowed: boolean;
  hosts: PolicyHost[];
  block_count: number;
};

export async function getPolicyRules(): Promise<PolicyRules> {
  const res = await fetch("/api/policy/rules");
  if (!res.ok) throw new Error(`policy rules ${res.status}`);
  return res.json();
}

export async function transcribeAudio(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/transcribe", { method: "POST", body: form });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`transcribe ${res.status}: ${text}`);
  }
  const data = (await res.json()) as { text: string };
  return data.text || "";
}

export async function toggleGoogleAccess(enabled: boolean): Promise<{
  google_allowed: boolean;
  block_count: number;
}> {
  const res = await fetch("/api/policy/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`google toggle ${res.status}: ${text}`);
  }
  return res.json();
}

export type MemorySession = {
  id: string;
  started: string | null;
  updated: string | null;
  model: string;
  turns: number;
  total_messages: number;
  tool_calls: number;
  tools: string[];
  first_prompt: string;
  last_prompt: string;
  attachment_count: number;
};

export type MemorySummary = {
  stats: {
    total_sessions: number;
    total_turns: number;
    total_tool_calls: number;
    total_attachments: number;
    oldest: string | null;
  };
  top_tools: { name: string; count: number }[];
  recent: MemorySession[];
};

export async function getMemorySummary(limit = 25): Promise<MemorySummary> {
  const res = await fetch(`/api/memory/summary?limit=${limit}`);
  if (!res.ok) throw new Error(`memory ${res.status}`);
  return res.json();
}

export type DemoToggle = {
  key: string;
  name: string;
  hosts: string[];
  enabled: boolean;
};

export async function getToggles(): Promise<DemoToggle[]> {
  const res = await fetch("/api/policy/toggles");
  if (!res.ok) throw new Error(`toggles ${res.status}`);
  const data = (await res.json()) as { toggles: DemoToggle[] };
  return data.toggles;
}

export async function setToggle(key: string, enabled: boolean): Promise<void> {
  const res = await fetch("/api/policy/toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, enabled }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`toggle ${res.status}: ${text}`);
  }
}

export type RedTeamEvent =
  | { type: "start"; count: number }
  | { type: "running"; name: string; url: string }
  | {
      type: "result";
      name: string;
      url: string;
      http_code: string;
      blocked: boolean;
      duration_ms: number;
    }
  | { type: "done" };

export function runRedTeam(onEvent: (e: RedTeamEvent) => void): () => void {
  const controller = new AbortController();
  (async () => {
    try {
      const res = await fetch("/api/red-team", {
        method: "POST",
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        console.error("red team request failed", res.status);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            onEvent(JSON.parse(payload) as RedTeamEvent);
          } catch {}
        }
      }
    } catch (e: any) {
      if (e.name === "AbortError") return;
      console.error(e);
    }
  })();
  return () => controller.abort();
}
