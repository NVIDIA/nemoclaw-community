// SPDX-License-Identifier: Apache-2.0

  // Included in Studio's closure. Keep dialogs inside the fullscreen root.
  const worldViewport=document.getElementById('campus-viewport');
  const worldButton=document.createElement('button');
  worldButton.id='studio-focus';worldButton.type='button';
  worldButton.textContent='Fullscreen';worldButton.title='Fullscreen · Enter after selecting the 3D view';
  worldButton.setAttribute('aria-controls','campus-viewport');worldButton.setAttribute('aria-expanded','false');
  document.querySelector('.campus-scene-bottom .row').prepend(worldButton);
  worldViewport.tabIndex=0;worldViewport.setAttribute('role','region');
  worldViewport.setAttribute('aria-keyshortcuts','Enter');
  worldViewport.setAttribute('aria-label','Interactive 3D studio. Click then press Enter for fullscreen, or double-click an empty area. Drag to orbit and scroll to zoom. Escape returns to the studio.');
  let worldOpen=false,worldEpoch=0,worldPreviousFocus=null,worldScroll=[0,0],worldOverflow='',worldInert=[];
  const resources=document.getElementById('studio-resources');
  if(resources){
    document.addEventListener('pointerdown',e=>{if(!resources.contains(e.target))resources.open=false;});
    resources.addEventListener('focusout',e=>{if(!resources.contains(e.relatedTarget))resources.open=false;});
    resources.addEventListener('click',e=>{if(e.target.closest('a'))resources.open=false;});
    document.getElementById('studio-about').onclick=()=>{
      resources.open=false;
      resources.querySelector('summary').focus({preventScroll:true});
      const diagnosticsAvailable=!settingsButton.hidden;
      dialog('About Multi-Agent Studio',`<div class="studio-about-panel">
        <p class="studio-about-description">Multi-Agent Studio lets you hire personal AI agents, equip them with skills and OpenShell protection, and coordinate specialist teams to complete tasks.</p>
        <div class="studio-about-version"><span>Current version</span><strong>v${escape(buildInfo.version)}</strong></div>
        <section class="studio-about-release" aria-labelledby="studio-about-release-title"><h3 id="studio-about-release-title">Release notes</h3><div class="chat-prose">${messageMarkup(releaseNotes.replace(/^# Release notes\s*/i,''))}</div></section>
        ${diagnosticsAvailable?issueReportPanel():''}
      </div>`);
      if(diagnosticsAvailable)bindDiagnosticActions();
    };
    document.addEventListener('keydown',e=>{
      if(e.key==='Escape'&&resources.open){e.preventDefault();e.stopPropagation();resources.open=false;resources.querySelector('summary').focus();}
    },true);
  }

  function restoreWorld(){
    if(!worldOpen)return;
    worldOpen=false;++worldEpoch;
    document.querySelector('.studio-header-actions').append(settingsButton);
    root.classList.remove('studio-world-open');layout.classList.remove('world-expanded');
    worldButton.textContent='Fullscreen';worldButton.setAttribute('aria-expanded','false');
    document.body.style.overflow=worldOverflow;
    worldInert.forEach(([node,value])=>node.inert=value);worldInert=[];
    if(worldPreviousFocus?.isConnected)worldPreviousFocus.focus({preventScroll:true});
    window.scrollTo(...worldScroll);
  }
  async function leaveWorld(){
    restoreWorld();
    if(document.fullscreenElement===root){try{await document.exitFullscreen();}catch{}}
  }
  async function enterWorld(){
    if(worldOpen||el('dialog').open)return;
    worldOpen=true;const epoch=++worldEpoch;
    if(resources)resources.open=false;
    root.querySelector('.campus-scene-bottom .row').append(settingsButton);
    worldPreviousFocus=document.activeElement;worldScroll=[window.scrollX,window.scrollY];worldOverflow=document.body.style.overflow;
    // The window-filling fallback has the same keyboard boundary as native fullscreen.
    for(let node=root;node.parentElement&&node!==document.body;node=node.parentElement){
      for(const sibling of node.parentElement.children){if(sibling!==node){worldInert.push([sibling,sibling.inert]);sibling.inert=true;}}
    }
    root.classList.add('studio-world-open');layout.classList.add('world-expanded');document.body.style.overflow='hidden';
    worldButton.textContent='Exit fullscreen · Esc';worldButton.setAttribute('aria-expanded','true');
    worldViewport.focus({preventScroll:true});
    if(root.requestFullscreen&&!document.fullscreenElement){
      try{
        await root.requestFullscreen({navigationUI:'hide'});
        // An exit or view change can arrive while the browser is entering fullscreen.
        if(epoch!==worldEpoch&&document.fullscreenElement===root)await document.exitFullscreen();
      }catch{/* Keep the full-window experience when fullscreen is unavailable. */}
    }
  }
  worldButton.onclick=()=>worldOpen?leaveWorld():enterWorld();
  worldViewport.addEventListener('pointerdown',e=>{if(e.target.tagName==='CANVAS'||e.target===worldViewport)worldViewport.focus({preventScroll:true});});
  worldViewport.addEventListener('dblclick',e=>{
    if(el('dialog').open||e.target.closest('button'))return;
    e.preventDefault();if(!worldOpen)enterWorld();
  });
  worldViewport.addEventListener('keydown',e=>{
    if(e.target===worldViewport&&e.key==='Enter'&&!e.repeat){e.preventDefault();worldOpen?leaveWorld():enterWorld();}
  });
  document.addEventListener('keydown',e=>{
    if(!worldOpen||!e.shiftKey||e.ctrlKey||e.altKey||e.metaKey||e.repeat||e.isComposing||e.defaultPrevented||root.querySelector('dialog[open]'))return;
    if(e.composedPath().some(node=>node instanceof Element&&(node.matches('input,textarea,select,[role="textbox"]')||node.isContentEditable)))return;
    const selector={Digit1:'[data-world-room="workshop"]',Digit2:'[data-world-room="lounge"]',Digit3:'[data-world-scenario="plan"]'}[e.code];
    const button=selector&&root.querySelector('.world-room-map '+selector);
    if(!button||button.disabled)return;
    e.preventDefault();button.click();worldViewport.focus({preventScroll:true});
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&worldOpen&&!root.querySelector('dialog[open]')){e.preventDefault();leaveWorld();}});
  document.addEventListener('fullscreenchange',()=>{if(document.fullscreenElement!==root)restoreWorld();});
