// SPDX-License-Identifier: Apache-2.0

// Keep live panels (and their event handlers) inside the fullscreen root.
const surfaceStore=document.createElement('div');surfaceStore.id='studio-surface-store';surfaceStore.hidden=true;root.append(surfaceStore);
const surfaceDialog=document.createElement('dialog');surfaceDialog.id='studio-surface';surfaceDialog.setAttribute('aria-labelledby','studio-surface-title');
surfaceDialog.innerHTML='<header><div class="studio-surface-heading"><h2 id="studio-surface-title"></h2><p id="studio-surface-task" hidden></p></div><button type="button" class="studio-secondary" id="studio-surface-close" aria-label="Close panel">×</button></header><div id="studio-surface-body"></div>';
root.append(surfaceDialog);
dismissOnBackdrop(surfaceDialog);
let activeSurface=null;
// A policy review is a child dialog: keep the live Mission Control DOM in place.
const policyOverlay=document.createElement('dialog');policyOverlay.id='studio-policy-overlay';policyOverlay.setAttribute('aria-labelledby','studio-policy-overlay-title');
policyOverlay.innerHTML='<header><h2 id="studio-policy-overlay-title">OpenShell Policy</h2><button type="button" class="studio-secondary" id="studio-policy-overlay-close" aria-label="Close policy">×</button></header><div id="studio-policy-overlay-body"></div>';
root.append(policyOverlay);dismissOnBackdrop(policyOverlay);
let policyReturnFocus=null;
function openPolicyOverlay(){
 policyReturnFocus=document.activeElement;
 const panel=el('policy-panel');el('policy-overlay-body').append(panel);panel.hidden=false;panel.open=true;
 loadPolicy();if(!policyOverlay.open)policyOverlay.showModal();
}
function closePolicyOverlay(){if(policyOverlay.open)policyOverlay.close();}
el('policy-overlay-close').onclick=closePolicyOverlay;
policyOverlay.addEventListener('close',()=>{
 if(policyOverlay.open)return;
 const panel=el('policy-panel');
 if(panel.parentElement===el('policy-overlay-body')){
  surfaceStore.append(panel);panel.open=false;clearTimeout(policyRefreshTimer);policyRefreshTimer=null;
 }
 if(surfaceDialog.open&&activeSurface==='control'&&policyReturnFocus?.isConnected)policyReturnFocus.focus({preventScroll:true});
 policyReturnFocus=null;
});
const taskOverlay=document.createElement('dialog');taskOverlay.id='studio-task-overlay';taskOverlay.setAttribute('aria-labelledby','studio-task-overlay-title');
taskOverlay.innerHTML='<header><h2 id="studio-task-overlay-title"></h2><button type="button" class="studio-secondary" id="studio-task-overlay-close" aria-label="Close task description">×</button></header><div id="studio-task-overlay-body"></div>';
root.append(taskOverlay);dismissOnBackdrop(taskOverlay);
let taskReturnFocus=null;
function openTaskOverlay(example,job,trigger){
  if(!example)return;
  taskReturnFocus=trigger||document.activeElement;
  el('task-overlay-title').textContent=example.title;
  el('task-overlay-body').innerHTML='<p class="studio-task-description">'+escape(example.detail||'Predefined Open Task scenario.')+'</p><h3>Task request</h3><pre class="studio-task-prompt">'+escape(job?.payload?.prompt||goalPrompt(example))+'</pre>';
  if(!taskOverlay.open)taskOverlay.showModal();
}
function closeTaskOverlay(){if(taskOverlay.open)taskOverlay.close();}
el('task-overlay-close').onclick=closeTaskOverlay;
taskOverlay.addEventListener('close',()=>{
  if(surfaceDialog.open&&taskReturnFocus?.isConnected)taskReturnFocus.focus({preventScroll:true});
  taskReturnFocus=null;
});
const planResults=document.createElement('section');planResults.id='studio-plan-results';planResults.className='studio-plan-results';planResults.hidden=true;surfaceStore.append(planResults);
planResults.onclick=event=>{const file=event.target.closest('[data-plan-file]');if(file)openFile(file.dataset.planFile,file.dataset.planJob);};
function renderPlanResults(job){
 if(!job){planResults.innerHTML='';delete planResults.dataset.key;return;}
 const plan=job.payload.collaboration,answer=collaborationAnswer(job);
 const total=planResults.querySelector('[data-plan-total]');if(total)total.textContent=collaborationTime(job);
 const files=[...new Set([...(job.result?.files||[]),...Object.values(plan.webpages||{}).flat(),...Object.values(plan.outputs||{}).flatMap(output=>output.files||[]),...(plan.revision?.output?.files||[])])];
 const key=JSON.stringify([job.id,job.status,answer,files,plan]);
 if(planResults.dataset.key===key)return;
 planResults.dataset.key=key;
 const status=['queued','running','waiting','stopping'].includes(job.status)?'Work is in progress. Saved results appear here as the team finishes.':job.status==='error'?'This request did not finish. Any saved files are available below.':'No final response was saved for this request.';
 planResults.innerHTML='<header class="studio-result-heading"><small>Task</small><p>'+escape(plan.task||job.payload.prompt||'')+'</p>'+collaborationTimeMarkup(job)+'</header><div class="chat-prose">'+messageMarkup(answer||status)+'</div>'+collaborationCompletionMarkup(plan,answer)+(files.length?'<section class="studio-result-files" aria-label="Saved files"><h3>Saved files</h3>'+webpageButtons(files,job.id)+collaborationFileButtons(files,job.id,'Open saved file')+'</section>':'');
}

