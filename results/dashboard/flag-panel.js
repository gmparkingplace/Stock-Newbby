/* One selected structure on the chart; the server supplies all pattern evidence. */
(function(){
  'use strict';
  const windowed=typeof module!=='undefined'&&module.exports?require('./pattern-window.js'):PatternWindow;
  const labels={forming:'형성 중',confirmed:'종가 돌파 확인','breakout-pending':'장중 돌파 · 잠정',retested:'돌파선 재확인',failed:'패턴 실패',expired:'기간 경과',revised:'원천 정정',paused:'자료 보류'};
  function view(analysis,tf,asOf,blocked){
    if(!analysis?.enabled)return {status:'disabled',patterns:[],events:[]};
    if(!['D','H4'].includes(tf)||tf!==(analysis.timeframe||'D')||analysis.sourceStatus==='unsupported')return {status:'unsupported',patterns:[],events:[]};
    const t=asOf?(analysis.timeline||[]).find(x=>x.barTime===asOf):(analysis.timeline||[]).at(-1);
    const paused=blocked||analysis.sourceStatus==='paused';
    const reference=analysis.window?.end||(analysis.timeline||[]).at(-1)?.barTime;
    if(asOf&&asOf<windowed.start(reference))return {status:'out-of-window',patterns:[],events:[],window:{months:3,start:windowed.start(reference),end:reference}};
    return {status:analysis.sourceStatus==='error'?'error':paused?'paused':t?.status||'not-collected',barTime:t?.barTime,ruleVersion:analysis.ruleVersion,dataRevision:analysis.dataRevision,
      window:{months:3,start:windowed.start(reference),end:reference},
      patterns:windowed.filter((t?.patterns||[]).map(p=>({...p,barTime:p.barTime||t.barTime})),reference).map(p=>({...p,status:paused||!t.confirmed&&!analysis.provisionalEligible?'paused':p.status})),
      events:windowed.filter(analysis.recentEvents,reference).filter(e=>!asOf||e.confirmedBarTime<=asOf)};
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={view,labels};return;}
  const $=id=>document.getElementById(id);let overlay=null,visible=true,choice='auto',lastState='',areaChoice='auto';
  const name=p=>p.type==='bull-flag'?'상승 플래그 (Bull)':'하락 플래그 (Bear)';
  const number=n=>n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:2});
  function current(){const f=frameOf(curSym()),analysis=S.tf==='H4'?f?.flagAnalysis:curSym()?.flagAnalysis;
    const context=ChartTiming.patternContext({frame:f,analysis,selectedAsOf:S.selectedAsOf,lastError:S.lastErr,enabled:S.autoRef&&!document.hidden});
    return view(analysis,S.tf,context.asOf,context.blocked);
  }
  function signature(v){return JSON.stringify([S.symbol,S.tf,S.selectedAsOf,v.status,v.barTime,v.patterns.map(p=>[p.patternId,p.status])]);}
  function tick(){const v=current();if(signature(v)!==lastState)render();}
  function selected(){const v=current();return v.patterns.find(p=>p.patternId===choice)||v.patterns.find(p=>!['failed','expired','paused'].includes(p.status))||null;}
  function update(){if(!overlay)return;const p=PatternOverlay.choose(selected(),window.TrianglePanel?.selected(),areaChoice);overlay.set(visible&&['D','H4'].includes(S.tf)?p:null);$('flagOverlayStatus').textContent=p?`${p.type.endsWith('-triangle')?TrianglePanel.name(p):name(p)} · ${labels[p.status]} · ${visible?'색 채움 표시':'색 채움 숨김'}`:'표시할 패턴 없음';}
  function render(){
    const v=current(),a=S.tf==='H4'?frameOf(curSym()):curSym();lastState=signature(v);$('flagPanel').hidden=v.status==='disabled';$('flagOverlayControls').hidden=v.status==='disabled'&&!a?.triangleAnalysis?.enabled;
    if(v.status==='disabled'){update();return;}
    $('flagState').textContent=({'out-of-window':'패턴 범위 밖 · 최신 자료 기준 최근 3개월입니다.',unsupported:'플래그는 주식·코인 일봉/4시간봉에서 확인합니다.',error:'플래그 계산 오류 · 새 판단 보류',paused:'자료 보류 · 이전 이력은 유지합니다.','insufficient-data':'선행 가격과 확정 피벗 자료가 부족합니다.'})[v.status]||`${PatternWindow.format(v.barTime)||'—'} 기준 · ${v.patterns.length?'형성과 종가 돌파를 구분하세요.':'확인된 플래그 구조 없음'}`;
    const select=$('flagChoice');select.replaceChildren();
    const addOption=(value,text)=>{const o=document.createElement('option');o.value=value;o.textContent=text;select.append(o);};
    addOption('auto','최근 유효 패턴');for(const p of v.patterns)addOption(p.patternId,`${p.type.endsWith('-triangle')?TrianglePanel.name(p):name(p)} · ${labels[p.status]}`);
    if(choice!=='auto'&&!v.patterns.some(p=>p.patternId===choice))choice='auto';select.value=choice;
    const cards=$('flagCards');cards.replaceChildren();
    for(const p of v.patterns){
      const card=document.createElement('div');card.className='patternCard';card.dataset.state=p.status;
      const lines=[`${p.type.endsWith('-triangle')?TrianglePanel.name(p):name(p)} · ${labels[p.status]}`,`조정 ${p.adjustmentBars}봉 · 되돌림 ${number(100*p.retracementRatio)}%`,
        `종가 통과 ${number(p.triggerPrice)} · 무효 ${number(p.invalidationPrice)}`,
        `조정 거래량 ${number(p.adjustmentVolumeRatio)}배 · 현재 봉 거래량 ${number(p.rvol20Previous)}배`];
      for(let i=0;i<lines.length;i++){const e=document.createElement(i===0?'strong':'div');e.textContent=lines[i];card.append(e);}cards.append(card);
    }
    const history=$('flagEvents');history.replaceChildren();
    for(const e of v.events){const b=document.createElement('button');b.type='button';b.textContent=`${PatternWindow.format(e.confirmedBarTime)} · ${name(e)} · ${labels[e.eventType]||e.eventType}`;b.onclick=()=>PatternPanel.openEvent(e);history.append(b);}
    if(!v.events.length)history.textContent='발생한 플래그 없음';
    update();
  }
  const selectArea=family=>{areaChoice=family;$('patternAreaFamily').value=family;update();};
  window.FlagPanel={view,selectArea,showArea:family=>{visible=true;$('flagOverlayToggle').setAttribute('aria-pressed','true');$('flagOverlayToggle').textContent='패턴 영역 ON';selectArea(family);},current,render,update,tick,selected,overlay:()=>overlay};
  document.addEventListener('DOMContentLoaded',()=>{
    overlay=PatternOverlay.create($('chart'),chart,candles,()=>frameOf(curSym())?.candles||[]);
    $('flagChoice').onchange=e=>{choice=e.target.value;areaChoice='flag';$('patternAreaFamily').value='flag';update();};
    $('patternAreaFamily').onchange=e=>{areaChoice=e.target.value;update();};
    $('flagOverlayToggle').onclick=()=>{visible=!visible;$('flagOverlayToggle').setAttribute('aria-pressed',String(visible));$('flagOverlayToggle').textContent=visible?'패턴 영역 ON':'패턴 영역 OFF';update();};
    document.addEventListener('visibilitychange',render);render();
  });
})();
