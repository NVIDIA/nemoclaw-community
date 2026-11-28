// SPDX-License-Identifier: Apache-2.0

// Edit the actual agent files in place; drafts stay with their owning workspace.
let identityRequest=0;
const identityDrafts=new Map();
const identitySaves=new Map();
async function openAgentDocuments(role=null,codeView=false){
 const target=agentId,request=++identityRequest,workspace=target+':'+(role??'personal');
 const name=role===null?data.profile?.name:defaultNames[role];
 if(!name||!target)return;
 dialog(codeView?'INSTRUCTIONS':'AGENT FILES','<section id="studio-identity-viewer"><h3>'+escape(name)+'</h3><p role="status">Loading agent files…</p></section>');
 el('dialog').classList.add('studio-agent-documents');
 el('dialog').classList.toggle('studio-agent-code',codeView);
 const host=el('identity-viewer');
 const current=()=>request===identityRequest&&el('dialog').open&&el('identity-viewer')===host&&agentId===target;
 try{
  await identitySaves.get(workspace)?.catch(()=>{});
  if(!current())return;
  const result=await api('agent-documents'+(role===null?'':'?role='+role),undefined,target);
  if(!current())return;
  let documents=result.documents||[],selected=documents[0]?.path,saving=false;
  const definitions=[['AGENTS.md','Working instructions'],['IDENTITY.md','Identity'],['SOUL.md','Character and boundaries']];
  const drafts=identityDrafts.get(workspace)||new Map();
  const visiblePaths=codeView?definitions.map(([path])=>path):documents.map(doc=>doc.path);
  const changes=()=>[...drafts.values()].filter(draft=>visiblePaths.includes(draft.path));
  const keepDrafts=()=>{if(drafts.size)identityDrafts.set(workspace,drafts);else identityDrafts.delete(workspace);};
  const heading='<div class="studio-identity-heading"><div><h3>'+escape(result.name)+'</h3><p>'+escape(codeView?result.description:'Edit files here. Saved changes apply to the next task.')+'</p></div><button type="button" class="studio-secondary" data-identity-save disabled>Save changes</button></div><p class="studio-document-status" role="status" hidden></p>';
  if(codeView){
   host.innerHTML=heading+'<div class="studio-code-layout">'+definitions.map(([path,label],index)=>'<article class="studio-code-panel"><header><div><small>'+escape(label)+'</small><h4>'+escape(path)+'</h4></div><div class="studio-document-actions"><button type="button" class="studio-secondary" data-code-discard="'+index+'" hidden>Discard</button><button type="button" class="studio-secondary" data-code-copy="'+index+'">Copy</button></div></header><p role="status" data-code-unavailable hidden>Could not open this file.</p><textarea class="studio-markdown-editor" data-code-source="'+index+'" aria-label="'+escape(path)+'" spellcheck="false"></textarea></article>').join('')+'</div>';
  }else{
   host.innerHTML=heading+'<div class="studio-identity-layout"><nav aria-label="Agent documents" class="studio-identity-files">'+['agent','skill'].map(group=>{
    const items=documents.map((doc,index)=>({doc,index})).filter(({doc})=>doc.group===group);
    return items.length?'<section><h4>'+(group==='agent'?'OpenClaw files':'Custom skills')+'</h4>'+items.map(({doc,index})=>'<button type="button" data-identity-document="'+index+'" aria-pressed="false" data-status="'+escape(doc.status)+'"><strong>'+escape(group==='skill'?doc.title:doc.filename)+'</strong><small>'+escape(group==='skill'?'SKILL.md':doc.title)+'</small></button>').join('')+'</section>':'';
   }).join('')+'</nav><section class="studio-identity-document" aria-label="Document contents"><header><div><h4 id="studio-identity-filename"></h4><small id="studio-identity-file-note"></small></div><div class="studio-document-actions"><button type="button" class="studio-secondary" data-identity-discard hidden>Discard changes</button><button type="button" class="studio-secondary" id="studio-identity-copy">Copy</button></div></header><p id="studio-identity-unavailable" role="status" hidden></p><textarea id="studio-identity-source" class="studio-markdown-editor" spellcheck="false"></textarea></section></div>';
  }
  const save=host.querySelector('[data-identity-save]'),status=host.querySelector('.studio-document-status');
  const views=codeView?definitions.map(([path],index)=>({path:()=>path,editor:host.querySelector('[data-code-source="'+index+'"]'),copy:host.querySelector('[data-code-copy="'+index+'"]'),discard:host.querySelector('[data-code-discard="'+index+'"]'),unavailable:host.querySelectorAll('[data-code-unavailable]')[index]})):[{path:()=>selected,editor:el('identity-source'),copy:el('identity-copy'),discard:host.querySelector('[data-identity-discard]'),unavailable:el('identity-unavailable')}];
  const sync=()=>{
   save.disabled=saving||!changes().length;save.textContent=saving?'Saving…':'Save changes';
   for(const view of views){
    view.editor.disabled=saving;view.discard.hidden=!drafts.has(view.path());view.discard.disabled=saving;
    if(codeView)view.editor.closest('article').dataset.dirty=String(drafts.has(view.path()));
   }
   for(const button of host.querySelectorAll('[data-identity-document]'))button.dataset.dirty=String(drafts.has(documents[Number(button.dataset.identityDocument)].path));
   if(!codeView){const doc=documents.find(doc=>doc.path===selected);el('identity-file-note').textContent=drafts.has(selected)?'Unsaved changes':doc?.status==='ready'?'Saved file · '+new Date(doc.updated*1000).toLocaleString():doc?.status==='missing'?'New file':doc?.title||'';}
  };
  const show=()=>{
   for(const view of views){
    const path=view.path(),doc=documents.find(doc=>doc.path===path),available=['ready','missing'].includes(doc?.status);
    view.editor.hidden=!available;view.editor.value=drafts.get(path)?.content??doc?.content??'';
    view.editor.setAttribute('aria-label',path);view.editor.placeholder='Write '+(doc?.filename||path)+' here…';
    view.copy.disabled=!available;view.copy.textContent='Copy';view.unavailable.hidden=available;view.unavailable.textContent='Could not open this file.';
   }
   if(!codeView){
    el('identity-filename').textContent=documents.find(doc=>doc.path===selected)?.filename||'';
    for(const button of host.querySelectorAll('[data-identity-document]'))button.setAttribute('aria-pressed',String(documents[Number(button.dataset.identityDocument)].path===selected));
   }
   sync();
  };
  host.querySelector('nav')?.addEventListener('click',event=>{const button=event.target.closest('[data-identity-document]');if(button&&!saving){selected=documents[Number(button.dataset.identityDocument)].path;show();views[0].editor.scrollTop=0;}});
  for(const view of views){
   view.editor.oninput=()=>{
    const path=view.path(),doc=documents.find(doc=>doc.path===path);if(!doc||saving)return;
    const original=drafts.get(path);
    if(view.editor.value===(doc.content||''))drafts.delete(path);
    else drafts.set(path,{path,revision:original?.revision??doc.revision,content:view.editor.value});
    keepDrafts();status.hidden=true;sync();
   };
   view.discard.onclick=()=>{drafts.delete(view.path());keepDrafts();status.hidden=true;show();};
   view.editor.onkeydown=event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();save.click();}};
   view.copy.onclick=async()=>{
    if(view.editor.hidden)return;const path=view.path();
    try{await copyText(view.editor.value);if(current()&&view.path()===path)view.copy.textContent='Copied';}
    catch{if(current()&&view.path()===path)view.copy.textContent='Select text to copy';}
   };
  }
  save.onclick=async()=>{
   const submitted=changes();if(!current()||saving||!submitted.length)return;
   saving=true;status.hidden=true;sync();
   const pending=api('agent-documents',{role,documents:submitted},target).then(saved=>{for(const draft of submitted)drafts.delete(draft.path);keepDrafts();return saved;});
   identitySaves.set(workspace,pending);
   try{
    const saved=await pending;if(!current())return;
    documents=saved.documents||[];
    status.textContent='Saved. Changes apply to the next task.';status.dataset.error='false';status.hidden=false;
    show();await refresh();
   }catch(error){
    if(current()&&error.status===409){
     try{
      const latest=await api('agent-documents'+(role===null?'':'?role='+role),undefined,target);
      if(current()){documents=documents.map(doc=>latest.documents.find(f=>f.path===doc.path)||doc);show();}
     }catch{}
    }
    if(current()){status.textContent=error.message;status.dataset.error='true';status.hidden=false;}
   }
   finally{if(identitySaves.get(workspace)===pending)identitySaves.delete(workspace);saving=false;if(current())sync();}
  };
  show();
 }catch(error){if(current())host.innerHTML='<h3>'+escape(name)+'</h3><p role="alert">'+escape(error.message)+'</p>';}
}
window.addEventListener('beforeunload',event=>{if(identityDrafts.size){event.preventDefault();event.returnValue='';}});
for(const id of ['portrait','agent-name'])el(id).onclick=()=>openAgentDocuments();
el('agent-code').onclick=()=>openAgentDocuments(null,true);
el('crew-instructions').onclick=async()=>{const key=selectedCrewVisitor()?.key;if(!key)return;await switchAgent(key);if(room==='mission'&&selectedCrewVisitor()?.key===key&&agentId===key)openAgentDocuments(null,true);};
for(const id of ['crew-portrait','crew-name'])el(id).onclick=async()=>{const visitor=selectedCrewVisitor();if(visitor){await switchAgent(visitor.key);if(agentId===visitor.key)openAgentDocuments();}else openAgentDocuments(selectedCrewRole);};
el('dialog').addEventListener('close',()=>{if(!el('dialog').open)identityRequest++;});

