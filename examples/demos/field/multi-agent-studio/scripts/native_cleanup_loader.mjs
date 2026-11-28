// SPDX-License-Identifier: Apache-2.0

// Scoped adapter for pinned OpenClaw 2026.11.3. Keep native path guards, lifecycle
// fencing and Trash rename semantics; redirect only receipt-marked BaC deletes.
// A load hook keeps the runtime image immutable and the integration app-owned.
import {registerHooks} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const state=process.env.OPENCLAW_STATE_DIR;
if(state) {
  const root=path.dirname(state);
  const target=path.join(root,'package/node_modules/@openclaw/fs-safe/dist/trash.js');
  if(fs.existsSync(target)) {
    const version=JSON.parse(fs.readFileSync(path.join(root,'package/node_modules/openclaw/package.json'),'utf8')).version;
    if(version!=='2026.11.3')throw Error('Unsupported native cleanup runtime');
    const real=fs.realpathSync(target);
    const helper=new URL('./native_cleanup_trash.mjs',import.meta.url).href;
    const tasksHelper=new URL('./native_cleanup_tasks.mjs',import.meta.url).href;
    const nativeDist=fs.realpathSync(path.join(root,'package/node_modules/openclaw/dist'));
    registerHooks({load(url,context,nextLoad) {
      const loaded=nextLoad(url,context);
      if(url.startsWith('file:') && path.dirname(fileURLToPath(url))===nativeDist && /^cleanup-service-.*\.mjs$/.test(path.basename(fileURLToPath(url)))) {
        let source=Buffer.isBuffer(loaded.source)?loaded.source.toString():String(loaded.source);
        const signature='async function purgeAgentSessionStoreEntries(cfg, agentId, options = {}) {';
        if(!source.includes('async function purgeAgentSessionStoreEntries'))return loaded;
        if(source.split(signature).length!==2)throw Error('Unsupported native session cleanup implementation');
        source=source.replace(signature,'async function nativePurgeAgentSessionStoreEntries(cfg, agentId, options = {}) {');
        source+=`\nasync function purgeAgentSessionStoreEntries(cfg, agentId, options = {}) {
          if(await nativePurgeAgentSessionStoreEntries(cfg, agentId, options))return true;
          try { await purgeRetiredTasks(agentId); return false; }
          catch { return true; }
        }\n`;
        return {...loaded,source:`import {purgeRetiredTasks} from ${JSON.stringify(tasksHelper)};\n`+source};
      }
      if(!url.startsWith('file:') || fileURLToPath(url)!==real)return loaded;
      const replacements=[['function resolveTrashDir() {','function resolveTrashDir(targetPath) {'],
        ['const homeDir = os.homedir();','const homeDir = deletionHome(targetPath) || os.homedir();'],
        ['const trashDir = resolveTrashDir();','const trashDir = resolveTrashDir(targetPath);'],
        ['if (movePathToDestination(target, dest)) {','recordDeletionDestination(target.path, dest);\n        if (movePathToDestination(target, dest)) {']];
      let source=Buffer.isBuffer(loaded.source)?loaded.source.toString():String(loaded.source);
      for(const [before,after] of replacements) {
        if(source.split(before).length!==2)throw Error('Unsupported native Trash implementation');
        source=source.replace(before,after);
      }
      if(process.argv.includes('gateway') && process.argv.includes('run')) {
        const integration=createHash('sha256').update(fs.readFileSync(fileURLToPath(import.meta.url))).update(fs.readFileSync(fileURLToPath(helper))).update(fs.readFileSync(fileURLToPath(tasksHelper))).digest('hex');
        const destination=path.join(fs.realpathSync(root),'cleanup-capability.json');
        const temporary=destination+'.'+process.pid;
        const fd=fs.openSync(temporary,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_NOFOLLOW,0o600);
        try {
          const stat=fs.fstatSync(fd);if(!stat.isFile()||stat.nlink!==1)throw Error('Redirected cleanup capability');
          fs.ftruncateSync(fd,0);fs.writeFileSync(fd,JSON.stringify({version:1,pid:process.pid,integration}));fs.fsyncSync(fd);
        }
        finally {fs.closeSync(fd);}
        fs.renameSync(temporary,destination);
      }
      return {...loaded,source:`import {deletionHome, recordDeletionDestination} from ${JSON.stringify(helper)};\n`+source};
    }});
  }
}
