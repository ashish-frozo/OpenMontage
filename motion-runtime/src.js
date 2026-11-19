import rough from 'roughjs';
import {interpolate} from 'flubber';
import ELK from 'elkjs/lib/elk.bundled.js';
import lottie from 'lottie-web';
import transitions from 'gl-transitions';
import createTransition from 'gl-transition';
import createTexture from 'gl-texture2d';
import Matter from 'matter-js';
import * as vega from 'vega';
import * as maplibregl from 'maplibre-gl';
import {tsParticles} from '@tsparticles/engine';
import {loadSlim} from '@tsparticles/slim';
const ns='http://www.w3.org/2000/svg';
function svgEl(tag, attrs={}, text=''){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);e.textContent=text;return e;}
function canvas(w,h){const c=document.createElement('canvas');c.width=w;c.height=h;return c;}
function rng(seed){return ()=>{seed=(Math.imul(1664525,seed)+1013904223)>>>0;return seed/4294967296;};}
window.createMotionScene=async function(s){
 const renders=[]; document.body.style.cssText=`margin:0;background:${s.background};overflow:hidden`;
 await loadSlim(tsParticles);
 for(const [index,o] of s.objects.entries()){
  const box=document.createElement('div');box.id=o.id;box.style.cssText=`position:absolute;left:${o.x}px;top:${o.y}px;width:${o.width}px;height:${o.height}px;overflow:hidden`;document.body.append(box);
  const svg=svgEl('svg',{width:o.width,height:o.height,viewBox:`0 0 ${o.width} ${o.height}`});
  let render=()=>{};
  if(o.recipe==='media'){
   const img=new Image();img.src=o.image_data;await img.decode();const c=canvas(o.width,o.height);box.append(c);const ctx=c.getContext('2d');
   render=p=>{const z=1+(o.zoom_end-1)*p,scale=Math.max(o.width/img.width,o.height/img.height)*z,w=img.width*scale,h=img.height*scale;ctx.clearRect(0,0,o.width,o.height);ctx.drawImage(img,(o.width-w)/2+o.pan_x*(w-o.width)*p,(o.height-h)/2+o.pan_y*(h-o.height)*p,w,h);};
  }
  if(o.recipe==='sketch'){box.append(svg);const r=rough.svg(svg);svg.append(o.shape==='ellipse'?r.ellipse(o.width/2,o.height/2,o.width-20,o.height-20,{seed:s.seed+index,stroke:o.color,fill:o.secondary}):r.rectangle(10,10,o.width-20,o.height-20,{seed:s.seed+index,stroke:o.color,fill:o.secondary}));render=p=>svg.style.opacity=p;}
  if(o.recipe==='morph'){box.append(svg);const path=svgEl('path',{fill:o.color});svg.append(path);const f=interpolate(o.from_path,o.to_path);render=p=>path.setAttribute('d',f(p));}
  if(o.recipe==='diagram'){
   const layout=await new ELK().layout({id:'root',layoutOptions:{'elk.algorithm':'layered','elk.direction':'RIGHT'},children:o.nodes.map(n=>({id:n.id,width:110,height:50})),edges:o.edges.map((e,i)=>({id:'e'+i,sources:[e.source],targets:[e.target]}))});
   svg.setAttribute('viewBox',`0 0 ${layout.width} ${layout.height}`);box.append(svg);
   for(const e of layout.edges||[])for(const seg of e.sections||[]){const pts=[seg.startPoint,...(seg.bendPoints||[]),seg.endPoint];svg.append(svgEl('polyline',{points:pts.map(p=>`${p.x},${p.y}`).join(' '),fill:'none',stroke:o.secondary,'stroke-width':3}));}
   for(const n of layout.children){svg.append(svgEl('rect',{x:n.x,y:n.y,width:n.width,height:n.height,rx:8,fill:o.color}));svg.append(svgEl('text',{x:n.x+8,y:n.y+30,'font-size':14,fill:'#102030'},o.nodes.find(x=>x.id===n.id).label));}render=p=>svg.style.opacity=p;
  }
  if(o.recipe==='lottie'){const anim=lottie.loadAnimation({container:box,renderer:'svg',loop:false,autoplay:false,animationData:o.animation});await new Promise((resolve,reject)=>{anim.addEventListener('DOMLoaded',resolve);anim.addEventListener('data_failed',()=>reject(Error('Invalid Lottie data')));});render=p=>anim.goToAndStop(p*Math.max(0,anim.totalFrames-1),true);}
  if(o.recipe==='transition'){
   const c=canvas(o.width,o.height);box.append(c);const gl=c.getContext('webgl',{preserveDrawingBuffer:true});if(!gl)throw Error('WebGL unavailable');const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,-1,4,4,-1]),gl.STATIC_DRAW);gl.viewport(0,0,o.width,o.height);
   const texture=color=>{const c=canvas(2,2);const ctx=c.getContext('2d');ctx.fillStyle=color;ctx.fillRect(0,0,2,2);return createTexture(gl,c);};
   const from=texture(o.color),to=texture(o.secondary);const shader=transitions.find(t=>t.name.toLowerCase()===o.effect.toLowerCase());if(!shader)throw Error('Unsupported transition '+o.effect);
   const draw=createTransition(gl,shader);render=p=>draw.draw(p,from,to,o.width,o.height,{});
  }
  if(o.recipe==='physics'){
   const c=canvas(o.width,o.height);box.append(c);const ctx=c.getContext('2d'),random=rng(s.seed+index),engine=Matter.Engine.create();
   const bodies=Array.from({length:Math.min(o.count,40)},()=>Matter.Bodies.rectangle(20+random()*(o.width-40),20+random()*o.height/3,18,18,{restitution:.6}));Matter.Composite.add(engine.world,[...bodies,Matter.Bodies.rectangle(o.width/2,o.height+20,o.width,40,{isStatic:true})]);
   const frames=[];for(let f=0;f<=Math.ceil(o.duration*s.fps);f++){frames.push(bodies.map(b=>({x:b.position.x,y:b.position.y,a:b.angle})));Matter.Engine.update(engine,1000/s.fps);}
   render=p=>{ctx.clearRect(0,0,o.width,o.height);ctx.fillStyle=o.color;for(const b of frames[Math.min(frames.length-1,Math.floor(p*(frames.length-1)))]){ctx.save();ctx.translate(b.x,b.y);ctx.rotate(b.a);ctx.fillRect(-9,-9,18,18);ctx.restore();}};
  }
  if(o.recipe==='particles'){
   // Bake library-generated particles under a seeded RNG, then seek immutable frames.
   const c=canvas(o.width,o.height);box.append(c);const ctx=c.getContext('2d');const old=Math.random;let container;
   try{Math.random=rng(s.seed+index);container=await tsParticles.load({id:o.id+'-particles',options:{autoPlay:false,fullScreen:{enable:false},detectRetina:false,particles:{number:{value:o.count},color:{value:o.color},size:{value:3},move:{enable:false}},interactivity:{events:{onHover:{enable:false},onClick:{enable:false}}}}});}finally{Math.random=old;}
   container.pause();const random=rng(s.seed+index);const particles=Array.from({length:container.particles.count},()=>({x:random()*o.width,y:random()*o.height,v:10+random()*30}));container.destroy();
   render=p=>{ctx.clearRect(0,0,o.width,o.height);ctx.fillStyle=o.color;for(const a of particles){ctx.beginPath();ctx.arc(a.x,(a.y+p*o.duration*a.v)%o.height,3,0,Math.PI*2);ctx.fill();}};
  }
  if(o.recipe==='chart'){
   const spec={$schema:'https://vega.github.io/schema/vega/v6.json',width:o.width-50,height:o.height-40,padding:5,data:[{name:'table',values:o.data}],scales:[{name:'x',type:'band',domain:{data:'table',field:'label'},range:'width',padding:.1},{name:'y',domain:{data:'table',field:'value'},nice:true,range:'height'}],axes:[{orient:'bottom',scale:'x',labelColor:'white'},{orient:'left',scale:'y',labelColor:'white'}],marks:[{type:'rect',from:{data:'table'},encode:{enter:{x:{scale:'x',field:'label'},width:{scale:'x',band:1},y:{scale:'y',field:'value'},y2:{scale:'y',value:0},fill:{value:o.color}}}}]};
   await new vega.View(vega.parse(spec),{renderer:'svg',container:box}).runAsync();render=p=>box.style.clipPath=`inset(${(1-p)*100}% 0 0 0)`;
  }
  if(o.recipe==='map'){
   const map=new maplibregl.Map({container:box,style:{version:8,sources:{},layers:[{id:'bg',type:'background',paint:{'background-color':s.background}}]},interactive:false,attributionControl:false,fadeDuration:0});
   await new Promise(resolve=>map.on('load',resolve));map.addSource('route',{type:'geojson',data:{type:'Feature',properties:{},geometry:{type:'LineString',coordinates:o.coordinates}}});map.addLayer({id:'route',type:'line',source:'route',paint:{'line-color':o.color,'line-width':5}});const bounds=o.coordinates.reduce((b,c)=>b.extend(c),new maplibregl.LngLatBounds(o.coordinates[0],o.coordinates[0]));map.fitBounds(bounds,{padding:30,duration:0});
   render=async p=>{map.setPaintProperty('route','line-opacity',p);map.triggerRepaint();await new Promise(resolve=>map.once('render',resolve));};
  }
  if(o.recipe==='mouth'&&!o.mouth_data){box.append(svg);svg.append(svgEl('ellipse',{cx:o.width/2,cy:o.height/2,rx:o.width*.4,ry:o.height*.4,fill:o.color}));const mouth=svgEl('ellipse',{cx:o.width/2,cy:o.height*.65,rx:20,ry:2,fill:'#102030'});svg.append(mouth);render=p=>{const t=p*o.duration,cue=o.mouth_cues.find(c=>c.start<=t&&c.end>t);mouth.setAttribute('ry',({A:2,B:5,C:12,D:20,E:10,F:5,G:4,H:7,X:2})[cue?.value||'X']);};}
  if(o.recipe==='mouth'&&o.mouth_data){
   const images={};for(const [key,data] of Object.entries(o.mouth_data)){const img=new Image();img.src=data;await img.decode();images[key]=img;}
   const c=canvas(o.width,o.height);box.append(c);const ctx=c.getContext('2d');render=p=>{const t=p*o.duration,cue=o.mouth_cues.find(c=>c.start<=t&&c.end>t),img=images[cue?.value||'X'];ctx.clearRect(0,0,o.width,o.height);ctx.drawImage(img,0,0,o.width,o.height);};
  }
  if(o.label){const label=document.createElement('div');label.dataset.label='true';label.textContent=o.label;label.style.cssText='position:absolute;bottom:4px;left:4px;right:4px;color:white;font:20px sans-serif;white-space:nowrap';box.append(label);}
  renders.push(async t=>{box.style.opacity=t<o.start?'0':'1';const p=Math.max(0,Math.min(1,(t-o.start)/o.duration));await render(s.reduced_motion?1:p);});
 }
 window.render=async t=>{for(const render of renders)await render(t);};await window.render(0);window.READY=true;
};
