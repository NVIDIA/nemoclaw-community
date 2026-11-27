// SPDX-License-Identifier: Apache-2.0

// A miniature agent workshop: role workbenches around one shared brief.
function createScene() {
  const {scenarios:scenarioDefinitions,roomTitles}=window.BacDemo;
  const viewport=el('viewport');
  const scene=new THREE.Scene();
  const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true,powerPreference:'low-power'});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.6));
  renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.0;
  viewport.prepend(renderer.domElement); renderer.domElement.setAttribute('aria-hidden','true');
  const camera=new THREE.OrthographicCamera(-11,11,7,-7,.1,180);
  const focus=new THREE.Vector3(0,.15,0);
  let azimuth=.43,elevation=.76,zoom=1,drag=null,moved=false;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let motion=!reduced.matches,visible=true,lastFrame=0,clock=0,phase=-2,state=snapshot,activeSelection=selected;
  let lost=false,sceneReady=false,lastKey='',lastActive=-1,lastJob=null;
  scene.add(new THREE.HemisphereLight(0xf4f7ff,0x161c26,1.65));
  const sun=new THREE.DirectionalLight(0xffffff,3.0);sun.position.set(-5,15,8);sun.castShadow=true;
  sun.shadow.intensity=.73;
  sun.shadow.mapSize.set(2048,2048);sun.shadow.camera.left=-12;sun.shadow.camera.right=12;sun.shadow.camera.top=10;sun.shadow.camera.bottom=-10;sun.shadow.normalBias=.035;scene.add(sun);scene.add(sun.target);
  const fill=new THREE.DirectionalLight(0xc7ddff,.75);fill.position.set(8,6,-9);scene.add(fill);
  const materials=new Map();
  function mat(color,glow=false){const key=color+':'+glow;if(!materials.has(key))materials.set(key,new THREE.MeshStandardMaterial({color,roughness:.48,metalness:.16,...(glow?{emissive:color,emissiveIntensity:.35}:{})}));return materials.get(key);}
  const boxGeometry=new THREE.BoxGeometry(1,1,1);
  function box(parent,x,y,z,w,h,d,color,glow=false){const object=new THREE.Mesh(boxGeometry,mat(color,glow));object.position.set(x,y,z);object.scale.set(w,h,d);object.castShadow=true;object.receiveShadow=true;parent.add(object);return object;}
  function cylinder(parent,x,y,z,r,h,color,segments=24){const object=new THREE.Mesh(new THREE.CylinderGeometry(r,r,h,segments),mat(color));object.position.set(x,y,z);object.castShadow=true;object.receiveShadow=true;parent.add(object);return object;}
  function ring(parent,x,y,z,r,color){const mesh=new THREE.Mesh(new THREE.TorusGeometry(r,.022,6,64),mat(color,true));mesh.rotation.x=-Math.PI/2;mesh.position.set(x,y,z);parent.add(mesh);return mesh;}
  function label(text,width=512,height=100,color='#e8eef5',bg=null){const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;const context=canvas.getContext('2d');if(bg){context.fillStyle=bg;context.fillRect(0,0,width,height);}context.fillStyle=color;context.font='600 '+Math.floor(height*.48)+'px Arial';context.textAlign='center';context.textBaseline='middle';context.fillText(text,width/2,height/2,width*.94);const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;return new THREE.MeshBasicMaterial({map:texture,transparent:!bg,depthWrite:false,toneMapped:false});}
  function sign(parent,text,x,y,z,w,h,color,bg){const mesh=new THREE.Mesh(new THREE.PlaneGeometry(w,h),label(text,512,100,color,bg));mesh.position.set(x,y,z);parent.add(mesh);return mesh;}
  // Match the texture to the physical display so letters keep their natural proportions.
  function displayTitle(parent,text,x,y,z,w,h,color='#f2f6fb'){
    const canvas=document.createElement('canvas');canvas.width=2048;canvas.height=Math.round(2048*h/w);
    const ctx=canvas.getContext('2d');let size=Math.floor(canvas.height*.72);
    ctx.font='700 '+size+'px Arial';
    while(ctx.measureText(text).width>canvas.width*.92){size--;ctx.font='700 '+size+'px Arial';}
    ctx.fillStyle=color;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,canvas.width/2,canvas.height/2);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
    texture.anisotropy=renderer.capabilities.getMaxAnisotropy();
    const mesh=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false,toneMapped:false}));
    mesh.position.set(x,y,z);parent.add(mesh);return mesh;
  }
  /* AGENT_CHARACTER */
  const missionRoom=new THREE.Group();scene.add(missionRoom);
  // Wider floor with clear aisles around the Captain and specialist workstations.
  box(missionRoom,0,-.42,0,21.6,.75,15,0x151b23);
  const missionFloor=box(missionRoom,0,-.025,0,21.45,.07,14.85,0x2a333e);missionFloor.userData.scenarioFloor=true;
  const missionAccent=box(missionRoom,0,-.3,7.51,20.9,.075,.025,0x76b900,true);missionAccent.userData.scenarioAccent=true;
  for(let x=-10;x<=10;x++)box(missionRoom,x,.02,0,.014,.008,14.6,0x3a4653);
  for(let z=-7;z<=7;z++)box(missionRoom,0,.02,z,21.4,.008,.014,0x3a4653);
  box(missionRoom,0,.65,-7.25,21.6,1.35,.18,0x1e2732);
  for(const [z,length] of [[-4.225,6.05],[4.225,6.05]])box(missionRoom,-10.65,.65,z,.15,1.35,length,0x1e2732);
  box(missionRoom,0,1.36,-7.25,21.6,.055,.24,0x63778b);
  for(const [z,length] of [[-4.225,6.05],[4.225,6.05]])box(missionRoom,-10.65,1.36,z,.22,.055,length,0x63778b);
  // Keep the full Open Task illustration in its original aspect ratio.
  box(missionRoom,-.6,2.4,-7.17,5.8,3.8,.14,0x0c121b);
  const missionTitle=displayTitle(missionRoom,roomTitles.mission,-.6,4.0,-7.06,5.1,.48);missionTitle.userData.scenarioTitle=true;
  const artworkWidth=5.22,artworkHeight=artworkWidth*893/1600;
  box(missionRoom,-.6,2.175,-7.075,artworkWidth+.14,artworkHeight+.14,.025,0x343f4c);
  const artworkTexture=new THREE.TextureLoader().load('__OPEN_TASK_ART_DATA_URL__');
  artworkTexture.colorSpace=THREE.SRGBColorSpace;
  artworkTexture.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());
  const artwork=new THREE.Mesh(new THREE.PlaneGeometry(artworkWidth,artworkHeight),new THREE.MeshBasicMaterial({map:artworkTexture,toneMapped:false}));
  artwork.position.set(-.6,2.175,-7.049);missionRoom.add(artwork);
  box(missionRoom,-.6,.60,-7.06,5.22,.026,.02,0x76b900,true);
  // Preserve role IDs; arrange Dylan, Alex and Morgan from left to right.
  const positions=[[0,.4],[-6.2,-4.5],[0,-4.5],[6.2,-4.5],...state.agents.slice(4).map(()=>[10.3,0])];
  const homes=positions.map(([x,z],i)=>new THREE.Vector3(i?x:-1.65,.05,i?z+1:1.65));
  const deskLights=[],workIndicators=[],routes=[];
  const exchangeExit=new THREE.Vector3(10.3,.05,0),exchangeEntry=new THREE.Vector3(8.3,.05,0);
  const originalHomes=homes.map(h=>h.clone());
  positions.forEach(([x,z],i)=>{
    if(i>3)return;
    if(i===0){deskLights.push(ring(missionRoom,0,.085,.4,.38,colors[0]));return;}
    box(missionRoom,x,.035,z,3.35,.04,2.65,0x343f4c);
    box(missionRoom,x,.064,z+1.25,3.3,.04,.045,colors[i],true);
    box(missionRoom,x,.82,z,2.1,.14,.85,0xb6c3d1);
    box(missionRoom,x-.75,.42,z,.14,.8,.55,0x283544);box(missionRoom,x+.75,.42,z,.14,.8,.55,0x283544);
    box(missionRoom,x,1.36,z-.22,1.45,.76,.1,0x172432);
    const monitor=box(missionRoom,x,1.36,z-.159,1.29,.61,.016,0x070e17);monitor.material=mat(0x070e17).clone();workIndicators[i]=monitor;
    for(let row=0;row<3;row++){box(missionRoom,x-.32,1.53-row*.16,z-.145,.39+.13*row,.033,.01,colors[i],true);box(missionRoom,x+.43,1.41-row*.09,z-.145,.17,.026,.01,0x41627d);}
    box(missionRoom,x,.92,z+.22,.74,.018,.24,0x5e7186);
    cylinder(missionRoom,x+.85,.98,z+.12,.1,.21,colors[i],12);
    deskLights.push(ring(missionRoom,x,.085,z,.38,colors[i]));
  });
  // A separate entrance for specialists called in by the Captain.
  const exchangeDoor=new THREE.Group();missionRoom.add(exchangeDoor);
  for(const z of [-.8,.8])box(exchangeDoor,9.7,1.3,z,.18,2.6,.18,0x536d87);
  box(exchangeDoor,9.7,2.6,0,.18,.16,1.8,0x536d87);
  const exchangePanel=box(exchangeDoor,9.7,1.3,0,.07,2.4,1.5,0x233545);
  const exchangeGlow=box(exchangeDoor,9.61,2.4,0,.035,.06,1.35,0x76b900,true);
  // Shared state hub: all agents use this same versioned brief.
  cylinder(missionRoom,0,.23,.4,1.14,.44,0x152333,48);cylinder(missionRoom,0,.48,.4,1.02,.07,0x536d87,48);
  ring(missionRoom,0,.525,.4,.93,0x76b900);
  const core=box(missionRoom,0,1.5,.4,.35,.38,.35,0x76b900);core.rotation.y=Math.PI/4;
  core.material=core.material.clone();workIndicators[0]=core;
  const captainWorkspot=new THREE.Vector3(-2.05,homes[0].y,.12);
  const coreRing=ring(missionRoom,0,1.24,.4,.72,0x96d52b);
  // Layered data cards make shared state the physical center of the workspace.
  const briefPaper=mat(0xb5d0e6).clone();
  briefPaper.emissive.setHex(0xb4ed86);briefPaper.emissiveIntensity=0;
  for(let i=0;i<3;i++){
    const card=box(missionRoom,0,.72+i*.23,.4,.92,.055,.7,0xb5d0e6);
    card.rotation.y=.12+i*.15;card.material=briefPaper;
  }

  // The access gate sits at the edge of the workspace.
  box(missionRoom,9.0,.13,2.15,1.45,.26,1.8,0x24303d);
  box(missionRoom,8.35,1.03,2.15,.12,1.8,.16,0x758a9e);box(missionRoom,9.65,1.03,2.15,.12,1.8,.16,0x758a9e);
  const gate=box(missionRoom,9.0,1.36,2.15,1.42,.09,.09,0x9bbacf,true);
  // Small Spark-like appliance and planters, for scale and life.
  box(missionRoom,9.15,.54,-6.23,1.1,1.05,.74,0x1b2633);
  for(let y=.2;y<.9;y+=.11)box(missionRoom,9.15,y,-5.85,.8,.035,.015,0x4b637a);
  box(missionRoom,9.47,.92,-5.84,.065,.065,.02,0x76b900,true);
  function plant(x,z){cylinder(missionRoom,x,.25,z,.24,.5,0x35495c,8);for(let i=0;i<5;i++){const leaf=new THREE.Mesh(new THREE.ConeGeometry(.18,.62,5),mat(i%2?0x5d985b:0x295c40));leaf.position.set(x+Math.sin(i*2)*.18,.65+Math.cos(i)*.12,z+Math.cos(i*2)*.18);leaf.rotation.z=Math.sin(i)*.28;missionRoom.add(leaf);}}
  plant(-9.8,-6.35);plant(-9.8,6.1);plant(4.3,-6.4);
  // Narrow lit walkways visually tie all workstations to the shared state.
  positions.forEach(([x,z])=>{
    const points=[new THREE.Vector3(x,.073,z+1.05),new THREE.Vector3(x,.073,.4),new THREE.Vector3(0,.073,.4)];
    const route=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:colors[routes.length],transparent:true,opacity:.2}));missionRoom.add(route);routes.push(route);
  });
  // Only the selected space uses the live rig. Other floors are quiet scenery,
  // not duplicate agents or model executions.
  const missionShell=missionRoom.clone(true);
  const robots=[];const hitTargets=[];const labels=[];
  positions.forEach((_,i)=>{
    const rig=createCharacter(avatarDefaults[i]),robot=rig.group;robot.position.copy(homes[i]);robot.visible=i===0;if(i===0)robot.scale.setScalar(1.12);missionRoom.add(robot);
    const halo=ring(missionRoom,homes[i].x,.086,homes[i].z,.48,rig.color);
    const packet=box(rig.body,.39,.7,.2,.21,.27,.045,rig.color,true);packet.visible=false;
    robot.traverse(object=>{if(object.isMesh){object.userData.agent=i;hitTargets.push(object);}});
    const badge=document.createElement('button');badge.type='button';badge.className='campus-agent-label';badge.dataset.crewMember=String(i);
    badge.onclick=()=>{
      if(room!=='mission'||overview||journey)return;
      if(i===0&&state.crewMission?.needsInput){
        root.dispatchEvent(new CustomEvent('bac:review-task-access',{detail:state.crewMission.id}));
      }else choose(i);
    };
    badge.style.setProperty('--agent-color',hex(i));el('labels').append(badge);labels.push(badge);
    robots.push({...rig,robot,halo,packet,home:homes[i],path:[],idle:i*.9,destination:homes[i].clone(),exchange:null,wanted:i===0,avatarKey:JSON.stringify(avatarDefaults[i])});
  });
  function dressCrew(){
    robots.forEach((r,i)=>{
      const avatar={...(state.agents[i].avatar||avatarDefaults[i]),protection:state.agents[i].protection||'standard'},key=JSON.stringify(avatar);if(key===r.avatarKey)return;
      const rig=createCharacter(avatar);r.robot.remove(r.body);clearGeometry(r.body);r.robot.add(rig.body);
      r.body=rig.body;r.arms=rig.arms;r.legs=rig.legs;r.appearance=rig.appearance;r.avatarKey=key;
      r.packet=box(r.body,.39,.7,.2,.21,.27,.045,rig.color,true);r.packet.visible=false;
      r.halo.material=mat(rig.color,true);labels[i].style.setProperty('--agent-color','#'+rig.color.toString(16).padStart(6,'0'));
    });
    hitTargets.length=0;robots.forEach((r,i)=>r.robot.traverse(o=>{if(o.isMesh){o.userData.agent=i;hitTargets.push(o);}}));
  }
  const hotspotLayer=document.createElement('div');hotspotLayer.className='world-hotspots';viewport.append(hotspotLayer);
  const hotspots=[];
  const knowledgeProp=new THREE.Group(),weatherProp=new THREE.Group(),hiringProp=new THREE.Group();
  // The knowledge cabinet is shared by document and memory skills.
  box(knowledgeProp,-7.65,.88,-1.3,1.0,1.65,.48,0x293849);
  for(let shelf=0;shelf<3;shelf++){box(knowledgeProp,-7.65,.28+shelf*.5,-1.02,1.08,.07,.56,0x70889e);for(let j=0;j<4;j++)box(knowledgeProp,-7.99+j*.23,.5+shelf*.5,-1.05,.13,.35,.34,[0x76b900,0x479cda,0xe3b15d,0x9e85db][(j+shelf)%4]);}
  // Public-source research console.
  box(missionRoom,-9.45,.6,1.25,1.05,1.1,.62,0x293849);box(missionRoom,-9.45,1.23,1.25,.85,.6,.1,0x355e79);sign(missionRoom,'WEB',-9.45,1.24,1.31,.72,.38,'#b6deff','#162a3c');
  // Compact weather instrument instead of a landscape observatory.
  box(weatherProp,7.3,.55,-1.8,.94,1,.65,0x2e4053);cylinder(weatherProp,7.3,1.45,-1.8,.027,1.0,0xa4bfd3,8);const weatherRotor=new THREE.Group();weatherRotor.position.set(7.3,1.92,-1.8);weatherProp.add(weatherRotor);for(let i=0;i<3;i++){const blade=box(weatherRotor,0,0,0,.8,.028,.055,0x8caec8);blade.rotation.y=i*Math.PI/3;}sign(weatherProp,'WEATHER',7.3,.71,-1.462,.69,.24,'#b6deff','#182c3e');
  // A paired-channel terminal at the front edge.
  box(hiringProp,7.2,.48,4.75,.9,.92,.75,0x24384b);
  const hiringDisk=new THREE.Group();hiringDisk.position.set(7.2,1.19,4.7);hiringProp.add(hiringDisk);
  box(hiringDisk,0,0,0,.46,.75,.10,0x102032);sign(hiringDisk,'↗',0,.01,.058,.37,.56,'#b7dbe8','#304850');
  const packets=[];for(let i=0;i<4;i++){const packet=box(missionRoom,0,.6,0,.12,.17,.035,0xa5dbef,true);packet.visible=false;packets.push(packet);}
  let packetStart=new THREE.Vector3(),packetEnd=new THREE.Vector3(),packetTime=-20;
  // Dispatch follows active roles; returns follow saved outputs, never elapsed model time.
  let captainJob=null,captainRevision=null,documentFlight=null,documentProgress=0;
  const seenDeliverables=new Set(),receivedDocuments=new Set(),assignedDocuments=new Set(),documentQueue=[];
  const returnedSheets=[];
  for(let i=1;i<positions.length;i++){
    const sheet=new THREE.Group();sheet.position.set(.62,.8+i*.07,.58);missionRoom.add(sheet);
    box(sheet,0,0,0,.52,.035,.38,0xe8f0f8).material=briefPaper;box(sheet,-.19,.022,0,.05,.008,.28,colors[i],true);
    sheet.rotation.y=.10*i;sheet.visible=false;returnedSheets[i]=sheet;
  }
  const flyingDocument=new THREE.Group();missionRoom.add(flyingDocument);flyingDocument.visible=false;
  box(flyingDocument,0,0,0,.54,.72,.045,0xe8f0f8);
  const documentStripe=box(flyingDocument,0,.24,.03,.43,.08,.015,0x76b900,true);
  for(let i=0;i<3;i++)box(flyingDocument,-.03,.07-i*.12,.03,.35-i*.05,.027,.014,0x536b80);
  function syncCaptain(){
    const job=state.crewMission;if(!job){captainJob=null;captainRevision=null;documentQueue.length=0;documentFlight=null;seenDeliverables.clear();receivedDocuments.clear();assignedDocuments.clear();returnedSheets.forEach(s=>s.visible=false);flyingDocument.visible=false;return;}
    if(captainJob!==job.id){
      const initial=captainJob===null;captainJob=job.id;captainRevision=null;documentQueue.length=0;documentFlight=null;flyingDocument.visible=false;
      seenDeliverables.clear();receivedDocuments.clear();assignedDocuments.clear();returnedSheets.forEach(s=>s.visible=false);
      // Existing results on first load are already on the desk, not new work.
      if(initial){for(const i of job.completed){seenDeliverables.add(i);if(i>0&&i<positions.length)receivedDocuments.add(i);} }
    }
    if(Number.isInteger(job.revisionRole)&&captainRevision!==job.revisionRole){
      captainRevision=job.revisionRole;
      // Repeat only this participant's assignment/return animation, not the team entrance.
      if(!job.completed.includes(captainRevision)){
        seenDeliverables.delete(captainRevision);receivedDocuments.delete(captainRevision);assignedDocuments.delete(captainRevision);
        if(returnedSheets[captainRevision])returnedSheets[captainRevision].visible=false;
        for(let i=documentQueue.length-1;i>=0;i--)if(documentQueue[i].role===captainRevision)documentQueue.splice(i,1);
        if(documentFlight?.role===captainRevision){documentFlight=null;flyingDocument.visible=false;}
      }
    }
    for(const i of job.completed){
      if(seenDeliverables.has(i))continue;seenDeliverables.add(i);
      if(i>0&&i<positions.length)documentQueue.push({kind:'return',role:i});
    }
    const active=new Set(job.activeStages||[]);
    // Discard deliveries to roles that finished, stopped, or were excluded while offscreen.
    const valid=d=>d.kind==='return'||(active.has(d.role)&&!job.completed.includes(d.role)&&job.enabledRoles?.includes(d.role)!==false);
    for(let i=documentQueue.length-1;i>=0;i--)if(!valid(documentQueue[i]))documentQueue.splice(i,1);
    if(documentFlight&&!valid(documentFlight)){documentFlight=null;flyingDocument.visible=false;}
    for(const role of active){
      if(role<=0||role>=positions.length||job.completed.includes(role)||job.enabledRoles?.includes(role)===false||assignedDocuments.has(role))continue;
      if(documentFlight?.kind==='assignment'&&documentFlight.role===role||documentQueue.some(d=>d.kind==='assignment'&&d.role===role))continue;
      documentQueue.push({kind:'assignment',role,settledFor:0});
    }
    receivedDocuments.forEach(i=>returnedSheets[i].visible=true);
  }
  function animateCaptain(dt){
    if(!documentFlight&&!documentQueue.length)return;
    if(reduced.matches||!motion){for(const d of [...documentQueue,...(documentFlight?[documentFlight]:[])]){if(d.kind==='return')receivedDocuments.add(d.role);else assignedDocuments.add(d.role);}documentQueue.length=0;documentFlight=null;flyingDocument.visible=false;receivedDocuments.forEach(i=>returnedSheets[i].visible=true);renderCrewLabels();return;}
    if(!motion||room!=='mission'||overview||journey)return;
    // Let each recipient settle at its desk before Casey dispatches the paper.
    // Count all waiting recipients independently, including during other flights.
    for(const d of documentQueue){
      if(d.kind!=='assignment')continue;
      const r=crewPresentation(d.role),seated=r?.robot.visible&&!r.exchange&&!r.path.length&&r.robot.position.distanceTo(r.home)<.12;
      d.settledFor=seated?Math.min(1.5,d.settledFor+dt):0;
    }
    if(!documentFlight&&documentQueue.length&&!crewPresentation(documentQueue[0].role)?.robot.visible)return;
    if(!documentFlight&&documentQueue[0]?.kind==='assignment'&&documentQueue[0].settledFor<1.5)return;
    if(!documentFlight&&documentQueue.length){documentFlight=documentQueue.shift();documentProgress=0;documentStripe.material=mat(colors[documentFlight.role],true);}
    if(!documentFlight)return;
    documentProgress=Math.min(1,documentProgress+dt/1.65);const t=documentProgress,p=t*t*(3-2*t),d=documentFlight;
    const captain=robots[0].robot.position.clone().add(new THREE.Vector3(0,1,.25));
    const specialist=crewPresentation(d.role).robot.position.clone().add(new THREE.Vector3(.25,1,.15));
    const tray=new THREE.Vector3(.62,1,.58);
    flyingDocument.visible=true;flyingDocument.position.lerpVectors(d.kind==='return'?specialist:captain,d.kind==='return'?tray:specialist,p);
    flyingDocument.position.y+=Math.sin(t*Math.PI)*1.3;flyingDocument.rotation.set(-.2,Math.sin(t*Math.PI)*.45,Math.sin(t*Math.PI*2)*.1);
    if(d.kind==='return'&&state.agents[0].included!==false)robots[0].arms[0].rotation.x=-.65*Math.sin(t*Math.PI);
    else if(state.agents[0].included!==false)robots[0].arms[1].rotation.x=-.55*Math.sin(t*Math.PI);
    if(t===1){if(d.kind==='return'){receivedDocuments.add(d.role);returnedSheets[d.role].visible=true;}else assignedDocuments.add(d.role);documentFlight=null;flyingDocument.visible=false;renderCrewLabels();}
  }
  let room='mission';
  /* WORLD_ROOMS */
  /* WORLD_SCENARIOS */
  /* WORLD_NAVIGATION */
  /* WORLD_ROUNDTABLE */
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
  function cam(){
    camera.position.set(Math.sin(azimuth)*Math.cos(elevation)*50,Math.sin(elevation)*50,Math.cos(azimuth)*Math.cos(elevation)*50).add(focus);
    camera.lookAt(focus);camera.zoom=zoom;camera.updateProjectionMatrix();camera.updateMatrixWorld();
    sun.position.copy(focus).add(new THREE.Vector3(-5,15,8));sun.target.position.copy(focus);sun.target.updateMatrixWorld();
  }
  function frame(){
    const w=viewport.clientWidth,h=viewport.clientHeight;if(!w||!h)return;
    const aspect=w/h,vertical=viewHalfHeight||roomHeight(room);
    camera.left=-vertical*aspect;camera.right=vertical*aspect;camera.top=vertical;camera.bottom=-vertical;cam();
  }
  // CSS owns layout; resize only the drawing buffer, never the canvas's CSS size.
  function resize(){
    const w=viewport.clientWidth,h=viewport.clientHeight;if(!w||!h)return;
    renderer.setSize(w,h,false);resizeNavigation();frame();renderer.render(scene,camera);
  }
  function movement(){
    robots.forEach(r=>{if(!r.exchange)r.path=r.robot.visible&&r.robot.position.distanceTo(r.home)>.06?[r.home.clone()]:[];r.packet.visible=false;});
    const active=state.agents.findIndex((a,i)=>i<robots.length&&(a.lane===1||a.lane===2));
    if(active>=0){
      const r=robots[active],station={builder:[0,-2.3],documents:[-6.55,-.45],memory:[-6.55,-.45],weather:[6.3,-1],web:[-6.5,1.6],writer:[-4.8,4]}[state.missionSkill];
      const target=state.crewMission&&active===0?captainWorkspot:station?new THREE.Vector3(station[0],.05,station[1]):r.home.clone();
      if(!r.exchange)r.path=state.crewMission||active===0?[target]:[new THREE.Vector3(r.robot.position.x,.05,.5),new THREE.Vector3(0,.05,.5),new THREE.Vector3(target.x,.05,.5),target];r.packet.visible=!state.crewMission;
      packetStart=lastJob===state.jobId&&lastActive>=0&&lastActive!==active?robots[lastActive].home.clone():new THREE.Vector3(0,.6,.4);packetEnd=target.clone();packetTime=clock;
    }
    lastActive=active;lastJob=state.jobId;
    routes.forEach((route,i)=>{route.material.opacity=state.agents[i]?.lane===1 ? .85 : .18;});
    // Equipment decisions are app approvals; never color OpenShell as enforced from them.
    if(!motion)settleCrewExchange();
  }
  /* WORLD_CREW_EXCHANGE */
  /* WORLD_VISITOR_TRAVEL */
  const workLines=['Organizing the brief and assigning the team…','Comparing sources and choosing demo themes…','Reviewing presenter coverage and breaks…','Writing the webpage and LinkedIn post…','Preparing the survey and reviewing the plan…','Building the event page…'];
  function crewWorking(i){
    if(state.agents[i].included===false||state.agents[i].lane!==1)return false;
    return !state.crewMission||(state.crewMission.activeStages||[]).includes(i)&&(i===0||assignedDocuments.has(i));
  }
  function captainFacing(){
    const job=state.crewMission;
    if(job.needsInput||(!documentFlight&&!job.activeStages?.length))return 0;
    const specialist=documentFlight?.role??job.activeStages?.find(role=>role>0);
    const teammate=specialist!=null?crewPresentation(specialist):null;
    const target=teammate?.robot.visible?teammate.robot.position:core.position;
    const position=robots[0].robot.position;
    return Math.atan2(target.x-position.x,target.z-position.z);
  }
  function workingStatus(role){
    return '<span class="crew-working-badge"><span aria-hidden="true" class="crew-working-dot"></span>Working</span><span class="crew-working-role">'+escape(role)+'</span>';
  }
  let announcedTeamJob=null,teamAnnouncementHtml='',teamAnnouncementUntil=0,announcementKind='';
  function renderCrewLabels(){
    const job=state.crewMission;
    if(job?.id!==announcedTeamJob){announcedTeamJob=job?.id;teamAnnouncementHtml='';teamAnnouncementUntil=0;announcementKind='';}
    if(job?.kind==='plan'&&Array.isArray(job.assignedRoles)&&job.assignedRoles.every(role=>state.agents[role]?.displayed!==false)&&!announcementKind){
      announcementKind='assigned';
      const names=job.assignedRoles.filter(role=>role>0).map(role=>state.agents[role]?.name).filter(Boolean).map(name=>'<strong>'+escape(name)+'</strong>');
      if(names.length&&['queued','running','waiting'].includes(job.status)){
        const list=names.length<2?names[0]:names.slice(0,-1).join(', ')+' and '+names.at(-1);
        teamAnnouncementHtml='We need '+list+'.';teamAnnouncementUntil=performance.now()+10000;
      }
    }
    if(job?.unassignedAt&&announcementKind!=='declined'){
      announcementKind='declined';
      // A refreshed or reopened studio may contain a much older completed task.
      const remaining=Math.min(8000,job.unassignedAt*1000+8000-Date.now());
      teamAnnouncementHtml='Looks like we need another teammate for this one.';
      teamAnnouncementUntil=remaining>0?performance.now()+remaining:0;
    }
    const announcement=job?.needsInput?'<strong class="crew-permission-title"><span aria-hidden="true">!</span>Your call!</strong>Can you review access so we can continue?':performance.now()<teamAnnouncementUntil?teamAnnouncementHtml:'';
    labels.forEach((b,i)=>{
      const working=crewWorking(i)&&!robots[i].exchange&&state.agents[i].included!==false;
      const permissionRequest=i===0&&!!job?.needsInput;
      b.classList.toggle('permission-request',permissionRequest);
      const status=robots[i].exchange==='leaving'?'Leaving team':robots[i].exchange==='entering'?'Joining team':state.agents[i].included===false?'Available':state.agents[i].lane===2?'Waiting for you':state.crewMission?.kind==='plan'&&i>0&&state.agents[i].lane===0?state.agents[i].status+' · '+state.agents[i].role:state.agents[i].role;
      const name=escape(state.agents[i].name);
      b.innerHTML=(permissionRequest?'':working?'<b>'+name+'</b>':name)+'<small>'+(working?workingStatus(state.agents[i].role):escape(status))+'</small>'+(i===0&&announcement?'<span class="crew-team-bubble">'+announcement+'</span>':'');
      if(permissionRequest){
        b.removeAttribute('aria-pressed');b.setAttribute('aria-haspopup','dialog');
        b.setAttribute('aria-label','Review requested access in OpenShell Policy');
      }else{
        b.removeAttribute('aria-haspopup');b.setAttribute('aria-pressed',String(activeSelection===i));
        b.setAttribute('aria-label','Select '+state.agents[i].name+(working?', working':''));
      }
      b.classList.toggle('working',working);b.classList.toggle('selected',activeSelection===i);b.classList.toggle('excluded',state.agents[i].included===false);b.classList.toggle('waiting',state.agents[i].lane===2);
    });}

  function update(next,index){state=next;placeTeam();if(scenarioMoved)settleCrewExchange();syncRoundtable();syncVisitorTeam();syncCaptain();activeSelection=index;phase=state.phase;dressCrew();const key=[state.jobId,state.phase,state.missionSkill,state.crewMission?.id,state.crewMission?.enabledRoles?.join(),state.agents.map(a=>a.lane).join('')].join(':');if(key!==lastKey){lastKey=key;movement();}renderCrewLabels();}

  /* WORLD_PROTECTION */

  function motionButton(){el('motion').textContent=motion?'Ⅱ':'▶';el('motion').setAttribute('aria-label',motion?'Pause scene motion':'Resume scene motion');}
  el('motion').onclick=()=>{motion=!motion;if(!motion)studioSound.stop();motionButton();};reduced.addEventListener('change',()=>{motion=!reduced.matches;if(!motion)studioSound.stop();motionButton();});
  el('camera').onclick=resetNavigation;
  renderer.domElement.addEventListener('pointerdown',e=>{if(journey||e.button!==0)return;if(room==='lounge'&&!overview){const rect=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);const hit=raycaster.intersectObjects(roomHitTargets(),true)[0];if(hit&&beginResidentDrag(e,hit.object.userData.resident))return;}drag={x:e.clientX,y:e.clientY};moved=false;renderer.domElement.setPointerCapture(e.pointerId);});
  renderer.domElement.addEventListener('pointermove',e=>{if(moveResidentDrag(e))return;if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>2)moved=true;azimuth-=dx*.005;elevation=Math.max(room==='workshop'?.2:.5,Math.min(1.35,elevation+dy*.003));drag={x:e.clientX,y:e.clientY};cam();});
  renderer.domElement.addEventListener('pointerup',e=>{if(endResidentDrag())return;if(!drag)return;if(!moved){const rect=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);if(!journey){const hits=raycaster.intersectObjects(navigationTargets(),true);if(hits.length){const object=hits[0].object;if(!selectNavigationObject(object)){if(room==='mission')choose(object.userData.agent);else selectRoomObject(object);}}}}drag=null;});
  renderer.domElement.addEventListener('pointercancel',()=>{endResidentDrag(true);drag=null;});
  renderer.domElement.addEventListener('wheel',e=>{e.preventDefault();if(journey)return;zoom=Math.max(.75,Math.min(1.9,zoom-e.deltaY*.0007));cam();},{passive:false});
  renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();lost=true;el('fallback').hidden=false;root.dataset.renderer='lost';});renderer.domElement.addEventListener('webglcontextrestored',()=>{lost=false;el('fallback').hidden=true;root.dataset.renderer='webgl';});
  new ResizeObserver(resize).observe(viewport);new IntersectionObserver(items=>visible=items[0].isIntersecting).observe(viewport);
  function positionLabel(node,point){const p=point.clone().project(camera);node.style.left=(p.x*.5+.5)*viewport.clientWidth+'px';node.style.top=(-p.y*.5+.5)*viewport.clientHeight+'px';node.style.display=p.z>1?'none':'';}
  // Modal forms cover the scene. Keep incoming state updates, but spare their
  // inputs the WebGL, label layout and backdrop recompositing on every frame.
  const studioDialog=document.getElementById('studio-dialog');
  function animate(now){requestAnimationFrame(animate);if(document.hidden||root.hidden||studioDialog?.open||!viewport.clientWidth||lost){lastFrame=now;return;}if(now-lastFrame<32)return;const dt=Math.min((now-lastFrame)/1000,.06);lastFrame=now;if(motion)clock+=dt;
    if(teamAnnouncementUntil&&now>=teamAnnouncementUntil){teamAnnouncementUntil=0;renderCrewLabels();}
    animateNavigation(now);animateRooms(dt);animateRoundtable(dt);animateCrewExchange(dt);animateVisitors(dt);
    // Keep idle name buttons at the desk while the character fidgets; walking labels still follow.
    robots.forEach((r,i)=>{
      if(!r.robot.visible){r.halo.visible=false;labels[i].hidden=true;return;}
      labels[i].hidden=false;
      const captain=i===0&&state.crewMission;
      let walking=false;
      if(motion){
        if(r.path.length){
          const delta=r.path[0].clone().sub(r.robot.position),dist=delta.length();
          if(dist<.1)r.path.shift();
          else{
            walking=true;
            r.robot.position.addScaledVector(delta.normalize(),Math.min(dist,dt*(r.exchange?4:1.65)));
            r.robot.rotation.y=Math.atan2(delta.x,delta.z);
          }
        }else if(!r.exchange&&state.agents[i].lane===0&&state.agents[i].included!==false&&i!==0&&state.crewMission?.kind!=='plan'){
          const target=r.home.clone().add(new THREE.Vector3(Math.sin(clock*.45+i)*.32,0,Math.cos(clock*.45+i)*.18));
          const delta=target.clone().sub(r.robot.position);
          walking=delta.length()>.05;
          r.robot.position.lerp(target,.025);
          r.robot.rotation.y=THREE.MathUtils.lerp(r.robot.rotation.y,Math.atan2(delta.x,delta.z),.04);
        }else if(captain){
          const turn=captainFacing()-r.robot.rotation.y;
          r.robot.rotation.y+=Math.atan2(Math.sin(turn),Math.cos(turn))*Math.min(1,dt*6);
        }else r.robot.rotation.y=THREE.MathUtils.lerp(r.robot.rotation.y,crewWorking(i)?Math.PI:0,.08);
        r.body.position.y=walking?Math.abs(Math.sin(clock*8+i))*.04:Math.sin(clock*2+i)*.02;
        r.legs.forEach((l,j)=>l.rotation.x=walking?Math.sin(clock*9+i+j*Math.PI)*.4:0);
        const working=!walking&&crewWorking(i);
        r.arms.forEach((arm,j)=>{
          if(working&&captain&&!state.crewMission.needsInput){
            arm.rotation.x=j===0?-.16:-.55+Math.sin(clock*2)*.08;
          }else if(working&&!captain)arm.rotation.x=-.85+Math.sin(clock*9+j*Math.PI+i)*.16;
          else arm.rotation.x=Math.sin(clock*(walking?8:1.6)+j*Math.PI+i)*(walking ? .38 : .08);
        });
      }else if(captain&&reduced.matches)r.robot.rotation.y=captainFacing();
      r.halo.position.set(r.robot.position.x,.086,r.robot.position.z);r.halo.visible=i===activeSelection||state.agents[i].lane!==0;const labelAnchor=state.agents[i].lane===0&&!r.path.length?r.home:r.robot.position;const labelHeight=labels[i].classList.contains('working')?1.92:1.65;positionLabel(labels[i],missionRoom.localToWorld(labelAnchor.clone().add(new THREE.Vector3(0,labelHeight,0))));});
    if(room==='mission')hotspots.forEach(h=>positionLabel(h.button,missionRoom.localToWorld(h.position.clone())));
    if(motion){core.rotation.y=clock*.25;coreRing.position.y=1.35+Math.sin(clock*1.5)*.045;weatherRotor.rotation.y=clock*.28;}
    const readingBrief=state.crewMission && !state.crewMission.needsInput && crewWorking(0);
    briefPaper.emissiveIntensity=readingBrief ? .72+(motion?Math.sin(clock*2.4)*.18:0) : 0;
    workIndicators.forEach((indicator,i)=>{
      const role=deskRole(i),busy=role!=null&&crewWorking(role);
      deskLights[i].visible=busy;
      indicator.material.emissive.setHex(busy?colors[role]:0);
      indicator.material.emissiveIntensity=busy ? .3+Math.sin(clock*3+i)*.12 : 0;
    });
    packets.forEach((p,i)=>{const t=(clock-packetTime-i*.13)/2.8;p.visible=!state.crewMission&&t>=0&&t<=1&&state.phase>=0;if(p.visible){p.position.lerpVectors(packetStart,packetEnd,t);p.position.y=.65+Math.sin(t*Math.PI)*1.15;}});
    animateCaptain(dt);
    animateProtection(now);
    renderer.render(scene,camera);
  }
  setScenario('plan');motionButton();resize();update(snapshot,0);sceneReady=true;requestAnimationFrame(animate);root.dataset.renderer='webgl';
  return {resize,update,setRoom,setScenario,setScenarioStatus,scenarios:showScenarios,setCollection,observeProtection,observeExternalActivity,protectionReplyDelay,setDraft,welcomeAgent,finishArrival,overview:showOverview,inspect:()=>({sceneStyle:'connected-studio',protectionHits:[...protectionHits.values()].map(h=>({id:h.event.id,owner:h.event.owner,role:h.event.role,action:h.event.action,source:h.event.source,globeRotation:h.earth?.rotation.y,visible:h.group.visible,animated:motion&&h.phase!=='blocked',phase:h.phase})),visitorTravel:visitorTravelInfo(),visitorSeating:{chairs:visitorBenches.children.length,positions:visitorBenches.children.map(chair=>chair.position.toArray())},roundtable:roundtableInfo(),arrival:arrival?{key:arrival.key,avatar:{...arrival.rig.appearance},phase:arrival.time<1.8?'loading':'walking',position:arrival.rig.group.position.toArray()}:null,room,navigation:navigationInfo(),residents:residentInfo(),draft:draftProfile,draftPreview:draftRig?{avatar:{...draftRig.appearance},visible:draftRig.group.visible&&draftRig.group.parent===workshopRoom}:null,draftShield:!!draftRig?.body.getObjectByName('openshell-shield'),crewExchange:robots.map((r,role)=>({role,visible:r.robot.visible,phase:r.exchange,wanted:r.wanted})),deskAssignments:[...deskAssignments],crewHomes:robots.map(r=>r.home.toArray()),selectedTeam:state.crewMission?.enabledRoles||[0],crewAvatars:robots.map(r=>r.appearance),activeRole:lastActive,captain:{position:robots[0].robot.position.toArray(),job:captainJob,received:[...receivedDocuments],assigned:[...assignedDocuments],pending:documentQueue.map(d=>({...d})),inFlight:documentFlight?{...documentFlight}:null},robots:robots.map(r=>r.robot.position.toArray()),phase,motion,visible,lost,lastFrame,clock,rootHidden:root.hidden,documentHidden:document.hidden,camera:[azimuth,elevation,zoom],hotspots:hotspots.map(h=>h.id)})};
}
