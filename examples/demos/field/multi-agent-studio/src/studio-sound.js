// SPDX-License-Identifier: Apache-2.0

// Small, locally synthesized earcons. No audio downloads, speech or model calls.
function createStudioSound(){
  const AudioEngine=window.AudioContext||window.webkitAudioContext;
  const storageKey='bac-studio-sound-v1';
  let enabled=false,volume=25,context=null,master=null,activating=null,lastAt=-Infinity,lastPriority=0,owner=null,view=null,baseline=true;
  let knownJobs=new Map();const voices=new Set(),history=[];
  try{const saved=JSON.parse(localStorage.getItem(storageKey)||'null');if(saved){enabled=saved.enabled===true;volume=Number.isFinite(saved.volume)?Math.max(0,Math.min(100,saved.volume)):25;}}catch{}
  const controls=document.createElement('div');controls.className='studio-sound';
  controls.innerHTML='<button type="button" id="campus-sound-toggle" aria-pressed="false"></button>';
  const footer=root.querySelector('.campus-scene-bottom .row'),layout=root.querySelector('.campus-layout');
  footer.prepend(controls);
  const toggle=el('sound-toggle');
  function save(){try{localStorage.setItem(storageKey,JSON.stringify({enabled,volume}));}catch{}}
  function render(){
    const ready=enabled&&context?.state==='running';
    toggle.textContent=ready?'♫':'♪';
    toggle.setAttribute('aria-pressed',String(ready));toggle.setAttribute('aria-label',ready?'Turn sound off':'Turn sound on');
    toggle.title=!AudioEngine?'This browser does not support interface sounds':ready?'Mute greetings and mission sounds':'Enable quiet greetings and mission sounds';toggle.disabled=!AudioEngine;
  }
  function stop(){
    for(const voice of voices){try{voice.osc.stop();}catch{}voice.gain.disconnect();voice.pan?.disconnect();}voices.clear();
  }
  function currentView(){return root.dataset.room||'workshop';}
  function visible(){return !document.hidden&&!root.hidden;}
  function setVolume(){
    if(master&&context){master.gain.cancelScheduledValues(context.currentTime);master.gain.setTargetAtTime(volume/100*.45,context.currentTime,.025);}
  }
  async function activate(){
    if(!AudioEngine||!enabled)return false;if(activating)return activating;
    activating=(async()=>{
      try{
        if(!context){context=new AudioEngine();master=context.createGain();master.gain.value=volume/100*.45;master.connect(context.destination);context.onstatechange=render;}
        if(context.state==='suspended')await context.resume();
        if(!enabled||!visible())return false;
        return context.state==='running';
      }catch{return false;}
    })();
    try{return await activating;}finally{activating=null;render();}
  }
  // frequency, offset, duration, ending frequency. Sine envelopes avoid sharp clicks.
  const motifs={
    enable:[[660,0,.13,720]],
    guide:[[660,0,.10,760],[880,.09,.12,820]],
    maker:[[740,0,.08,920],[1040,.075,.10,980]],
    analyst:[[580,0,.12,610],[720,.13,.13,700]],
    start:[[392,0,.12,440],[587,.10,.16,587]],
    handoff:[[523,0,.10,554],[784,.095,.15,784]],
    complete:[[523,0,.16,523],[659,.11,.18,659],[784,.23,.25,784]],
    attention:[[622,0,.16,622],[622,.24,.19,622]],
    error:[[392,0,.14,392],[330,.15,.22,330]],
    stopped:[[440,0,.14,440],[392,.14,.16,392]]
  };
  const priorities={enable:0,guide:1,maker:1,analyst:1,start:2,handoff:2,stopped:3,complete:4,attention:5,error:6};
  function cue(kind,pan=0){
    if(!motifs[kind]||!enabled||!volume||!visible()||context?.state!=='running'||window.speechSynthesis?.speaking)return false;
    const now=performance.now(),priority=priorities[kind];
    if(now-lastAt<650&&priority<=lastPriority)return false;
    stop();lastAt=now;lastPriority=priority;
    const start=context.currentTime+.008;
    for(const [hz,offset,duration,end] of motifs[kind]){
      const osc=context.createOscillator(),gain=context.createGain(),panner=context.createStereoPanner?.();
      osc.type='sine';osc.frequency.setValueAtTime(hz,start+offset);osc.frequency.exponentialRampToValueAtTime(end,start+offset+duration);
      gain.gain.setValueAtTime(.0001,start+offset);gain.gain.linearRampToValueAtTime(priority===1?.18:.28,start+offset+.012);gain.gain.exponentialRampToValueAtTime(.0001,start+offset+duration);
      osc.connect(gain);if(panner){panner.pan.value=Math.max(-.3,Math.min(.3,pan));gain.connect(panner);panner.connect(master);}else gain.connect(master);
      const voice={osc,gain,pan:panner};voices.add(voice);osc.onended=()=>{osc.disconnect();gain.disconnect();panner?.disconnect();voices.delete(voice);};
      osc.start(start+offset);osc.stop(start+offset+duration+.015);
    }
    history.push({kind,at:now});if(history.length>32)history.shift();return true;
  }
  toggle.onclick=async()=>{
    if(enabled&&context?.state==='running'){enabled=false;stop();save();render();return;}
    enabled=true;save();if(await activate()){lastAt=-Infinity;cue('enable');}render();
  };
  // A saved preference resumes only on a real gesture; missed cues are never queued.
  function unlock(e){if(e.isTrusted&&enabled&&!controls.contains(e.target)&&context?.state!=='running')void activate();}
  root.addEventListener('pointerdown',unlock);root.addEventListener('keydown',unlock);
  document.addEventListener('visibilitychange',()=>{baseline=true;if(document.hidden)stop();});
  app.addEventListener('bac:mode',()=>{baseline=true;stop();});
  function syncControls(){
    const destination=footer;
    if(controls.parentElement!==destination){if(destination===footer)footer.insertBefore(controls,footer.querySelector('#campus-motion'));else destination.append(controls);}
  }
  let lastRootView=root.hidden+'|'+currentView(),lastLayoutHidden=layout.hidden;
  new MutationObserver(()=>{const next=root.hidden+'|'+currentView();if(next!==lastRootView){lastRootView=next;stop();syncControls();}}).observe(root,{attributes:true,attributeFilter:['hidden','data-room']});
  new MutationObserver(()=>{if(layout.hidden!==lastLayoutHidden){lastLayoutHidden=layout.hidden;stop();syncControls();}}).observe(layout,{attributes:true,attributeFilter:['hidden']});
  window.addEventListener('pagehide',stop);
  function observeJobs(nextOwner,jobs){
    const room=currentView(),seed=baseline||owner!==nextOwner||view!==room;
    owner=nextOwner;view=room;baseline=false;
    const next=new Map(),events=[];
    for(const job of jobs||[]){
      const state={status:job.status,stage:Number(job.payload?.stage)||0,kind:job.kind};next.set(job.id,state);
      if(seed)continue;const previous=knownJobs.get(job.id);
      if(previous?.status===state.status&&previous?.stage===state.stage)continue;
      if(state.status==='done'&&previous?.status!=='done')events.push('complete');
      else if(state.status==='error'&&previous?.status!=='error')events.push('error');
      else if(state.status==='waiting'&&previous?.status!=='waiting')events.push('attention');
      else if(['cancelled','stopped'].includes(state.status)&&previous&&previous.status!==state.status)events.push('stopped');
      else if(state.status==='running'){
        if(state.kind==='crew'&&previous?.status==='running'&&state.stage>previous.stage)events.push('handoff');
        else if(previous?.status!=='running')events.push('start');
      }
    }
    knownJobs=next;
    if(room!=='mission'||!visible())return;
    const mostImportant=events.sort((a,b)=>priorities[b]-priorities[a])[0];if(mostImportant)cue(mostImportant);
  }
  render();
  return {speak:(persona,pan)=>currentView()==='lounge'&&cue(['guide','maker','analyst'].includes(persona)?persona:'guide',pan),observeJobs,stop,inspect:()=>({enabled,volume,ready:context?.state==='running',state:context?.state||'locked',activeVoices:voices.size,history:history.map(item=>({...item}))})};
}
const studioSound=createStudioSound();window.BacSound=studioSound;
