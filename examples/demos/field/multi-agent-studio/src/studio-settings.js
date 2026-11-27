// SPDX-License-Identifier: Apache-2.0

// Host settings: tab changes keep drafts; model discovery is visibly selectable.
async function waitForAgentRuntime(){
  const deadline=Date.now()+45000;
  do{
    runtime=await api('runtime',undefined,'');runtimeBadge();
    if(runtime.gateway)return;
    await new Promise(resolve=>setTimeout(resolve,1500));
  }while(Date.now()<deadline);
  throw new Error('The agent runtime is not ready. Try Start agents again.');
}
const settingsButton=document.createElement('button');settingsButton.id='studio-config';settingsButton.className='studio-config';settingsButton.type='button';settingsButton.textContent='⚙';settingsButton.title='Settings';settingsButton.setAttribute('aria-label','Settings');settingsButton.hidden=true;document.querySelector('.studio-header-actions').append(settingsButton);
let settingsOpenRequest=0;
function scenarioHasWork(id=selectedScenario){
 const scenario=(data.scenarios||[]).find(s=>s.id===id);
 return !!(scenario?.hasWork||scenario?.busy);
}
function syncResetButtons(){
 const hasAgents=!!(data.agents||[]).length,hasAnyScenario=(data.scenarios||[]).some(s=>s.hasWork||s.busy);
 el('settings-reset-panel')?.setAttribute('aria-busy',String(resetInProgress||!!data.bacResetting&&!data.bacResetError));
 for(const id of ['agent-reset','settings-plan-reset','reset-all','bac-reset']){
  const button=el(id);if(!button)continue;
  const empty=id==='agent-reset'?!hasAgents:id==='reset-all'?!hasAgents&&!hasAnyScenario:!scenarioHasWork(button.dataset.resetScenario||selectedScenario);
  const retry=!!data.bacResetError&&id!=='agent-reset';
  button.disabled=resetInProgress||!!data.bacResetting&&!retry||removingAgent||(empty&&!retry);
  button.title=retry?'Retry reset':empty?'Nothing to reset':'';
 }
 if(data.bacResetError&&!resetInProgress&&el('settings-status')){el('settings-status').hidden=false;el('settings-status').textContent=data.bacResetError;}
 if(resetInProgress&&el('settings-status'))el('settings-status').textContent='Reset in progress. Agent cleanup is still running.';
}
settingsButton.onclick=()=>openModelConnections();
el('dialog').addEventListener('close',()=>{const key=el('connect-key');if(key)key.value='';});
function settingsUtilityPanels(){return `  <section id="studio-settings-location-panel" role="tabpanel" aria-labelledby="studio-settings-location-tab" hidden><label for="studio-location-city">City</label><input id="studio-location-city" autocomplete="address-level2" maxlength="80" required aria-describedby="studio-location-note"><small id="studio-location-note">Default city for weather and local requests.</small></section>
  <section id="studio-settings-reset-panel" role="tabpanel" aria-labelledby="studio-settings-reset-tab" class="studio-agent-reset" hidden>
   <div class="studio-reset-row"><div><small class="studio-reset-stage">STAGES 01 / 02</small><h3>${roomTitles.workshop} &amp; ${roomTitles.lounge}</h3><p>Remove hired agents and their chats, files, and workspaces.</p></div><button type="button" id="studio-agent-reset" class="studio-secondary" aria-label="Remove Stage 1 and 2 agents" ${(data.agents||[]).length?'':'disabled'}>Remove agents</button></div>
   ${[['plan','03',roomTitles.mission,'plan']].map(([scenario,stage,title,id])=>`<div class="studio-reset-row"><div><small class="studio-reset-stage">STAGE ${stage}</small><h3>${title}</h3><p>Clear Open Task chats, documents, results, built-in model choices and Shell’s website approvals.</p></div><button type="button" id="studio-settings-${id}-reset" data-reset-scenario="${scenario}" class="studio-secondary" aria-label="Reset ${title}">Reset Open Task</button></div>`).join('')}
   <div class="studio-reset-footer"><p>Reset all stages. Model and connection settings are kept.</p><button type="button" id="studio-reset-all" class="studio-danger">Reset all</button></div>
  </section>
`;}

