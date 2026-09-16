// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

(() => {
  const STORAGE_KEY = "askNemoClawBearerSession";
  const ACCESS_COOKIE = "hermes_session_at";
  const REFRESH_COOKIE = "hermes_session_rt";
  const PROVIDER_COOKIE = "hermes_session_provider";
  const COOKIE_PREFIXES = ["__Host-", "__Secure-", ""];
  const CLOCK_SKEW_SECONDS = 30;
  const MAX_TOKEN_CHARS = 16_384;

  function validToken(value) {
    return typeof value === "string" && value.length >= 16 && value.length <= MAX_TOKEN_CHARS;
  }

  function cookieByName(cookies, bareName) {
    for (const prefix of COOKIE_PREFIXES) {
      const match = cookies.find(cookie => cookie.name === `${prefix}${bareName}`);
      if (match) return match;
    }
    return null;
  }

  function cookieTemplate(cookie) {
    if (!cookie) return null;
    return {
      name: cookie.name,
      path: cookie.path || "/",
      secure: cookie.secure !== false,
      httpOnly: cookie.httpOnly !== false,
      sameSite: cookie.sameSite || "lax",
      expirationDate: Number(cookie.expirationDate || 0)
    };
  }

  function normalizedSession(value, origin) {
    if (!value || value.origin !== origin || !validToken(value.accessToken)) return null;
    const expiresAt = Number(value.expiresAt || 0);
    return {
      origin,
      accessToken: value.accessToken,
      refreshToken: validToken(value.refreshToken) ? value.refreshToken : "",
      provider: typeof value.provider === "string" ? value.provider.slice(0, 128) : "",
      expiresAt: Number.isFinite(expiresAt) ? expiresAt : 0,
      accessCookie: cookieTemplate(value.accessCookie),
      refreshCookie: cookieTemplate(value.refreshCookie)
    };
  }

  function sessionIsCurrent(session) {
    return session && (!session.expiresAt || session.expiresAt > Date.now() / 1000 + CLOCK_SKEW_SECONDS);
  }

  async function storedSession(origin) {
    const stored = await chrome.storage.session.get(STORAGE_KEY);
    return normalizedSession(stored[STORAGE_KEY], origin);
  }

  async function saveSession(session) {
    await chrome.storage.session.set({ [STORAGE_KEY]: session });
    return session;
  }

  async function clearSession() {
    await chrome.storage.session.remove(STORAGE_KEY);
  }

  async function cookieSession(origin) {
    const cookies = await chrome.cookies.getAll({ url: `${origin}/` });
    const access = cookieByName(cookies, ACCESS_COOKIE);
    if (!access || !validToken(access.value)) return null;
    const refresh = cookieByName(cookies, REFRESH_COOKIE);
    const provider = cookieByName(cookies, PROVIDER_COOKIE);
    return {
      origin,
      accessToken: access.value,
      refreshToken: refresh && validToken(refresh.value) ? refresh.value : "",
      provider: provider?.value?.slice(0, 128) || "",
      expiresAt: Number(access.expirationDate || 0),
      accessCookie: cookieTemplate(access),
      refreshCookie: cookieTemplate(refresh)
    };
  }

  async function availableRefresh(origin) {
    const stored = await storedSession(origin);
    if (stored?.refreshToken) return stored;
    const cookies = await chrome.cookies.getAll({ url: `${origin}/` });
    const refresh = cookieByName(cookies, REFRESH_COOKIE);
    if (!refresh || !validToken(refresh.value)) return null;
    const provider = cookieByName(cookies, PROVIDER_COOKIE);
    return {
      origin,
      accessToken: stored?.accessToken || "",
      refreshToken: refresh.value,
      provider: provider?.value?.slice(0, 128) || "",
      expiresAt: stored?.expiresAt || 0,
      accessCookie: stored?.accessCookie || null,
      refreshCookie: cookieTemplate(refresh)
    };
  }

  function cookieDetails(origin, template, bareName, value, expirationDate) {
    return {
      url: `${origin}/`,
      name: template?.name || `__Host-${bareName}`,
      value,
      path: template?.path || "/",
      secure: true,
      httpOnly: true,
      sameSite: template?.sameSite || "lax",
      expirationDate
    };
  }

  async function synchronizeCookies(origin, current, body) {
    const accessExpiration = Number(body.expires_at || Date.now() / 1000 + 15 * 60);
    const refreshExpiration = Number(
      current.refreshCookie?.expirationDate || Date.now() / 1000 + 30 * 24 * 60 * 60
    );
    await chrome.cookies.set(cookieDetails(
      origin,
      current.accessCookie,
      ACCESS_COOKIE,
      body.access_token,
      accessExpiration
    ));
    if (validToken(body.refresh_token)) {
      await chrome.cookies.set(cookieDetails(
        origin,
        current.refreshCookie,
        REFRESH_COOKIE,
        body.refresh_token,
        refreshExpiration
      ));
    }
  }

  async function refreshSession(origin, options = {}) {
    const current = await availableRefresh(origin);
    if (!current?.refreshToken) return null;
    const response = await fetch(`${origin}/auth/native/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        refresh_token: current.refreshToken,
        provider: current.provider
      }),
      credentials: "omit",
      cache: "no-store",
      redirect: "manual",
      signal: options.signal
    });
    if (!response.ok) {
      if (response.status === 400 || response.status === 401) await clearSession();
      return null;
    }
    const body = await response.json();
    if (!validToken(body.access_token)) {
      await clearSession();
      return null;
    }
    const session = await saveSession({
      origin,
      accessToken: body.access_token,
      refreshToken: validToken(body.refresh_token) ? body.refresh_token : "",
      provider: typeof body.provider === "string" ? body.provider.slice(0, 128) : current.provider,
      expiresAt: Number(body.expires_at || 0),
      accessCookie: current.accessCookie,
      refreshCookie: current.refreshCookie
    });
    // Keep the dashboard's HttpOnly cookies aligned when the refresh endpoint
    // rotates tokens. The bearer session remains usable if Chrome refuses
    // this best-effort synchronization.
    try {
      await synchronizeCookies(origin, current, body);
    } catch (_) {
      // Do not log token-bearing cookie details.
    }
    return session;
  }

  async function sessionForRequest(origin, options = {}) {
    if (options.forceRefresh) return refreshSession(origin, options);
    const stored = await storedSession(origin);
    if (sessionIsCurrent(stored)) return stored;
    const fromCookie = await cookieSession(origin);
    if (sessionIsCurrent(fromCookie)) return saveSession(fromCookie);
    return refreshSession(origin, options);
  }

  globalThis.AskNemoClawAuth = Object.freeze({
    clearSession,
    sessionForRequest
  });
})();
