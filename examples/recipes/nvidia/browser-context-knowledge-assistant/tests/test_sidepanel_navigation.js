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
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const conversation = id => ({ conversation: { conversation_id: id }, messages: [] });

function fixture(fetch) {
  const renders = [], errors = [], stored = [], posts = [];
  const context = vm.createContext({
    AbortController,
    activeConversationId: 'A', activeJob: null, pendingSubmission: null,
    refreshGeneration: 0, refreshController: null, conversationLoadGeneration: 0,
    submissionControl: null, pollTimer: null,
    nemoClawDashboardUrl: 'https://agent.example', nemoClawServiceUrl: 'https://agent.example/api',
    elements: {
      conversationSelect: { value: 'A' }, prompt: { value: 'A new question' },
      sendButton: { disabled: false }, newConversationButton: {}, refreshButton: {},
      settingsButton: {}, disconnectButton: {}, stopButton: {}
    },
    chrome: { storage: { local: { set: async value => stored.push(value) } } },
    showStatus: () => {}, hideStatus: () => {}, clearError: () => {}, showSettings: () => {},
    showError: (...args) => errors.push(args),
    renderConversationMessages: messages => renders.push(messages),
    clearTimeout: () => {}, schedulePoll: () => {},
    conversationUrl: (id, suffix = '') => id + suffix,
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