function confirmTeamReset(sourceButton){
 if(resetInProgress||removingAgent||pendingWrites||changingAgent||data.bacResetting&&!data.bacResetError)return;
 dialog(roomTitles.mission, '<h3>Reset '+escape(roomTitles.mission)+'?</h3><p>This stops active work and clears all Open Task chats, documents and results. Shell’s website approvals are cleared. Your hired agents and connection settings are preserved.</p><div class="studio-dialog-actions"><button type="button" class="studio-secondary" id="studio-team-reset-cancel" autofocus>Cancel</button><button type="button" class="studio-danger" id="studio-team-reset-confirm">Reset Open Task</button></div>');
 el('team-reset-cancel').onclick=()=>el('dialog').close();
 el('team-reset-confirm').onclick=()=>{el('dialog').close();resetStudio('bac',sourceButton);};
 el('team-reset-cancel').focus();
}

async function resetStudio(scope,sourceButton=null,scenario=selectedScenario){
 if(resetInProgress||removingAgent||pendingWrites||changingAgent)return;
 resetInProgress=true;++refreshVersion;
 // Lock the composer before the first network round trip; otherwise a new
 // draft can be accepted here and erased when the reset epoch arrives.
 render();
 const modal=el('dialog'),revision=dialogRevision;
 const status=sourceButton?el('team-reset-status'):el('settings-status');
 status.hidden=false;status.textContent='Resetting…';
 syncResetButtons();
 let background=false,teamCleared=false;
 try{
  const latest=await api('state',undefined,'',scenario);
  const agents=scope==='bac'?[]:latest.agents||[];
  if(scope==='bac'||scope==='all'){
   let reset=await api('bac-reset',{scope:scope==='all'?'all':'scenario'},latest.agentId,scenario);
   while(reset.resetting){
    status.textContent=scope==='all'?'Stopping all scenarios and resetting…':'Stopping '+(stageScenarios.find(s=>s.id===scenario)?.title||'the scenario')+' and resetting…';
    await new Promise(resolve=>setTimeout(resolve,1000));
    const snapshot=await api('state',undefined,'',scenario);
    if(snapshot.bacResetError)throw new Error(snapshot.bacResetError);
    reset={resetting:!!snapshot.bacResetting};
   }
   if(scope==='all'||scenario===selectedScenario)selectedJob=null;
   teamCleared=true;
  }
  // Automatically dismiss only after every agent's deletion is queued on the server.
  for(const agent of agents)await api('delete-agent',{name:agent.name},agent.key);
  if(agents.length){
   background=true;
   if(modal.open&&revision===dialogRevision&&el('settings-reset-panel')?.hidden===false)modal.close();
   alert('Removing '+agents.length+' agent'+(agents.length===1?'':'s')+'…','progress');
   await waitForAgentDeletions(agents,scenario);
  }else await refresh();
  if(scope!=='bac'){
   clearTimeout(comparisonTimer);comparison=null;comparePanel.replaceChildren();delete comparePanel.dataset.batch;
  }
  const confirmation=scope==='all'?'All stages reset.':scope==='bac'?(stageScenarios.find(s=>s.id===scenario)?.title||'Scenario')+' reset.':'Lounge agents reset.';
  if(sourceButton){status.hidden=true;status.textContent='';alert(confirmation,'success');}
  else status.textContent=confirmation;
  if(background)alert(agents.length+' agent'+(agents.length===1?'':'s')+' removed.','success');
 }catch(error){
  const message=(scope==='all'&&teamCleared?roomTitles.mission+' was reset. ':'')+error.message;
  try{applyDeletionSnapshot(await api('state',undefined,''));}catch{}
  if(background||(!sourceButton&&(!modal.open||revision!==dialogRevision)))alert(message,'error');
  // Refreshing controls while resetInProgress is true shows the busy notice.
  // Restore the failure afterward so the presenter can see why a retry is needed.
  status.textContent=message;
 }finally{
  resetInProgress=false;
  if(el('settings-status')&&el('settings-status')!==status&&!el('settings-reset-panel')?.hidden)el('settings-status').textContent=status.textContent;
  render(); // Release composer locks even when the next state poll returns 304.
  syncResetButtons();
  refresh();
 }
}


