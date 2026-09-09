export const COLORS = ['#ebd66c', '#6ad6e9', '#b798f7', '#f09b85'];
export const channelUnit = (state,ch) => ({VOLT:'V',AMP:'A',WATT:'W',UNKN:''}[state.values?.[`:CHAN${ch}:UNIT`]] ?? 'V');
export const TITLES = {vertical:'Vertical channels',horizontal:'Horizontal timebase',trigger:'Trigger',acquire:'Acquisition',math:'Math & FFT',cursors:'Cursor measurements',display:'Display preferences',system:'System & tools'};
export const MEASUREMENTS = {
 FREQ:['Frequency','Hz'], PER:['Period','s'], VPP:['Peak to peak','V'], VRMS:['RMS','V'], VMAX:['Maximum','V'], VMIN:['Minimum','V'],
 VAVG:['Average','V'], VTOP:['Top','V'], VBAS:['Base','V'], VAMP:['Amplitude','V'], RTIM:['Rise time','s'], FTIM:['Fall time','s'],
 PWID:['Positive width','s'], NWID:['Negative width','s'], PDUT:['Positive duty','%'], NDUT:['Negative duty','%'],
 OVER:['Overshoot','%'], PRES:['Preshoot','%'], MAR:['Area','V·s'], MPAR:['Period area','V·s'],
 TVMAX:['Time at maximum','s'], TVMIN:['Time at minimum','s'], PSLEW:['Positive slew','V/s'], NSLEW:['Negative slew','V/s'],
 VUPP:['Upper','V'], VMID:['Middle','V'], VLOW:['Lower','V'], VAR:['Variance','V²'], PVRMS:['Period RMS','V'],
 PPUL:['Positive pulses',''], NPUL:['Negative pulses',''], PEDG:['Positive edges',''], NEDG:['Negative edges','']
};

export function engineering(value, unit='', digits=3) {
 if(value===null || value===undefined || !Number.isFinite(Number(value)) || Math.abs(Number(value))>=1e30) return {number:'—',unit};
 const n=Number(value);
 if(unit==='%' || !unit) return {number:Number(n.toPrecision(digits)).toString(),unit};
 const steps=[[-12,'p'],[-9,'n'],[-6,'µ'],[-3,'m'],[0,''],[3,'k'],[6,'M'],[9,'G'],[12,'T']];
 const exp=n===0 ? 0 : Math.max(-12,Math.min(12,Math.floor(Math.log10(Math.abs(n))/3)*3));
 const prefix=steps.find(x=>x[0]===exp)?.[1] || '';
 return {number:Number((n/10**exp).toPrecision(digits)).toString(),unit:prefix+unit};
}
export function format(value, unit='', digits=3){const f=engineering(value,unit,digits);return `${f.number}${f.unit?' '+f.unit:''}`;}
export function parseValue(text) {
 const match=String(text).trim().match(/^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([pnuµμmkMGT]?)(?:\s*(?:V|s|Hz|Sa\/s|pts|%|W|A))?$/);
 if(!match) throw new Error('Enter a number, optionally with an SI prefix: 500 mV, 20 µs, 1e-3.');
 const powers={p:-12,n:-9,u:-6,'µ':-6,'μ':-6,m:-3,k:3,M:6,G:9,T:12,'':0};
 const value=Number(match[1])*10**powers[match[2]];
 if(!Number.isFinite(value)) throw new Error('Enter a finite number.');
 return value;
}
const E=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
const options=(...entries)=>entries.map(x=>Array.isArray(x)?x:[x,x]);
const BOOL=options(['1','On'],['0','Off']);
const CH=(count)=>Array.from({length:count},(_,i)=>[`CHAN${i+1}`,`Channel ${i+1}`]);
const series=(min,max)=>{const out=[];for(let p=-12;p<13;p++)for(const m of [1,2,5]){const n=m*10**p;if(n>=min*(1-1e-9)&&n<=max*(1+1e-9))out.push(n);}return out;};

