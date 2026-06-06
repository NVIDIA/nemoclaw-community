// SPDX-License-Identifier: Apache-2.0
const templates = {
  snapshot:
    'Use the financial-market-snapshot skill to summarize NVDA, MSFT, and AAPL. Return a compact table and caveats.',
  earnings:
    'Create a concise earnings-prep checklist for NVDA using public market context and SEC facts. Separate facts from hypotheses.',
  sec:
    'Use the sec-company-facts skill for NVDA and summarize the latest available revenue, net income, assets, and operating cash flow facts.',
};

const statusEl = document.querySelector('#status');
const conversation = document.querySelector('#conversation');
const promptEl = document.querySelector('#prompt');
const baseUrlEl = document.querySelector('#baseUrl');
const apiTokenEl = document.querySelector('#apiToken');
const composer = document.querySelector('#composer');

function setStatus(text, busy = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle('busy', busy);
}

function addMessage(role, content) {
  const article = document.createElement('article');
  article.className = `message ${role}`;
  const label = document.createElement('strong');
  label.textContent = role === 'user' ? 'You' : 'Assistant';
  const body = document.createElement('p');
  body.textContent = content;
  article.append(label, body);
  conversation.append(article);
  conversation.scrollTop = conversation.scrollHeight;
}

async function sendPrompt(prompt) {
  const baseUrl = baseUrlEl.value.trim().replace(/\/$/, '');
  const token = apiTokenEl.value.trim();
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${baseUrl}/chat/completions`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      model: 'nvidia/nemotron-3-ultra-550b-a55b',
      messages: [
        {
          role: 'system',
          content:
            'You are a concise financial analyst assistant running through NemoClaw/Hermes. Use installed finance skills when helpful. Do not provide investment advice.',
        },
        { role: 'user', content: prompt },
      ],
      temperature: 0.2,
      max_tokens: 700,
    }),
  });

  if (!response.ok) {
    throw new Error(`API returned HTTP ${response.status}`);
  }
  const data = await response.json();
  return data?.choices?.[0]?.message?.content || '(No assistant message returned.)';
}

document.querySelectorAll('[data-template]').forEach((button) => {
  button.addEventListener('click', () => {
    promptEl.value = templates[button.dataset.template] || promptEl.value;
    promptEl.focus();
  });
});

composer.addEventListener('submit', async (event) => {
  event.preventDefault();
  const prompt = promptEl.value.trim();
  if (!prompt) return;
  addMessage('user', prompt);
  setStatus('Thinking', true);
  composer.querySelector('button[type="submit"]').disabled = true;
  try {
    const message = await sendPrompt(prompt);
    addMessage('assistant', message);
    setStatus('Ready');
  } catch (error) {
    addMessage('assistant', `Request failed: ${error.message}`);
    setStatus('Error');
  } finally {
    composer.querySelector('button[type="submit"]').disabled = false;
  }
});
