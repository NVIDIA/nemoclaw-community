// SPDX-License-Identifier: Apache-2.0

// Three places in one studio: creation, a growing personal collection, and crew work.
let editingInPlace=false,hiringArrival=false,draftNameEdited=false,draftModel='',creatorModelMarkup='';
function switchyardAvailable(){return runtime.modelConnections?.connections?.api?.provider==='nvidia'&&!!runtime.switchyard?.available;}
function switchyardChoice(){return switchyardAvailable()?(runtime.personalModels?.models||[]).find(row=>row.id==='auto'):null;}
function routingModelLabel(id){
 const currentRole=runtime.switchyard?.roles?.find(role=>role.id===id);
 if(currentRole)return currentRole.label;
 const models=[...(runtime.switchyard?.models||[]),...(runtime.teamModels||[]),...(runtime.personalModels?.models||[])];
 const known=models.find(model=>typeof model==='object'&&(model.id===id||model.id==='api/nvidia/'+id));
 const name=(known?.label||String(id||'')).split('/').at(-1);
 return /^nemotron-/i.test(name)?name.replace(/^nemotron-/i,'Nemotron ').replace(/-super-vl(?:-120b-a12b)?$/i,' Super VL').replace(/-lightning(?:-30b-a3b)?$/i,' Lightning'):name;
}
function switchyardDescription(info=runtime.switchyard){return info?.description||'Automatic model routing.';}
function switchyardOverviewMarkup(info=runtime.switchyard){
 const roles=info?.roles||[],role=key=>roles.find(item=>(item.key||item.role?.toLowerCase())===key);
 const router=role('router'),answers=[role('capable'),role('efficient')];if(!router||answers.some(item=>!item))return '';
 const node=item=>'<div class="switchyard-flow-node" title="'+escape(item.id)+'"><small>'+escape(item.role)+'</small><strong>'+escape(item.label.replace(/^Nemotron 3\.5 /,''))+'</strong></div>';
 return '<div class="switchyard-overview"><div class="switchyard-overview-title">NeMo Switchyard</div>'+
  '<div class="switchyard-flow" role="group" aria-label="Router chooses Capable or Efficient">'+node(router)+
  '<div class="switchyard-destinations">'+answers.map(node).join('')+'</div></div>'+
  (info.notice?'<p class="switchyard-notice">'+escape(info.notice)+'</p>':'')+'</div>';
}
function modelUsageMarkup(job,{role=null,phase=null,attempt=null,agent=null,latest=false,includeLive=false}={}){
 const matches=record=>{
  if(!record||agent&&record.agent!==agent)return false;
  const name=String(record.phase||String(record.stage||'').replace(/^plan-/,''));
  if(role!==null){
   const matches=record.role!==undefined?Number(record.role)===Number(role):record.agent?.endsWith('-r'+role)||record.name===planNames(job.payload?.collaboration)[role];
   if(!matches)return false;
  }
  return (!phase||phase.test(name))&&(attempt===null||Number(name.match(/-permission-retry-(\d+)/)?.[1]||0)===attempt);
 };
 const current=includeLive&&job?.status==='running'&&job.payload.collaboration?.liveModel;
 const live=current&&matches(current);
 if(live&&!current.model&&current.routing?.strategy==='switchyard')
  return '<div class="model-usage" aria-label="Model for this step"><span class="model-usage-chip">Selecting model… <small>Switchyard</small></span></div>';
 let records=live?[current]:Object.values(job?.payload?.metrics||{}).filter(matches);
 if(latest)records=records.sort((a,b)=>(a.measuredAt||0)-(b.measuredAt||0)).slice(-1);
 const items=new Map();
 for(const record of records){
  const routed=record.routing?.strategy==='switchyard';
  const model=record.model||(routed?record.routing.model:null);
  // Never present a configured alias or an unobserved routing choice as an answer model.
  if(!model||['switchyard','switchyard-vision','auto'].includes(model))continue;
  const selected=routed&&!record.model,key=[model,routed,selected,record.routing?.mode].join(':');
  const note=record.previouslyConfirmed?'Last confirmed answer model for this agent in this mission.':routed?(record.routing.mode==='vision'?'Image request - routed directly to '+routingModelLabel(model)+'.':record.routing.judgeModel?'Routing model: '+routingModelLabel(record.routing.judgeModel)+'. Answer model: '+routingModelLabel(model)+'.':'Answer model selected by Switchyard.'):live?'Model handling this request.':'Model reported for this response.';
  items.set(key,'<span class="model-usage-chip" title="'+escape(note+' '+model)+'">'+(routed?'<i aria-hidden="true">↳</i> ':'')+escape(routingModelLabel(model))+(selected?'<small>Selected</small>':routed?'<small>Switchyard'+(record.routing.mode==='vision'?' · Image':'')+'</small>':'')+'</span>');
 }
 return items.size?'<div class="model-usage" aria-label="Models for this step">'+[...items.values()].join('')+'</div>':'';
}
function modelRoutingText(record){
 if(record?.routing?.strategy!=='switchyard'||typeof record.routing.model!=='string')return '';
 return (typeof record.model==='string'&&record.model?'Model: '+routingModelLabel(record.model):'Selected: '+routingModelLabel(record.routing.model));
}
const loungeRoutingNote=el('model-routing');
function personalModel(profile,stage='lounge'){
 profile=(profile?.key&&(data.agents||[]).find(row=>row.key===profile.key))||profile;
 let id=profile?.model||'shared';
 const states=runtime.modelConnections?.connections;
 const explicitTask=stage==='team'&&profile?.taskModel;
 if(explicitTask)id=profile.taskModel;
 if(states&&!explicitTask&&['local','shared','prefer-local'].includes(id)){
  const source=stage==='team'?(states.api?.ready?'api':states.local?.ready?'local':null)
    :id==='prefer-local'?(states.local?.ready?'local':states.api?.ready?'api':null):runtime.modelConnections.loungeSource;
  if(source)id=source==='local'?'local':states.api.defaultModel==='auto'?'auto':`api/${states.api.provider}/${states.api.model}`;
 }
 if(id==='prefer-local')id='local';
 const choice=runtime.personalModels?.models?.find(row=>row.id===id&&(id!=='auto'||switchyardAvailable()));
 return choice||{id,label:id==='auto'?(states?.api?.provider==='nvidia'?'Model routing (NeMo Switchyard)':'Automatic'):id==='local'?'Local':id==='shared'?'Shared default':id.split('/').slice(2).join('/'),source:id==='auto'?'auto':undefined,connected:id==='shared'?!!runtime.model:id==='local'&&!runtime.personalModels?!!runtime.model:false};
}
function personalReady(profile,stage='lounge'){return !!runtime.gateway&&personalModel(profile,stage).connected;}
function personalModelNotice(profile,stage='lounge'){
 if(stage==='team')return profile?.taskModel||profile?.model?.startsWith('api/')?'This agent’s Open Task model is unavailable. Check Settings or choose another model using its model badge.':'Connect Local or an External Endpoint in Settings.';
 return profile?.model==='local'?'No model connection is available. Connect Local or an External Endpoint in Settings.':'This agent’s model is unavailable. Check Settings or choose another model in Edit agent.';
}
function creatorModelChoices(){
 const rows=runtime.personalModels?.models||[{id:'local',label:'Local',source:'local',connected:!!runtime.model},{id:'shared',label:'Shared default',source:'shared',connected:!!runtime.model}];
 const choices=rows.filter(row=>(row.id!=='shared'||draftModel==='shared')&&(row.id!=='auto'||switchyardAvailable()));
 const selected=personalModel({model:draftModel});
 if(draftModel&&!choices.some(row=>row.id===selected.id))choices.push(selected);
 return [...new Map(choices.map(row=>[row.id,row])).values()];
}
function creatorModelAllowed(){
 // Existing agents can still change their name/persona while their saved model is offline.
 return !!draftModel&&(personalModel({model:draftModel}).connected||(draftMode==='edit'&&draftModel===(data.profile?.model||'shared')));
}
function updateCreatorSubmit(){
 el('create').disabled=hiringArrival||!creatorModelAllowed()||(draftMode==='new'&&(data.agents?.length||0)>=(data.agentLimit||12));
}
function renderCreatorModels(){
 const input=el('agent-model-search'),results=el('agent-model-results'),choices=creatorModelChoices();
 const selected=personalModel({model:draftModel});
 const chosen=draftModel==='prefer-local'?choices.find(row=>row.id==='local')
   :draftMode==='new'&&draftModel==='local'&&!selected.connected?null:selected;
 const query=input.value.trim().toLowerCase();
 const sourceName=row=>row.source==='auto'?'Automatic':row.source==='api'?'External Endpoint':row.source==='local'?'Local':'Shared default';
 const matches=choices.filter(row=>(row.label+' '+row.id+' '+sourceName(row)+' '+(row.description||'')).toLowerCase().includes(query));
 const displayName=row=>row.source==='auto'?row.label:row.source==='local'?'Local':row.label.split('/').at(-1);
 const nemotron=row=>(row.label+' '+row.id).toLowerCase().includes('nemotron');
 matches.sort((a,b)=>Number(b.id==='auto')-Number(a.id==='auto')||Number(nemotron(b))-Number(nemotron(a))||displayName(a).localeCompare(displayName(b))||a.id.localeCompare(b.id));
 const html=matches.slice(0,40).map(row=>{
  const title=displayName(row),description=row.source==='auto'?(row.description||switchyardDescription()):row.source==='local'?(row.label.replace(/^Local(?: - )?/,'')||'On this host'):row.source==='api'?row.id.split('/').slice(2).join('/'):'Uses the shared connection';
  return `<button type="button" data-agent-model-choice="${escape(row.id)}" aria-pressed="${row.id===chosen?.id}" ${row.connected?'':'disabled'} title="${escape(row.label)}"><span><strong>${escape(title)}</strong><small>${escape(description)}</small></span><span class="studio-model-choice-state">${row.connected?(row.id===chosen?.id?'Selected':sourceName(row)):'Not connected'}</span></button>`;
 }).join('')||'<p class="studio-model-empty">No matching models</p>';
 const focused=document.activeElement?.closest('[data-agent-model-choice]')?.dataset.agentModelChoice;
 // Compare the source markup: the browser normalizes boolean attributes and spacing.
 // Replacing unchanged rows on each poll can interrupt clicks or keyboard selection.
 if(creatorModelMarkup!==html){creatorModelMarkup=html;results.innerHTML=html;if(focused)[...results.querySelectorAll('button')].find(button=>button.dataset.agentModelChoice===focused&&!button.disabled)?.focus({preventScroll:true});}
 const summary=el('agent-model-summary');
 summary.textContent=chosen?(chosen.id==='local'?'Local':chosen.label.split('/').at(-1)):'Not connected';summary.title=chosen?.label||'';summary.dataset.ready=String(!!chosen?.connected);
 const missing=!chosen?.connected;
 el('agent-model-note').textContent=!chosen?'Connect a model in Settings.':missing?(chosen.id==='auto'&&runtime.switchyard?.reason||'Selected model is not connected.'):chosen.id==='auto'?(chosen.description||switchyardDescription()):matches.length>40?'Showing 40 models. Refine your search.':'';
 el('agent-model-note').hidden=!el('agent-model-note').textContent;el('agent-model-settings').hidden=!missing;
 updateCreatorSubmit();
}
function chooseCreatorModel(id){
 if(!creatorModelChoices().some(row=>row.id===id&&row.connected))return;
 draftModel=id==='local'?'prefer-local':id;el('agent-model-search').value='';renderCreatorModels();
 el('agent-model-panel').open=false;el('agent-model-panel').querySelector('summary').focus({preventScroll:true});
}
el('agent-model-search').oninput=renderCreatorModels;
el('agent-model-search').onkeydown=event=>{
 if(event.key==='Enter'){
  event.preventDefault();const enabled=el('agent-model-results').querySelectorAll('button:not(:disabled)');
  if(enabled.length===1)chooseCreatorModel(enabled[0].dataset.agentModelChoice);
 }else if(event.key==='ArrowDown'){event.preventDefault();el('agent-model-results').querySelector('button:not(:disabled)')?.focus();}
};
el('agent-model-results').onclick=event=>{const button=event.target.closest('[data-agent-model-choice]');if(button&&!button.disabled)chooseCreatorModel(button.dataset.agentModelChoice);};
el('agent-model-results').onkeydown=event=>{
 if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
 const buttons=[...el('agent-model-results').querySelectorAll('button:not(:disabled)')];if(!buttons.length)return;
 event.preventDefault();const index=buttons.indexOf(document.activeElement);
 buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();
};
el('agent-model-panel').addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();el('agent-model-panel').open=false;el('agent-model-panel').querySelector('summary').focus();}});
el('agent-model-panel').addEventListener('toggle',()=>{if(el('agent-model-panel').open)renderCreatorModels();});
el('agent-model-settings').onclick=openModelSettings;
const appearanceColors={green:'#76b900',cyan:'#55bfff',amber:'#f4b34f',coral:'#ff8873',violet:'#b49aff',ice:'#cbddea'};
const appearanceCatalog=/* AVATAR_CATALOG */;
const appearanceNames={rover:'Scout',...Object.fromEntries(appearanceCatalog.bodies.map(body=>[body.id,body.name]))};
function avatarAppearanceStyle(avatar={}){
 const palette=appearanceCatalog.palettes[avatar.color];
 return '--avatar-accent:'+(palette?.accent||appearanceColors[avatar.color]||appearanceColors.green)+(palette?';--avatar-base:'+palette.base+';--avatar-light:'+palette.light+';--avatar-dark:'+palette.dark:'');
}
function renderAvatarPortrait(node,avatar={}){
 node.dataset.body=avatar.body||'classic';node.dataset.accessory=avatar.accessory||'none';
 node.style.cssText=avatarAppearanceStyle(avatar);
}
function renderPalettes(preserveSaved=false){
 const body=appearanceCatalog.bodies.find(body=>body.id===draftAvatar.body);
 const options=[...(body?.palettes||Object.keys(appearanceColors))];
 if(preserveSaved&&!options.includes(draftAvatar.color)&&(appearanceCatalog.palettes[draftAvatar.color]||appearanceColors[draftAvatar.color]))options.push(draftAvatar.color);
 if(!options.includes(draftAvatar.color))draftAvatar.color=options[0];
 el('color-picker').innerHTML=options.map(id=>{
  const palette=appearanceCatalog.palettes[id],label=palette?.label||(id[0].toUpperCase()+id.slice(1)+' (saved)');
  const swatch=palette?'linear-gradient(135deg,'+palette.base+' 0 40%,'+palette.light+' 40% 65%,'+palette.dark+' 65% 100%)':appearanceColors[id];
  return '<button type="button" data-avatar-color="'+escape(id)+'" style="--swatch:'+swatch+'" aria-label="'+escape(label)+'" title="'+escape(label)+'" aria-pressed="false"></button>';
 }).join('');
}
function renderAccessories(preserveSaved=false){
 const body=appearanceCatalog.bodies.find(body=>body.id===draftAvatar.body);
 const options=['none',...(body?.accessories||['antenna','headset','glasses','cap','backpack'])];
 // Existing agents keep a previously saved outfit until the user changes it.
 const saved=preserveSaved&&!options.includes(draftAvatar.accessory)&&appearanceCatalog.accessories[draftAvatar.accessory];
 if(saved)options.push(draftAvatar.accessory);
 if(!options.includes(draftAvatar.accessory))draftAvatar.accessory='none';
 el('accessory').innerHTML=options.map(id=>'<option value="'+escape(id)+'">'+escape(appearanceCatalog.accessories[id])+(saved&&id===draftAvatar.accessory?' (saved)':'')+'</option>').join('');
 el('accessory').value=draftAvatar.accessory;
 el('saved-appearance').hidden=!!body;
 el('saved-appearance').textContent=body?'':'Rover · saved appearance';
}
function avatarBadge(avatar={}){return `<span class="studio-avatar tiny" aria-hidden="true" data-body="${escape(avatar.body||'classic')}" data-accessory="${escape(avatar.accessory||'none')}" style="${avatarAppearanceStyle(avatar)}"><i></i><i></i></span>`;}
// Presets and custom text edit the same two fields; no hidden tone overrides.
function creatorPrompt(){
  return {tonePrompt:el('tone-prompt').value.trim(),purpose:el('purpose').value.trim()};
}
function writeCreatorPrompt(tone,role){el('tone-prompt').value=tone;el('purpose').value=role;}
function tonePromptLabel(key){return tones[key][0]+' ('+tones[key][1]+')';}
function matchesTonePrompt(key,text){return [tones[key][0],tonePromptLabel(key)].some(value=>value.toLowerCase()===text.toLowerCase());}
function savedTonePrompt(profile){return profile.tonePrompt??tonePromptLabel(profile.tone||'kind');}
function syncCreatorTone(){
  const tone=creatorPrompt().tonePrompt.toLowerCase();
  draftTone=Object.keys(tones).find(key=>matchesTonePrompt(key,tone))||'kind';
}
function availableAgentName(body){
  const baseName=appearanceNames[body]||'Agent';let name=baseName,number=2;
  while(data.agents?.some(a=>a.name.toLowerCase()===name.toLowerCase()))name=baseName+'_'+number++;
  return name;
}
function updateDraft(){
  syncRequiredRoleSkills();
  el('body-picker').querySelectorAll('button[data-body]').forEach(b=>{
   const selected=b.dataset.body===draftAvatar.body;b.setAttribute('aria-pressed',selected);
   const body=appearanceCatalog.bodies.find(body=>body.id===b.dataset.body);
   b.querySelector('.body-glyph').style.cssText=avatarAppearanceStyle(selected?draftAvatar:{color:body.palettes[0]});
  });
  el('color-picker').querySelectorAll('button[data-avatar-color]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.avatarColor===draftAvatar.color));
  el('palette-name').textContent=appearanceCatalog.palettes[draftAvatar.color]?.label||((draftAvatar.color||'')[0]?.toUpperCase()+(draftAvatar.color||'').slice(1)+' (saved)');
  draftAvatar.accessory=el('accessory').value;
  const verbosity='balanced';
  // Status badges elsewhere in the studio are not editor controls.
  el('tone-picker').querySelectorAll('button[data-tone]').forEach(b=>b.setAttribute('aria-pressed',matchesTonePrompt(b.dataset.tone,creatorPrompt().tonePrompt)));
  window.BacCampus?.setDraft({name:el('name').value.trim()||'Your new agent',...creatorPrompt(),persona,tone:draftTone,verbosity,protection:el('onboarding').querySelector('[name=protection]:checked')?.value||'standard',avatar:{...draftAvatar}});
  renderCreatorModels();
}
function fillCreator(creating){
  draftMode=creating?'new':'edit';draftOwner=agentId;
  const n=data.agents?.length||0;
  const used=new Set((data.agents||[]).map(a=>[a.avatar?.body,a.avatar?.color,a.avatar?.accessory].join(':')));
  let defaults;
  for(let offset=0;offset<12;offset++){const index=n+offset,body=appearanceCatalog.bodies[index%appearanceCatalog.bodies.length];defaults={body:body.id,color:body.palettes[Math.floor(index/appearanceCatalog.bodies.length)%body.palettes.length],accessory:'none'};if(!used.has([defaults.body,defaults.color,defaults.accessory].join(':')))break;}
  const name=availableAgentName(defaults.body);
  const p=creating?{name,persona:'guide',purpose:roleTemplates[0].purpose,skills:[...roleTemplates[0].skills],avatar:defaults}:data.profile;
  if(!p)return fillCreator(true);
  draftNameEdited=!creating;
  draftModel=creating?'local':p.model||'shared';el('agent-model-search').value='';el('agent-model-panel').open=false;
  el('name').value=p.name;writeCreatorPrompt(savedTonePrompt(p),p.purpose||(creating?'':personas[p.persona]));persona=p.persona;draftAvatar={...(p.avatar||defaults)};renderAccessories(!creating);renderPalettes(!creating);
  draftTone=p.tone||'kind';
  el('role-templates').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(roleTemplates[Number(b.dataset.roleTemplate)]?.purpose===p.purpose)));
  el('role-hint').textContent='';
  el('skill-picker').querySelectorAll('input').forEach(i=>i.checked=p.skills.includes(i.value));
  el('onboarding').querySelectorAll('[name=protection]').forEach(i=>i.checked=i.value===(p.protection||'standard'));
  el('onboarding').querySelector('.studio-protection-picker').hidden=!creating;
  el('onboarding').querySelectorAll('[name=protection]').forEach(i=>i.disabled=!creating);
  el('creator-title').textContent=creating?'Hire your own Agent.':'Edit '+p.name;
  el('creator-note').hidden=true;
  el('creator-note').textContent='';
  el('create').textContent=creating?'Hire my agent':'Save my agent';el('cancel-create').hidden=!data.profile;updateCreatorSubmit();
  updateDraft();el('workshop').scrollTop=0;
}
function setRoom(next,options={}){
  const openPolicies=next==='policies';if(openPolicies)next='lounge';
  if(!Object.hasOwn(roomTitles,next))return;
  const before=options.fromWorld&&!worldOpen?worldViewport.getBoundingClientRect().top:null;
  if(next!==room||(next==='mission'&&options.fromWorld&&!options.resume))closeSurface();
  editingInPlace=false;room=next;if(next!=='mission'){board=false;selectedOpenTaskVisitor='';}
  root.dataset.room=next;worldViewport.setAttribute('aria-label',roomTitles[next]+'. Drag to orbit, scroll to zoom. Press Enter to toggle fullscreen.');if(roomsReady)try{sessionStorage.setItem('bac-studio-room',next);}catch{}
  if(next==='mission')renderCrew();renderRoomVisibility();
  runtimeBadge();
  window.BacCampus?.setRoom(next,{instant:!roomsReady});
  if(openPolicies)openSurface('policies');
  if(before!==null)window.scrollBy(0,worldViewport.getBoundingClientRect().top-before);
}
function renderRoomVisibility(){
  syncHeartbeatContext();
  if(el('compare'))el('compare').hidden=room!=='lounge'||!comparison;
  syncComposer();
  const workshop=room==='workshop',lounge=room==='lounge',mission=room==='mission';
  el('workshop').hidden=!(workshop||editingInPlace);el('passport').hidden=!lounge||editingInPlace;el('crew-passport').hidden=!mission||editingInPlace;el('connections').hidden=!workshop;el('policies').hidden=false;el('policy-panel').hidden=!lounge;
  el('collection').hidden=!lounge||!data.profile;
  layout.hidden=false;el('board').hidden=true;
  el('experiences').hidden=!lounge;el('workspace').hidden=workshop||editingInPlace||(mission?!currentCollaboration():(!current()&&!data.files?.length));el('safety-bar').hidden=true;
  el('room-action').hidden=true;
  document.getElementById('campus-roster').hidden=!mission;
  renderScenarioSelector();
  const count=data.agents?.length||0;
  const detail=workshop?'Meet your next agent':lounge?count+' hired '+(count===1?'agent':'agents'):'Multi-agent collaboration';
  document.getElementById('campus-location').textContent=roomTitles[room]+' / '+detail;
  syncSurface();
  if(workshop)document.getElementById('campus-motion-status').textContent='';
  if(lounge)document.getElementById('campus-motion-status').textContent='';
}
function renderRooms(){
  if(!roomsReady){roomsReady=true;fillCreator(true);let saved;try{saved=sessionStorage.getItem('bac-studio-room');}catch{}setRoom(data.profile?(Object.hasOwn(roomTitles,saved)?saved:'lounge'):'workshop');window.BacCampus?.overview({instant:true});}
  renderRoomVisibility();
  const agents=data.agents||[];
  const auto=runtime.modelConnections?.connections?.api?.provider==='nvidia'&&data.profile&&personalModel(data.profile).id==='auto';
  loungeRoutingNote.hidden=!auto;loungeRoutingNote.innerHTML=auto?switchyardOverviewMarkup(runtime.switchyard):'';
  loungeRoutingNote.title=auto?(switchyardChoice()?.description||runtime.switchyard?.reason||switchyardDescription()):'';
  el('gateway-state').textContent=runtime.testFixture?'Test fixture · no live gateway':gatewayLabel();
  el('model-state').textContent=runtime.testFixture?'Test fixture · no live model':runtime.model?'Connected':'Not connected';
  el('shell-state').textContent=runtime.openshell||'Optional · not configured';
  if(data.profile)renderAvatarPortrait(el('portrait'),data.profile.avatar);
  window.BacCampus?.setCollection(agents,agentId);
  // Connection settings can change without a new conversation-state response.
  // Refresh the selected agent's model badge before its next execution.
  if(room==='mission'){
   const binding=selectedCrewVisitor(),visitor=agents.find(agent=>agent.key===binding?.key)||binding;
   renderCrewModel(visitor?personalModel(visitor,'team'):teamModel(selectedCrewRole),visitor);
  }
  // Runtime readiness can finish while this picker is open, without a new
  // conversation state. Keep its Automatic option in sync with that result.
  if(!teamModelDialog.hidden&&teamModelDialog.isConnected)renderModelResults();
  renderPolicySelector();
}
function agentForm(creating=false){if(creating&&(data.agents?.length||0)>=(data.agentLimit||12)){alert('Your lounge is full. You can edit any of your existing agents.');return;}fillCreator(creating);if(creating)setRoom('workshop');else{editingInPlace=true;renderRoomVisibility();}el('workshop').scrollTop=0;}
el('body-picker').innerHTML=appearanceCatalog.bodies.map(body=>'<button type="button" data-body="'+escape(body.id)+'" aria-pressed="false"><span class="studio-body-art" aria-hidden="true"><span class="body-glyph '+escape(body.id)+'" style="'+avatarAppearanceStyle({color:body.palettes[0]})+'"><i></i><i></i></span></span><span>'+escape(body.label)+'</span></button>').join('');
el('body-picker').onclick=e=>{const b=e.target.closest('[data-body]');if(b){draftAvatar.body=b.dataset.body;renderAccessories();renderPalettes();if(draftMode==='new'&&!draftNameEdited)el('name').value=availableAgentName(draftAvatar.body);updateDraft();}};
el('color-picker').onclick=e=>{const b=e.target.closest('[data-avatar-color]');if(b){draftAvatar.color=b.dataset.avatarColor;updateDraft();}};
el('accessory').onchange=updateDraft;el('name').addEventListener('input',()=>{draftNameEdited=true;updateDraft();});
const roleTemplates=/* ROLE_TEMPLATES */;
el('role-templates').innerHTML=roleTemplates.map((t,i)=>`<button type="button" data-role-template="${i}" aria-pressed="false">${t.label}</button>`).join('');
function selectedRoleTemplate(){return roleTemplates.find(t=>t.purpose.toLowerCase()===creatorPrompt().purpose.trim().toLowerCase());}
function syncRequiredRoleSkills(){
  const template=selectedRoleTemplate(),required=template?.requiredSkills||[];
  // The scheduled Radar role follows its fixed skill, including its check interval.
  const fixedRole=required.includes('radar');
  el('purpose').readOnly=fixedRole;
  el('skill-picker').querySelectorAll('input').forEach(input=>{
    const fixed=required.includes(input.value),card=input.closest('.studio-skill-card');
    input.disabled=fixed;if(fixed)input.checked=true;
    card.querySelector('.studio-skill-fixed').hidden=!fixed;
    card.querySelector('label').title=fixed?'Included with '+template.label:'';
  });
}
function selectRoleSkills(skills,showHint=false){
  el('skill-picker').querySelectorAll('input').forEach(input=>input.checked=skills.includes(input.value));
  el('role-hint').textContent=showHint?(skills.length?'Skills suggested based on your description.':'No matching skills.'):'';
  updateDraft();
}
el('skill-picker').addEventListener('change',()=>{el('role-hint').textContent='';});
el('role-templates').onclick=e=>{const button=e.target.closest('[data-role-template]');if(!button)return;const template=roleTemplates[Number(button.dataset.roleTemplate)];writeCreatorPrompt(creatorPrompt().tonePrompt,template.purpose);el('role-templates').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));selectRoleSkills(template.skills);};
el('purpose').addEventListener('input',()=>{el('role-templates').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed','false'));el('role-hint').textContent='';syncCreatorTone();updateDraft();});
el('tone-prompt').addEventListener('input',()=>{syncCreatorTone();updateDraft();});
el('apply-prompt').onclick=()=>{
  syncCreatorTone();
  const role=creatorPrompt().purpose.toLowerCase();
  // Preset wording mentions teammates and outputs too; it is not a request to equip their skills.
  const template=selectedRoleTemplate();
  if(template){selectRoleSkills(template.requiredSkills?.length?[...new Set([...template.skills,...[...el('skill-picker').querySelectorAll('input:checked')].map(i=>i.value)])]:template.skills,true);return;}
  const rules={radar:/heartbeat|tech radar|technical feeds|하트비트|기술.*소식/,weather:/weather|forecast|travel|trip|날씨|여행/,web:/research|paper|arxiv|논문|search|online|web|travel|trip|cafe|restaurant|리서치|조사|검색|웹|여행|맛집|카페/,documents:/takeaway|three points|meeting|notes|회의|메모|document|report|pdf|ppt|slides|deck|summar|요약|슬라이드|csv|spreadsheet|문서|보고서|자료|엑셀/,builder:/app|game|prototype|code|coding|programmer|programming|website|webpage|앱|게임|코딩|개발|웹사이트/,writer:/slack|announcement|공지|message|email|메시지|메일|writ|draft|content|invitation|social|campaign|marketing|copy|작성|글쓰기|초대|마케팅|콘텐츠/,memory:/remember|memor|preference|기억|선호/};
  selectRoleSkills(Object.entries(rules).filter(([skill,rule])=>rule.test(role)).map(([skill])=>skill),true);
};
el('onboarding').querySelectorAll('[name=protection]').forEach(input=>input.onchange=updateDraft);
el('tone-picker').onclick=e=>{const button=e.target.closest('[data-tone]');if(button){draftTone=button.dataset.tone;writeCreatorPrompt(tonePromptLabel(draftTone),creatorPrompt().purpose);updateDraft();}};
root.addEventListener('bac:world-room',e=>setRoom(e.detail.room,{fromWorld:true}));

el('edit-agent').onclick=()=>agentForm(false);el('cancel-create').onclick=()=>{if(editingInPlace){editingInPlace=false;fillCreator(true);renderRoomVisibility();}else setRoom('lounge');};
function forgetDeletedAgent(target){
  stateCache.clear();
  personalDrafts.delete(target);
  for(const key of chatImageDrafts.keys())if(key.startsWith(target+':'))chatImageDrafts.delete(key);
  for(const key of crewDrafts.keys())if(key.startsWith(target+':'))crewDrafts.delete(key);
  try{const layout=JSON.parse(localStorage.getItem('bac-lounge-layout-v1')||'{}');delete layout[target];localStorage.setItem('bac-lounge-layout-v1',JSON.stringify(layout));}catch{}
}
// A collection snapshot stays valid even when the selected identity was just removed.
function applyDeletionSnapshot(state){
  if(changingAgent)return;
  if(state.agentId===agentId){
    if(state!==data){data=state;render();}
    return;
  }
  const selected=state.agents.find(agent=>agent.key===agentId);
  if(!selected){openAgentState(state,{keepView:true});return;}
  // The default workspace belongs to another agent. Only its roster is shared.
  if(data.agents!==state.agents){
    data={...data,agents:state.agents,deleting:!!selected.deleting};render();
  }
}
async function waitForAgentDeletions(agents,scenario){
  const pending=new Map(agents.map(agent=>[agent.key,agent.name]));
  while(pending.size){
    const selected=agentId,watchingSelection=pending.has(selected);
    const state=await api('state',undefined,'',scenario);
    let paused='';
    for(const [key,name] of pending){
      const agent=state.agents.find(row=>row.key===key);
      if(!agent){pending.delete(key);forgetDeletedAgent(key);}
      else if(!agent.deletionWaiting)paused=name;
    }
    if(watchingSelection&&selected===agentId&&scenario===selectedScenario)applyDeletionSnapshot(state);
    if(paused)throw new Error('Cleanup could not finish for '+paused+'. Retry deletion.');
    if(pending.size)await new Promise(resolve=>setTimeout(resolve,1000));
  }
}
el('delete-agent').onclick=()=>{
  if(!data.profile||pendingWrites||changingAgent||removingAgent||resetInProgress)return;
  const target=agentId,name=data.profile.name;
  dialog('REMOVE AGENT',`<div class="studio-delete-identity">${avatarBadge(data.profile.avatar)}<div><span class="studio-delete-speaker">${escape(name)}</span><h3>“You sure you won’t need me?”</h3></div></div><p>Deleting <strong>${escape(name)}</strong> permanently removes this agent’s chats, memory and files.</p><p class="studio-delete-note">Pending and scheduled tasks are cancelled. Active tasks involving this agent stop.</p><p id="studio-delete-error" role="alert" hidden></p><div class="studio-delete-actions"><button class="studio-secondary" id="studio-delete-cancel" autofocus>Keep ${escape(name)}</button><button class="studio-danger" id="studio-delete-confirm">Delete ${escape(name)}</button></div>`);
  el('dialog').classList.add('studio-delete-dialog');
  el('delete-cancel').onclick=()=>el('dialog').close();el('delete-cancel').focus();
  el('delete-confirm').onclick=async()=>{
    if(target!==agentId)return;
    removingAgent=true;++refreshVersion;
    el('dialog').close();
    el('delete-agent').disabled=true;
    try{
      await api('delete-agent',{name},target);
    }catch(error){removingAgent=false;render();refresh();alert(error.message,'error');return;}
    removingAgent=false;
    try{
      const row=data.agents.find(agent=>agent.key===target);
      if(target===agentId&&row){
        data={...data,deleting:true,agents:data.agents.map(agent=>agent.key===target?{...agent,deleting:true,deletionWaiting:true}:agent)};
        render();
      }
      await waitForAgentDeletions([{key:target,name}],selectedScenario);
      alert(name+' was deleted.');
    }catch(error){alert(error.message,'error');}
    finally{await refresh();}
  };
};
el('connection-setup').onclick=setup;el('connection-security').onclick=()=>setRoom('policies');
el('onboarding').onsubmit=async e=>{
  e.preventDefault();if(hiringArrival)return;if(!creatorModelAllowed()){el('agent-model-panel').open=true;el('agent-model-search').focus();return;}syncCreatorTone();const mode=draftMode,target=mode==='new'?agentId:draftOwner,first=!data.agents?.length;
  syncRequiredRoleSkills();
  const payload={model:draftModel,name:el('name').value,...creatorPrompt(),persona,tone:draftTone,verbosity:'balanced',skills:[...el('skill-picker').querySelectorAll('input:checked')].map(x=>x.value),avatar:{...draftAvatar},protection:el('onboarding').querySelector('[name=protection]:checked').value};
  hiringArrival=true;el('create').disabled=true;el('onboarding').inert=true;
  try{
    const result=await api(mode==='edit'?'profile':first?'onboard':'agents',payload,mode==='new'&&!first?'':target);
    // Bind the arrival to this response, never to a changing workspace selection.
    const createdId=mode==='new'&&!first?result.agentId:target;
    if(mode==='new'){++refreshVersion;openAgentState(await api('state',undefined,createdId));}else await refresh();
    if(mode==='new'&&room==='workshop'){hiringArrival=true;el('create').textContent='Joining your lounge…';await window.BacCampus?.welcomeAgent(createdId);if(room!=='workshop'||root.dataset.worldOverview==='true'){fillCreator(true);return;}}
    const stayHere=mode==='edit'&&editingInPlace;editingInPlace=false;fillCreator(true);if(stayHere)renderRoomVisibility();else setRoom('lounge');el('workshop').scrollTop=0;
    alert(mode==='edit'?'Your agent is updated.':(data.profile?.name||payload.name)+' has joined your lounge. Give your new teammate a mission.');
  }catch(error){alert(error.message,'error');}finally{hiringArrival=false;el('onboarding').inert=false;updateCreatorSubmit();}
};
// Selecting a resident updates its workspace without moving the visitor's view.
root.addEventListener('bac:collection-select',e=>{editingInPlace=false;renderRoomVisibility();if(room==='mission'&&selectedScenario==='plan'){selectOpenTaskVisitor(e.detail);return;}renderRoomVisibility();switchAgent(e.detail);});
// Useful in file-only UI review too; live status is supplied by boot().
fillCreator(true);setRoom('workshop');window.BacCampus?.overview({instant:true});