// Browser-based folder access works on both local and remote installations.
function syncFileButtons(){
 personalFilesButton.hidden=!data.hasFiles;
 const visitor=selectedCrewVisitor();
 scenarioFilesButton.hidden=visitor?!visitor.hasUploads:!(data.fileWorkspaces||[]).includes(String(selectedCrewRole));
}
async function openWorkspaceFiles(team=false){
 const visitor=team?selectedCrewVisitor():null;if(visitor){await switchAgent(visitor.key);if(room==='mission'&&selectedCrewVisitor()?.key===visitor.key&&agentId===visitor.key)return openWorkspaceFiles();return;}
 const target=agentId,scenario=selectedScenario,role=selectedCrewRole,workspace=team?String(role):'personal';
 if(team?!(data.fileWorkspaces||[]).includes(workspace):!data.hasFiles)return;
 const name=team?defaultNames[role]:data.profile?.name;
 dialog('FILES','<section id="studio-workspace-browser"><header><h3>'+escape(name?'Files shared with '+name:'Uploaded files')+'</h3></header><p id="studio-file-status" role="status">Loading files…</p><div id="studio-file-folders" class="studio-file-folder"></div></section>');
 const host=el('workspace-browser');
 const current=()=>host.isConnected&&el('dialog').open&&target===agentId&&scenario===selectedScenario&&(!team||role===selectedCrewRole);
 try{
  const result=await api('workspace-files?workspace='+encodeURIComponent(workspace)+'&view=uploads',undefined,target);
  if(!current())return;
  const files=result.files||[];
  el('file-status').textContent=files.length?'':'No files attached yet.';
  el('file-folders').innerHTML=files.map(f=>'<button type="button" class="studio-secondary" data-browse-file="'+escape(f.path)+'"><span>'+escape(f.path.slice('inbox/'.length))+'</span><small>'+Math.ceil(f.size/1024)+' KB ↗</small></button>').join('');
  el('file-folders').onclick=event=>{const button=event.target.closest('[data-browse-file]');if(button&&current())openFile(button.dataset.browseFile,'',workspace);};
 }catch(error){if(current())el('file-status').textContent=error.message;}
}
const personalFilesButton=document.createElement('button');personalFilesButton.type='button';personalFilesButton.hidden=true;personalFilesButton.id='studio-personal-files';personalFilesButton.className='studio-secondary';personalFilesButton.textContent='Files';personalFilesButton.onclick=()=>openWorkspaceFiles(false);el('agent-code').after(personalFilesButton);
const scenarioFilesButton=document.createElement('button');scenarioFilesButton.type='button';scenarioFilesButton.hidden=true;scenarioFilesButton.className='studio-team-utility';scenarioFilesButton.textContent='Files';scenarioFilesButton.onclick=()=>openWorkspaceFiles(true);teamConnectionBar.querySelector('.studio-team-utilities').prepend(scenarioFilesButton);

