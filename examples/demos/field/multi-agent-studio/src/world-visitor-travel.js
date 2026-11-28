// SPDX-License-Identifier: Apache-2.0

// Scene-only visitors. Following the presenter never starts or reserves model work.
const visitorTravel=new Map();
const visitorLayer=document.createElement('div');visitorLayer.className='world-roundtable';viewport.append(visitorLayer);
const visitorBenches=new THREE.Group();scene.add(visitorBenches);
let visitorBenchKey='';
let releasedVisitorJob='';
function planPoint(x,z){const floor=scenarioFloors.find(s=>s.id==='plan');return new THREE.Vector3(floor.x+x,.05,floor.z+z);}
function visitorRoute(v,points,phase,destination='working'){
  v.route=[v.group.position.clone(),...points.map(p=>p.clone())].filter((p,i,all)=>!i||p.distanceTo(all[i-1])>.001);
  v.segment=0;v.travel=0;v.phase=phase;v.destination=destination;
  v.target=v.route.at(-1).clone();
  v.length=v.route.slice(1).reduce((sum,p,i)=>sum+p.distanceTo(v.route[i]),0);
}
function disposeVisitor(v){visitorTravel.delete(v.key);scene.remove(v.group);clearGeometry(v.group);v.node.remove();}
function visitorCorridor(position,toTask){
  const points=[...scenarioPath('plan').map(([x,z])=>new THREE.Vector3(x,.05,z)),planPoint(-8.8,0)];
  if(position.x<=points[0].x)return toTask?points:[];
  if(position.x>=points.at(-1).x)return toTask?[new THREE.Vector3(position.x,.05,points.at(-1).z)]:[new THREE.Vector3(position.x,.05,points.at(-1).z),...points.reverse()];
  // Retarget along the shared corridor, never through a previous desk or seat.
  let nearest=null,segment=0,distance=Infinity;
  for(let i=0;i<points.length-1;i++){
    const point=new THREE.Line3(points[i],points[i+1]).closestPointToPoint(position,true,new THREE.Vector3());
    const gap=point.distanceToSquared(position);
    if(gap<distance){nearest=point;segment=i;distance=gap;}
  }
  return [nearest,...(toTask?points.slice(segment+1):points.slice(0,segment+1).reverse())];
}
function visitorApproach(v,target){
  const aisle=new THREE.Vector3(target.x,.05,planPoint(0,0).z);
  return [...visitorCorridor(v.group.position,true),aisle,target];
}
function returnVisitor(v){
  if(v.phase==='returning')return;
  visitorRoute(v,[...visitorCorridor(v.group.position,false),v.home],'returning');
}
function syncVisitorResidents(){
  for(const r of residents){
    r.atOpenTask=visitorTravel.has(r.key);
    if(r.atOpenTask){if(loungeSpeaker===r)endLoungeSpeech();if(drag?.resident===r)endResidentDrag(true);r.target=null;}
    r.mount.visible=!r.atOpenTask&&!r.atRoundtable&&arrival?.key!==r.key;r.node.hidden=!r.mount.visible;
  }
}
function syncVisitorCollection(){
  for(const v of visitorTravel.values()){
    const member=collection.find(a=>a.key===v.key);
    if(!member||member.deleting){disposeVisitor(v);continue;}
    if(activeScenario!=='plan'&&member.activity?.job!==v.job)returnVisitor(v);
  }
  syncVisitorTeam();syncVisitorResidents();
}
function syncVisitorTeam(){
  if(activeScenario!=='plan')return;
  const job=state.crewMission,visitorJob=job?.visitorJobId||job?.id;
  const finished=job?.visitorsFinished??job?.status==='done';
  // Leaving a finished task releases its desks for this visit. Saved results
  // remain available, but reopening Open Task seats these hires on standby.
  if(!job)releasedVisitorJob='';
  else if(room==='lounge'&&!overview&&finished)releasedVisitorJob=visitorJob;
  const active=job?.kind==='plan'&&job.visitorsPresent&&visitorJob!==releasedVisitorJob;
  const selected=new Map(active?state.agents.flatMap((a,role)=>a.visitorKey&&a.displayed!==false?[[a.visitorKey,{...a,taskTitle:a.role,role}]]:[]):[]);
  const following=['mixed','hired'].includes(state.visitorTeamMode)&&room==='mission'&&!overview;
  // Reaction guests use their own actors and seats. Never clone them on a bench.
  const reacting=new Set(meetingGuests.filter(g=>g.phase!=='returned').map(g=>g.key));
  const available=collection.filter(a=>!a.deleting&&!reacting.has(a.key)&&(!a.activity||a.activity.job===job?.id));
  const waiting=following?available:[];
  const desired=new Map(waiting.map(a=>[a.key,{...a,role:null,taskTitle:a.workspacePreparation==='running'?'Preparing workspace':'Standby'}]));
  selected.forEach((value,key)=>desired.set(key,value));
  for(const v of visitorTravel.values())if(!desired.has(v.key)){
    if(reacting.has(v.key))disposeVisitor(v);else returnVisitor(v);
  }
  const seats=new Map(waiting.map((a,i)=>[a.key,planPoint((i%4-(Math.min(waiting.length-Math.floor(i/4)*4,4)-1)/2)*4.5,6.4-Math.floor(i/4)*1.5)]));
  const benchKey=waiting.map(a=>a.key).join(':');
  if(benchKey!==visitorBenchKey){
    visitorBenchKey=benchKey;
    while(visitorBenches.children.length){const child=visitorBenches.children[0];visitorBenches.remove(child);clearGeometry(child);}
    for(const point of seats.values()){
      const chair=new THREE.Group();chair.position.copy(point);visitorBenches.add(chair);
      box(chair,0,.36,0,.9,.14,.75,0x344b5b);box(chair,0,.68,.34,.9,.62,.09,0x435f70);
      box(chair,-.34,.16,0,.1,.32,.6,0x233441);box(chair,.34,.16,0,.1,.32,.6,0x233441);
    }
  }
  scene.updateMatrixWorld(true);
  for(const [key,member] of desired){
    const resident=residents.find(r=>r.key===key&&!r.deleting);if(!resident)continue;
    let v=visitorTravel.get(key);
    const assigned=member.role!==null;
    const target=assigned?missionRoom.localToWorld(robots[member.role].home.clone()):seats.get(key);
    const destination=assigned?'working':'seated';
    const avatar={...member.avatar,protection:member.protection||'standard'};
    if(!v){
      if(arrival?.key===key)finishArrival();
      const rig=createCharacter(avatar);rig.group.scale.setScalar(1.15);rig.group.userData.visitorAgent=key;
      rig.group.position.copy(loungeRoom.localToWorld(resident.group.position.clone()));scene.add(rig.group);
      const node=document.createElement('button');node.type='button';node.className='campus-agent-label';node.dataset.visitorAgent=key;node.innerHTML='<b></b><small></small>';visitorLayer.append(node);
      v={...rig,key,node,home:rig.group.position.clone()};visitorTravel.set(key,v);
      node.onclick=()=>{if(v.role!==null&&activeScenario==='plan'&&state.agents[v.role]?.visitorKey===key)choose(v.role);else root.dispatchEvent(new CustomEvent('bac:collection-select',{detail:key}));};
      visitorRoute(v,visitorApproach(v,target),'entering',destination);
    }else if(v.phase==='returning'||v.destination!==destination||v.target.distanceTo(target)>.05){
      visitorRoute(v,visitorApproach(v,target),'entering',destination);
    }
    if(['body','color','accessory','protection'].some(field=>v.appearance[field]!==avatar[field])){
      const rig=createCharacter(avatar);v.group.remove(v.body);clearGeometry(v.body);v.group.add(rig.body);v.body=rig.body;v.arms=rig.arms;v.legs=rig.legs;v.appearance=rig.appearance;
    }
    v.job=assigned?job.id:null;v.role=member.role;v.name=member.name;v.title=member.taskTitle;
    v.working=assigned&&(job.activeStages||[]).includes(member.role);
    const label=v.node.querySelector('b');if(label.textContent!==v.name)label.textContent=v.name;
    const accessibleName='Select '+v.name+(v.phase==='working'&&v.working?', working':'');
    if(v.node.getAttribute('aria-label')!==accessibleName)v.node.setAttribute('aria-label',accessibleName);
  }
  syncVisitorResidents();
}
function animateVisitors(dt){
  for(const v of visitorTravel.values()){
    const walking=['entering','returning'].includes(v.phase);
    if(walking){
      v.travel+=dt;const fraction=!motion||reduced.matches?1:Math.min(1,v.travel/4);
      let distance=fraction*v.length;v.segment=0;
      while(v.segment<v.route.length-2){const length=v.route[v.segment].distanceTo(v.route[v.segment+1]);if(distance<length)break;distance-=length;v.segment++;}
      const a=v.route[v.segment],b=v.route[v.segment+1]||a;
      v.group.position.lerpVectors(a,b,Math.min(1,distance/Math.max(.001,a.distanceTo(b))));v.group.rotation.y=Math.atan2(b.x-a.x,b.z-a.z);
      if(fraction===1){if(v.phase==='returning'){disposeVisitor(v);continue;}v.phase=v.destination;v.segment=v.route.length-1;v.group.position.copy(v.target);}
    }
    const stepping=['entering','returning'].includes(v.phase)&&motion&&!reduced.matches,working=v.phase==='working'&&v.working,seated=v.phase==='seated';
    if(!stepping)v.group.rotation.y=v.phase==='working'||seated?Math.PI:0;
    v.body.position.y=seated?.18:stepping?Math.abs(Math.sin(clock*9))*.04:0;
    v.legs.forEach((leg,j)=>leg.rotation.x=seated?-Math.PI/2:stepping?Math.sin(clock*9+j*Math.PI)*.4:0);
    v.arms.forEach((arm,j)=>arm.rotation.x=seated?-.35:stepping?Math.sin(clock*9+j*Math.PI)*.3:working?-.7:0);
    const status=v.node.querySelector('small');
    const statusText=working?workingStatus(v.title):v.phase==='returning'?'Back to '+roomTitles.lounge:v.phase==='entering'?(v.destination==='seated'?'Joining Open Task':'Taking a workbench'):v.title;
    if(v.statusText!==statusText||v.statusWorking!==working){
      if(working)status.innerHTML=statusText;else status.textContent=statusText;
      v.statusText=statusText;v.statusWorking=working;
    }
    const accessibleName='Select '+v.name+(working?', working':'');
    if(v.node.getAttribute('aria-label')!==accessibleName)v.node.setAttribute('aria-label',accessibleName);
    v.node.classList.toggle('visitor-waiting',seated);v.node.classList.toggle('working',working);v.node.classList.toggle('selected',activeScenario==='plan'&&(state.selectedVisitorKey===v.key||v.role!==null&&activeSelection===v.role));
    v.node.hidden=!(overview||journey||room==='mission'&&activeScenario==='plan'||room==='lounge'&&stepping);
    positionLabel(v.node,v.group.position.clone().add(new THREE.Vector3(0,2.2,0)));
    // Keep the measured label width while moving beside the detail panel.
    // Translate it inward instead of letting absolute-position shrink-to-fit wrap it.
    if(!v.node.hidden&&v.node.style.display!=='none'){
      const half=v.node.offsetWidth/2;
      v.node.style.left=THREE.MathUtils.clamp(parseFloat(v.node.style.left),half+12,viewport.clientWidth-half-12)+'px';
    }
  }
  syncVisitorResidents();
}
function crewPresentation(role){
  const v=visitorTravel.get(state.agents[role]?.visitorKey);if(!v)return robots[role];
  const position=missionRoom.worldToLocal(v.group.position.clone());
  return {robot:{visible:true,position},home:robots[role].home,path:[],exchange:v.phase==='working'?null:v.phase};
}
function visitorTravelInfo(){return [...visitorTravel.values()].map(v=>{const point=v.group.localToWorld(new THREE.Vector3(0,.85,0)).project(camera);return {key:v.key,name:v.name,job:v.job,role:v.role,phase:v.phase,avatar:v.appearance,position:v.group.position.toArray(),destination:v.route.at(-1).toArray(),screenCenter:[(point.x*.5+.5)*viewport.clientWidth,(-point.y*.5+.5)*viewport.clientHeight]};});}
