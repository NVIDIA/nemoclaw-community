// SPDX-License-Identifier: Apache-2.0

import fs from 'node:fs';
import path from 'node:path';
export function deletionHome(target) {
  const markerPath=path.join(target,'.bac-deletion-owner.json');
  let marker;
  try {
    const stat=fs.lstatSync(markerPath);
    if(!stat.isFile() || stat.nlink!==1)throw Error('Invalid deletion marker');
    marker=JSON.parse(fs.readFileSync(markerPath,'utf8'));
  } catch(error) {if(['ENOENT','ENOTDIR'].includes(error.code))return null;throw error;}
  if(!/^bac-[a-f0-9]{24}(?:-r\d+)?$/.test(marker.agentId)||!/^[a-f0-9]{64}$/.test(marker.token))throw Error('Invalid deletion owner');
  const root=fs.realpathSync(path.dirname(process.env.OPENCLAW_STATE_DIR));
  const receiptPath=path.join(root,'deletion-receipts',marker.agentId+'.json');
  if(fs.realpathSync(receiptPath)!==receiptPath)throw Error('Redirected deletion receipt');
  const receipt=JSON.parse(fs.readFileSync(receiptPath,'utf8'));
  if(receipt.agentId!==marker.agentId || receipt.token!==marker.token || !receipt.paths.includes(path.resolve(target)))throw Error('Unowned deletion path');
  const home=path.join(root,'deletion-staging');
  fs.mkdirSync(home,{recursive:true,mode:0o700});
  if(fs.realpathSync(home)!==home || !fs.lstatSync(home).isDirectory())throw Error('Redirected cleanup staging');
  return home;
}
export function recordDeletionDestination(target, destination) {
  const home=deletionHome(target);
  if(!home)return;
  const marker=JSON.parse(fs.readFileSync(path.join(target,'.bac-deletion-owner.json'),'utf8'));
  const receiptPath=path.join(path.dirname(home),'deletion-receipts',marker.agentId+'.json');
  const receipt=JSON.parse(fs.readFileSync(receiptPath,'utf8'));
  const container=path.dirname(destination);
  if(path.dirname(container)!==path.join(home,'.Trash') || fs.realpathSync(container)!==container)throw Error('Unowned Trash destination');
  const stat=fs.lstatSync(container);
  if(!stat.isDirectory())throw Error('Invalid Trash container');
  receipt.routed ||= [];receipt.trash ||= [];
  if(!receipt.routed.includes(path.resolve(target)))receipt.routed.push(path.resolve(target));
  const item={name:path.basename(container),dev:stat.dev,ino:stat.ino};
  if(!receipt.trash.some(r=>r.name===item.name))receipt.trash.push(item);
  // Persist exact ownership BEFORE native rename/copy. Partial native moves and
  // crashes remain recoverable without scanning anybody's Trash directory.
  const temporary=receiptPath+'.routing';
  const fd=fs.openSync(temporary,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_NOFOLLOW,0o600);
  try {
    const st=fs.fstatSync(fd);if(!st.isFile() || st.nlink!==1)throw Error('Redirected routing receipt');
    fs.ftruncateSync(fd,0);fs.writeFileSync(fd,JSON.stringify(receipt));fs.fsyncSync(fd);
  } finally {fs.closeSync(fd);}
  fs.renameSync(temporary,receiptPath);
}