export function buildPanel(name, state, hooks) {
 const root=E('div'); const fields=[]; const count=state.channel_count||2;
 function field(parent,label,key,type='number',unit='',values=null,limits={}) {
  const wrap=E('label','field'); const top=E('span','',label); if(unit)top.append(E('small','field-unit',unit));wrap.append(top);
  let input;
  if(type==='select') {input=E('select');input.append(new Option('—',''));for(const [val,text] of values)input.append(new Option(text,val));}
  else {input=E('input');input.type='text';input.inputMode='decimal';input.placeholder='—';input.autocomplete='off';input.spellcheck=false;}
  input.dataset.key=key;input.dataset.unit=unit;input.dataset.connected='';input.setAttribute('aria-label',label);fields.push(key);
  if(type==='step') {
   const step=E('div','stepper');
   for(const direction of [-1,1]) {
    const button=E('button','',direction<0?'−':'+');button.type='button';button.dataset.connected='';button.title=`${direction<0?'Decrease':'Increase'} ${label.toLowerCase()}`;
    button.addEventListener('click',()=>hooks.attempt(async()=>{
     const current=Number(hooks.state().values[key]);
     if(!Number.isFinite(current))throw new Error('Read the current setting first.');
     let next;
     if(limits.series){const seq=typeof limits.series==='function'?limits.series():limits.series;next=direction>0?seq.find(v=>v>current*1.001):[...seq].reverse().find(v=>v<current*.999);}
     else next=current+direction*(limits.increment?.()||1);
     if(next===undefined)throw new Error('End of the available range.');
     await hooks.command(`${key} ${Number(next.toPrecision(10))}`,key);
    }));
    if(direction<0){step.append(button,input);}else step.append(button);
   }
   wrap.append(step);
  } else wrap.append(input);
  const apply=()=>hooks.attempt(async()=>{
   const value=type==='select'?input.value:parseValue(input.value);
   if(value==='')return;
   if(limits.min!==undefined&&value<limits.min || limits.max!==undefined&&value>limits.max)throw new Error(`Allowed range: ${limits.min} to ${limits.max} ${unit}.`);
   if(limits.integer&&!Number.isInteger(value))throw new Error('Enter a whole number.');
   await hooks.command(`${key} ${value}`,key);
  });
  input.addEventListener('change',apply);
  input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();input.blur();}});
  parent.append(wrap);return input;
 }
 function section(title,channel) {
  const card=E('section','control-section');if(channel)card.style.setProperty('--channel-color',COLORS[channel-1]);
  const head=E('div','control-section-heading');const caption=E('span');
  if(channel)caption.append(E('b','channel-number',String(channel)));caption.append(document.createTextNode(title));head.append(caption);
  if(channel){const toggle=E('button','toggle');toggle.dataset.toggle=`:CHAN${channel}:DISP`;toggle.dataset.connected='';toggle.setAttribute('aria-label',`Toggle channel ${channel}`);toggle.append(E('i'),E('span','','ON'));toggle.onclick=()=>hooks.attempt(()=>hooks.command(`:CHAN${channel}:DISP ${hooks.state().values[`:CHAN${channel}:DISP`]==='1'?'0':'1'}`,`:CHAN${channel}:DISP`));head.append(toggle);}
  const body=E('div','control-section-body');card.append(head,body);root.append(card);return body;
 }
 function select(parent,label,key,values){return field(parent,label,key,'select','',values);}
 function number(parent,label,key,unit='',limits={}){return field(parent,label,key,'number',unit,null,limits);}
 function note(text){root.append(E('p','panel-note',text));}
 function link(text,filter){const button=E('button','button panel-link',text+' ↗');button.onclick=()=>hooks.library(filter);root.append(button);}
 function localSelect(parent,label,key,values,current,handler){const wrap=E('label','field');wrap.append(E('span','',label));const input=E('select');input.id=key;for(const [v,t] of values)input.append(new Option(t,v));input.value=String(current);input.onchange=()=>handler(input.value);wrap.append(input);parent.append(wrap);}
 if(name==='vertical') {
  for(let ch=1;ch<=count;ch++) {
   const p=section(`Channel ${ch}`,ch), base=`:CHAN${ch}`, unit=channelUnit(state,ch);
   field(p,'Vertical scale',`${base}:SCAL`,'step',unit+' / div',null,{series:()=>series(.0005*(Number(hooks.state().values[`${base}:PROB`])||1),10*(Number(hooks.state().values[`${base}:PROB`])||1))});
   field(p,'Position',`${base}:OFFS`,'step',unit,null,{increment:()=>Number(hooks.state().values[`${base}:SCAL`])/5});
   const row=E('div','field-row');p.append(row);
   select(row,'Coupling',`${base}:COUP`,options('DC','AC','GND'));
   select(row,'Probe',`${base}:PROB`,[.01,.02,.05,.1,.2,.5,1,2,5,10,20,50,100,200,500,1000].map(v=>[String(v),`${v}×`]));
   const details=E('details','control-details');details.append(E('summary','','Channel options'));p.append(details);
   select(details,'Bandwidth limit',`${base}:BWL`,options(['OFF','Full bandwidth'],['20M','20 MHz']));
   select(details,'Invert',`${base}:INV`,BOOL);select(details,'Fine adjustment',`${base}:VERN`,BOOL);
   select(details,'Unit',`${base}:UNIT`,options(['VOLT','Voltage'],['AMP','Current'],['WATT','Power'],['UNKN','Unknown']));
  }
  note('Values accept SI prefixes. Type 500 mV or 2 V, then press Enter. Channel colors follow the instrument.');
 } else if(name==='horizontal') {
  let p=section('Main timebase');
  field(p,'Time scale',':TIM:MAIN:SCAL','step','s / div',null,{series:series(5e-9,50)});
  field(p,'Horizontal position',':TIM:MAIN:OFFS','step','s',null,{increment:()=>Number(hooks.state().values[':TIM:MAIN:SCAL'])/5});
  select(p,'Timebase mode',':TIM:MODE',options(['MAIN','Y–T'],['XY','X–Y'],['ROLL','Roll']));
  p=section('Delayed timebase');select(p,'Delayed sweep',':TIM:DEL:ENAB',BOOL);number(p,'Scale',':TIM:DEL:SCAL','s / div');number(p,'Position',':TIM:DEL:OFFS','s');
  note('The fast view plots the main Y–T traces. Use Instrument screen for XY, roll and the delayed window.');
 } else if(name==='trigger') {
  let p=section('Trigger setup');
  select(p,'Type',':TRIG:MODE',options(['EDGE','Edge'],['PULS','Pulse width'],['RUNT','Runt'],['WIND','Window'],['NEDG','Nth edge'],['SLOP','Slope'],['VID','Video'],['PATT','Pattern'],['DEL','Delay'],['TIM','Timeout'],['DUR','Duration'],['SHOL','Setup / hold'],['RS232','RS232 / UART'],['IIC','I²C'],['SPI','SPI']));
  select(p,'Sweep',':TRIG:SWE',options(['AUTO','Auto'],['NORM','Normal'],['SING','Single']));
  const mode=state.values?.[':TRIG:MODE']||'EDGE';
  if(mode==='EDGE') {
   p=section('Edge parameters');select(p,'Source',':TRIG:EDGE:SOUR',[...CH(count),['AC','AC line']]);
   select(p,'Slope',':TRIG:EDGE:SLOP',options(['POS','Rising ↗'],['NEG','Falling ↘'],['RFAL','Either edge']));
   field(p,'Trigger level',':TRIG:EDGE:LEV','step','V',null,{increment:()=>Number(hooks.state().values[':CHAN1:SCAL']||1)/5});
   select(p,'Coupling',':TRIG:COUP',options(['DC','DC'],['AC','AC'],['LFR','LF reject'],['HFR','HF reject']));
  } else {link(`Configure ${mode} trigger`,`:TRIGger:${{PULS:'PULSe',RUNT:'RUNT',WIND:'WINDows',NEDG:'NEDGe',SLOP:'SLOPe',VID:'VIDeo',PATT:'PATTern',DEL:'DELay',TIM:'TIMeout',DUR:'DURATion',SHOL:'SHOLd',RS232:'RS232',IIC:'IIC',SPI:'SPI'}[mode]||mode}`);}
  p=section('Timing & noise');number(p,'Holdoff',':TRIG:HOLD','s',{min:16e-9,max:10});select(p,'Noise rejection',':TRIG:NREJ',BOOL);
  const force=E('button','button full-width','Force trigger');force.dataset.connected='';force.onclick=()=>hooks.attempt(()=>hooks.command(':TFOR'));p.append(force);
 } else if(name==='acquire') {
  let p=section('Acquisition engine');select(p,'Acquisition type',':ACQ:TYPE',options(['NORM','Normal'],['AVER','Average'],['PEAK','Peak detect'],['HRES','High resolution']));
  select(p,'Averages',':ACQ:AVER',[2,4,8,16,32,64,128,256,512,1024].map(v=>[String(v),String(v)]));
  const enabled=Array.from({length:count},(_,i)=>state.values?.[`:CHAN${i+1}:DISP`]).filter(v=>v==='1').length;
  const depths=enabled<=1?[12000,120000,1200000,12000000,24000000]:enabled<=2?[6000,60000,600000,6000000,12000000]:[3000,30000,300000,3000000,6000000];
  select(p,'Memory depth',':ACQ:MDEP',[['AUTO','Automatic'],...depths.map(v=>[String(v),format(v,'pts')])]);
  p=section('Full acquisition memory');const choice=E('select');choice.id='memory-channel';for(const [v,t] of CH(count))choice.append(new Option(t,v.slice(-1)));p.append(choice);
  p.append(E('p','hint','Stop acquisition first. Download all stored BYTE samples with time and voltage calibration in a ZIP archive.'));
  const download=E('button','button full-width','Download memory ZIP');download.dataset.connected='';download.onclick=()=>hooks.attempt(()=>hooks.download(`/api/memory.zip?channel=${choice.value}`,'rigol-memory.zip',download));p.append(download);
  link('Waveform recording & playback',':FUNCtion:WREC');link('Pass / fail testing',':MASK');
 } else if(name==='math') {
  note('These controls operate the instrument’s math engine. Select Instrument screen to see its math or FFT trace.');
  let p=section('Math operation');select(p,'Math trace',':MATH:DISP',BOOL);
  select(p,'Operator',':MATH:OPER',options(['ADD','A + B'],['SUBT','A − B'],['MULT','A × B'],['DIV','A ÷ B'],['FFT','FFT'],['AND','A AND B'],['OR','A OR B'],['XOR','A XOR B'],['NOT','NOT A'],['INTG','Integral'],['DIFF','Derivative'],['SQRT','Square root'],['LOG','Log₁₀'],['LN','Natural logarithm'],['EXP','Exponential'],['ABS','Absolute'],['FILT','Filter']));
  select(p,'Source A',':MATH:SOUR1',CH(count));select(p,'Source B',':MATH:SOUR2',CH(count));number(p,'Vertical scale',':MATH:SCAL');number(p,'Position',':MATH:OFFS');
  p=section('FFT spectrum');select(p,'Source',':MATH:FFT:SOUR',CH(count));select(p,'Window',':MATH:FFT:WIND',options(['RECT','Rectangle'],['HANN','Hanning'],['HAMM','Hamming'],['BLAC','Blackman'],['FLAT','Flat top'],['TRI','Triangle']));
  select(p,'Amplitude unit',':MATH:FFT:UNIT',options(['DB','dB'],['VRMS','Vrms']));select(p,'Split display',':MATH:FFT:SPL',BOOL);select(p,'Data source',':MATH:FFT:MODE',options(['TRAC','Screen trace'],['MEM','Acquisition memory']));number(p,'Frequency scale',':MATH:FFT:HSC','Hz / div');number(p,'Center frequency',':MATH:FFT:HCEN','Hz');
  link('Filters & compound operations',':MATH:');
 } else if(name==='cursors') {
  let p=section('Local time cursors');const button=E('button','button full-width','Toggle draggable cursors');button.onclick=hooks.cursors;p.append(button);p.append(E('p','hint','Drag A and B on the waveform to read Δt and 1/Δt. These cursors belong to this browser.'));
  p=section('Instrument cursors');select(p,'Cursor mode',':CURS:MODE',options(['OFF','Off'],['MAN','Manual'],['TRAC','Track'],['AUTO','Auto'],['XY','XY']));select(p,'Manual type',':CURS:MAN:TYPE',options(['X','Time (X)'],['Y','Voltage (Y)']));select(p,'Source',':CURS:MAN:SOUR',[...CH(count),['MATH','Math']]);
  for(const axis of ['X','Y'])for(const cursor of ['A','B'])number(p,`${cursor} · ${axis} position`,`:CURS:MAN:${cursor}${axis}`,'px',{min:5,max:axis==='X'?594:394,integer:true});
  note('Instrument cursor coordinates use the Rigol’s 600 × 400 plot area. View these cursors on Instrument screen.');link('Cursor values & tracking',':CURSor');
 } else if(name==='display') {
  let p=section('This workspace');
  localSelect(p,'Target transfer rate','target-fps',options(['5','5 fps'],['10','10 fps'],['15','15 fps'],['20','20 fps'],['30','30 fps'],['60','60 fps']),state.target_fps||10,v=>hooks.attempt(()=>hooks.stream({fps:Number(v)})));
  localSelect(p,'Local persistence','local-persistence',options(['0','Off'],['0.3','300 ms'],['1','1 second'],['5','5 seconds']),hooks.plot.persistence,v=>{hooks.plot.persistence=Number(v);hooks.plot.clear();});
  localSelect(p,'Local grid','local-grid',options(['FULL','Full grid'],['HALF','Axes only'],['NONE','None']),hooks.plot.grid,v=>{hooks.plot.grid=v;hooks.plot.resize();});
  p.append(E('p','hint','The target is a ceiling. Actual frames per second depend on the instrument, timebase, active channels and LAN.'));
  p=section('Instrument display');select(p,'Drawing',':DISP:TYPE',options(['VECT','Vectors'],['DOTS','Dots']));select(p,'Persistence',':DISP:GRAD:TIME',options(['MIN','Minimum'],['0.1','100 ms'],['0.2','200 ms'],['0.5','500 ms'],['1','1 second'],['5','5 seconds'],['10','10 seconds'],['INF','Infinite']));number(p,'Waveform brightness',':DISP:WBR','%',{min:0,max:100,integer:true});select(p,'Grid',':DISP:GRID',options(['FULL','Full'],['HALF','Half'],['NONE','None']));number(p,'Grid brightness',':DISP:GBR','%',{min:0,max:100,integer:true});
 } else if(name==='system') {
  let p=section('Instrument preferences');select(p,'Beeper',':SYST:BEEP',BOOL);select(p,'Front panel lock',':SYST:LOCK',BOOL);select(p,'Power-on settings',':SYST:PON',options(['LAT','Last settings'],['DEF','Default settings']));
  const err=E('button','button full-width','Read instrument error queue');err.dataset.connected='';err.onclick=()=>hooks.attempt(async()=>{const value=await hooks.command(':SYST:ERR?');hooks.toast(String(value));});p.append(err);
  p=section('Save & export');const screen=E('button','button full-width','Download instrument PNG');screen.dataset.connected='';screen.onclick=()=>hooks.attempt(()=>hooks.download('/api/screenshot.png','rigol-screen.png',screen));p.append(screen);
  const save=E('button','button full-width','Save workspace settings');save.onclick=hooks.saveSettings;p.append(save);
  link('Reference waveforms',':REFerence');link('Serial bus decoding',':DECoder');link('Recording & pass / fail',':FUNCtion');link('Storage commands',':STORage');link('All instrument commands','');
 }
 return {nodes:[...root.childNodes],fields:[...new Set(fields)]};
}

export function updateFields(root, state) {
 for(const input of root.querySelectorAll('[data-key]')) {
  const value=state.values?.[input.dataset.key];
  if(value===undefined || document.activeElement===input || input.classList.contains('pending'))continue;
  if(input.tagName==='SELECT') {
   const match=[...input.options].find(o=>o.value===value || (o.value!=='' && Number.isFinite(Number(value)) && Number(o.value)===Number(value)));
   if(match)input.value=match.value;
   else {let unknown=[...input.options].find(o=>o.dataset.actual);if(!unknown){unknown=new Option(String(value),String(value));unknown.dataset.actual='1';input.add(unknown);}unknown.value=value;unknown.textContent=value;input.value=value;}
  } else {const unit=input.dataset.unit.split(' / ')[0];input.value=format(value,['V','A','W','s','Hz','%'].includes(unit)?unit:'',6);}
 }
 for(const toggle of root.querySelectorAll('[data-toggle]')) {
  const on=state.values?.[toggle.dataset.toggle]==='1';toggle.classList.toggle('on',on);toggle.querySelector('span').textContent=on?'ON':'OFF';toggle.setAttribute('aria-pressed',String(on));
 }
}
