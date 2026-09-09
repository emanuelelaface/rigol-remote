import {COLORS,MATH_COLOR,TITLES,MEASUREMENTS,channelUnit,mathUnit,engineering,format,buildPanel,updateFields} from './controls.js';
import {ScopePlot} from './plot.js';

const $=selector=>document.querySelector(selector), $$=selector=>[...document.querySelectorAll(selector)];
const E=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;};
let state={connected:false,values:{},channel_count:2,measurements:{}},panel='vertical',panelFields=[],socket=null,socketReady=false,connectionBusy=false,commandBusy=false;
let catalog=[],lastBinaryAt=0,lastScreenURL=null,previousScreenAt=0,requestQueue=Promise.resolve(),history=[],historyIndex=0,lastGeneration=-1,lastModel='',previousTrigger='',lastError='',lastUnits='';
let measurements=[];
const plot=new ScopePlot($('#plot-wrap'));
try{const host=localStorage.getItem('rigol-host');if(host)$('#host-input').value=host;const port=localStorage.getItem('rigol-port');if(port)$('#port-input').value=port;}catch{}

function toast(message,error=false){const n=E('div',`toast${error?' error':''}`,message);$('#toasts').append(n);setTimeout(()=>n.remove(),error?8000:3500);}
async function attempt(callback){try{return await callback();}catch(error){toast(error.message||String(error),true);return null;}}
async function api(data){
 const response=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const body=await response.json();if(!response.ok)throw new Error(body.error||'The server could not complete the request.');
 if(body.state)applyState(body.state);return body.result;
}
function log(command,result,error=false){
 const output=$('#console-output');output.append(E('div','log-command','› '+command));
 if(result!==undefined&&result!==null){const row=E('div',error?'log-error':'log-response',typeof result==='string'?result:JSON.stringify(result));output.append(row);}
 else if(!error)output.append(E('div','log-response','Completed · instrument acknowledged'));
 while(output.children.length>250)output.firstElementChild.remove();output.scrollTop=output.scrollHeight;
}
function saveBlob(blob,filename){const url=URL.createObjectURL(blob),a=E('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
async function download(url,filename,button){
 const text=button?.textContent;if(button){button.disabled=true;button.textContent='Downloading…';}
 try{const response=await fetch(url);if(!response.ok){const body=await response.json();throw new Error(body.error||'Download failed.');}saveBlob(await response.blob(),filename);}
 finally{if(button){button.textContent=text;button.disabled=!state.connected;}}
}
function command(value,readback){
 const operation=async()=>{
  if(!state.connected)throw new Error('Connect an oscilloscope first.');
  commandBusy=true;updateDisabled();
  try{
   const result=await api({action:'command',command:value});
   if(result&&typeof result==='object'&&result.binary){const bytes=Uint8Array.from(atob(result.binary),c=>c.charCodeAt(0));saveBlob(new Blob([bytes]),'rigol-response.bin');log(value,`${result.length} bytes downloaded`);}
   else log(value,result);
   return result;
  }catch(error){log(value,error.message,true);throw error;}
  finally{commandBusy=false;updateDisabled();updateFields($('#control-panel'),state);}
 };
 const result=requestQueue.then(operation);requestQueue=result.catch(()=>{});return result;
}
const hooks={state:()=>state,command,attempt,library:openLibrary,toast,download,stream:settings=>api({action:'stream',...settings}),plot,cursors:toggleCursors,saveSettings:()=>saveBlob(new Blob([JSON.stringify({instrument:state.idn,saved_at:new Date().toISOString(),settings:state.values},null,2)],{type:'application/json'}),'rigol-settings.json')};
function updateDisabled(){$$('[data-connected]').forEach(n=>n.disabled=!state.connected||!socketReady||connectionBusy||commandBusy);}
function showPanel(name,read=true){
 panel=name;$('#panel-title').textContent=TITLES[name];$$('[data-panel]').forEach(b=>{b.classList.toggle('active',b.dataset.panel===name);b.setAttribute('aria-current',b.dataset.panel===name?'page':'false');});
 const built=buildPanel(name,state,hooks);panelFields=built.fields;$('#control-panel').replaceChildren(...built.nodes);updateFields($('#control-panel'),state);updateDisabled();
 if(read&&state.connected&&panelFields.length)attempt(()=>api({action:'read',fields:panelFields}));
}
function renderChannels(){
 const strip=$('#channel-strip');strip.replaceChildren();
 for(let ch=1;ch<=state.channel_count;ch++){
  const button=E('button','channel-chip');button.style.setProperty('--channel-color',COLORS[ch-1]);button.classList.toggle('off',state.values[`:CHAN${ch}:DISP`]!=='1');button.title=`Open channel ${ch} controls`;
  const detail=E('span','channel-detail');detail.append(E('strong','',format(state.values[`:CHAN${ch}:SCAL`],channelUnit(state,ch))+' / div'),E('small','',`${state.values[`:CHAN${ch}:COUP`]||'—'}  ·  ${state.values[`:CHAN${ch}:PROB`]?Number(state.values[`:CHAN${ch}:PROB`])+'× probe':'—'}`));
  button.append(E('span','channel-number',String(ch)),detail);button.onclick=()=>{showPanel('vertical');const cards=$$('#control-panel .control-section');cards[ch-1]?.scrollIntoView({block:'nearest',behavior:'smooth'});};strip.append(button);
 }
 if(['1','ON'].includes(state.values[':MATH:DISP'])){
  const button=E('button','channel-chip');button.style.setProperty('--channel-color',MATH_COLOR);button.title='Open math controls';
  const detail=E('span','channel-detail');detail.append(E('strong','',format(state.values[':MATH:SCAL'],mathUnit(state))+' / div'),E('small','',state.values[':MATH:OPER']||'MATH'));
  button.append(E('span','channel-number','M'),detail);button.onclick=()=>showPanel('math');strip.append(button);
 }
}
function applyState(next){
 const wasConnected=state.connected;state={...state,...next,values:next.values||state.values};
 plot.setInstrumentState(state);
 const connected=state.connected,idn=state.idn?.split(',')||[],newModel=idn[1]||'';
 $('#connection-dot').className='status-dot'+(connected?' connected':'')+(state.demo?' demo':'');
 $('#connection-label').textContent=connected?(state.demo?'Demo instrument':`${state.host}:${state.port}`):'Connect instrument';
 $('#instrument-model').textContent=connected?newModel:'Oscilloscope';$('#instrument-detail').textContent=connected?`${idn[2]||''}  ·  FW ${idn[3]||''}`:'Your bench. A clearer view.';
 $('#demo-badge').hidden=!connected||!state.demo;$('#plot-empty').hidden=connected;$('#disconnect-button').hidden=!connected;
 if(newModel!==lastModel||(!wasConnected&&connected)){lastModel=newModel;plot.reset();showPanel(panel,false);renderMeasurements();if(connected)attempt(()=>api({action:'read',fields:panelFields}));}
 if(!connected&&wasConnected){plot.reset();$('#screen-image').hidden=true;lastBinaryAt=0;}
 $('#time-scale').textContent=format(state.values[':TIM:MAIN:SCAL'],'s');$('#sample-rate').textContent=format(state.values[':ACQ:SRAT'],'Sa/s');
 $('#memory-depth').textContent=state.values[':ACQ:MDEP']==='AUTO'?'Auto memory':format(state.values[':ACQ:MDEP'],'pts');
 const status=state.values[':TRIG:STAT']||'OFFLINE',stopped=status==='STOP';
 $('#trigger-status').textContent=connected?({TD:'TRIGGERED',WAIT:'WAITING',AUTO:'AUTO',RUN:'RUNNING',STOP:'STOPPED'}[status]||status):'OFFLINE';
 $('#trigger-status').className='trigger-status'+(connected?(stopped?' stopped':' running'):'');$('#run-button').classList.toggle('stopped',stopped);$('#run-button span').textContent=connected?(stopped?'Run':'Stop'):'Run / Stop';
 $('#run-button svg use').setAttribute('href',stopped?'#i-play':'#i-acquire');
 const source=state.values[':TRIG:EDGE:SOUR']||'—',edge=state.values[':TRIG:EDGE:SLOP'];
 $('#trigger-summary').textContent=state.values[':TRIG:MODE']==='EDGE'?`${source.replace('CHAN','CH')} ${edge==='NEG'?'↘':'↗'} ${format(state.values[':TRIG:EDGE:LEV'],'V')}`:state.values[':TRIG:MODE']||'—';
 if(previousTrigger&&previousTrigger!==state.values[':TRIG:MODE']&&panel==='trigger')showPanel('trigger');previousTrigger=state.values[':TRIG:MODE'];
 $('#waveform-view').classList.toggle('selected',state.mode==='waveform');$('#screen-view').classList.toggle('selected',state.mode==='screen');
 const screenMode=state.mode==='screen';$('#screen-image').hidden=!screenMode||!connected;for(const n of [$('#trace-canvas'),$('#grid-canvas'),$('#overlay-canvas')])n.hidden=screenMode;
 plot.setDisplayMode(screenMode);
 $('#cursors-toggle').disabled=screenMode;$('#persistence-toggle').disabled=screenMode;
 $('#pause-button').textContent=state.streaming?'Pause view':'Resume view';$('#live-dot').classList.toggle('active',connected&&state.streaming&&socketReady);
 $('#stream-status').textContent=!connected?'Waiting for instrument':!state.streaming?'View paused · acquisition unchanged':state.demo?'Demo stream':screenMode?'Instrument screenshots':'Live waveform transfer';
 if(state.generation!==lastGeneration){lastGeneration=state.generation;plot.clear();}
 if(state.error&&state.error!==lastError){toast(state.error,true);lastError=state.error;}else if(!state.error)lastError='';
 const units=Array.from({length:state.channel_count},(_,i)=>state.values[`:CHAN${i+1}:UNIT`]).join(',');
 if(units!==lastUnits&&panel==='vertical')showPanel('vertical',false);lastUnits=units;
 updateFields($('#control-panel'),state);renderChannels();updateMeasurements();updateDisabled();updateNotice();
}
function updateNotice(){
 const notice=$('#plot-notice');let text='';
 if(state.connected){
  if(!socketReady)text='Server connection lost · displayed data is stale';
  else if(state.error)text=state.error;
  else if(!state.streaming)text='View paused · last received data';
  else if(lastBinaryAt&&Date.now()-lastBinaryAt>3000)text='Waiting for a fresh frame · displayed data is stale';
  else if(state.mode==='waveform'&&plot.frame?.waiting_channels?.length){const waiting=plot.frame.waiting_channels.map(value=>typeof value==='number'?`CH${value}`:value).join(', ');text=`${waiting}: waiting for an acquisition · check the trigger or select Auto sweep`;}
  else if(state.mode==='waveform'&&!Array.from({length:state.channel_count},(_,i)=>state.values[`:CHAN${i+1}:DISP`]).includes('1'))text='All channels are off · enable a channel to display its waveform';
  else if(state.mode==='waveform'&&state.values[':TIM:MODE']!=='MAIN')text='Fast view shows Y–T samples · use Instrument screen for this timebase mode';
 }
 notice.textContent=text;notice.hidden=!text;
}
function renderMeasurements(){
 const grid=$('#measurement-grid');grid.replaceChildren();
 if(!measurements.length)grid.append(E('div','empty-measurements','Add a measurement to monitor your signal.'));
 measurements.forEach((m,index)=>{
  const key=`${m.channel}:${m.item}`,item=E('div','measurement-item');item.dataset.measurement=key;item.style.setProperty('--channel-color',COLORS[m.channel-1]);
  const label=E('div','measurement-label');label.append(E('span','channel-label',`CH${m.channel}`),E('span','',MEASUREMENTS[m.item][0]));
  const value=E('div','measurement-value');value.append(E('span','','—'),E('small','',MEASUREMENTS[m.item][1]));
  const remove=E('button','remove-measurement','×');remove.title='Remove measurement';remove.setAttribute('aria-label',`Remove CH${m.channel} ${MEASUREMENTS[m.item][0]}`);remove.onclick=()=>{measurements.splice(index,1);renderMeasurements();attempt(syncMeasurements);};
  item.append(label,value,remove);grid.append(item);
 });$('#measurement-count').textContent=measurements.length;updateMeasurements();
}
function updateMeasurements(){
 for(const el of $$('[data-measurement]')){
  const [channel,key]=el.dataset.measurement.split(':'),m=state.measurements?.[el.dataset.measurement];const stale=!state.connected||!socketReady||!m||Date.now()/1000-m.timestamp>Math.max(8,measurements.length*.7);
  const v=engineering(stale?null:m.value,MEASUREMENTS[key][1].replace('V',channelUnit(state,channel)),4);el.querySelector('.measurement-value span').textContent=v.number;el.querySelector('.measurement-value small').textContent=v.unit;
  el.title=stale?'Waiting for a current instrument measurement':`Read at ${new Date(m.timestamp*1000).toLocaleTimeString()}`;
 }
}
async function syncMeasurements(){if(state.connected)await api({action:'measurements',items:measurements});}
function connectWebSocket(){
 socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);socket.binaryType='arraybuffer';
 socket.onopen=()=>{socketReady=true;updateDisabled();updateNotice();};
 socket.onmessage=event=>{
  try{
   if(typeof event.data==='string'){
    const message=JSON.parse(event.data);
    if(message.type==='state')applyState(message);
    else if(message.type==='measurement'){state.measurements[message.key]={value:message.value,timestamp:message.timestamp};updateMeasurements();}
   }else{
    const bytes=new Uint8Array(event.data);lastBinaryAt=Date.now();
    if(bytes[0]===137&&bytes[1]===80&&bytes[2]===78&&bytes[3]===71){
     if(state.mode!=='screen')return;
     const url=URL.createObjectURL(new Blob([event.data],{type:'image/png'}));$('#screen-image').src=url;if(lastScreenURL)URL.revokeObjectURL(lastScreenURL);lastScreenURL=url;
     if(previousScreenAt){const duration=performance.now()-previousScreenAt;$('#fps-value').textContent=`${(1000/duration).toFixed(1)} fps`;$('#latency-value').textContent=`${duration.toFixed(0)} ms / frame`;}previousScreenAt=performance.now();
    }else{
     if(state.mode!=='waveform')return;
     const frame=plot.ingest(event.data);$('#fps-value').textContent=frame.fps?`${frame.fps.toFixed(1)} fps`:'Measuring…';$('#latency-value').textContent=`${frame.acquisition_ms.toFixed(0)} ms / frame`;
    }
    updateNotice();
   }
  }catch(error){toast('Display: '+error.message,true);}
 };
 socket.onclose=()=>{socketReady=false;updateDisabled();updateNotice();$('#live-dot').classList.remove('active');$('#stream-status').textContent='Server disconnected';setTimeout(connectWebSocket,2000);};
 socket.onerror=()=>socket.close();
}
function bottom(name){$$('[data-bottom]').forEach(b=>b.classList.toggle('active',b.dataset.bottom===name));$('#measurements-pane').hidden=name!=='measurements';$('#console-pane').hidden=name!=='console';$('#add-measurement').hidden=name!=='measurements';}
function showDialog(selector){const d=$(selector);if(!d.open)d.showModal();}
function toggleCursors(){const on=plot.toggleCursors();$('#cursors-toggle').classList.toggle('active',on);}
async function openLibrary(filter=''){
 showDialog('#library-dialog');$('#catalog-search').value=filter;$('#catalog-group').value='';$('#catalog-response').textContent='';
 if(!catalog.length){const response=await fetch('/api/catalog');catalog=await response.json();const groups=[...new Set(catalog.map(e=>e.group))].sort((a,b)=>a.localeCompare(b));for(const group of groups)$('#catalog-group').append(new Option(group,group));$('#catalog-count').textContent=catalog.length;}
 renderCatalog();
}
function renderCatalog(){
 const q=$('#catalog-search').value.toLowerCase(),group=$('#catalog-group').value,root=$('#catalog-results');root.replaceChildren();
 const matches=catalog.filter(e=>(!group||e.group===group)&&(!q||JSON.stringify(e).toLowerCase().includes(q)));
 for(const entry of matches){
  const row=E('div','catalog-row'),left=E('div');left.append(E('code','',entry.name));
  if(entry.choices.length)left.append(E('small','',entry.choices.join(' · ')));
  const buttons=E('div','catalog-buttons');
  for(const form of entry.forms){
   const query=form.includes('?'),button=E('button','',query?'Query':'Set / run');button.title=form;
   button.onclick=()=>{$('#catalog-command').value=form.replace(/\[:([A-Za-z]+)\]/g,':$1').replace(/\[([?])\]/g,'$1');$('#catalog-response').textContent='';$('#catalog-command').focus();};buttons.append(button);
  }
  row.append(left,buttons);root.append(row);
 }
 if(!matches.length)root.append(E('div','empty-measurements','No commands match your search.'));
}

$$('[data-panel]').forEach(b=>b.onclick=()=>showPanel(b.dataset.panel));
$$('[data-bottom]').forEach(b=>b.onclick=()=>bottom(b.dataset.bottom));
$$('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$$('dialog').forEach(d=>d.addEventListener('click',e=>{const r=d.getBoundingClientRect();if(e.target===d&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))d.close();}));
for(const selector of ['#connection-button','#empty-connect'])$(selector).onclick=()=>showDialog('#connect-dialog');
$('#connect-form').onsubmit=e=>{
 e.preventDefault();attempt(async()=>{
  connectionBusy=true;updateDisabled();$('#connect-error').hidden=true;$('#connect-submit').disabled=true;$('#connect-submit').textContent='Connecting…';
  try{await api({action:'connect',host:$('#host-input').value.trim(),port:Number($('#port-input').value)});try{localStorage.setItem('rigol-host',$('#host-input').value.trim());localStorage.setItem('rigol-port',$('#port-input').value);}catch{}$('#connect-dialog').close();await syncMeasurements();toast('Instrument connected.');}
  catch(error){$('#connect-error').textContent=error.message;$('#connect-error').hidden=false;}
  finally{connectionBusy=false;$('#connect-submit').disabled=false;$('#connect-submit').textContent='Connect instrument ↗';updateDisabled();}
 });
};
$('#disconnect-button').onclick=()=>attempt(async()=>{await api({action:'disconnect'});$('#connect-dialog').close();});
$('#demo-button').onclick=()=>attempt(async()=>{await api({action:'connect',demo:true});await syncMeasurements();});
$('#refresh-settings').onclick=()=>attempt(async()=>{await api({action:'read',fields:panelFields});toast('Settings refreshed from the instrument.');});
$('#run-button').onclick=()=>attempt(()=>command(state.values[':TRIG:STAT']==='STOP'?':RUN':':STOP'));
$('#single-button').onclick=()=>attempt(()=>command(':SING'));
$('#auto-button').onclick=()=>attempt(async()=>{await command(':AUT');setTimeout(()=>attempt(()=>api({action:'read',fields:panelFields})),1200);});
$('#clear-button').onclick=()=>attempt(async()=>{await command(':CLE');plot.clear();});
$('#waveform-view').onclick=()=>attempt(()=>api({action:'stream',mode:'waveform',enabled:true}));
$('#screen-view').onclick=()=>attempt(()=>api({action:'stream',mode:'screen',enabled:true}));
$('#pause-button').onclick=()=>attempt(()=>api({action:'stream',enabled:!state.streaming}));
$('#cursors-toggle').onclick=toggleCursors;
$('#persistence-toggle').onclick=()=>{plot.persistence=plot.persistence?0:1;plot.clear();$('#persistence-toggle').classList.toggle('active',!!plot.persistence);};
$('#capture-button').onclick=()=>attempt(async()=>{if(state.mode==='screen'){if(!lastScreenURL)throw new Error('Wait for an instrument screenshot first.');saveBlob(await (await fetch(lastScreenURL)).blob(),'rigol-screen.png');}else{if(!plot.frame)throw new Error('Acquire a waveform first.');saveBlob(await plot.png(),'rigol-waveforms.png');}});
$('#fullscreen-button').onclick=()=>attempt(()=>document.fullscreenElement?document.exitFullscreen():$('#scope-card').requestFullscreen());
$('#export-csv').onclick=()=>attempt(()=>download('/api/waveforms.csv','rigol-waveforms.csv',$('#export-csv')));
$('#help-button').onclick=()=>showDialog('#help-dialog');
for(const selector of ['#library-button','#console-library'])$(selector).onclick=()=>attempt(()=>openLibrary());
$('#catalog-search').oninput=renderCatalog;$('#catalog-group').onchange=renderCatalog;
$$('[data-filter]').forEach(b=>b.onclick=()=>{$('#catalog-search').value=b.dataset.filter;$('#catalog-group').value='';renderCatalog();});
$('#catalog-send').onclick=()=>attempt(async()=>{const value=$('#catalog-command').value;$('#catalog-response').textContent='Sending…';try{const result=await command(value);$('#catalog-response').textContent=result===null?'Completed · instrument acknowledged':typeof result==='string'?result:`${result.length} bytes downloaded`;$('#catalog-response').classList.remove('error-text');}catch(error){$('#catalog-response').textContent=error.message;$('#catalog-response').classList.add('error-text');}});
$('#catalog-command').onkeydown=e=>{if(e.key==='Enter')$('#catalog-send').click();};
$('#console-form').onsubmit=e=>{e.preventDefault();const value=$('#console-input').value.trim();if(!value)return;history.push(value);historyIndex=history.length;$('#console-input').value='';attempt(()=>command(value));};
$('#console-input').onkeydown=e=>{if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();historyIndex=Math.max(0,Math.min(history.length,historyIndex+(e.key==='ArrowUp'?-1:1)));e.target.value=history[historyIndex]||'';}};
$('#add-measurement').onclick=()=>{
 const src=$('#measurement-source');src.replaceChildren();for(let ch=1;ch<=state.channel_count;ch++)src.append(new Option(`Channel ${ch}`,ch));
 const items=$('#measurement-item');items.replaceChildren();for(const [key,[label,unit]] of Object.entries(MEASUREMENTS))items.append(new Option(`${label}${unit?' · '+unit:''}`,key));showDialog('#measurement-dialog');
};
$('#measurement-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{if(measurements.length>=16)throw new Error('Up to 16 live measurements are supported.');const m={channel:Number($('#measurement-source').value),item:$('#measurement-item').value};if(measurements.some(x=>x.channel===m.channel&&x.item===m.item))throw new Error('This measurement is already displayed.');measurements.push(m);renderMeasurements();await syncMeasurements();$('#measurement-dialog').close();});};
document.addEventListener('keydown',e=>{
 if(e.ctrlKey||e.metaKey||e.altKey||e.repeat||e.target.matches('input,textarea,select')||$('dialog[open]'))return;
 const actions={' ':'#run-button',s:'#single-button',a:'#auto-button',c:'#clear-button',f:'#fullscreen-button','?':'#help-button'};
 const selector=actions[e.key.toLowerCase()];if(selector){e.preventDefault();$(selector).click();}
});
setInterval(()=>{updateNotice();updateMeasurements();if(lastBinaryAt&&Date.now()-lastBinaryAt>3000)$('#fps-value').textContent='0.0 fps';},1000);
showPanel('vertical',false);renderMeasurements();renderChannels();updateDisabled();connectWebSocket();
