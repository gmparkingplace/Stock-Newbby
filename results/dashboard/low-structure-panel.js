/* Presentation only: shared context computes every judgment; no provider calls. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory(require('./pattern-window'));else root.LowStructureView=factory(root.PatternWindow);})(typeof self!=='undefined'?self:this,function(Window){
 'use strict';
 function visible(analysis){const from=Window.start(analysis?.observedThrough);return (analysis?.structures||[]).filter(s=>from!=null&&s.startedAt>=from);}
 function choose(structures,decision,selected,choice='auto'){
  const manual=choice!=='auto'?structures.find(s=>s.id===choice):null;
  if(manual)return {structure:manual,manual:true};
  const eligible=structures.filter(s=>selected.includes(s.family));
  return {structure:eligible.find(s=>s.id===decision.structureId)||eligible.filter(s=>!['invalidated','expired','superseded'].includes(s.phase)).at(-1)||null,manual:false};
 }
 function markers(s){
  if(!s)return [];
  const points=s.family==='H'?[[s.anchorTimes[0],'저점 1',s.knownAt],[s.testTime,'높아진 저점',s.testKnownAt]]:
   [[s.anchorTimes[0],'기준 지지',s.supportKnownAt],[s.springTime,'이탈·회복 저점',s.recoveredAt],[s.testTime,'재시험 저점',s.testKnownAt]];
  const result=points.filter(([time])=>time!=null).map(([time,text,known])=>({time,position:'belowBar',shape:'circle',color:'#64748b',size:1,text:`${text} (확인 ${Window.format(known)||'대기'})`}));
  if(s.signalAt!=null)result.push({time:s.signalAt,position:'aboveBar',shape:'arrowUp',color:'#17644c',size:1,text:'저점 구조 · 확정 조건 충족'});
  return result;
 }
 function geometry(s){if(!s)return [];
  const points=s.family==='H'?[{time:s.anchorTimes[0],price:s.previousLow},{time:s.testTime,price:s.testPrice}]:
   [{time:s.anchorTimes[0],price:s.supportPrice},{time:s.springTime,price:s.springLow},...(s.testTime?[{time:s.testTime,price:s.testPrice}]:[])];
  return points.filter(p=>p.time!=null&&Number.isFinite(p.price));
 }
 return {visible,choose,markers,geometry};
});
if(typeof window!=='undefined'&&typeof document!=='undefined')(() => {
 'use strict';
 const $=id=>document.getElementById(id);let choice='auto',model=null,selected=null,overlay=null,raf=0;
 function current(){
  const frame=frameOf(curSym());if(!frame?.candles?.length)return null;
  const historical=!!(S.selectedAsOf&&S.selectedAsOf!==latestTime(frame));
  const x=LowEntryContext.evaluate({frame,index:asOfIdx(),symbol:S.symbol,tf:S.tf,historical,selected:S.lowStrategies||['R','H'],
   maxAtr:S.entryMaxAtr||.5,quote:window.__tossQuote?.(),lastError:S.lastErr,enabled:S.autoRef&&!document.hidden,now:Date.now()});
  if(!x)return null;
  const structures=LowStructureView.visible(x.analysis);
  const selection=LowStructureView.choose(structures,x.decision,S.lowStrategies||['R','H'],choice),s=selection.structure;
  return {version:x.analysis.version,status:x.analysis.status,basis:x.analysis.basis,observedThrough:x.analysis.observedThrough,
   confirmedThrough:x.analysis.confirmedThrough,parameters:x.analysis.parameters,sourceRevision:x.analysis.sourceRevision,revision:x.analysis.revision||null,dataWarnings:x.analysis.dataWarnings,
   decision:x.decision,selected:s,manual:selection.manual,structures,events:(x.analysis.events||[]).filter(e=>structures.some(s=>s.id===e.structureId))};
 }
 function render(){
  model=current();selected=model?.selected||null;
  $('lowStructurePanel').hidden=S.entryFamily!=='low';
  const legend=$('lowMarkerLegend');if(legend)legend.hidden=S.entryFamily!=='low';
  $('lowStructureStatus').textContent=!model?'차트 자료 대기':model.status==='unsupported'?'일봉·코인 4시간봉에서 지원합니다.':model.status==='invalid-data'?'봉 자료 오류 · 저점 판단 보류':model.status==='unconfirmed'?'확정봉 확인 대기':selected?`${model.manual?'과거 구조 · 현재 판단과 별도 · ':''}${LowEntryModel.names[selected.family]} · ${LowEntryModel.describe(selected,model.parameters).rowLabel}`:'선택한 전략의 구조 없음 · 최근 3개월';
  const select=$('lowStructureChoice');select.replaceChildren();
  const add=(value,text)=>{const o=document.createElement('option');o.value=value;o.textContent=text;select.append(o);};
  add('auto','판단 기준 구조');for(const s of model?.structures||[])add(s.id,`${LowEntryModel.names[s.family]} · ${fmtT(s.knownAt)} · ${LowEntryModel.describe(s,model.parameters).rowLabel}`);
  if(choice!=='auto'&&!model?.structures.some(s=>s.id===choice))choice='auto';select.value=choice;
  const facts=$('lowStructureFacts');facts.replaceChildren();
  const ended=model?.manual||selected&&['invalidated','expired','superseded'].includes(selected.phase),prefix=ended?'이전 ':'';
  const items=[['판단 봉',model?fmtT(model.decision.basis):'—'],[prefix+'반등 확인 가격',selected?.triggerLevel!=null?fmtP(selected.triggerLevel):'대기'],
   [prefix+'지지 하한선',selected?.invalidationLevel!=null?fmtP(selected.invalidationLevel):'대기'],[prefix+'매수 상한',selected?.chaseLimit!=null?fmtP(selected.chaseLimit):'신호 대기']];
  for(const [label,value] of items){const card=document.createElement('div');card.className='lowFact';const title=document.createElement('span'),val=document.createElement('strong');title.textContent=label;val.textContent=value;card.append(title,val);facts.append(card);}
  const evidence=$('lowStructureEvidence');evidence.replaceChildren();
  for(const e of selected?.evidence||[]){const p=document.createElement('p');p.textContent=`${e.label}: ${e.result==='unknown'?'미확인':e.result==='supportive'?'참고 근거':'주의/미충족'}${e.observed!=null?' · '+Number(e.observed.toFixed(3)).toLocaleString('ko-KR'):''} · ${e.detail} · 기준 ${fmtT(e.basisTime)}`;evidence.append(p);}
  const extension=selected?.referencePrice!=null&&selected?.triggerLevel!=null?(selected.referencePrice-selected.triggerLevel)/selected.atrAnchor:0;
  const extended=extension>(S.entryMaxAtr||.5)?' · 최초 신호봉 급등 · 가격 위험 확인':'';
  const old=currentObs()?.st?.sigF==='exit'?' · 돌파 전략 이탈 조건도 확인됨':'';
  $('lowStructureNote').textContent=LowEntryModel.describe(selected,model?.parameters).reason+old+extended+(model?.revision?' · 원천 정정 · 재계산':'')+(S.entryFamily==='low'?'':' · 저점 매수 선택 시 차트에 표시');
  $('lowStructureSource').textContent=model?`${model.version} · ${model.decision.source||'저장 자료'} · 수집 ${fmtClock(model.decision.fetchedAt)} · 확정 기준 ${fmtT(model.confirmedThrough)} · 가격 조정 일관성 미확인`:'';
  schedule();
 }
 function active(){return S.entryFamily==='low'&&$('lowOverlayEnabled')?.checked&&selected;}
 function schedule(){if(!raf)raf=requestAnimationFrame(draw);}
 function draw(){
  raf=0;if(!overlay)return;overlay.replaceChildren();const s=active();if(!s)return;
  const host=$('chart'),w=host.clientWidth,h=host.clientHeight,right=chart.priceScale('right').width(),left=chart.priceScale('left').width(),height=h-chart.timeScale().height();
  overlay.setAttribute('viewBox',`0 0 ${w} ${h}`);
  const ns='http://www.w3.org/2000/svg',node=(tag,attrs,parent=overlay)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);parent.append(e);return e;};
  const defs=node('defs',{}),clip=node('clipPath',{id:'low-structure-plot'},defs);node('rect',{x:left,y:0,width:Math.max(0,w-right-left),height:Math.max(0,height)},clip);
  const group=node('g',{'clip-path':'url(#low-structure-plot)'}),xy=p=>({x:chart.timeScale().timeToCoordinate(p.time),y:candles.priceToCoordinate(p.price)});
  const points=LowStructureView.geometry(s).map(xy).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));
  if(points.length>=2)node('polyline',{points:points.map(p=>`${p.x},${p.y}`).join(' '),fill:'none',stroke:'#7c3aed','stroke-width':2},group);
  for(const [price,color,knownAt] of [[s.triggerLevel,'#17644c',s.testKnownAt||s.knownAt],[s.invalidationLevel,'#b45309',s.testKnownAt||s.recoveredAt||s.knownAt],[s.chaseLimit,'#64748b',s.signalAt]]){if(price==null)continue;const x=chart.timeScale().timeToCoordinate(knownAt),y=candles.priceToCoordinate(price);if(Number.isFinite(x)&&Number.isFinite(y))node('line',{x1:x,y1:y,x2:w-right,y2:y,stroke:color,'stroke-width':1.5,'stroke-dasharray':'5 4'},group);}
 }
 window.LowStructurePanel={current,render,selected:()=>selected,markers:()=>active()?LowStructureView.markers(selected):[]};
 document.addEventListener('DOMContentLoaded',()=>{
  $('lowStructureChoice').onchange=e=>{choice=e.target.value;render();renderMarkers();};$('lowOverlayEnabled').onchange=()=>{schedule();renderMarkers();};
  overlay=document.createElementNS('http://www.w3.org/2000/svg','svg');overlay.classList.add('lowStructureOverlay');overlay.setAttribute('aria-hidden','true');$('chart').append(overlay);
  chart.timeScale().subscribeVisibleLogicalRangeChange(schedule);chart.timeScale().subscribeVisibleTimeRangeChange(schedule);
  const resize=new ResizeObserver(schedule);resize.observe($('chart'));for(const type of ['pointermove','wheel','pointerup','dblclick'])$('chart').addEventListener(type,schedule,{passive:true});
  document.addEventListener('visibilitychange',render);render();renderMarkers();
 });
})();
