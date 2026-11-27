// SPDX-License-Identifier: Apache-2.0

// Only codes and source locations are retained. Never retain Error.message, bodies or URLs.
const browserDiagnostics=[];
const diagnosticRoutes=new Set('session state runtime diagnostics telemetry settings settings/models settings/start settings/team-model settings/connections settings/connections/preferences settings/connections/check settings/connections/models settings/scenario-model settings/scenario-models credential-session agents onboard profile agent-model delete-agent agent-policy crew-policy jobs upload decision ask-reaction retry-reaction reset crew-chat-reset bac-reset heartbeat team-model file workspace-files agent-documents evidence security'.split(' '));
function recordBrowserDiagnostic(code,fields={}){
 const event={time:new Date().toISOString(),code};
 if(fields.route)event.route=diagnosticRoutes.has(fields.route.split('?')[0])?fields.route.split('?')[0]:'unknown';
 if(/^[a-f0-9]{16}$/.test(fields.requestId||''))event.requestId=fields.requestId;
 for(const key of ['status','elapsedMs','line','column'])if(Number.isFinite(fields[key])&&fields[key]>=0)event[key]=Math.round(fields[key]);
 if(['Error','TypeError','ReferenceError','SyntaxError','RangeError','URIError','EvalError','AbortError'].includes(fields.type))event.type=fields.type;
 if(['app','external'].includes(fields.source))event.source=fields.source;
 const last=browserDiagnostics.at(-1);
 if(last&&JSON.stringify({...last,time:''})===JSON.stringify({...event,time:''}))return;
 browserDiagnostics.push(event);if(browserDiagnostics.length>40)browserDiagnostics.shift();
}
window.addEventListener('error',event=>{
 if(!(event instanceof ErrorEvent))return;
 let source='external';try{const url=new URL(event.filename);if(url.origin===location.origin&&url.pathname===location.pathname)source='app';}catch{}
 recordBrowserDiagnostic('script-error',{type:event.error?.name,source,line:event.lineno,column:event.colno});
});
window.addEventListener('unhandledrejection',event=>recordBrowserDiagnostic('unhandled-rejection',{type:event.reason?.name}));
async function collectDiagnostics(full=false){
 const report={schema:1,clientBuild:buildInfo,client:{room:['workshop','lounge','mission'].includes(room)?room:'unknown',
  teamMode:effectiveTeamMode(),
  platform:/Windows/.test(navigator.userAgent)?'Windows':/Macintosh/.test(navigator.userAgent)?'macOS':/Linux/.test(navigator.userAgent)?'Linux':'other'}};
 try{Object.assign(report,await api('diagnostics'+(full?'?full=1':'')));report.serverAvailable=true;}
 catch{report.serverAvailable=false;report.generatedAt=new Date().toISOString();}
 report.browserEvents=[...browserDiagnostics];
 return report;
}
function bindDiagnosticActions(){
 const copy=el('copy-build'),download=el('download-diagnostics'),notice=el('build-copy-status');
 const run=async full=>{
  if(copy.disabled)return;copy.disabled=true;download.disabled=true;notice.textContent='Collecting diagnostics…';
  try{
   const report=await collectDiagnostics(full),text='Multi-Agent Studio v'+buildInfo.version+' - diagnostics\n'+JSON.stringify(report,null,2);
   if(full){
    const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'})),link=document.createElement('a');
    link.href=url;link.download='bac-diagnostics-'+new Date().toISOString().replace(/[:.]/g,'-')+'.txt';
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
   }else await copyText(text);
   notice.textContent=(full?'Diagnostics downloaded.':'Diagnostics copied.')+(report.serverAvailable?'':' Server unavailable; browser and build details included.');
  }catch{notice.textContent='Could not export diagnostics. Try Download.';}
  finally{copy.disabled=false;download.disabled=false;}
 };
 copy.onclick=()=>run(false);download.onclick=()=>run(true);
}