// Uploaded documents open independently of chat navigation or attachment selection.
function attachmentCsvRows(text,maxRows=1000,maxColumns=100){
 const rows=[];let row=[],cell='',quoted=false,clipped=false;
 const field=()=>{if(row.length<maxColumns)row.push(cell);else clipped=true;cell='';};
 const record=()=>{field();rows.push(row);row=[];};
 text=text.replace(/^\uFEFF/,'');
 for(let i=0;i<text.length;i++){
  const char=text[i];
  if(char==='"'){
   if(quoted&&text[i+1]==='"'){cell+='"';i++;}
   else if(quoted||cell==='')quoted=!quoted;
   else cell+=char;
  }else if(char===','&&!quoted)field();
  else if((char==='\n'||char==='\r')&&!quoted){
   if(char==='\r'&&text[i+1]==='\n')i++;
   record();
   if(rows.length>=maxRows){clipped=clipped||i<text.length-1;return {rows,clipped};}
  }else cell+=char;
 }
 if(cell!==''||row.length||quoted)record();
 return {rows,clipped};
}
function attachmentPreviewMarkup(name,text,extracted=false){
 const limit=500000,shortened=text.length>limit,preview=text.slice(0,limit);
 let content,note=extracted?'Extracted text · original formatting and images are not shown.':'';
 if(/\.csv$/i.test(name)&&!extracted){
  const {rows,clipped}=attachmentCsvRows(preview);
  content='<div class="table-scroll"><table>'+rows.map((row,index)=>'<tr>'+row.map(cell=>'<'+(index?'td':'th')+'>'+escape(cell)+'</'+(index?'td':'th')+'>').join('')+'</tr>').join('')+'</table></div>';
  if(clipped||shortened)note='Preview limited to 1,000 rows, 100 columns and 500,000 characters. Download for the full file.';
 }else{
  content='<pre>'+escape(preview)+'</pre>';
  if(shortened)note+=(note?' ':'')+'Preview shortened. Download for the full file.';
 }
 return '<h1>'+escape(name)+'</h1><p class="note">'+escape(note)+'</p>'+content;
}
async function openAttachmentTab(path,workspace,localFile){
 const target=agentId,scenario=selectedScenario,name=path.split('/').pop();
 const tab=window.open('about:blank','_blank');
 if(!tab){alert('Allow pop-ups for this site to preview attachments.','error');return;}
 tab.opener=null;
 const shell=body=>'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>'+escape(name)+'</title><style>html{color-scheme:dark}body{margin:0;padding:32px;background:#101a22;color:#e2eaf0;font:15px/1.65 system-ui,sans-serif}main{max-width:1200px;margin:auto}h1{font-size:22px;overflow-wrap:anywhere;margin:0 0 8px}.note{color:#9db2bf;font-size:13px}pre{font:15px/1.8 system-ui,sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;background:#15232d;padding:24px;border:1px solid #304653;border-radius:12px}a{display:inline-block;color:#cee7a8;margin:0 0 20px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;vertical-align:top;padding:10px 14px;border:1px solid #304653;white-space:pre-wrap;min-width:100px;max-width:480px;overflow-wrap:anywhere}th{background:#23352a;position:sticky;top:0}tr:nth-child(even){background:#15232d}.table-scroll{overflow:auto;max-height:80vh;border-radius:8px}@media(max-width:600px){body{padding:16px}pre{padding:16px}}</style></head><body><main>'+body+'</main></body></html>';
 const show=body=>{if(tab.closed)return;tab.document.open();tab.document.write(shell(body));tab.document.close();};
 show('<h1>'+escape(name)+'</h1><p role="status">Loading file…</p>');
 const read=filePath=>api('file?path='+encodeURIComponent(filePath)+'&workspace='+encodeURIComponent(workspace),undefined,target,scenario);
 try{
  const file=localFile??await read(path);if(tab.closed)return;
  const binary=file.encoding==='base64';
  const readable=binary?await read(path+'.txt'):file;
  if(tab.closed)return;
  show(attachmentPreviewMarkup(name,readable.content||'',binary));
  const blob=new Blob([binary?Uint8Array.from(atob(file.content),c=>c.charCodeAt(0)):file.content],{type:file.mime||(/\.csv$/i.test(name)?'text/csv;charset=utf-8':'text/plain;charset=utf-8')});
  const url=URL.createObjectURL(blob),link=tab.document.createElement('a');
  link.href=url;link.download=name;link.textContent='Download original';
  tab.document.querySelector('h1').after(link);
  const cleanup=setInterval(()=>{if(tab.closed){clearInterval(cleanup);URL.revokeObjectURL(url);}},5000);
 }catch(error){show('<h1>'+escape(name)+'</h1><p role="alert">'+escape(error.message||'Could not open this file.')+'</p>');}
}
