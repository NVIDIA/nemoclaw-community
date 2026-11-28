// SPDX-License-Identifier: Apache-2.0

// Register through the live gateway without booting the full CLI twice per agent.
// Configuration (which can contain credentials) travels through stdin, never argv.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
async function main() {
  const pkg=path.join(process.argv[2],'package/node_modules/openclaw');
  if(JSON.parse(await fs.readFile(path.join(pkg,'package.json'),'utf8')).version!=='2026.11.3')throw Error('Unsupported runtime');
  let input='';for await(const chunk of process.stdin)input+=chunk;
  const {patch,replacePaths}=JSON.parse(input);
  if(!patch||typeof patch!=='object'||Array.isArray(patch)||!Array.isArray(replacePaths)||!replacePaths.every(p=>typeof p==='string'))throw Error('Invalid patch');
  const dist=path.join(pkg,'dist'),files=await fs.readdir(dist);
  async function nativeExport(prefix,symbol) {
    for(const name of files.filter(n=>n.startsWith(prefix)&&n.endsWith('.mjs'))) {
      const file=path.join(dist,name),source=await fs.readFile(file,'utf8');
      const alias=source.match(new RegExp('\\b'+symbol+' as (\\w+)\\b'))?.[1];
      if(alias)return (await import(pathToFileURL(file)))[alias];
    }
    throw Error('Pinned native API unavailable');
  }
  const callGateway=await nativeExport('call-','callGateway');
  const transportError=await nativeExport('transport-error-','isGatewayTransportError');
  const deadline=Date.now()+60000;
  let snapshot;
  while(true) {
    try {
      snapshot=await callGateway({method:'config.get',params:{},mode:'cli',clientName:'cli',requiredMethods:['config.get'],timeoutMs:Math.max(1,deadline-Date.now())});
      break;
    } catch(error) {
      if(!transportError(error)||Date.now()>=deadline)throw error;
      await new Promise(resolve=>setTimeout(resolve,Math.min(500,deadline-Date.now())));
    }
  }
  if(typeof snapshot?.hash!=='string'||!snapshot.hash)throw Error('Missing revision');
  // A lost response can mean the write succeeded. Never replay an uncertain write.
  const applied=await callGateway({method:'config.patch',params:{raw:JSON.stringify(patch),baseHash:snapshot.hash,replacePaths,note:'Multi-Agent Studio agent registration'},
    mode:'cli',clientName:'cli',requiredMethods:['config.patch'],timeoutMs:60000});
  if(applied?.ok!==true)throw Error('Unconfirmed patch');
  process.stdout.write(JSON.stringify({ok:true}));
}
main().catch(()=>{process.stderr.write('Native configuration update was not confirmed.\n');process.exitCode=1;});
