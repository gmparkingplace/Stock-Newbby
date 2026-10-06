(function(root,factory){
 if(typeof module==='object'&&module.exports)module.exports=factory(require('./low-structure-rules.js'));
 else root.LowEntryModel=factory(root.LowStructureRules);
})(typeof self!=='undefined'?self:this,function(Rules){
 'use strict';
 const names={R:'저점 회복',H:'저점 상승'};
 // Presentation vocabulary only. Engine phases, reasons, IDs and thresholds stay unchanged.
 function describe(structure,parameters=Rules.defaults){
  if(!structure)return {label:'저점 확인을 기다리세요',reason:'선택한 방식에 맞는 저점과 반등이 아직 확인되지 않았어요.',rowLabel:'확인된 저점 없음'};
  const p={...Rules.defaults,...parameters},phase=structure.phase,raw=structure.reason;
  const stages={
   breached:{label:'지지 가격 회복을 기다리세요',reason:'이전 저점 아래로 내려왔어요. 종가가 지지 구간 위로 돌아오는지 확인하세요.',rowLabel:'지지 가격 회복 대기'},
   reclaimed:{label:'다시 눌릴 때 지지를 확인하세요',reason:'지지 가격을 회복했어요. 다시 내려올 때 회복 당시 저점을 지키는지 확인하세요.',rowLabel:'다시 눌려도 저점을 지키는지 확인'},
   tested:{label:'반등 고점 돌파를 기다리세요',reason:'다시 눌린 저점을 확인했어요. 종가가 반등 기준 위에서 마감하는지 확인하세요.',rowLabel:'저점 지지 확인 · 반등 돌파 대기'},
   rising:{label:'저점은 높아졌어요 · 돌파 대기',reason:'새 저점이 이전보다 높아요. 두 저점 사이의 반등 고점을 종가가 넘는지 확인하세요.',rowLabel:'높아진 저점 확인 · 반등 돌파 대기'},
   ready:{label:'진입 검토',reason:'저점 확인 후 반등 기준을 종가가 넘었어요.',rowLabel:'저점 확인 · 반등 돌파 충족'},
   superseded:{label:'새 저점을 확인하고 있어요',reason:'더 최근에 확인된 저점을 기준으로 다시 살펴봅니다.',rowLabel:'새 저점으로 기준 변경'},
  };
  if(phase==='invalidated'){
   const causes={
    '고정 무효선 이탈':['지지선 이탈 · 매수 대기','확정봉의 저가가 정해 둔 지지 하한선 아래로 내려왔어요.','지지 하한선 아래로 하락'],
    '회복 당시 저점 재이탈':['저점 재이탈 · 매수 대기','확정봉의 저가가 회복 당시 저점 아래로 다시 내려왔어요.','회복했던 저점을 다시 이탈'],
    '깊은 이탈 · 해당 전략 제외':['하락 폭이 큼 · 매수 대기','지지 가격 아래로 내려간 폭이 허용 범위를 넘었어요.','지지 아래 하락 폭이 큼'],
    '저점 확인 전에 무효선 이탈':['지지선 이탈 · 매수 대기','저점을 확인하는 동안 가격이 지지 하한선 아래로 내려왔어요.','저점 확인 중 지지선 이탈'],
    '반등 기준 아래로 종가 복귀':['반등 약해짐 · 매수 대기','확정 종가가 돌파했던 반등 기준 아래로 돌아왔어요.','돌파 기준 아래로 다시 마감'],
    '가격 자료 단절 · 구조 종료':['가격 자료를 다시 확인하세요','봉 자료가 끊겨 저점과 반등을 이어서 확인할 수 없어요.','가격 자료 연결 끊김'],
   };
   const cause=causes[raw];return {label:cause?.[0]||'매수 근거가 사라졌어요',reason:(cause?.[1]||'이전 저점의 지지가 유지되지 않았어요.')+(raw==='가격 자료 단절 · 구조 종료'?'':' 새 저점과 반등을 기다리세요.'),rowLabel:cause?.[2]||'저점 지지 확인 중단'};
  }
  if(phase==='expired'){
   const causes={
    '회복 기한 초과':[`이탈 봉부터 ${p.reclaimBars}봉 안에 지지 가격을 회복하지 못했어요.`,'지지 회복 시간 경과'],
    '재시험 확인 기한 초과':[`회복 후 ${p.retestBars}봉 안에 저점을 다시 지키는 모습이 확인되지 않았어요.`,'다시 눌린 저점 확인 안 됨'],
    '반등 돌파 대기 기한 초과':[`저점 확인 봉부터 ${p.triggerBars}봉 안에 반등 고점을 넘지 못했어요.`,'반등 고점 돌파 안 됨'],
    '신호 후 검토 기한 초과':[`이전 매수 신호의 확인 기간(발생봉과 이후 ${p.reviewBars}봉)이 끝났어요.`,'이전 매수 신호 확인 기간 종료'],
   };
   const cause=causes[raw];return {label:'새 매수 신호를 기다리세요',reason:cause?.[0]||'이전 저점에서 기다리던 매수 확인 기간이 끝났어요.',rowLabel:cause?.[1]||'이전 확인 기간 종료'};
  }
  return stages[phase]||{label:'저점 확인을 기다리세요',reason:'저점과 반등을 확인하고 있어요.',rowLabel:'저점 확인 대기'};
 }
 function evaluate({analysis,selected=['R','H'],timing,historical=false,provisional=false}={}){
  const ids=[...new Set(selected)].filter(id=>names[id]),rows=ids.map(id=>{
   const s=analysis?.current?.[id],copy=describe(s,analysis?.parameters);let code='wait',label=copy.rowLabel;
   if(!analysis||!['ready','insufficient-data'].includes(analysis.status)){code='blocked';label=analysis?.status==='unsupported'?'지원 준비 중':'자료 확인 필요';}
   else if(s?.phase==='invalidated'){code='avoid';label=copy.rowLabel;}
   else if(s?.phase==='ready'){
    const index=analysis.confirmedIndex??analysis.series.findLastIndex(b=>b.confirmed),price=analysis.price;
    code=typeof price==='number'&&price>s.chaseLimit?'chase':'candidate';label=code==='chase'?'추격 주의':'진입 검토';
    if(index-s.signalIndex>analysis.parameters.reviewBars){code='wait';label='이전 매수 신호 확인 기간 종료';}
   }else if(s){label=copy.rowLabel;}
   if(analysis?.status==='insufficient-data'){code='blocked';label='가격/ATR 준비 중';}
   return {id,name:names[id],signal:code==='candidate'?'entry':code==='avoid'?'exit':'none',phase:s?.phase||'wait',code,label,
    rule:id==='R'?'이전 저점 위로 회복 → 다시 눌려도 저점 유지 → 반등 고점 위 마감':'이전보다 높은 저점 → 중간 반등 고점 위 마감',structure:s||null,description:copy};
  });
  const hasWaiting=rows.some(r=>r.code==='wait'&&r.structure&&!['expired','superseded'].includes(r.structure.phase));
  const rank=r=>r.code==='candidate'?0:r.code==='wait'&&r.structure&&!['expired','superseded'].includes(r.structure.phase)?1:
   r.code==='chase'?(hasWaiting?2:1):r.code==='avoid'?3:r.code==='wait'?3.5:4;
  const ordered=rows.slice().sort((a,b)=>rank(a)-rank(b)||
   (b.structure?.testKnownIndex??b.structure?.knownIndex??-1)-(a.structure?.testKnownIndex??a.structure?.knownIndex??-1)||(a.id==='H'?-1:b.id==='H'?1:0));
  const best=ordered[0],s=best?.structure;let code=best?.code||'blocked';
  let label=code==='candidate'?`${best.name} · 진입 검토`:code==='chase'?'가격이 많이 올랐어요 · 매수 대기':code==='blocked'?best?.label||'전략을 선택하세요':best.description.label;
  let reason=code==='candidate'?best.description.reason:code==='chase'?'최초 신호에서 정한 매수 상한을 넘었어요. 가격을 따라가기보다 새 신호를 기다리세요.':code==='blocked'?best?.label||'저점 매수 방식을 하나 이상 선택하세요.':best.description.reason;
  const setupDecision={code,label,reason};
  if(historical){code='historical';label='당시 조건 비교';reason='선택한 과거 봉의 결과예요. 현재 진입 안내가 아니에요.';}
  else if(!timing?.judgmentReady){code='blocked';label='진입 판단 보류';reason=timing?.message||'자료 시각을 확인하지 못했습니다.';}
  else if(provisional&&code==='candidate'){code='wait';label='봉 확정 대기';reason='현재 봉은 잠정입니다. 확정된 가격을 확인하세요.';}
  return {version:Rules.version,code,label,reason,setupDecision,rows,selected:ids,structureId:s?.id||null,
   basis:analysis?.basis||null,setup:best?.label||'조건 대기',anchorTime:s?.signalAt||null,signalAge:s?.signalIndex!=null?(analysis.confirmedIndex??analysis.series.findLastIndex(b=>b.confirmed))-s.signalIndex:null,
   chaseLimit:s?.chaseLimit??null,maxAtr:analysis?.parameters?.maxAtr??.5,referenceType:'signal-close',provisional,
   family:'low',modeMessage:timing?.message||'',matched:best?.code==='candidate',combinationNote:'선택한 저점 매수 방식 중 하나만 충족해도 검토합니다. 같은 저점의 신호가 겹쳐도 확인 횟수를 더하지 않아요.'};
 }
 return {evaluate,names,describe};
});
