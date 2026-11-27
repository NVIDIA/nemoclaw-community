// SPDX-License-Identifier: Apache-2.0

  const usageChevron='<svg class="usage-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 10 4-4 4 4"/></svg>';
  const usageSummary=(cpu='—',ram='—',context='—')=>[['CPU',cpu],['RAM',ram],['Context',context]].map(([label,value])=>`<span class="usage-stat"><span class="usage-label">${label}</span> <span class="usage-value">${value}</span></span>`).join('')+usageChevron;
  const meter=document.createElement('details');meter.id='studio-telemetry';meter.innerHTML=`<summary aria-label="Runtime usage" aria-controls="studio-usage-panel">${usageSummary()}</summary><div id="studio-usage-panel" class="usage-panel" role="region" aria-label="Runtime usage details"></div>`;
  root.querySelector('.campus-scene-bottom .row').prepend(meter);
  const count=n=>typeof n==='number'?Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(n):'—';
  const percent=n=>typeof n==='number'?n.toFixed(1)+'%':'—';
  const speed=n=>typeof n==='number'&&Number.isFinite(n)?n.toFixed(1)+' tok/s':'—';
  let telemetryBusy=false, telemetrySnapshot=null;
  function missionTelemetryRecords(snapshot){
    const job=currentCollaboration();
    if(!job)return [];
    const latest=new Map();
    for(const record of Object.values(job.payload?.metrics||{})){
      const previous=latest.get(record.agent);
      if(!previous||typeof record.measuredAt!=='number'||typeof previous.measuredAt!=='number'||record.measuredAt>=previous.measuredAt)latest.set(record.agent,record);
    }
    // payload.roster contains available hired agents, not the role-indexed
    // mission team. Recorded turns are the authoritative participant list and
    // include Casey, standby specialists, hired agents, and closing reactions.
    return [...latest.values()].map(record=>{
      const cumulative=snapshot.agents.find(a=>a.agent===record.agent&&a.crew===true)||{};
      return {...record,total:cumulative.total,calls:cumulative.calls};
    });
  }
  function renderTelemetry(snapshot){
    const records=room==='mission'?missionTelemetryRecords(snapshot):snapshot.agents.filter(a=>!a.crew);
      const knownRecords=records.filter(a=>typeof a.context==='number'&&typeof a.limit==='number'&&a.limit>0);
      const highest=knownRecords.reduce((best,a)=>!best||a.context/a.limit>best.context/best.limit?a:best,null);
      const summary=meter.querySelector('summary');
      summary.innerHTML=usageSummary(percent(snapshot.host.cpu),percent(snapshot.host.memory),highest?percent(highest.context/highest.limit*100):'—');
      summary.title=highest?`${highest.name}: ${count(highest.context)} / ${count(highest.limit)} tokens · last reported · highest agent utilization`:'Context usage has not been reported yet.';
      meter.querySelector('.usage-panel').innerHTML=`<div class="spread usage-heading"><strong>Context per agent</strong><span>Last reported</span></div>${records.length?records.map(a=>{
        const known=typeof a.context==='number'&&typeof a.limit==='number'&&a.limit>0;
        const p=known?a.context/a.limit*100:null;
        const routed=modelRoutingText(a);
        return `<div class="usage-agent" title="${escape([a.model,a.measuredAt?new Date(a.measuredAt*1000).toLocaleString():null].filter(Boolean).join(' · '))}"><div class="spread"><strong>${escape(a.name)}</strong><span>${a.status?escape(a.status)+' · ':''}${percent(p)}</span></div>${routed?`<small>${escape(routed)}</small>`:''}<div class="usage-track"><i style="width:${known?Math.min(100,p):0}%"></i></div><div class="spread"><span>${count(a.context)} / ${count(a.limit)} configured limit</span><span>${a.calls?count(a.total):'—'} cumulative</span></div><div class="spread" title="Output tokens / response time, including waiting and tools."><span>Avg output speed</span><span>${speed(a.outputTokensPerSecond)}</span></div></div>`;
      }).join(''):'<p class="usage-empty">Context appears after an agent runs.</p>'}<div class="usage-total spread"><span>Total tokens</span><strong>${count(snapshot.total)}</strong></div><small>Across all recorded runs. ${room==='mission'?'Context and speed are for this mission.':'Context and speed reflect each agent’s latest response.'} ${snapshot.unreportedCalls?'Some usage is unreported.':''}</small><hr><div class="spread usage-host"><strong>App host</strong><span>CPU ${percent(snapshot.host.cpu)} · RAM ${percent(snapshot.host.memory)}</span></div><small>CPU and RAM on the app server.</small>`;
  }
  async function updateTelemetry(){
    if(!connected||document.hidden||telemetryBusy)return;
    telemetryBusy=true;
    const requestedAgent=agentId;
    try{
      const snapshot=await api('telemetry',undefined,'');
      if(!connected||document.hidden||requestedAgent!==agentId)return;
      telemetrySnapshot={agentId,snapshot};
      renderTelemetry(snapshot);
    }catch{meter.querySelector('summary').removeAttribute('title');meter.querySelector('summary').innerHTML=`<span class="usage-unavailable">Usage unavailable</span>${usageChevron}`;meter.querySelector('.usage-panel').textContent='Usage unavailable. Reconnecting…';}
    finally{telemetryBusy=false;}
  }
  meter.addEventListener('toggle',()=>{if(meter.open)updateTelemetry();});
  function dismissTelemetry(event){if(meter.open&&!meter.contains(event.target))meter.open=false;}
  // Do not consume the outside interaction: the clicked control must still work.
  document.addEventListener('pointerdown',dismissTelemetry,true);
  document.addEventListener('click',dismissTelemetry,true);
  document.addEventListener('focusin',dismissTelemetry);
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&meter.open){event.preventDefault();event.stopPropagation();meter.open=false;meter.querySelector('summary').focus({preventScroll:true});}
  },true);
  function repaintTelemetry(){
    if(telemetrySnapshot?.agentId===agentId)renderTelemetry(telemetrySnapshot.snapshot);
    else renderTelemetry({agents:[],host:{},total:null});
  }
  root.addEventListener('bac:state-rendered',repaintTelemetry);
  root.addEventListener('bac:world-room',()=>{meter.open=false;repaintTelemetry();updateTelemetry();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)updateTelemetry();});
  setInterval(updateTelemetry,5000);
