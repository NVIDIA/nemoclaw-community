// SPDX-License-Identifier: Apache-2.0

// One persistent floor plan. Room changes move the camera, never swap worlds.
const studioRooms={
  workshop:{group:workshopRoom,x:0,z:18,title:roomTitles.workshop,number:'01'},
  lounge:{group:loungeRoom,x:0,z:0,title:roomTitles.lounge,number:'02'},
  mission:{group:missionRoom,x:24,z:0,title:roomTitles.mission,number:'03'}
};
Object.entries(studioRooms).forEach(([id,entry])=>{entry.group.position.set(entry.x,0,entry.z);entry.group.visible=true;entry.group.userData.studioRoom=id;});
let overview=false,journey=null,viewHalfHeight=0;
const corridors=[],doorways=[],overviewLabels=[];
const navigationLayer=document.createElement('div');navigationLayer.className='world-navigation';viewport.append(navigationLayer);
navigationLayer.dataset.scenarioDensity=scenarioFloors.length>2?'compact':'normal';
const overviewControl=document.createElement('div');overviewControl.className='world-overview-control';navigationLayer.append(overviewControl);
const overviewButton=document.createElement('button');overviewButton.type='button';overviewButton.className='world-overview-button';overviewButton.dataset.worldOverview='';overviewButton.textContent='• See the whole studio';overviewButton.setAttribute('aria-pressed','false');overviewControl.append(overviewButton);
const studioVersion=document.createElement('span');studioVersion.className='world-build-version';studioVersion.textContent='v'+(/* BUILD_VERSION */);overviewControl.append(studioVersion);
const journeyNote=document.createElement('div');journeyNote.className='world-journey';journeyNote.setAttribute('role','status');journeyNote.setAttribute('aria-live','polite');journeyNote.hidden=true;navigationLayer.append(journeyNote);
const roomMap=document.createElement('nav');roomMap.className='world-room-map';roomMap.setAttribute('aria-label','Connected studio rooms');
roomMap.classList.add('world-scenario-map');
roomMap.innerHTML='<span class="world-map-caption">STUDIO MAP</span><div class="world-map-stages">'+Object.entries(studioRooms).map(([id,entry])=>{
  const destination=id==='mission'?'data-world-scenario="plan"':'data-world-room="'+id+'"';
  return '<button type="button" '+destination+'><i>'+entry.number+'</i><span>'+escape(entry.title)+'</span></button>';
}).join('')+'</div>';
navigationLayer.append(roomMap);
const roomGuides={
  workshop:{
    anchor:new THREE.Vector3(-.85,2.12,-3.92),
    intro:'Create an <button type="button" class="world-paper-term" data-paper-term="agent">agent</button> for a job you have in mind.',
    points:[
      'Name your agent, pick a character and choose how it speaks.',
      'Choose a role and review its <button type="button" class="world-paper-term" data-paper-term="skill">skills</button>. For a custom role, write a description and select Suggest skills.',
      'Choose whether to turn on <button type="button" class="world-paper-term" data-paper-term="openshell">OpenShell</button> protection, then select Hire my agent.'
    ],
    note:'Preset roles include their core skills. You can add more before hiring.'
  },
  lounge:{
    anchor:new THREE.Vector3(3.75,2.12,-5.78),
    intro:'Try your agent’s skills in a one-on-one conversation.',
    points:[
      'Select a hired agent to open its chat. Click its name to see its instructions and files.',
      'Ask for something its skills cover, such as a forecast from Weather buddy. Attach a document if needed.',
      'If OpenShell blocks a website you want the agent to read, approve it in OpenShell Policy and resend your request.'
    ],
    note:'Tech Radar checks for articles automatically in the Lounge. Its Heartbeat pauses in Open Task.'
  },
  mission:{anchor:new THREE.Vector3(2.45,4.02,-6.98)},
};
function roomGuide(id){
  const stage=studioRooms[id];
  const guide={...roomGuides[id],title:stage.title,label:'STAGE '+stage.number+' / QUICK GUIDE'};
  if(id!=='mission')return guide;
  const scenario=scenarioFloors.find(item=>item.id===activeScenario);
  if(!scenario)return null;
  return {...guide,intro:escape(scenario.guide?.intro||scenario.description),points:(scenario.guide?.points||[]).map(point=>escape(point)),note:scenario.guide?.note||''};
}
const termGuides={
  agent:{title:'How an agent works',overview:'agent',body:['Each hire has its own instructions, skills and workspace. The model uses them to decide how to handle your request.','Heartbeat schedules checks for agents such as Tech Radar, so they can post an update without a chat message.']},
  openshell:{title:'How OpenShell protection works',overview:'openshell',body:['OpenShell runs a protected agent’s tools in a sandbox. Its policy limits which files those tools can access and which websites they can reach.','In the Lounge, check Recent activity in OpenShell Policy to see what happened. To retry a blocked site, approve it and resend your message.','If a team task pauses for access, review the sites in OpenShell Policy, then select Continue in Mission Control. You can continue with the evidence already collected without approving any sites.'],details:`<section class="world-term-command"><h3>Runtime command</h3><p>Example command. The sandbox name and policy path depend on the installation.</p><pre>openshell sandbox create &#92;
  --name &lt;agent-runtime-id&gt; &#92;
  --from openclaw &#92;
  --policy &lt;data-dir&gt;/openclaw/policies/default-deny.json &#92;
  --no-auto-providers &#92;
  --detach -- sleep infinity</pre></section>`},
  skill:{title:'How skills work',body:['A skill gives an agent instructions for a particular job. For example, Coding helps an agent build a webpage, and Web research helps it find and cite sources.','Casey considers equipped skills and available tools when assigning team tasks. A protected agent still needs permission to reach a blocked website.']}
};
const roomPaper=document.createElement('aside');roomPaper.className='world-room-paper';roomPaper.hidden=true;roomPaper.setAttribute('role','dialog');roomPaper.setAttribute('aria-modal','false');roomPaper.setAttribute('aria-labelledby','world-room-paper-title');
roomPaper.innerHTML='<button type="button" class="world-room-paper-close" aria-label="Close room information">×</button><div class="world-room-paper-content"><div class="world-room-paper-drag" title="Drag to move"><span aria-hidden="true">•••</span><small></small><h2 id="world-room-paper-title"></h2></div><p class="world-room-paper-intro"></p><ol></ol><p class="world-room-paper-note"></p></div><button type="button" class="world-room-paper-resize" aria-label="Resize information window" title="Drag to resize"></button>';
navigationLayer.append(roomPaper);
const termPaper=document.createElement('aside');termPaper.className='world-room-paper world-term-paper';termPaper.hidden=true;termPaper.setAttribute('role','dialog');termPaper.setAttribute('aria-modal','false');termPaper.setAttribute('aria-labelledby','world-term-paper-title');
termPaper.innerHTML='<button type="button" class="world-room-paper-close" aria-label="Close definition">×</button><div class="world-room-paper-content"><div class="world-room-paper-drag" title="Drag to move"><span aria-hidden="true">•••</span><small>FIELD NOTES / GLOSSARY</small><h2 id="world-term-paper-title"></h2></div><div class="world-term-paper-body"></div></div><button type="button" class="world-room-paper-resize" aria-label="Resize definition window" title="Drag to resize"></button>';
navigationLayer.append(termPaper);
const termOverview=document.createElement('aside');termOverview.className='world-term-overview';termOverview.hidden=true;termOverview.setAttribute('role','dialog');termOverview.setAttribute('aria-modal','true');termOverview.setAttribute('aria-labelledby','world-term-overview-title');
termOverview.innerHTML='<button type="button" class="world-room-paper-close" aria-label="Close overview">×</button><div><div class="world-room-paper-drag" title="Drag to move"><span aria-hidden="true">•••</span><h2 id="world-term-overview-title"></h2></div><img></div>';
navigationLayer.append(termOverview);
function movablePaper(paper,limits={}){
  const handle=paper.querySelector('.world-room-paper-drag'),resizer=paper.querySelector('.world-room-paper-resize'),margin=10;
  let moving=null,resizing=null,lastSize=null;
  function resetMobile(){
    for(const name of ['left','top','right','bottom','width','height','max-height','transform'])paper.style.removeProperty(name);
    paper.classList.remove('world-room-paper-positioned');
  }
  function position(){
    if(navigationLayer.clientWidth<=700){resetMobile();return false;}
    if(!paper.classList.contains('world-room-paper-positioned')){
      const bounds=navigationLayer.getBoundingClientRect(),rect=paper.getBoundingClientRect();
      paper.style.left=(rect.left-bounds.left)+'px';paper.style.top=(rect.top-bounds.top)+'px';
      paper.style.right='auto';paper.style.bottom='auto';paper.style.transform='none';paper.classList.add('world-room-paper-positioned');
    }
    return true;
  }
  function constrain(){
    if(paper.hidden||!position())return;
    const bounds=navigationLayer.getBoundingClientRect(),rect=paper.getBoundingClientRect();
    const width=Math.min(rect.width,limits.width||Infinity,Math.max(280,bounds.width-margin*2));
    const height=Math.min(rect.height,limits.height||Infinity,Math.max(180,bounds.height-margin*2));
    if(Math.abs(width-rect.width)>.5)paper.style.width=width+'px';
    if(Math.abs(height-rect.height)>.5)paper.style.height=height+'px';
    const left=Math.max(margin,Math.min(rect.left-bounds.left,bounds.width-width-margin));
    const top=Math.max(margin,Math.min(rect.top-bounds.top,bounds.height-height-margin));
    paper.style.left=left+'px';paper.style.top=top+'px';
  }
  handle.addEventListener('pointerdown',event=>{
    if(event.button!==0||!position())return;
    const bounds=navigationLayer.getBoundingClientRect(),rect=paper.getBoundingClientRect();
    moving={pointer:event.pointerId,dx:event.clientX-rect.left,dy:event.clientY-rect.top,bounds};
    handle.setPointerCapture(event.pointerId);handle.classList.add('is-dragging');event.preventDefault();
  });
  handle.addEventListener('pointermove',event=>{
    if(!moving||moving.pointer!==event.pointerId)return;
    const rect=paper.getBoundingClientRect();
    const left=Math.max(margin,Math.min(event.clientX-moving.bounds.left-moving.dx,moving.bounds.width-rect.width-margin));
    const top=Math.max(margin,Math.min(event.clientY-moving.bounds.top-moving.dy,moving.bounds.height-rect.height-margin));
    paper.style.left=left+'px';paper.style.top=top+'px';
  });
  const finish=event=>{
    if(!moving||moving.pointer!==event.pointerId)return;
    moving=null;handle.classList.remove('is-dragging');
  };
  handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);
  if(resizer){
    resizer.addEventListener('pointerdown',event=>{
      if(event.button!==0||!position())return;
      const bounds=navigationLayer.getBoundingClientRect(),rect=paper.getBoundingClientRect();
      resizing={pointer:event.pointerId,x:event.clientX,y:event.clientY,width:rect.width,height:rect.height,
                maxWidth:Math.min(limits.width||Infinity,bounds.right-rect.left-margin),
                maxHeight:Math.min(limits.height||Infinity,bounds.bottom-rect.top-margin)};
      resizer.setPointerCapture(event.pointerId);paper.classList.add('is-resizing','is-user-sized');event.preventDefault();event.stopPropagation();
    });
    resizer.addEventListener('pointermove',event=>{
      if(!resizing||resizing.pointer!==event.pointerId)return;
      paper.style.width=Math.max(280,Math.min(resizing.maxWidth,resizing.width+event.clientX-resizing.x))+'px';
      paper.style.height=Math.max(180,Math.min(resizing.maxHeight,resizing.height+event.clientY-resizing.y))+'px';
    });
    const finishResize=event=>{
      if(!resizing||resizing.pointer!==event.pointerId)return;
      resizing=null;paper.classList.remove('is-resizing');constrain();
    };
    resizer.addEventListener('pointerup',finishResize);resizer.addEventListener('pointercancel',finishResize);
  }
  new ResizeObserver(()=>{
    if(paper.hidden)return;
    const size=[paper.offsetWidth,paper.offsetHeight];
    const scale=Math.max(1,Math.min(1.45,size[0]/480));
    paper.style.setProperty('--world-paper-body-size',(15*scale)+'px');
    paper.style.setProperty('--world-paper-title-size',(32*scale)+'px');
    paper.style.setProperty('--world-paper-label-size',(11*scale)+'px');
    paper.style.setProperty('--world-paper-step-size',(12*scale)+'px');
    if(lastSize&&(size[0]!==lastSize[0]||size[1]!==lastSize[1])){
      if(paper.classList.contains('world-term-overview'))paper.classList.add('is-user-sized');
      constrain();
    }
    lastSize=size;
  }).observe(paper);
  return constrain;
}
const constrainRoomPaper=movablePaper(roomPaper),constrainTermPaper=movablePaper(termPaper);
const constrainTermOverview=movablePaper(termOverview,{width:1920,height:1080});
new ResizeObserver(()=>{constrainRoomPaper();constrainTermPaper();constrainTermOverview();}).observe(navigationLayer);
let roomInfoReturn=null,termInfoReturn=null;
let termOverviewReturn=null;
function closeTermOverview(restoreFocus=true){
  if(termOverview.hidden)return;
  termOverview.hidden=true;termOverview.classList.remove('is-maximized','is-user-sized','is-resizing');termPaper.removeAttribute('aria-hidden');
  for(const name of ['left','top','right','bottom','width','height','max-height','transform'])termOverview.style.removeProperty(name);
  termOverview.classList.remove('world-room-paper-positioned');
  const target=termOverviewReturn;termOverviewReturn=null;
  if(restoreFocus)target?.focus({preventScroll:true});
}
function openTermOverview(trigger,key){
  const source=window.BacOverviewImages?.[key];if(!source)return;
  const image=termOverview.querySelector('img');
  termOverviewReturn=trigger;image.src=source;
  image.alt=key==='openshell'?'OpenShell architecture showing its gateway, supervisor, sandbox isolation, policy lifecycle and approved egress':'AI agent overview showing an LLM combined with a harness of tools, instructions, memory and guardrails in an observe, plan and act loop';
  termOverview.querySelector('h2').textContent=key==='openshell'?'OpenShell overview':'Agent overview';
  termOverview.classList.toggle('is-maximized',key==='openshell');
  termPaper.setAttribute('aria-hidden','true');termOverview.hidden=false;
  termOverview.querySelector('.world-room-paper-close').focus({preventScroll:true});
}
function closeTermInfo(restoreFocus=true){
  if(termPaper.hidden)return;
  closeTermOverview(false);
  termPaper.hidden=true;navigationLayer.dataset.termOpen='false';
  const target=termInfoReturn;termInfoReturn=null;
  if(restoreFocus)target?.focus({preventScroll:true});
}
function closeRoomInfo(restoreFocus=true){
  if(roomPaper.hidden)return;
  closeTermInfo(false);
  roomPaper.hidden=true;
  const target=roomInfoReturn;roomInfoReturn=null;
  if(restoreFocus)target?.focus({preventScroll:true});
}
function openRoomInfo(id,trigger){
  const guide=roomGuide(id);if(!guide)return;
  closeTermInfo(false);
  roomInfoReturn=trigger;roomPaper.querySelector('small').textContent=guide.label;
  roomPaper.querySelector('h2').textContent=guide.title;
  roomPaper.querySelector('.world-room-paper-intro').innerHTML=guide.intro;
  roomPaper.querySelector('ol').innerHTML=guide.points.map(point=>'<li>'+point+'</li>').join('');
  roomPaper.querySelector('ol').hidden=!guide.points.length;
  roomPaper.querySelector('.world-room-paper-note').textContent=guide.note;
  roomPaper.querySelector('.world-room-paper-note').hidden=!guide.note;
  roomPaper.hidden=false;roomPaper.querySelector('.world-room-paper-close').focus({preventScroll:true});
}
function openTermInfo(id,trigger){
  const guide=termGuides[id];if(!guide)return;
  termInfoReturn=trigger;termPaper.querySelector('h2').textContent=guide.title;
  const overview=guide.overview?'<p class="term-overview-link"><a href="#" data-term-overview="'+guide.overview+'">Overview</a></p>':'';
  termPaper.querySelector('.world-term-paper-body').innerHTML=overview+(id==='agent'?(window.BacAgentBlueprint||''):'')+guide.body.map(paragraph=>'<p>'+paragraph+'</p>').join('')+(guide.details||'');
  termPaper.hidden=false;navigationLayer.dataset.termOpen='true';
  termPaper.querySelector('.world-room-paper-close').focus({preventScroll:true});
}
roomPaper.querySelector('.world-room-paper-close').onclick=()=>closeRoomInfo();
roomPaper.onclick=e=>{const term=e.target.closest('[data-paper-term]');if(term)openTermInfo(term.dataset.paperTerm,term);};
roomPaper.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeRoomInfo();}};
termPaper.querySelector('.world-room-paper-close').onclick=()=>closeTermInfo();
termPaper.onclick=event=>{
  const link=event.target.closest('[data-term-overview]');if(!link)return;
  event.preventDefault();openTermOverview(link,link.dataset.termOverview);
};
termPaper.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeTermInfo();}};
termOverview.querySelector('.world-room-paper-close').onclick=()=>closeTermOverview();
termOverview.onkeydown=e=>{
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeTermOverview();}
  else if(e.key==='Tab'){e.preventDefault();termOverview.querySelector('.world-room-paper-close').focus();}
};
root.addEventListener('pointerdown',event=>{
  if(event.button!==0||event.target.closest('dialog[open]'))return;
  // Dismiss only the top information layer, preserving the page beneath it.
  if(!termOverview.hidden){
    if(!termOverview.contains(event.target)&&!event.target.closest('[data-term-overview]'))closeTermOverview(false);
  }else if(!termPaper.hidden){
    if(!termPaper.contains(event.target)&&!event.target.closest('[data-paper-term]'))closeTermInfo(false);
  }else if(!roomPaper.hidden&&!roomPaper.contains(event.target)&&!event.target.closest('[data-room-info]'))closeRoomInfo(false);
},true);
const roomInfoMarkers=Object.keys(roomGuides).map(id=>{
  const node=document.createElement('button');node.type='button';node.className='world-room-info';node.dataset.roomInfo=id;
  node.textContent='i';node.setAttribute('aria-label','About '+studioRooms[id].title);node.title='About '+studioRooms[id].title;
  node.onclick=()=>openRoomInfo(id,node);navigationLayer.append(node);return {id,node};
});
function goToRoom(next){
  const restoreFocus=navigationLayer.contains(document.activeElement);
  root.dispatchEvent(new CustomEvent('bac:world-room',{detail:{room:next}}));
  if(restoreFocus)roomMap.querySelector('[data-world-room="'+next+'"]')?.focus({preventScroll:true});
}
function goToScenario(id){if(!scenarioPending)root.dispatchEvent(new CustomEvent('bac:world-scenario',{detail:{id}}));}
roomMap.onclick=e=>{const scenario=e.target.closest('[data-world-scenario]');if(scenario){goToScenario(scenario.dataset.worldScenario);return;}const button=e.target.closest('[data-world-room]');if(button)goToRoom(button.dataset.worldRoom);};
overviewButton.onclick=()=>scenarioGallery?showOverview():overview?goToRoom(room):showOverview();

