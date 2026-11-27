// SPDX-License-Identifier: Apache-2.0

// Fan out through the existing per-agent queue: identities and policies remain separate.
const comparePanel=document.createElement('section');comparePanel.id='studio-compare';comparePanel.className='studio-compare';comparePanel.hidden=true;surfaceStore.append(comparePanel);
function drawComparison(){
  comparePanel.hidden=room!=='lounge'||!comparison;if(!comparison)return;
  if(comparePanel.dataset.batch!==comparison.id){
    comparePanel.dataset.batch=comparison.id;
    comparePanel.innerHTML=`<div class="studio-section-heading"></div><p class="studio-compare-prompt"></p><small>Each agent uses its selected model. Attachments stay with their original agent.</small><div class="studio-compare-grid"></div>`;
    comparePanel.querySelector('.studio-compare-prompt').textContent=comparison.prompt;
    comparePanel.querySelector('.studio-compare-grid').innerHTML=comparison.rows.map((r,i)=>`<article data-compare-row="${i}"><div class="studio-companion-name">${avatarBadge(r.avatar)}<div><h3>${escape(r.name)}</h3><small>${escape(r.purpose||'Personal agent')} · ${escape(voiceSummary(r))}</small></div></div><b class="compare-status"></b><p class="compare-answer"></p></article>`).join('');
  }
  comparison.rows.forEach((r,i)=>{const card=comparePanel.querySelector('[data-compare-row="'+i+'"]');card.querySelector('.compare-status').textContent=r.status;card.querySelector('.compare-answer').textContent=r.answer||'';});
}
let comparisonRead=null;
const comparisonPending=row=>row.job&&!['done','error','cancelled','unavailable'].includes(row.status);
async function pollComparison(schedule=true){
  const batch=comparison;if(!batch)return;
  if(!comparisonRead)comparisonRead=Promise.all(batch.rows.filter(comparisonPending).map(async r=>{
    try{const state=await api('state',undefined,r.key),job=state.jobs.find(j=>j.id===r.job);if(!job){r.status='unavailable';r.answer='This mission is no longer in the agent’s visible history.';return;}r.status=job.status;r.answer=job.result?.answer||job.result?.error||'';}
    catch(error){r.answer=error.message;if(error.status===404)r.status='unavailable';}
  })).finally(()=>{comparisonRead=null;});
  await comparisonRead;
  if(comparison!==batch)return;drawComparison();
  if(schedule&&batch.rows.some(comparisonPending)){clearTimeout(comparisonTimer);comparisonTimer=setTimeout(pollComparison,2500);}
}
async function askAllAgents(){
  if(comparisonSending||!personalReady(data.profile)||data.deleting||radarChatDisabled())return;
  if(rejectLoungePlan())return;
  comparisonSending=true;syncComposer();
  try{
    // Refresh before deciding: the cached comparison may lag behind completed jobs.
    if(comparison){
      await pollComparison(false);
      if(comparison.rows.some(comparisonPending)){
        clearTimeout(comparisonTimer);comparisonTimer=setTimeout(pollComparison,2500);return;
      }
    }
    const prompt=el('prompt').value.trim(),agents=(data.agents||[]).filter(a=>!radarChatDisabled(a)).map(a=>({...a}));if((!prompt&&!pendingImages().length)||agents.length<2)return;
    const draft=captureChatDraft(),images=draft.images;
    clearTimeout(comparisonTimer);
    const batch=comparison={id:String(Date.now()),prompt,rows:agents.map(a=>({...a,status:'Waiting for queue',answer:'',job:null}))};drawComparison();
    for(const row of batch.rows){
      while(comparison===batch){
        try{if(row.deleting)throw new Error('This agent is being deleted.');if(!personalReady(row))throw new Error(personalModelNotice(row));const job=await api('jobs',{kind:'chat',prompt,images},row.key);row.job=job.id;row.status=job.status||'queued';break;}
        catch(error){
          // A rejected quota request has not created a job. Wait for this batch's
          // accepted work to free a slot; never retry an uncertain network failure.
          if(error.status===429&&batch.rows.some(comparisonPending)){
            row.status='Waiting for queue';drawComparison();
            await new Promise(resolve=>setTimeout(resolve,750));
            if(comparison!==batch)return;
            await pollComparison(false);
          }else{row.status='error';row.answer=error.message;break;}
        }
      }
      if(comparison!==batch)return;
      drawComparison();
    }
    if(comparison.rows.some(row=>row.job))acknowledgeChatDraft(draft);
    await refresh();drawComparison();pollComparison();
  }finally{comparisonSending=false;syncComposer();}
}
