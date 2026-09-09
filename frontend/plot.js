import {COLORS, format} from './controls.js';

export class ScopePlot {
 constructor(wrap) {
  this.wrap=wrap;this.gridCanvas=document.querySelector('#grid-canvas');this.trace=document.querySelector('#trace-canvas');this.overlay=document.querySelector('#overlay-canvas');
  this.frame=null;this.persistence=0;this.grid='FULL';this.cursors=false;this.positions=[.35,.65];this.drag=-1;this.signature='';this.lastDraw=0;this.scheduled=false;this.pending=null;
  new ResizeObserver(()=>this.resize()).observe(wrap);
  this.overlay.addEventListener('pointerdown',e=>{if(!this.cursors)return;const x=this.pointerX(e);this.drag=Math.abs(x-this.positions[0])<Math.abs(x-this.positions[1])?0:1;this.positions[this.drag]=x;this.overlay.setPointerCapture(e.pointerId);this.drawOverlay();});
  this.overlay.addEventListener('pointermove',e=>{if(this.drag<0)return;this.positions[this.drag]=this.pointerX(e);this.drawOverlay();});
  this.overlay.addEventListener('pointerup',()=>this.drag=-1);this.overlay.addEventListener('pointercancel',()=>this.drag=-1);
 }
 pointerX(e){const r=this.overlay.getBoundingClientRect();return Math.max(0,Math.min(1,(e.clientX-r.left-this.area.x)/this.area.w));}
 resize(){
  const rect=this.wrap.getBoundingClientRect();this.width=rect.width;this.height=rect.height;const dpr=window.devicePixelRatio||1;
  if(!this.width||!this.height)return;
  for(const canvas of [this.gridCanvas,this.trace,this.overlay]){canvas.width=Math.round(this.width*dpr);canvas.height=Math.round(this.height*dpr);canvas.getContext('2d').setTransform(dpr,0,0,dpr,0,0);}
  this.area={x:28,y:13,w:this.width-56,h:this.height-45};this.drawGrid();if(this.frame)this.drawTraces(true);this.drawOverlay();
 }
 clear(){this.signature='';if(this.trace)this.trace.getContext('2d').clearRect(0,0,this.width,this.height);if(this.frame)this.drawTraces(true);}
 reset(){this.frame=null;this.pending=null;this.signature='';this.trace.getContext('2d').clearRect(0,0,this.width,this.height);this.drawGrid();this.drawOverlay();}
 ingest(buffer){
  if(buffer.byteLength<5)throw new Error('Incomplete waveform frame.');
  const size=new DataView(buffer).getUint32(0,true);if(size>buffer.byteLength-4)throw new Error('Invalid waveform header.');
  const frame=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,4,size)));
  for(const ch of frame.channels){if(ch.start<0||ch.length<0||4+size+ch.start+ch.length>buffer.byteLength)throw new Error('Incomplete channel data.');ch.data=new Uint8Array(buffer,4+size+ch.start,ch.length);}
  this.pending=frame;
  if(!this.scheduled){this.scheduled=true;requestAnimationFrame(()=>{this.scheduled=false;if(!this.pending)return;this.frame=this.pending;this.pending=null;this.drawGrid();this.drawTraces();this.drawOverlay();});}
  return frame;
 }
 drawGrid(){
  const ctx=this.gridCanvas.getContext('2d'),a=this.area;if(!a)return;ctx.clearRect(0,0,this.width,this.height);
  ctx.font='9px SFMono-Regular, Consolas, monospace';ctx.lineWidth=1;ctx.textBaseline='middle';
  if(this.grid==='FULL'){
   ctx.strokeStyle='#1b2a39';ctx.beginPath();
   for(let x=0;x<=12;x++){const px=a.x+x*a.w/12;ctx.moveTo(px,a.y);ctx.lineTo(px,a.y+a.h);}
   for(let y=0;y<=8;y++){const py=a.y+y*a.h/8;ctx.moveTo(a.x,py);ctx.lineTo(a.x+a.w,py);}ctx.stroke();
   ctx.fillStyle='#283747';for(let x=0;x<=60;x++)for(let y=0;y<=40;y++){if(x%5===0||y%5===0)continue;ctx.fillRect(a.x+x*a.w/60-.5,a.y+y*a.h/40-.5,1,1);}
  }
  if(this.grid!=='NONE'){
   ctx.strokeStyle='#3b4c5c';ctx.beginPath();ctx.moveTo(a.x,a.y+a.h/2);ctx.lineTo(a.x+a.w,a.y+a.h/2);ctx.moveTo(a.x+a.w/2,a.y);ctx.lineTo(a.x+a.w/2,a.y+a.h);ctx.stroke();
   ctx.strokeStyle='#3b4c5c';ctx.beginPath();for(let i=0;i<=60;i++){const x=a.x+i*a.w/60;ctx.moveTo(x,a.y+a.h/2-2);ctx.lineTo(x,a.y+a.h/2+2);}for(let i=0;i<=40;i++){const y=a.y+i*a.h/40;ctx.moveTo(a.x+a.w/2-2,y);ctx.lineTo(a.x+a.w/2+2,y);}ctx.stroke();
  }
  const scale=this.frame?.time_scale||.0002, offset=this.frame?.time_offset||0;
  ctx.fillStyle='#556a7e';ctx.textAlign='center';for(let x=0;x<=12;x+=2)ctx.fillText(format((x-6)*scale+offset,'s'),a.x+x*a.w/12,a.y+a.h+18);
  ctx.textAlign='left';ctx.fillStyle='#405468';ctx.fillText('Y',8,9);
 }
 drawTraces(force=false){
  if(!this.frame||!this.area)return;const ctx=this.trace.getContext('2d'),a=this.area;
  const signature=JSON.stringify([this.frame.generation,this.frame.time_scale,this.frame.time_offset,this.frame.channels.map(c=>[c.channel,c.scale,c.offset,c.preamble])]);
  const now=performance.now(),dt=Math.max(.001,(now-this.lastDraw)/1000);this.lastDraw=now;
  if(force||!this.persistence||signature!==this.signature)ctx.clearRect(0,0,this.width,this.height);
  else{ctx.save();ctx.globalCompositeOperation='destination-out';ctx.fillStyle=`rgba(0,0,0,${1-Math.exp(-dt/this.persistence)})`;ctx.fillRect(0,0,this.width,this.height);ctx.restore();}
  this.signature=signature;
  for(const channel of this.frame.channels){
   const p=channel.preamble,color=COLORS[channel.channel-1],scale=channel.scale;
   const point=i=>{
    const t=(i-p.x_reference)*p.x_increment+p.x_origin;
    const v=(channel.data[i]-p.y_origin-p.y_reference)*p.y_increment;
    return [a.x+((t-this.frame.time_offset)/(12*this.frame.time_scale)+.5)*a.w,a.y+a.h/2-(v+channel.offset)/scale*a.h/8];
   };
   ctx.save();ctx.beginPath();ctx.rect(a.x,a.y,a.w,a.h);ctx.clip();ctx.strokeStyle=color;ctx.lineWidth=1.45;ctx.lineJoin='round';ctx.lineCap='round';
   ctx.beginPath();for(let i=0;i<channel.data.length;i++){const [x,y]=point(i);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();
   ctx.globalAlpha=.14;ctx.lineWidth=4;ctx.stroke();ctx.restore();
  }
 }
 drawOverlay(){
  const ctx=this.overlay.getContext('2d'),a=this.area;if(!a)return;ctx.clearRect(0,0,this.width,this.height);
  for(const channel of this.frame?.channels||[]){
   const y=Math.max(a.y+6,Math.min(a.y+a.h-6,a.y+a.h/2-channel.offset/channel.scale*a.h/8));
   ctx.fillStyle=COLORS[channel.channel-1];ctx.beginPath();ctx.moveTo(a.x-4,y);ctx.lineTo(a.x-10,y-5);ctx.lineTo(5,y-5);ctx.lineTo(5,y+5);ctx.lineTo(a.x-10,y+5);ctx.closePath();ctx.fill();ctx.fillStyle='#0b141c';ctx.font='bold 8px monospace';ctx.textAlign='left';ctx.fillText(String(channel.channel),8,y+3);
  }
  const readout=document.querySelector('#cursor-readout');readout.hidden=!this.cursors||!this.frame;
  if(!this.cursors||!this.frame)return;
  this.positions.forEach((pos,index)=>{const x=a.x+pos*a.w;ctx.strokeStyle=index===0?'#b2cfdf':'#799ba9';ctx.setLineDash(index===0?[]:[4,4]);ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,a.y);ctx.lineTo(x,a.y+a.h);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#29414e';ctx.fillRect(x-9,a.y,18,17);ctx.fillStyle='#d1e7f1';ctx.font='10px monospace';ctx.textAlign='center';ctx.fillText(index===0?'A':'B',x,a.y+12);});
  const delta=Math.abs(this.positions[1]-this.positions[0])*12*this.frame.time_scale;
  readout.textContent=`Δt ${format(delta,'s',4)}   ·   1/Δt ${delta>0?format(1/delta,'Hz',4):'—'}`;
 }
 toggleCursors(){this.cursors=!this.cursors;this.overlay.style.cursor=this.cursors?'crosshair':'default';this.drawOverlay();return this.cursors;}
 async png(){
  const canvas=document.createElement('canvas');canvas.width=this.gridCanvas.width;canvas.height=this.gridCanvas.height+76*(window.devicePixelRatio||1);const ctx=canvas.getContext('2d'),dpr=window.devicePixelRatio||1;
  ctx.fillStyle='#0b121a';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(this.gridCanvas,0,0);ctx.drawImage(this.trace,0,0);ctx.drawImage(this.overlay,0,0);
  ctx.scale(dpr,dpr);ctx.fillStyle='#94a6b8';ctx.font='11px monospace';ctx.fillText(`RIGOL REMOTE · ${new Date((this.frame?.timestamp||Date.now()/1000)*1000).toISOString()}`,28,this.height+25);
  const values=this.frame?.channels.map(c=>`CH${c.channel} ${format(c.scale,c.unit)}/div`).join('   ')||'';ctx.fillText(`${values}   H ${format(this.frame?.time_scale,'s')}/div`,28,this.height+48);
  return new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
 }
}
