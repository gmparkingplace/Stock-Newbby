'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const {place,install}=require('../results/dashboard/context-help.js');
// Narrow viewport, bottom edge, long glossary and partially scrolled anchor.
for(const [anchor,w,h,vw,vh] of [
 [{left:1000,top:600,bottom:632},384,200,1120,700],
 [{left:290,top:620,bottom:664},384,900,320,680],
 [{left:15,top:10,bottom:42},384,300,390,844],
 [{left:15,top:300,bottom:332},384,1000,390,640]]){
 const p=place(anchor,w,h,vw,vh);
 assert(p.left>=12);assert(p.left+Math.min(w,vw-24)<=vw-12);
 assert(p.top>=12);assert(p.top+Math.min(h,p.maxHeight)<=vh-12);
}
class Element{
 constructor(id=''){this.id=id;this.dataset={};this.attrs={};this.listeners={};this.children=[];this.style={};this.classes=new Set();this.classList={add:s=>this.classes.add(s),remove:s=>this.classes.delete(s)};this.offsetWidth=384;this.scrollHeight=160;}
 setAttribute(k,v){this.attrs[k]=v;}getAttribute(k){return this.attrs[k];}
 append(...items){this.children.push(...items);}prepend(item){this.children.unshift(item);}
 addEventListener(k,fn){(this.listeners[k]||=[]).push(fn);}emit(k,extra={}){for(const f of this.listeners[k]||[])f({target:this,...extra});}
 contains(el){return el===this||this.children.some(c=>c.contains(el));}
 getBoundingClientRect(){return {left:280,top:600,bottom:632};}
 focus(){doc.activeElement=this;this.emit('focus');}
}
const buttons=[new Element('one'),new Element('two')],popups=[new Element('help1'),new Element('help2')],doc=new Element();
for(let i=0;i<2;i++){buttons[i].dataset.help=popups[i].id;buttons[i].setAttribute('aria-label','용어 '+i+' 도움말');}
doc.querySelectorAll=()=>buttons;doc.getElementById=id=>popups.find(p=>p.id===id);doc.createElement=()=>new Element();
let task=0;const tasks=new Map(),win=new Element();win.innerWidth=390;win.innerHeight=700;
win.setTimeout=fn=>{tasks.set(++task,fn);return task;};win.clearTimeout=id=>tasks.delete(id);
const flush=()=>{for(const [k,f] of [...tasks]){tasks.delete(k);f();}};
install(doc,win);
const isOpen=i=>popups[i].classes.has('isOpen');
buttons[0].emit('mouseenter');assert(isOpen(0));assert.equal(buttons[0].attrs['aria-expanded'],'true');
buttons[0].emit('mouseleave');popups[0].emit('mouseenter');flush();assert(isOpen(0),'pointer can enter the explanation');
popups[0].emit('mouseleave');flush();assert(!isOpen(0));
buttons[0].focus();assert(isOpen(0));buttons[0].emit('mouseleave');flush();assert(isOpen(0),'keyboard focus keeps help visible');
let prevented=false;doc.emit('keydown',{key:'Escape',preventDefault:()=>{prevented=true;},stopPropagation:()=>{}});assert(prevented);assert(!isOpen(0));
buttons[0].emit('click');assert(isOpen(0));buttons[0].emit('mouseleave');doc.activeElement=null;flush();assert(isOpen(0),'tap pins help');
buttons[1].emit('mouseenter');assert(!isOpen(0));assert(isOpen(1),'one popup at a time');
// A renderer updates the actual content node while open; it is never cloned or reset.
const live=new Element();live.textContent='원래 설명';popups[1].append(live);live.textContent='갱신된 설명';assert.equal(popups[1].children.at(-1).textContent,'갱신된 설명');
doc.emit('click',{target:live});assert(isOpen(1));doc.emit('click',{target:new Element()});assert(!isOpen(1));
buttons[1].emit('click');buttons[1].emit('click');assert(!isOpen(1),'second tap closes');
buttons[0].focus();const close=popups[0].children[0].children[1];doc.activeElement=close;
doc.emit('keydown',{key:'Escape',preventDefault:()=>{},stopPropagation:()=>{}});assert(!isOpen(0));assert.equal(doc.activeElement,buttons[0],'Escape restores button focus without reopening');
buttons[0].emit('click');doc.activeElement=close;close.emit('click');assert(!isOpen(0));assert.equal(doc.activeElement,buttons[0]);
// Wiring uses unique live IDs, no markup copies; critical statuses stay outside help.
const html=fs.readFileSync(require.resolve('../results/dashboard/chart-first.html'),'utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);assert.equal(new Set(ids).size,ids.length,'duplicate DOM IDs');
for(const match of html.matchAll(/data-help="([^"]+)"/g))assert(html.includes(`class="helpContent" id="${match[1]}"`));
for(const id of ['entryTitle','entryRisk','indicatorStatus','priceIndicatorStatus','monitorError','patternStatus'])assert(ids.includes(id));
assert(html.includes('src="context-help.js"'));assert(!html.includes('Lightweight Charts 복원'));
// Run the actual entry renderer: the main price remains visible and its full calculation stays in help.
const vm=require('node:vm'),elements=new Map();
const el=id=>{if(!elements.has(id)){const item=new Element(id);item.replaceChildren=(...xs)=>{item.children=xs;};item.appendChild=x=>item.children.push(x);elements.set(id,item);}return elements.get(id);};
const ctx={document:{getElementById:el,createElement:()=>{const item=new Element();item.appendChild=x=>item.children.push(x);return item;},addEventListener:()=>{}},fmtP:n=>n+'원',fmtT:String,fmtClock:String};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/entry-panel.js'),'utf8'),ctx);
ctx.entryEvaluation=()=>({code:'candidate',label:'진입 검토',reason:'조건 충족',modeMessage:'확정봉',fetchedAt:'2026-10-06',basis:'2026-10-05',observationBasis:'2026-10-05',setup:'F',selected:['F'],mode:'all',chaseLimit:105,signalAge:1,anchorTime:'2026-10-04',maxAtr:.5,referenceType:'breakout',rows:[]});
ctx.renderEntryPanel({});assert.equal(el('entryRisk').textContent,'추격 주의선 105원 · 신호 1봉 경과');assert.match(el('entryRiskHelp').textContent,/돌파 기준선.*0.5 ATR/);assert.match(el('entryRiskHelp').textContent,/매수 목표가·손절가는 아니/);
ctx.entryEvaluation=()=>null;ctx.renderEntryPanel(null);assert.equal(el('entryPanel').dataset.state,'blocked');assert.equal(el('entryRisk').textContent,'');assert.equal(el('entryRiskHelp').textContent,'');
console.log('Context help: viewport placement, hover, keyboard, tap, dismiss, live content and HTML wiring passed');
