// SPDX-License-Identifier: Apache-2.0

function planNames(plan){return defaultNames.map((name,role)=>plan?.visitorBindings?.[role]?.name||name);}
function assignmentFitMarkup(task){
 const reason=typeof task?.roleFit==='string'?task.roleFit.trim():'';
 return reason?'<p class="crew-assignment-fit"><span>Why this agent</span>'+escape(reason)+'</p>':'';
}
function declinedAssignmentsMarkup(job){
 const declined=job.payload.collaboration.declinedAgents||[],roster=[...(job.payload.roster||[]),...(job.payload.unavailableVisitors||[])];
 if(!declined.length)return '';
 return '<div class="crew-declined-assignments"><small>Not assigned</small><ul>'+declined.map(item=>'<li><strong>'+escape(roster.find(member=>member.key===item.agent)?.name||(defaultNames.includes(item.agent)?item.agent:'Requested agent'))+'</strong><span>'+escape(item.reason)+'</span></li>').join('')+'</ul></div>';
}
function assignedVisitor(role){return selectedScenario==='plan'?seatedCollaboration()?.payload.collaboration.visitorBindings?.[role]:null;}
function selectedCrewVisitor(){return selectedScenario==='plan'&&selectedOpenTaskVisitor?(data.agents||[]).find(agent=>agent.key===selectedOpenTaskVisitor&&!agent.deleting):assignedVisitor(selectedCrewRole);}
function crewAgentEditLock(key){
 if(resetInProgress||data.bacResetting)return 'Available when the reset finishes.';
 if((data.crewChats||[]).some(job=>['queued','running','waiting','stopping'].includes(job.status)))return 'Available when the team finishes its current work.';
 return hiredModelLock(key);
}
async function openCrewAgentEditor(){
 const key=selectedCrewVisitor()?.key;
 if(!key||crewAgentEditLock(key))return;
 await switchAgent(key);
 if(room==='mission'&&selectedCrewVisitor()?.key===key&&agentId===key&&!crewAgentEditLock(key))agentForm(false);
}
el('crew-edit-agent').onclick=openCrewAgentEditor;
function selectOpenTaskVisitor(key){
 if(!(data.agents||[]).some(agent=>agent.key===key&&!agent.deleting))return;
 if(crewChatKey)crewDrafts.set(crewChatKey,el('crew-prompt').value);
 crewChatKey='';crewChatSignature='';selectedOpenTaskVisitor=key;selectedCrewRole=0;
 root.dataset.crewDetails='true';renderCrew();
}
function visitorAvailable(visitor){return !!visitor&&(data.agents||[]).some(agent=>agent.key===visitor.key&&!agent.deleting);}
// Each specialist has a durable direct conversation, separate from crew execution.
const defaultCrewPrompt=role=>selectedScenario==='plan'&&role===0?'/goal ':'';
const crewDrafts=new Map();let crewChatKey='',crewChatSignature='',crewChatSending=false,crewResetEpoch='';
let crewComposerEditing=false,crewComposerPointer=false;
// New tasks use hired agents only; an active job keeps its captured team mode.
let preferredTeamMode='hired';
function taskTeamMode(job){return job?.payload.teamMode||(job?.payload.includeHiredAgents??!!job?.payload.roster?.length?'mixed':'builtin');}
function draftTeamMode(){return crewDocumentSelection().teamMode||preferredTeamMode;}
function effectiveTeamMode(){const active=(data.crewChats||[]).find(j=>j.payload?.collaboration&&['queued','running','waiting','stopping'].includes(j.status));return active?taskTeamMode(active):draftTeamMode();}
el('crew-team-mode').onclick=event=>{const button=event.target.closest('[data-team-mode]');if(!button||button.disabled)return;preferredTeamMode=button.dataset.teamMode;el('crew-chat-error').hidden=true;render();};
// Shared by Lounge, crew chat, event replies and roundtable reactions.
function customSkillMarkup(activity){
 if(!activity?.available||!Array.isArray(activity.calls))return '';
 const skills=new Map();
 for(const call of activity.calls){
  const skill=call.customSkill;
  if(call.tool==='read'&&call.status==='completed'&&/^bac-[a-z0-9-]+$/.test(skill?.id||'')&&typeof skill.label==='string')skills.set(skill.id,skill.label);
 }
 if(!skills.size)return '';
 return '<div class="chat-custom-skills" aria-label="Custom skills loaded">'+[...skills.values()].map(label=>'<span class="chat-custom-skill" title="Skill instructions read during this reply"><span>Custom skill</span><strong>'+escape(label)+'</strong></span>').join('')+'</div>';
}
function crewActivityMarkup(job,role){
 const activity=job.direct?job.result?.activity:job.payload.activity?.[role];
 if(!activity)return '';
 if(!activity.available)return '<p class="studio-muted">Tool activity could not be retrieved from the runtime.</p>';
 const labels={read:'Read file',write:'Wrote file',edit:'Edited file',web_fetch:'Read webpage',web_search:'Searched the web',exec:'Executed tool'};
 return '<details class="crew-tool-activity"><summary>Activity · '+activity.calls.length+' tool calls</summary><ol>'+activity.calls.map(call=>'<li><strong>'+escape(call.action?({search:'Searched NVIDIA Blog',read:'Read source articles',schedule:'Validated & exported timetable'}[call.action]||call.action):labels[call.tool]||call.tool)+'</strong><span>'+escape(call.status)+'</span><small>'+escape(call.target||'')+'</small></li>').join('')+'</ol><small>Observed OpenClaw tool calls</small></details>';
}
function webpageButtons(files,jobId){
 const pages=[...new Set(files||[])].filter(path=>/\.html$/i.test(path));
 return pages.length?'<div class="chat-webpages">'+pages.map((path,index)=>'<button type="button" class="studio-secondary" data-preview-file="'+escape(path)+'" data-preview-job="'+escape(jobId)+'">Preview webpage'+(pages.length>1?' '+(index+1):'')+' <span aria-hidden="true">↗</span></button>').join('')+'</div>':'';
}
root.addEventListener('click',event=>{const page=event.target.closest('[data-preview-file]');if(page)openFile(page.dataset.previewFile,page.dataset.previewJob);});
// The latest saved plan owns the visible team, including after a refresh.
async function stageCollaboration(job){
 if(selectedScenario!=='plan')await chooseScenario('plan');
 render();showCollaboration();renderRoomVisibility();
}
// Keep this visit’s chosen team visible until a newer plan or reset.
function currentCollaboration(){
 if(selectedScenario!=='plan')return null;
 const latest=(data.crewChats||[]).filter(j=>j.payload.collaboration&&j.created>=(data.crewChatReset?.at||0)).sort((a,b)=>b.created-a.created)[0];
 return latest||null;
}
// Keep the last confirmed identities at their desks while Casey plans the next task.
// An explicitly empty team releases them; a reset removes the earlier plans entirely.
function seatedCollaboration(){
 if(selectedScenario!=='plan')return null;
 const plans=(data.crewChats||[]).filter(j=>j.payload.collaboration&&j.created>=(data.crewChatReset?.at||0)).sort((a,b)=>b.created-a.created);
 return plans.find(j=>Array.isArray(j.payload.collaboration.tasks)&&(taskTeamMode(j)==='builtin'||j.payload.collaboration.visitorBindings))||plans[0]||null;
}
// Mission Control can inspect saved plans without replaying their stage animation.
function missionControlPlan(){
 const latest=(data.crewChats||[]).filter(j=>j.payload.collaboration&&j.created>=(data.crewChatReset?.at||0)).sort((a,b)=>b.created-a.created)[0];
 return latest||null;
}
function renderStandbySpecialists(agents){
 const occupied=new Set(agents.flatMap((agent,i)=>agent.displayed&&!assignedVisitor(i)?[i]:[]));
 const available=window.BacCrewCatalog.map((member,role)=>({...member,roleIndex:role}))
  .filter(member=>member.planEligible!==false&&(effectiveTeamMode()!=='hired'||member.roleIndex===0));
 el('standby-count').textContent=String(available.length);
 const markup=available.map(member=>{
  const role=member.roleIndex,label=escape(teamModel(role)?.label||'Not connected');
  let model='<span class="studio-specialist-model">'+label+'</span>';
  if(builtinModelEditable(role)){
   const reason=builtinModelLock(role),action=escape('Change '+member.name+' model');
   model='<button type="button" class="studio-specialist-model specialist-model-edit" data-standby-model="'+role+'" aria-label="'+action+'" title="'+(reason?escape(reason):action)+'" '+(modelPickerSaving||reason?'disabled':'')+'>'+label+' <span aria-hidden="true">⌕</span></button>';
  }
  return '<li data-standby-role="'+role+'"><div><strong>'+escape(member.name)+'</strong><span>'+escape(member.collaboration.title)+(occupied.has(role)?' · With team':'')+'</span></div>'+model+'<p class="studio-specialist-summary">'+escape(member.collaboration.summary||member.collaboration.description)+'</p></li>';
 }).join('');
 if(!el('standby-list').contains(document.activeElement)&&el('standby-list').innerHTML!==markup)el('standby-list').innerHTML=markup;
 if(el('standby').open)requestAnimationFrame(fitStandbyPanel);
}
const teamModelDialog=document.createElement('section');
teamModelDialog.hidden=true;
teamModelDialog.className='team-model-dialog';
teamModelDialog.setAttribute('aria-labelledby','team-model-heading');
teamModelDialog.innerHTML='<header><div><h3 id="team-model-heading">Choose a model</h3><p id="team-model-member"></p></div><button type="button" data-model-close>← Back</button></header><input type="search" aria-label="Search models" placeholder="Search models or providers…" autocomplete="off"><p class="team-model-count" aria-live="polite"></p><div class="team-model-results"></div><p class="team-model-error" role="alert" hidden></p>';
// Both Open Task passports and the specialist list use the same model picker.
let modelPickerRole=0,modelPickerSaving=false,modelPickerDraft=null,modelPickerOwner=null,modelPickerScenario=null,modelPickerVisitor=null,modelPickerMarkup='';
function builtinModelEditable(role){
 return selectedScenario==='plan'&&window.BacCrewCatalog[role]?.planEligible!==false&&!!(data.teamConnection?.shared?data.teamConnection.effectiveSource==='api'&&runtime.modelConnections?.connections?.api?.provider==='nvidia':data.teamConnection?.provider!=='local'&&runtime.teamModel);
}
function builtinModelLock(role=0){
 if(resetInProgress||data.bacResetting)return 'Available when the reset finishes.';
 if((data.crewChats||[]).some(j=>['queued','running','waiting','stopping'].includes(j.status))||['queued','running','waiting','stopping'].includes(data.preparation?.status))return 'Available when the team finishes its current work.';
 if(!builtinModelEditable(role)||!teamRuntime().teamReady)return 'Connect the team model in Settings.';
 return '';
}
function hiredModelLock(key){
 const visitor=(data.agents||[]).find(agent=>agent.key===key);
 if(!visitor||visitor.deleting)return 'This agent is no longer available.';
 if(visitor.pending||visitor.activity||visitor.workspacePreparation==='running')return 'Available when this agent finishes its current work.';
 return '';
}
function renderCrewModel(model,visitor=null){
 const badge=el('crew-model'),editable=visitor?visitorAvailable(visitor):builtinModelEditable(selectedCrewRole),reason=editable?(visitor?hiredModelLock(visitor.key):builtinModelLock(selectedCrewRole)):'',name=visitor?.name||defaultNames[selectedCrewRole];
 badge.textContent=model?.label||'';badge.hidden=!model;
 badge.classList.toggle('studio-model-edit',editable);
 badge.disabled=!editable||!!reason||modelPickerSaving;
 badge.title=[reason||(editable?'Change '+name+' model':!visitor&&selectedCrewRole===0?'Follows the Open Task model in Settings':model?.id||''),model?.source==='auto'?model.description:''].filter(Boolean).join(' · ');
 badge.setAttribute('aria-label',editable?'Change '+name+' model: '+(model?.label||'Not connected'):model?.label||'Model');
}
function modelPickerChoices(){
 if(!modelPickerVisitor){
  const models=runtime.teamModels||[];
  if(modelPickerRole===0){
   const id=data.teamSelections?.find(row=>row.role===0)?.defaultId;
   return [{id:'inherit',label:'Use Open Task default',source:'default',description:models.find(row=>row.id===id)?.label||id||''},...models.filter(row=>row.id!=='auto')];
  }
  return models.filter(row=>row.id!=='auto'||runtime.switchyard?.available&&runtime.modelConnections?.connections?.api?.provider==='nvidia');
 }
 const visitor=(data.agents||[]).find(agent=>agent.key===modelPickerVisitor);
 const automatic=personalModel({model:visitor?.model},'team');
 const hub=runtime.modelConnections?.connections?.api?.provider==='nvidia',choices=runtime.personalModels?.models||[];
 const routed=hub&&runtime.switchyard?.available?choices.find(row=>row.id==='auto'):null;
 const auto=routed||(!hub?{id:'auto',label:'Automatic',source:'auto',connected:automatic.connected,description:automatic.label}:null);
 const restore=hub&&visitor?.taskModel?{id:'inherit',label:'Use stage default',source:'default',connected:true,description:automatic.label}:null;
 const rows=[...(restore?[restore]:[]),...(auto?[auto]:[]),...choices.filter(row=>!['shared','auto'].includes(row.id))];
 if(modelPickerDraft&&!rows.some(row=>row.id===modelPickerDraft))rows.push(personalModel({model:modelPickerDraft}));
 return [...new Map(rows.map(row=>[row.id,row])).values()];
}
function renderModelResults(){
 teamModelDialog.querySelector('[data-model-close]').disabled=modelPickerSaving;
 teamModelDialog.querySelector('input').disabled=modelPickerSaving;
 const query=teamModelDialog.querySelector('input').value.trim().toLowerCase();
 const selected=modelPickerDraft;
 const locked=modelPickerVisitor?hiredModelLock(modelPickerVisitor):builtinModelLock(modelPickerRole);
 const models=modelPickerChoices().filter(m=>(m.id+' '+m.label+' '+(m.description||'')+' '+(m.source==='api'?'External Endpoint':'')).toLowerCase().includes(query));
 const displayName=model=>model.source==='auto'?model.label:model.source==='local'?'Local':model.label.split('/').at(-1);
 const nemotron=model=>(model.label+' '+model.id).toLowerCase().includes('nemotron');
 models.sort((a,b)=>Number(b.id==='inherit')-Number(a.id==='inherit')||Number(b.id==='auto')-Number(a.id==='auto')||Number(nemotron(b))-Number(nemotron(a))||displayName(a).localeCompare(displayName(b))||a.id.localeCompare(b.id));
 teamModelDialog.querySelector('.team-model-count').textContent=models.length?(models.length>40?'Showing 40 of '+models.length+' models · Search to narrow the list.':models.length+' models'):'No matching models';
 const markup=models.slice(0,40).map(m=>'<button type="button" data-model-choice="'+escape(m.id)+'" title="'+escape(m.description||m.id)+'" aria-pressed="'+(m.id===selected)+'" '+(modelPickerSaving||locked||m.connected===false?'disabled':'')+'><span><strong>'+escape(displayName(m))+'</strong><small>'+escape(m.source==='default'?m.description:m.source==='auto'?m.description||'Restore the stage model':modelPickerVisitor?(m.source==='local'?m.label:m.source==='shared'?'Uses the shared connection':m.id.split('/').slice(2).join('/')):m.id)+'</small></span><span class="team-model-choice-state">'+(m.connected===false?'Not connected':m.id===selected?'Selected':m.source==='default'?'':m.source==='auto'?'Automatic':!modelPickerVisitor||m.source==='api'?'External Endpoint':'')+'</span></button>').join('');
 const results=teamModelDialog.querySelector('.team-model-results');
 if(modelPickerMarkup!==markup){modelPickerMarkup=markup;results.innerHTML=markup;}
 teamModelDialog.querySelector('.team-model-count').textContent=locked||teamModelDialog.querySelector('.team-model-count').textContent;
}
root.addEventListener('click',event=>{
 const button=event.target.closest('[data-standby-model]');if(!button||button.disabled||modelPickerSaving||!teamModelDialog.hidden)return;
 openCrewModelPicker(Number(button.dataset.standbyModel));
});
el('crew-model').onclick=()=>{
 if(el('crew-model').disabled)return;
 const visitor=selectedCrewVisitor();
 openCrewModelPicker(selectedCrewRole,visitor);
};
function visitorTaskModelSelection(visitor){
 return visitor?.taskModel||(runtime.modelConnections?.connections?.api?.provider==='nvidia'?personalModel(visitor,'team').id:'auto');
}
function builtinPickerSelection(role){
 return role===0&&data.teamSelections?.find(row=>row.role===0)?.inherited?'inherit':teamModel(role)?.id;
}
function openCrewModelPicker(role,visitor=null){
 if(modelPickerSaving||!teamModelDialog.hidden)return;
 modelPickerRole=role;
 if(visitor?hiredModelLock(visitor.key):(!builtinModelEditable(role)||builtinModelLock(role)))return;
 modelPickerVisitor=visitor?.key||null;modelPickerOwner=agentId;modelPickerScenario=selectedScenario;modelPickerDraft=visitor?visitorTaskModelSelection(visitor):builtinPickerSelection(role);
 const name=visitor?.name||defaultNames[role];
 teamModelDialog.querySelector('#team-model-member').textContent=name;
 teamModelDialog.querySelector('input').value='';teamModelDialog.querySelector('.team-model-error').hidden=true;
 renderModelResults();dialog(name+' · Model','');el('dialog-body').append(teamModelDialog);teamModelDialog.hidden=false;
 el('dialog').scrollTop=0;teamModelDialog.querySelector('.team-model-results').scrollTop=0;
 teamModelDialog.querySelector('input').focus({preventScroll:true});
}
teamModelDialog.querySelector('input').addEventListener('input',renderModelResults);
function closeTeamModelPicker(){
 if(modelPickerSaving)return;
 teamModelDialog.hidden=true;el('dialog').close();
}
teamModelDialog.addEventListener('keydown',event=>{
 if(event.key==='Escape'&&!teamModelDialog.hidden){event.preventDefault();event.stopPropagation();closeTeamModelPicker();}
 const buttons=[...teamModelDialog.querySelectorAll('[data-model-choice]:not(:disabled)')];
 if(event.target===teamModelDialog.querySelector('input')){
  if(event.key==='ArrowDown'){event.preventDefault();buttons[0]?.focus();}
  if(event.key==='Enter'){event.preventDefault();if(buttons.length===1)buttons[0].click();}
 }else if(buttons.includes(event.target)&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
  event.preventDefault();const index=buttons.indexOf(event.target);
  buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();
 }
});
el('dialog').addEventListener('cancel',event=>{
 if(!teamModelDialog.hidden&&teamModelDialog.isConnected){event.preventDefault();closeTeamModelPicker();}
});
el('dialog').addEventListener('close',()=>{teamModelDialog.hidden=true;});
teamModelDialog.addEventListener('click',async event=>{
 if(event.target.closest('[data-model-close]')){closeTeamModelPicker();return;}
 if(modelPickerSaving)return;
 const choice=event.target.closest('[data-model-choice]');
 if(choice&&!choice.disabled){
  if(!modelPickerVisitor&&builtinModelLock(modelPickerRole)){renderModelResults();return;}
  if(modelPickerVisitor&&(hiredModelLock(modelPickerVisitor)||!modelPickerChoices().some(m=>m.id===choice.dataset.modelChoice&&m.connected))){renderModelResults();return;}
  modelPickerDraft=choice.dataset.modelChoice;
  if(agentId!==modelPickerOwner||selectedScenario!==modelPickerScenario){closeTeamModelPicker();return;}
  teamModelDialog.querySelector('.team-model-error').hidden=true;
  const pickerRevision=dialogRevision;
  const saved=await applyTeamModel();
  // The presenter may close this picker and open another dialog while saving.
  if(pickerRevision!==dialogRevision||teamModelDialog.hidden||!teamModelDialog.isConnected)return;
  if(saved)closeTeamModelPicker();else renderModelResults();return;
 }

});
async function applyTeamModel(){
 const target=modelPickerOwner,scenario=modelPickerScenario,role=modelPickerRole,model=modelPickerDraft,visitor=modelPickerVisitor;
 const current=()=>agentId===target&&selectedScenario===scenario;
 modelPickerSaving=true;
 if(!teamModelDialog.hidden)renderModelResults();
 try{
  const selected=model==='inherit'?null:model;
  const result=await api(visitor?'agent-model':'team-model',visitor?{model:selected,stage:'team'}:{role,model:selected},visitor||target,scenario);
  if(visitor)stateCache.clear();
  if(current()){
   // A poll started before this write must not restore the previous model.
   ++refreshVersion;stateCache.delete(target);busy=false;
   data=visitor?{...data,agents:data.agents.map(agent=>agent.key===visitor?{...agent,...result,taskModel:result.taskModel}:agent),profile:agentId===visitor?result:data.profile}:{...data,teamSelections:result.teamSelections};render();
  }
  return true;
 }catch(error){
  if(current())modelPickerDraft=visitor?visitorTaskModelSelection((data.agents||[]).find(agent=>agent.key===visitor)):builtinPickerSelection(role);
  if(current()&&!teamModelDialog.hidden){const notice=teamModelDialog.querySelector('.team-model-error');notice.textContent=error.message;notice.hidden=false;}
  else alert('Model changes could not be applied. '+error.message);
  return false;
 }finally{
  modelPickerSaving=false;render();
  if(!teamModelDialog.hidden)renderModelResults();
 }
}

