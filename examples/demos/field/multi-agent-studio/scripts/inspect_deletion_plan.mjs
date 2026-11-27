// SPDX-License-Identifier: Apache-2.0

// Read-only proof for definitions that never acquired native runtime state.
// Check a deletion plan in one process; never cache this across deletion attempts.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [root, encoded] = process.argv.slice(2), ids = JSON.parse(encoded);
if (!Array.isArray(ids) || !ids.length || ids.length > 256 || new Set(ids).size !== ids.length ||
    ids.some(id => typeof id !== 'string' || !/^bac-[a-f0-9]{24}(?:-r(?:0|[1-9][0-9]*))?$/.test(id)) ||
    ids.some(id => id.slice(0,28) !== ids[0].slice(0,28))) throw Error('Invalid deletion plan');
const pkg = path.join(root, 'package/node_modules/openclaw');
if (JSON.parse(await fs.readFile(path.join(pkg,'package.json'),'utf8')).version !== '2026.11.3') throw Error('Unsupported native runtime version');
const dist = path.join(pkg,'dist'), files = await fs.readdir(dist);
async function nativeExport(prefix, symbol) {
  for (const name of files.filter(n => n.startsWith(prefix) && n.endsWith('.mjs'))) {
    const file = path.join(dist,name), source = await fs.readFile(file,'utf8');
    const alias = source.match(new RegExp('\\b'+symbol+' as (\\w+)\\b'))?.[1];
    if (alias) return (await import(pathToFileURL(file)))[alias];
  }
  throw Error('Pinned native inspection API unavailable');
}
const config = JSON.parse(await fs.readFile(process.env.OPENCLAW_CONFIG_PATH,'utf8'));
const entries = config.agents?.entries;
if (!entries || typeof entries !== 'object' || Array.isArray(entries)) throw Error('Invalid native registration');
const readJournal = await nativeExport('agent-deletion-journal-','readAgentDeletionJournal');
const readRegistry = await nativeExport('registry-','readRegistry');
const registry = (await readRegistry()).entries;
if (!Array.isArray(registry)) throw Error('Invalid native sandbox registry');
const unregistered = [];
for (const id of ids) {
  if (Object.hasOwn(entries,id) || readJournal(id)) continue;
  const prefix = 'agent:'+id;
  if (registry.some(row => row.sessionKey === prefix || row.sessionKey?.startsWith(prefix+':'))) continue;
  try { await fs.lstat(path.join(root,'state/agents',id)); continue; }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  unregistered.push(id);
}
console.log(JSON.stringify({unregistered}));
await new Promise(resolve => process.stdout.write('',resolve));
process.exit(0);
