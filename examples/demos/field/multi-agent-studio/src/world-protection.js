// SPDX-License-Identifier: Apache-2.0

// Both directions require native OpenShell policy evidence, never an approval click.
const protectionSeen=new Set(),protectionHits=new Map(),protectionCooldown=new Map();
const externalActivitySeen=new Set(),externalActivityPrimed=new Set(),nativeAllowSeen=new Map();
function protectionReplyDelay(){
  // Keep the chat/bubble interface while showing completed replies alongside
  // the shield animation. Native verification and event timing are unchanged.
  return null;
}
let protectionPrimed=false;
const protectionLayer=document.createElement('div');protectionLayer.className='world-protection-layer';viewport.append(protectionLayer);
function protectionTarget(event){return event.role===null?(visitorTravel.get(event.owner)?.group||residents.find(r=>r.key===event.owner)?.group):robots[event.role]?.robot;}
function protectionVisible(event){
  return !overview&&!journey&&(event.role!==null?room==='mission':visitorTravel.has(event.owner)?room==='mission'&&activeScenario==='plan':room==='lounge');
}
function placeProtectionNotice(hit,point){
  const speaker=room==='lounge'&&hit.event.role===null
    ?residents.find(r=>r.key===hit.event.owner&&r.node.dataset.speaking==='true'):null;
  if(speaker){
    // A reply and its policy outcome share one readable card instead of
    // competing for the same point above the character's head.
    if(hit.label.parentNode!==speaker.node){
      hit.label.dataset.inline='true';
      speaker.node.insertBefore(hit.label,speaker.node.querySelector('.world-resident-speech'));
      hit.label.style.removeProperty('left');hit.label.style.removeProperty('top');hit.label.style.removeProperty('display');
      placeResident(speaker);
    }
    return;
  }
  if(hit.label.parentNode!==protectionLayer){delete hit.label.dataset.inline;protectionLayer.append(hit.label);}
  positionLabel(hit.label,point);
  const half=hit.label.offsetWidth/2;
  hit.label.style.left=Math.max(half+8,Math.min(viewport.clientWidth-half-8,parseFloat(hit.label.style.left)))+'px';
  hit.label.style.top=Math.max(hit.label.offsetHeight+8,Math.min(viewport.clientHeight-8,parseFloat(hit.label.style.top)))+'px';
}
function disposeProtection(hit){
  scene.remove(hit.group);hit.label.remove();
  hit.group.traverse(o=>{o.geometry?.dispose();if(o.material)o.material.dispose();});
}
function protectionMaterial(color,opacity=1){return new THREE.MeshBasicMaterial({color,transparent:true,opacity,side:THREE.DoubleSide,depthWrite:false,toneMapped:false,blending:THREE.AdditiveBlending});}
function createProtectionShell(){
  return new THREE.Mesh(new THREE.SphereGeometry(1.8,48,24,0,Math.PI*2,0,Math.PI/2),new THREE.ShaderMaterial({
    transparent:true,depthWrite:false,side:THREE.DoubleSide,blending:THREE.AdditiveBlending,
    uniforms:{elapsed:{value:-1},fade:{value:1},impactPoint:{value:new THREE.Vector3(1.35,1/1.08,.75)}},
    vertexShader:`varying vec3 localPoint;varying vec3 viewNormal;varying vec3 viewDirection;varying vec2 surfaceUV;
      void main(){localPoint=position;surfaceUV=uv;viewNormal=normalize(normalMatrix*normal);vec4 p=modelViewMatrix*vec4(position,1.);viewDirection=-p.xyz;gl_Position=projectionMatrix*p;}`,
    fragmentShader:`uniform float elapsed;uniform float fade;uniform vec3 impactPoint;
      varying vec3 localPoint;varying vec3 viewNormal;varying vec3 viewDirection;varying vec2 surfaceUV;
      void main(){
        float edge=pow(1.-abs(dot(normalize(viewNormal),normalize(viewDirection))),2.);
        vec2 p=surfaceUV*vec2(32.,20.),r=vec2(1.,1.732);
        vec2 a=mod(p,r)-r*.5,b=mod(p-r*.5,r)-r*.5;
        vec2 cell=abs(dot(a,a)<dot(b,b)?a:b);
        float hex=max(cell.x,dot(cell,vec2(.5,.866)));
        float grid=smoothstep(.43,.485,hex);
        float distanceToHit=distance(localPoint,impactPoint);
        float hitEnabled=step(0.,elapsed),t=max(0.,elapsed);
        float wave=(1.-smoothstep(.025,.12,abs(distanceToHit-t*2.2)))*exp(-t*.95)*hitEnabled;
        float echo=(1.-smoothstep(.02,.08,abs(distanceToHit-max(0.,t-.2)*1.6)))*exp(-t*1.7)*hitEnabled;
        float flash=exp(-distanceToHit*4.)*exp(-t*5.)*hitEnabled;
        vec3 color=mix(vec3(.16,.72,1.),vec3(.65,1.,.76),edge*.7+wave*.3);
        color=mix(color,vec3(1.,.62,.22),flash*.85);
        float alpha=(.035+edge*.44+grid*(.06+wave*.34)+wave*.48+echo*.18+flash*.6)*fade;
        gl_FragColor=vec4(color,alpha);
      }`
  }));
}
function createExternalConnection(event){
  const group=new THREE.Group();group.name='openshell-outbound';group.visible=false;scene.add(group);
  const shell=createProtectionShell();shell.scale.y=1.08;group.add(shell);
  shell.visible=event.source!=='OpenClaw tool activity'||event.protected;
  const screen=protectionTarget(event).getWorldPosition(new THREE.Vector3()).project(camera),direction=screen.x>0?-1:1;
  const origin=new THREE.Vector3(0,.95,.05),destination=new THREE.Vector3(direction*8.8,1.9,1);
  const curve=new THREE.QuadraticBezierCurve3(origin,new THREE.Vector3(direction*4,4.2,.8),destination);
  const route=new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(64)),new THREE.LineDashedMaterial({color:0x97ffd4,dashSize:.16,gapSize:.11,transparent:true,opacity:.85,depthWrite:false,toneMapped:false}));
  route.computeLineDistances();group.add(route);
  const globe=new THREE.Group();globe.position.copy(destination);globe.scale.setScalar(1.3);group.add(globe);
  const earth=new THREE.Group();globe.add(earth);
  earth.add(new THREE.Mesh(new THREE.SphereGeometry(.66,32,20),new THREE.MeshBasicMaterial({color:0x123a54,transparent:true,opacity:.94,depthWrite:false})));
  const spherePoint=(lon,lat,r=.675)=>{const a=lon*Math.PI/180,b=lat*Math.PI/180;return new THREE.Vector3(r*Math.cos(b)*Math.sin(a),r*Math.sin(b),r*Math.cos(b)*Math.cos(a));};
  function outline(points,color,opacity){const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color,transparent:true,opacity,depthWrite:false,toneMapped:false}));earth.add(line);}
  for(const latitude of [-60,-30,0,30,60])outline(Array.from({length:73},(_,i)=>spherePoint(i*5,latitude)),0x65b9db,.4);
  for(let longitude=0;longitude<180;longitude+=30)outline(Array.from({length:73},(_,i)=>{const a=i*Math.PI/36;return new THREE.Vector3(.675*Math.cos(a)*Math.sin(longitude*Math.PI/180),.675*Math.sin(a),.675*Math.cos(a)*Math.cos(longitude*Math.PI/180));}),0x65b9db,.4);
  // Lightweight geographic silhouettes, bundled geometry with no map downloads.
  const continents=[
    [[-168,66],[-135,70],[-110,73],[-60,52],[-82,25],[-97,16],[-117,32],[-130,53],[-168,66]],
    [[-80,10],[-51,3],[-35,-8],[-49,-28],[-69,-55],[-76,-20],[-80,10]],
    [[-17,35],[10,37],[34,29],[51,12],[42,-13],[20,-35],[10,-18],[-5,4],[-17,15],[-17,35]],
    [[-10,36],[-9,58],[27,71],[65,72],[110,74],[170,60],[141,39],[122,22],[106,1],[79,8],[65,25],[43,12],[35,40],[16,42],[-10,36]],
    [[113,-22],[130,-12],[145,-16],[153,-28],[137,-39],[115,-34],[113,-22]],
    [[-52,60],[-22,70],[-40,82],[-65,76],[-52,60]]
  ];
  for(const coast of continents)outline(coast.map(([lon,lat])=>spherePoint(lon,lat,.692)),0xb5ffbb,.95);
  earth.children.forEach(part=>part.userData.opacity=part.material.opacity);
  const halo=new THREE.Mesh(new THREE.SphereGeometry(.73,24,16),protectionMaterial(0x67dbff,.07));globe.add(halo);
  const packets=[];
  for(let i=0;i<2;i++){const packet=new THREE.Mesh(new THREE.SphereGeometry(.085,12,8),protectionMaterial(0xd4ffe7));packet.add(new THREE.Mesh(new THREE.SphereGeometry(.17,12,8),protectionMaterial(0x7dffc3,.2)));group.add(packet);packets.push(packet);}
  const arrow=new THREE.Mesh(new THREE.ConeGeometry(.12,.32,12),protectionMaterial(0xb4ffdb));arrow.position.copy(curve.getPoint(.72));arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),curve.getTangent(.72).normalize());group.add(arrow);
  const label=document.createElement('div');label.className='world-protection-hit world-protection-allow';label.setAttribute('role','status');
  const observed=event.source==='OpenClaw tool activity';
  const title=document.createElement('b');title.textContent=observed?'↗ Internet activity':'↗ Request allowed';
  const host=document.createElement('small');host.textContent=String(event.host||'').slice(0,120);
  const caption=document.createElement('span');caption.textContent=observed?(event.protected?'OpenShell agent · web tool':'Direct access · web tool'):'OpenShell · external website';label.append(title,host,caption);protectionLayer.append(label);
  return {event,group,shell,route,globe,earth,halo,curve,packets,arrow,label,began:performance.now(),phase:'outbound'};
}
function animateExternalConnection(hit,age,duration){
  const fade=motion?Math.min(1,age/.2,(duration-age)/.7):1;
  hit.phase=motion?'outbound':'allowed';hit.shell.material.uniforms.fade.value=.28*fade;
  hit.earth.rotation.y=motion?age*.55:-.35;hit.earth.rotation.z=.18;
  hit.earth.children.forEach(part=>part.material.opacity=part.userData.opacity*fade);
  hit.route.material.opacity=.85*fade;hit.arrow.material.opacity=fade;hit.halo.material.opacity=.07*fade;
  hit.packets.forEach((packet,i)=>{packet.visible=motion;packet.position.copy(hit.curve.getPoint(((age*.6+i*.5)%1)*.88));packet.material.opacity=fade;});
  hit.label.dataset.phase=hit.phase;hit.label.style.opacity=String(fade);
  hit.group.updateMatrixWorld(true);
  placeProtectionNotice(hit,hit.group.localToWorld(hit.globe.position.clone().add(new THREE.Vector3(0,1.35,0))));
}
function queueExternalConnection(event){
  const key=event.owner+':'+(event.role===null?'personal':event.role),target=protectionTarget(event);
  const cooldownKey=key+':allow';
  if(!target||performance.now()-(protectionCooldown.get(cooldownKey)||-Infinity)<4500)return;
  if(protectionHits.get(key)?.event.action==='deny')return;
  protectionCooldown.set(cooldownKey,performance.now());
  if(protectionHits.has(key)){disposeProtection(protectionHits.get(key));protectionHits.delete(key);}
  if(protectionHits.size>=3){const [oldKey,old]=protectionHits.entries().next().value;disposeProtection(old);protectionHits.delete(oldKey);}
  protectionHits.set(key,createExternalConnection(event));
}
function observeExternalActivity(jobs=[],owner){
  const resident=residents.find(r=>r.key===owner),protectedAgent=resident?.appearance?.protection==='openshell';
  const candidates=[];
  for(const job of jobs){
    if(!['chat','reminder'].includes(job.kind))continue;
    const activity=job.liveActivity||job.result?.activity;
    if(!activity?.available||!Array.isArray(activity.calls))continue;
    activity.calls.forEach((call,index)=>{
      if(!['web_fetch','web_search'].includes(call.tool)||!['running','completed'].includes(call.status))return;
      let host=call.tool==='web_search'?'Web search':String(call.target||'External website');
      if(call.tool==='web_fetch')try{host=new URL(host).hostname||host;}catch{}
      candidates.push({id:'web:'+job.id+':'+(call.id||index),host});
    });
  }
  if(!externalActivityPrimed.has(owner)){
    candidates.forEach(event=>externalActivitySeen.add(event.id));externalActivityPrimed.add(owner);return;
  }
  const key=owner+':personal';
  for(const event of candidates){
    if(externalActivitySeen.has(event.id))continue;
    externalActivitySeen.add(event.id);
    if(protectedAgent&&performance.now()-(nativeAllowSeen.get(key)||-Infinity)<30000)continue;
    queueExternalConnection({...event,owner,role:null,action:'allow',source:'OpenClaw tool activity',protected:protectedAgent});
  }
  while(externalActivitySeen.size>256)externalActivitySeen.delete(externalActivitySeen.values().next().value);
}
function observeProtection(events=[]){
  const now=Date.now()/1000;
  for(const event of events){
    if(!event.id||event.source!=='OpenShell policy log'||!['deny','allow'].includes(event.action)||protectionSeen.has(event.id))continue;
    protectionSeen.add(event.id);
    if(!protectionPrimed||now-event.observedAt>12||now-event.time>30||event.time>now+2)continue;
    const key=event.owner+':'+(event.role===null?'personal':event.role),target=protectionTarget(event);
    const cooldownKey=key+':'+event.action;
    if(!target||performance.now()-(protectionCooldown.get(cooldownKey)||-Infinity)<4500)continue;
    // Keep a denial visible when other concurrent destinations are allowed.
    if(event.action==='allow'&&protectionHits.get(key)?.event.action==='deny')continue;
    if(event.action==='allow')nativeAllowSeen.set(key,performance.now());
    else protectionCooldown.set(cooldownKey,performance.now());
    if(event.action==='allow'){queueExternalConnection(event);continue;}
    if(protectionHits.has(key)){disposeProtection(protectionHits.get(key));protectionHits.delete(key);}
    if(protectionHits.size>=3){const [oldKey,old]=protectionHits.entries().next().value;disposeProtection(old);protectionHits.delete(oldKey);}
    const group=new THREE.Group();group.name='openshell-impact';group.visible=false;scene.add(group);
    const shell=createProtectionShell();shell.scale.y=1.08;group.add(shell);
    const rim=new THREE.Mesh(new THREE.TorusGeometry(1.8,.035,8,80),protectionMaterial(0x7fe9ff,.85));rim.rotation.x=-Math.PI/2;rim.position.y=.045;group.add(rim);
    const impact=new THREE.Group();impact.visible=false;impact.position.set(1.35,1,.75);impact.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),new THREE.Vector3(1.35,1/(1.08*1.08),.75).normalize());group.add(impact);
    const wave=new THREE.Mesh(new THREE.RingGeometry(.23,.26,48),protectionMaterial(0xb6ffe3));impact.add(wave);
    const seal=new THREE.Group();impact.add(seal);
    // A small amber stop cross makes the collision legible even at a distance.
    for(const angle of [-Math.PI/4,Math.PI/4]){const bar=new THREE.Mesh(new THREE.BoxGeometry(.075,.48,.025),protectionMaterial(0xffb86b));bar.rotation.z=angle;seal.add(bar);}
    const points=[];
    for(let i=0;i<10;i++){
      const angle=i*Math.PI/5;let previous=new THREE.Vector3();
      for(let j=1;j<=5;j++){
        const radius=j*.16,a=angle+(j%2?.2:-.13),next=new THREE.Vector3(Math.cos(a)*radius,Math.sin(a)*radius,.025);
        points.push(previous,next);previous=next;
      }
    }
    const sparks=new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:0xc5faff,transparent:true,opacity:1,depthWrite:false,toneMapped:false,blending:THREE.AdditiveBlending}));impact.add(sparks);
    // The request originates INSIDE the boundary and never crosses it. On denial
    // the amber packet reverses back toward its agent, then dissolves.
    const request=new THREE.Group();request.visible=motion;group.add(request);
    const packet=new THREE.Mesh(new THREE.SphereGeometry(.1,12,8),protectionMaterial(0xffce83));request.add(packet);
    const glow=new THREE.Mesh(new THREE.SphereGeometry(.2,12,8),protectionMaterial(0xffb66b,.25));packet.add(glow);
    const trail=new THREE.Mesh(new THREE.CylinderGeometry(.018,.035,1,8),protectionMaterial(0xffb66b,.8));request.add(trail);
    const origin=new THREE.Vector3(0,.95,.05),destination=impact.position.clone();
    const label=document.createElement('div');label.className='world-protection-hit';label.setAttribute('role','status');
    const title=document.createElement('b');title.textContent='⛨ Request blocked';const host=document.createElement('small');host.textContent=String(event.host||'').slice(0,120);
    const caption=document.createElement('span');caption.textContent='OpenShell · connection stopped';label.append(title,host,caption);protectionLayer.append(label);
    protectionHits.set(key,{event,group,shell,rim,impact,wave,seal,sparks,request,packet,glow,trail,origin,destination,label,began:performance.now(),phase:'request'});
  }
  protectionPrimed=true;
  while(protectionSeen.size>256)protectionSeen.delete(protectionSeen.values().next().value);
  for(const [key,stamp] of protectionCooldown)if(performance.now()-stamp>30000)protectionCooldown.delete(key);
  for(const [key,stamp] of nativeAllowSeen)if(performance.now()-stamp>30000)nativeAllowSeen.delete(key);
}
function animateProtection(now){
  for(const [key,hit] of protectionHits){
    const age=(now-hit.began)/1000,target=protectionTarget(hit.event),duration=motion?(hit.event.action==='allow'?4.8:3.8):3;
    if(!target||age>duration){disposeProtection(hit);protectionHits.delete(key);continue;}
    const shown=protectionVisible(hit.event);
    hit.group.visible=shown;hit.label.hidden=!shown;
    if(!shown)continue;
    target.getWorldPosition(hit.group.position);hit.group.position.y+=.025;hit.group.rotation.y=azimuth;
    if(hit.event.action==='allow'){animateExternalConnection(hit,age,duration);continue;}
    const collision=.6,t=age-collision,fade=motion?Math.min(1,(duration-age)/.9):1;
    hit.phase=!motion?'blocked':t<0?'request':t<.85?'impact':'blocked';
    hit.shell.material.uniforms.elapsed.value=motion?t:10;hit.shell.material.uniforms.fade.value=fade;
    hit.rim.material.opacity=(.6+(t>=0?.35*Math.exp(-t*3):0))*fade;
    hit.impact.visible=!motion||t>=0;
    hit.wave.visible=motion;hit.sparks.visible=motion;
    hit.wave.scale.setScalar(.6+Math.max(0,t)*3.2);hit.wave.material.opacity=Math.max(0,1-t/1.05)*fade;
    // A single local impact, not repeated flashes across the screen.
    hit.sparks.scale.setScalar(.45+Math.min(1,Math.max(0,t))*1.1);
    hit.sparks.material.opacity=Math.max(0,1-t/.8)*(.72+.28*Math.sin(t*28));
    hit.sparks.rotation.z=Math.max(0,t)*.28;hit.seal.scale.setScalar(motion?.7+.3*Math.min(1,Math.max(0,t)*7):1);
    hit.seal.children.forEach(o=>o.material.opacity=fade);
    hit.request.visible=motion&&age<collision+.7;
    if(hit.request.visible){
      const progress=t<0?age/collision:Math.max(0,1-t/.66);
      hit.packet.position.lerpVectors(hit.origin,hit.destination,progress);
      const tailProgress=t<0?Math.max(0,progress-.27):Math.min(1,progress+.23);
      const tail=hit.origin.clone().lerp(hit.destination,tailProgress),delta=hit.packet.position.clone().sub(tail);
      hit.trail.position.copy(tail).add(hit.packet.position).multiplyScalar(.5);
      hit.trail.scale.y=Math.max(.001,delta.length());hit.trail.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),delta.normalize());
      hit.packet.material.opacity=t<0?1:Math.max(0,1-t/.7);hit.glow.material.opacity=.25*hit.packet.material.opacity;hit.trail.material.opacity=.8*hit.packet.material.opacity;
    }
    hit.label.dataset.phase=hit.phase;hit.label.style.opacity=String(motion?(t<0?.5:fade):1);
    placeProtectionNotice(hit,hit.group.position.clone().add(new THREE.Vector3(0,2.65,0)));
  }
}
