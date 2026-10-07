/* Triangle evidence is supplied by the same server snapshot as the candles. */
(function(){
  'use strict';
  const view=typeof module!=='undefined'&&module.exports?require('./flag-panel.js').view:FlagPanel.view;
  const names={'ascending-triangle':'상승 삼각형','descending-triangle':'하락 삼각형','symmetrical-triangle':'대칭 삼각형'};
  const name=p=>names[p.type]||'삼각형';
  const label=p=>({forming:'형성 중 · 방향 대기',confirmed:'종가 확인','breakout-pending':'장중 돌파 · 잠정',retested:'돌파선 재확인',failed:'패턴 무효·실패',expired:'기간·꼭짓점 경과',paused:'자료 보류',revised:'원천 정정'})[p.eventType||p.status]+(p.direction==='up'?' · 위쪽':p.direction==='down'?' · 아래쪽':'');
  const errorText=code=>({'invalid-data':'봉 자료 형식 오류','storage-error':'분석 저장 오류','calculation-error':'삼각수렴 계산 오류'})[code]||'삼각수렴 처리 오류';
  function fitBounds(pattern,bars){
    if(!pattern||['failed','expired','paused'].includes(pattern.status))return null;
    const indexes=new Map(bars.map((b,i)=>[String(b.time),i]));
    const points=(pattern.geometry?.points||[]).map(p=>({index:indexes.get(String(p.time??p.anchorTime))+(p.time==null?Number(p.logicalOffset):0),price:p.price}));
    if(points.length<3||points.some(p=>!Number.isFinite(p.index)||!Number.isFinite(p.price)||p.price<=0))return null;
    const first=Math.min(...points.map(p=>p.index)),observed=indexes.get(String(pattern.geometry.observedThrough??pattern.barTime))??first,end=Math.max(...points.map(p=>p.index),observed);
    const prices=[...points.map(p=>p.price),...bars.slice(Math.max(0,Math.floor(first)),Math.min(bars.length,observed+1)).flatMap(b=>[b.high,b.low]).filter(Number.isFinite)];
    const low=Math.min(...prices),high=Math.max(...prices),pad=Math.max((high-low)*.1,high*.005);
    return {range:{from:first-3,to:Math.max(end+3,first+7)},priceRange:{minValue:Math.max(Number.MIN_VALUE,low-pad),maxValue:high+pad}};
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={view,name,label,errorText,fitBounds};return;}
  const $=id=>document.getElementById(id);let choice='auto',last='',fitted=null;
  const number=n=>n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:2});
  function current(){const f=frameOf(curSym()),a=S.tf==='H4'?f?.triangleAnalysis:curSym()?.triangleAnalysis;
    const context=ChartTiming.patternContext({frame:f,analysis:a,selectedAsOf:S.selectedAsOf,lastError:S.lastErr,enabled:S.autoRef&&!document.hidden});
    return view(a,S.tf,context.asOf,context.blocked);
  }
  function selected(){const v=current();return v.patterns.find(p=>p.patternId===choice)||v.patterns.find(p=>!['failed','expired','paused'].includes(p.status))||null;}
  function signature(v){return JSON.stringify([S.symbol,S.tf,S.selectedAsOf,v.status,v.barTime,v.patterns.map(p=>[p.patternId,p.status,p.direction])]);}
  function tick(){if(signature(current())!==last)render();}
  function render(){const v=current();last=signature(v);$('trianglePanel').hidden=v.status==='disabled';
    if(v.status==='disabled'){FlagPanel.update();return;}
    $('triangleState').textContent=({'out-of-window':'패턴 범위 밖 · 최신 자료 기준 최근 3개월입니다.',unsupported:'삼각수렴은 주식·코인 일봉/4시간봉에서 확인합니다.',paused:'자료 보류 · 이전 이력은 유지합니다.',error:'계산 오류 · 새 판단 보류','insufficient-data':'확정된 접촉점 자료가 부족합니다.'})[v.status]||`${PatternWindow.format(v.barTime)||'—'} 기준 · ${v.patterns.length?'돌파 방향을 확인하세요.':v.pastPatterns?.length?'현재 유효 삼각형 없음 · 선택 목록에서 과거 구조 확인':'확인된 삼각형 없음'}`;
    if(v.status==='error')$('triangleState').textContent=errorText((S.tf==='H4'?frameOf(curSym()):curSym())?.triangleAnalysis?.errorCode)+' · 새 판단 보류';
    const select=$('triangleChoice');select.replaceChildren();const add=(value,text)=>{const o=document.createElement('option');o.value=value;o.textContent=text;select.append(o);};
    add('auto','최근 유효 삼각형');for(const p of v.patterns)add(p.patternId,`${name(p)} · ${label(p)}`);
    for(const p of v.pastPatterns||[])add('past:'+p.patternId,`과거 · ${PatternWindow.format(p.barTime)} · ${name(p)} · ${label(p)}`);
    if(choice!=='auto'&&!v.patterns.some(p=>p.patternId===choice))choice='auto';select.value=choice;
    const bounds=fitBounds(selected(),frameOf(curSym())?.candles||[]);
    $('triangleFit').disabled=!bounds;$('triangleFit').title=bounds?'시작점부터 예상 꼭짓점까지 가로·세로 범위를 맞춥니다.':'표시할 유효 삼각형이 없습니다.';
    $('triangleFitStatus').textContent=!bounds?'표시할 유효 삼각형 없음':fitted?.patternId===selected()?.patternId?'삼각형 시작점~꼭짓점 전체 표시':'';
    const cards=$('triangleCards');cards.replaceChildren();
    for(const p of v.patterns){const card=document.createElement('div');card.className='patternCard';card.dataset.state=p.status;
      const lines=[`${name(p)} · ${label(p)}`,`수렴 ${p.structureBars}봉 · 접촉 ${p.contactCount}회 · 폭 ${number(p.convergenceRatio*100)}%`,
        `위쪽 종가 통과 ${number(p.upTrigger)} · 아래쪽 ${number(p.downTrigger)}`,
        p.reason?({ 'apex-reached':'예상 꼭짓점 경과','structure-over-60':'60봉 기간 초과','two-sided-range':'한 봉에서 양쪽 경계를 모두 넘김','channel-containment':'봉이 수렴 경계를 반복 이탈'})[p.reason]:p.direction==='neutral'?`방향 대기 · 현재 봉 거래량 ${number(p.rvol20Previous)}배`:`돌파 후 무효 ${number(p.invalidationPrice)} · 현재 봉 거래량 ${number(p.rvol20Previous)}배`];
      for(let i=0;i<lines.length;i++){const node=document.createElement(i===0?'strong':'div');node.textContent=lines[i];card.append(node);}cards.append(card);
    }
    const history=$('triangleEvents');history.replaceChildren();
    for(const e of v.events){const b=document.createElement('button');b.type='button';b.textContent=`${PatternWindow.format(e.confirmedBarTime)} · ${name(e)} · ${label(e)}`;b.onclick=()=>PatternPanel.openEvent(e);history.append(b);}
    if(!v.events.length)history.textContent='발생한 삼각형 없음';FlagPanel.update();
  }
  function fitSelected(){
    const p=selected(),bounds=fitBounds(p,frameOf(curSym())?.candles||[]);
    if(!bounds){$('triangleFitStatus').textContent='표시할 유효 삼각형 없음';return false;}
    fitted={...bounds,patternId:p.patternId};
    // Set custom explicitly: the chart's initial render guard can ignore range-change events.
    S.preset='custom';if(typeof paintPreset==='function')paintPreset();FlagPanel.showArea('triangle');
    if(candles.applyOptions)candles.applyOptions({autoscaleInfoProvider:base=>{
      const info=base(),range=chart.timeScale().getVisibleLogicalRange?.();
      if(!fitted||selected()?.patternId!==fitted.patternId||!range||Math.abs(range.from-fitted.range.from)>.1||Math.abs(range.to-fitted.range.to)>.1)return info;
      return {...info,priceRange:{minValue:Math.min(info?.priceRange?.minValue??Infinity,fitted.priceRange.minValue),maxValue:Math.max(info?.priceRange?.maxValue??-Infinity,fitted.priceRange.maxValue)}};
    }});
    candles.priceScale?.().applyOptions({autoScale:true});
    chart.timeScale().setVisibleLogicalRange(bounds.range);
    $('triangleFitStatus').textContent='삼각형 시작점~꼭짓점 전체 표시';$('chart').scrollIntoView?.({block:'center',behavior:'smooth'});return true;
  }
  window.TrianglePanel={current,selected,render,tick,name,fit:fitSelected};
  document.addEventListener('DOMContentLoaded',()=>{
    $('triangleFit').onclick=fitSelected;$('triangleChoice').onchange=e=>{const value=e.target.value;fitted=null;
      if(value.startsWith('past:')){const p=current().pastPatterns?.find(p=>'past:'+p.patternId===value);if(!p)return;choice=p.patternId;window.__CF.select(p.barTime);FlagPanel.showArea('triangle');render();fitSelected();return;}
      choice=value;FlagPanel.selectArea('triangle');render();};document.addEventListener('visibilitychange',render);render();});
})();
