// SPDX-License-Identifier: Apache-2.0

// Idle personality vignettes and brief excerpts of actual completed replies.
// All timing runs on the scene clock: no requests, timers or background jobs.
const loungePersonalities={
  guide:{title:'Helper',speed:.70,rest:[2.8,5.2],intro:name=>`Hey, I'm ${name}. Happy to help.`,lines:[
    'Small steps. We’ll figure it out.',
    'I like making tricky things feel simple.',
    'New here? You’re in good company.',
    'Ask away. There’s no silly question.',
    'A little encouragement goes a long way.'
  ]},
  maker:{title:'Creator',speed:1.02,rest:[1.2,3.0],intro:name=>`I'm ${name}. What should we build?`,lines:[
    'I learn best by making things.',
    'What if we tried something a little different?',
    'Give me an idea. I’ll bring the curiosity.',
    'My favorite question? “What if?”',
    'Small experiments. Plenty of possibilities.'
  ]},
  analyst:{title:'Researcher',speed:.57,rest:[3.8,6.5],intro:name=>`I'm ${name}. Let’s look a little closer.`,lines:[
    'I like a good question — and clear evidence.',
    'Details are kind of my thing.',
    'First, understand. Then, decide.',
    'A fresh perspective can change the picture.',
    'Curious, careful, and always asking why.'
  ]}
};
// Short, authored greetings reflect voice; answer length governs actual task replies.
const loungeVoices={
  direct:{guide:['A clear goal. A useful next step.','Let’s make the plan actionable.'],maker:['Less talk. Let’s build a first version.','Start small. Try it. Improve it.'],analyst:['Show me the evidence.','Facts first. Conclusions second.']},
  playful:{guide:['Think of me as a GPS for tricky ideas.','One small step for you. One happy checklist for me.'],maker:['Ideas in, tiny inventions out.','My hobby? Giving “what if” a prototype.'],analyst:['I collect sources, not rumors.','A mystery? Let me get my imaginary magnifying glass.']},
  cynical:{guide:['Another meeting? Only if we leave with a plan.','“We’ll figure it out” could use a checklist.'],maker:['Another big idea? Let’s see if the tiny version works.','A slide deck? I’d rather build the thing.'],analyst:['Bold claim. Got a source?','Just guess? No thanks. Bring me evidence.']}
};
// Idle dialogue is authored flavor, never a claim that research or tool work occurred.
// Use the purpose only to pick a topic; never recite the user's instructions.
function purposeDialogue(r){
  const text=r.purpose.trim().toLowerCase();
  const domains=[
    [/weather|forecast|날씨|기상/,['weather','Bring a city. I’ll focus on its weather.','Weather first. Outdoor plans second.','The weather has opinions. So do umbrellas.','An outdoor picnic? Let’s at least check the forecast.']],
    [/document|pdf|slide|deck|summar|문서|요약|슬라이드/,['documents','Let’s find the key points.','Three points. Straight to the takeaway.','Big deck. Tiny summary.','More slides. Still looking for the point.']],
    [/travel|trip|food|여행|맛집/,['travel plans','Let’s shape a trip around what you enjoy.','Destination, dates, budget. Let’s start there.','My kind of adventure includes a snack stop.','A packed itinerary? Congratulations on inventing a commute.']],
    [/research|compare|조사|연구/,['research','Let’s take a closer look at your question.','Give me a question and the evidence to examine.','A good source is my kind of treasure.','Sounds convincing. That is not the same as being true.']],
    [/app|game|code|build|앱|게임|코딩|개발/,['building things','We can start with a small version of your idea.','Pick one feature. Let’s make it work.','Tiny prototype, big curiosity.','Another grand idea? Show me the smallest useful version.']],
    [/writ|content|invitation|campaign|글|작성|마케팅/,['writing','Let’s find the right words for your audience.','Audience, message, format. That’s my starting point.','Blank pages don’t scare me. Bland headlines do.','“Revolutionary”? Let’s write something people might believe.']]
  ];
  const match=domains.find(([pattern])=>pattern.test(text));
  const tone=['kind','direct','playful','cynical'].includes(r.tone)?r.tone:'kind';
  const voiceIndex={kind:1,direct:2,playful:3,cynical:4}[tone];
  const lines=match?[match[1][voiceIndex],{
    kind:`Happy to help with ${match[1][0]}.`,
    direct:`Let’s focus on ${match[1][0]}.`,
    playful:`A little ${match[1][0]}, a little curiosity.`,
    cynical:`${match[1][0][0].toUpperCase()+match[1][0].slice(1)}. Preferably without the busywork.`
  }[tone]]:(loungeVoices[tone]?.[r.persona]||loungePersonalities[r.persona].lines);
  return lines[r.line++%lines.length];
}
function compactLoungeLine(text,r){
  const line=String(text||'').replace(/\s+/g,' ').trim();
  if(line&&Array.from(line).length<=80)return line;
  return {kind:'Ready when you are.',direct:'What’s the next step?',playful:'What are we trying today?',cynical:'Ready. Let’s make it worth the effort.'}[r.tone]||'Ready when you are.';
}
function loungeLine(r){
  if(r.purpose)return purposeDialogue(r);
  const mood=loungePersonalities[r.persona],voice=loungeVoices[r.tone];
  if(!voice)return r.saidIntro?mood.lines[r.line++%mood.lines.length]:mood.intro(r.name);
  const lines=voice[r.persona],line=lines[r.line++%lines.length];
  return (r.saidIntro?'':`I'm ${r.name}. `)+line;
}
// An excerpt, not another model call: preserve the reply's wording and persona.
function loungeReplyExcerpt(answer){
 const text=String(answer||'').replace(/```[^\n]*\n/g,'').replace(/```/g,'')
  .replace(/!\[([^\]]*)\]\([^)]*\)/g,'$1').replace(/\[([^\]]+)\]\([^)]*\)/g,'$1')
  .replace(/<[^>]*>/g,'').replace(/^[ \t]*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)/gm,'')
  .replace(/[*_`~]/g,'').replace(/\s+/g,' ').trim();
 if(text.length<=240)return text;
 const excerpt=text.slice(0,237),sentences=[...excerpt.matchAll(/[.!?。！？](?=\s|$)/g)];
 const end=sentences.at(-1)?.index;
 return (end>=60?excerpt.slice(0,end+1):excerpt.replace(/\s+\S*$/,'')).trim()+'…';
}
const loungeBounds={left:-7.1,right:7.1,back:-2.7,front:4.4};
const loungeLayoutKey='bac-lounge-layout-v1';
let loungeLayout={};try{const saved=JSON.parse(localStorage.getItem(loungeLayoutKey)||'{}');if(saved&&typeof saved==='object')loungeLayout=saved;}catch{}
function savedLoungePosition(key){const p=loungeLayout[key];return Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)?[THREE.MathUtils.clamp(p[0],loungeBounds.left,loungeBounds.right),THREE.MathUtils.clamp(p[1],loungeBounds.back,loungeBounds.front)]:null;}
function loungePointerPoint(e){
 const rect=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
 const hit=raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0,1,0),-.015),new THREE.Vector3());return hit?loungeRoom.worldToLocal(hit):null;
}
function beginResidentDrag(e,key){
 if(e.button!==0||room!=='lounge'||overview||journey||arrival||drag)return false;
 const r=residents.find(r=>r.key===key),point=loungePointerPoint(e);if(!r||!point||r.atOpenTask||r.atRoundtable)return false;
 endLoungeSpeech();r.target=null;
 drag={resident:r,x:e.clientX,y:e.clientY,start:r.group.position.clone(),offset:r.group.position.clone().sub(point),pointerId:e.pointerId};moved=false;
 r.dragging=true;e.currentTarget.setPointerCapture(e.pointerId);e.preventDefault();return true;
}
function moveResidentDrag(e){
 if(!drag?.resident||drag.pointerId!==e.pointerId)return false;
 if(Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>5)moved=true;
 if(!moved)return true;
 const p=loungePointerPoint(e);if(!p)return true;p.add(drag.offset);p.x=THREE.MathUtils.clamp(p.x,loungeBounds.left,loungeBounds.right);p.z=THREE.MathUtils.clamp(p.z,loungeBounds.back,loungeBounds.front);
 if(!residents.some(r=>r!==drag.resident&&Math.hypot(r.group.position.x-p.x,r.group.position.z-p.z)<1.4))drag.resident.group.position.set(p.x,.015,p.z);
 return true;
}
function endResidentDrag(cancel=false){
 if(!drag?.resident)return false;
 const r=drag.resident;r.dragging=false;
 if(cancel)r.group.position.copy(drag.start);
 else if(moved){r.placed=true;loungeLayout[r.key]=[r.group.position.x,r.group.position.z];try{localStorage.setItem(loungeLayoutKey,JSON.stringify(loungeLayout));}catch{}r.suppressClickUntil=performance.now()+400;}
 // Selecting and placing a resident are compatible. Small pointer movement
 // during a name-tag click must not silently discard the workspace selection.
 drag=null;
 if(!cancel)root.dispatchEvent(new CustomEvent('bac:collection-select',{detail:r.key}));
 return true;
}
const loungeIdleInterval=30;
let loungeTime=0,loungeSpeaker=null,lastLoungeSpeaker='',nextLoungeSpeech=.9,nextLoungeIdle=loungeIdleInterval;
const welcomeSpeakers=[];
function queueWelcome(key){
  endLoungeSpeech();
  if(!welcomeSpeakers.includes(key))welcomeSpeakers.push(key);
  nextLoungeSpeech=loungeTime;
}
function welcomeLine(r){
  return `Hi, I’m ${r.name}.`;
}
function residentRandom(r){r.seed=(Math.imul(r.seed,1664525)+1013904223)>>>0;return r.seed/4294967296;}
function residentSeed(key){let seed=2166136261;for(const c of key)seed=Math.imul(seed^c.charCodeAt(0),16777619)>>>0;return seed;}
function loungeSpawn(){
  const spots=[[0,1.4],[-4.4,1.4],[4.4,1.4],[-2.2,-1.7],[2.2,-1.7],[-6.3,-1.7],[6.3,-1.7],[-6,4.1],[-2,4.1],[2,4.1],[6,4.1],[0,-.3]];
  const distance=([x,z])=>Math.min(...residents.map(r=>Math.hypot(r.group.position.x-x,r.group.position.z-z)));
  if(!residents.length)return spots[0];
  let best=spots.reduce((best,p)=>distance(p)>distance(best)?p:best,spots[0]);
  if(distance(best)<1.4)for(let x=-6.4;x<=6.4;x+=1.6)for(let z=-2.4;z<=4;z+=1.6)if(distance([x,z])>distance(best))best=[x,z];
  return best;
}
function endLoungeSpeech(){
  if(!loungeSpeaker)return;
  const r=loungeSpeaker;r.speechText='';r.node.dataset.speaking='false';r.node.querySelector('.world-resident-speech').hidden=true;
  r.completionSpeech=false;r.node.removeAttribute('aria-describedby');r.node.removeAttribute('title');r.activity=r.pending?'assigned':'resting';r.waitUntil=loungeTime+1.1+residentRandom(r);loungeSpeaker=null;nextLoungeSpeech=loungeTime+2.7;
}
function setCollection(agents,key){
  // The collection panel retains cleanup status and retry actions; the scene shows active hires.
  collection=(agents||[]).filter(agent=>!agent.deleting);selectedResident=key;residentLayer.dataset.dense=collection.length>6;
  // Reconcile by identity so polling, edits and new arrivals never teleport the crew.
  for(let i=residents.length-1;i>=0;i--){
    const r=residents[i];if(collection.some(a=>a.key===r.key))continue;
    if(loungeSpeaker===r)endLoungeSpeech();
    if(drag?.resident===r)endResidentDrag(true);
    if(arrival?.key===r.key)finishArrival();
    residentPods.remove(r.mount);clearGeometry(r.mount);r.node.remove();residents.splice(i,1);
  }
  collection.forEach((a,index)=>{
    const avatar={...avatarDefaults[index%5],...a.avatar,protection:a.protection||'standard'};let r=residents.find(r=>r.key===a.key);
    if(!r){
      const [x,z]=savedLoungePosition(a.key)||loungeSpawn(),rig=createCharacter(avatar),mount=new THREE.Group();rig.group.scale.setScalar(1.3);rig.group.position.set(x,.015,z);mount.add(rig.group);residentPods.add(mount);
      const halo=ring(mount,x,.045,z,.65,rig.color);
      const node=document.createElement('button');node.type='button';node.className='world-resident';node.dataset.resident=a.key;node.dataset.speaking='false';node.innerHTML='<b></b><small></small><span class="world-resident-speech" hidden></span>';residentLayer.append(node);
      const speech=node.querySelector('.world-resident-speech');speech.id='lounge-speech-'+a.key;
      r={...rig,placed:!!savedLoungePosition(a.key),key:a.key,mount,node,halo,seed:residentSeed(a.key),target:null,waitUntil:loungeTime+.25+index*.4,activity:'resting',hovered:false,focused:false,saidIntro:false,line:0,speechText:'',blockedFor:0};residents.push(r);
      node.onclick=e=>{if(e.detail>0&&performance.now()<(r.suppressClickUntil||0)){e.preventDefault();return;}root.dispatchEvent(new CustomEvent('bac:collection-select',{detail:r.key}));};
      node.style.touchAction='none';node.style.cursor='grab';
      node.onpointerdown=e=>beginResidentDrag(e,r.key);node.onpointermove=moveResidentDrag;
      node.onpointerup=()=>{if(drag?.resident===r){endResidentDrag();r.suppressClickUntil=performance.now()+400;}};node.onpointercancel=()=>endResidentDrag(true);
      node.onpointerenter=()=>r.hovered=true;node.onpointerleave=()=>r.hovered=false;
      node.onfocus=()=>r.focused=true;node.onblur=()=>r.focused=false;
    }else if(['body','color','accessory','protection'].some(field=>r.appearance[field]!==avatar[field])){
      const old=r.group,rig=createCharacter(avatar);rig.group.scale.setScalar(1.3);rig.group.position.copy(old.position);rig.group.rotation.copy(old.rotation);
      r.mount.remove(old);clearGeometry(old);r.mount.add(rig.group);Object.assign(r,rig);r.halo.material=mat(rig.color,true);
    }
    const tone=loungeVoices[a.tone]?a.tone:'kind';
    if(r.persona!==a.persona||r.name!==a.name||r.tone!==tone||r.purpose!==(a.purpose||'')){if(loungeSpeaker===r)endLoungeSpeech();r.saidIntro=false;r.line=0;}
    r.heartbeat=!!a.techRadar||(a.skills||[]).includes('radar');
    const latest=a.latestMission,signature=latest?latest.id+':'+latest.status:'',replyHeld=!!protectionReplyDelay(a.key,null);
    r.replyExcerpt=!replyHeld&&latest?.status==='done'?loungeReplyExcerpt(latest.answerPreview):'';
    if(r.missionSignature!==undefined&&signature!==r.missionSignature&&r.replyExcerpt){
      // A fresh answer takes precedence over an unrelated idle vignette.
      if(loungeSpeaker&&!loungeSpeaker.completionSpeech)endLoungeSpeech();
      else if(loungeSpeaker===r)endLoungeSpeech();
      r.completionCue=true;nextLoungeSpeech=loungeTime;
    }
    if(!replyHeld)r.missionSignature=signature;
    // Shared-event reservations protect identity; only unfinished activity makes the resident busy.
    const occupied='activity' in a?!!a.activity:['queued','running','waiting','stopping'].includes(latest?.status);
    if(occupied)r.completionCue=false;
    r.name=a.name;r.purpose=a.purpose||'';r.persona=loungePersonalities[a.persona]?a.persona:'guide';r.tone=tone;r.verbosity=a.verbosity||'balanced';r.pending=occupied;
    if(loungeSpeaker===r&&r.pending)endLoungeSpeech();
    if(r.pending)r.activity='assigned';
    else if(r.activity==='assigned')r.activity='resting';
    r.node.setAttribute('aria-label','Open '+a.name+'’s workspace');r.node.setAttribute('aria-pressed',r.key===key);r.node.style.setProperty('--resident-color','#'+r.color.toString(16).padStart(6,'0'));r.node.querySelector('b').textContent=a.name;
    r.node.dataset.status=r.pending?'busy':'ready';
    r.node.querySelector('small').textContent=r.pending?'Busy':'Ready';
    r.halo.visible=r.key===key||r.pending||loungeSpeaker===r;
  });
  residentMeshes.length=0;residents.forEach(r=>r.group.traverse(o=>{if(o.isMesh){o.userData.resident=r.key;residentMeshes.push(o);}}));
  if(!residents.length){lastLoungeSpeaker='';nextLoungeSpeech=loungeTime+.9;nextLoungeIdle=loungeTime+loungeIdleInterval;}
  syncVisitorCollection();
}
function chooseLoungeTarget(r){
  const p=r.group.position;
  for(let attempt=0;attempt<24;attempt++){
    const angle=residentRandom(r)*Math.PI*2,length=2.2+residentRandom(r)*3.6;
    const x=THREE.MathUtils.clamp(p.x+Math.sin(angle)*length,loungeBounds.left,loungeBounds.right),z=THREE.MathUtils.clamp(p.z+Math.cos(angle)*length,loungeBounds.back,loungeBounds.front);
    if(Math.hypot(x-p.x,z-p.z)<1.6||residents.some(o=>o!==r&&Math.hypot(o.group.position.x-x,o.group.position.z-z)<1.7))continue;
    r.target=new THREE.Vector3(x,p.y,z);r.blockedFor=0;return;
  }
  r.waitUntil=loungeTime+.7;
}
function turnResident(r,angle,dt){const delta=Math.atan2(Math.sin(angle-r.group.rotation.y),Math.cos(angle-r.group.rotation.y));r.group.rotation.y+=delta*Math.min(1,dt*5);}
function moveResident(r,dt){
  const mood=loungePersonalities[r.persona],p=r.group.position;
  r.activity=r.pending?'assigned':loungeSpeaker===r?'speaking':'resting';
  if(r.placed||r.dragging||r.pending||r.hovered||r.focused||loungeSpeaker===r)return false;
  if(!r.target&&loungeTime>=r.waitUntil)chooseLoungeTarget(r);
  if(!r.target)return false;
  const delta=r.target.clone().sub(p),distance=delta.length();
  if(distance<.18){r.target=null;r.waitUntil=loungeTime+mood.rest[0]+residentRandom(r)*(mood.rest[1]-mood.rest[0]);return false;}
  const steering=delta.normalize();
  // Yield before bodies overlap. Repulsion opposing the goal used to flip the
  // normalized heading each frame when two residents met.
  const next=p.clone().addScaledVector(steering,Math.min(distance,dt*mood.speed));
  next.x=THREE.MathUtils.clamp(next.x,loungeBounds.left,loungeBounds.right);next.z=THREE.MathUtils.clamp(next.z,loungeBounds.back,loungeBounds.front);
  const approachingNeighbor=residents.some(o=>{
    if(o===r)return false;
    const gap=p.distanceTo(o.group.position),nextGap=next.distanceTo(o.group.position);
    return nextGap<1.85&&nextGap<gap-.00001;
  });
  if(approachingNeighbor||next.distanceTo(p)<.001){
    r.blockedFor+=dt;r.holdHeadingUntil=loungeTime+1.5;
    if(r.blockedFor>.75){r.target=null;r.waitUntil=loungeTime+1+residentRandom(r)*1.2;}
    return false;
  }
  r.blockedFor=0;p.copy(next);turnResident(r,Math.atan2(steering.x,steering.z),dt);r.activity='walking';return true;
}
function startLoungeSpeech(){
  if(loungeSpeaker||loungeTime<nextLoungeSpeech||overview||journey||arrival||room!=='lounge'||drag)return;
  while(welcomeSpeakers.length&&!residents.some(r=>r.key===welcomeSpeakers[0]&&!r.pending&&!r.atOpenTask&&!r.atRoundtable))welcomeSpeakers.shift();
  const newcomer=residents.find(r=>r.key===welcomeSpeakers[0]);
  if(!motion&&!newcomer&&!residents.some(r=>r.completionCue))return;
  const eligible=residents.filter(r=>!r.atRoundtable&&!r.atOpenTask&&!r.pending&&(r.completionCue||(!r.hovered&&!r.focused)));if(!eligible.length&&!newcomer)return;
  const start=(residents.findIndex(r=>r.key===lastLoungeSpeaker)+1)%Math.max(1,residents.length);
  const ordered=[...residents.slice(start),...residents.slice(0,start)].filter(r=>eligible.includes(r));
  // Greetings and actual replies are immediate. Ambient chatter has one shared
  // 30-second cadence, regardless of roster size or previous conversations.
  let r=newcomer||ordered.find(r=>r.completionCue);
  if(!r){
    if(!motion||loungeTime<nextLoungeIdle)return;
    // Paused heartbeat agents also stay out of ambient chatter.
    const idle=eligible.filter(r=>!r.heartbeat);if(!idle.length)return;
    const others=idle.filter(r=>r.key!==lastLoungeSpeaker),candidates=others.length?others:idle;
    r=candidates[Math.floor(Math.random()*candidates.length)];
  }
  if(newcomer)welcomeSpeakers.shift();
  r.completionSpeech=!newcomer&&!!r.completionCue;if(!newcomer)r.completionCue=false;
  r.speechText=r.completionSpeech?r.replyExcerpt:compactLoungeLine(newcomer?welcomeLine(r):loungeLine(r),r);r.saidIntro=true;
  r.node.dataset.speechKind=r.completionSpeech?'reply':'idle';
  const speech=r.node.querySelector('.world-resident-speech');speech.textContent=r.speechText;speech.hidden=false;r.node.dataset.speaking='true';r.node.setAttribute('aria-describedby',speech.id);
  r.node.title=r.completionSpeech?'From the latest reply · open the full conversation':'Personality vignette · select to open this agent’s workspace';r.speechUntil=loungeTime+(r.completionSpeech?Math.min(14,Math.max(6,r.speechText.length/20)):5.8);r.target=null;
  loungeSpeaker=r;lastLoungeSpeaker=r.key;
  nextLoungeIdle=loungeTime+loungeIdleInterval;
  // Measure at the cue itself; observer notifications can lag room/fullscreen changes.
  const view=viewport.getBoundingClientRect();
  if(view.width&&view.height&&view.right>0&&view.left<innerWidth&&view.bottom>0&&view.top<innerHeight)studioSound.speak(r.persona,r.group.position.x/24);
}
function placeResident(r){
  positionLabel(r.node,loungeRoom.localToWorld(r.group.position.clone().add(new THREE.Vector3(0,2.2,0))));
  const x=parseFloat(r.node.style.left),y=parseFloat(r.node.style.top),half=r.node.offsetWidth/2,w=viewport.clientWidth,h=viewport.clientHeight;
  r.node.style.left=THREE.MathUtils.clamp(x,half+12,w-half-12)+'px';
  if(loungeSpeaker===r){
    // Leave navigation and the map unobstructed; the bubble replaces its own name tag.
    const compact=innerWidth<=560;
    const top=Math.min(h-(compact?80:104),Math.max((compact?154:114)+r.node.offsetHeight,y));r.node.style.top=top+'px';
    r.node.style.setProperty('--speech-tail',THREE.MathUtils.clamp(x-parseFloat(r.node.style.left)+half,18,r.node.offsetWidth-18)+'px');
  }
}
function animateLounge(dt){
  {
    loungeTime+=dt;
    if(loungeSpeaker&&loungeTime>=loungeSpeaker.speechUntil&&!loungeSpeaker.hovered&&!loungeSpeaker.focused)endLoungeSpeech();
    startLoungeSpeech();
  }
  residents.forEach((r,index)=>{
    if(r.atRoundtable||r.atOpenTask){r.mount.visible=false;r.node.hidden=true;return;}
    if(arrival?.key===r.key){r.mount.visible=false;r.node.hidden=true;return;}
    if(motion){
      const walking=moveResident(r,dt),speaking=loungeSpeaker===r,beat=loungeTime*(walking?8:1.7)+index;
      if(speaking)turnResident(r,azimuth,dt);
      else if(!walking&&!r.target&&loungeTime>=(r.holdHeadingUntil||0)&&!r.hovered&&!r.focused)turnResident(r,Math.sin(loungeTime*.4+index)*.35,dt);
      r.body.position.y=walking?Math.abs(Math.sin(beat))*.035:Math.sin(beat)*.018;
      r.legs.forEach((leg,j)=>leg.rotation.x=walking?Math.sin(beat+j*Math.PI)*.32:0);
      r.arms.forEach((arm,j)=>{arm.rotation.x=Math.sin(beat+j*Math.PI)*(walking?.27:.065);arm.rotation.z=speaking&&j===0?(r.persona==='guide'?-1.9+Math.sin(loungeTime*5)*.16:r.persona==='maker'?-1.15+Math.sin(loungeTime*4)*.2:-.48):0;});
    }
    r.halo.position.set(r.group.position.x,.045,r.group.position.z);r.halo.visible=r.key===selectedResident||r.pending||loungeSpeaker===r;
    placeResident(r);
  });
}
