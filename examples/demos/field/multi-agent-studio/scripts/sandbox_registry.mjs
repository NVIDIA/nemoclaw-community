// SPDX-License-Identifier: Apache-2.0

// Read agent-scoped native registry entries without probing any sandbox.
// Retire only entries the caller has verified absent in OpenShell.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [root,agentId,namesJson]=process.argv.slice(2),lookup=agentId==='--owner',names=lookup||namesJson===undefined?null:JSON.parse(namesJson);
if(lookup ? !/^oc-[a-z0-9-]+$/.test(namesJson||'') : !/^bac-[a-f0-9]{24}(?:-r[0-9]+)?$/.test(agentId)||(names!==null&&(!Array.isArray(names)||names.some(n=>!/^oc-[a-z0-9-]+$/.test(n)))))throw Error('Invalid cleanup identity');
const pkg=path.join(root,'package/node_modules/openclaw');
if(JSON.parse(await fs.readFile(path.join(pkg,'package.json'),'utf8')).version!=='2026.11.3')throw Error('Unsupported native runtime version');
for(const name of await fs.readdir(path.join(pkg,'dist'))){
 if(!/^registry-.*\.mjs$/.test(name))continue;
 const file=path.join(pkg,'dist',name),source=await fs.readFile(file,'utf8');
 const read=source.match(/readRegistry as (\w+)/)?.[1],remove=source.match(/removeRegistryEntry as (\w+)/)?.[1];
 if(!read||!remove)continue;
 const api=await import(pathToFileURL(file));
 if(lookup){
  const rows=(await api[read]()).entries.filter(row=>row.containerName===namesJson);
  const owners=new Set(rows.map(row=>row.backendId==='openshell'&&row.sessionKey?.match(/^agent:(bac-[a-f0-9]{24}(?:-r[0-9]+)?)(?::|$)/)?.[1]));
  if(owners.size!==1||owners.has(false)||owners.has(undefined))throw Error('Sandbox has no unique Multi-Agent Studio owner');
  console.log(JSON.stringify({agentId:[...owners][0]}));process.exit(0);
 }
 const prefix='agent:'+agentId;
 if(names===null){
  const containers=(await api[read]()).entries.filter(row=>row.backendId==='openshell'&&(row.sessionKey===prefix||row.sessionKey.startsWith(prefix+':')));
  console.log(JSON.stringify({containers}));process.exit(0);
 }
 for(const containerName of names){
  const row=(await api[read]()).entries.find(r=>r.containerName===containerName);
  if(!row)continue;
  if(row.backendId!=='openshell'||!(row.sessionKey===prefix||row.sessionKey.startsWith(prefix+':')))throw Error('Registry ownership mismatch');
  await api[remove](containerName);
 }
 console.log('Missing sandbox records retired');process.exit(0);
}
throw Error('Pinned registry API unavailable');
