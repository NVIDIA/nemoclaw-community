// SPDX-License-Identifier: Apache-2.0

import {weatherTool} from './weather/tool.mjs';

// Bound this app's research and static review. Never change OpenShell policies.
const sessions = new Map();
const reviews = new Map();
const loungeRuns = new Map();
const TTL = 15 * 60 * 1000;
const workspaceWarmups = new Map();

async function warmWorkspace(config, agentId, workspaceDir) {
  const {resolveSandboxContext} = await import('openclaw/plugin-sdk/agent-harness-runtime');
  const sessionKey = `agent:${agentId}:openai-user:${agentId}`;
  const ctx = await resolveSandboxContext({config, agentId, sessionKey, workspaceDir, requireCurrentConfig:true});
  try {
    if (ctx?.agentId !== agentId || ctx.backendId !== 'openshell' || ctx.workspaceAccess !== 'rw') throw Error('Unexpected workspace');
    // The native mirror backend serializes this operation with tools on the same workspace.
    const probe = await ctx.backend.runShellCommand({script:'printf bac-ready', args:[], signal:AbortSignal.timeout(150000)});
    if (probe.stdout.toString() !== 'bac-ready') throw Error('Workspace probe failed');
  } finally {
    ctx?.[Symbol.dispose]?.();
  }
}

async function handleWorkspaceWarmup(request) {
  const {agentId, waitOnly = false} = request.params ?? {};
  if (typeof agentId !== 'string' || !/^bac-[a-f0-9]{24}(?:-r9)?$/.test(agentId) || typeof waitOnly !== 'boolean' ||
      Object.keys(request.params).some(k => k !== 'agentId' && k !== 'waitOnly')) {
    request.respond(false, undefined, {code:'INVALID_REQUEST', message:'A protected hire or standby Shell is required.'});
    return;
  }
  if (waitOnly) {
    // Cleanup and policy reads need quiescence even if a probe failed.
    await workspaceWarmups.get(agentId)?.catch(() => {});
    request.respond(true, {idle:true});
    return;
  }
  const config = request.context.getRuntimeConfig();
  const entry = config.agents?.entries?.[agentId];
  if (entry?.sandbox?.backend !== 'openshell' || entry.sandbox.mode !== 'all' ||
      entry.sandbox.scope !== 'agent' || entry.sandbox.workspaceAccess !== 'rw' || !entry.workspace) {
    request.respond(false, undefined, {code:'INVALID_REQUEST', message:'A protected agent workspace is required.'});
    return;
  }
  let pending = workspaceWarmups.get(agentId);
  if (!pending) {
    pending = warmWorkspace(config, agentId, entry.workspace).finally(() => workspaceWarmups.delete(agentId));
    workspaceWarmups.set(agentId, pending);
  }
  try {
    await pending;
    request.respond(true, {ready:true});
  } catch {
    request.respond(false, undefined, {code:'UNAVAILABLE', message:'The protected workspace could not be warmed.'});
  }
}

