// SPDX-License-Identifier: Apache-2.0

import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

// The pinned runtime retains its task tables after retiring the task registry.
async function stateWriteTransaction(root) {
  const dist = path.join(root, 'package/node_modules/openclaw/dist');
  for (const name of fs.readdirSync(dist)) {
    if (!/^openclaw-state-db-[\w-]+\.mjs$/.test(name)) continue;
    const file = path.join(dist, name);
    const alias = fs.readFileSync(file, 'utf8').match(/\brunOpenClawStateWriteTransaction as (\w+)\b/)?.[1];
    if (alias) return (await import(pathToFileURL(file)))[alias];
  }
  throw Error('Pinned state transaction API unavailable');
}

export async function purgeRetiredTasks(agentId) {
  if(!/^bac-[a-f0-9]{24}(?:-r\d+)?$/.test(agentId))return;
  const root=path.dirname(process.env.OPENCLAW_STATE_DIR);
  const receiptPath=path.join(root,'deletion-receipts',agentId+'.json');
  let receipt;
  try {
    const info=fs.lstatSync(receiptPath);
    if(!info.isFile() || info.nlink!==1 || fs.realpathSync(receiptPath)!==receiptPath)throw Error('Redirected deletion receipt');
    receipt=JSON.parse(fs.readFileSync(receiptPath,'utf8'));
  } catch(error){if(error.code==='ENOENT')return;throw error;}
  if(receipt.agentId!==agentId || !/^[a-f0-9]{64}$/.test(receipt.token))throw Error('Invalid deletion receipt');
  const transact = await stateWriteTransaction(root);
  transact(({db}) => {
    const active = db.prepare(`SELECT 1 FROM task_runs WHERE agent_id = ?
      AND status NOT IN ('succeeded', 'failed', 'timed_out', 'cancelled', 'lost') LIMIT 1`).get(agentId);
    if (active) throw Error('Agent task retirement is not quiescent');
    db.prepare(`DELETE FROM task_delivery_state
      WHERE task_id IN (SELECT task_id FROM task_runs WHERE agent_id = ?)`).run(agentId);
    db.prepare('DELETE FROM task_runs WHERE agent_id = ?').run(agentId);
    if (db.prepare('SELECT 1 FROM task_runs WHERE agent_id = ? LIMIT 1').get(agentId))
      throw Error('Agent tasks remain');
  }, {}, {operationLabel: 'bac.retire-agent-tasks'});
}
