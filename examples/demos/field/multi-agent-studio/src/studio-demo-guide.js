// SPDX-License-Identifier: Apache-2.0

// Presenter aids are local drafts. Selecting an example never starts a task.
window.BacOverviewImages={agent:'__AGENT_BIG_PICTURE_DATA_URL__',openshell:'__OPENSHELL_OVERVIEW_DATA_URL__'};
const agentBlueprint=`<div class="agent-blueprint" aria-label="An agent combines a language model, instructions, skills and memory inside a tool runtime">
 <div class="agent-blueprint-input">Your request <span>or a scheduled Heartbeat</span></div><span class="agent-blueprint-arrow" aria-hidden="true">↓</span>
 <section class="agent-blueprint-runtime"><header>Agent runtime <small>OpenClaw coordinates the loop</small></header>
 <div class="agent-blueprint-parts"><article><b>Role &amp; voice</b><span>Purpose and behavior</span></article><article><b>Language model</b><span>Reasons and selects actions</span></article><article><b>Skills</b><span>Instructions for specific work</span></article><article><b>Memory &amp; files</b><span>Saved context and evidence</span></article></div>
 <div class="agent-blueprint-tools"><b>Permitted tools</b><span>Read, write, search or fetch</span><small>Read tool results → decide the next action → answer when ready.</small><small>OpenShell can isolate tool execution and restrict access.</small></div></section>
 <span class="agent-blueprint-arrow" aria-hidden="true">↓</span><div class="agent-blueprint-output">Response or saved result <span>Inspect the evidence; completion is not guaranteed.</span></div></div>`;
window.BacAgentBlueprint=agentBlueprint;
function goalHint(choice){return choice.detail;}
function goalPrompt(choice){const location='the city selected in Settings > Location';return choice.prompt.replace(location,()=>runtime.location?.city||location);}
el('crew-goal-choices').innerHTML='<div class="studio-goal-options">'+goalExamples.map(g=>`<button type="button" id="studio-goal-example-${escape(g.id)}" data-goal-example="${escape(g.id)}" data-goal-hint="${escape(goalHint(g))}" aria-pressed="false" title="${escape(goalHint(g))}" aria-controls="studio-crew-prompt">${escape(g.title)}</button>`).join('')+'</div>';
function syncGoalExamples(locked){
 const box=el('crew-examples');box.hidden=locked||selectedScenario!=='plan'||selectedCrewRole!==0||!!selectedOpenTaskVisitor;
 box.querySelectorAll('[data-goal-example]').forEach(button=>{
  const choice=goalExamples.find(g=>g.id===button.dataset.goalExample);
  button.disabled=locked||box.hidden;
  button.setAttribute('aria-pressed',String(el('crew-prompt').value===goalPrompt(choice)));
  button.dataset.goalHint=goalHint(choice);
  button.title=goalHint(choice);
 });
}
el('crew-goal-choices').onclick=event=>{
 const button=event.target.closest('[data-goal-example]');
 if(!button||button.disabled||selectedCrewRole!==0||selectedOpenTaskVisitor||selectedScenario!=='plan')return;
 syncCrewComposer();if(button.disabled)return;
 const choice=goalExamples.find(g=>g.id===button.dataset.goalExample),prompt=el('crew-prompt');
 el('crew-chat-error').hidden=true;
 const selection=crewDocumentSelection();
 selection.teamMode=choice.teamMode||'';
 selection.example=choice.document?'inbox/'+choice.document:'';
 selection.lockedExample=choice.requiredDocument?selection.example:'';
 if(selection.example)selection.excluded.delete(selection.example);
 prompt.value=goalPrompt(choice);prompt.dispatchEvent(new Event('input',{bubbles:true}));
 prompt.focus({preventScroll:true});prompt.setSelectionRange(prompt.value.length,prompt.value.length);prompt.scrollTop=0;
};
function issueReportPanel(){return `<details id="studio-issue-report" class="studio-issue-report"><summary>Issue report</summary><div id="studio-issue-report-content">
 <header class="studio-issue-heading"><div><h3>Multi-Agent Studio <span class="studio-issue-version">v${escape(buildInfo.version)}</span></h3></div></header>
 <dl class="studio-issue-details"><div><dt>Branch</dt><dd>${escape(buildInfo.branch||'Packaged build')}</dd></div><div><dt>Source commit</dt><dd><code>${escape(buildInfo.commit?.slice(0,12)||'Not recorded')}</code>${buildInfo.modified?'<span class="studio-issue-local">Local changes</span>':''}</dd></div></dl>
 <section class="studio-issue-runtime" aria-label="Pinned runtime versions"><h4>Pinned runtime</h4><dl>${Object.entries(buildInfo.runtime||{}).map(([key,value])=>`<div><dt>${escape(({node:'Node.js',openclaw:'OpenClaw',openshell:'OpenShell'})[key]||key)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl></section>
 <footer class="studio-issue-footer"><p>Build info and recent diagnostics.<br>No chat or file contents.</p><div class="studio-diagnostic-actions"><button type="button" class="studio-secondary" id="studio-copy-build">Copy diagnostics</button><button type="button" id="studio-download-diagnostics">Download</button></div></footer><p id="studio-build-copy-status" role="status"></p>
 </div></details>`;}
