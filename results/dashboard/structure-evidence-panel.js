/* Parallel structure evidence (Schabacker principles). Server supplied; no recalculation. */
(function(){
  'use strict';
  const windowed=typeof module!=='undefined'&&module.exports?require('./pattern-window.js'):PatternWindow;
  const names={'double-top':'더블탑','double-bottom':'더블바텀','head-shoulders':'헤드앤숄더','inverse-head-shoulders':'역헤드앤숄더'};
  const states={candidate:'돌파 대기',confirmed:'돌파 확인',retesting:'기준선 재시험',holding:'재시험 후 유지',failed:'구조 무효',expired:'추적 종료',invalidated:'확인 전 무효'};
  const events={'candidate-detected':'후보 발견','breakout-confirmed':'종가 돌파 확인','retest-started':'기준선 재시험','retest-held':'재시험 후 유지','breakout-failed':'구조 무효','expired':'추적 종료','candidate-invalidated':'확인 전 무효','volume-supported':'거래량 동반 재돌파'};
  const term={failed:1,expired:1,invalidated:1};
  const SUPPORTED_RULE='structure-evidence-d-v1';
  const name=p=>names[p?.type]||'구조 패턴';
  const stateLabel=p=>states[p?.lifecycleState]||'상태 미상';
  const eventLabel=e=>events[e?.eventType]||e?.eventType||'사건';
  const volumeLabel=s=>({supported:'평균 이상',weak:'평균 이하',unknown:'자료 부족'})[s]||'자료 부족';
  const trendLabel=d=>({up:'상승',down:'하락',flat:'뚜렷하지 않음',unknown:'자료 부족'})[d]||'자료 부족';

  /* Past state is rebuilt from the events that had already happened. Copying the
     latest pattern and only swapping the label used to expose a later bar's
     volume, confirmation price and retest evidence. */
  function stateAt(pattern,asOf){
    if(!asOf||asOf>=pattern.evaluatedAt)return pattern;
    const events=(pattern.events||[]).filter(e=>e.effectiveBarTime<=asOf);
    if(!events.length)return null;
    const last=events[events.length-1],snapshot=last.snapshot||{};
    const confirmation=events.find(e=>e.eventType==='breakout-confirmed')||null;
    const breakout=confirmation?(confirmation.snapshot||{}):null;
    const evidence={...(pattern.evidence||{}),
      latestVolume:{ratio:snapshot.volumeRatio??null,status:snapshot.volumeStatus||'unknown'}};
    delete evidence.boostedAt;delete evidence.retestVolume;
    evidence.breakoutVolume=breakout
      ?{ratio:breakout.volumeRatio??null,status:breakout.volumeStatus||'unknown'}
      :null;
    return {...pattern,historical:true,lifecycleState:last.snapshot?.phaseAfter||pattern.lifecycleState,
      evaluatedAt:last.effectiveBarTime,barTime:last.effectiveBarTime,
      confirmedAt:confirmation?confirmation.effectiveBarTime:null,
      confirmedBarTime:confirmation?confirmation.effectiveBarTime:null,
      close:snapshot.close??null,
      neckline:{...pattern.neckline,atEvaluation:snapshot.neckline??null},
      triggerPriceAtEvaluation:snapshot.triggerPrice??null,
      triggerPriceAtEvent:breakout?(breakout.triggerPrice??null):null,
      invalidationPrice:snapshot.invalidationPrice??null,
      reasons:(snapshot.reasons||[]).map(r=>typeof r==='string'?{code:r,text:r}:r),
      evidence,events};
  }

  function view(analysis,tf,asOf,blocked){
    if(!analysis?.enabled)return {status:'disabled',patterns:[],events:[]};
    if(tf!=='D'||(analysis.timeframe&&analysis.timeframe!=='D')||analysis.sourceStatus==='unsupported')
      return {status:'unsupported',patterns:[],events:[],reason:analysis.reason};
    if(['computing','error'].includes(analysis.sourceStatus))return {status:analysis.sourceStatus,patterns:[],events:[]};
    if(analysis.ruleVersion&&analysis.ruleVersion!==SUPPORTED_RULE)
      return {status:'unsupported-version',patterns:[],events:[],ruleVersion:analysis.ruleVersion};
    const paused=Boolean(blocked||analysis.sourceStatus==='paused');
    const reference=analysis.evaluatedThrough;
    const patterns=(analysis.patterns||[])
      .filter(p=>!asOf||p.discoveredAt<=asOf)
      .filter(p=>windowed.within(p,reference))
      .map(p=>stateAt(p,asOf)).filter(Boolean)
      .map(p=>paused?{...p,paused:true}:p);
    const events=(analysis.events||[]).filter(e=>!asOf||e.effectiveBarTime<=asOf);
    // A paused source keeps the last valid history visible and stops only new
    // judgment; hiding the list would erase evidence the user already saw.
    if(paused)return {status:'paused',ruleVersion:analysis.ruleVersion,barTime:reference,patterns,events,paused:true};
    return {status:patterns.length?'ready':'insufficient-data',ruleVersion:analysis.ruleVersion,
      configId:analysis.configId,barTime:analysis.evaluatedThrough,patterns,events};
  }

  if(typeof module!=='undefined'&&module.exports){
    module.exports={view,stateAt,name,stateLabel,eventLabel,volumeLabel,trendLabel,names,states,events,SUPPORTED_RULE};return;
  }
  const $=id=>document.getElementById(id);
  let choice='auto',eventChoice=null,last='';
  const number=n=>n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:2});
  const pct=n=>n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:1})+'%';
  function current(){
    const f=frameOf(curSym()),a=curSym()?.structureEvidenceV2;
    const context=ChartTiming.patternContext({frame:f,analysis:a,selectedAsOf:S.selectedAsOf,lastError:S.lastErr,enabled:S.autoRef&&!document.hidden});
    return view(a,S.tf,context.asOf,context.blocked);
  }
  function signature(v){return JSON.stringify([S.symbol,S.tf,S.selectedAsOf,v.status,v.barTime,v.patterns.map(p=>[p.patternId,p.lifecycleState,p.historical||false])]);}
  function tick(){if(signature(current())!==last)render();}
  function selected(v){return v.patterns.find(p=>p.patternId===choice)||v.patterns.find(p=>!term[p.lifecycleState])||v.patterns[0]||null;}
  function render(){
    const v=current();last=signature(v);
    const panel=$('structureEvidencePanel');
    panel.hidden=v.status==='disabled';
    if(v.status==='disabled')return;
    $('structureEvidenceState').textContent=({
      unsupported:'이번 병행 평가는 주식 일봉만 지원합니다.',
      'unsupported-version':'이 화면과 서버의 규칙 버전이 달라 병행 근거를 숨겼습니다. 새로고침해 주세요.',
      paused:'자료 보류 · 새 판단을 멈췄습니다. 기존 진입 판단에는 반영하지 않습니다.',
      computing:'차트 표시 완료 · 병행 근거 계산 중…',
      error:'계산 오류 · 새 판단 보류',
      'insufficient-data':'확인된 후보가 아직 없습니다.'
    })[v.status]||`${PatternWindow.format(v.barTime)||'—'} 기준 · 후보 ${v.patterns.length}개 · 기존 진입 판단에는 미반영`;
    const select=$('structureEvidenceChoice');select.replaceChildren();
    const add=(value,text)=>{const o=document.createElement('option');o.value=value;o.textContent=text;select.append(o);};
    add('auto','최근 유효 구조');
    for(const p of v.patterns)add(p.patternId,`${name(p)} · ${stateLabel(p)}${p.historical?' · 과거':''}`);
    if(choice!=='auto'&&!v.patterns.some(p=>p.patternId===choice))choice='auto';
    select.value=choice;
    const cards=$('structureEvidenceCards');cards.replaceChildren();
    const pattern=selected(v);
    if(pattern){
      const evidence=pattern.evidence||{},trend=evidence.priorTrend||{},volume=evidence.breakoutVolume||{};
      const neckline=pattern.neckline?.flat?`목선 ${number(pattern.neckline?.atEvaluation)}`
        :`목선 ${number(pattern.neckline?.points?.[0]?.price)} → ${number(pattern.neckline?.points?.[1]?.price)}`;
      const lines=[`${name(pattern)} · ${stateLabel(pattern)}${pattern.historical?' · 당시 기준':''}${pattern.paused?' · 보류':''}`,`구간 ${pattern.structureBars}봉 · ${neckline}`,
        `확인 기준 ${number(pattern.triggerPriceAtEvaluation)} · 무효 ${number(pattern.invalidationPrice)}`,
        `확인봉 거래량 ${number(volume.ratio)}배 (${volumeLabel(volume.status)}) · 선행 흐름 ${trendLabel(trend.direction)} · 깊이 ${pct(evidence.depth?.pct)}`];
      if(pattern.triggerPriceAtEvent!=null&&pattern.triggerPriceAtEvent!==pattern.triggerPriceAtEvaluation)
        lines.push(`확인 당시 기준 ${number(pattern.triggerPriceAtEvent)} (현재 기준과 다름)`);
      for(const reason of (pattern.reasons||[]).slice(0,3))lines.push(`· ${reason.text}`);
      const card=document.createElement('div');card.className='patternCard';card.dataset.state=pattern.lifecycleState;
      lines.forEach((line,i)=>{const e=document.createElement(i===0?'strong':'div');e.textContent=line;card.append(e);});
      cards.append(card);
    }else{
      const empty=document.createElement('div');empty.className='patternCard';
      empty.textContent=({computing:'패턴 근거를 계산 중입니다. 기존 진입 판단과 별도입니다.',paused:'자료 보류 중입니다. 새 후보를 표시하지 않습니다.',unsupported:'이번 병행 평가의 지원 범위가 아닙니다.','unsupported-version':'규칙 버전이 달라 병행 근거를 표시하지 않습니다.',error:'계산 오류로 새 후보를 표시하지 않습니다.','insufficient-data':'확인된 후보가 아직 없습니다.'})[v.status]||'이번 범위에서 확인된 구조 후보가 없습니다.';
      cards.append(empty);
    }
    const history=$('structureEvidenceEvents');history.replaceChildren();
    const list=pattern?pattern.events:[];
    for(const e of list){
      const b=document.createElement('button');b.type='button';
      b.textContent=`${PatternWindow.format(e.effectiveBarTime)} · ${eventLabel(e)}`;
      b.onclick=()=>{eventChoice=eventChoice===e.eventId?null:e.eventId;render();};history.append(b);
      if(eventChoice===e.eventId){
        const s=e.snapshot||{},detail=document.createElement('div');
        detail.textContent=`종가 ${number(s.close)} · 목선 ${number(s.neckline)} · 기준 ${number(s.triggerPrice)} · 무효 ${number(s.invalidationPrice)} · 거래량 ${number(s.volumeRatio)}배`;
        history.append(detail);
      }
    }
    if(!list.length)history.textContent='기록된 사건 없음';
    // Chart overlay: neckline, confirmation and invalidation of the shown card.
    if(typeof syncStructureEvidenceLines==='function')syncStructureEvidenceLines(pattern);
  }
  function currentPattern(){
    const v=current();
    return v.status==='disabled'||v.status==='unsupported'||v.status==='unsupported-version'?null:selected(v);
  }
  window.StructureEvidencePanel={current,currentPattern,render,tick,name,stateLabel,eventLabel};
  document.addEventListener('DOMContentLoaded',()=>{
    $('structureEvidenceChoice').onchange=e=>{choice=e.target.value;eventChoice=null;render();};
    document.addEventListener('visibilitychange',render);render();
  });
})();
