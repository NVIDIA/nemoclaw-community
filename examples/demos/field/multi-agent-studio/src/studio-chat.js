// SPDX-License-Identifier: Apache-2.0

// Documents persist with the selected agent, independently of message drafts.
let documentUploadTarget=null,documentUploadName='';
async function documentText(file){
 const bytes=await file.arrayBuffer();
 try{return new TextDecoder('utf-8',{fatal:true}).decode(bytes);}
 catch{throw new Error('This text file is not valid UTF-8. Save it as UTF-8 and upload it again.');}
}
function renderDocuments(){
 const panel=el('documents'),paths=new Set((data.files||[]).map(file=>file.path));
 const documents=(data.files||[]).filter(file=>file.kind==='inbox'&&/\.(pdf|pptx|xlsx|txt|md|csv)$/i.test(file.path)&&!(/\.(pdf|pptx|xlsx)\.txt$/i.test(file.path)&&paths.has(file.path.slice(0,-4))));
 const busy=documentUploadTarget===agentId;
 panel.hidden=!documents.length&&!busy;
 panel.innerHTML='<small>Documents · '+escape(data.profile?.name||'')+'</small><ul>'+documents.map(file=>'<li title="'+escape(file.path.slice(6))+'"><span aria-hidden="true">▤</span><span>'+escape(file.path.slice(6))+'</span><small>'+escape(file.size<1024*1024?Math.max(1,Math.ceil(file.size/1024))+' KB':(file.size/1024/1024).toFixed(1)+' MB')+'</small></li>').join('')+'</ul>'+(busy?'<p role="status">Adding '+escape(documentUploadName)+'…</p>':'');
}
async function uploadDocuments(files){
 if(!files.length||documentUploadTarget!==null||radarChatDisabled())return;
 if(!data.profile||data.deleting){alert('Choose an available agent before adding documents.');return;}
 const target=agentId,revision=dialogRevision,errors=[];documentUploadTarget=target;pendingWrites++;renderDocuments();syncComposer();
 try{
  for(const file of files){
   const binary=/\.(pdf|pptx|xlsx)$/i.test(file.name),limit=10*1024*1024;
   if(!/\.(pdf|pptx|xlsx|txt|md|csv)$/i.test(file.name)){errors.push(file.name+': Use PDF, PPTX, XLSX, TXT, Markdown or CSV.');continue;}
   if(file.size>limit){errors.push(file.name+': Choose a file of 10 MB or smaller.');continue;}
   documentUploadName=file.name;renderDocuments();
   try{
    let content;
    if(binary){const bytes=new Uint8Array(await file.arrayBuffer());let raw='';for(let i=0;i<bytes.length;i+=8192)raw+=String.fromCharCode(...bytes.subarray(i,i+8192));content=btoa(raw);}
    else content=await documentText(file);
    await api('upload',{name:file.name,content,...(binary?{encoding:'base64'}:{})},target);
    await refresh();
   }catch(error){errors.push(file.name+': '+error.message);}
  }
 }finally{pendingWrites--;documentUploadTarget=null;documentUploadName='';renderDocuments();syncComposer();}
 if(errors.length){
  if(agentId===target&&dialogRevision===revision)dialog('Document upload','<p>'+errors.map(escape).join('<br>')+'</p>');
  else alert(errors.join('\n'),'error');
 }
}
// Keep cancellation pending independently of DOM nodes replaced by polling.
const pendingChatStops=new Set();
function chatStopButton(id,crew=false,stopping=false,label='Stop'){
 const pending=stopping||pendingChatStops.has(agentId+':'+id);
 return '<button type="button" '+(crew?'data-crew-chat-stop':'data-chat-stop')+'="'+escape(id)+'" '+(pending?'disabled':'')+'>'+(pending?'Stopping…':label)+'</button>';
}
async function stopChat(id,crew=false){
 const owner=agentId,role=selectedCrewRole,key=owner+':'+id;
 if(pendingChatStops.has(key))return;
 if(crew)el('crew-chat-error').hidden=true;
 pendingChatStops.add(key);render();
 try{await api('decision',{id,action:'cancel'},owner);await refresh();}
 catch(error){
  if(crew&&agentId===owner&&selectedCrewRole===role){el('crew-chat-error').textContent=error.message;el('crew-chat-error').hidden=false;}
  else alert(error.message,'error');
 }finally{pendingChatStops.delete(key);render();}
}
const documentDropZone=el('companion');
for(const eventName of ['dragenter','dragover'])documentDropZone.addEventListener(eventName,event=>{
 if(![...event.dataTransfer.types].includes('Files'))return;
 event.preventDefault();event.dataTransfer.dropEffect=radarChatDisabled()||data.deleting||documentUploadTarget!==null?'none':'copy';
 documentDropZone.classList.toggle('document-drag-over',!radarChatDisabled()&&!data.deleting&&documentUploadTarget===null);
});
documentDropZone.addEventListener('dragleave',event=>{if(!documentDropZone.contains(event.relatedTarget))documentDropZone.classList.remove('document-drag-over');});
documentDropZone.addEventListener('drop',event=>{
 if(![...event.dataTransfer.types].includes('Files'))return;
 event.preventDefault();documentDropZone.classList.remove('document-drag-over');
 if(radarChatDisabled()||data.deleting)return;
 const files=[...event.dataTransfer.files],images=files.filter(file=>file.type.startsWith('image/'));
 if(images.length)addChatImages(images);
 uploadDocuments(files.filter(file=>!file.type.startsWith('image/')));
});
const chatImageDrafts=new Map();
const personalDrafts=new Map();
function restorePersonalDraft(next,agents){
 const live=new Set(agents.map(agent=>agent.key));
 if(live.has(agentId))personalDrafts.set(agentId,el('prompt').value);
 for(const owner of personalDrafts.keys())if(!live.has(owner))personalDrafts.delete(owner);
 el('prompt').value=personalDrafts.get(next)||'';
}
const imageKey=crew=>agentId+(crew?':crew:'+selectedScenario+':'+selectedCrewRole:':personal');
function pendingImages(crew=false){return chatImageDrafts.get(imageKey(crew))||[];}
// Acknowledgement clears only the submitted draft, not later typing or attachments.
function captureChatDraft(crew=false){return {crew,crewRole:selectedCrewRole,key:imageKey(crew),roleKey:crewDraftKey(selectedCrewRole),prompt:el((crew?'crew-':'')+'prompt').value,images:pendingImages(crew).slice()};}
function acknowledgeChatDraft(draft){
 const current=imageKey(draft.crew)===draft.key;
 if(current){const input=el((draft.crew?'crew-':'')+'prompt');if(input.value===draft.prompt)input.value=draft.crew?defaultCrewPrompt(draft.crewRole):'';if(draft.crew)crewDrafts.set(draft.roleKey,input.value);}
 else if(draft.crew&&crewDrafts.get(draft.roleKey)===draft.prompt)crewDrafts.set(draft.roleKey,defaultCrewPrompt(draft.crewRole));
 const remaining=(chatImageDrafts.get(draft.key)||[]).filter(image=>!draft.images.includes(image));
 if(remaining.length)chatImageDrafts.set(draft.key,remaining);else chatImageDrafts.delete(draft.key);
 if(current){renderImageDrafts(draft.crew);if(draft.crew)syncCrewComposer();}
}
function renderImageDrafts(crew=false){
 const id=crew?'crew-':'',node=el(id+'image-drafts');if(!node)return;
 node.replaceChildren();
 pendingImages(crew).forEach((item,index)=>{const card=document.createElement('span'),image=document.createElement('img'),remove=document.createElement('button');image.src=item.dataUrl;image.alt=item.name;remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Remove '+item.name);remove.onclick=()=>{const items=pendingImages(crew).slice();items.splice(index,1);chatImageDrafts.set(imageKey(crew),items);renderImageDrafts(crew)};card.append(image,remove);node.append(card)});
 node.hidden=!pendingImages(crew).length;
 el(id+'prompt').required=!pendingImages(crew).length;
}
async function addChatImages(files,crew=false){
 const key=imageKey(crew),input=el((crew?'crew-':'')+'prompt');if(input.disabled)return;
 for(const file of files){
  if((chatImageDrafts.get(key)||[]).length>=4){alert('Attach up to four images per message.');break;}
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)){alert('Use PNG, JPEG or WebP images.');continue;}
  if(file.size>20*1024*1024){alert('Choose an image smaller than 20 MB.');continue;}
  try{const bitmap=await createImageBitmap(file),scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height)),canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();const dataUrl=canvas.toDataURL('image/jpeg',.88);if(dataUrl.length>2800000)throw new Error('Image is too large after resizing. Try a smaller image.');const items=chatImageDrafts.get(key)||[];if(items.length<4)chatImageDrafts.set(key,[...items,{name:file.name||'Pasted image',dataUrl}]);if(imageKey(crew)===key)renderImageDrafts(crew);}catch(error){alert(error.message||'This image could not be read.');}
 }
}
function imageHistoryMarkup(images,jobId){return (images||[]).map(image=>'<img class="chat-image" data-chat-image="'+escape(image.path)+'" data-image-job="'+escape(jobId||'')+'" alt="Attached image">').join('');}
function loadChatImages(container,owner){
 container.querySelectorAll('[data-chat-image]').forEach(async image=>{try{const file=await api('file?path='+encodeURIComponent(image.dataset.chatImage)+(image.dataset.imageJob?'&job='+encodeURIComponent(image.dataset.imageJob):''),undefined,owner);if(image.isConnected&&file.encoding==='base64'&&['image/png','image/jpeg','image/webp'].includes(file.mime))image.src='data:'+file.mime+';base64,'+file.content;}catch{image.alt='Image unavailable';}});
}
for(const crew of [false,true]){
 const id=crew?'crew-':'',form=el(id+'chat'),input=el(id+'prompt'),previews=document.createElement('div');
 previews.id='studio-'+id+'image-drafts';previews.className='chat-image-drafts';previews.hidden=true;form.insertBefore(previews,input);
 input.addEventListener('paste',event=>{const images=[...event.clipboardData.items].filter(item=>item.kind==='file'&&item.type.startsWith('image/')).map(item=>item.getAsFile()).filter(Boolean);if(images.length){event.preventDefault();addChatImages(images,crew)}});
}
let chatSending=false;
const isPlanCommand=value=>/^\s*\/(?:goals?|plans?)(?:\s|$)/i.test(value);
const planLocationHint='Use /goal with Casey in Open Task. Lounge agents and other teammates accept direct messages only.';
function clearPlanLocationHint(crew=false){
 const prefix=crew?'crew-':'',notice=el(prefix+'chat-error');
 if(!isPlanCommand(el(prefix+'prompt').value)&&notice.textContent===planLocationHint)notice.hidden=true;
}
function rejectLoungePlan(){
 if(!isPlanCommand(el('prompt').value))return false;
 el('chat-error').textContent=planLocationHint;el('chat-error').hidden=false;return true;
}
function radarChatDisabled(profile=data.profile){return profile?.skills?.includes('radar')||false;}
function syncComposer(){
  if(!connected)return;
  const radar=radarChatDisabled(),unavailable=!personalReady(data.profile),blocked=radar||unavailable||!!data.deleting;
  el('chat').classList.toggle('is-heartbeat-only',radar);
  el('prompt').disabled=blocked;
  el('send').disabled=blocked||chatSending||comparisonSending||documentUploadTarget===agentId;
  el('send-all').disabled=blocked||chatSending||comparisonSending||documentUploadTarget===agentId||(data.agents||[]).filter(agent=>!radarChatDisabled(agent)).length<2;
  el('run-options').disabled=el('send-all').disabled;
  if(el('run-options').disabled)setRunOptions(false);
  el('attach').disabled=radar||!!data.deleting||!data.profile||documentUploadTarget!==null;
  el('schedule').disabled=radar||!!data.deleting;
  el('chat-connection').hidden=!blocked;
  el('chat-connection-text').textContent=data.deleting?'This agent is paused for deletion.':radar?'Tech Radar uses Heartbeat. Manual chat is disabled.':!runtime.gateway?(gatewayState()==='slow'?'Waiting for the agent runtime to respond. Checking automatically.':'Agent runtime unavailable. Retry the connection to continue.'):personalModelNotice(data.profile);
  el('chat-connect').hidden=radar||!unavailable||(runtime.gateway&&settingsButton.hidden);
  el('chat-connect').textContent=!runtime.gateway?'Retry connection':'Connect model';
  el('chat-connect').disabled=runtimeRetrying;
  el('prompt').placeholder=data.deleting?'This agent is paused for deletion…':radar?'':!runtime.gateway?'Waiting for the agent runtime…':!personalModel(data.profile).connected?'Connect a model to message your agent…':'Message your agent…';
  el('equipped').querySelectorAll('button').forEach(button=>button.disabled=blocked);
}
el('chat-connect').onclick=connectionAction;
// Model text is escaped before formatting; raw HTML is never inserted into the app.
function messageMarkup(value){
  const saved=[];
  const token=html=>'\u0000'+(saved.push(html)-1)+'\u0000';
  function inline(text){
    return escape(text).replace(/`([^`]+)`/g,(_,s)=>token('<code>'+s+'</code>'))
      .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,(_,label,url)=>token('<a href="'+url+'" target="_blank" rel="noopener noreferrer">'+label+'</a>'))
      .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>').replace(/\*([^*\n]+)\*/g,'<em>$1</em>');
  }
  const lines=String(value||'').replace(/\u0000/g,'').split('\n'),out=[];let i=0;
  while(i<lines.length){
    const line=lines[i];
    if(/^```/.test(line)){const code=[];i++;while(i<lines.length&&!/^```/.test(lines[i]))code.push(lines[i++]);i++;out.push('<pre><code>'+escape(code.join('\n'))+'</code></pre>');continue;}
    if(!line.trim()){i++;continue;}
    if(i+1<lines.length&&line.includes('|')&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){
      const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|').map(v=>inline(v.trim()));
      out.push('<div class="chat-table"><table><thead><tr>'+cells(line).map(c=>'<th>'+c+'</th>').join('')+'</tr></thead><tbody>');i+=2;
      while(i<lines.length&&lines[i].includes('|'))out.push('<tr>'+cells(lines[i++]).map(c=>'<td>'+c+'</td>').join('')+'</tr>');out.push('</tbody></table></div>');continue;
    }
    if(/^\s*(?:[-*+] |\d+\. )/.test(line)){
      const ordered=/^\s*\d+\./.test(line),tag=ordered?'ol':'ul';
      const item=ordered?/^\s*\d+\. /:/^\s*[-*+] /;
      const start=ordered?Number(line.match(/^\s*(\d+)\./)[1]):1;
      out.push('<'+tag+(ordered&&start!==1?' start="'+start+'"':'')+'>');
      while(i<lines.length&&item.test(lines[i])){
        out.push('<li>'+inline(lines[i++].replace(item,''))+'</li>');
        // Blank lines separate loose list items, not independent lists.
        let next=i;while(next<lines.length&&!lines[next].trim())next++;
        if(next>i&&next<lines.length&&item.test(lines[next]))i=next;
      }
      out.push('</'+tag+'>');continue;
    }
    if(/^#{1,6} /.test(line))out.push('<h4>'+inline(line.replace(/^#{1,6} /,''))+'</h4>');
    else if(/^> /.test(line))out.push('<blockquote>'+inline(line.slice(2))+'</blockquote>');
    else out.push('<p>'+inline(line)+'</p>');i++;
  }
  return out.join('').replace(/\u0000(\d+)\u0000/g,(_,n)=>saved[Number(n)]||'');
}
function shieldReplyHeld(job,role=null){
  const hold=window.BacCampus?.protectionReplyDelay(agentId,role);
  if(!hold)return false;
  // Do not hide earlier replies when a later request hits the shield.
  const lastEvent=job.events?.at(-1)?.time||job.created;
  return job.kind==='roundtable'?job.created>=hold.time-1:
    job.created<=hold.time+1&&(lastEvent>=hold.time-1||['queued','running','waiting','stopping'].includes(job.status));
}
const shieldReplyWait='<div class="chat-progress shield-reply-wait" role="status" aria-label="Access blocked. Reply will appear shortly.">···</div>';
root.addEventListener('bac:protection-reveal',()=>{if(connected)render();});
let conversationSignature='',conversationOwner=null;
function renderConversation(){
  renderImageDrafts();renderDocuments();syncComposer();const log=el('conversation');if(!log)return;
  const jobs=[...data.jobs.filter(j=>j.kind!=='crew'),...(data.crewChats||[]).filter(j=>j.payload.collaboration?.origin?.owner===agentId&&j.payload.collaboration.origin.role===null),...(data.roundtableTurns||[])].sort((a,b)=>a.created-b.created);
  const signature=JSON.stringify([agentId,data.profile?.name,[...pendingChatStops],jobs.map(j=>[j.id,j.status,j.result,j.events?.at(-1),shieldReplyHeld(j)])]);
  if(conversationOwner!==agentId)el('chat-error').hidden=true;
  if(signature===conversationSignature)return;
  const follow=conversationOwner!==agentId||log.scrollHeight-log.scrollTop-log.clientHeight<70,top=log.scrollTop;
  conversationSignature=signature;conversationOwner=agentId;
  log.innerHTML=(data.jobs.length>=30?'<small class="chat-history-note">Recent conversations · up to 30 missions</small>':'')+(jobs.length?jobs.map(j=>{
    if(j.payload.collaboration)return collaborationHistoryMarkup(j);
    const held=shieldReplyHeld(j),result=held?{}:j.result||{},pending=['queued','running','waiting','stopping'].includes(j.status);
    const status={queued:'Waiting to start…',running:j.events?.at(-1)?.title==='Preparing OpenShell'?'Preparing your protected runtime…':'Working on your request…',waiting:'Waiting for a decision.',stopping:'Stopping after the current model call…',cancelled:'Stopped.'}[j.status];
    return '<article class="chat-turn" data-chat-turn="'+escape(j.id)+'">'+(j.kind==='heartbeat'?'':'<div class="chat-message chat-user"><small>'+escape(j.payload.sender||'You')+'</small><div>'+escape(j.payload.prompt||'').replace(/\n/g,'<br>')+imageHistoryMarkup(j.payload.images,j.id)+'</div></div>')+'<div class="chat-message chat-agent"><small>'+escape(j.result?.systemNotice?'System':data.profile?.name||'Agent')+(j.kind==='heartbeat'?' · Heartbeat':'')+' · '+escape(new Date(j.created*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}))+'</small>'+modelUsageMarkup(j)+customSkillMarkup(result.activity)+(held?shieldReplyWait:'<div class="chat-prose">'+messageMarkup(result.answer||result.error||(pending?'':status||'No text reply was returned.'))+'</div>')+(!held&&pending?'<div class="chat-progress" role="status">'+escape(status)+(j.status!=='stopping'?chatStopButton(j.id):'')+'</div>':'')+(!held&&result.source?'<small class="heartbeat-source">'+'Technical discovery · '+'Published '+escape(result.source.published)+' · Feed excerpt<br><a href="'+escape(result.source.url)+'" target="_blank" rel="noopener noreferrer">'+escape(result.source.title)+'</a></small>':'')+webpageButtons(result.files,j.id)+(result.files||[]).filter(f=>!/\.html$/i.test(f)&&(f!=='artifacts/reply-'+j.id.slice(0,6)+'.md'||!result.answer)).map(f=>'<details class="chat-file"><summary data-chat-file="'+escape(f)+'">'+escape(f.split('/').pop())+'</summary><div class="chat-file-body"></div></details>').join('')+'</div></article>';
  }).join(''):'<p class="chat-empty">No messages yet.</p>');
  loadChatImages(log,agentId);
  if(follow)log.scrollTop=log.scrollHeight;else log.scrollTop=top;
}
el('conversation').addEventListener('click',async event=>{
  if(event.target.closest('[data-open-collaboration]')){showCollaboration();return;}
  const stop=event.target.closest('[data-chat-stop]');
  if(stop){if(!stop.disabled)await stopChat(stop.dataset.chatStop);return;}
  const item=event.target.closest('[data-chat-file]');if(!item||item.dataset.loaded)return;
  const owner=agentId,body=item.nextElementSibling;item.dataset.loaded='true';body.textContent='Loading…';
  try{
    const path=item.dataset.chatFile,file=await api('file?path='+encodeURIComponent(path));if(owner!==agentId||!item.isConnected)return;
    body.replaceChildren();
    if(file.encoding!=='base64'){
      if(/\.html?$/i.test(path)){
        const frame=document.createElement('iframe');frame.title='Generated page preview';frame.setAttribute('sandbox','');
        frame.srcdoc=protectedPageHtml(file.content,'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:; form-action \'none\'; base-uri \'none\'">');
        body.append(frame);
      }else{const prose=document.createElement('div');prose.className='chat-prose';prose.innerHTML=messageMarkup(file.content);body.append(prose);}
    }
    const download=document.createElement('button');download.type='button';download.textContent='Download file';download.onclick=()=>{const bytes=file.encoding==='base64'?Uint8Array.from(atob(file.content),c=>c.charCodeAt(0)):file.content;const url=URL.createObjectURL(new Blob([bytes],{type:file.mime||'text/plain'})),a=document.createElement('a');a.href=url;a.download=path.split('/').pop();a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};body.append(download);
  }catch(error){body.textContent=error.message;delete item.dataset.loaded;}
});
el('prompt').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(el('send').disabled)return;el('chat').requestSubmit(el('send'));}});

// Keep Enter scoped to this agent; the alternative is an explicit action only.
function setRunOptions(open){
  const expanded=!!open&&!el('run-options').disabled;
  el('run-menu').hidden=!expanded;el('run-options').setAttribute('aria-expanded',String(expanded));
}
el('run-options').onclick=()=>setRunOptions(el('run-menu').hidden);
el('run-control').addEventListener('focusout',e=>{if(!el('run-control').contains(e.relatedTarget))setRunOptions(false);});
el('run-control').addEventListener('keydown',e=>{
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();setRunOptions(false);el('run-options').focus();}
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setRunOptions(true);if(!el('run-menu').hidden)el('send-all').focus();}
});
document.addEventListener('pointerdown',e=>{if(!el('run-control').contains(e.target))setRunOptions(false);});
el('chat').addEventListener('submit',()=>setRunOptions(false));

// Suggestions only complete an explicit slash prefix; Enter selects before sending.
for(const id of ['crew-prompt']){
 const input=el(id),anchor=document.createElement('div'),menu=document.createElement('div'),option=document.createElement('button');
 anchor.className='studio-command-anchor';input.before(anchor);anchor.append(input,menu);
 menu.className='studio-command-menu';menu.id=input.id+'-commands';menu.hidden=true;menu.setAttribute('role','listbox');menu.setAttribute('aria-label','Commands');
 option.type='button';option.id=menu.id+'-plan';option.setAttribute('role','option');option.setAttribute('aria-selected','true');
 option.innerHTML='<strong>/goal</strong><span>Collaborate with the team</span><small>↵</small>';menu.append(option);
 input.setAttribute('aria-controls',menu.id);input.setAttribute('aria-autocomplete','list');
 const close=()=>{menu.hidden=true;input.removeAttribute('aria-activedescendant');};
 const enabled=()=>selectedScenario==='plan'&&selectedCrewRole===0&&input.dataset.planEnabled==='true';
 const update=()=>{const value=input.value.trimStart();const show=enabled()&&!input.disabled&&/^\/(?:g(?:o(?:a(?:ls?)?)?)?|p(?:l(?:a(?:ns?)?)?)?)?$/i.test(value)&&input.selectionStart===input.value.length;
  menu.hidden=!show;if(show)input.setAttribute('aria-activedescendant',option.id);else input.removeAttribute('aria-activedescendant');};
 const choose=()=>{if(!enabled()){close();return;}input.value='/goal ';close();input.focus({preventScroll:true});input.setSelectionRange(input.value.length,input.value.length);input.dispatchEvent(new Event('input',{bubbles:true}));};
 input.addEventListener('input',update);input.addEventListener('focus',update);input.addEventListener('click',update);
 input.addEventListener('keydown',event=>{
  if(!enabled()){close();return;}
  if(menu.hidden||event.isComposing)return;
  if(['Enter','Tab','Escape','ArrowDown','ArrowUp'].includes(event.key)&&!event.shiftKey){
   event.preventDefault();event.stopImmediatePropagation();
   if(event.key==='Enter'||event.key==='Tab')choose();else if(event.key==='Escape')close();
  }
 },true);
 option.addEventListener('pointerdown',event=>event.preventDefault());option.addEventListener('click',choose);
 anchor.addEventListener('focusout',event=>{if(!anchor.contains(event.relatedTarget))close();});
 input.form.addEventListener('submit',close);
 new MutationObserver(()=>{if(input.disabled||!enabled())close();}).observe(input,{attributes:true,attributeFilter:['disabled','data-plan-enabled']});
}
