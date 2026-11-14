'use strict';
// 격리된 VM·가상 시계만 사용한다. 서버·공급처·개인 저장소에 접근하지 않는다.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=name=>fs.readFileSync(require.resolve('../results/dashboard/'+name),'utf8');
const {FIELDS}=require('../results/dashboard/pattern-async');
const fetched='2026-11-14T01:00:00.000Z';
const analysis=(symbol='TEST',tf='D',status='computing')=>({enabled:true,symbol,timeframe:tf,sourceStatus:status,sourceFetchedAt:fetched,dataRevision:'r1',provisionalEligible:true,
 timeline:[{barTime:'2026-11-13',confirmed:true,status:'ready',patterns:[{patternId:'old',type:'bull-flag',status:'confirmed',barTime:'2026-11-13'}],levels:[{type:'prior-20-high',status:'confirmed',barTime:'2026-11-13'}]}],
 recentEvents:[{eventId:'old',confirmedBarTime:'2026-11-13'}],patterns:[{patternId:'old'}],events:[{eventId:'old'}]});
function frame(symbol='TEST',tf='D',id='job1'){
 const f={symbol,timeframe:tf,source:'yfinance',dataRevision:'r1',snapshotId:'s1',fetchedAt:fetched,confirmed:false,
  candles:[{time:'2026-11-13',close:10},{time:'2026-11-14',close:11}],state:[1,2],marks:{F:[1]},patternJob:{id,state:'pending',retryAfterMs:300}};
 for(const key of FIELDS)f[key]=analysis(symbol,tf);
 return f;
}
class Element{
 constructor(){this.children=[];this.dataset={};this.value='';this.textContent='';this.hidden=false;this.parentNode=null;}
 replaceChildren(...items){this.children=items;}append(...items){this.children.push(...items);}
 setAttribute(k,v){this[k]=v;}addEventListener(){}
 insertBefore(el){this.append(el);el.parentNode=this;}
}
function harness(){
 let now=Date.parse(fetched),nextId=1;const timers=new Map(),intervals=[],listeners={},requests=[],elements=new Map();
 const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const parent=new Element();get('chartWrap').parentNode=parent;
 let daily=frame(),intra=null;
 const ctx={console,AbortController,PatternWindow:require('../results/dashboard/pattern-window'),
  Date:class extends Date{static now(){return now;}},
  S:{symbol:'TEST',tf:'D',selectedAsOf:null,autoRef:true,lastErr:null,refreshing:false,preset:'custom'},
  reqSeq:0,API:'',serverMode:true,navigator:{onLine:true},
  curSym:()=>daily,frameOf:()=>ctx.S.tf==='D'?daily:['W','M'].includes(ctx.S.tf)?daily[ctx.S.tf]:intra,
  document:{hidden:false,getElementById:get,createElement:()=>new Element(),addEventListener:(k,f)=>(listeners[k]||=[]).push(f)},
  addEventListener:(k,f)=>(listeners[k]||=[]).push(f),
  setTimeout:(fn,ms)=>{const id=nextId++;timers.set(id,{fn,at:now+ms});return id;},clearTimeout:id=>timers.delete(id),
  setInterval:fn=>{intervals.push(fn);return intervals.length;},
  chart:{},candles:{},syncStructureEvidenceLines(){},
  PatternOverlay:{create:()=>({set(){}}),choose:()=>null},
  renderAll(){throw Error('원 차트 다시 그리기 금지');},renderMarkers(){throw Error('원신호 갱신 금지');},refreshLive(){throw Error('시세 조회 금지');},
  fetch:(url,opt)=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});requests.push({url,opt,resolve,reject});return promise;}};
 ctx.window=ctx;vm.createContext(ctx);
 for(const name of ['chart-timing','pattern-panel','flag-panel','triangle-panel','structure-panel','structure-evidence-panel','pattern-async'])vm.runInContext(source(name+'.js'),ctx,{filename:name+'.js'});
 for(const fn of listeners.DOMContentLoaded)fn();
 const tick=()=>ctx.PatternAsync.tick();
 const advance=ms=>{now+=ms;for(const [id,t] of [...timers])if(t.at<=now){timers.delete(id);t.fn();}tick();};
 const event=key=>{for(const fn of listeners[key]||[])fn();};
 async function settle(){for(let i=0;i<8;i++)await Promise.resolve();}
 async function reply(index,data,status=200){requests[index].resolve({ok:status>=200&&status<300,status,json:async()=>data});await settle();}
 const identity=f=>({symbol:f.symbol,timeframe:f.timeframe,source:f.source,dataRevision:f.dataRevision,snapshotId:f.snapshotId,fetchedAt:f.fetchedAt});
 const ready=(f=daily)=>({id:f.patternJob.id,state:'ready',identity:identity(f),fields:Object.fromEntries(FIELDS.map(key=>[key,{enabled:true,symbol:f.symbol,timeframe:f.timeframe,sourceStatus:'ready',dataRevision:f.dataRevision,sourceFetchedAt:f.fetchedAt,provisionalEligible:true,
  timeline:[{barTime:'2026-11-13',confirmed:true,status:'ready',patterns:[],levels:[]},{barTime:'2026-11-14',confirmed:false,status:'ready',patterns:[{patternId:'new',type:key==='triangleAnalysis'?'ascending-triangle':'bull-flag',status:'breakout-pending',barTime:'2026-11-14'}],levels:[{type:'prior-20-high',status:'breakout-pending',barTime:'2026-11-14'}]}],recentEvents:[],patterns:[],events:[]}]))});
 return {ctx,get,tick,advance,event,requests,reply,ready,identity,settle,daily:()=>daily,setDaily:f=>{daily=f;},setIntra:f=>{intra=f;}};
}
(async()=>{
 let cases=0;
 {
  const h=harness(),f=h.daily(),original=JSON.stringify(Object.fromEntries(Object.entries(f).filter(([key])=>!FIELDS.includes(key))));
  assert.match(h.get('patternComputeStatus').textContent,/차트 표시 완료.*패턴 계산 중/);
  for(const panel of ['PatternPanel','FlagPanel','TrianglePanel','StructurePanel','StructureEvidencePanel']){
   const v=h.ctx[panel].current();assert.equal(v.status,'computing');assert.equal((v.levels||v.patterns).length,0);assert.equal(v.events.length,0);assert.equal(v.pastPatterns?.length||0,0);
  }
  h.advance(299);assert.equal(h.requests.length,0);h.advance(1);h.tick();assert.equal(h.requests.length,1,'겹친 요청 금지');
  assert.equal(h.requests[0].url,'api/pattern-jobs?id=job1');
  const data=h.ready();data.fields.candles=['금지'];data.fields.state=['금지'];data.fields.fetchedAt='금지';
  const token=f.patternJob;
  await h.reply(0,data);assert.equal(h.get('patternComputeStatus').hidden,true);
  assert.equal(f.patternJob,token);assert.equal(token.state,'ready');
  assert.equal(JSON.stringify({...Object.fromEntries(Object.entries(f).filter(([key])=>!FIELDS.includes(key))),patternJob:{...f.patternJob,state:'pending'}}),original);
  assert.equal(h.ctx.FlagPanel.current().patterns[0].status,'breakout-pending');
  h.ctx.S.autoRef=false;assert.equal(h.ctx.FlagPanel.current().patterns[0].status,'paused');
  h.ctx.S.selectedAsOf='2026-11-13';assert.equal(h.ctx.FlagPanel.current().status,'ready');cases++;
 }
 {
  const h=harness();h.ctx.S.autoRef=false;h.advance(300);await h.reply(0,h.ready());
  assert.equal(h.daily().flagAnalysis.sourceStatus,'ready','자동갱신 OFF에서도 계산 수신');assert.equal(h.ctx.FlagPanel.current().patterns[0].status,'paused');cases++;
 }
 for(const change of ['symbol','timeframe','source','dataRevision','snapshotId','fetchedAt','frame','job','refresh','offline','hidden','server']){
  const h=harness(),old=h.daily(),data=h.ready();h.advance(300);
  if(change==='symbol'){h.ctx.S.symbol='OTHER';h.setDaily(frame('OTHER','D','job2'));}
  else if(change==='timeframe'){h.ctx.S.tf='H4';h.setIntra(frame('TEST','H4','job2'));}
  else if(['source','dataRevision','snapshotId','fetchedAt'].includes(change))old[change]+='-corrected';
  else if(change==='frame')h.setDaily(frame());
  else if(change==='job')old.patternJob={id:'job2',state:'pending'};
  else if(change==='refresh'){h.ctx.reqSeq++;h.ctx.S.refreshing=true;}
  else if(change==='offline')h.ctx.navigator.onLine=false;
  else if(change==='hidden')h.ctx.document.hidden=true;
  else h.ctx.serverMode=false;
  h.tick();assert.equal(h.requests[0].opt.signal.aborted,true,change+' 취소');
  await h.reply(0,data);assert.equal(old.flagAnalysis.sourceStatus,'computing',change+' 늦은 응답 격리');cases++;
 }
 for(const tf of ['W','M']){
  const h=harness();h.ctx.S.tf=tf;h.tick();h.advance(5000);assert.equal(h.requests.length,0);cases++;
 }
 {
  const h=harness(),daily=h.daily(),intra=frame('TEST','M5','intra-job');h.setIntra(intra);h.ctx.S.tf='M5';h.tick();h.advance(300);await h.reply(0,h.ready(intra));
  assert.equal(intra.flagAnalysis.sourceStatus,'ready');assert.equal(daily.flagAnalysis.sourceStatus,'computing');assert.equal(h.ctx.FlagPanel.current().patterns[0].patternId,'new');cases++;
 }
 {
  const h=harness();h.advance(300);h.ctx.document.hidden=true;h.event('visibilitychange');await h.reply(0,h.ready());
  assert.equal(h.daily().flagAnalysis.sourceStatus,'computing');assert.equal(h.get('patternComputeStatus').hidden,true);
  h.ctx.document.hidden=false;h.event('visibilitychange');assert.equal(h.requests.length,2);await h.reply(1,h.ready());assert.equal(h.daily().flagAnalysis.sourceStatus,'ready');cases++;
 }
 {
  const h=harness();h.advance(300);await h.reply(0,{},404);assert.equal(h.daily().flagAnalysis.sourceStatus,'error');assert.equal(h.daily().patternJob.state,'error');assert.match(h.get('patternComputeStatus').textContent,/계산 오류/);
  h.advance(90000);assert.equal(h.requests.length,1);assert.equal(h.ctx.FlagPanel.current().pastPatterns.length,0);cases++;
 }
 for(const key of ['symbol','timeframe','source','dataRevision','snapshotId','fetchedAt','id']){
  const h=harness();h.advance(300);
  for(let i=0;i<3;i++){
   const data=h.ready();if(key==='id')data.id='stale';else data.identity[key]+='-stale';await h.reply(i,data);if(i<2)h.advance(1500);
  }
  assert.equal(h.daily().patternAnalysis.sourceStatus,'error',key+' 동일성 검사');assert.equal(h.requests.length,3);h.advance(10000);assert.equal(h.requests.length,3);cases++;
 }
 {
  const h=harness();h.advance(300);const pending={id:'job1',state:'pending',identity:h.identity(h.daily())};
  for(let i=0;i<5;i++){await h.reply(i,pending);h.advance(1500);}
  h.advance(60000);assert.equal(h.daily().structureAnalysis.sourceStatus,'error');assert.match(h.get('patternComputeStatus').textContent,/시간 초과/);
  await h.reply(5,h.ready());assert.equal(h.daily().structureAnalysis.sourceStatus,'error');cases++;
 }
 {
  const h=harness();h.advance(300);h.ctx.document.hidden=true;h.event('visibilitychange');h.advance(61000);
  assert.equal(h.daily().flagAnalysis.sourceStatus,'computing','숨김 중 오류 필드 변경 금지');h.ctx.document.hidden=false;h.event('visibilitychange');assert.equal(h.daily().flagAnalysis.sourceStatus,'error');cases++;
 }
 {
  const h=harness();h.advance(300);const data=h.ready();delete data.fields.structureAnalysis;
  for(let i=0;i<3;i++){await h.reply(i,data);if(i<2)h.advance(1500);}
  for(const key of FIELDS)assert.equal(h.daily()[key].sourceStatus,'error','누락 필드가 있으면 일부 결과만 게시하지 않음');cases++;
 }
 {
  const h=harness();h.advance(300);await h.reply(0,{id:'job1',state:'error',identity:h.identity(h.daily())});
  for(const panel of ['PatternPanel','FlagPanel','TrianglePanel','StructurePanel','StructureEvidencePanel']){
   const v=h.ctx[panel].current();assert.equal(v.status,'error');assert.equal((v.levels||v.patterns).length,0);assert.equal(v.events.length,0);
  }
  h.advance(90000);assert.equal(h.requests.length,1);cases++;
 }
 {
  const h=harness();h.advance(300);
  for(let i=0;i<3;i++){
   h.requests[i].reject(Error('격리 통신 오류'));await h.settle();if(i<2)h.advance(1500);
  }
  assert.equal(h.daily().patternJob.state,'error');h.advance(15000);assert.equal(h.requests.length,3);cases++;
 }
 {
  const h=harness(),old=h.daily(),data=h.ready();h.advance(300);h.ctx.S.tf='W';
  await h.reply(0,data);assert.equal(old.patternJob.state,'pending','다음 250ms 확인 전에도 선택 변경 거부');assert.equal(old.flagAnalysis.sourceStatus,'computing');cases++;
 }
 {
  const h=harness();h.daily().patternAnalysis.sourceStatus='unsupported';h.advance(300);await h.reply(0,{},404);
  assert.equal(h.daily().patternAnalysis.sourceStatus,'unsupported','미지원 기능은 작업 오류로 바꾸지 않음');cases++;
 }
 console.log('비동기 패턴 VM 검사 '+cases+'건 통과: 경쟁·정정·숨김·시간 제한·가격 불변·기존 잠정 게이트');
})().catch(error=>{console.error(error);process.exitCode=1;});