function openTeamSettings(){return openModelConnections();}
async function openModelConnections(){
 const request=++settingsOpenRequest,previousContent=el('dialog-body').firstElementChild;
 const wasOpen=el('dialog').open;
 let state,settings;
 try{[state,settings]=await Promise.all([api('settings/connections',undefined,''),api('settings',undefined,'')]);}
 catch(error){alert(error.message,'error');return;}
 // A native close event can arrive after the user has already reopened Settings.
 if(request!==settingsOpenRequest||el('dialog-body').firstElementChild!==previousContent||(wasOpen&&!el('dialog').open))return;
 const tabs=['model','location','reset'];
 const routeOptions=()=>`<option value="" disabled hidden>No connection ready</option><option value="local">Local</option><option value="api">External Endpoint</option>`;
 const scenarioRoute=(key,title)=>`<div class="connection-scenario"><div><label for="studio-route-${key}">${title}</label><span id="studio-connection-${key}-effective" class="connection-effective" role="status"></span></div><select id="studio-route-${key}" data-route="${key}" aria-describedby="studio-connection-${key}-effective">${routeOptions()}</select></div>`;
 dialog('Settings',`<form id="studio-config-form" novalidate>
  <nav class="connection-tabs" role="tablist" aria-label="Settings">${tabs.map((tab,index)=>`<button type="button" role="tab" id="studio-settings-${tab}-tab" data-connection-tab="${tab}" data-settings-tab="${tab}" aria-controls="studio-settings-${tab}-panel" aria-selected="${index===0}" tabindex="${index===0?0:-1}" ${index===0?'aria-current="page"':''}>${tab[0].toUpperCase()+tab.slice(1)}</button>`).join('')}</nav>
  <section id="studio-settings-model-panel" role="tabpanel" aria-labelledby="studio-settings-model-tab"><div id="studio-model-connections">
  <div class="connection-section-heading"><h3>Connections</h3><button type="button" class="connection-text-button" id="studio-connections-check">↻ Refresh</button></div>
  <div class="connection-grid">${['local','api'].map(source=>`<section class="connection-card" data-source="${source}"><header><label class="connection-toggle"><input type="checkbox" data-connection-enable="${source}"><strong>${source==='local'?'Local':'External Endpoint'}</strong></label><span data-connection-status="${source}" role="status"></span></header><div class="connection-card-details"><p data-connection-summary="${source}"></p><button type="button" class="connection-text-button" data-connection-edit="${source}">Configure</button></div></section>`).join('')}</div>
  <p id="studio-connections-status" role="status"></p>
  <div id="studio-connection-editor" hidden></div>
  <div class="connection-model-settings"><div class="connection-section-heading"><h3>Models</h3></div>
  <div class="connection-scenarios">${scenarioRoute('lounge','Hired agents')}${scenarioRoute('plan','Open Task')}</div>
  <div class="connection-footer"><button type="button" id="studio-connections-save" class="studio-primary">Save changes</button></div></div></div></section>
  ${settingsUtilityPanels()}
  <p id="studio-settings-status" role="status"></p><div class="studio-dialog-actions"><button type="button" id="studio-start-agents" class="studio-secondary" ${runtime.gateway?'hidden':''}>Start agents</button><button type="submit" class="studio-primary" id="studio-save-settings" hidden>Save location</button></div></form>`);
 const form=el('config-form');
 const panel=el('model-connections'),notice=el('connections-status'),owner=agentId,scenario=selectedScenario;
 let working=false,editing=false,inventoryRevision=0,tab='model';
 const current=()=>el('model-connections')===panel&&el('dialog').open&&agentId===owner&&selectedScenario===scenario;
 const prefs={lounge:state.loungePreference||'auto',plan:state.scenarioPreferences?.plan||'auto'};
 let savedPrefs={...prefs};
 const dirty=()=>Object.keys(prefs).some(key=>prefs[key]!==savedPrefs[key]);
 function routeState(kind){
  const preferred=prefs[kind]==='auto'?(kind==='lounge'?'local':'api'):prefs[kind],other=preferred==='local'?'api':'local';
  const effective=state.connections[preferred].ready?preferred:state.connections[other].ready?other:null;
  return {preferred,effective};
 }
 function showEffective(kind,target){
  if(!target)return;
  const {preferred,effective}=routeState(kind),pending=prefs[kind]!==savedPrefs[kind];
  const name=source=>source==='local'?'Local':'External Endpoint';
  const use=pending?'Save to use ':'Using ';
  const fallback=prefs[kind]!=='auto'&&effective!==preferred;
  target.textContent=!effective?'No connection ready':fallback?name(preferred)+' unavailable · '+use+name(effective):use+name(effective);
  target.dataset.state=!effective?'unavailable':fallback?'fallback':'ready';
 }
 function paint(){
  for(const source of ['local','api']){const c=state.connections[source],badge=panel.querySelector(`[data-connection-status="${source}"]`);badge.textContent=c.ready?'Ready':['Not configured','Disabled','Checking…'].includes(c.message)?c.message:'Unavailable';badge.title=c.message;badge.dataset.ready=String(c.ready);const summary=panel.querySelector(`[data-connection-summary="${source}"]`);summary.textContent=c.model?[c.provider==='local'?'':({nvidia:'NVIDIA NIM API',openai:'OpenAI',anthropic:'Anthropic'}[c.provider]),c.defaultLabel||c.model].filter(Boolean).join(' · '):source==='local'?'Connect a model running on your host.':'NVIDIA · OpenAI · Anthropic';summary.title=c.defaultLabel||c.model||'';const toggle=panel.querySelector(`[data-connection-enable="${source}"]`);if(!working)toggle.checked=c.enabled&&c.message!=='Not configured';toggle.disabled=working;}
  for(const select of panel.querySelectorAll('select[data-route]')){
   const kind=select.dataset.route,{effective}=routeState(kind);
   // Show the connection new work will use, without rewriting saved defaults on open/poll.
   // Keep an explicit unsaved selection visible until the presenter saves or changes it.
   select.value=effective?(prefs[kind]!==savedPrefs[kind]?prefs[kind]:effective):'';select.disabled=working||!effective;
   for(const option of select.options)option.disabled=!option.value||!state.connections[option.value].ready;
   showEffective(select.dataset.route,el('connection-'+select.dataset.route+'-effective'));
  }
  el('connections-save').disabled=working||!dirty();el('connections-check').disabled=working;
 }
 function changed(){notice.textContent=dirty()?'Unsaved changes':'';paint();}
 paint();
 for(const select of panel.querySelectorAll('select[data-route]'))select.onchange=()=>{if(working||!state.connections[select.value]?.ready)return;prefs[select.dataset.route]=select.value;changed();};
 async function refreshConnections(force=false){const revision=inventoryRevision;try{const next=await api('settings/connections'+(force?'/check':''),force?{}:undefined);if(current()&&revision===inventoryRevision&&!working){state=next;paint();}}catch(error){if(current())notice.textContent=error.message;}}
 const timer=setInterval(()=>{if(!current()){clearInterval(timer);return;}if(!working&&!editing)refreshConnections();},2500);
 el('connections-check').onclick=()=>refreshConnections(true);
 function selectTab(next){
  if(working)return;
  tab=next;el('dialog-body').scrollTop=0;
  for(const button of form.querySelectorAll('[data-settings-tab]')){
   const active=button.dataset.settingsTab===tab;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;
   if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
   el('settings-'+button.dataset.settingsTab+'-panel').hidden=!active;
  }
  el('save-settings').hidden=tab!=='location';
  el('start-agents').hidden=tab!=='model'||!!runtime.gateway;el('settings-status').textContent='';
  if(tab==='reset')syncResetButtons();
 }
 for(const button of form.querySelectorAll('[data-settings-tab]')){
  button.onclick=()=>selectTab(button.dataset.settingsTab);
  button.onkeydown=event=>{
   if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
   event.preventDefault();if(working)return;
   selectTab(event.key==='Home'?tabs[0]:event.key==='End'?tabs.at(-1):tabs[(tabs.indexOf(tab)+(event.key==='ArrowLeft'?-1:1)+tabs.length)%tabs.length]);
   el('settings-'+tab+'-tab').focus();
  };
 }
 el('location-city').value=settings.location?.city||'Zurich';
 el('agent-reset').onclick=()=>resetStudio('lounge');for(const button of el('settings-reset-panel').querySelectorAll('[data-reset-scenario]'))button.onclick=()=>resetStudio('bac',null,button.dataset.resetScenario);el('reset-all').onclick=()=>resetStudio('all');syncResetButtons();
 async function utilityAction(action){
  if(working||!current())return;
  working=true;paint();
  const controls=[...form.querySelectorAll('#studio-settings-location-panel input,#studio-save-settings,#studio-start-agents')].map(node=>[node,node.disabled]);
  controls.forEach(([node])=>node.disabled=true);const status=el('settings-status');
  try{await action(status);}catch(error){if(current())status.textContent=error.message;}
  finally{working=false;if(current()){controls.forEach(([node,disabled])=>node.disabled=disabled);paint();}}
 }
 el('start-agents').onclick=()=>utilityAction(async status=>{status.textContent='Starting agent runtime…';await api('settings/start',{});await waitForAgentRuntime();if(current()){el('start-agents').hidden=true;status.textContent=runtime.ready?'Model and agent runtime connected.':'Agent runtime ready. Connect a model to continue.';}});
 form.onsubmit=event=>{
  event.preventDefault();if(working||tab!=='location')return;
  const field=el('location-city');if(!field.checkValidity()){field.reportValidity();return;}
  const city=field.value.trim();
  utilityAction(async status=>{status.textContent='Saving location…';const saved=await api('settings',{section:'location',location:{city}});settings.location=saved.location;runtime.location=saved.location;if(current()){field.value=saved.location.city;status.textContent='Saved. Applies to every agent’s next request.';}});
 };
 el('connections-save').onclick=async()=>{if(working||!dirty())return;working=true;++inventoryRevision;paint();notice.textContent='Applying…';try{
  const changes={};
  if(prefs.lounge!==savedPrefs.lounge)changes.lounge=prefs.lounge;
  if(prefs.plan!==savedPrefs.plan)changes.scenarios={plan:prefs.plan};
  const result=await api('settings/connections/preferences',changes,owner);if(!current())return;state=result;savedPrefs={...prefs};
  ++refreshVersion;stateCache.clear();data.teamConnection=result.teamConnection;runtime=await api('runtime',undefined,'');if(!current())return;render();notice.textContent='Saved. Applies to new requests.';
 }catch(error){if(current())notice.textContent=error.message;}finally{working=false;if(current())paint();}};
 for(const toggle of panel.querySelectorAll('[data-connection-enable]'))toggle.onchange=async()=>{
  if(working)return;const source=toggle.dataset.connectionEnable,on=toggle.checked;
  if(on&&state.connections[source].message==='Not configured'){editConnection(source);paint();return;}
  working=true;++inventoryRevision;paint();try{state=await api('settings/connections/preferences',{[on?'enable':'disable']:source},owner);runtime=await api('runtime',undefined,'');if(current()){runtimeBadge();notice.textContent=on?'Enabled.':'Disabled.';}}catch(error){if(current())notice.textContent=error.message;}finally{working=false;if(current()){paint();await refresh();}}
 };
 for(const button of panel.querySelectorAll('[data-connection-edit]'))button.onclick=()=>editConnection(button.dataset.connectionEdit);
 function editConnection(source){
  if(working)return;editing=true;const editor=el('connection-editor');editor.hidden=false;
  editor.innerHTML=`<h3>${source==='local'?'Local model':'API connection'}</h3>
   ${source==='api'?`<div class="connection-credentials"><label>Provider<select id="studio-connect-provider"><option value="nvidia">NVIDIA NIM API</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic (Claude)</option></select></label><label>Endpoint<input id="studio-connect-url" type="url"></label></div>
   <div class="connection-key-heading"><label for="studio-connect-key">API key</label><a id="studio-get-nvidia-key" href="https://build.nvidia.com/settings/api-keys" target="_blank" rel="noopener noreferrer" hidden>Get an NVIDIA API key</a></div><input id="studio-connect-key" type="password" autocomplete="off"><small id="studio-connect-key-status"></small>`:'<div class="connection-field-row"><label for="studio-connect-url">Endpoint</label><input id="studio-connect-url" type="url"></div>'}
   <div id="studio-connect-selection" ${source==='api'?'hidden':''}><div class="connection-field-row connection-model-field"><label for="studio-connect-model">Model</label><div><input id="studio-connect-model" autocomplete="off" placeholder="Search models…" aria-controls="studio-connect-model-results"><datalist id="studio-connect-models"></datalist><div id="studio-connect-model-results" class="studio-agent-model-results" role="group" aria-label="Available endpoint models"></div></div></div>
   <div id="studio-connect-routing" hidden></div></div>
   <p id="studio-connect-status" role="status"></p>
   <div class="connection-editor-bottom"><details><summary>Advanced</summary><label for="studio-connect-context">Context limit · tokens</label><input id="studio-connect-context" type="number" min="8192" max="2000000" step="1" required><small>Instructions, conversation, tool results and reply. Must fit the model endpoint.</small></details><div class="studio-dialog-actions"><button type="button" class="studio-secondary" id="studio-connect-cancel">Close</button><button type="button" class="studio-primary" id="studio-connect-apply">Connect &amp; enable</button></div></div>`;
  const provider=()=>source==='local'?'local':el('connect-provider').value;
  let catalogVersion=0,catalogLoaded=false,catalogPending=false,catalogModels=[],catalogFilter='',automaticInfo=null,routingDraft=null;
  const automaticLabel='Model routing (NeMo Switchyard)';
  const selectedModel=()=>el('connect-model').value.trim()===automaticLabel?'auto':el('connect-model').value.trim();
  const setModel=id=>{el('connect-model').value=id==='auto'?automaticLabel:id;};
  function renderRouting(){
   const box=el('connect-routing');box.hidden=selectedModel()!=='auto'||provider()!=='nvidia';if(box.hidden){box.replaceChildren();return;}
   if(!routingDraft||!automaticInfo?.defaults){box.textContent='Loading routing models…';return;}
   const defaults=automaticInfo.defaults,custom=Object.keys(defaults).some(key=>routingDraft[key]!==defaults[key]);
   const rows=[['router','Router','Routes tasks to Efficient or Capable'],['efficient','Efficient','Lighter tasks'],['capable','Capable','More demanding tasks']];
   box.innerHTML='<div class="switchyard-editor"><div class="switchyard-editor-heading"><strong>Routing models</strong><button type="button" class="switchyard-reset" '+(custom?'':'disabled')+'>Use defaults</button></div>'+rows.map(([key,label,note])=>'<div class="switchyard-edit-row"><div><strong>'+label+'</strong><small>'+note+'</small></div><button type="button" data-routing-role="'+key+'" '+(catalogModels.length?'':'disabled')+' title="'+escape(routingDraft[key])+'" aria-label="'+label+' model" aria-expanded="false"><span>'+escape(routingModelLabel(routingDraft[key]))+'</span><span aria-hidden="true">⌄</span></button></div>').join('')+'<p class="switchyard-notice" role="status" '+(custom?'':'hidden')+'>Warning: This model combination has not been tested with this demo.</p></div>';
   box.querySelector('.switchyard-reset').onclick=()=>{routingDraft={...defaults};renderRouting();};
   for(const button of box.querySelectorAll('[data-routing-role]'))button.onclick=()=>{
    const wasOpen=button.getAttribute('aria-expanded')==='true';box.querySelector('.switchyard-picker')?.remove();box.querySelectorAll('[data-routing-role]').forEach(b=>b.setAttribute('aria-expanded','false'));if(wasOpen)return;
    button.setAttribute('aria-expanded','true');const picker=document.createElement('div');picker.className='switchyard-picker';picker.innerHTML='<input type="search" autocomplete="off" placeholder="Search NVIDIA models…" aria-label="Search '+button.dataset.routingRole+' models"><div class="studio-agent-model-results" role="group" aria-label="Routing model choices"></div>';
    button.closest('.switchyard-edit-row').after(picker);const input=picker.querySelector('input'),results=picker.querySelector('.studio-agent-model-results');
    const paintChoices=()=>{const q=input.value.trim().toLowerCase(),selected=routingDraft[button.dataset.routingRole];const matches=catalogModels.filter(m=>(m.id+' '+(m.name||'')).toLowerCase().includes(q)).sort((a,b)=>Number(b.id===selected)-Number(a.id===selected)||Number(b.id.includes('nemotron'))-Number(a.id.includes('nemotron'))||a.id.localeCompare(b.id));results.innerHTML=matches.slice(0,40).map(m=>'<button type="button" data-routing-choice="'+escape(m.id)+'" aria-pressed="'+(m.id===selected)+'"><span><strong>'+escape(routingModelLabel(m.id))+'</strong><small>'+escape(m.id)+'</small></span>'+(m.id===selected?'<small>Selected</small>':'')+'</button>').join('')||'<small>No matching models.</small>';};
    input.oninput=paintChoices;picker.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();picker.remove();button.setAttribute('aria-expanded','false');button.focus();}};
    results.onclick=e=>{const choice=e.target.closest('[data-routing-choice]');if(choice){const role=button.dataset.routingRole;routingDraft[role]=choice.dataset.routingChoice;renderRouting();box.querySelector('[data-routing-role="'+role+'"]').focus();}};paintChoices();input.focus();
   };
   box.onfocusout=()=>setTimeout(()=>{if(!box.contains(document.activeElement)){box.querySelector('.switchyard-picker')?.remove();box.querySelectorAll('[data-routing-role]').forEach(b=>b.setAttribute('aria-expanded','false'));}},0);
  }
  // A connection may be ready using another tab's key. Only this tab's key
  // or a host-saved key can be reused by the connection editor.
  const endpointValue=value=>(value||'').trim().replace(/\/+$/,'');
  function keySource(){
   const id=provider(),base=endpointValue(el('connect-url').value),saved=settings.profiles[id],file=settings.fileKeys?.[id],active=state.connections.api;
   if(saved?.hasKey&&base===endpointValue(saved.baseUrl))return 'session';
   if(file?.hasKey&&base===endpointValue(file.baseUrl))return 'api.json';
   if(active.provider===id&&base===endpointValue(active.baseUrl)&&active.keySource==='host')return active.keySource;
   return '';
  }
  function lockFields(){
   el('connect-url').disabled=source==='api'&&provider()!=='nvidia';
   const input=el('connect-key');if(!input)return;
   const base=endpointValue(el('connect-url').value);
   el('get-nvidia-key').hidden=provider()!=='nvidia'||base!==endpointValue(settings.providers.nvidia.baseUrl);
   const origin=keySource(),active=state.connections.api;
   const verified=active.ready&&active.provider===provider()&&endpointValue(active.baseUrl)===endpointValue(el('connect-url').value);
   input.disabled=!!origin&&(origin==='api.json'||verified);
   const labels={'api.json':'API key configured · api.json',host:'API key verified · saved on host',session:'API key verified · this session'};
   input.placeholder=input.disabled?labels[origin]:'Enter API key';
   el('connect-key-status').textContent=origin?'':'Key expires when this tab reloads or closes.';
  }
  function showConnectionStep(){
   if(source!=='api')return;
   el('connect-selection').hidden=!catalogLoaded;
   const apply=el('connect-apply');
   apply.textContent=catalogLoaded?'Use model':catalogPending?'Connecting…':'Connect';
   const hasCredentials=el('connect-url').value.trim()&&(el('connect-key').value.trim()||keySource());
   apply.disabled=working||catalogPending||!(catalogLoaded?selectedModel():hasCredentials);
  }
  function renderCatalog(){
   const query=catalogFilter.trim().toLowerCase(),selected=selectedModel();
   renderRouting();
   const displayName=model=>(model.name||model.id).split('/').at(-1);
   const nemotron=model=>(model.name+' '+model.id).toLowerCase().includes('nemotron');
   const options=source==='api'&&provider()==='nvidia'&&automaticInfo?.roles?.length?[{id:'auto',name:automaticLabel},...catalogModels]:catalogModels;
   const matches=options.filter(model=>(model.name+' '+model.id).toLowerCase().includes(query)).sort((a,b)=>Number(b.id==='auto')-Number(a.id==='auto')||Number(nemotron(b))-Number(nemotron(a))||displayName(a).localeCompare(displayName(b))||a.id.localeCompare(b.id));
   el('connect-model-results').innerHTML=matches.slice(0,40).map(model=>`<button type="button" data-connect-model-choice="${escape(model.id)}" aria-pressed="${model.id===selected}" title="${escape(model.name)}"><span><strong>${escape(displayName(model))}</strong><small>${escape(model.id==='auto'?switchyardDescription(automaticInfo):model.id)}</small></span><span class="studio-model-choice-state">${model.id===selected?'Selected':'External Endpoint'}</span></button>`).join('')||(catalogModels.length?'<p class="studio-model-empty">No matching models</p>':'');
  }
  const fill=()=>{const id=provider(),profile=settings.profiles[id]||{},file=settings.fileKeys?.[id],active=state.connections[source];
   const base=(profile.hasKey&&profile.baseUrl)||(active.provider===id&&active.baseUrl)||file?.baseUrl||profile.baseUrl||settings.providers[id].baseUrl;
   el('connect-url').value=base;
   const savedModel=endpointValue(profile.baseUrl)===endpointValue(base)?profile.model:'';
   setModel((active.provider===id&&endpointValue(active.baseUrl)===endpointValue(base)?active.defaultModel||active.model:'')||(id==='nvidia'?'auto':savedModel)||'');
   automaticInfo=id==='nvidia'&&active.provider===id&&endpointValue(active.baseUrl)===endpointValue(base)?active.automatic:null;routingDraft=automaticInfo?.configuration?{...automaticInfo.configuration}:null;el('connect-context').value=profile.contextWindow||(active.provider===id?active.contextWindow:0)||32768;if(el('connect-key'))el('connect-key').value='';el('connect-models').innerHTML='';catalogModels=[];catalogFilter='';renderCatalog();lockFields();};
  if(source==='api')el('connect-provider').value=state.connections.api.provider;
  fill();
  const payload=()=>({source,provider:provider(),apiKey:el('connect-key')?.value.trim()||'',baseUrl:el('connect-url').value.trim(),model:selectedModel(),contextWindow:Number(el('connect-context').value),...(provider()==='nvidia'&&selectedModel()==='auto'&&routingDraft?{routingModels:{...routingDraft}}:{})});
  el('connect-cancel').onclick=()=>{if(!working){editor.replaceChildren();editor.hidden=true;editing=false;}};
  async function action(){if(working)return;const context=el('connect-context');if(!context.checkValidity()){context.closest('details').open=true;context.reportValidity();return;}working=true;++inventoryRevision;paint();const values=payload(),message=el('connect-status');editor.querySelectorAll('input,select,button').forEach(e=>e.disabled=true);message.textContent='Checking connection…';try{
   const result=await api('settings/connections',values,owner);if(!current()||!editor.contains(message))return;
   {state=result;settings.profiles[values.provider]={baseUrl:values.baseUrl,model:result.connections[source].model,contextWindow:values.contextWindow,hasKey:source==='api'&&result.connections[source].keySource==='session'};if(el('connect-key'))el('connect-key').value='';runtime=await api('runtime',undefined,'');if(current()){runtimeBadge();await refresh();paint();message.textContent='Connected.';}}
  }catch(error){if(current())message.textContent=error.message;}finally{working=false;if(current()){editor.querySelectorAll('input,select,button').forEach(e=>e.disabled=false);lockFields();showConnectionStep();paint();}}}
  async function loadCatalog(focusModel=false){
   if(working||catalogLoaded||catalogPending)return;
   const values=payload();
   if(source==='api'&&!values.apiKey&&!keySource())return;
   const version=++catalogVersion,message=el('connect-status'),list=el('connect-models');
   catalogPending=true;showConnectionStep();message.textContent='Loading models…';
   try{
    const result=await api('settings/connections/models',values,owner);
    if(!current()||!editor.contains(list)||version!==catalogVersion)return;
    catalogModels=result.models;automaticInfo=result.automatic||null;routingDraft=automaticInfo?.configuration?{...automaticInfo.configuration}:null;
    catalogLoaded=catalogModels.length>0;
    if(source==='api'){
     const preferred=result.defaultModel||selectedModel();
     if(preferred==='auto'&&automaticInfo?.available)setModel('auto');
     else if(catalogModels.some(m=>m.id===preferred))setModel(preferred);
     else setModel(catalogModels.length===1?catalogModels[0].id:'');
    }
    list.replaceChildren(...catalogModels.map(m=>new Option(m.name||m.id,m.id)));renderCatalog();showConnectionStep();
    message.textContent=catalogLoaded?'':'No compatible models found. Check the endpoint or context limit.';
    if(focusModel&&catalogLoaded&&[el('connect-key'),el('connect-apply'),document.body].includes(document.activeElement))el('connect-model').focus();
   }catch(error){if(current()&&editor.contains(message)&&version===catalogVersion)message.textContent=error.message;}
   finally{if(current()&&editor.contains(list)&&version===catalogVersion){catalogPending=false;showConnectionStep();}}
  }
  function invalidateCatalog(){
   ++catalogVersion;catalogLoaded=false;catalogPending=false;catalogModels=[];catalogFilter='';automaticInfo=null;routingDraft=null;
   setModel('');el('connect-models').replaceChildren();el('connect-status').textContent='';
  }
  function openCatalogIfConnected(){
   showConnectionStep();
   const active=state.connections[source];
   if(source==='local'||(active.ready&&active.provider===provider()&&endpointValue(active.baseUrl)===endpointValue(el('connect-url').value)&&keySource()))loadCatalog();
  }
  el('connect-model').onfocus=()=>{el('connect-model').select();if(source==='local')loadCatalog();};
  el('connect-model').oninput=()=>{catalogFilter=el('connect-model').value;renderCatalog();showConnectionStep();};
  el('connect-model-results').onclick=event=>{const button=event.target.closest('[data-connect-model-choice]');if(button){setModel(button.dataset.connectModelChoice);catalogFilter='';renderCatalog();showConnectionStep();}};
  if(el('connect-provider'))el('connect-provider').onchange=()=>{invalidateCatalog();fill();openCatalogIfConnected();};
  for(const id of ['connect-key','connect-url'])if(el(id))el(id).oninput=()=>{
   invalidateCatalog();
   if(id==='connect-url'&&el('connect-key'))el('connect-key').value='';
   lockFields();renderCatalog();showConnectionStep();
  };
  if(source==='local')el('connect-url').onchange=()=>loadCatalog();
  else el('connect-key').onkeydown=event=>{
   if(event.key==='Enter'){event.preventDefault();if(!catalogLoaded&&!el('connect-apply').disabled)el('connect-apply').click();}
  };
  el('connect-apply').onclick=()=>{
   if(source==='api'&&!catalogLoaded){
    const context=el('connect-context');
    if(!context.checkValidity()){context.closest('details').open=true;context.reportValidity();return;}
    loadCatalog(true);return;
   }
   ++catalogVersion;catalogPending=false;action();
  };
  openCatalogIfConnected();
 }
}
