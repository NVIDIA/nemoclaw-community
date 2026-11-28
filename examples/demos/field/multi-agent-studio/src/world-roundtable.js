// SPDX-License-Identifier: Apache-2.0

// Actual opinions live in the results and Captain's history. The scene only
// acknowledges submission once, then sends each guest home in turn on success.
const meetingFurniture=new THREE.Group();missionRoom.add(meetingFurniture);meetingFurniture.visible=false;
let meetingWidth=0,meetingCenter=0;
const meetingSeatX=Array.from({length:12},(_,i)=>(i%2?1:-1)*(Math.floor(i/2)*1.75+.875));
const meetingTable=new THREE.Group();meetingFurniture.add(meetingTable);
function fitMeetingTable(){
 // Pack holes left by removed guests, but preserve seats on ordinary reruns.
 meetingGuests.slice().sort((a,b)=>a.seat-b.seat).forEach((guest,seat)=>{
  if(guest.seat===seat)return;
  const x=meetingSeatX[seat],oldX=missionRoom.worldToLocal(guest.target.clone()).x;
  guest.chair.position.x+=x-oldX;guest.seat=seat;
  guest.target.copy(missionRoom.localToWorld(new THREE.Vector3(x,.05,6.05)));
  if(guest.seated)guest.group.position.copy(guest.target);
  else if(guest.phase==='entering'){
   guest.route[guest.route.length-2].x=guest.target.x;
   guest.route[guest.route.length-1].copy(guest.target);
  }
 });
 const xs=meetingGuests.map(g=>meetingSeatX[g.seat]);
 const left=Math.min(...xs),right=Math.max(...xs);
 const width=Math.max(3.6,right-left+1.6),center=(left+right)/2;
 if(width===meetingWidth&&center===meetingCenter)return;
 meetingWidth=width;meetingCenter=center;clearGeometry(meetingTable);
 box(meetingTable,center,.78,4.85,width,.14,1.5,0x627883);
 const legs=[center-width/2+.5,center+width/2-.5];if(width>9)legs.push(center);
 for(const x of legs)box(meetingTable,x,.37,4.85,.17,.75,.65,0x263b49);
 box(meetingTable,center,.865,4.85,width-.8,.016,.045,0x96d52b,true);
 sign(meetingTable,'YOUR AGENTS’ TABLE',center,1.0,4.85,3.1,.28,'#dff3ce','#192a35');
}
const meetingChairs=new THREE.Group();meetingFurniture.add(meetingChairs);
function syncMeetingFurniture(){
 // Open Task reuses these hires as standby visitors after their reactions.
 // Their old reaction chairs must not remain beside the standby seats.
 for(const guest of meetingGuests)guest.chair.visible=activeScenario!=='plan'||guest.phase!=='returned';
 meetingFurniture.visible=!!meetingId&&(activeScenario!=='plan'||meetingGuests.some(guest=>guest.chair.visible));
}
const meetingLayer=document.createElement('div');meetingLayer.className='world-roundtable';viewport.append(meetingLayer);
let meetingId='',meetingGuests=[],meetingSpeaker='',meetingSpeechUntil=0,meetingElapsed=0;
const meetingSpoken=new Set();
function releaseMeetingGuest(guest){
 guest.phase='returned';guest.seated=false;guest.group.visible=false;guest.node.hidden=true;
 const resident=residents.find(r=>r.key===guest.key);
 if(resident){resident.atRoundtable=false;resident.mount.visible=true;resident.node.hidden=false;}
}
function meetingRoute(guest,start){
 return [start,...scenarioPath(activeScenario).map(([x,z])=>new THREE.Vector3(x,.05,z)),missionRoom.localToWorld(new THREE.Vector3(-10,.05,6.85)),missionRoom.localToWorld(new THREE.Vector3(missionRoom.worldToLocal(guest.target.clone()).x,.05,6.85)),guest.target.clone()];
}
function inviteMeetingGuest(guest){
 const resident=residents.find(r=>r.key===guest.key);
 const start=resident?loungeRoom.localToWorld(resident.group.position.clone()):loungeRoom.localToWorld(new THREE.Vector3(2,.05,3));
 guest.route=meetingRoute(guest,start);guest.travel=0;guest.phase='entering';guest.seated=false;guest.group.visible=true;guest.group.position.copy(start);
}
function returnMeetingGuest(guest){
 const resident=residents.find(r=>r.key===guest.key);
 const home=resident?loungeRoom.localToWorld(resident.group.position.clone()):guest.route[0].clone();
 guest.route=meetingRoute(guest,home).reverse();guest.route[0]=guest.group.position.clone();
 guest.phase='returning';guest.travel=0;guest.seated=false;
}
function clearMeeting(){
 for(const guest of meetingGuests){releaseMeetingGuest(guest);scene.remove(guest.group);clearGeometry(guest.group);guest.node.remove();}
 meetingGuests=[];meetingSpoken.clear();meetingSpeaker='';meetingSpeechUntil=0;meetingElapsed=0;
 clearGeometry(meetingChairs);
}
function syncRoundtable(){
 const job=state.crewMission,meeting=job?.roundtable;
 // Open Task reactions happen at the existing desks/standby seats. Event Brief
 // retains its separate guests' table and return-to-Lounge animation.
 if(activeScenario==='plan'){if(meetingId)clearMeeting();meetingId='';meetingFurniture.visible=false;return;}
 if(!meeting?.members?.length){if(meetingId)clearMeeting();meetingId='';meetingFurniture.visible=false;return;}
 if(!meetingId&&['queued','cancelled','error'].includes(job.status))return;
 if(job.id===meetingId)return;
 // A finished event opened later must not replay arrivals, speeches or departures.
 const restored=['done','cancelled','error'].includes(job.status);
 const previous=new Map(meetingGuests.map(guest=>[guest.key,guest]));
 const remaining=new Set(meeting.members.map(member=>member.key));
 for(const guest of meetingGuests){
  if(remaining.has(guest.key))continue;
  releaseMeetingGuest(guest);scene.remove(guest.group);clearGeometry(guest.group);guest.node.remove();
  meetingChairs.remove(guest.chair);clearGeometry(guest.chair);
 }
 meetingGuests=meetingGuests.filter(guest=>remaining.has(guest.key));
 meetingId=job.id;meetingFurniture.visible=true;meetingSpoken.clear();meetingSpeaker='';meetingSpeechUntil=0;meetingElapsed=0;
 endLoungeSpeech();
 const usedSeats=new Set(meetingGuests.map(guest=>guest.seat));
 meeting.members.forEach((member,index)=>{
  const avatar={...avatarDefaults[index%avatarDefaults.length],...member.avatar,protection:member.protection||'standard'};
  const existing=previous.get(member.key);
  if(existing){
   existing.node.dataset.speaking='false';existing.node.querySelector('.roundtable-bubble').hidden=true;
   existing.name=member.name;existing.node.querySelector('b').textContent=member.name;
   if(['body','color','accessory','protection'].some(field=>existing.appearance[field]!==avatar[field])){
    const rig=createCharacter(avatar);rig.group.position.copy(existing.group.position);rig.group.rotation.copy(existing.group.rotation);
    scene.remove(existing.group);clearGeometry(existing.group);scene.add(rig.group);Object.assign(existing,rig);
   }
   if(restored)releaseMeetingGuest(existing);
   else if(existing.phase==='returned')inviteMeetingGuest(existing);
   else if(existing.phase==='returning'){
    // A new event may start mid-exit. Turn from the current position, never teleport home.
    existing.route=[existing.group.position.clone(),missionRoom.localToWorld(new THREE.Vector3(-10,.05,6.85)),missionRoom.localToWorld(new THREE.Vector3(missionRoom.worldToLocal(existing.target.clone()).x,.05,6.85)),existing.target.clone()];
    existing.phase='entering';existing.travel=0;
   }else if(existing.phase==='submitted')existing.phase='seated';
   return;
  }
  let seat=0;while(usedSeats.has(seat))seat++;usedSeats.add(seat);
  const x=meetingSeatX[seat],z=6.05;
  const chair=new THREE.Group();meetingChairs.add(chair);box(chair,x,.36,z,.76,.12,.76,0x344b5b);box(chair,x,.65,z+.34,.76,.64,.09,0x435f70);
  const rig=createCharacter(avatar),target=missionRoom.localToWorld(new THREE.Vector3(x,.05,z));scene.add(rig.group);
  const node=document.createElement('button');node.type='button';node.className='roundtable-guest';node.dataset.roundtableGuest=member.key;
  node.innerHTML='<b></b><small></small><span class="roundtable-bubble" hidden></span>';
  node.querySelector('b').textContent=member.name;node.title='Read opinions in the Captain’s conversation';node.onclick=()=>choose(0);meetingLayer.append(node);
  const guest={...rig,key:member.key,name:member.name,node,chair,seat,target,index};meetingGuests.push(guest);
  if(restored)releaseMeetingGuest(guest);else inviteMeetingGuest(guest);
 });
 fitMeetingTable();
 syncMeetingFurniture();
}
function animateRoundtable(dt){
 const job=state.crewMission,meeting=job?.roundtable;
 meetingLayer.hidden=!meetingId||room!=='mission'||overview||!!journey;
 if(!meetingId)return;
 const onScreen=!meetingLayer.hidden;
 const aborted=job?.failed||['error','cancelled'].includes(job?.status);
 if(aborted){
  meetingSpeaker='';meetingSpeechUntil=0;
  for(const guest of meetingGuests){
   if(!['returning','returned'].includes(guest.phase))returnMeetingGuest(guest);
  }
 }
 meetingElapsed+=dt;
 for(const guest of meetingGuests){
  if(guest.phase==='returned')continue;
  const resident=residents.find(r=>r.key===guest.key);
  if(resident?.deleting){
   if(meetingSpeaker===guest.key)meetingSpeaker='';
   if(!['returning','returned'].includes(guest.phase))returnMeetingGuest(guest);
  }
  if(resident){resident.atRoundtable=true;resident.mount.visible=false;resident.node.hidden=true;}
  guest.travel+=dt;
  if(['entering','returning'].includes(guest.phase)){
   const fraction=reduced.matches||!motion?1:Math.min(1,Math.max(0,(guest.travel-(guest.phase==='entering'?guest.index*.18:0))/5));
   const lengths=guest.route.slice(1).map((p,i)=>p.distanceTo(guest.route[i]));let remaining=fraction*lengths.reduce((a,b)=>a+b,0),segment=0;
   while(segment<lengths.length-1&&remaining>lengths[segment])remaining-=lengths[segment++];
   guest.group.position.lerpVectors(guest.route[segment],guest.route[segment+1],Math.min(1,remaining/Math.max(.001,lengths[segment])));
   const direction=guest.route[segment+1].clone().sub(guest.route[segment]);guest.group.rotation.y=Math.atan2(direction.x,direction.z);
   if(fraction===1){if(guest.phase==='returning'){releaseMeetingGuest(guest);continue;}guest.phase='seated';guest.group.position.copy(guest.target);}
  }
  guest.seated=['seated','submitted'].includes(guest.phase);
  if(guest.seated)guest.group.rotation.y=Math.PI;
  guest.body.position.y=guest.seated?.18:Math.abs(Math.sin(guest.travel*10))*.035;
  guest.legs.forEach((leg,j)=>leg.rotation.x=guest.seated?-Math.PI/2:Math.sin(guest.travel*10+j*Math.PI)*.32);
  guest.arms.forEach((arm,j)=>arm.rotation.x=guest.seated?-.35:Math.sin(guest.travel*10+j*Math.PI)*.2);
 }
 if(meetingSpeaker&&meetingElapsed>=meetingSpeechUntil){
  const guest=meetingGuests.find(g=>g.key===meetingSpeaker);if(guest?.phase==='submitted')returnMeetingGuest(guest);
  meetingSpeaker='';
 }
 // One short acknowledgement and one departure at a time; never repeat opinions.
 if(!aborted&&onScreen&&!meetingSpeaker&&!meetingGuests.some(g=>['entering','returning'].includes(g.phase))){
  const next=meetingGuests.find(g=>g.phase==='seated'&&meeting?.replies?.[g.key]?.status==='done');
  if(next){next.phase='submitted';meetingSpeaker=next.key;meetingSpoken.add(next.key);meetingSpeechUntil=meetingElapsed+2;}
  else if(['done','cancelled','error'].includes(job?.status)){
   const unfinished=meetingGuests.find(g=>g.phase==='seated');if(unfinished)returnMeetingGuest(unfinished);
  }
 }
 syncMeetingFurniture();
 for(const guest of meetingGuests){
  guest.node.hidden=guest.phase==='returned';if(guest.node.hidden)continue;
  const reply=meeting?.replies?.[guest.key],speaking=onScreen&&guest.key===meetingSpeaker;
  guest.node.dataset.speaking=String(speaking);guest.node.dataset.seated=String(guest.seated);
  guest.node.querySelector('small').textContent=guest.phase==='returning'?'Back to '+roomTitles.lounge:guest.phase==='entering'?'Joining the table':reply?.status==='running'?'Considering the plan…':reply?.status==='error'?'Reaction unavailable':'Waiting for the results';
  const bubble=guest.node.querySelector('.roundtable-bubble');bubble.hidden=!speaking;bubble.textContent=speaking?'Opinion submitted.':'';
  positionLabel(guest.node,guest.group.position.clone().add(new THREE.Vector3(0,1.75,0)));
  guest.node.style.zIndex=speaking?'12':'2';
  if(speaking){const half=guest.node.offsetWidth/2;guest.node.style.left=THREE.MathUtils.clamp(parseFloat(guest.node.style.left),half+12,viewport.clientWidth-half-12)+'px';guest.node.style.top=Math.max(guest.node.offsetHeight+75,parseFloat(guest.node.style.top))+'px';}
 }
}
function roundtableInfo(){return {job:meetingId,tableWidth:meetingWidth,visible:meetingFurniture.visible,visibleChairs:meetingFurniture.visible?meetingChairs.children.filter(chair=>chair.visible).length:0,speaker:meetingSpeaker,guests:meetingGuests.map(g=>({key:g.key,name:g.name,appearance:g.appearance,seat:g.seat,seated:g.seated,phase:g.phase,facing:g.group.rotation.y,position:g.group.position.toArray()})),spoken:[...meetingSpoken]};}