// Hiring and Open Task connect through the lounge; no long outer bridge.
const connections=[
  ...scenarioFloors.map(s=>({from:'lounge',to:'mission',scenario:s.id,points:scenarioPath(s.id)})),
  {from:'lounge',to:'workshop',points:[[0,6.3],[0,13.75]]}
];
function hallRail(parent,x,z,length){
  box(parent,x,.055,z,length,.035,.045,0x76b900,true);
  box(parent,x,.48,z,length,.055,.065,0x617b90);
  for(let p=-length/2+.12;p<length/2;p+=Math.max(.25,(length-.24)/Math.max(1,Math.ceil(length/4))))box(parent,x+p,.24,z,.055,.48,.055,0x617b90);
}
// Split shared paths at junctions so rails never fence off another scenario.
const junctions=new Map(),hallEdges=new Map();
const pointKey=([x,z])=>x.toFixed(3)+':'+z.toFixed(3);
for(const c of connections)for(const point of c.points)junctions.set(pointKey(point),{point,neighbors:new Set()});
for(const c of connections){
  const segments=[];let length=0;
  for(let i=1;i<c.points.length;i++){
    const [sx,sz]=c.points[i-1],[ex,ez]=c.points[i],distance=Math.hypot(ex-sx,ez-sz),angle=-Math.atan2(ez-sz,ex-sx);
    segments.push({sx,sz,ex,ez,distance,offset:length,angle});length+=distance;
    const onSegment=[...junctions.values()].filter(({point:[x,z]})=>Math.abs((x-sx)*(ez-sz)-(z-sz)*(ex-sx))<.001&&x>=Math.min(sx,ex)-.001&&x<=Math.max(sx,ex)+.001&&z>=Math.min(sz,ez)-.001&&z<=Math.max(sz,ez)+.001).sort((a,b)=>Math.hypot(a.point[0]-sx,a.point[1]-sz)-Math.hypot(b.point[0]-sx,b.point[1]-sz));
    for(let j=1;j<onSegment.length;j++){
      const a=onSegment[j-1],b=onSegment[j],ak=pointKey(a.point),bk=pointKey(b.point);
      if(ak===bk)continue;a.neighbors.add(bk);b.neighbors.add(ak);hallEdges.set([ak,bk].sort().join('|'),[a,b]);
    }
  }
  const pulse=box(scene,0,.11,0,.48,.035,1.7,0x96d52b,true);pulse.visible=false;
  corridors.push({...c,segments,length,pulse});
}
for(const [a,b] of hallEdges.values()){
  const [sx,sz]=a.point,[ex,ez]=b.point,distance=Math.hypot(ex-sx,ez-sz),angle=-Math.atan2(ez-sz,ex-sx);
  const hall=new THREE.Group();hall.position.set(sx,0,sz);hall.rotation.y=angle;scene.add(hall);
  const start=a.neighbors.size>1?Math.min(1.2,distance/2-.02):0,end=distance-(b.neighbors.size>1?Math.min(1.2,distance/2-.02):0),width=end-start,x=(start+end)/2;
  box(hall,x,-.18,0,width,.36,2.4,0x172330);box(hall,x,.015,0,width,.04,2.25,0x35485a);
  for(const z of [-1.14,1.14])hallRail(hall,x,z,width);
  for(let p=start+.5;p<end-.2;p+=1.05)box(hall,p,.043,0,.38,.015,.1,0x92b4c9);
}
for(const junction of junctions.values()){
  if(junction.neighbors.size<2)continue;
  const [x,z]=junction.point,corner=new THREE.Group();corner.position.set(x,0,z);scene.add(corner);
  box(corner,0,-.18,0,2.4,.36,2.4,0x172330);box(corner,0,.015,0,2.25,.04,2.25,0x35485a);
  const open=[...junction.neighbors].map(key=>{const [px,pz]=junctions.get(key).point;return [Math.sign(px-x),Math.sign(pz-z)];});
  for(const [dx,dz] of [[-1,0],[1,0],[0,-1],[0,1]])if(!open.some(([ox,oz])=>dx===ox&&dz===oz)){
    const edge=new THREE.Group();corner.add(edge);edge.rotation.y=dx?Math.PI/2:0;hallRail(edge,0,dx?dx*1.14:dz*1.14,2.4);
  }
  ring(corner,0,.055,0,.32,0x96d52b);
}
function doorway(from,to,x,z,rotation=0,parent=studioRooms[from].group){
  const group=new THREE.Group();group.position.set(x,0,z);group.rotation.y=rotation;parent.add(group);
  box(group,0,.055,0,.65,.1,2.35,0x3d5265);
  for(const z of [-1.1,1.1]){box(group,0,1.1,z,.18,2.2,.18,0x627e93);box(group,.105,1.14,z,.03,1.94,.045,0x96d52b,true);}
  box(group,0,2.2,0,.22,.18,2.4,0x344d60);box(group,.13,2.2,0,.026,.09,2.04,0x96d52b,true);
  doorways.push({from,to,group});
}
doorway('lounge','mission',8.8,0);doorway('mission','lounge',-10.6,0);
scenarioFloors.forEach(s=>doorway('scenario:'+s.id,'lounge',-10.6,0,0,s.group));
doorway('lounge','workshop',0,6.1,Math.PI/2);doorway('workshop','lounge',0,-4.05,Math.PI/2);
for(const [id,r] of Object.entries(studioRooms).filter(([id])=>id!=='mission')){
  const node=document.createElement('button');node.type='button';node.className='world-campus-room';node.dataset.worldRoom=id;
  node.innerHTML='<span>'+r.number+'</span><b>'+r.title+'</b>';node.onclick=()=>goToRoom(id);navigationLayer.append(node);overviewLabels.push({id,node,group:r.group});
}
for(const r of scenarioFloors){
  const node=document.createElement('button');node.type='button';node.className='world-campus-room world-scenario-label';node.dataset.worldScenario=r.id;
  node.style.setProperty('--scenario-accent',r.accent);node.title=r.description;
  node.innerHTML='<span>'+escape(r.number)+'</span><b>'+escape(r.title)+'</b>';
  node.onclick=()=>goToScenario(r.id);navigationLayer.append(node);overviewLabels.push({id:r.id,scenario:r.id,node,group:r.group});
}
function refreshScenarioLabels(){
  for(const item of overviewLabels.filter(r=>r.scenario)){
    const saved=scenarioStatus.find(s=>s.id===item.scenario);
    item.node.classList.toggle('has-work',!!saved?.hasWork);item.node.disabled=scenarioPending;
  }
  roomMap.querySelectorAll('[data-world-scenario]').forEach(node=>{
    node.disabled=scenarioPending;node.classList.toggle('selected',room==='mission'&&!scenarioGallery&&node.dataset.worldScenario===activeScenario);
    node.setAttribute('aria-current',room==='mission'&&!scenarioGallery&&node.dataset.worldScenario===activeScenario?'location':'false');
  });
}
function roomHeight(id){
  const aspect=viewport.clientWidth/Math.max(1,viewport.clientHeight);
  return id==='workshop'?Math.max(6.8,8/aspect):(aspect<1?12.5:aspect<1.5?10.2:8.5)*(id==='mission'?1.1:1);
}
function overviewHeight(){return campusFrame(scenarioGallery).height;}
function roomFocus(id){return new THREE.Vector3(studioRooms[id].x,id==='workshop'?1.0:.25,studioRooms[id].z+.6);}
function refreshNavigation(){
  navigationLayer.dataset.overview=String(overview);navigationLayer.dataset.travelling=String(!!journey);
  root.dataset.worldOverview=String(overview);root.dataset.worldTravelling=String(!!journey);root.dataset.scenarioGallery=String(scenarioGallery);refreshScenarioLabels();
  hotspotLayer.hidden=room!=='mission'||overview||!!journey;el('labels').hidden=room!=='mission'||overview||!!journey;residentLayer.hidden=room!=='lounge'||overview||!!journey;
  overviewButton.textContent=scenarioGallery?'← Whole studio':overview?'↙ Return to '+studioRooms[room].title:'• See the whole studio';overviewButton.setAttribute('aria-pressed',String(overview));
  overviewButton.setAttribute('aria-label',scenarioGallery?'See the whole studio':overview?'Return to '+studioRooms[room].title:'See the whole studio');
  roomMap.querySelectorAll('[data-world-room]').forEach(b=>{b.setAttribute('aria-current',b.dataset.worldRoom===room?'location':'false');b.classList.toggle('selected',b.dataset.worldRoom===room);});
  overviewLabels.forEach(r=>{r.node.hidden=!overview||!!journey||(scenarioGallery&&!r.scenario);r.node.setAttribute('aria-current',r.scenario?room==='mission'&&r.scenario===activeScenario?'location':'false':r.id===room?'location':'false');});
  roomInfoMarkers.forEach(marker=>{
    marker.node.hidden=!!journey||overview||marker.id!==room;
    const title='About '+(roomGuide(marker.id)?.title||studioRooms[marker.id].title);
    marker.node.title=title;marker.node.setAttribute('aria-label',title);
  });
  journeyNote.hidden=!journey&&!overview;
  if(!journey&&overview)journeyNote.textContent=scenarioGallery?'Choose a space to begin or continue.':'Choose a space in your studio.';
}
function rememberCamera(){if(!overview&&!journey)roomCameras[room]=[azimuth,elevation,zoom];}
function travelTo(target,instant=false,remaining=[]){
  endResidentDrag(true);drag=null;
  const start={focus:focus.clone(),azimuth,elevation,zoom,height:viewHalfHeight||roomHeight(room)};
  const delta=Math.atan2(Math.sin(target.azimuth-azimuth),Math.cos(target.azimuth-azimuth));target.azimuth=azimuth+delta;
  const distance=start.focus.distanceTo(target.focus);
  journey={start,target,began:performance.now(),duration:target.overview?800:Math.min(1000,650+distance*8),remaining,lift:target.overview?0:Math.min(target.height*.18,distance*.055)};
  refreshNavigation();
  if(instant||reduced.matches)finishJourney(true);
}
function finishJourney(instant=false){
  if(!journey)return;const {target,remaining}=journey;
  focus.copy(target.focus);azimuth=target.azimuth;elevation=target.elevation;zoom=target.zoom;viewHalfHeight=target.height;journey=null;
  if(remaining.length){travelTo(remaining[0],instant,remaining.slice(1));return;}
  refreshNavigation();frame();renderer.render(scene,camera);
}
function setRoom(next,options={}){
  closeRoomInfo(false);
  if(arrival)finishArrival();
  if(!studioRooms[next])return;
  if(next===room&&!overview&&!journey&&!scenarioMoved){resize();return;}
  scenarioMoved=false;scenarioGallery=false;
  // Retarget from the current camera pose, without queuing intermediate rooms.
  const previous=room;rememberCamera();room=next;overview=false;syncVisitorTeam();
  const [a,e,z]=roomCameras[next];
  journeyNote.textContent='Opening '+studioRooms[next].title;
  travelTo({focus:roomFocus(next),azimuth:a,elevation:e,zoom:z,height:roomHeight(next),overview:false,from:previous,to:next,scenario:activeScenario},options.instant);
}
function showOverview(options={}){
  closeRoomInfo(false);closeTermInfo(false);
  if(arrival)finishArrival();
  rememberCamera();overview=true;scenarioGallery=false;syncVisitorTeam();journeyNote.textContent='Opening your connected studio';
  travelTo({...campusFrame(),azimuth:.43,elevation:.64,zoom:1,overview:true},!!options.instant);
}
function showScenarios(options={}){
  if(scenarioFloors.length===1){setScenario(scenarioFloors[0].id);setRoom('mission',options);return;}
  closeRoomInfo(false);closeTermInfo(false);if(arrival)finishArrival();
  rememberCamera();room='mission';overview=true;scenarioGallery=true;
  journeyNote.textContent='Multi-Agent spaces';
  travelTo({...campusFrame(true),azimuth:.43,elevation:.64,zoom:1,overview:true},!!options.instant);
}
function resetNavigation(){
  roomCameras[room]=room==='workshop'?[.34,.64,1]:[.43,.76,1];
  if(overview){scenarioGallery?showScenarios():showOverview();return;}
  const [a,e,z]=roomCameras[room];journeyNote.textContent='Returning to '+studioRooms[room].title;
  travelTo({focus:roomFocus(room),azimuth:a,elevation:e,zoom:z,height:roomHeight(room),overview:false});
}
function resizeNavigation(){
  if(journey){for(const target of [journey.target,...journey.remaining])target.height=target.overview?overviewHeight():roomHeight(target.to||room);}
  else viewHalfHeight=overview?overviewHeight():roomHeight(room);
}
const hiringRimPoint=new THREE.Vector3();
function positionHiringLabel(node){
  // The rim nearest the camera is the lowest visible point of the circular platform.
  const {radiusBottom,height}=hiringPlatform.geometry.parameters;
  hiringRimPoint.set(Math.sin(azimuth)*radiusBottom,-height/2,Math.cos(azimuth)*radiusBottom);
  positionLabel(node,hiringPlatform.localToWorld(hiringRimPoint));
  node.style.top=(parseFloat(node.style.top)+6+node.offsetHeight)+'px';
}
function animateNavigation(now){
  if(journey){
    const t=Math.min(1,(now-journey.began)/journey.duration),p=t*t*(3-2*t),{start,target}=journey;
    focus.lerpVectors(start.focus,target.focus,p);
    azimuth=THREE.MathUtils.lerp(start.azimuth,target.azimuth,p);elevation=THREE.MathUtils.lerp(start.elevation,target.elevation,p);zoom=THREE.MathUtils.lerp(start.zoom,target.zoom,p);
    viewHalfHeight=THREE.MathUtils.lerp(start.height,target.height,p)+Math.sin(Math.PI*p)**2*journey.lift;
    frame();if(t===1)finishJourney();
  }
  scene.updateMatrixWorld();
  overviewLabels.forEach(r=>{
    if(r.node.hidden)return;
    if(r.id==='workshop')positionHiringLabel(r.node);
    else positionLabel(r.node,r.group.localToWorld(new THREE.Vector3(0,r.scenario?4.8:4.5,r.scenario?-5.8:-1.7)));
    const controlsBottom=Math.max(overviewControl.offsetTop+overviewControl.offsetHeight,journeyNote.offsetHeight?journeyNote.offsetTop+journeyNote.offsetHeight:0);
    r.node.style.top=Math.max(controlsBottom+12+r.node.offsetHeight,parseFloat(r.node.style.top))+'px';
  });
  // Keep every entrance clickable when rows are added or the desktop narrows.
  const placed=[];
  for(const {node} of overviewLabels.filter(r=>!r.node.hidden).sort((a,b)=>parseFloat(a.node.style.top)-a.node.offsetHeight-(parseFloat(b.node.style.top)-b.node.offsetHeight))){
    const width=node.offsetWidth,height=node.offsetHeight;
    const left=THREE.MathUtils.clamp(parseFloat(node.style.left)-width/2,12,viewport.clientWidth-width-12);
    let top=parseFloat(node.style.top)-height;
    for(const other of placed)if(left<other.right+10&&left+width>other.left-10&&top<other.bottom+10&&top+height>other.top-10)top=other.bottom+10;
    top=Math.min(top,viewport.clientHeight-height-12);
    node.style.left=(left+width/2)+'px';node.style.top=(top+height)+'px';
    placed.push({left,right:left+width,top,bottom:top+height});
  }
  roomInfoMarkers.forEach(marker=>{
    if(marker.node.hidden)return;
    positionLabel(marker.node,studioRooms[marker.id].group.localToWorld(roomGuides[marker.id].anchor.clone()));
    const half=marker.node.offsetWidth/2;
    marker.node.style.left=THREE.MathUtils.clamp(parseFloat(marker.node.style.left),half+12,viewport.clientWidth-half-12)+'px';
    marker.node.style.top=THREE.MathUtils.clamp(parseFloat(marker.node.style.top),half+12,viewport.clientHeight-half-12)+'px';
  });
  // Highlight only the bridge for the current trip, in the direction of travel.
  corridors.forEach(c=>{
    const target=journey?.target,matching=!c.scenario||c.scenario===activeScenario,forward=matching&&target?.from===c.from&&target?.to===c.to,backward=matching&&target?.from===c.to&&target?.to===c.from;
    c.pulse.visible=!!journey&&!reduced.matches&&(forward||backward);
    if(!c.pulse.visible)return;
    const t=Math.min(1,(now-journey.began)/journey.duration),distance=(forward?t:1-t)*c.length;
    const s=c.segments.find(s=>distance<=s.offset+s.distance)||c.segments[c.segments.length-1],p=(distance-s.offset)/s.distance;
    c.pulse.position.set(THREE.MathUtils.lerp(s.sx,s.ex,p),.11,THREE.MathUtils.lerp(s.sz,s.ez,p));c.pulse.rotation.y=s.angle;
  });
}
function navigationTargets(){
  if(overview)return [...(scenarioGallery?[]:[workshopRoom,loungeRoom]),missionRoom,...scenarioFloors.filter(s=>s.group.visible).map(s=>s.group)];
  return room==='mission'?[...hitTargets.filter(o=>robots[o.userData.agent]?.robot.visible),...(activeScenario==='plan'?[...visitorTravel.values()].filter(v=>v.phase!=='returning').map(v=>v.group):[])]:roomHitTargets();
}
function selectNavigationObject(object){
  for(let node=object;node;node=node.parent){
    if(!overview&&room==='mission'&&activeScenario==='plan'&&node.userData.visitorAgent){root.dispatchEvent(new CustomEvent('bac:collection-select',{detail:node.userData.visitorAgent}));return true;}
    if(overview&&node.userData.scenario){goToScenario(node.userData.scenario);return true;}
    if(overview&&node.userData.studioRoom){goToRoom(node.userData.studioRoom);return true;}
  }
  return false;
}
function navigationInfo(){return {overview,scenarioGallery,activeScenario,scenarios:scenarioFloors.map(s=>{const p=new THREE.Vector3(s.x+8,.03,s.z+5).project(camera);return {id:s.id,x:s.x,z:s.z,active:s.id===activeScenario,screenEntry:[(p.x*.5+.5)*viewport.clientWidth,(-p.y*.5+.5)*viewport.clientHeight]};}),travelling:!!journey,route:journey?[journey.target,...journey.remaining].map(t=>({from:t.from,to:t.to})):[],focus:focus.toArray(),rooms:Object.fromEntries(Object.entries(studioRooms).map(([id,r])=>[id,r.group.position.toArray()])),visibleRooms:Object.keys(studioRooms).filter(id=>studioRooms[id].group.visible),doorways:doorways.map(d=>({from:d.from,to:d.to})),corridors:corridors.map(c=>({from:c.from,to:c.to,points:c.points,active:c.pulse.visible}))};}
reduced.addEventListener('change',()=>{if(reduced.matches)finishJourney(true);});
focus.copy(roomFocus(room));viewHalfHeight=roomHeight(room);refreshNavigation();
