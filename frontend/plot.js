import {COLORS, MATH_COLOR, format} from './controls.js';

const traceColor=channel=>channel==='MATH'?MATH_COLOR:COLORS[channel-1];
const traceLabel=channel=>channel==='MATH'?'M':String(channel);
const finite=(value,fallback=0)=>value!==null&&value!==''&&Number.isFinite(Number(value))?Number(value):fallback;

export class ScopePlot {
 constructor(wrap) {
  this.wrap=wrap;this.gridCanvas=document.querySelector('#grid-canvas');this.trace=document.querySelector('#trace-canvas');this.overlay=document.querySelector('#overlay-canvas');
  this.fftPanel=document.querySelector('#fft-panel');this.fftWrap=document.querySelector('#fft-wrap');this.fftGrid=document.querySelector('#fft-grid-canvas');this.fftTrace=document.querySelector('#fft-trace-canvas');this.fftReadout=document.querySelector('#fft-readout');
  this.frame=null;this.instrument=null;this.screenMode=false;this.persistence=0;this.grid='FULL';this.cursors=false;this.positions=[.35,.65];this.drag=-1;this.mainSignature='';this.fftSignature='';this.lastMainDraw=0;this.lastFFTDraw=0;this.scheduled=false;this.pending=null;
  const observer=new ResizeObserver(entries=>{for(const entry of entries){if(entry.target===this.wrap)this.resize();else if(entry.target===this.fftWrap)this.resizeFFT();}});observer.observe(wrap);observer.observe(this.fftWrap);
  this.overlay.addEventListener('pointerdown',e=>{if(!this.cursors)return;const x=this.pointerX(e);this.drag=Math.abs(x-this.positions[0])<Math.abs(x-this.positions[1])?0:1;this.positions[this.drag]=x;this.overlay.setPointerCapture(e.pointerId);this.drawOverlay();});
  this.overlay.addEventListener('pointermove',e=>{if(this.drag<0)return;this.positions[this.drag]=this.pointerX(e);this.drawOverlay();});
  this.overlay.addEventListener('pointerup',()=>this.drag=-1);this.overlay.addEventListener('pointercancel',()=>this.drag=-1);
 }
 pointerX(e){const r=this.overlay.getBoundingClientRect();return Math.max(0,Math.min(1,(e.clientX-r.left-this.area.x)/this.area.w));}
 sizeCanvases(canvases,width,height){const dpr=window.devicePixelRatio||1;for(const canvas of canvases){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);canvas.getContext('2d').setTransform(dpr,0,0,dpr,0,0);}}
 resize(){
  const rect=this.wrap.getBoundingClientRect();this.width=rect.width;this.height=rect.height;if(!this.width||!this.height)return;
  this.sizeCanvases([this.gridCanvas,this.trace,this.overlay],this.width,this.height);
  this.area={x:28,y:13,w:this.width-56,h:this.height-45};this.drawGrid();if(this.frame)this.drawTraces(true);this.drawOverlay();
 }
 resizeFFT(){
  if(this.fftPanel.hidden)return;const rect=this.fftWrap.getBoundingClientRect();this.fftWidth=rect.width;this.fftHeight=rect.height;if(!this.fftWidth||!this.fftHeight)return;
  this.sizeCanvases([this.fftGrid,this.fftTrace],this.fftWidth,this.fftHeight);
  this.fftArea={x:58,y:12,w:this.fftWidth-78,h:this.fftHeight-43};this.drawFFTGrid();if(this.frame)this.drawFFTTrace(true);
 }
 fftChannel(){return this.frame?.channels.find(channel=>channel.channel==='MATH'&&channel.operation==='FFT');}
 updateFFTVisibility(){
  const spectrum=this.fftChannel(),hidden=this.screenMode||!spectrum,changed=this.fftPanel.hidden!==hidden;this.fftPanel.hidden=hidden;
  if(hidden){this.fftReadout.textContent='—';return;}
  const scale=this.fftScale(spectrum),center=this.fftCenter(spectrum,scale);this.fftReadout.textContent=`${format(scale,'Hz')} / div  ·  center ${format(center,'Hz')}`;
  if(changed||!this.fftArea)this.resizeFFT();
 }
 clear(){this.mainSignature='';this.fftSignature='';if(this.trace)this.trace.getContext('2d').clearRect(0,0,this.width||0,this.height||0);if(this.fftTrace)this.fftTrace.getContext('2d').clearRect(0,0,this.fftWidth||0,this.fftHeight||0);if(this.frame){this.drawTraces(true);this.drawFFTTrace(true);}}
 reset(){this.frame=null;this.pending=null;this.mainSignature='';this.fftSignature='';this.trace.getContext('2d').clearRect(0,0,this.width||0,this.height||0);this.fftTrace.getContext('2d').clearRect(0,0,this.fftWidth||0,this.fftHeight||0);this.fftPanel.hidden=true;this.drawGrid();this.drawOverlay();}
 setInstrumentState(state){this.instrument=state;this.drawOverlay();}
 setDisplayMode(screenMode){this.screenMode=screenMode;this.updateFFTVisibility();}
 ingest(buffer){
  if(buffer.byteLength<5)throw new Error('Incomplete waveform frame.');
  const size=new DataView(buffer).getUint32(0,true);if(size>buffer.byteLength-4)throw new Error('Invalid waveform header.');
  const frame=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,4,size)));
  for(const ch of frame.channels){if(ch.start<0||ch.length<0||4+size+ch.start+ch.length>buffer.byteLength)throw new Error('Incomplete channel data.');ch.data=new Uint8Array(buffer,4+size+ch.start,ch.length);}
  this.pending=frame;
  if(!this.scheduled){this.scheduled=true;requestAnimationFrame(()=>{this.scheduled=false;if(!this.pending)return;this.frame=this.pending;this.pending=null;this.drawGrid();this.drawTraces();this.drawOverlay();this.updateFFTVisibility();this.drawFFTGrid();this.drawFFTTrace();});}
  return frame;
 }
 drawGrid(){
  const ctx=this.gridCanvas.getContext('2d'),a=this.area;if(!a)return;ctx.clearRect(0,0,this.width,this.height);ctx.font='9px SFMono-Regular, Consolas, monospace';ctx.lineWidth=1;ctx.textBaseline='middle';this.drawGridLines(ctx,a);
  const scale=this.frame?.time_scale||.0002,offset=this.frame?.time_offset||0;ctx.fillStyle='#556a7e';ctx.textAlign='center';for(let x=0;x<=12;x+=2)ctx.fillText(format((x-6)*scale+offset,'s'),a.x+x*a.w/12,a.y+a.h+18);ctx.textAlign='left';ctx.fillStyle='#405468';ctx.fillText('Y',8,9);
 }
 drawGridLines(ctx,a){
  if(this.grid==='FULL'){
   ctx.strokeStyle='#1b2a39';ctx.beginPath();for(let x=0;x<=12;x++){const px=a.x+x*a.w/12;ctx.moveTo(px,a.y);ctx.lineTo(px,a.y+a.h);}for(let y=0;y<=8;y++){const py=a.y+y*a.h/8;ctx.moveTo(a.x,py);ctx.lineTo(a.x+a.w,py);}ctx.stroke();
   ctx.fillStyle='#283747';for(let x=0;x<=60;x++)for(let y=0;y<=40;y++){if(x%5===0||y%5===0)continue;ctx.fillRect(a.x+x*a.w/60-.5,a.y+y*a.h/40-.5,1,1);}
  }
  if(this.grid!=='NONE'){
   ctx.strokeStyle='#3b4c5c';ctx.beginPath();ctx.moveTo(a.x,a.y+a.h/2);ctx.lineTo(a.x+a.w,a.y+a.h/2);ctx.moveTo(a.x+a.w/2,a.y);ctx.lineTo(a.x+a.w/2,a.y+a.h);ctx.stroke();ctx.beginPath();for(let i=0;i<=60;i++){const x=a.x+i*a.w/60;ctx.moveTo(x,a.y+a.h/2-2);ctx.lineTo(x,a.y+a.h/2+2);}for(let i=0;i<=40;i++){const y=a.y+i*a.h/40;ctx.moveTo(a.x+a.w/2-2,y);ctx.lineTo(a.x+a.w/2+2,y);}ctx.stroke();
  }
 }
 fadeOrClear(ctx,width,height,force,signature,previous,lastDraw){
  const now=performance.now(),dt=Math.max(.001,(now-lastDraw)/1000);if(force||!this.persistence||signature!==previous)ctx.clearRect(0,0,width,height);else{ctx.save();ctx.globalCompositeOperation='destination-out';ctx.fillStyle=`rgba(0,0,0,${1-Math.exp(-dt/this.persistence)})`;ctx.fillRect(0,0,width,height);ctx.restore();}return now;
 }
 displayValue(channel,sample){
  const p=channel.preamble;
  if(channel.channel==='MATH')return (sample-p.y_reference)*p.y_increment+finite(channel.offset);
  return (sample-p.y_origin-p.y_reference)*p.y_increment+finite(channel.offset);
 }
 drawTraces(force=false){
  if(!this.frame||!this.area)return;const ctx=this.trace.getContext('2d'),a=this.area,traces=this.frame.channels.filter(channel=>!(channel.channel==='MATH'&&channel.operation==='FFT'));
  const signature=JSON.stringify([this.frame.generation,this.frame.time_scale,this.frame.time_offset,traces.map(c=>[c.channel,c.scale,c.offset,c.preamble])]);this.lastMainDraw=this.fadeOrClear(ctx,this.width,this.height,force,signature,this.mainSignature,this.lastMainDraw);this.mainSignature=signature;
  for(const channel of traces){const p=channel.preamble,color=traceColor(channel.channel),scale=finite(channel.scale,1);if(scale<=0)continue;const point=i=>{const t=(i-p.x_reference)*p.x_increment+p.x_origin,v=this.displayValue(channel,channel.data[i]);return [a.x+((t-this.frame.time_offset)/(12*this.frame.time_scale)+.5)*a.w,a.y+a.h/2-v/scale*a.h/8];};this.strokeTrace(ctx,a,channel.data.length,point,color);}
 }
 strokeTrace(ctx,a,length,point,color){ctx.save();ctx.beginPath();ctx.rect(a.x,a.y,a.w,a.h);ctx.clip();ctx.strokeStyle=color;ctx.lineWidth=1.45;ctx.lineJoin='round';ctx.lineCap='round';ctx.beginPath();for(let i=0;i<length;i++){const [x,y]=point(i);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();ctx.globalAlpha=.14;ctx.lineWidth=4;ctx.stroke();ctx.restore();}
 fftScale(channel){const explicit=finite(channel?.frequency_scale);if(explicit>0)return explicit;const p=channel?.preamble;return p&&p.x_increment>0?p.x_increment*Math.max(1,channel.data.length-1)/12:1;}
 fftCenter(channel,scale=this.fftScale(channel)){const explicit=finite(channel?.frequency_center,NaN);if(Number.isFinite(explicit))return explicit;const p=channel?.preamble;return p?p.x_origin+(channel.data.length/2-p.x_reference)*p.x_increment:6*scale;}
 drawFFTGrid(){
  const channel=this.fftChannel(),ctx=this.fftGrid.getContext('2d'),a=this.fftArea;if(!channel||!a||this.fftPanel.hidden)return;ctx.clearRect(0,0,this.fftWidth,this.fftHeight);ctx.font='9px SFMono-Regular, Consolas, monospace';ctx.lineWidth=1;ctx.textBaseline='middle';this.drawGridLines(ctx,a);
  const hScale=this.fftScale(channel),center=this.fftCenter(channel,hScale),vScale=finite(channel.scale,1),offset=finite(channel.offset),unit=channel.unit||'';ctx.fillStyle='#556a7e';ctx.textAlign='center';for(let x=0;x<=12;x+=2)ctx.fillText(format(center+(x-6)*hScale,'Hz'),a.x+x*a.w/12,a.y+a.h+18);ctx.textAlign='right';for(let y=0;y<=8;y+=2)ctx.fillText(format((4-y)*vScale-offset,unit),a.x-7,a.y+y*a.h/8);ctx.textAlign='left';ctx.fillStyle=MATH_COLOR;ctx.fillText('FFT',8,9);
 }
 drawFFTTrace(force=false){
  const channel=this.fftChannel(),a=this.fftArea;if(!channel||!a||this.fftPanel.hidden)return;const ctx=this.fftTrace.getContext('2d'),p=channel.preamble,scale=finite(channel.scale,1);if(scale<=0)return;const signature=JSON.stringify([this.frame.generation,channel.scale,channel.offset,channel.frequency_scale,channel.frequency_center,channel.preamble]);this.lastFFTDraw=this.fadeOrClear(ctx,this.fftWidth,this.fftHeight,force,signature,this.fftSignature,this.lastFFTDraw);this.fftSignature=signature;
  const point=i=>{const v=this.displayValue(channel,channel.data[i]);return [a.x+i/Math.max(1,channel.data.length-1)*a.w,a.y+a.h/2-v/scale*a.h/8];};this.strokeTrace(ctx,a,channel.data.length,point,MATH_COLOR);
 }
 drawOverlay(){
  const ctx=this.overlay.getContext('2d'),a=this.area;if(!a)return;ctx.clearRect(0,0,this.width,this.height);this.drawTimeZero(ctx,a);this.drawTrigger(ctx,a);
  for(const channel of this.frame?.channels||[]){if(channel.channel==='MATH'&&channel.operation==='FFT')continue;const scale=finite(channel.scale,1);if(scale<=0)continue;const y=Math.max(a.y+6,Math.min(a.y+a.h-6,a.y+a.h/2-finite(channel.offset)/scale*a.h/8));ctx.fillStyle=traceColor(channel.channel);ctx.beginPath();ctx.moveTo(a.x-4,y);ctx.lineTo(a.x-10,y-5);ctx.lineTo(5,y-5);ctx.lineTo(5,y+5);ctx.lineTo(a.x-10,y+5);ctx.closePath();ctx.fill();ctx.fillStyle='#0b141c';ctx.font='bold 8px monospace';ctx.textAlign='left';ctx.fillText(traceLabel(channel.channel),8,y+3);}
  const readout=document.querySelector('#cursor-readout');readout.hidden=!this.cursors||!this.frame;if(!this.cursors||!this.frame)return;this.positions.forEach((pos,index)=>{const x=a.x+pos*a.w;ctx.strokeStyle=index===0?'#b2cfdf':'#799ba9';ctx.setLineDash(index===0?[]:[4,4]);ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,a.y);ctx.lineTo(x,a.y+a.h);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#29414e';ctx.fillRect(x-9,a.y,18,17);ctx.fillStyle='#d1e7f1';ctx.font='10px monospace';ctx.textAlign='center';ctx.fillText(index===0?'A':'B',x,a.y+12);});const delta=Math.abs(this.positions[1]-this.positions[0])*12*this.frame.time_scale;readout.textContent=`Δt ${format(delta,'s',4)}   ·   1/Δt ${delta>0?format(1/delta,'Hz',4):'—'}`;
 }
 drawTimeZero(ctx,a){
  const frame=this.frame;if(!frame||!Number.isFinite(frame.time_scale)||frame.time_scale<=0)return;const raw=a.x+(.5-frame.time_offset/(12*frame.time_scale))*a.w,left=a.x,right=a.x+a.w,visible=raw>=left&&raw<=right,x=Math.max(left,Math.min(right,raw));ctx.save();ctx.strokeStyle='#e3a95f';ctx.fillStyle='#e3a95f';ctx.lineWidth=1;if(visible){ctx.globalAlpha=.72;ctx.setLineDash([3,5]);ctx.beginPath();ctx.moveTo(x,a.y);ctx.lineTo(x,a.y+a.h);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;ctx.beginPath();ctx.moveTo(x-5,a.y-7);ctx.lineTo(x+5,a.y-7);ctx.lineTo(x,a.y);ctx.closePath();ctx.fill();ctx.font='bold 8px monospace';ctx.textAlign='center';ctx.fillText('0',x,a.y-9);}else{const direction=raw<left?1:-1;ctx.beginPath();ctx.moveTo(x,a.y-8);ctx.lineTo(x+direction*7,a.y-4);ctx.lineTo(x,a.y);ctx.closePath();ctx.fill();ctx.font='bold 8px monospace';ctx.textAlign=raw<left?'left':'right';ctx.fillText('0',x+direction*9,a.y-4);}ctx.restore();
 }
 drawTrigger(ctx,a){
  const values=this.instrument?.values||{};if(!this.frame||values[':TRIG:MODE']!=='EDGE')return;const match=String(values[':TRIG:EDGE:SOUR']||'').match(/CHAN(?:NEL)?(\d+)/i),level=Number(values[':TRIG:EDGE:LEV']);if(!match||!Number.isFinite(level))return;const number=Number(match[1]),channel=this.frame.channels.find(item=>item.channel===number);if(!channel||!Number.isFinite(channel.scale)||channel.scale<=0)return;const raw=a.y+a.h/2-(level+channel.offset)/channel.scale*a.h/8,top=a.y,bottom=a.y+a.h,visible=raw>=top&&raw<=bottom,y=Math.max(top+1,Math.min(bottom-1,raw)),right=a.x+a.w,color=COLORS[number-1]||'#e3a95f';ctx.save();ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1;if(visible){ctx.globalAlpha=.62;ctx.setLineDash([6,5]);ctx.beginPath();ctx.moveTo(a.x,y);ctx.lineTo(right,y);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;}ctx.beginPath();ctx.moveTo(right,y);ctx.lineTo(right+7,y-5);ctx.lineTo(right+23,y-5);ctx.lineTo(right+23,y+5);ctx.lineTo(right+7,y+5);ctx.closePath();ctx.fill();ctx.fillStyle='#0b141c';ctx.font='bold 8px monospace';ctx.textAlign='center';ctx.fillText(visible?'T':raw<top?'↑':'↓',right+15,y+3);ctx.restore();
 }
 toggleCursors(){this.cursors=!this.cursors;this.overlay.style.cursor=this.cursors?'crosshair':'default';this.drawOverlay();return this.cursors;}
 async png(){
  const dpr=window.devicePixelRatio||1,includeFFT=!!this.fftChannel()&&!this.screenMode,fftHeader=includeFFT?34*dpr:0,fftHeight=includeFFT?this.fftGrid.height:0,footer=76*dpr,canvas=document.createElement('canvas');canvas.width=this.gridCanvas.width;canvas.height=this.gridCanvas.height+fftHeader+fftHeight+footer;const ctx=canvas.getContext('2d');ctx.fillStyle='#0b121a';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(this.gridCanvas,0,0);ctx.drawImage(this.trace,0,0);ctx.drawImage(this.overlay,0,0);
  let footerY=this.height;if(includeFFT){ctx.fillStyle='#111923';ctx.fillRect(0,this.gridCanvas.height,canvas.width,fftHeader);ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle=MATH_COLOR;ctx.font='bold 10px monospace';ctx.fillText(`M  FFT SPECTRUM   ${this.fftReadout.textContent}`,28,this.height+22);ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(this.fftGrid,0,this.gridCanvas.height+fftHeader);ctx.drawImage(this.fftTrace,0,this.gridCanvas.height+fftHeader);footerY+=34+this.fftHeight;}
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#94a6b8';ctx.font='11px monospace';ctx.fillText(`RIGOL REMOTE · ${new Date((this.frame?.timestamp||Date.now()/1000)*1000).toISOString()}`,28,footerY+25);const values=this.frame?.channels.map(c=>`${c.channel==='MATH'?'MATH':'CH'+c.channel} ${format(c.scale,c.unit)}/div`).join('   ')||'';ctx.fillText(`${values}   H ${format(this.frame?.time_scale,'s')}/div`,28,footerY+48);return new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
 }
}
