/* Double top/bottom and head-and-shoulders structure evidence. Server supplied. */
(function(){
  'use strict';
  const view=typeof module!=='undefined'&&module.exports?require('./flag-panel.js').view:FlagPanel.view;
  const names={'double-top':'더블탑','double-bottom':'더블바텀','head-shoulders':'헤드앤숄더','inverse-head-shoulders':'역헤드앤숄더'};
  const name=p=>names[p.type]||'구조 패턴';
  const label=p=>({confirmed:'종가 확인',retested:'돌파선 재확인',failed:'패턴 무효·실패',expired:'기간 경과',paused:'자료 보류',revised:'원천 정정',forming:'형성 중'})[p.eventType||p.status]+(p.direction==='up'?' · 위쪽':p.direction==='down'?' · 아래쪽':'');
  const errorText=code=>({'invalid-data':'봉 자료 형식 오류','storage-error':'분석 저장 오류','calculation-error':'구조 패턴 계산 오류'})[code]||'구조 패턴 처리 오류';
  if(typeof module!=='undefined'&&module.exports){module.exports={view,name,label,errorText};return;}
  const $=id=>document.getElementById(id);let choice='auto',last='';
  const INTRADAY=new Set(['M5','M15','M30','H1','H2','H4']);
  const number=n=>n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:2});
  function current(){const f=frameOf(curSym()),a=INTRADAY.has(S.tf)?f?.structureAnalysis:curSym()?.structureAnalysis;
    const context=ChartTiming.patternContext({frame:f,analysis:a,selectedAsOf:S.selectedAsOf,lastError:S.lastErr,enabled:S.autoRef&&!document.hidden});
    return view(a,S.tf,context.asOf,context.blocked);
  }
  function selected(){const v=current();return v.patterns.find(p=>p.patternId===choice)||v.patterns.find(p=>!['failed','expired','paused'].includes(p.status))||null;}
  function signature(v){return JSON.stringify([S.symbol,S.tf,S.selectedAsOf,v.status,v.barTime,v.patterns.map(p=>[p.patternId,p.status,p.direction])]);}
  function tick(){if(signature(current())!==last)render();}
  function render(){const v=current();last=signature(v);$('structurePanel').hidden=v.status==='disabled';
    if(v.status==='disabled'){FlagPanel.update();return;}
    $('structureState').textContent=({'out-of-window':'패턴 범위 밖 · 최신 자료 기준 최근 3개월입니다.',unsupported:'구조 패턴은 주식·코인 일봉과 분봉에서 확인합니다.',computing:'차트 표시 완료 · 구조 패턴 계산 중…',paused:'자료 보류 · 이전 이력은 유지합니다.',error:'계산 오류 · 새 판단 보류','insufficient-data':'확정된 고점·저점 자료가 부족합니다.'})[v.status]||`${PatternWindow.format(v.barTime)||'—'} 기준 · ${v.patterns.length?'목선 종가 돌파를 확인하세요.':v.pastPatterns?.length?'현재 유효 구조 없음 · 선택 목록에서 과거 구조 확인':'확인된 구조 패턴 없음'}`;
    if(v.status==='error')$('structureState').textContent=errorText((INTRADAY.has(S.tf)?frameOf(curSym()):curSym())?.structureAnalysis?.errorCode)+' · 새 판단 보류';
    const evidence=curSym()?.structureEvidenceV2;
    if(evidence?.sourceStatus==='ready')$('structureState').textContent+=' · 병행 근거는 아래 패널 참고';
    const select=$('structureChoice');select.replaceChildren();const add=(value,text)=>{const o=document.createElement('option');o.value=value;o.textContent=text;select.append(o);};
    add('auto','최근 유효 구조');for(const p of v.patterns)add(p.patternId,`${name(p)} · ${label(p)}`);
    for(const p of v.pastPatterns||[])add('past:'+p.patternId,`과거 · ${PatternWindow.format(p.barTime)} · ${name(p)} · ${label(p)}`);
    if(choice!=='auto'&&!v.patterns.some(p=>p.patternId===choice))choice='auto';select.value=choice;
    const cards=$('structureCards');cards.replaceChildren();
    for(const p of v.patterns){const card=document.createElement('div');card.className='patternCard';card.dataset.state=p.status;
      const lines=[`${name(p)} · ${label(p)}`,`구간 ${p.structureBars}봉 · 목선 ${number(p.neckline)}`,
        `종가 통과 ${number(p.triggerPrice)} · 무효 ${number(p.invalidationPrice)}`,
        `고점/저점 ${(p.peakPrices||[]).map(number).join(' · ')} · 확인봉 거래량 ${number(p.rvol20Previous)}배`];
      for(let i=0;i<lines.length;i++){const e=document.createElement(i===0?'strong':'div');e.textContent=lines[i];card.append(e);}cards.append(card);
    }
    const history=$('structureEvents');history.replaceChildren();
    for(const e of v.events){const b=document.createElement('button');b.type='button';b.textContent=`${PatternWindow.format(e.confirmedBarTime)} · ${name(e)} · ${label(e)}`;b.onclick=()=>PatternPanel.openEvent(e);history.append(b);}
    if(!v.events.length)history.textContent='발생한 구조 패턴 없음';FlagPanel.update();
  }
  window.StructurePanel={current,selected,render,tick,name};
  document.addEventListener('DOMContentLoaded',()=>{
    $('structureChoice').onchange=e=>{const value=e.target.value;
      if(value.startsWith('past:')){const p=current().pastPatterns?.find(p=>'past:'+p.patternId===value);if(!p)return;choice=p.patternId;window.__CF.select(p.barTime);FlagPanel.showArea('structure');render();return;}
      choice=value;FlagPanel.selectArea('structure');render();};document.addEventListener('visibilitychange',render);render();});
})();