// Reconstruct the visible trace from saved handoffs, contributions and checkpoints.
// Planned-but-uncalled roles are never presented as completed execution steps.
function collaborationRoleOrder(plan){
 const tasks=(plan.tasks||[]).map(task=>Number(task.role));
 const handoffs=Object.keys(plan.handoffs||{}).map(Number).sort((a,b)=>{
  const first=plan.handoffs[a]?.started,last=plan.handoffs[b]?.started;
  return first&&last?first-last:tasks.indexOf(a)-tasks.indexOf(b);
 });
 return [...new Set([...(plan.calledRoles||[]).map(Number),...handoffs,...tasks,...Object.keys(plan.outputs||{}).map(Number)])]
  .filter(role=>Number.isInteger(role)&&role>0&&defaultNames[role]);
}
// Presence follows this plan's confirmed identities. Reusing an earlier plan's
// role slots without its bindings would briefly summon the built-in occupants.
function collaborationTeam(plan,teamMode='builtin'){
 if(teamMode!=='builtin'&&!plan.visitorBindings)return [0];
 const selected=Array.isArray(plan.tasks)?plan.tasks.map(task=>task.role):(plan.calledRoles||[]);
 return [0,...new Set(selected.filter(role=>Number.isInteger(role)&&role>0&&defaultNames[role]&&window.BacCrewCatalog[role].planEligible!==false&&(teamMode!=='hired'||!!plan.visitorBindings?.[role]?.key)))];
}
// The scene can announce a confirmed team gap before any specialist has worked.
function unassignedTeamAt(job){
 const plan=job.payload.collaboration;
 if(job.status!=='done'||plan.outcome!=='unavailable'||!plan.summary)return null;
 if(plan.calledRoles?.length||Object.keys(plan.handoffs||{}).length||Object.keys(plan.outputs||{}).length)return null;
 return job.updated;
}
function collaborationAnswer(job){return job.result?.answer||job.payload.collaboration.finalAnswer||'';}
// Wall-clock time includes queueing, planning, all specialists and final review.
function collaborationTime(job,now=Date.now()/1000){
 const active=['queued','running','waiting','stopping'].includes(job.status);
 const start=Number(job.created),end=active?now:Number(job.updated);
 if(!Number.isFinite(start)||!Number.isFinite(end)||start<=0||end<=0)return '';
 const seconds=Math.max(0,Math.floor(end-start)),hours=Math.floor(seconds/3600),minutes=Math.floor(seconds%3600/60);
 const duration=hours?hours+'h '+minutes+'m '+seconds%60+'s':minutes?minutes+'m '+seconds%60+'s':seconds+'s';
 return (active?'Total elapsed: ':'Total time: ')+duration;
}
function updateCollaborationTimers(log,jobs){
 for(const job of jobs){
  const label=collaborationTime(job);
  for(const timer of log.querySelectorAll('[data-plan-total="'+job.id+'"],[data-plan-elapsed="'+job.id+'"]'))timer.textContent=label;
 }
}
function collaborationTimeMarkup(job){
 const label=collaborationTime(job);
 return label?'<p class="mission-plan-inputs" data-plan-total="'+escape(job.id)+'" title="From submission to completion, including queueing, planning, specialists and review.">'+escape(label)+'</p>':'';
}
function modelReasoningMarkup(job,role,revision=null,attempt=null){
 const state=missionReasoningCache.get(job.id),report=state?.report;
 const calls=(report?.calls||[]).filter(call=>Number(call.role)===Number(role)&&(revision===null||/^Revis/.test(call.phase)===revision)&&(attempt===null||Number(call.phase?.match(/-permission-retry-(\d+)/)?.[1]||0)===attempt));
 const sections=calls.flatMap(call=>call.turns||[]).flatMap(turn=>turn.sections||[]);
 const published=sections.some(section=>section.text);
 const kinds=new Set(sections.filter(section=>section.text).map(section=>section.kind));
 const label=kinds.size===1&&kinds.has('summary')?'Reasoning summary':'Model reasoning';
 let body='';
 if(!report){
  body='<p class="mission-reasoning-empty" role="status">'+(state?.error?'Could not load reasoning. Close and reopen to retry.':'Loading saved reasoning…')+'</p>';
 }else if(!calls.length){
  body='<p class="mission-reasoning-empty">'+(report.active?'Reasoning will appear here if the model provides it.':report.recorded?'No reasoning was recorded for this step.':'Reasoning not available. This task has no saved provider trace.')+'</p>';
 }else{
  const latest=calls.findLast(call=>call.status==='collecting'||(call.turns||[]).some(turn=>turn.sections?.some(section=>section.text)))?.id;
  body=calls.map(call=>{
   const textTurns=(call.turns||[]).filter(turn=>turn.sections?.some(section=>section.text));
   const model=[...new Set((call.turns||[]).map(turn=>turn.model).filter(Boolean))].map(model=>model.split('/').at(-1)).join(' · ');
   const phase=/-permission-retry-/.test(call.phase)?'Continuing after access review':/^Assessing-access-/.test(call.phase)?'Access needs':/^Planning-captain-scope/.test(call.phase)?'Casey’s scope':/^Planning.*scope/.test(call.phase)?'Team capabilities':/^Planning/.test(call.phase)?'Planning':/^Checking/.test(call.phase)?'Checking progress':/^Review/.test(call.phase)?'Final review':/^Revis/.test(call.phase)?'Revision':/^Recover/.test(call.phase)?'Recovery':'Working';
   const status=call.status==='collecting'?'Receiving':textTurns.length?'Saved':'Not provided';
   const content=textTurns.length?textTurns.map(turn=>'<div class="mission-reasoning-turn"><small>Turn '+Number(turn.index)+(turn.status==='interrupted'?' · Interrupted':'')+'</small>'+turn.sections.filter(s=>s.text).map(section=>'<div class="mission-reasoning-text" data-reasoning-scroll="'+escape(call.id+':'+turn.index+':'+section.kind)+'">'+escape(section.text)+'</div>'+(section.truncated?'<small>Display limit reached.</small>':'')).join('')+'</div>').join(''):'<p class="mission-reasoning-empty">'+(call.status==='collecting'?'Waiting for provider-published text…':'Reasoning not available. The model or connection did not provide displayable text.')+'</p>';
   return '<details class="mission-reasoning-call" data-trace-details="reasoning-'+escape(call.id)+'" '+(call.id===latest?'open':'')+'><summary><span>'+escape(phase)+'</span><small title="'+escape(model)+'">'+escape(model||'Model')+'</small><em>'+status+'</em></summary>'+content+'</details>';
  }).join('');
 }
 return '<section class="mission-model-reasoning"><div class="mission-reasoning-heading"><strong>'+label+'</strong><span>'+(published?'Provider-published':'Availability varies by model')+'</span></div><p class="mission-reasoning-note">Text shared by the model provider. Opening this view does not run the model again.</p>'+body+(report?.truncated?'<small class="mission-reasoning-note">Some text is shortened to keep this view responsive.</small>':'')+'</section>';
}
async function loadModelReasoning(job){
 if(!missionReasoningOpen||document.hidden||el('board').hidden||!el('board').getClientRects().length)return;
 const old=missionReasoningCache.get(job.id),active=['queued','running','waiting','stopping'].includes(job.status);
 if(old?.pending||old?.error||old?.loaded&&(!active&&!old.report?.active||Date.now()-old.loaded<1500))return;
 const state={...old,pending:true};missionReasoningCache.set(job.id,state);
 while(missionReasoningCache.size>2)missionReasoningCache.delete(missionReasoningCache.keys().next().value);
 try{
  const report=await api('model-reasoning?id='+encodeURIComponent(job.id));
  if(missionReasoningCache.get(job.id)!==state)return;
  state.report=report;state.loaded=Date.now();
 }catch{state.error=true;}
 finally{
  state.pending=false;
  if(missionReasoningOpen&&missionReasoningJob===job.id){
   renderMissionControl();
   clearTimeout(missionReasoningTimer);
   if(!state.error&&(active||state.report?.active))missionReasoningTimer=setTimeout(()=>renderMissionControl(),1600);
  }
 }
}
const taskPolicyPending=new Set();
function taskNeedsPolicyReview(job){
 return !!(job?.status==='waiting'&&job.payload?.collaboration?.policyRequests?.some(request=>request.status==='pending'));
}
function taskPolicyRequestMarkup(job,request){
 const active=job.status==='waiting'&&request.status==='pending',pending=taskPolicyPending.has(request.id)||policySaving;
 const label=active?'Review access to continue':request.status==='continued'?(Array.isArray(request.newlyAllowedHosts)?(request.newlyAllowedHosts.length?'Continuing with updated permissions':'Using available evidence'):'Continuing with current permissions'):request.status==='expired'?'Using available evidence':'Task stopped';
 return '<section class="mission-policy-request" data-policy-request="'+escape(request.id)+'"><strong>◇ OpenShell · '+escape(label)+'</strong><p>'+escape(request.name)+(active?' has finished researching, but some needed sources remain blocked.':' reviewed access for this task.')+'</p>'+(request.reason?'<p>'+escape(request.reason)+'</p>':'')+(active?'<p>Choose websites in OpenShell Policy, then Continue. Newly allowed sites can be retried; without new access, the agent uses existing evidence.</p><div class="mission-policy-actions"><button type="button" class="studio-secondary" data-task-policy="policy" data-policy-job="'+escape(job.id)+'" data-policy-id="'+escape(request.id)+'" '+(pending?'disabled':'')+'>OpenShell Policy for '+escape(request.name)+' Agent ↗</button><button type="button" class="studio-primary" data-task-policy="continue" data-policy-job="'+escape(job.id)+'" data-policy-id="'+escape(request.id)+'" '+(pending?'disabled':'')+'>'+(policySaving?'Applying permissions…':pending?'Continuing…':'Continue')+'</button></div>':'<small>Continue does not grant access. Only permissions selected in OpenShell Policy apply.</small>')+'</section>';
}

