'use strict';
/* Explicit context evaluation: combines ChartTiming.assess and EntryModel.evaluate without reading DOM/S.
   Returns null when there are no candles. The judgment index time is preserved as observationBasis.
   When not historical and the market is closed, selects the lastConfirmedTime index; if no matching
   candle exists, evaluates -1 as-is (blocked) rather than substituting the latest candle. */
function evaluateEntryFrame({frame,index=frame?.candles?.length-1,symbol,tf,historical=false,selected=['F'],mode='all',maxAtr=.5,quote=null,lastError=null,enabled=true,now=Date.now()}){
 if(!frame||!frame.candles?.length)return null;
 const cs=frame.candles;
 let idx=index;
 if(!historical&&frame.marketSession?.state==='closed'){
  idx=cs.findIndex(c=>c.time===frame.lastConfirmedTime);
 }
 const basis=cs[idx]?.time;
 const confirmed=frame.lastConfirmedTime!=null&&basis===frame.lastConfirmedTime&&cs.some(c=>c.time===frame.lastConfirmedTime);
 const timing=ChartTiming.assess({symbol,tf,historical,basis,quote,source:frame.source,barAsOf:frame.barAsOf||null,now,
  marketSession:frame.marketSession,fetchedAt:frame.fetchedAt,snapshotEligible:frame.snapshotEligible,
  confirmed,lastError,enabled});
 const result=EntryModel.evaluate({frame,index:idx,selected,mode,maxAtr,timing,historical});
 return {...result,index:idx,observationBasis:basis,fetchedAt:frame.fetchedAt,source:frame.source};
}
/* Shared strategy-family adapter for the chart and latest-only watchlist. */
function evaluateEntryContext({family='legacy',lowSelected=['R','H'],...context}) {
 const out=family==='low'?LowEntryContext.evaluate({...context,selected:lowSelected})?.decision:evaluateEntryFrame(context);
 if(!out)return null;
 const settingsId=JSON.stringify([family,out.selected.slice().sort(),family==='low'?'any':context.mode||'all',context.maxAtr??.5]);
 return {...out,family,settingsId};
}
/* Current chart adapter: preserves the original entryEvaluation(obs) signature and observationBasis. */
function entryEvaluation(obs=currentObs()) {
 if(!obs)return null;
 const historical=!!(S.selectedAsOf&&S.selectedAsOf!==latestTime(obs.f));
 const out=evaluateEntryContext({family:S.entryFamily||'legacy',lowSelected:S.lowStrategies||['R','H'],frame:obs.f,index:obs.oi,symbol:S.symbol,tf:S.tf,historical,
  selected:S.entryStrategies||['F'],mode:S.entryMode||'all',maxAtr:S.entryMaxAtr||.5,
  quote:window.__tossQuote?.(),lastError:S.lastErr,enabled:S.autoRef&&!document.hidden,now:Date.now()});
 if(!out)return null;
 return {...out,observationBasis:obs.model.observationAsOf};
}
function renderEntryPanel(obs) {
 if(typeof window!=='undefined')window.LowStructurePanel?.render();
 const out=entryEvaluation(obs),box=document.getElementById('entryPanel');
 if(!box)return;
 if(!out){
  box.dataset.state='blocked';
  box.dataset.decision='blocked';
  document.getElementById('entryTitle').textContent='자료 없음 · 판단 보류';
  document.getElementById('entryReason').textContent='선택한 주기의 자료가 필요해요.';
  for(const id of ['entrySetup','entryRisk','entryRiskHelp','entryConflict','entryDataStatus','entryDataDetails'])document.getElementById(id).textContent='';
  document.getElementById('entryCompare').replaceChildren();
  return;
 }
 box.dataset.state=out.code;
 // Historical mode keeps its identity; only presentation uses the selected bar's decision.
 const decision=out.code==='historical'?out.setupDecision:null;
 box.dataset.decision=decision?.code||(out.code==='historical'?'blocked':out.code);
 document.getElementById('entryTitle').textContent=out.code==='historical'?`당시 · ${decision?.label||out.label}`:out.label;
 document.getElementById('entryReason').textContent=out.code==='chase'&&out.family!=='low'?'추격 주의선을 넘었습니다. 새 조건을 기다리세요.':out.reason;
 document.getElementById('entryDataStatus').textContent=out.code==='historical'?'과거 봉':out.code==='blocked'?'자료 확인 필요':out.provisional?(out.family==='low'?'직전 확정봉 기준 · 새 봉 진행 중':'진행봉 · 잠정'):'확정봉 기준';
 document.getElementById('entryDataDetails').textContent=`${out.modeMessage} · 마지막 조회 ${fmtClock(out.fetchedAt)} · 공급처 지연 미확인`;
 const chartBasis=out.observationBasis!=null&&out.observationBasis!==out.basis?` · 차트 봉 ${fmtT(out.observationBasis)}`:'';
 document.getElementById('entrySetup').textContent=(out.family==='low'?`판단 봉 ${fmtT(out.basis)}`:`기준 ${fmtT(out.basis)} · ${out.setup}${out.continuation?` · 최초 신호 ${fmtT(out.anchorTime)}`:''}`)+chartBasis;
 const activeLowRisk=out.family==='low'&&['candidate','chase'].includes(out.setupDecision?.code);
 document.getElementById('entryRisk').textContent=out.family==='low'?activeLowRisk&&out.chaseLimit!=null?`매수 상한 ${fmtP(out.chaseLimit)} · 신호 후 ${out.signalAge}봉`:'새 신호 확인 후 매수 상한 표시':out.chaseLimit!==null?`추격 주의선 ${fmtP(out.chaseLimit)} · 신호 ${out.signalAge}봉 경과`:'추격 주의선 — 조건 대기';
 document.getElementById('entryRiskHelp').textContent=out.family==='low'&&!activeLowRisk?
  '이전 신호의 가격 상한은 지금 매수 기준으로 쓰지 않아요. 새 신호가 확인되면 그때의 가격과 변동 폭으로 다시 계산합니다.':out.chaseLimit!==null?
  `추격 주의선 ${fmtP(out.chaseLimit)} · 최초 신호 ${fmtT(out.anchorTime)} ${out.referenceType==='breakout'?'돌파 기준선':'종가'} + ${out.maxAtr} ATR · ${out.signalAge}봉 경과. 매수 목표가·손절가는 아니에요.`:
  '조건이 충족되면 신호 발생봉 기준 추격 주의선을 계산해요. 신호 발생 전에는 진입 가격을 제시하지 않아요.';
 document.getElementById('entryConflict').textContent=out.combinationNote||'조합은 조건 비교용이에요. 신호 개수는 승률이 아니며, 수익률 비교를 검증한 조합은 아니에요.';
 document.getElementById('entryCompare').replaceChildren();
 const breakout=document.getElementById('entryBreakoutKind').value||(out.selected.includes('C')&&!out.selected.includes('F')?'C':'F');
 for(const r of out.rows.filter(r=>out.family==='low'||['A','B',breakout].includes(r.id))){
  const row=document.createElement('tr');
  const phase=out.family==='low'?r.label:r.phase==='unavailable'?'자료 부족':r.phase==='tracking'?`신호 후 추적 ${r.signalAge}/3봉`:r.phase==='maintained'?'돌파 조건 유지':r.signal==='entry'?'새 신호'+(out.provisional?' (잠정)':''):r.signal==='exit'?'이탈 신호':r.signal==='missing'?'자료 없음':'조건 대기';
  for(const text of [out.family==='low'?r.name:['C','F'].includes(r.id)?`돌파 · ${r.name}`:`${r.id} · ${r.name}`,phase,r.readiness?.ready===false?`필요: ${r.readiness.missing.join(' · ')}`:r.id==='F'?r.rule.replace('C 돌파','직전 20봉 고점 돌파'):r.rule]){
   const cell=document.createElement('td');cell.textContent=text;row.appendChild(cell);
  }
  document.getElementById('entryCompare').appendChild(row);
 }
}
document.addEventListener('DOMContentLoaded',()=>{
 const updateSelection=()=>{
  S.entryStrategies=[...document.querySelectorAll('[name=entryStrategy]:checked')].map(x=>x.value);renderEntryPanel(currentObs());window.Watchlist?.render();
 };
 for(const el of document.querySelectorAll('[name=entryStrategy]'))el.addEventListener('change',updateSelection);
 document.getElementById('entryBreakoutKind').onchange=e=>{
  document.getElementById('entryBreakoutEnabled').value=e.target.value;updateSelection();
 };
 document.getElementById('entryMode').onchange=e=>{S.entryMode=e.target.value;renderEntryPanel(currentObs());window.Watchlist?.render();};
 document.getElementById('entryMaxAtr').onchange=e=>{S.entryMaxAtr=Number(e.target.value);renderEntryPanel(currentObs());window.LowStructurePanel?.render();renderMarkers();window.Watchlist?.render();};
 const family=document.getElementById('entryFamily');
 const syncFamily=()=>{
  const low=S.entryFamily==='low';
  document.getElementById('legacyStrategies').hidden=low;document.getElementById('lowStrategies').hidden=!low;
  document.getElementById('entryMode').disabled=low;const modeLabel=document.getElementById('entryMode').closest?.('label');if(modeLabel)modeLabel.hidden=low;
  const controls=document.getElementById('entryControls');if(controls)controls.dataset.family=low?'low':'legacy';
  const legacyHelp=document.getElementById('entrySettingsLegacy'),lowHelp=document.getElementById('entrySettingsLow');if(legacyHelp)legacyHelp.hidden=low;if(lowHelp)lowHelp.hidden=!low;
  renderEntryPanel(currentObs());window.LowStructurePanel?.render();if(typeof renderMarkers==='function')renderMarkers();window.Watchlist?.render();
 };
 if(family?.value){family.onchange=e=>{S.entryFamily=e.target.value;syncFamily();};
 for(const el of document.querySelectorAll('[name=lowStrategy]'))el.addEventListener('change',()=>{S.lowStrategies=[...document.querySelectorAll('[name=lowStrategy]:checked')].map(x=>x.value);syncFamily();});syncFamily();}
 document.getElementById('signalStrategy').onchange=e=>{S.signalStrategy=e.target.value;renderMarkers();paintSelLine();};
 renderEntryPanel(currentObs());
});
