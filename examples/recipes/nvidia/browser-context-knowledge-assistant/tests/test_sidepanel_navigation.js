// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../extension/sidepanel.js'), 'utf8');
const section = (from, to) => source.slice(source.indexOf(from), source.indexOf(to));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((done, failed) => { resolve = done; reject = failed; });
  return { promise, resolve, reject };
};
const conversation = id => ({ conversation: { conversation_id: id }, messages: [] });

function fixture(fetch) {
  const renders = [], errors = [], stored = [], posts = [];
  const context = vm.createContext({
    AbortController,
    activeConversationId: 'A', activeJob: null, pendingSubmission: null, activePage: {},
    refreshGeneration: 0, refreshController: null, conversationLoadGeneration: 0,
    submissionControl: null, pollTimer: null,
    nemoClawDashboardUrl: 'https://agent.example', nemoClawServiceUrl: 'https://agent.example/api',
    elements: {
      conversationSelect: { value: 'A', prepend: () => {} },
      prompt: { value: 'A new question', focus: () => {} },
      sendButton: { disabled: false }, newConversationButton: { disabled: false },
      refreshButton: { disabled: false },
      settingsButton: {}, disconnectButton: {}, stopButton: {}
    },
    chrome: { storage: { local: { set: async value => stored.push(value) } } },
    document: { createElement: () => ({}) },
    showStatus: () => {}, hideStatus: () => {}, clearError: () => {}, showSettings: () => {},
    showError: (...args) => errors.push(args),
    renderConversationMessages: messages => renders.push(messages),
    clearTimeout: () => {}, schedulePoll: () => {},
    conversationUrl: (id, suffix = '') => id + suffix,
    conversationsEndpoint: () => 'conversations',
    refreshActivePage: async () => true,
    newIdempotencyKey: () => 'x'.repeat(24),
    captureContext: async () => ({ page_text: 'Example page' }),
    readJsonResponse: async response => response,
    authenticatedFetch: async (url, options) => {
      if (options?.method === 'POST') posts.push(url);
      if (fetch) return fetch(url, options);
      if (url.endsWith('/cancel')) return { job_id: 'job', status: 'cancelling' };
      if (url.endsWith('/messages')) return { job_id: 'job', status: 'queued' };
      return conversation(url);
    }
  });
  vm.runInContext(section('async function loadConversation(', 'async function loadConversationList('), context);
  vm.runInContext(section('function showCreatedConversation(', 'function schedulePoll('), context);
  vm.runInContext(section('async function submitMessage(', 'async function initialize('), context);
  return { context, renders, errors, stored, posts };
}

test('Send is disabled until the selected conversation has loaded', async () => {
  const loading = deferred();
  const f = fixture((url, options) => options?.method === 'POST'
    ? { job_id: 'job', status: 'queued' } : loading.promise);
  const selection = f.context.selectConversation('B');
  assert.equal(f.context.activeConversationId, null);
  assert.equal(f.context.elements.sendButton.disabled, true);
  await f.context.submitMessage();
  assert.equal(f.posts.length, 0);
  loading.resolve(conversation('B'));
  await selection;
  assert.equal(f.context.activeConversationId, 'B');
  assert.equal(f.context.elements.sendButton.disabled, false);
  await f.context.submitMessage();
  assert.deepEqual(f.posts, ['B/messages']);
});

test('an older response cannot replace a later selection', async () => {
  const responses = { B: deferred(), C: deferred() };
  const f = fixture(url => responses[url].promise);
  const b = f.context.selectConversation('B');
  const c = f.context.selectConversation('C');
  responses.C.resolve(conversation('C'));
  await c;
  responses.B.resolve(conversation('B'));
  await b;
  assert.equal(f.context.activeConversationId, 'C');
  assert.equal(f.context.elements.conversationSelect.value, 'C');
  assert.equal(f.renders.length, 1);
  assert.equal(f.stored.at(-1).askNemoClawConversationId, 'C');
});

test('selection failures do not allow sending to the previous conversation', async () => {
  const f = fixture(async () => { throw new Error('Unavailable'); });
  await f.context.selectConversation('B');
  await f.context.submitMessage();
  assert.equal(f.context.activeConversationId, null);
  assert.equal(f.context.elements.sendButton.disabled, true);
  assert.equal(f.posts.length, 0);
});