const usageTime=document.createElement('section');usageTime.id='studio-usage-time';usageTime.className='studio-usage-time';usageTime.hidden=true;surfaceStore.append(usageTime);
function usageNumber(value){return typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;}
function usageDuration(seconds){
 const value=usageNumber(seconds);if(value===null)return '—';
 const rounded=Math.round(value),hours=Math.floor(rounded/3600),minutes=Math.floor(rounded%3600/60),secs=rounded%60;
 return hours?hours+'h '+minutes+'m '+secs+'s':minutes?minutes+'m '+secs+'s':value<1?value.toFixed(1)+'s':secs+'s';
}
function scenarioTaskSummary(job){
 const prompt=job?.payload?.collaboration?.task||job?.payload?.prompt;
 if(prompt)return String(prompt).replace(/^\s*\/(?:goals?|plans?)(?=\s|$)/i,'').trim();
 return 'No task summary was saved for this run.';
}
function scenarioUsageSummary(job){
 const records=Object.values(job?.payload?.metrics||{}).filter(record=>record&&typeof record==='object'),agents=new Map();
 let input=0,output=0,total=0,apiSeconds=0,inputReported=false,outputReported=false,totalReported=false,timeReported=false,unreportedCalls=0;
 for(const record of records){
  const recordInput=usageNumber(record.input),recordOutput=usageNumber(record.output);
  const recordTotal=usageNumber(record.total)??(recordInput!==null&&recordOutput!==null?recordInput+recordOutput:null);
  const seconds=usageNumber(record.runSeconds),key=record.agent||record.name||'unknown';
  if(!agents.has(key))agents.set(key,{name:record.name||'Unknown agent',models:new Set(),endpoints:new Set(),input:0,output:0,total:0,seconds:0,calls:0,inputReported:false,outputReported:false,totalReported:false,timeReported:false});
  const agent=agents.get(key);agent.calls++;
  if(typeof record.endpoint==='string'&&record.endpoint)agent.endpoints.add(record.endpoint);
  if(typeof record.model==='string'&&record.model)agent.models.add(record.model);
  if(recordInput!==null){input+=recordInput;agent.input+=recordInput;inputReported=agent.inputReported=true;}
  if(recordOutput!==null){output+=recordOutput;agent.output+=recordOutput;outputReported=agent.outputReported=true;}
  if(recordTotal!==null){total+=recordTotal;agent.total+=recordTotal;totalReported=agent.totalReported=true;}
  if(recordInput===null||recordOutput===null||recordTotal===null)unreportedCalls++;
  if(seconds!==null){apiSeconds+=seconds;agent.seconds+=seconds;timeReported=agent.timeReported=true;}
 }
 const start=usageNumber(job?.created),end=usageNumber(job?.updated);
 return {records,agents:[...agents.values()],input,output,total,apiSeconds,inputReported,outputReported,totalReported,timeReported,unreportedCalls,elapsed:start!==null&&end!==null?Math.max(0,end-start):null};
}
function renderUsageTime(job){
 if(!job){usageTime.innerHTML='';delete usageTime.dataset.key;return;}
 const summary=scenarioUsageSummary(job),key=JSON.stringify([job.id,job.status,job.updated,job.payload?.metrics,job.payload?.prompt,job.payload?.brief,job.payload?.collaboration?.task]);
 if(usageTime.dataset.key===key)return;usageTime.dataset.key=key;
 const amount=(value,reported)=>reported?Math.round(value).toLocaleString():'—';
 const rows=summary.agents.map(agent=>{
  const models=[...agent.models],endpoints=[...agent.endpoints];
  const label=models.map(id=>(runtime.teamModels||[]).find(model=>model.id===id)?.label||id.split('/').pop()).join(', ')||'Model not reported';
  const connection='<details class="studio-usage-connection"><summary aria-label="'+escape(agent.name)+' model and connection"><span>'+escape(agent.name)+'</span><small>'+escape(label)+'</small></summary><dl><dt>Model</dt><dd>'+escape(models.join(', ')||'Not reported')+'</dd><dt>Connection</dt><dd>'+escape(endpoints.join(', ')||'Not reported')+'</dd></dl></details>';
  return '<tr><th scope="row">'+connection+'</th><td data-label="Input">'+amount(agent.input,agent.inputReported)+'</td><td data-label="Output">'+amount(agent.output,agent.outputReported)+'</td><td data-label="Total" class="studio-usage-combined">'+amount(agent.total,agent.totalReported)+'</td><td data-label="Time">'+usageDuration(agent.timeReported?agent.seconds:null)+'<small class="studio-usage-turns">'+agent.calls+' turn'+(agent.calls===1?'':'s')+'</small></td></tr>';
 }).join('');
 const warning=summary.unreportedCalls?'<p class="studio-usage-note">'+summary.unreportedCalls+' recorded agent turn'+(summary.unreportedCalls===1?' did':'s did')+' not report token counts, so token totals are partial.</p>':'';
 usageTime.innerHTML='<section class="studio-usage-task"><small>Task</small><p>'+escape(scenarioTaskSummary(job))+'</p></section>'+
  '<div class="studio-usage-totals"><article><small>Total tokens</small><strong>'+amount(summary.total,summary.totalReported)+'</strong><p><span>Input '+amount(summary.input,summary.inputReported)+'</span><span>Output '+amount(summary.output,summary.outputReported)+'</span></p></article><article><small>Total elapsed</small><strong>'+usageDuration(summary.elapsed)+'</strong><p>From start to finish</p></article><article><small>Combined agent time</small><strong>'+usageDuration(summary.timeReported?summary.apiSeconds:null)+'</strong><p>'+summary.records.length+' recorded turn'+(summary.records.length===1?'':'s')+'</p></article></div>'+
  (rows?'<div class="studio-usage-section-heading"><h3>By agent</h3><span>Expand an agent for connection details</span></div><div class="studio-usage-table-wrap"><table aria-label="Usage and time by agent"><thead><tr><th scope="col">Agent / model</th><th scope="col">Input</th><th scope="col">Output</th><th scope="col">Total</th><th scope="col">Time</th></tr></thead><tbody>'+rows+'</tbody></table></div>':'<p class="studio-usage-note">No usage reported for this run.</p>')+
  warning+'<p class="studio-usage-note">Agent time includes tools; parallel work can exceed total elapsed time. Recorded responses only.</p>';
}

