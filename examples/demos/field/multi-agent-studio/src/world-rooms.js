// SPDX-License-Identifier: Apache-2.0

// All rooms share one renderer and the same camera/fullscreen lifecycle.
const loungeRoom=new THREE.Group(),workshopRoom=new THREE.Group();scene.add(loungeRoom,workshopRoom);
// All three rooms stay in one connected scene.
const residentLayer=document.createElement('div');residentLayer.className='world-residents';viewport.append(residentLayer);residentLayer.hidden=true;
const residents=[],residentMeshes=[];let collection=[],selectedResident='',draftProfile={name:'Jinny',persona:'guide',avatar:avatarDefaults[0]},draftRig=null,draftKey='';
const roomCameras={mission:[.43,.76,1],lounge:[.43,.76,1],workshop:[.34,.64,1]};
function floor(parent,width,depth){
  box(parent,0,-.3,0,width,.55,depth,0x151b23);
  box(parent,0,-.012,0,width-.12,.05,depth-.12,0x26323f);
  box(parent,0,-.13,depth/2+.01,width-.45,.035,.02,0x76b900,true);
  const gridColor=0x2e3c49;
  for(let x=-width/2+1;x<width/2;x++)box(parent,x,.019,0,.012,.006,depth-.3,gridColor);
  for(let z=-depth/2+1;z<depth/2;z++)box(parent,0,.019,z,width-.3,.006,.012,gridColor);
}
function roomSign(parent,title,x,y,z,width,height,titleHeight){
  box(parent,x,y,z,width,height,.14,0x354453);
  displayTitle(parent,title,x,y+.06,z+.11,width*.9,titleHeight);
  box(parent,x,y-height*.37,z+.115,width*.17,.042,.012,0x76b900,true);
}
floor(loungeRoom,18,12.6);
loungeRoom.add(knowledgeProp,weatherProp);knowledgeProp.position.x=1;weatherProp.position.x=-.5;
box(loungeRoom,0,.65,-6.05,18,1.35,.18,0x1e2732);
box(loungeRoom,-8.85,.65,0,.15,1.35,12,0x1e2732);
box(loungeRoom,0,1.36,-6.05,18,.055,.24,0x63778b);
box(loungeRoom,-8.85,1.36,0,.22,.055,12,0x63778b);
roomSign(loungeRoom,roomTitles.lounge,0,2,-5.97,6.6,1.42,.90);
for(const x of [-6.4,6.4]){box(loungeRoom,x,.45,-4.65,3.1,.7,.94,0x334453);box(loungeRoom,x,.9,-5.07,3.1,.7,.17,0x45596c);box(loungeRoom,x-1.5,.7,-4.65,.15,.7,.95,0x45596c);box(loungeRoom,x+1.5,.7,-4.65,.15,.7,.95,0x45596c);}
const residentPods=new THREE.Group();loungeRoom.add(residentPods);
function clearGeometry(parent){
  const owned=new Set();
  parent.traverse(({geometry})=>{
    if(geometry&&!sharedGeometries.has(geometry))owned.add(geometry);
  });
  for(const geometry of owned)geometry.dispose();
  parent.clear();
}
/* LOUNGE_LIFE */
floor(workshopRoom,12,8.5);
workshopRoom.add(hiringProp);hiringProp.position.set(-3,0,-3);
for(const x of [-3.6,3.6]){box(workshopRoom,x,.725,-4.16,4.8,1.45,.17,0x17222e);box(workshopRoom,x,1.46,-4.16,4.8,.035,.20,0x63778b);}
// A rear-side sign leaves the central doorway open.
roomSign(workshopRoom,roomTitles.workshop,-3.3,2.05,-4.08,4,1.1,.8);
const hiringPlatform=cylinder(workshopRoom,0,.14,.5,1.85,.25,0x182432,64);
cylinder(workshopRoom,0,.29,.5,1.65,.08,0x5e7184,64);
const draftRing=ring(workshopRoom,0,.345,.5,1.57,0x76b900);
for(const x of [-4.5,4.5]){box(workshopRoom,x,.75,-2.2,1.25,1.5,.85,0x314356);for(let y=.25;y<1.4;y+=.22)box(workshopRoom,x,y,-1.765,1.0,.065,.02,0x768d9f);box(workshopRoom,x+.42,1.32,-1.74,.08,.08,.02,0x76b900,true);}
function setDraft(profile){
  draftProfile=profile;const avatar={...(profile.avatar||avatarDefaults[0]),protection:profile.protection||'standard'},key=JSON.stringify(avatar);if(key===draftKey)return;
  const next=createCharacter(avatar);next.group.scale.setScalar(2.05);next.group.position.set(0,.35,.5);
  if(draftRig){workshopRoom.remove(draftRig.group);clearGeometry(draftRig.group);}
  draftRig=next;draftKey=key;workshopRoom.add(draftRig.group);draftRing.material=mat(draftRig.color,true);
  // Input feedback must not wait for the ambient animation loop to resume.
  // The initial draft is built before the camera and room layout are ready.
  if(sceneReady&&!lost&&!document.hidden&&!root.hidden&&!studioDialog?.open&&viewport.clientWidth)renderer.render(scene,camera);
}
// Saved profile arrival is visual only; native runtime registration still happens on Run.
let arrival=null;
function finishArrival(){
  if(!arrival)return;
  const a=arrival;arrival=null;clearTimeout(a.timeout);
  scene.remove(a.rig.group);clearGeometry(a.rig.group);
  hiringProp.add(a.packet);a.packet.position.copy(a.diskPosition);a.packet.quaternion.copy(a.diskQuaternion);a.packet.scale.copy(a.diskScale);a.packet.visible=true;
  a.resident.mount.visible=true;a.resident.node.hidden=false;
  a.resident.waitUntil=loungeTime+1.2;
  // Keep the hiring pedestal empty until the next draft is requested.
  a.resolve();
}
function welcomeAgent(key){
  finishArrival();
  const resident=residents.find(r=>r.key===key);
  if(!resident)return Promise.resolve();
  queueWelcome(key);
  if(reduced.matches||!motion||document.hidden)return Promise.resolve();
  // Move the actual preview when it matches the saved profile; don't swap it
  // for another character as the disk loads. Detach ownership from the editor.
  const matches=draftRig&&['body','color','accessory','protection'].every(field=>draftRig.appearance[field]===resident.appearance[field]);
  const rig=matches?draftRig:createCharacter(resident.appearance);
  if(matches){workshopRoom.remove(rig.group);draftRig=null;draftKey='';}
  rig.group.visible=true;rig.group.scale.setScalar(2.05);
  const start=workshopRoom.localToWorld(new THREE.Vector3(0,.35,.5));rig.group.position.copy(start);scene.add(rig.group);
  // Lift the actual disk out of its dock, preserving its appearance and origin.
  const packet=hiringDisk,diskPosition=packet.position.clone(),diskQuaternion=packet.quaternion.clone(),diskScale=packet.scale.clone();
  const source=packet.getWorldPosition(new THREE.Vector3());
  scene.attach(packet);packet.position.copy(source);
  const destination=loungeRoom.localToWorld(resident.group.position.clone());
  resident.mount.visible=false;resident.node.hidden=true;
  if(draftRig)draftRig.group.visible=false;
  journey=null;overview=false;refreshNavigation();
  return new Promise(resolve=>{
    arrival={key,resident,rig,packet,diskPosition,diskQuaternion,diskScale,start,source,destination,time:0,resolve,
      points:[start,new THREE.Vector3(0,.05,14),new THREE.Vector3(0,.05,6),destination],
      timeout:setTimeout(finishArrival,12000)};
  });
}
function animateArrival(dt){
  if(!arrival)return;
  if(reduced.matches||!motion){finishArrival();return;}
  const a=arrival;a.time+=dt;
  a.resident.mount.visible=false;a.resident.node.hidden=true;
  if(draftRig)draftRig.group.visible=false;
  if(a.time<1.8){
    const t=a.time/1.8,target=a.start.clone().add(new THREE.Vector3(0,2.2,0));
    a.packet.position.lerpVectors(a.source,target,t);
    a.packet.position.y+=Math.sin(t*Math.PI)*2.4;
    a.packet.rotation.y=t*Math.PI*2;a.packet.scale.setScalar(1-Math.pow(t,4)*.9);
  }else{
    a.packet.visible=false;
    const t=Math.min(1,(a.time-1.8)/5.2),lengths=a.points.slice(1).map((p,i)=>p.distanceTo(a.points[i]));
    let remaining=t*lengths.reduce((x,y)=>x+y,0),i=0;
    while(i<lengths.length-1&&remaining>lengths[i])remaining-=lengths[i++];
    a.rig.group.position.lerpVectors(a.points[i],a.points[i+1],Math.min(1,remaining/lengths[i]));
    const direction=a.points[i+1].clone().sub(a.points[i]);
    a.rig.group.rotation.y=Math.atan2(direction.x,direction.z);
    a.rig.group.scale.setScalar(2.05-.75*Math.min(1,t*3));
    a.rig.body.position.y=Math.abs(Math.sin(a.time*10))*.045;
    a.rig.legs.forEach((leg,j)=>leg.rotation.x=Math.sin(a.time*10+j*Math.PI)*.35);
    a.rig.arms.forEach((arm,j)=>arm.rotation.x=Math.sin(a.time*10+j*Math.PI)*.25);
    focus.lerp(a.rig.group.position.clone().add(new THREE.Vector3(0,.6,0)),Math.min(1,dt*4));cam();
    if(t===1)finishArrival();
  }
}
document.addEventListener('visibilitychange',()=>{if(document.hidden)finishArrival();});
function animateRooms(dt){
  animateArrival(dt);
  if((room==='workshop'||overview||journey)&&draftRig){if(motion){draftRig.group.rotation.y=Math.sin(clock*.35)*.24;draftRig.body.position.y=Math.sin(clock*1.8)*.025;draftRig.arms[0].rotation.x=Math.sin(clock*1.5)*.12;}}
  if(room==='lounge'||overview||journey||arrival)animateLounge(dt);
}
function roomHitTargets(){return room==='lounge'?residentMeshes.filter(o=>residents.some(r=>r.key===o.userData.resident&&!r.atOpenTask&&!r.atRoundtable)):[];}
function selectRoomObject(object){if(object.userData.resident)root.dispatchEvent(new CustomEvent('bac:collection-select',{detail:object.userData.resident}));}
function residentInfo(){return residents.map(r=>({key:r.key,avatar:r.appearance,persona:r.persona,tone:r.tone,verbosity:r.verbosity,position:r.group.position.toArray(),activity:r.activity,atRoundtable:!!r.atRoundtable,atOpenTask:!!r.atOpenTask,visible:r.mount.visible,speech:r.speechText||null}));}
setDraft(draftProfile);