function reviewModelUsageMarkup(job,check){
 const plan=job.payload.collaboration;
 // The final saved check comes from Reviewing/Finalizing, not Checking-<role>.
 // Limit that fallback to the final check so earlier reviews keep their own models.
 const final=check===(plan.checks||[]).at(-1)&&Number(check.afterRole)===Number(plan.tasks?.at(-1)?.role)&&!plan.skippedRoles?.length;
 if(final){
  const usage=modelUsageMarkup(job,{role:0,phase:check.afterRevision?/^(Checking-revision|Finalizing)$/:/^(Reviewing|Finalizing)$/,latest:true});
  if(usage)return usage;
 }
 return modelUsageMarkup(job,{role:0,phase:check.afterRevision?/^Checking-revision$/:new RegExp('^Checking-'+Number(check.afterRole)+'(?:$|-)')});
}
function missionControlTraceMarkup(job,advanced=false){
 const defaultNames=planNames(job.payload.collaboration);
 const plan=job.payload.collaboration,active=['queued','running','waiting','stopping'].includes(job.status),tasks=plan.tasks||[],checks=plan.checks||[];
 const usage=(role,phase,options={})=>modelUsageMarkup(job,{role,phase,...options});
 let sequence=-1;
 const row=(kind,name,status,content,attrs='',recorded=true,state='')=>'<article class="mission-plan-step" data-trace-key="'+escape(kind+':'+attrs)+'" data-trace-kind="'+kind+'" data-step-state="'+state+'" '+attrs+'><header><small>'+(recorded?String(++sequence).padStart(2,'0')+' · '+({plan:'PLAN',contribution:'CONTRIBUTION',reasoning:'REASONING',review:'REVIEW',revision:'REVISION REQUEST','revision-work':'REVISION',response:'RESPONSE',stopped:'STOPPED'}[kind]||kind.toUpperCase()):kind==='skipped'?'NOT CALLED':'PLANNED')+'</small><h4>'+escape(name)+'</h4><span>'+escape(status)+'</span></header><div class="mission-plan-content">'+content+'</div></article>';
 const detail=(key,label,content)=>'<details class="mission-trace-detail" data-trace-details="'+key+'"'+(key==='response'?' open':'')+'><summary>'+escape(label)+'</summary><div class="chat-prose">'+content+'</div></details>';
 const question=String(plan.task||job.payload.prompt||'').replace(/^\s*\/(?:goals?|plans?)(?=\s|$)/i,'').trim();
 let markup=row('user','User','Submitted','<strong>Request</strong><div class="chat-prose">'+messageMarkup(question)+'</div>','',true,'done');
 markup+=row('plan','Casey',plan.summary?'Plan ready':active?'Planning':'No plan saved',usage(0,/^(Planning|Team-skill-check)/,{includeLive:true})+ '<strong>Approach</strong><div>'+messageMarkup(plan.summary||(active?'Casey is deciding which expertise this request needs.':'No plan was saved before the work stopped.'))+'</div>'+declinedAssignmentsMarkup(job)+(advanced?modelReasoningMarkup(job,0):''),'data-plan-role="0"',true,plan.summary?'done':active?'working':'');
 const permissionRow=request=>row('permission','Casey',job.status==='waiting'&&['pending','applying'].includes(request.status)?'Waiting for you':request.status,usage(0,new RegExp('^Assessing-access-'+request.assignmentRole+'(?:$|-)'))+taskPolicyRequestMarkup(job,request),'data-permission-id="'+escape(request.id)+'"',true,job.status==='waiting'&&['pending','applying'].includes(request.status)?'working':'done');
 const called=tasks.filter(task=>plan.handoffs?.[task.role]||plan.outputs?.[task.role]||plan.calledRoles?.includes(task.role));
 const calledOrder=collaborationRoleOrder(plan);
 called.sort((a,b)=>calledOrder.indexOf(Number(a.role))-calledOrder.indexOf(Number(b.role)));
 for(const task of called){
  const role=task.role,h=plan.handoffs?.[role],output=plan.outputs?.[role];
  const requests=(plan.policyRequests||[]).filter(request=>request.assignmentRole===role);
  const working=active&&plan.activeRole===role&&!requests.length;
  const recovery=plan.handoffRecovery?.role===role?plan.handoffRecovery:null;
  const missing=output?.handoffStatus==='missing';
  const pendingPermission=job.status==='waiting'&&(plan.policyRequests||[]).some(r=>r.assignmentRole===role&&['pending','applying'].includes(r.status));
  const status=requests.length?(requests[0].status==='pending'&&pendingPermission?'Waiting for approval':'Access blocked'):missing?(working&&recovery?.status==='working'?'Saving missing handoff':'Handoff incomplete'):output?.incomplete?'Partial work saved':output?'Delivered':working?(job.status==='stopping'?'Stopping':'Working'):active?'Started':'Incomplete';
  const expected=h?.expected||task.expected;
  const assignment='<strong>Casey’s assignment</strong><div>'+messageMarkup(h?.task||task.task)+'</div>'+assignmentFitMarkup(task)+(expected?'<div class="mission-expectation"><small>Expected result</small><div>'+messageMarkup(expected)+'</div></div>':'')+(h?'<small class="mission-plan-inputs">Received: '+escape(['Casey’s brief',...(h.receivedFrom||[]).map(i=>defaultNames[Number(i)]+"’s contribution")].join(' · '))+'</small>':'');
  const recoveryNote=recovery?'<p class="mission-plan-inputs">'+escape(recovery.status==='delivered'?'A missing handoff was saved and verified in one repair before continuing.':recovery.status==='working'?'Required files are missing. One repair is using the existing research; later specialists are waiting.':'The required handoff could not be recovered. Later specialists were not started.')+'</p>':'';
  const initialOutput=requests.length?requests[0].contribution:output;
  markup+=row('contribution',defaultNames[role],status,usage(role,/^(Working|Recovering)/,{attempt:requests.length?0:null,includeLive:working})+assignment+(!requests.length?recoveryNote:'')+(initialOutput?detail('output-'+role,defaultNames[role]+'’s result',messageMarkup(initialOutput.answer||'No response text was saved.')+webpageButtons(initialOutput.files,job.id)):requests.length?'<p class="mission-plan-inputs">Research finished with blocked sources. The earlier response was not saved separately.</p>':'')+(advanced?modelReasoningMarkup(job,role,false,requests.length?0:null):''),'data-plan-role="'+role+'"',true,requests.length?'done':missing?(working?'working':''):output?'done':working?'working':'');
  for(const [index,request] of requests.entries()){
   markup+=permissionRow(request);
   if(request.status!=='continued')continue;
   const next=requests[index+1],continuedOutput=next?next.contribution:output;
   const resuming=active&&plan.activeRole===role&&!next&&job.status!=='waiting';
   const status=next?'Access blocked':continuedOutput?.handoffStatus==='missing'?'Handoff incomplete':continuedOutput?.incomplete?'Partial work saved':continuedOutput?'Delivered':resuming?(job.status==='stopping'?'Stopping':'Working'):active?'Ready to continue':'Incomplete';
   const note=request.newlyAllowedHosts?.length?'Retrying the newly allowed sources.':Array.isArray(request.newlyAllowedHosts)?'Finishing with available evidence; no new websites were approved.':'Continuing with the current permissions.';
   markup+=row('contribution',defaultNames[role],status,usage(role,/^(Working|Recovering)/,{attempt:index+1,includeLive:resuming})+'<strong>Continuing after access review</strong><p>'+escape(note)+'</p>'+(!next?recoveryNote:'')+(continuedOutput?detail('output-'+role+'-after-'+request.id,defaultNames[role]+'’s result',messageMarkup(continuedOutput.answer||'No response text was saved.')+webpageButtons(continuedOutput.files,job.id)):'')+(advanced?modelReasoningMarkup(job,role,false,index+1):''),'data-plan-role="'+role+'" data-after-permission="'+escape(request.id)+'"',true,next||continuedOutput?'done':resuming?'working':'');
  }
  const reviews=checks.filter(check=>!check.afterRevision&&Number(check.afterRole)===role);
  for(const check of reviews){
   const status=check.done?(check.outcome==='partial'?'Partial result':check.outcome==='unavailable'?'Capability unavailable':'Enough to finish'):'More work needed';
   markup+=row('review','Casey',status,reviewModelUsageMarkup(job,check)+'<strong>After '+escape(defaultNames[role])+'’s result</strong><div>'+messageMarkup(check.reason)+'</div>'+(check.done?'<small class="mission-plan-inputs">No additional agents will be called.</small>':''),'data-after-role="'+role+'"',true,'done');
  }
  if(output&&!reviews.length&&active&&plan.activeRole===0&&!plan.responseReady&&task===called.at(-1)&&!plan.revision)
   markup+=row('review','Casey',job.status==='stopping'?'Stopping':'Reviewing',usage(0,new RegExp('^(Checking-'+role+'(?:$|-)|Assessing-access-'+role+'(?:$|-)|Reviewing$|Finalizing$)'),{latest:true,includeLive:true})+'<strong>After '+escape(defaultNames[role])+'’s result</strong><p>Checking the contribution against the request before deciding what comes next.</p>','data-after-role="'+role+'"',true,'working');
 }
 for(const request of (plan.policyRequests||[]).filter(r=>!called.some(t=>t.role===r.assignmentRole)))markup+=permissionRow(request);
 for(const task of tasks.filter(task=>!called.includes(task))){
  const skipped=plan.skippedRoles?.includes(task.role),uncalled=skipped||!active||plan.responseReady;
  markup+=row(uncalled?'skipped':'planned',defaultNames[task.role],uncalled?'Not called':'Waiting for Casey',assignmentFitMarkup(task)+detail('assignment-'+task.role,'Planned assignment',messageMarkup(task.task)+(task.expected?'<div class="mission-expectation"><small>Expected result</small>'+messageMarkup(task.expected)+'</div>':''))+'<small class="mission-plan-inputs">'+(skipped?'Casey ended the plan before calling this agent.':uncalled?'This assignment was not started.':'Casey will decide whether this assignment is still needed.')+'</small>','data-plan-role="'+task.role+'"',false,uncalled?'skipped':'planned');
 }
 if(plan.revision){
  const r=plan.revision,output=r.output,working=active&&r.status==='working';
  markup+=row('revision','Casey','One targeted revision','<strong>Why repair is needed</strong><div>'+messageMarkup(r.reason)+'</div><div>'+messageMarkup(r.issue)+'</div>','data-revision-request',true,'done');
  markup+=row('revision-work',defaultNames[r.role],output?'Revised result delivered':working?'Revising':active&&r.status==='requested'?'Requested':r.status==='failed'?'Revision failed':'Not completed',usage(r.role,/^Revising/,{includeLive:working})+collaborationRevisionBody(r,job.id)+(advanced?modelReasoningMarkup(job,r.role,true):''),'data-revision-role="'+r.role+'"',true,output?'done':working?'working':'');
  for(const check of checks.filter(check=>check.afterRevision))
   markup+=row('review','Casey',check.outcome==='partial'?'Partial result':'Final verification',reviewModelUsageMarkup(job,check)+ '<div>'+messageMarkup(check.reason)+'</div><small>No further specialist calls.</small>','data-after-revision',true,'done');
  if(output&&!checks.some(check=>check.afterRevision)&&active&&!plan.responseReady)
   markup+=row('review','Casey','Verifying revision',usage(0,/^(Checking-revision|Finalizing)$/,{latest:true,includeLive:true})+'<p>Checking the repaired result and remaining limitations. No further specialist calls.</p>','data-after-revision',true,'working');
 }
 const answer=collaborationAnswer(job);
 if(answer)markup+=row('response','Casey',plan.outcome==='partial'?'Partial result':plan.outcome==='unavailable'?'Capability unavailable':'Response ready',usage(0,/^(Reviewing|Finalizing|Checking)/,{latest:true})+detail('response','Final team response',messageMarkup(answer)+(plan.outcome==='partial'&&plan.remaining?.length?'<strong>Still needed</strong><ul>'+plan.remaining.map(item=>'<li>'+escape(item)+'</li>').join('')+'</ul>':'')+webpageButtons(Object.values(plan.webpages||{}).flat(),job.id)),'',true,'done');
 else if(!active)markup+=row('stopped','Casey',job.status==='cancelled'?'Stopped':'Error','<div>'+messageMarkup(job.result?.error||(job.status==='cancelled'?'The work stopped before a final response was ready.':'No final response was saved.'))+'</div>');
 return markup;
}
function updateMissionControlTrace(lanes,jobId,markup,notify=true){
 const sameJob=lanes.dataset.traceJob===jobId;
 const viewport=lanes.closest('#studio-surface-body'),scrollTop=viewport?.scrollTop;
 const visible=!!viewport?.getClientRects().length;
 if(!sameJob||!notify||!visible)lanes._traceUpdate=null;
 syncMissionUpdateNotice(lanes);
 if(sameJob&&lanes._traceMarkup===markup)return;
 const template=document.createElement('template');template.innerHTML=markup;
 const incoming=[...template.content.children],keys=new Set(incoming.map(node=>node.dataset.traceKey));
 const old=new Map(sameJob?[...lanes.children].map(node=>[node.dataset.traceKey,node]):[]);
 if(!sameJob)lanes.replaceChildren();
 else for(const node of [...lanes.children])if(!keys.has(node.dataset.traceKey))node.remove();
 let cursor=lanes.firstElementChild;
 const retained=new Set();
 for(const fresh of incoming){
  const previous=old.get(fresh.dataset.traceKey),source=fresh.outerHTML;
  const node=previous?._traceMarkup===source?previous:fresh;
  if(sameJob&&notify&&visible&&node!==previous&&fresh.dataset.traceKind!=='planned'&&previous?.textContent!==fresh.textContent){
   const texts=new Map([...(previous?.querySelectorAll('[data-reasoning-scroll]')||[])].map(item=>[item.dataset.reasoningScroll,item.textContent]));
   const changed=[...fresh.querySelectorAll('[data-reasoning-scroll]')].filter(item=>texts.get(item.dataset.reasoningScroll)!==item.textContent).at(-1);
   lanes._traceUpdate={trace:fresh.dataset.traceKey,reasoning:changed?.dataset.reasoningScroll};
  }
  if(previous&&node!==previous){
   const details=new Map([...previous.querySelectorAll('[data-trace-details]')].map(item=>[item.dataset.traceDetails,item.open]));
   for(const item of node.querySelectorAll('[data-trace-details]'))if(details.has(item.dataset.traceDetails))item.open=details.get(item.dataset.traceDetails);
   const positions=new Map([...previous.querySelectorAll('[data-reasoning-scroll]')].map(item=>[item.dataset.reasoningScroll,item.scrollTop]));
   // Replace in place so later unchanged cards never move through the DOM.
   if(cursor===previous)cursor=node;
   previous.replaceWith(node);
   for(const item of node.querySelectorAll('[data-reasoning-scroll]'))if(positions.has(item.dataset.reasoningScroll))item.scrollTop=positions.get(item.dataset.reasoningScroll);
  }
  node._traceMarkup=source;
  // Retain unchanged cards, including their focused links/buttons and selection.
  if(node!==cursor)lanes.insertBefore(node,cursor);
  cursor=node.nextElementSibling;retained.add(node);
 }
 for(const node of [...lanes.children])if(!retained.has(node))node.remove();
 lanes.dataset.traceJob=jobId;lanes._traceMarkup=markup;
 // Polling never moves the reader, including when an earlier card grows.
 if(sameJob&&viewport)viewport.scrollTop=scrollTop;
 syncMissionUpdateNotice(lanes);
}
function syncMissionUpdateNotice(lanes){
 const notice=document.getElementById('studio-mission-updates'),viewport=lanes.closest('#studio-surface-body');
 if(!notice||!viewport)return;
 const target=()=>{
  const pending=lanes._traceUpdate;
  const row=pending&&[...lanes.children].find(node=>node.dataset.traceKey===pending.trace);
  if(!row)return null;
  return (pending.reasoning&&[...row.querySelectorAll('[data-reasoning-scroll]')].find(node=>node.dataset.reasoningScroll===pending.reasoning))||row.querySelector('.mission-trace-detail:last-of-type')||row;
 };
 const sync=()=>{
  if(!viewport.contains(lanes))return;
  const node=target(),bounds=viewport.getBoundingClientRect(),rect=node?.getBoundingClientRect();
  let closed=false;
  for(let item=node;item&&item!==lanes;item=item.parentElement)if(item.matches('details:not([open])'))closed=true;
  const read=node&&!closed&&rect.height>0&&rect.top>=bounds.top&&rect.bottom<=bounds.bottom-8&&node.scrollHeight-node.clientHeight-node.scrollTop<12;
  if(!node||read)lanes._traceUpdate=null;
  notice.hidden=!lanes._traceUpdate;
 };
 // Capture also observes scrolls inside the bounded reasoning text boxes.
 if(lanes._updateViewport!==viewport){
  lanes._updateViewport?.removeEventListener('scroll',lanes._updateScroll,true);
  lanes._updateViewport=viewport;lanes._updateScroll=()=>syncMissionUpdateNotice(lanes);
  viewport.addEventListener('scroll',lanes._updateScroll,{capture:true,passive:true});
 }
 notice.querySelector('button').onclick=()=>{
  const node=target();if(!node)return;
  for(let item=node;item&&item!==lanes;item=item.parentElement)if(item.matches('details'))item.open=true;
  if(node.matches('[data-reasoning-scroll]'))node.scrollTop=node.scrollHeight;
  node.scrollIntoView({block:'center',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  node.setAttribute('tabindex','-1');node.focus({preventScroll:true});
  lanes._traceUpdate=null;notice.hidden=true;
 };
 sync();
}
let missionReasoningOpen=false,missionReasoningJob='';
const missionReasoningCache=new Map();
let missionReasoningTimer=0;
function renderMissionControl(){
 const job=missionControlPlan(),intro=el('board').querySelector('.studio-board-intro');
 el('lanes').classList.toggle('studio-plan-control',!!job);
 el('board').classList.toggle('has-plan',!!job);
 intro.querySelector('h3').textContent=job?'Execution trace':'No active plan';
 intro.querySelector('[data-mission-total]').textContent=job?collaborationTime(job):'';
 intro.querySelector('p').textContent=job?job.payload.collaboration.task:'Send /goal to Casey to start.';
 const reasoningButton=el('mission-reasoning');
 reasoningButton.onclick=()=>{missionReasoningOpen=!missionReasoningOpen;clearTimeout(missionReasoningTimer);if(missionReasoningCache.get(missionReasoningJob)?.error)missionReasoningCache.delete(missionReasoningJob);renderMissionControl();};
 if(!job){
  missionReasoningOpen=false;missionReasoningJob='';reasoningButton.hidden=true;
  el('mission-updates').hidden=true;el('lanes')._traceUpdate=null;
  el('lanes').innerHTML='';delete el('lanes').dataset.traceJob;delete el('lanes')._traceMarkup;return;
 }
 if(missionReasoningJob!==job.id){missionReasoningJob=job.id;missionReasoningOpen=false;}
 reasoningButton.hidden=false;reasoningButton.setAttribute('aria-expanded',String(missionReasoningOpen));
 reasoningButton.textContent=missionReasoningOpen?'Hide advanced reasoning':'Advanced reasoning';
 if(missionReasoningOpen)loadModelReasoning(job);
 const lanes=el('lanes');
 // Completion must not clear unread updates. Provider text can also arrive
 // after the task ends; only changing views suppresses update notifications.
 updateMissionControlTrace(lanes,job.id,missionControlTraceMarkup(job,missionReasoningOpen),
  lanes._traceAdvanced===missionReasoningOpen);
 lanes._traceAdvanced=missionReasoningOpen;
}
// /goal is a real Captain-led job; contributions come from completed model calls.
function collaborationRevisionBody(revision,jobId){
 return '<strong>Casey’s revision assignment</strong><div>'+messageMarkup(revision.task)+'</div><div class="mission-expectation"><small>Expected result</small>'+messageMarkup(revision.expected)+'</div>'+(revision.output?'<details class="mission-trace-detail" data-trace-details="revision-output"><summary>Revised contribution</summary><div class="chat-prose">'+messageMarkup(revision.output.answer)+'</div>'+webpageButtons(revision.output.files,jobId)+collaborationFileButtons(revision.output.files,jobId)+'</details>':'')+(revision.status==='failed'?'<p>The revision did not finish. Previous contributions are preserved.</p>':'');
}
function collaborationRevisionMarkup(job){
 const defaultNames=planNames(job.payload.collaboration);
 const r=job.payload.collaboration.revision;if(!r)return '';
 return '<section class="chat-message chat-handoff" data-plan-revision><small>Casey · One targeted revision</small><div class="chat-prose">'+messageMarkup(r.reason)+'</div><p>'+escape(r.issue)+'</p><small>'+escape(defaultNames[r.role])+' · '+(r.output?'Revised contribution':r.status==='working'&&['running','stopping'].includes(job.status)?'Revising':'Revision '+r.status)+'</small>'+collaborationRevisionBody(r,job.id)+'</section>'+collaborationDecisionMarkup({...job.payload.collaboration,checks:(job.payload.collaboration.checks||[]).filter(check=>check.afterRevision)});
}
function collaborationDecisionMarkup(plan){
 const checks=plan.checks||[];
 if(plan.summary&&Array.isArray(plan.tasks)&&!plan.tasks.length)return '<div class="chat-message chat-handoff" data-plan-decision><small>Casey · '+(plan.outcome==='partial'?'Partial result - no agents called':plan.outcome==='unavailable'?'Required expertise unavailable - no agents called':'No additional agents needed')+'</small><div class="chat-prose">'+messageMarkup(plan.summary)+'</div></div>';
 return checks.map(check=>'<div class="chat-message chat-handoff" data-plan-decision><small>Casey · '+(check.done?(check.outcome==='partial'?'Partial result - stopping here':check.outcome==='unavailable'?'Required expertise unavailable - no additional agents will be called':'Enough to finish - no additional agents will be called'):'More work needed')+'</small><div class="chat-prose">'+messageMarkup(check.reason)+'</div></div>').join('');
}
// Keep the final reply self-contained, including saved plans whose answer omitted
// the Captain's separately recorded stopping reason. Never invent a rationale.
function collaborationCompletionMarkup(plan,answer){
 const defaultNames=planNames(plan);
 if(!answer)return '';
 const decision=(plan.checks||[]).filter(check=>check.done).at(-1)||(plan.outcome==='partial'?{outcome:'partial',reason:plan.summary,remaining:plan.remaining}:null);
 if(!decision)return '';
 const skipped=(plan.skippedRoles||[]).map(role=>defaultNames[role]).filter(Boolean);
 const reason=decision.reason&&!answer.includes(decision.reason)?messageMarkup(decision.reason):'';
 const remaining=decision.outcome==='partial'?(decision.remaining||plan.remaining||[]):[];
 if(!reason&&!skipped.length&&!remaining.length)return '';
 return '<div class="collaboration-completion" data-plan-completion><strong>'+ (decision.outcome==='partial'?'Partial result - what remains':decision.outcome==='unavailable'?'Why the team stopped':'Why this result is sufficient')+'</strong>'+reason+(remaining.length?'<ul>'+remaining.map(item=>'<li>'+escape(item)+'</li>').join('')+'</ul>':'')+(skipped.length?'<p class="studio-muted">Not called: '+escape(skipped.join(', '))+'. Their planned work was not performed.</p>':'')+'</div>';
}
function collaborationFileButtons(files,jobId,label='Open supporting file'){
 const paths=[...new Set((files||[]).filter(path=>typeof path==='string'&&!/\.html$/i.test(path)))];
 return paths.map((path,index)=>'<button type="button" class="studio-secondary" data-plan-file="'+escape(path)+'" data-plan-job="'+escape(jobId)+'">'+escape(label)+(paths.length>1?' '+(index+1):'')+'</button>').join('');
}
function livePlanActivityMarkup(job,role){
 const plan=job.payload.collaboration,jobId=job.id;
 const defaultNames=planNames(plan);
 const activity=plan.liveActivity;
 if(!activity||(role!==0&&role!==activity.role))return '';
 const labels={web_fetch:'Read webpage',web_search:'Search web',read:'Read file',write:'Save file',edit:'Edit file',apply_patch:'Update files',exec:'Run tool',tool:'Tool call'};
 const statuses={started:'Started',running:'Running',completed:'Completed',failed:'Failed'};
 const busy=activity.calls.some(call=>['started','running'].includes(call.status));
 const waiting=!activity.available?'Waiting for runtime activity':busy?'Waiting for tool completion':'Waiting for agent response';
 // Internal requests restart during checks and retries; the visible clock follows the whole task.
 const elapsed=collaborationTime(job);
 return '<section class="plan-live-activity" aria-label="Observed activity"><strong>'+escape(defaultNames[activity.role])+' · Live activity</strong><ol>'+activity.calls.map(call=>'<li data-activity-status="'+escape(call.status)+'"><span>'+escape(labels[call.tool]||'Tool call')+(call.target?' · '+escape(call.target):'')+'</span><small>'+escape((statuses[call.status]||'Started')+(call.status==='failed'&&call.errorLabel?' ('+call.errorLabel+')':''))+'</small></li>').join('')+'</ol><p>'+waiting+(elapsed?' · <span data-plan-elapsed="'+escape(jobId)+'">'+escape(elapsed)+'</span>':'')+'</p></section>';
}
function collaborationMarkup(job,role){
 const defaultNames=planNames(job.payload.collaboration);
 const plan=job.payload.collaboration,pending=['queued','running','waiting','stopping'].includes(job.status);
 const policyRequest=plan.policyRequests?.find(request=>request.status==='pending');
 const held=shieldReplyHeld(job,role),piece=plan.outputs?.[role],captain=role===0;
 const finalAnswer=collaborationAnswer(job),answer=captain?(finalAnswer||job.result?.error||''):piece?.answer||'';
 const uncalled=!captain&&!piece&&!plan.handoffs?.[role]&&(!pending||plan.responseReady||plan.skippedRoles?.includes(role));
 const preparing=job.status==='queued'?(data.agents||[]).filter(a=>a.workspacePreparation==='running'&&job.payload.roster?.some(m=>m.key===a.key)):[];
 const queued=preparing.length?'Queued - waiting for workspace setup ('+preparing.map(a=>a.name).join(', ')+').':'Queued - waiting for current studio work to finish.';
 const status=uncalled?'Casey did not call '+defaultNames[role]+' for this plan.':job.status==='queued'?queued:job.status==='cancelled'?'Stopped.':job.status==='stopping'?'Stopping after the current call…':job.events?.at(-1)?.title||'Waiting for the Captain…';
 const summary=captain&&plan.summary?'<div class="chat-message chat-handoff"><small>Captain’s plan</small><div class="chat-prose">'+messageMarkup(plan.summary)+'</div><ol class="crew-plan-assignments">'+(plan.tasks||[]).map(t=>'<li><strong>'+escape(defaultNames[t.role])+' · '+escape(window.BacCrewCatalog[t.role].collaboration.title)+'</strong>: '+escape(t.task)+(plan.skippedRoles?.includes(t.role)?' <small>Not called - '+(plan.outcome==='partial'?'plan ended with unfinished work':plan.outcome==='unavailable'?'required expertise unavailable':'no longer needed')+'</small>':'')+assignmentFitMarkup(t)+'</li>').join('')+'</ol>'+declinedAssignmentsMarkup(job)+'</div>':'';
 const outputRoles=collaborationRoleOrder(plan).filter(i=>plan.outputs?.[i]);
 const contributions=captain?outputRoles.map(i=>{const p=plan.outputs[i];return '<details class="crew-tool-activity" data-contribution-role="'+i+'"><summary>'+escape(p.name)+' · Contribution</summary>'+modelUsageMarkup(job,{role:i,phase:/^(Working|Recovering|Revising)/})+customSkillMarkup(p.activity)+'<div class="chat-prose">'+messageMarkup(p.answer)+'</div>'+collaborationFileButtons(p.files,job.id)+'</details>'+collaborationDecisionMarkup({...plan,checks:(plan.checks||[]).filter(check=>!check.afterRevision&&Number(check.afterRole)===i)});}).join(''):'';
 const handoff=!captain&&plan.handoffs?.[role]?'<div class="chat-message chat-handoff"><small>Casey → '+escape(defaultNames[role])+'</small><div class="chat-prose">'+messageMarkup(plan.handoffs[role].task)+'</div><small>Received: '+escape(['Captain’s task',...plan.handoffs[role].receivedFrom.map(i=>defaultNames[Number(i)]+"’s contribution")].join(' · '))+'</small></div>':'';
 return '<article class="chat-turn" data-collaboration-job="'+escape(job.id)+'">'+(captain||plan.origin?.role===role?'<div class="chat-message chat-user"><small>You</small><div>'+escape(job.payload.prompt).replace(/\n/g,'<br>')+imageHistoryMarkup(job.payload.images,job.id)+'</div></div>':'')+(captain?collaborationTimeMarkup(job):'')+(held?shieldReplyWait:summary+handoff+contributions+livePlanActivityMarkup(job,role)+(captain?collaborationRevisionMarkup(job):'')+(captain&&!outputRoles.length?collaborationDecisionMarkup(plan):'')+'<div class="chat-message chat-agent"><small>'+escape(defaultNames[role])+' · '+(captain?'Team collaboration':'Specialist contribution')+'</small>'+modelUsageMarkup(job,{role,latest:captain,phase:captain?/^(Reviewing|Finalizing|Checking)/:/^(Working|Recovering|Revising)/})+'<div class="chat-prose">'+messageMarkup(answer||status)+'</div>'+(captain?collaborationCompletionMarkup(plan,finalAnswer):'')+'</div>')+(!held&&!captain&&plan.revision?.role===role?collaborationRevisionMarkup(job):'')+(captain&&job.status==='waiting'?'<button type="button" class="studio-primary mission-policy-notice" data-review-task-policy>Review OpenShell request'+(policyRequest?.name?' for '+escape(policyRequest.name)+' Agent':'')+'</button>':'')+(pending?'<div class="chat-progress" role="status">'+escape(status)+(job.status!=='stopping'?chatStopButton(job.id,true,false,plan.responseReady?'Stop reactions':'Stop'):'')+'</div>':'')+(held?'':'<div class="chat-result-actions">'+webpageButtons(captain?Object.values(plan.webpages||{}).flat():piece?.files,job.id)+(captain?'':collaborationFileButtons(piece?.files,job.id))+'</div>')+(captain&&!held?roundtableMarkup(job):'')+'</article>';
}
function collaborationHistoryMarkup(job){
 const held=shieldReplyHeld(job,0),pending=['queued','running','waiting','stopping'].includes(job.status);
 const answer=collaborationAnswer(job)||job.result?.error||(pending?'The team is collaborating…':job.status==='cancelled'?'Stopped.':'No final reply was returned.');
 return '<article class="chat-turn" data-collaboration-history="'+escape(job.id)+'"><div class="chat-message chat-user"><small>You</small><div>'+messageMarkup(job.payload.prompt)+'</div></div><div class="chat-message chat-agent"><small>Casey · Team collaboration</small>'+collaborationTimeMarkup(job)+(held?shieldReplyWait:'<div class="chat-prose">'+messageMarkup(answer)+'</div>'+collaborationCompletionMarkup(job.payload.collaboration,collaborationAnswer(job)))+(held?'':collaborationDecisionMarkup(job.payload.collaboration)+webpageButtons(job.result?.files||Object.values(job.payload.collaboration.webpages||{}).flat(),job.id))+'<button type="button" class="studio-secondary" data-open-collaboration>View team conversation</button></div></article>';
}
function showCollaboration(){selectedCrewRole=0;selectedOpenTaskVisitor='';setRoom('mission');root.dataset.crewDetails='true';renderCrewPassport();}
function teamRuntime(){if(data.teamConnection?.shared)return {...runtime,teamModel:data.teamConnection.ready,teamReady:data.teamConnection.ready&&!!runtime.gateway};return data.teamConnection?.provider==='local'?{...runtime,teamModel:!!data.teamConnection.local?.model,teamReady:!!data.teamConnection.local?.model&&!!runtime.gateway}:runtime;}
function teamReady(){return teamRuntime().teamReady??runtime.ready;}
function teamModel(role){
 if(data.teamConnection?.shared){const source=data.teamConnection.effectiveSource,connections=runtime.modelConnections?.connections;if(source==='local'||connections?.api?.provider!=='nvidia'){const id=data.teamConnection.model;return id?{id,label:id}:null;}}
 if(data.teamConnection?.provider==='local'){const id=data.teamConnection.local?.model;return id?{id,label:id}:null;}
 const id=data.teamSelections?.find(row=>row.role===role)?.id,models=runtime.teamModels||[];
 if(role===0){
  if(!id)return null;
  const capable=runtime.modelConnections?.connections?.api?.automatic?.roles?.find(row=>row.key==='capable'&&row.id===id);
  return {id,label:capable?.label||models.find(row=>row.id===id)?.label||id};
 }
 return models.find(model=>model.id===id)||(id?{id,label:id==='auto'?'Model routing (NeMo Switchyard)':id,connected:id==='auto'?false:undefined}:models.find(model=>model.id==='auto')||models[[0,5,7].includes(role)?0:1]);
}
let crewDocumentUpload=false;
const crewDocumentSelections=new Map();
const crewExampleDocuments=new Set(goalExamples.filter(choice=>choice.document).map(choice=>'inbox/'+choice.document));
function crewDocumentSelection(){
 const epoch=data.crewChatReset?.epoch||'';
 let selection=crewDocumentSelections.get(selectedScenario);
 if(!selection||selection.epoch!==epoch){selection={epoch,excluded:new Set(),uploaded:new Set(),example:'',lockedExample:''};crewDocumentSelections.set(selectedScenario,selection);}
 return selection;
}
function renderCrewDocuments(){
 const files=[...(data.crewDocuments||[])],paths=new Set(files.map(f=>f.path)),selection=crewDocumentSelection(),excluded=selection.excluded;
 if(selectedCrewRole===0&&!selectedOpenTaskVisitor&&/^\s*(?:\/(?:goals?|plans?)\s*)?$/i.test(el('crew-prompt').value)){selection.example='';selection.lockedExample='';selection.teamMode='';}
 // Browsing templates only changes a local attachment draft. Save on submission.
 const example=goalExamples.find(choice=>choice.document&&'inbox/'+choice.document===selection.example);
 if(example&&!paths.has(selection.example))files.push({path:selection.example,pendingExample:example});
 // Previously submitted samples remain saved, but only attach to their own draft.
 const docs=files.filter(f=>(!crewExampleDocuments.has(f.path)||selection.example===f.path||selection.uploaded.has(f.path))&&/\.(pdf|pptx|xlsx|txt|md|csv)$/i.test(f.path)&&!/^(?:plan-input|plan|chat)-[0-9a-f]{24}(?:-|\.)/.test(f.path.split('/').at(-1))&&!(/\.(pdf|pptx|xlsx)\.txt$/i.test(f.path)&&paths.has(f.path.slice(0,-4))));
 const box=el('crew-documents');box.hidden=selectedCrewRole!==0||(!docs.length&&!crewDocumentUpload);
 box.innerHTML=docs.map(f=>{const locked=selection.lockedExample===f.path;return '<div class="studio-attachment"><input type="checkbox" aria-label="Attach '+escape(f.path.slice(6))+'" data-crew-document="'+escape(f.path)+'" '+(excluded.has(f.path)?'':'checked')+' '+(crewDocumentUpload||locked?'disabled':'')+(locked?' title="Required for this example" data-required-example="true"':'')+'><button type="button" data-attachment-preview="'+escape(f.path)+'" title="Open file in a new tab">'+escape(f.path.slice(6))+'</button></div>';}).join('')+(crewDocumentUpload?'<small role="status">Adding document…</small>':'');
 return docs.filter(f=>!excluded.has(f.path));
}
el('crew-documents').addEventListener('change',event=>{const path=event.target.dataset.crewDocument;if(path){const selection=crewDocumentSelection(),excluded=selection.excluded;if(selection.lockedExample===path){event.target.checked=true;excluded.delete(path);}else if(event.target.checked)excluded.delete(path);else excluded.add(path);}});
el('crew-documents').addEventListener('click',event=>{
 const button=event.target.closest('[data-attachment-preview]');
 if(button){
  const path=button.dataset.attachmentPreview;
  const sample=!data.crewDocuments?.some(file=>file.path===path)&&goalExamples.find(choice=>choice.document&&'inbox/'+choice.document===path);
  openAttachmentTab(path,'0',sample?{content:sample.documentContent}:undefined);
 }
});
el('crew-document-add').onclick=()=>el('crew-document-input').click();
el('crew-document-input').onchange=async event=>{await uploadCrewDocuments([...event.target.files]);event.target.value='';};
async function uploadCrewDocuments(files){
 if(selectedCrewRole!==0||crewDocumentUpload||el('crew-document-add').disabled)return;
 const target=agentId,selection=crewDocumentSelection();crewDocumentUpload=true;syncCrewComposer();renderCrewDocuments();
 try{
  for(const file of files){
   if(file.size>10*1024*1024)throw new Error(file.name+': Choose a file of 10 MB or smaller.');
   const binary=/\.(pdf|pptx|xlsx)$/i.test(file.name);let content;
   if(binary){const bytes=new Uint8Array(await file.arrayBuffer());let raw='';for(let i=0;i<bytes.length;i+=8192)raw+=String.fromCharCode(...bytes.subarray(i,i+8192));content=btoa(raw);}
   else content=await documentText(file);
   const result=await api('upload',{crewRole:0,name:file.name,content,...(binary?{encoding:'base64'}:{})},target);
   selection.uploaded.add(result.path);
   selection.excluded.delete(result.path);
  }
  await refresh();return true;
 }catch(error){el('crew-chat-error').textContent=error.message;el('crew-chat-error').hidden=false;return false;}
 finally{crewDocumentUpload=false;syncCrewComposer();renderCrewDocuments();}
}
for(const type of ['dragover','drop'])el('crew-chat').addEventListener(type,event=>{
 if(![...event.dataTransfer.types].includes('Files')||selectedCrewRole!==0)return;
 event.preventDefault();if(type==='drop')uploadCrewDocuments([...event.dataTransfer.files]);
});
function syncCrewComposerSize(){
 const form=el('crew-chat'),prompt=el('crew-prompt');
 const hasHistory=(data.crewChats||[]).some(job=>job.payload?.crewRole===0||job.payload?.collaboration);
 const hasDraft=!/^\s*(?:\/(?:goals?|plans?)\s*)?$/i.test(prompt.value);
 const attachments=crewDocumentUpload||pendingImages(true).length||el('crew-documents').querySelector('input:checked');
 form.classList.toggle('is-reading',selectedScenario==='plan'&&selectedCrewRole===0&&!selectedOpenTaskVisitor&&hasHistory&&!crewComposerEditing&&!hasDraft&&!attachments&&el('crew-chat-error').hidden);
}
el('crew-chat').addEventListener('focusin',()=>{crewComposerEditing=true;if(!crewComposerPointer)syncCrewComposerSize();});
// Finish a pointer click before resizing so Team/attachment buttons do not
// move out from under the pointer between pressing and releasing it.
el('crew-chat').addEventListener('pointerdown',()=>{crewComposerPointer=true;});
el('crew-chat').addEventListener('click',()=>{crewComposerPointer=false;crewComposerEditing=true;syncCrewComposerSize();});
for(const type of ['pointerup','pointercancel'])document.addEventListener(type,()=>{
 if(crewComposerPointer)setTimeout(()=>{crewComposerPointer=false;syncCrewComposerSize();},0);
});
el('crew-chat').addEventListener('focusout',event=>{
 if(event.relatedTarget&&!el('crew-chat').contains(event.relatedTarget)){crewComposerEditing=false;syncCrewComposerSize();}
});
document.addEventListener('pointerdown',event=>{
 if(!el('crew-chat').contains(event.target)){crewComposerEditing=false;syncCrewComposerSize();}
},{capture:true});
function syncCrewComposer(){
 el('crew-chat').hidden=!!selectedOpenTaskVisitor;
 if(selectedOpenTaskVisitor){el('crew-send').disabled=true;el('crew-documents').hidden=true;syncGoalExamples(true);return;}
 const activePlan=(data.crewChats||[]).find(j=>j.payload?.collaboration&&['queued','running','waiting','stopping'].includes(j.status));
 const captainPlanning=selectedCrewRole===0&&!!activePlan;
 const visitor=assignedVisitor(selectedCrewRole);
 const visitorMissing=visitor&&!visitorAvailable(visitor);
 const memberWorking=!!visitor&&(data.agents||[]).some(a=>a.key===visitor.key&&a.pending>0)||(data.crewChats||[]).some(j=>['queued','running','waiting','stopping'].includes(j.status)&&(j.payload?.collaboration?(['running','stopping'].includes(j.status)&&j.payload.collaboration.activeRole===selectedCrewRole):j.payload?.crewRole===selectedCrewRole));
 const blocked=resetInProgress||visitorMissing||(visitor?!personalReady(visitor,'team'):!teamReady())||!!visitor?.skills?.includes('radar')||!!data.bacResetting||captainPlanning||memberWorking||crewDocumentUpload;
 el('crew-document-add').hidden=selectedCrewRole!==0;el('crew-document-add').disabled=blocked;
 renderCrewDocuments();
 const commandOnly=selectedScenario==='plan'&&selectedCrewRole===0&&/^\s*\/(?:goals?|plans?)\s*$/i.test(el('crew-prompt').value);
 el('crew-prompt').disabled=blocked;el('crew-send').disabled=blocked||crewChatSending||commandOnly;
 syncGoalExamples(resetInProgress||!!data.bacResetting||captainPlanning||memberWorking||crewDocumentUpload||crewChatSending);
 el('crew-hired-option').closest('.studio-goal-toolbar').hidden=selectedCrewRole!==0;
 el('crew-hired-option').hidden=selectedScenario!=='plan'||selectedCrewRole!==0;
 const teamMode=effectiveTeamMode(),teamLocked=resetInProgress||!!activePlan||crewChatSending||!!data.bacResetting;
 el('crew-team-mode').querySelectorAll('[data-team-mode]').forEach(button=>{button.setAttribute('aria-pressed',String(button.dataset.teamMode===teamMode));button.disabled=teamLocked||!!crewDocumentSelection().teamMode;});
 el('crew-team-hint').textContent=teamMode==='hired'
  ? 'Casey works only with your hired agents.'
  : 'Casey can bring in standby specialists as needed.';
 el('crew-chat-connection').hidden=!blocked;
 el('crew-chat-connection').textContent=visitorMissing?'This agent was removed. Start a new task with Casey.':visitor?.skills?.includes('radar')?'Tech Radar uses Heartbeat. Manual chat is disabled.':crewDocumentUpload?'Adding document…':resetInProgress?'Resetting…':data.bacResetting?'Stopping '+(stageScenarios.find(s=>s.id===selectedScenario)?.title||'the scenario')+' and resetting…':captainPlanning?'Plan in progress · Casey is coordinating the team. Messaging resumes when the plan ends.':memberWorking?'Task in progress · Messaging resumes when this agent finishes.':!(visitor?personalModel(visitor,'team').connected:(teamRuntime().teamModel??runtime.model))?(visitor?personalModelNotice(visitor,'team'):'Model not connected. Enable Local or External Endpoint in Settings.'):'Run ./bac start on this computer to connect the team runtime.';
 syncCrewComposerSize();
}
function renderCrewPassport(){
 syncFileButtons();
 const epoch=selectedScenario+':'+(data.crewChatReset?.epoch||'');
 if(epoch!==crewResetEpoch){
  const resetChanged=crewResetEpoch.split(':')[0]===selectedScenario;crewResetEpoch=epoch;if(resetChanged){if(selectedScenario==='plan')preferredTeamMode='hired';for(const key of crewDrafts.keys())if(key.startsWith(selectedScenario+':'))crewDrafts.delete(key);}crewChatKey='';crewChatSignature='';el('crew-prompt').value=defaultCrewPrompt(selectedCrewRole);
  for(const key of chatImageDrafts.keys())if(key.includes(':crew:')&&key.includes(':'+selectedScenario+':'))chatImageDrafts.delete(key);
 }
 if(room!=='mission')return;
 const i=selectedCrewRole,binding=selectedCrewVisitor(),visitor=(data.agents||[]).find(agent=>agent.key===binding?.key)||binding,name=visitor?.name||defaultNames[i],template=visitor?roleTemplates.find(template=>template.purpose===visitor.purpose):null,role=visitor?(template?.label||'Personal agent'):window.BacCrewCatalog[i].collaboration.title;
 const editable=visitorAvailable(visitor);
 el('crew-agent-actions').hidden=!editable;
 const reason=editable?crewAgentEditLock(visitor.key):'';
 el('crew-edit-agent').disabled=!!reason;el('crew-edit-agent').title=reason;
 el('crew-agent-skills').hidden=!editable;
 el('crew-agent-skills').innerHTML=editable?(visitor.skills||[]).map(skill=>'<span class="studio-skill-badge">'+escape(titles[skill]||capabilities[skill]?.[0]||skill)+'</span>').join(''):'';
 const avatar=visitor?.avatar||window.BacCampus?.inspect().crewAvatars?.[i]||{};
 el('crew-number').textContent=selectedOpenTaskVisitor?'Standby':String(i+1).padStart(2,'0')+' / '+roles.length;
 el('crew-name').textContent=name;syncTeamTotalTime();el('crew-role').textContent=role;
 const model=visitor?personalModel(visitor,'team'):teamModel(i);renderCrewModel(model,visitor);
 if(!teamModelDialog.hidden)renderModelResults();
 renderAvatarPortrait(el('crew-portrait'),avatar);
 el('crew-policy').hidden=(visitor&&!visitorAvailable(visitor))||(visitor?.protection||window.BacCrewCatalog[i].protection)!=='openshell';
 syncPolicyBadges();
 if(selectedOpenTaskVisitor){
  syncCrewComposer();
  const summary=visitor.skills?.includes('radar')?'Heartbeat paused in Open Task.':template?.summary||visitor.purpose||'Ready for Casey to assign a task.';
  const content='<p class="chat-empty">'+escape(summary)+'</p>';
  if(el('crew-conversation').innerHTML!==content)el('crew-conversation').innerHTML=content;
  crewChatSignature='';return;
 }
 const key=crewDraftKey(i),switched=key!==crewChatKey;
 if(switched){crewComposerEditing=false;if(crewChatKey)crewDrafts.set(crewChatKey,el('crew-prompt').value);crewChatKey=key;el('crew-prompt').value=crewDrafts.get(key)??defaultCrewPrompt(i);el('crew-chat-error').hidden=true;}
 renderImageDrafts(true);
 el('crew-prompt').placeholder='Message '+name+'…'+(i===0?' or /goal a task with the team':'');
 el('crew-prompt').dataset.planEnabled=String(i===0);syncCrewComposer();
 const turns=(data.crewChats||[]).filter(j=>j.payload.crewRole===i||(j.payload.collaboration&&(j.payload.collaboration.origin?.role===i||j.payload.collaboration.handoffs?.[i]||j.payload.collaboration.tasks?.some(t=>t.role===i)||j.payload.collaboration.activeRole===i))).map(j=>({...j,direct:true}));
 turns.sort((a,b)=>a.created-b.created);
 const signature=JSON.stringify([key,[...pendingChatStops],(data.agents||[]).map(a=>[a.key,!!a.deleting,a.workspacePreparation]),turns.map(j=>[j.id,j.status,j.result,j.payload.metrics,j.payload.roundtable?.replies,j.payload.roundtable?.availableGuests,j.payload.collaboration?.liveActivity?{...j.payload.collaboration,liveActivity:{...j.payload.collaboration.liveActivity,elapsed:0}}:j.payload.collaboration,j.events?.at(-1),shieldReplyHeld(j,i)])]);
 updateCollaborationTimers(el('crew-conversation'),turns);
 if(signature===crewChatSignature)return;
 crewChatSignature=signature;const log=el('crew-conversation'),follow=switched||log.scrollHeight-log.scrollTop-log.clientHeight<70,top=log.scrollTop;
 const openMenus=new Set(Array.from(log.querySelectorAll('[data-reaction-menu][open]'),item=>item.dataset.reactionMenu));
 log.innerHTML=turns.length?turns.map(j=>{
 if(j.payload.collaboration)return i!==0&&j.payload.collaboration.origin?.role===i&&!j.payload.collaboration.handoffs?.[i]?collaborationHistoryMarkup(j):collaborationMarkup(j,i);
 const held=shieldReplyHeld(j,i),pending=['queued','running','waiting','stopping'].includes(j.status);
 const answer=j.result?.answer||j.result?.error||'';
 const request=j.payload.prompt||'Describe the attached image.';
 const status={queued:'Waiting to start…',running:'Working on your message…',waiting:'Waiting for a decision.',stopping:'Stopping…',cancelled:'Stopped.',error:'This message could not finish.'}[j.status];
 return '<article class="chat-turn"><div class="chat-message chat-user"><small>You</small><div>'+escape(request).replace(/\n/g,'<br>')+imageHistoryMarkup(j.payload.images,j.id)+'</div></div><div class="chat-message chat-agent"><small>'+escape(name)+'</small>'+modelUsageMarkup(j,{role:i})+(held?shieldReplyWait:customSkillMarkup(j.result?.activity)+'<div class="chat-prose">'+messageMarkup(answer||status||'No text reply was returned.')+'</div>'+crewActivityMarkup(j,i)+webpageButtons(j.result?.files,j.id)+(pending?'<div class="chat-progress">'+chatStopButton(j.id,true,j.status==='stopping')+'</div>':''))+'</div>'+(i===0?roundtableMarkup(j):'')+'</article>';
 }).join(''):i===0?'':'<p class="chat-empty">'+escape(currentCollaboration()?window.BacCrewCatalog[i].collaboration.description:roles[i][2])+'</p>';
 for(const menu of log.querySelectorAll('[data-reaction-menu]'))menu.open=openMenus.has(menu.dataset.reactionMenu);
 loadChatImages(log,agentId);
 if(follow)log.scrollTop=log.scrollHeight;else log.scrollTop=top;
}
el('crew-policy').onclick=async()=>{const visitor=selectedCrewVisitor();if(visitor){await switchAgent(visitor.key);if(agentId===visitor.key)openPolicy();}else openPolicy(selectedCrewRole);};
el('crew-chat').onsubmit=async e=>{
 e.preventDefault();syncCrewComposer();if(el('crew-send').disabled)return;
 const owner=agentId,index=selectedCrewRole,key=crewDraftKey(index),draft=captureChatDraft(true),teamChoice=draftTeamMode();
 if(isPlanCommand(draft.prompt)&&(selectedScenario!=='plan'||index!==0)){
  el('crew-chat-error').textContent=planLocationHint;
  el('crew-chat-error').hidden=false;return;
 }
 const docs=index===0?renderCrewDocuments():[],scenario=selectedScenario,visitor=assignedVisitor(index);
 crewChatSending=true;crewDocumentUpload=docs.some(file=>file.pendingExample);syncCrewComposer();el('crew-chat-error').hidden=true;
 try{
  for(const file of docs){
   if(!file.pendingExample)continue;
   const sample=file.pendingExample;
   const saved=await api('upload',{crewRole:0,name:sample.document,content:sample.documentContent},owner,scenario);
   file.path=saved.path;
  }
  if(crewDocumentUpload)await refresh();
  let requestPrompt=draft.prompt;
  if(docs.length)requestPrompt+='\n\nAttached documents (use these files):\n'+docs.map(file=>file.path.slice(6)).join('\n');
  const selectedExample=goalExamples.find(choice=>draft.prompt===goalPrompt(choice));
  const result=await api('jobs',visitor?{kind:'chat',modelStage:'team',prompt:requestPrompt,images:draft.images}:{kind:'crew-chat',crewRole:index,prompt:requestPrompt,images:draft.images,...(scenario==='plan'&&index===0&&isPlanCommand(draft.prompt)?{teamMode:teamChoice,...(selectedExample?{goalExample:selectedExample.id}:{})}:{})},visitor?.key||owner,scenario);
  crewComposerEditing=false;acknowledgeChatDraft(draft);if(visitor){await switchAgent(visitor.key);setRoom('lounge');}await refresh();if(result.collaboration)stageCollaboration(result);
 }
 catch(error){if(crewChatKey===key){el('crew-chat-error').textContent=error.message;el('crew-chat-error').hidden=false;}}
 finally{crewChatSending=false;crewDocumentUpload=false;syncCrewComposer();}
};
el('crew-prompt').addEventListener('input',()=>{
 const displayedMode=el('crew-team-mode').querySelector('[aria-pressed="true"]')?.dataset.teamMode;
 crewComposerEditing=true;clearPlanLocationHint(true);syncCrewComposer();
 if(displayedMode!==effectiveTeamMode())render();
});
el('crew-prompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!el('crew-send').disabled)el('crew-chat').requestSubmit(el('crew-send'));}});
el('crew-conversation').onclick=async e=>{const file=e.target.closest('[data-plan-file]');if(file){await openFile(file.dataset.planFile,file.dataset.planJob);return;}const button=e.target.closest('[data-crew-chat-stop]');if(!button||button.disabled)return;await stopChat(button.dataset.crewChatStop,true);};

function roundtableMarkup(job){
 const {roundtable:meeting,collaboration:plan}=job.payload;
 if(!meeting||(plan&&(!plan.responseReady||plan.outcome==='unavailable')))return '';
 const currentHires=new Set((data.agents||[]).filter(agent=>!agent.deleting).map(agent=>agent.key));
 const available=(meeting.availableGuests||[]).filter(member=>currentHires.has(member.key));
 const requested=meeting.members||[];
 const skipped=plan?[]:meeting.skipped||[];
 if(!requested.length&&!skipped.length&&!available.length)return '';
 const closed=job.status==='done';
 const cards=requested.map(member=>{
  const reply=meeting.replies?.[member.key]||{};
  const text=reply.answer||reply.error||reply.reason||meeting.reason||(
   job.status==='cancelled'?'Reaction cancelled.':closed?'No reaction was recorded.':'Waiting for '+member.name+'…');
  const retry=closed&&currentHires.has(member.key)&&(reply.status==='error'||reply.retryable);
  const action=retry?'<button type="button" class="reaction-retry" aria-label="Retry reaction from '+escape(member.name)+'" data-retry-reaction="'+escape(member.key)+'" data-reaction-job="'+escape(job.id)+'"><span aria-hidden="true">↻</span> Retry reaction</button>':'';
  return '<article class="chat-message chat-agent" data-roundtable-reply="'+escape(member.key)+'"><small>'+escape(member.name)+' · '+escape(member.tonePrompt||member.tone||'')+'</small>'+customSkillMarkup(reply.activity)+'<div class="chat-prose">'+messageMarkup(text)+'</div>'+action+'</article>';
 }).join('');
 const intro=plan&&meeting.availableGuests&&requested.length?'<p>Casey invited '+escape(requested[0].name)+' to share a reaction.</p>':'';
 const menu=available.length&&closed?'<details class="reaction-choices" data-reaction-menu="'+escape(job.id)+'"><summary>Ask another agent</summary><div>'+available.map(member=>'<button type="button" class="reaction-retry" data-ask-reaction="'+escape(member.key)+'" data-reaction-job="'+escape(job.id)+'">Ask '+escape(member.name)+'</button>').join('')+'</div></details>':'';
 return '<section class="crew-roundtable-log"><h4>Your agents’ take</h4>'+intro+skipped.map(member=>'<p class="studio-muted" data-roundtable-skipped="'+escape(member.key)+'">'+escape(member.name)+' · Skipped: '+escape(member.detail)+'</p>').join('')+cards+menu+'</section>';
}

root.addEventListener('click',async event=>{
 const button=event.target.closest('[data-ask-reaction],[data-retry-reaction]');if(!button||button.disabled)return;
 button.disabled=true;
 const first='askReaction' in button.dataset;
 try{await api(first?'ask-reaction':'retry-reaction',{id:button.dataset.reactionJob,member:first?button.dataset.askReaction:button.dataset.retryReaction});await refresh();}
 catch(error){alert(error.message,'error');button.disabled=false;}
});

async function openRequestedPolicy(button){
 if(button.disabled)return;
 const task=(data.crewChats||[]).find(item=>item.id===button.dataset.policyJob);
 const request=task?.payload.collaboration?.policyRequests?.find(item=>item.id===button.dataset.policyId);
 if(!request||task.status!=='waiting'||request.status!=='pending')return;
 if(request.role===null){
  await switchAgent(request.owner);
  if(agentId!==request.owner||activeSurface!=='control'||!surfaceDialog.open)return;
 }
 openPolicy(request.role,true);
}

root.addEventListener('bac:review-task-access',event=>{
 const job=currentCollaboration();
 if(job?.id!==event.detail||!taskNeedsPolicyReview(job))return;
 openSurface('control');
 const button=el('lanes').querySelector('[data-task-policy="policy"]');
 if(!button||button.dataset.policyJob!==job.id||button.disabled)return;
 button.scrollIntoView({block:'center'});button.focus({preventScroll:true});
 openRequestedPolicy(button);
});

el('lanes').addEventListener('click',async event=>{
 const button=event.target.closest('[data-task-policy]');if(!button||button.disabled)return;
 if(button.dataset.taskPolicy==='policy'){await openRequestedPolicy(button);return;}
 const id=button.dataset.policyId,job=button.dataset.policyJob,owner=agentId;
 if(taskPolicyPending.has(id)||policySaving)return;
 taskPolicyPending.add(id);renderMissionControl();
 try{await api('task-policy-decision',{id:job,request:id,action:button.dataset.taskPolicy},owner);}
 catch(error){alert(error.message,'error');}
 finally{taskPolicyPending.delete(id);await refresh();renderMissionControl();}
});
el('crew-conversation').addEventListener('click',event=>{
 if(event.target.closest('[data-review-task-policy]')){
  openSurface('control');
  requestAnimationFrame(()=>el('lanes').querySelector('.mission-policy-request [data-task-policy]')?.closest('.mission-policy-request').scrollIntoView({block:'center',behavior:'smooth'}));
 }else if(event.target.closest('[data-open-collaboration]'))showCollaboration();
});