const surfaceDefinitions={
  missions:{title:'Try a mission',ids:['experiences']},
  results:{title:'Results & files',ids:['workspace']},
  compare:{title:'Agent comparison',ids:['compare']},
  policies:{title:'OpenShell Policy',ids:['policy-panel']},
  control:{title:'Mission Control',ids:['board']},
  deliverables:{title:'Results',ids:['plan-results']},
  usage:{title:'Usage & time',ids:['usage-time']}
};
for(const id of ['board','workspace','experiences','policy-panel','connections'])surfaceStore.append(el(id));
el('passport').prepend(el('collection'));
el('collection-note').hidden=true;
const loungeActions=document.createElement('div');loungeActions.className='studio-panel-actions';loungeActions.innerHTML='<button type="button" class="studio-secondary" id="studio-compare-open" data-surface="compare" hidden>Compare replies</button>';
el('passport').append(loungeActions);
for(const node of [el('companion').querySelector('.studio-agent-extras'),el('companion').querySelector('.studio-native-note')])surfaceStore.append(node);
const crewActions=document.createElement('div');crewActions.className='studio-team-actions';crewActions.setAttribute('aria-label','Team actions');
el('crew-passport').prepend(crewActions);crewActions.append(el('room-action'));el('room-action').classList.add('studio-team-start');
el('crew-passport').append(document.getElementById('campus-roster'));
const controlButton=document.createElement('button');controlButton.type='button';controlButton.className='studio-secondary';controlButton.dataset.surface='control';controlButton.innerHTML='<span>Mission Control</span><span class="mission-attention-mark" aria-hidden="true" hidden>!</span>';crewActions.append(controlButton);
const teamResetButton=document.createElement('button');teamResetButton.type='button';teamResetButton.id='studio-bac-reset';teamResetButton.className='studio-team-utility';teamResetButton.innerHTML='<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 7a6 6 0 1 1-.2 5M4 3v4h4"/></svg><span>Reset</span>';teamResetButton.setAttribute('aria-label','Reset current scenario');teamResetButton.title='Stop this scenario’s work and clear its chats, documents and results';teamResetButton.onclick=()=>confirmTeamReset(teamResetButton);
const teamResetStatus=document.createElement('p');teamResetStatus.id='studio-team-reset-status';teamResetStatus.className='studio-muted';teamResetStatus.setAttribute('role','status');teamResetStatus.hidden=true;crewActions.after(teamResetStatus);
const resultsButton=document.createElement('button');resultsButton.type='button';resultsButton.className='studio-secondary';resultsButton.dataset.surface='deliverables';resultsButton.textContent='Results';resultsButton.hidden=true;crewActions.append(resultsButton);
const usageTimeButton=document.createElement('button');usageTimeButton.type='button';usageTimeButton.className='studio-secondary';usageTimeButton.dataset.surface='usage';usageTimeButton.textContent='Usage & time';usageTimeButton.hidden=true;crewActions.append(usageTimeButton);
const teamTotalTime=document.createElement('div');teamTotalTime.id='studio-team-total-time';teamTotalTime.hidden=true;teamTotalTime.setAttribute('role','timer');teamTotalTime.title='Total process time, including queueing, planning, specialists and review';el('crew-name').parentElement.classList.add('studio-captain-heading');el('crew-name').after(teamTotalTime);
const teamConnectionBar=document.createElement('div');teamConnectionBar.className='studio-team-connection-bar';teamConnectionBar.innerHTML='<span class="studio-team-connection-state" role="status"><i aria-hidden="true"></i><span id="studio-team-connection-label">Team API</span></span><div class="studio-team-utilities"><button type="button" class="studio-team-utility" id="studio-team-setup" aria-haspopup="dialog"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 6h3m4 0h7M3 14h7m4 0h3"/><circle cx="8" cy="6" r="2"/><circle cx="12" cy="14" r="2"/></svg><span>Models &amp; connection</span></button></div>';teamConnectionBar.querySelector('.studio-team-utilities').append(teamResetButton);crewActions.after(teamConnectionBar);el('team-setup').onclick=openTeamSettings;
const localTaskWarning=document.createElement('p');localTaskWarning.id='studio-local-task-warning';localTaskWarning.className='studio-local-task-warning';localTaskWarning.setAttribute('role','status');localTaskWarning.hidden=true;localTaskWarning.textContent='Local model selected for Open Task. Tasks may take longer, and complex requests may not produce the expected results. An external endpoint is recommended.';teamConnectionBar.after(localTaskWarning);
const standbyPanel=document.createElement('details');standbyPanel.id='studio-standby';
standbyPanel.innerHTML='<summary>Standby specialists <span id="studio-standby-count"></span></summary><div class="studio-standby-content"><ul id="studio-standby-list"></ul></div>';
teamConnectionBar.after(standbyPanel);
function fitStandbyPanel(){
 if(!standbyPanel.open)return;
 const top=standbyPanel.querySelector('.studio-standby-content').getBoundingClientRect().top;
 const composer=el('crew-chat').getBoundingClientRect();
 standbyPanel.style.setProperty('--standby-space',Math.max(60,Math.min(340,composer.top-top-12))+'px');
}
standbyPanel.addEventListener('toggle',fitStandbyPanel);
window.addEventListener('resize',fitStandbyPanel);
// Capture outside clicks even when another control stops event propagation.
document.addEventListener('click',event=>{
  if(standbyPanel.open&&!standbyPanel.contains(event.target))standbyPanel.open=false;
},true);
standbyPanel.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&standbyPanel.open){
    standbyPanel.open=false;standbyPanel.querySelector('summary').focus();event.stopPropagation();
  }
});
function openTaskName(job){
  const example=goalExamples.find(choice=>choice.id===job?.payload?.goalExample);
  return example?.title||"free user's entry";
}
function syncSurfaceTask(){
  const node=el('surface-task');
  const job=activeSurface==='control'?missionControlPlan():activeSurface==='deliverables'?currentCollaboration():null;
  const example=goalExamples.find(choice=>choice.id===job?.payload?.goalExample);
  node.hidden=!job;
  node.innerHTML=job?'Current Mission = '+(example?'<a href="#studio-goal-example-'+escape(example.id)+'" data-current-task-example="'+escape(example.id)+'">'+escape(example.title)+'</a>':'<strong>'+escape(openTaskName(job))+'</strong>'):'';
}
// Show the active scenario's total time beside its coordinator.
function syncTeamTotalTime(){
  const timer=el('team-total-time'),plan=currentCollaboration();
  const label=plan&&selectedCrewRole===0&&!selectedOpenTaskVisitor?collaborationTime(plan):'';
  if(timer.textContent!==label)timer.textContent=label;
  timer.hidden=!label;
}
setInterval(()=>{
  syncTeamTotalTime();
  if(!el('board').getClientRects().length)return;
  const timer=el('board').querySelector('[data-mission-total]'),plan=missionControlPlan();
  const label=plan?collaborationTime(plan):'';
  if(timer.textContent!==label)timer.textContent=label;
},1000);
function syncSurface(){
  teamConnectionBar.dataset.connected=String(!!teamReady());
  el('team-connection-label').textContent=teamReady()?((data.teamConnection?.effectiveSource||data.teamConnection?.provider)==='local'?'Local model configured':'API connected'):teamRuntime().teamModel?'Runtime offline':'Model not connected';
  localTaskWarning.hidden=selectedScenario!=='plan'||!teamRuntime().teamModel||(data.teamConnection?.effectiveSource||data.teamConnection?.provider)!=='local';
  syncResetButtons();
  const plan=currentCollaboration();
  const needsReview=taskNeedsPolicyReview(plan);
  controlButton.classList.toggle('needs-attention',!!needsReview);
  controlButton.querySelector('.mission-attention-mark').hidden=!needsReview;
  controlButton.setAttribute('aria-label',needsReview?'Mission Control - review website access':'Mission Control');
  controlButton.title=needsReview?'Website access needs your review':'';
  surfaceDialog.classList.toggle('needs-attention',activeSurface==='control'&&!!needsReview);
  if(policyOverlay.open)el('policy-panel').hidden=false;
  syncTeamTotalTime();
  standbyPanel.hidden=effectiveTeamMode()==='hired';
  resultsButton.hidden=!plan;
  const scenarioJob=plan;
  usageTimeButton.hidden=!scenarioJob||['queued','running','waiting','stopping'].includes(scenarioJob.status);
  surfaceDefinitions.deliverables.ids=['plan-results'];
  if(activeSurface==='deliverables'){renderPlanResults(plan);}
  if(activeSurface==='usage')renderUsageTime(scenarioJob);
  syncSurfaceTask();
  el('compare-open').hidden=!comparison;
  if(!activeSurface)return;
  for(const id of surfaceDefinitions[activeSurface].ids){
    const node=el(id);if(!node)continue;
    node.hidden=id==='plan-results'?!plan:id==='compare'?!comparison:false;
  }
}
function closeSurface(){closeTaskOverlay();closePolicyOverlay();if(surfaceDialog.open)surfaceDialog.close();}
surfaceDialog.addEventListener('click',event=>{
  const link=event.target.closest('[data-current-task-example]');if(!link)return;
  event.preventDefault();
  const job=activeSurface==='control'?missionControlPlan():activeSurface==='deliverables'?currentCollaboration():null;
  openTaskOverlay(goalExamples.find(example=>example.id===link.dataset.currentTaskExample),job,link);
});
surfaceDialog.addEventListener('close',()=>{
  // A new surface may already have opened before this queued close event arrives.
  if(surfaceDialog.open)return;
  closeTaskOverlay();
  closePolicyOverlay();
  for(const node of [...el('surface-body').children])surfaceStore.append(node);
  el('policy-panel').open=false;clearTimeout(policyRefreshTimer);policyRefreshTimer=null;activeSurface=null;board=false;
});
function openSurface(name,contribution='all'){
  const definition=surfaceDefinitions[name];if(!definition)return;
  closePolicyOverlay();
  if(name!=='policies'){el('policy-panel').open=false;clearTimeout(policyRefreshTimer);policyRefreshTimer=null;}
  el('mission-skill-notice')?.remove();
  for(const node of [...el('surface-body').children])surfaceStore.append(node);
  activeSurface=name;board=name==='control';el('surface-title').textContent=definition.title;
  for(const id of definition.ids){const node=el(id);if(node)el('surface-body').append(node);}
  if(name==='policies'){el('policy-panel').open=true;loadPolicy();}
  syncSurface();el('surface-body').scrollTop=0;
  if(!surfaceDialog.open)surfaceDialog.showModal();
}
el('surface-close').onclick=closeSurface;
root.addEventListener('click',e=>{const button=e.target.closest('[data-surface]');if(button)openSurface(button.dataset.surface);});
