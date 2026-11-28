// SPDX-License-Identifier: Apache-2.0

// Read-only inspection of saved JSON artifacts. No derived or regenerated data.
function jsonFieldLabel(key){return String(key).replace(/([a-z0-9])([A-Z])/g,'$1 $2').replace(/[_-]/g,' ').replace(/^./,letter=>letter.toUpperCase());}
function jsonValueNode(value){
 const node=document.createElement('span');node.className='result-json-value';
 node.textContent=value===null?'null':typeof value==='string'?value:JSON.stringify(value);
 if(typeof value==='string'&&/^https?:\/\//i.test(value)){
  try{const url=new URL(value);const link=document.createElement('a');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent=value;return link;}catch{}
 }
 if(value===null||typeof value==='boolean'||typeof value==='number')node.dataset.type=typeof value;
 return node;
}
function renderJsonEntries(value,container,depth=0){
 if(!value||typeof value!=='object'){container.append(jsonValueNode(value));return;}
 const entries=Object.entries(value),array=Array.isArray(value);
 if(!entries.length){const empty=document.createElement('span');empty.className='result-json-empty';empty.textContent=array?'[]':'{}';container.append(empty);return;}
 for(const [key,item] of entries){
  const title=array?String(Number(key)+1):jsonFieldLabel(key);
  if(item&&typeof item==='object'){
   const branch=document.createElement('details');branch.className='result-json-branch';branch.open=depth===0;
   const summary=document.createElement('summary'),label=document.createElement('span'),count=document.createElement('small');
   const descriptor=array&&['title','name','theme','id','topic','booth'].map(k=>item[k]).find(v=>typeof v==='string'&&v.trim());
   label.textContent=title+(descriptor?' · '+descriptor:'');
   const length=Object.keys(item).length;count.textContent=length+' '+(Array.isArray(item)?'item':'field')+(length===1?'':'s');summary.append(label,count);branch.append(summary);
   const children=document.createElement('div');children.className='result-json-children';branch.append(children);let rendered=false;
   const populate=()=>{if(branch.open&&!rendered){rendered=true;renderJsonEntries(item,children,depth+1);}};
   branch.addEventListener('toggle',populate);populate();container.append(branch);
  }else{
   const row=document.createElement('dl'),term=document.createElement('dt'),definition=document.createElement('dd');row.className='result-json-row';term.textContent=title;definition.append(jsonValueNode(item));row.append(term,definition);container.append(row);
  }
 }
}
async function openResultJson(path,title,jobId){
 const owner=agentId;
 dialog(title,'<section id="studio-json-viewer"><p role="status">Loading file</p></section>');
 const viewer=el('json-viewer'),current=()=>el('dialog').open&&el('json-viewer')===viewer&&agentId===owner;
 try{
  const file=await api('file?path='+encodeURIComponent(path)+(jobId?'&job='+encodeURIComponent(jobId):''),undefined,owner);if(!current())return;
  if(file.encoding==='base64'||typeof file.content!=='string')throw new Error('This file is not readable JSON.');
  let value;try{value=JSON.parse(file.content);}catch{throw new Error('This saved file contains invalid JSON.');}
  const formatted=JSON.stringify(value,null,2);
  viewer.innerHTML='<div class="result-json-toolbar"><div role="tablist" aria-label="File view"><button type="button" role="tab" id="studio-json-browse-tab" aria-controls="studio-json-browse" aria-selected="true" data-json-view="browse">Browse</button><button type="button" role="tab" id="studio-json-raw-tab" aria-controls="studio-json-raw" aria-selected="false" tabindex="-1" data-json-view="raw">JSON</button></div><button type="button" class="studio-secondary" id="studio-json-copy">Copy JSON</button><span id="studio-json-copy-status" class="sr-only" role="status"></span></div><div class="result-json-scroll"><div id="studio-json-browse" role="tabpanel" aria-labelledby="studio-json-browse-tab" tabindex="0"></div><pre id="studio-json-raw" role="tabpanel" aria-labelledby="studio-json-raw-tab" tabindex="0" hidden></pre></div>';
  renderJsonEntries(value,el('json-browse'));el('json-raw').textContent=formatted;
  const tabs=[...viewer.querySelectorAll('[data-json-view]')];
  const select=next=>{tabs.forEach(tab=>{const active=tab.dataset.jsonView===next;tab.setAttribute('aria-selected',active);tab.tabIndex=active?0:-1;});el('json-browse').hidden=next!=='browse';el('json-raw').hidden=next!=='raw';viewer.querySelector('.result-json-scroll').scrollTop=0;};
  tabs.forEach((tab,i)=>{tab.onclick=()=>select(tab.dataset.jsonView);tab.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?tabs[0]:event.key==='End'?tabs[1]:tabs[1-i];select(next.dataset.jsonView);next.focus();};});
  const copy=el('json-copy');copy.onclick=async()=>{try{await copyText(formatted);if(current()){copy.textContent='Copied';el('json-copy-status').textContent='JSON copied';setTimeout(()=>{if(current())copy.textContent='Copy JSON';},1800);}}catch{if(current()){select('raw');el('json-copy-status').textContent='Select the JSON text to copy it.';copy.textContent='Select JSON to copy';}}};
 }catch(error){if(current()){viewer.replaceChildren();const message=document.createElement('p');message.setAttribute('role','alert');message.textContent=error.message;const retry=document.createElement('button');retry.className='studio-secondary';retry.textContent='Retry';retry.onclick=()=>openResultJson(path,title,jobId);viewer.append(message,retry);}}
}
