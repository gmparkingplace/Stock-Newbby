/* Server-only daily evidence. View changes never recompute a crossing. */
(function(root){
  'use strict';
  const windowed=typeof module!=='undefined'&&module.exports?require('./pattern-window.js'):PatternWindow;
  const labels={'confirmed':'종가 돌파 확인','breakout-pending':'장중 돌파 · 잠정','forming':'돌파 대기','retested':'돌파선 재지지 확인','failed':'돌파 실패','revised':'원천 정정','paused':'자료 보류'};
  const names={'prior-20-high':'직전 20봉 고점','prior-10-low':'직전 10봉 저점','user-resistance':'지정 저항','user-support':'지정 지지','bull-flag':'상승 플래그 (Bull)','bear-flag':'하락 플래그 (Bear)','ascending-triangle':'상승 삼각형','descending-triangle':'하락 삼각형','symmetrical-triangle':'대칭 삼각형'};
  function view(analysis, tf, asOf, blocked){
    if(!analysis?.enabled)return {status:'disabled',levels:[],events:[]};
    if(tf!=='D')return {status:'unsupported',levels:[],events:[]};
    if(analysis.sourceStatus==='error'||analysis.sourceStatus==='unsupported')return {status:analysis.sourceStatus,levels:[],events:[]};
    const timeline=analysis.timeline||[];
    const selected=asOf?timeline.find(x=>x.barTime===asOf):timeline.at(-1);
    const paused=blocked||analysis.sourceStatus==='paused';
    const reference=analysis.window?.end||timeline.at(-1)?.barTime;
    if(asOf&&asOf<windowed.start(reference))return {status:'out-of-window',levels:[],events:[],window:{months:3,start:windowed.start(reference),end:reference}};
    return {status:paused?'paused':selected?.status||'not-collected',symbol:analysis.symbol,
      barTime:selected?.barTime||null,ruleVersion:analysis.ruleVersion,dataRevision:analysis.dataRevision,
      sourceFetchedAt:analysis.sourceFetchedAt,levels:windowed.filter((selected?.levels||[]).map(x=>({...x,barTime:x.barTime||selected.barTime})),reference).map(x=>({...x,status:paused||(!selected.confirmed&&!analysis.provisionalEligible)?'paused':x.status})),
      window:{months:3,start:windowed.start(reference),end:reference},
      events:windowed.filter(analysis.recentEvents,reference).filter(e=>!asOf||e.confirmedBarTime<=asOf)};
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={view,labels,names};return;}
  let basisOverlay=null,basisChart=null, observer=null, opened=null, openSequence=0, inputSymbol=null,lastState='';
  const $=id=>document.getElementById(id);
  function add(parent,tag,text,cls){const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;parent.append(el);return el;}
  function label(item){
    const state=item.eventType||item.status;
    if(item.direction==='down')return ({confirmed:'종가 이탈 확인','breakout-pending':'장중 이탈 · 잠정',retested:'이탈선 재저항 확인',failed:'이탈 실패'})[state]||labels[state]||state;
    return labels[state]||state;
  }
  function number(n){return n==null?'—':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:4});}
  function current(){const f=frameOf(curSym()),analysis=curSym()?.patternAnalysis;
    const context=ChartTiming.patternContext({frame:f,analysis,selectedAsOf:S.selectedAsOf,lastError:S.lastErr,enabled:S.autoRef&&!document.hidden});
    return {...view(analysis,S.tf,context.asOf,context.blocked),historical:context.historical};}
  function signature(v){return JSON.stringify([S.symbol,S.tf,S.selectedAsOf,v.status,v.barTime,v.levels.map(p=>p.status)]);}
  function tick(){if(signature(current())!==lastState)render();}
  function render(){
    const box=$('patternPanel');if(!box)return;
    const f=frameOf(curSym()), analysis=curSym()?.patternAnalysis, state=current();lastState=signature(state);
    box.hidden=state.status==='disabled'; if(box.hidden)return;
    const status=$('patternStatus');status.textContent=({'out-of-window':'패턴 범위 밖 · 최신 자료 기준 최근 3개월입니다.',unsupported:'패턴 분석은 주식 일봉에서 지원합니다.',error:'패턴 계산·저장 오류 · 새 사건 확인 보류',paused:'자료 보류 · 새 사건 확인을 중단했습니다.','insufficient-data':'비교 자료 부족 · 최소 22봉이 필요합니다.','not-collected':'아직 분석 자료가 없습니다.'})[state.status]||`${state.barTime} 기준 · ${state.historical?'당시 조건 비교':'종가 확인 / 장중 잠정 구분'}`;
    const grid=$('patternLevels');grid.replaceChildren();
    for(const level of state.levels){
      const card=add(grid,'div','', 'patternCard');card.dataset.state=level.status;
      add(card,'strong',`${names[level.type]} · ${label(level)}`);
      add(card,'div',`기준 ${number(level.boundary)} · ${level.direction==='up'?'위로':'아래로'} ${number(level.triggerPrice)} 종가 통과`);
      add(card,'div',`반대 방향 ${number(level.invalidationPrice)} 종가 통과 시 실패`);
      add(card,'small',`${level.volumeEvidence==='volume-confirmed'?'거래량 동반':'거래량 확인 부족'} · 직전 20봉 대비 ${number(level.rvol20Previous)}배`);
    }
    if(inputSymbol!==S.symbol){inputSymbol=S.symbol;$('patternSupport').value=analysis?.levels?.support??'';$('patternResistance').value=analysis?.levels?.resistance??'';$('patternSaveStatus').textContent='';}
    $('patternSave').disabled=S.tf!=='D'||!analysis?.enabled||state.status==='unsupported';
    const latest=state.events[0];$('patternLastEvent').textContent=latest?`최근 기록: ${latest.confirmedBarTime} · ${names[latest.type]} · ${label(latest)}`:'최근 돌파 기록 없음';
    const list=$('patternEvents');list.replaceChildren();
    if(!state.events.length)add(list,'p','저장된 사건이 없습니다.');
    for(const event of state.events){
      const b=add(list,'button',`${event.confirmedBarTime} · ${names[event.type]} · ${label(event)} · 종가 ${number(event.close)}`);
      b.type='button';b.dataset.eventId=event.eventId;b.onclick=()=>openEvent(event);
    }
  }
  async function read(path){const r=await fetch(path,{signal:AbortSignal.timeout(8000)});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();}
  async function openEvent(event){
    const seq=++openSequence;
    try{
      const snap=await read('/api/snapshots/'+encodeURIComponent(event.basisSnapshotId));
      if(seq!==openSequence)return;
      opened=snap;
      const dialog=$('patternDialog');if(!dialog.open)dialog.showModal();
      $('patternSnapshotTitle').textContent=`${snap.name} · ${snap.timeframe==='H4'?'4시간봉':'일봉'} · ${names[event.type]||event.type} · ${PatternWindow.format(event.confirmedBarTime)} · ${label(event)}`;
      $('patternSnapshotBasis').textContent=`종가 ${number(snap.event.close)} · 당시 기준 ${number(snap.event.boundary)} · 통과 가격 ${number(snap.event.triggerPrice)} · 실패 가격 ${number(snap.event.invalidationPrice)}`;
      $('patternSnapshotMeta').textContent=`${snap.source} · 원천 수집 ${snap.fetchedAt} · ${snap.ruleVersion} · revision ${snap.dataRevision.slice(0,12)}`;
      $('patternSnapshotNote').textContent=snap.basisBarAvailable===false?'정정 원천에 해당 날짜 봉이 없습니다. 최초 사건은 이력에서 다시 열 수 있습니다.':event.eventType==='revised'?'원천 정정 당시 자료입니다. 원래 사건 이력은 보존합니다.':'당시 원천 자료입니다. 사건 이후 봉은 포함하지 않습니다.';
      if(basisOverlay)basisOverlay.destroy();basisOverlay=null;
      if(basisChart)basisChart.remove();if(observer)observer.disconnect();
      const el=$('patternSnapshotChart');
      basisChart=LightweightCharts.createChart(el,{width:el.clientWidth,height:Math.max(220,Math.min(380,el.clientWidth/1.5)),layout:{background:{type:'solid',color:'rgba(255,255,255,0)'},textColor:'#334155'},rightPriceScale:{scaleMargins:{top:.1,bottom:.1}},timeScale:{borderColor:'#cbd5e1',timeVisible:snap.timeframe==='H4'}});
      const series=basisChart.addSeries(LightweightCharts.CandlestickSeries,{upColor:UP,downColor:DOWN,wickUpColor:UP,wickDownColor:DOWN,borderVisible:false});
      series.setData(snap.candles);
      if(snap.event.geometry){basisOverlay=PatternOverlay.create(el,basisChart,series,()=>snap.candles);basisOverlay.set(snap.event);}
      series.createPriceLine({price:snap.event.boundary,color:'#2563eb',lineWidth:2,lineStyle:0,title:'당시 기준',axisLabelVisible:true});
      basisChart.timeScale().fitContent();
      if(snap.candles.length>60)basisChart.timeScale().setVisibleLogicalRange({from:snap.candles.length-60,to:snap.candles.length});
      observer=new ResizeObserver(()=>{if(basisChart)basisChart.resize(el.clientWidth,Math.max(220,Math.min(380,el.clientWidth/1.5)));});observer.observe(el);
    }catch(e){if(seq!==openSequence)return;if($('patternDialog').open)$('patternDialog').close();$('patternStatus').textContent='사건 자료를 열지 못했습니다. '+e.message;}
  }
  async function save(){
    const symbol=S.symbol;const value=id=>$(id).value.trim()===''?null:Number($(id).value);
    const levels={support:value('patternSupport'),resistance:value('patternResistance')};
    if(Object.values(levels).some(n=>n!==null&&(!Number.isFinite(n)||n<=0))||(levels.support!==null&&levels.resistance!==null&&levels.support>=levels.resistance)){$('patternSaveStatus').textContent='양수 가격을 입력하고 지지는 저항보다 낮게 설정하세요.';return;}
    $('patternSave').disabled=true;
    try{
      const {sessionToken}=await read('/api/analysis-session');
      const r=await fetch('/api/pattern-levels',{method:'POST',headers:{'Content-Type':'application/json','X-Chart-Session':sessionToken},body:JSON.stringify({symbol,levels}),signal:AbortSignal.timeout(8000)});
      if(!r.ok)throw new Error(`HTTP ${r.status}`);
      if(symbol===S.symbol){$('patternSaveStatus').textContent='저장했습니다. 새로고침하면 지정선도 분석합니다.';inputSymbol=null;}
    }catch(e){$('patternSaveStatus').textContent='저장 실패 · '+e.message;}
    finally{$('patternSave').disabled=S.tf!=='D'||current().status==='unsupported';}
  }
  window.PatternPanel={render,tick,current,view,openEvent,snapshot:()=>opened};
  document.addEventListener('DOMContentLoaded',()=>{
    $('patternSave').onclick=save;
    $('patternClose').onclick=()=>$('patternDialog').close();
    $('patternDialog').addEventListener('close',()=>{openSequence++;opened=null;if(basisOverlay)basisOverlay.destroy();basisOverlay=null;if(observer)observer.disconnect();if(basisChart)basisChart.remove();basisChart=null;});
    document.addEventListener('visibilitychange',render);render();
  });
})(typeof window==='undefined'?globalThis:window);
