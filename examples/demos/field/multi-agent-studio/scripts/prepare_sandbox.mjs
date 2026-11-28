// SPDX-License-Identifier: Apache-2.0

// Pinned native lifecycle: prepare the same agent-scoped sandbox before any model turn.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [root,agentId]=process.argv.slice(2);
if(!/^bac-[a-f0-9]{24}(?:-r(?:0|[1-9][0-9]*))?$/.test(agentId||''))throw Error('Invalid Multi-Agent Studio agent');
const config=JSON.parse(await fs.readFile(process.env.OPENCLAW_CONFIG_PATH,'utf8'));
const agent=config.agents?.entries?.[agentId];
if(agent?.sandbox?.backend!=='openshell'||agent.sandbox.mode!=='all')throw Error('Protected agent required');
const pkg=path.join(root,'package/node_modules/openclaw');
if(JSON.parse(await fs.readFile(path.join(pkg,'package.json'),'utf8')).version!=='2026.11.3')throw Error('Unsupported native runtime version');
let pluginPath=config.plugins?.installs?.openshell?.installPath;
if(!pluginPath){
 const matches=[];
 for(const candidate of config.plugins?.load?.paths||[]){
  try{
   const manifest=JSON.parse(await fs.readFile(path.join(candidate,'package.json'),'utf8'));
   if(manifest.name==='@openclaw/openshell-sandbox'&&manifest.version==='2026.11.3')matches.push(candidate);
  }catch{}
 }
 if(matches.length>1)throw Error('Exactly one pinned OpenShell plugin is required');
 pluginPath=matches[0];
}
if(!pluginPath){
 const projects=path.join(root,'state/npm/projects');
 const matches=[];
 for(const dir of await fs.readdir(projects)){
  const candidate=path.join(projects,dir,'node_modules/@openclaw/openshell-sandbox');
  try{if(JSON.parse(await fs.readFile(path.join(candidate,'package.json'),'utf8')).version==='2026.11.3')matches.push(candidate);}catch{}
 }
 if(matches.length!==1)throw Error('Exactly one pinned OpenShell plugin is required');
 pluginPath=matches[0];
}
const plugin=(await import(pathToFileURL(path.join(pluginPath,'dist/index.js')))).default;
plugin.register({registrationMode:'full',pluginConfig:config.plugins.entries.openshell.config,lifecycle:{registerRuntimeLifecycle(){}}});
const dist=path.join(pkg,'dist');let resolve;
for(const name of await fs.readdir(dist)){
 if(!/^context-.*\.mjs$/.test(name))continue;
 const text=await fs.readFile(path.join(dist,name),'utf8');
 const alias=text.match(/resolveSandboxContext as (\w+)/)?.[1];
 if(alias){resolve=(await import(pathToFileURL(path.join(dist,name))))[alias];break;}
}
if(!resolve)throw Error('Native sandbox lifecycle is unavailable');
const result=await resolve({config,sessionKey:'agent:'+agentId+':main',workspaceDir:agent.workspace});
if(result?.backendId!=='openshell')throw Error('OpenShell sandbox was not prepared');
console.log(JSON.stringify({backend:result.backendId,runtimeId:result.runtimeId}));process.exit(0);