async function verifyProtectedWorkspace(api, request) {
  const agentId=request.params?.agentId;
  const config=request.context?.getRuntimeConfig?.()||api.config;
  const entry=typeof agentId==='string' ? config.agents?.entries?.[agentId] : undefined;
  if(!/^bac-[a-f0-9]{24}(?:-r(?:0|[1-9][0-9]*))?$/.test(agentId||'')||entry?.sandbox?.backend!=='openshell'||entry.sandbox.mode!=='all'||typeof entry.workspace!=='string'){
    request.respond(false,undefined,{code:'INVALID_REQUEST',message:'A protected Multi-Agent Studio agent is required.'});
    return;
  }
  try{
    const authority=api.runtime.sandbox.resolveWorkspaceAuthority({
      config,agentId,sessionKey:`agent:${agentId}:main`
    });
    // confinementError concerns delegation by this plugin. BaC delegates no
    // tools here; it only verifies the agent run's own sandbox selection.
    if(!authority?.sandboxed||authority.workspaceAccess!=='rw')throw Error('OpenShell protection was not confirmed');
    request.respond(true,{backend:'openshell'});
  }catch(error){
    api.logger.error(`Multi-Agent Studio protected workspace verification failed: ${error instanceof Error ? error.message : String(error)}`);
    request.respond(false,undefined,{code:'UNAVAILABLE',message:'The protected workspace could not be verified.'});
  }
}
// UTF-8 bytes are a conservative bound for multilingual source text too.
function boundedDetails(details, additions) {
  const safe = {};
  for (const key of ['status','exitCode','signal','durationMs','lineCount','totalLines']) {
    const value=details?.[key];
    if (typeof value==='number'||typeof value==='boolean'||(typeof value==='string'&&value.length<=500)) safe[key]=value;
  }
  return {...safe,...additions};
}
function takeText(value, limit) {
  const bytes = Buffer.from(value, 'utf8');
  if (bytes.length <= limit) return value;
  let end = Math.max(0, limit);
  while (end > 0 && (bytes[end] & 0xc0) === 0x80) end--;
  return bytes.subarray(0,end).toString('utf8');
}
function loungeKey(ctx) {
  const id = ctx.agentId || '';
  return /^bac-[a-f0-9]{24}$/.test(id) && ctx.sessionKey === `agent:${id}:openai-user:${id}` ? ctx.sessionKey : null;
}
function loungeState(event, ctx) {
  const key = loungeKey(ctx), run = event.runId || ctx.runId;
  if (!key || !run) return null;
  const now = Date.now();
  for (const [k, v] of loungeRuns) if (now - v.updated > TTL) loungeRuns.delete(k);
  if (loungeRuns.get(key)?.run !== run) {
    if (loungeRuns.size >= 1000) loungeRuns.delete(loungeRuns.keys().next().value);
    loungeRuns.set(key, {run, searches: 0, fetches: 0, calls: new Map(), updated: now});
  }
  const state = loungeRuns.get(key);state.updated = now;return state;
}
const spillFile = /(?:^|[\\/])openclaw-web-fetch-[a-f0-9]+\.log$/i;
function reviewState(ctx) {
  if (!/^bac-[a-f0-9]{24}(?:-r4)?$/.test(ctx.agentId || '')) return null;
  const match = (ctx.sessionKey || '').match(/:openai-user:bac-plan-([a-f0-9]{24})-4-(?:working|revising)(?:-output-retry)?$/);
  if (!match) return null;
  const now = Date.now(), key = ctx.agentId + ':' + match[1];
  for (const [k, v] of reviews) if (now - v.updated > TTL) reviews.delete(k);
  if (!reviews.has(key)) {
    if (reviews.size >= 1000) reviews.delete(reviews.keys().next().value);
    reviews.set(key, {reads: 0, chars: 0, ranges: new Set(), calls: new Map(), results: new Map(), updated: now});
  }
  const state = reviews.get(key);state.updated = now;return state;
}
function keyFor(ctx) {
  if (!/^bac-[a-f0-9]{24}(?:-r8)?$/.test(ctx.agentId || '')) return null;
  const match = (ctx.sessionKey || '').match(/:openai-user:bac-plan-([a-f0-9]{24})-([4-8])-(?:working|revising)(?:-output-retry)?$/);
  if (!match || (ctx.agentId.endsWith('-r8') && match[2] !== '8')) return null;
  return ctx.agentId + ':' + match[1];
}
const eventRuns = new Map();
const fileRuns = new Map();
function fileState(ctx) {
  const agent = (ctx.agentId || '').match(/^bac-[a-f0-9]{24}(?:-r(\d+))?$/);
  if (!agent) return null;
  const role = agent[1], session = ctx.sessionKey || '';
  const plan = session.match(/:openai-user:(bac-plan-[a-f0-9]{24}-(\d+)-[a-z0-9-]+)$/);
  const event = session.match(/:openai-user:(bac-crew-[a-f0-9]{24}-(\d+)(?:-social|-page-repair-\d+)?(?:-(?:context|output)-recovery)?)$/);
  const match = plan || event;
  // Dylan and Vera have stricter, dedicated guards below.
  if (!match || (role && match[2] !== role) || (!role && !plan) || (plan && match[2] === '4') || (event && role === '1')) return null;
  const now = Date.now(), key = ctx.agentId + ':' + match[1];
  for (const [k,v] of fileRuns) if (now-v.updated>TTL) fileRuns.delete(k);
  if (!fileRuns.has(key)) {
    if (fileRuns.size>=1000) fileRuns.delete(fileRuns.keys().next().value);
    fileRuns.set(key,{updated:now,reads:0,chars:0,calls:new Map(),results:new Map()});
  }
  const state=fileRuns.get(key);state.updated=now;return state;
}
function eventState(ctx) {
  if (!/^bac-[a-f0-9]{24}-r1$/.test(ctx.agentId || '') ||
      !/:openai-user:bac-crew-[a-f0-9]{24}-1(?:-(?:context|output)-recovery)?$/.test(ctx.sessionKey || '')) return null;
  const now = Date.now(), key = ctx.sessionKey;
  for (const [k,v] of eventRuns) if (now-v.updated>TTL) eventRuns.delete(k);
  if (!eventRuns.has(key)) {
    if (eventRuns.size>=1000) eventRuns.delete(eventRuns.keys().next().value);
    eventRuns.set(key,{updated:now,reads:new Set(),calls:new Map(),results:new Map(),chars:0,search:0,read:0,evidence:0});
  }
  const state=eventRuns.get(key);state.updated=now;return state;
}
function eventBefore(event, state, ctx) {
  const id=event.toolCallId||ctx.toolCallId, params=event.params||{};
  if(id && state.calls.has(id))return state.calls.get(id);
  let result;
  const block=reason=>({block:true,blockReason:reason});
  const finish='Use the evidence already returned, save the short demos JSON and run validate-themes. Report missing evidence honestly.';
  if(event.toolName==='read') {
    const path=String(params.path||params.file_path||'').replace(/\\/g,'/');
    const normalized=path.replace(/^.*\/(skills|inbox|artifacts)\//,'$1/');
    if(/-research\.json$|\.py$/.test(path)) result=block('Bulk research and tool-source reads are disabled for this mission. Use the event tool evidence action for bounded saved article excerpts. '+finish);
    else if(state.reads.has(normalized)||state.chars>=18000)result=block('This file was already read or the reading budget is exhausted. '+finish);
    else {state.reads.add(normalized);result={params:{...params,limit:Math.min(100,Math.max(1,Number(params.limit)||100))}};}
  } else if(event.toolName==='exec') {
    const command=String(params.command||'').trim();
    const match=command.match(/^python3?\s+(?:\/sandbox\/)?skills\/bac-event-tools\/scripts\/event_agent_tools\.py\s+(search|read|evidence|validate-themes)(?:\s+[^;&|`$<>\n\r]*)?$/);
    if(!match)result=block('Only direct shipped event-tool commands are available for this mission. No shell inspection, inline Python, pipelines or file copies. '+finish);
    else {
      const action=match[1],limits={search:2,read:2,evidence:2};
      if(action!=='validate-themes'&&(state[action]>=limits[action]||state.chars>=18000))result=block('Research command budget exhausted. '+finish);
      else {if(action!=='validate-themes')state[action]++;result={params:{...params,host:'sandbox',workdir:'/sandbox'}};}
    }
  }
  if(id&&result)state.calls.set(id,result);
  return result;
}
export function beforeTool(event, ctx) {
  const eventRun=eventState(ctx);
  const files = fileState(ctx);
  let normalized;
  // Models sometimes drop the leading slash from their own workspace path.
  // Translate only this agent's exact prefix, never another owner's path.
  if ((eventRun || files || reviewState(ctx)) && ['read','write','edit'].includes(event.toolName)) {
    const identity=(ctx.agentId||'').match(/^bac-([a-f0-9]{24})(?:-r(\d+))?$/), params={...event.params};
    for (const key of ['path','file_path']) {
      const value=params[key];
      if (!identity || typeof value!=='string') continue;
      const prefix=`var/lib/bac/studio/workspaces/${identity[1]}${identity[2] ? "-"+identity[2] : ""}/`;
      const path=value.replace(/^\//,'');
      if (path.startsWith(prefix)) {
        const relative=path.slice(prefix.length);
        if (/^(?:inbox|artifacts|skills)\//.test(relative) && !relative.split('/').includes('..')) {
          params[key]=relative;normalized={params};
        }
      }
    }
    if (normalized) event={...event,params};
  }
  if(eventRun)return eventBefore(event,eventRun,ctx)||normalized;
  if (files && event.toolName === 'write' && ctx.sessionKey.includes(':openai-user:bac-plan-')) {
    const {path, file_path, content} = event.params || {};
    const page = String(path || file_path || '').replaceAll('\\', '/');
    if (/(?:^|\/)artifacts\/.+\.html$/i.test(page) && typeof content === 'string') {
      // A second write replaces the whole file. Keep a chat handoff from erasing authored HTML.
      if (files.authoredPages?.has(page) && !content.includes('<')) {
        return {block:true, blockReason:'Put the handoff note in your chat reply. To revise this page, supply HTML.'};
      }
      if (/<html\b/i.test(content) && /<\/html\s*>/i.test(content)) {
        files.authoredPages ??= new Set();
        files.authoredPages.add(page);
      }
    }
  }
  if (files && event.toolName === 'read') {
    const id = event.toolCallId || ctx.toolCallId;
    if (id && files.calls.has(id)) return files.calls.get(id);
    const params = event.params || {};
    if (spillFile.test(String(params.path || params.file_path || ''))) return {block:true,blockReason:'Use the bounded web excerpt already returned. Do not read its full-output file or claim full-page verification.'};
    const result = files.reads >= 16 || files.chars >= 24000
      ? {block:true,blockReason:'File reading budget reached. Save useful work and finish with explicit gaps. Do not claim unread content was verified or repeat full-file reads.'}
      : {params:{...params,limit:Math.min(120,Math.max(1,Math.floor(Number(params.limit)||120)))}};
    if (!result.block) files.reads++;
    if (id) files.calls.set(id,result);
    return result;
  }
  if (loungeKey(ctx)) {
    const params = event.params || {};
    // Reading web_fetch's full-output file bypasses maxCharsCap.
    if (event.toolName === 'read' && spillFile.test(String(params.path || params.file_path || ''))) {
      return {block: true, blockReason: 'This web page was already returned as a bounded excerpt. Do not read its full-output file. Use the excerpt, or fetch a specific abstract/article URL if essential evidence is missing and budget remains. Report missing details honestly.'};
    }
    if (['web_search', 'web_fetch'].includes(event.toolName)) {
      const state = loungeState(event, ctx), id = event.toolCallId || ctx.toolCallId;
      if (id && state?.calls.has(id)) return state.calls.get(id);
      const search = event.toolName === 'web_search';
      const blocked = state && (search ? state.searches >= 2 : state.fetches >= 5);
      const result = blocked
        ? {block: true, blockReason: 'This request has reached its research budget. Answer now using the evidence already retrieved, with source links and any gaps. Do not repeat browsing or read full-output files. Do not invent missing findings.'}
        : {params: {...params, ...(search ? {count: Math.min(3, Math.max(1, Number(params.count) || 3))} : {maxChars: Math.min(3000, Math.max(1, Number(params.maxChars) || 3000))})}};
      if (state && !blocked) state[search ? 'searches' : 'fetches']++;
      if (id && state) state.calls.set(id, result);
      return result;
    }
  }
  const review = event.toolName === 'read' && reviewState(ctx);
  if (review) {
    const id = event.toolCallId || ctx.toolCallId;
    if (id && review.calls.has(id)) return review.calls.get(id);
    const params = event.params || {}, offset = Math.max(1, Math.floor(Number(params.offset) || 1));
    const limit = Math.min(120, Math.max(1, Math.floor(Number(params.limit) || 120)));
    const path = String(params.path || params.file_path || '').replace(/\\/g, '/').replace(/^.*\/(inbox|artifacts)\//, '$1/').replace(/^\.\//, '');
    const range = JSON.stringify([path, offset, limit]);
    const result = review.reads >= 8 || review.chars >= 18000 || review.ranges.has(range)
      ? {block: true, blockReason: 'Review read budget reached or this source range was already read. Use the evidence already returned. Do not repeat reads or guess source paths. Finish the review now; explicitly report any unread portion and unverified requirements. A limited review is not a full verification.'}
      : {params: {...params, offset, limit}};
    if (!result.block) {review.reads++;review.ranges.add(range);}
    if (id) review.calls.set(id, result);
    return result;
  }
  const key = keyFor(ctx);
  if (!key || !['web_search', 'web_fetch', ...(/^bac-[a-f0-9]{24}$/.test(ctx.agentId||'')?['exec']:[])].includes(event.toolName)) return normalized;
  const now = Date.now();
  for (const [k, v] of sessions) if (now - v.updated > TTL) sessions.delete(k);
  if (!sessions.has(key)) {
    if (sessions.size >= 1000) sessions.delete(sessions.keys().next().value);
    sessions.set(key, {searches: 0, fetches: 0, calls: new Set(), searchCalls: new Set(), unavailableSearches: new Set(), updated: now});
  }
  const state = sessions.get(key), id = event.toolCallId || ctx.toolCallId;
  state.updated = now;
  if (id && state.calls.has(id)) return;
  const blocked = event.toolName === 'web_search' ? state.searches >= 2 : state.searches > state.unavailableSearches.size || state.fetches >= 5;
  if (blocked) return {block: true, blockReason: 'Demo research budget reached. This is an application pacing limit, not an OpenShell policy denial. Save the evidence already retrieved to the assigned brief and finish. Search excerpts are not full-page reads; report missing details honestly. Do not retry browsing or switch tools.'};
  if (id) state.calls.add(id);
  if (event.toolName === 'web_search') {
    state.searches++;
    if (id) state.searchCalls.add(id);
    return {params: {...event.params, count: Math.min(3, Math.max(1, Number(event.params.count) || 3))}};
  }
  state.fetches++;
  if(event.toolName==='exec'){
    // OpenClaw rejects the legacy timeout key, even alongside timeoutSeconds.
    const {timeout,...params}=event.params||{};
    const requested=Number(params.timeoutSeconds??timeout);
    return {params:{...params,timeoutSeconds:Number.isFinite(requested)&&requested>0?Math.min(40,Math.max(1,requested)):40}};
  }
  return {params: {...event.params, maxChars: Math.min(4000, Math.max(1, Number(event.params.maxChars) || 3000))}};
}
function excerpt(value, limit) {
  if (typeof value !== 'string' || value.length <= limit) return value;
  // Preserve the native untrusted-content delimiters around a shortened source.
  const wrapped = value.match(/^([\s\S]*?Source: Web Search\n---\n)([\s\S]*)(\n<<<END_EXTERNAL_UNTRUSTED_CONTENT id="[^"]+">>>\s*)$/);
  const note = '\n[Excerpt shortened by the demo; not a full-page read.]';
  return wrapped ? wrapped[1] + wrapped[2].slice(0, limit) + note + wrapped[3] : value.slice(0, limit) + note;
}
export function persistResult(event, ctx) {
  const files = fileState(ctx), fileTool = event.toolName || ctx.toolName;
  if (files && ['read','exec'].includes(fileTool) && Array.isArray(event.message?.content)) {
    const id = event.message.toolCallId || event.toolCallId;
    if (id && files.results.has(id)) return files.results.get(id);
    let left = Math.min(6000,Math.max(0,24000-files.chars)), truncated = false;
    const content = event.message.content.map(block => {
      if (block.type !== 'text' || typeof block.text !== 'string') return block;
      const text=takeText(block.text,left), used=Buffer.byteLength(text);left-=used;files.chars+=used;
      if (text.length === block.text.length) return block;
      const note=truncated?'':'\n[Task excerpt shortened; some content omitted. Read only a focused missing section if budget remains. Save useful work; report coverage limits honestly.]';
      truncated=true;return {...block,text:text+note};
    });
    const result = truncated ? {message:{...event.message,content,details:boundedDetails(event.message.details,{truncated:true,coverageLimited:true})}} : undefined;
    if (id) files.results.set(id,result);
    return result;
  }
  const eventRun=eventState(ctx), eventTool=event.toolName||ctx.toolName;
  if(eventRun && ['read','exec'].includes(eventTool) && Array.isArray(event.message?.content)) {
    const id=event.message.toolCallId||event.toolCallId;
    if(id&&eventRun.results.has(id))return eventRun.results.get(id);
    const validating=/\svalidate-themes\s*$/.test(eventRun.calls.get(id)?.params?.command||'');
    let left=validating?1000:Math.min(6000,Math.max(0,18000-eventRun.chars)), truncated=false;
    const content=event.message.content.map(b=>{
      if(b.type!=='text'||typeof b.text!=='string')return b;
      const text=takeText(b.text,left), used=Buffer.byteLength(text);left-=used;eventRun.chars+=used;
      const note=text.length<b.text.length&&!truncated?'\n[Event excerpt shortened; some content omitted. Use only visible evidence. Save themes and validate; do not dump full files.]':'';
      truncated ||= text.length<b.text.length;return {...b,text:text+note};
    });
    const result={message:{...event.message,content,details:boundedDetails(event.message.details,{bounded:true})}};
    if(id)eventRun.results.set(id,result);
    return result;
  }

  const review = (event.toolName || ctx.toolName) === 'read' && reviewState(ctx);
  if (review && Array.isArray(event.message?.content)) {
    const id = event.message.toolCallId || event.toolCallId;
    if (id && review.results.has(id)) return review.results.get(id);
    let remaining = event.message.isError ? 500 : Math.min(5000, Math.max(0, 18000 - review.chars)), truncated = false;
    const content = event.message.content.map(block => {
      if (block.type !== 'text' || typeof block.text !== 'string') return block;
      const text = takeText(block.text, remaining), used=Buffer.byteLength(text);remaining -= used;review.chars += used;
      if (text.length === block.text.length) return block;
      const note=truncated?'':'\n[Review excerpt shortened. Some source was omitted. Use a focused, unread offset/limit range if budget remains; otherwise report limited coverage. Never claim the entire file was verified.]';
      truncated=true;return {...block,text:text+note};
    });
    const result = truncated ? {message: {...event.message, content, details: boundedDetails(event.message.details,{truncated: true, reviewCoverageLimited: true})}} : undefined;
    if (id) review.results.set(id, result);
    return result;
  }
  const personal = loungeKey(ctx), tool = event.toolName || ctx.toolName;
  // Only an observed provider failure releases the search-first stop rule.
  // Pending/successful searches still stop follow-up reads; attempts are never
  // refunded, including across handoff repairs. Native access policy still applies.
  if (tool === 'web_search' && event.message?.isError) {
    const state = sessions.get(keyFor(ctx));
    const id = event.message.toolCallId || event.toolCallId || ctx.toolCallId;
    const text = (event.message.content || []).filter(b => b.type === 'text').map(b => b.text || '').join(' ').slice(0,16000);
    if (state?.searchCalls.has(id) && !/openshell|policy denial|policy denied/i.test(text) &&
        /(?:rate[ -]limit|too many requests|\b429\b|search.{0,50}(?:unavailable|timed out)|missing.{0,30}api.?key)/i.test(text)) {
      state.unavailableSearches.add(id);
      state.updated = Date.now();
    }
  }
  if ((!keyFor(ctx) && !personal) || !['web_search', 'web_fetch'].includes(tool) || event.message?.isError) return;
  if (tool === 'web_fetch') {
    if (!Array.isArray(event.message?.content)) return;
    // Preserve source metadata and untrusted markers, but do not invite a
    // full-page reread from the native temporary file.
    const clean = value => {
      if (!value || typeof value !== 'object' || typeof value.text !== 'string' || !value.spill) return value;
      const {spill, ...rest} = value;
      return {...rest, text: value.text.replace(/\n*\[(?:Showing truncated web_fetch content\.[^\]]*|Full output[^\]]*)\]\s*$/i, '') + '\n[Excerpt only. Some page content was omitted; do not read full-output files.]', truncated: true};
    };
    return {message: {...event.message, content: event.message.content.map(block => {
      if (block.type !== 'text') return block;
      try {return {...block, text: JSON.stringify(clean(JSON.parse(block.text)))};} catch {return block;}
    }), details: clean(event.message.details)}};
  }
  const blocks = event.message?.content;
  if (!Array.isArray(blocks)) return;
  let envelope;
  for (const block of blocks) {
    if (block.type !== 'text') continue;
    try { const v = JSON.parse(block.text); if (Array.isArray(v.results)) { envelope = v; break; } } catch {}
  }
  if (!envelope) return;
  const results = envelope.results.slice(0, 3).filter(r => r && typeof r === 'object').map(r => {
    const row = {};
    for (const k of ['title', 'url', 'snippet', 'description', 'siteName', 'published', 'publishedDate', 'date']) {
      if (typeof r[k] === 'string') row[k] = k === 'url' ? r[k] : excerpt(r[k], ['snippet', 'description'].includes(k) ? 1200 : 300);
    }
    return row;
  });
  const bounded = {kind: envelope.kind, provider: envelope.provider, query: excerpt(envelope.query, 500),
    count: results.length, results, externalContent: envelope.externalContent,
    truncated: true, note: 'Bounded source excerpts only. Save relevant findings and finish; do not claim full-page verification.'};
  return {message: {...event.message, content: [{type: 'text', text: JSON.stringify(bounded)}], details: bounded}};
}
export default {
  id: 'bac-research-guard',
  register(api) {
    api.registerTool(weatherTool, {name:'bac_weather', optional:true});
    api.on('before_tool_call', beforeTool);
    api.on('tool_result_persist', persistResult);
    api.registerGatewayMethod('bac.protection.verify',request=>verifyProtectedWorkspace(api,request),{scope:'operator.admin'});
    api.registerGatewayMethod('bac.protection.warm', handleWorkspaceWarmup, {scope:'operator.admin'});
  }
};