for (const [operation, button] of [
  ['createNewConversation', 'newConversationButton'],
  ['refreshPageAndCreateConversation', 'refreshButton']
]) {
  test(`${operation}: selecting a conversation restores cancelled controls`, async () => {
    const creation = deferred(), started = deferred(), loading = deferred();
    let signal;
    const f = fixture((url, options) => {
      if (url === 'conversations') {
        signal = options.signal;
        started.resolve();
        return creation.promise;
      }
      return loading.promise;
    });
    const pending = f.context[operation]();
    await started.promise;
    assert.equal(f.context.elements[button].disabled, true);
    const selection = f.context.selectConversation('B');
    assert.equal(signal.aborted, true);
    assert.equal(f.context.elements.newConversationButton.disabled, false);
    assert.equal(f.context.elements.refreshButton.disabled, false);
    assert.equal(f.context.elements.sendButton.disabled, true);
    creation.reject(Object.assign(new Error('Cancelled'), { cancelled: true }));
    await pending;
    assert.equal(f.context.elements.sendButton.disabled, true);
    loading.resolve(conversation('B'));
    await selection;
    assert.equal(f.context.activeConversationId, 'B');
    assert.equal(f.context.elements[button].disabled, false);
    assert.equal(f.context.elements.sendButton.disabled, false);
    assert.equal(f.errors.length, 0);
  });

  test(`${operation}: failed selection still restores New and Refresh`, async () => {
    const creation = deferred(), started = deferred();
    const f = fixture((url) => {
      if (url === 'conversations') { started.resolve(); return creation.promise; }
      throw new Error('Unavailable');
    });
    const pending = f.context[operation]();
    await started.promise;
    await f.context.selectConversation('B');
    creation.resolve(conversation('obsolete'));
    await pending;
    assert.equal(f.context.elements.newConversationButton.disabled, false);
    assert.equal(f.context.elements.refreshButton.disabled, false);
    assert.equal(f.context.elements.sendButton.disabled, true);
    assert.equal(f.context.activeConversationId, null);
  });

  test(`${operation}: late cancellation cannot enable a newer operation's controls`, async () => {
    const oldCreation = deferred(), newCreation = deferred(), started = deferred();
    let creations = 0;
    const f = fixture((url) => {
      if (url !== 'conversations') return conversation(url);
      creations += 1;
      started.resolve();
      return creations === 1 ? oldCreation.promise : newCreation.promise;
    });
    const oldPending = f.context[operation]();
    await started.promise;
    await f.context.selectConversation('B');
    assert.equal(f.context.elements[button].disabled, false);
    const newPending = f.context[operation]();
    oldCreation.resolve(conversation('obsolete'));
    await oldPending;
    assert.equal(f.context.elements[button].disabled, true);
    assert.equal(f.context.elements.sendButton.disabled, true);
    newCreation.resolve(conversation('new'));
    await newPending;
    assert.equal(f.context.activeConversationId, 'new');
    assert.equal(f.context.elements[button].disabled, false);
    assert.equal(f.context.elements.sendButton.disabled, false);
  });
}

test('Stop during page capture prevents message submission', async () => {
  const capture = deferred();
  const f = fixture();
  f.context.captureContext = () => capture.promise;
  const sending = f.context.submitMessage();
  await f.context.stopActiveJob();
  capture.resolve({ page_text: 'Example page' });
  await sending;
  assert.equal(f.posts.length, 0);
  assert.equal(f.context.pendingSubmission, null);
  assert.equal(f.context.elements.sendButton.disabled, false);
});

test('Stop during upload cancels the job when its identifier arrives', async () => {
  const upload = deferred(), started = deferred();
  const f = fixture((url) => {
    if (url === 'A/messages') { started.resolve(); return upload.promise; }
    if (url.endsWith('/cancel')) return { job_id: 'job', status: 'cancelling' };
    return conversation('A');
  });
  const sending = f.context.submitMessage();
  await started.promise;
  await f.context.stopActiveJob();
  upload.resolve({ job_id: 'job', status: 'queued' });
  await sending;
  assert.deepEqual(f.posts, ['A/messages', 'A/messages/job/cancel']);
  assert.equal(f.context.activeJob.status, 'cancelling');
});

test('HTML 413 responses are size errors, not sign-in errors', async () => {
  const context = vm.createContext({
    authenticationError: () => Object.assign(new Error('Sign in'), { authenticationRequired: true })
  });
  vm.runInContext(section('function errorDetailFromResponse(', 'function renderConversationMessages('), context);
  await assert.rejects(context.readJsonResponse(new Response('<html>Too large</html>', {
    status: 413, headers: { 'Content-Type': 'text/html' }
  })), error => /413/.test(error.message) && !error.authenticationRequired);
  await assert.rejects(context.readJsonResponse(new Response('<html>Sign in</html>', {
    status: 200, headers: { 'Content-Type': 'text/html' }
  })), error => error.authenticationRequired === true);
});
