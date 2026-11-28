// SPDX-License-Identifier: Apache-2.0

// Three.js is bundled above. The scene consumes the same workflow state as the board.
const app = document.getElementById('bac-planner');
const root = document.getElementById('agent-campus');
const el = name => document.getElementById('campus-' + name);
const api = window.BacDemo;
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const colors = [0x76b900, 0x55bfff, 0xf4b34f, 0xff8873, 0xb49aff, 0xcbddea, 0x55bfff, 0xb49aff, 0x55bfff, 0x76b900];
const hex = i => '#' + colors[i].toString(16);
function syncBrowserViewport(){
  const height=window.visualViewport?.height||window.innerHeight;
  document.documentElement.style.setProperty('--browser-viewport-height',Math.round(height)+'px');
}
syncBrowserViewport();
window.addEventListener('resize',syncBrowserViewport);
window.visualViewport?.addEventListener('resize',syncBrowserViewport);
let snapshot = api.snapshot(), selected = 0, sceneView = null;
function choose(i) {
  if(!snapshot.agents[i])return;
  selected=i;render();root.dispatchEvent(new CustomEvent('bac:live-select',{detail:i}));
}
function render() {
  el('roster').innerHTML=snapshot.agents.map((agent,i)=>agent.displayed===false?'':`<button data-campus-agent="${i}" data-lane="${agent.lane}" data-included="${agent.included!==false}" aria-pressed="${i===selected}"><b>${escape(agent.name)}</b><small>${escape(agent.role)}</small></button>`).join('');
  sceneView?.update(snapshot,selected);
}
el('roster').addEventListener('click',event=>{
  const button=event.target.closest('[data-campus-agent]');if(button)choose(Number(button.dataset.campusAgent));
});

/* STUDIO_SOUND */
/* WORLD_SCENE */
try {sceneView=createScene();}catch(error){el('fallback').hidden=false;root.dataset.renderer='fallback';console.warn('3D unavailable; accessible workflow controls remain available.',error.message);}
window.BacCampus={setScenario:id=>sceneView?.setScenario(id),setScenarioStatus:(rows,busy)=>sceneView?.setScenarioStatus(rows,busy),scenarios:options=>sceneView?.scenarios(options),protectionReplyDelay:(owner,role)=>sceneView?.protectionReplyDelay(owner,role),observeProtection:events=>sceneView?.observeProtection(events),observeExternalActivity:(jobs,owner)=>sceneView?.observeExternalActivity(jobs,owner),welcomeAgent:key=>sceneView?.welcomeAgent(key),finishArrival:()=>sceneView?.finishArrival(),setRoom:(room,options)=>sceneView?.setRoom(room,options),overview:options=>sceneView?.overview(options),setCollection:(agents,key)=>sceneView?.setCollection(agents,key),setDraft:profile=>sceneView?.setDraft(profile),inspect:()=>sceneView?.inspect()||{fallback:true},setLive:next=>{snapshot=next;selected=next.selected;render();}};
render();
