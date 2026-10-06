/* Existing frame values and local MACD/OBV. No fetching. */
(function(){
  'use strict';
  const math=typeof module!=='undefined'&&module.exports?require('./technical-indicators.js'):TechnicalIndicators;
  const definitions={rsi:{label:'RSI 14',field:'rsi14',periodBars:14,unit:'0–100',help:'상승·하락의 상대적 힘입니다. 30·70 기준선은 자동 매수·매도 지시가 아닙니다.'},atr:{label:'ATR 14',field:'atr14',periodBars:14,unit:'price',help:'봉의 가격 변동폭입니다. 가격과 같은 단위이며 상승·하락 방향을 뜻하지 않습니다.'},volume:{label:'거래량',field:'volume',periodBars:1,unit:'volume',help:'봉의 누적 거래량입니다. 비율은 현재 봉을 포함한 20봉 평균 대비이며 패턴의 직전 20봉 비율과 다릅니다.'}};
  const known=v=>typeof v==='number'&&Number.isFinite(v);
  definitions.macd={label:'MACD 12·26·9',periodBars:34,unit:'price',help:'파랑 MACD · 주황 시그널 · 막대는 두 선의 차이입니다. 가격과 같은 단위이며, 0선과의 위치·차이 변화로 모멘텀을 확인합니다.'};
  definitions.obv={label:'OBV · 누적 거래량',periodBars:1,unit:'volume',help:'종가가 직전 봉보다 오르면 거래량을 더하고, 내리면 빼며, 같으면 유지합니다. 불러온 첫 봉을 0으로 시작하므로 절대값보다 흐름을 보세요. 거래량·종가 누락 이후는 계산을 보류합니다. 실제 순매수 금액·자동 매수 신호가 아닙니다.'};
  function build(frame,kind,index){
    const definition=definitions[kind],bars=frame?.candles||[];
    if(!definition||!bars[index])return {kind,status:'unavailable',value:null,basisTime:null,series:[]};
    const computed=kind==='macd'||kind==='obv'?math.calculate(frame):null;
    const values=computed?computed[kind]:bars.map((bar,i)=>kind==='volume'?bar.volume:frame.state?.[i]?.[definition.field]);
    const value=known(values[index])?values[index]:null;
    return {kind,label:definition.label,unit:definition.unit,periodBars:definition.periodBars,basisTime:bars[index].time,value,
      volumeRatio:kind==='volume'&&known(frame.state?.[index]?.vol_ratio)?frame.state[index].vol_ratio:null,
      ...(kind==='macd'&&computed?{signalValue:known(computed.signal[index])?computed.signal[index]:null,histogramValue:known(computed.histogram[index])?computed.histogram[index]:null,parameters:{fast:12,slow:26,signal:9},calculationVersion:math.version,seedPolicy:'sma-period',signalSeries:math.series(bars,computed.signal,index),histogramSeries:math.series(bars,computed.histogram,index).map(p=>known(p.value)?{...p,color:p.value>=0?'rgba(211,47,47,.65)':'rgba(24,89,201,.65)'}:p)}:{}),
      ...(kind==='obv'?{calculationVersion:math.version,seedPolicy:'first-bar-zero-stop-on-gap',seedTime:bars[0]?.time??null}:{}),
      status:value==null||(kind==='macd'&&computed&&!known(computed.signal[index]))?'insufficient-data':'ready',provisional:index===bars.length-1&&frame.confirmed===false,
      series:bars.map((bar,i)=>i<=index&&known(values[i])?{time:bar.time,value:values[i],...(kind==='volume'?{color:bar.close>=bar.open?'rgba(211,47,47,.65)':'rgba(24,89,201,.65)'}:{})}:{time:bar.time})};
  }
  const equalRange=(a,b)=>!!(a&&b&&Math.abs(a.from-b.from)<1e-6&&Math.abs(a.to-b.to)<1e-6);
  if(typeof module!=='undefined'&&module.exports){module.exports={build,definitions,equalRange};return;}
  const $=id=>document.getElementById(id);let kind='rsi',plot,line,signalLine,histogram,thresholds=[],last='';
  function current(){
    if(kind==='none')return {kind,status:'hidden',symbol:S.symbol,timeframe:S.tf};
    const f=frameOf(curSym()),data=build(f,kind,asOfIdx()),{series,signalSeries,histogramSeries,...summary}=data;
    const fetched=f?.fetchedAt||LIVE_META[metaKey(S.symbol,S.tf)]?.fetchedAt||null,age=Date.now()-Date.parse(fetched);
    const paused=Boolean(S.lastErr)||Boolean(data.provisional&&(!S.autoRef||document.hidden||!Number.isFinite(age)||age<0||age>90000));
    return {...summary,symbol:S.symbol,timeframe:S.tf,sourceFetchedAt:fetched,sourcePaused:paused,status:paused&&summary.status==='ready'?'paused':summary.status};
  }
  function readout(){
    const s=current();$('indicatorBody').hidden=kind==='none';if(kind==='none'){$('indicatorHelp').textContent='보조 지표를 숨긴 상태입니다.';last=JSON.stringify(s);return;}
    $('indicatorDate').textContent=s.basisTime==null?'—':fmtT(s.basisTime);
    $('indicatorValue').textContent=s.value==null?'자료 부족':kind==='atr'?fmtP(s.value):s.value.toLocaleString('ko-KR',{maximumFractionDigits:2});
    $('indicatorValueLabel').textContent=definitions[kind].label;
    $('indicatorComponents').hidden=kind!=='macd';
    for(const [id,value] of [['indicatorSignal',s.signalValue],['indicatorHistogram',s.histogramValue]])$(id).textContent=value==null?'자료 부족':value.toLocaleString('ko-KR',{maximumFractionDigits:4});
    if(kind==='macd'||kind==='obv')$('indicatorValue').textContent=s.value==null?'자료 부족':s.value.toLocaleString('ko-KR',{maximumFractionDigits:4});
    $('indicatorStatus').textContent=s.status==='paused'?'자료 보류':s.status!=='ready'?'계산 자료 부족':s.provisional?'진행 중 · 잠정':'확정봉 기준';
    for(const id of ['indicatorDate','indicatorValue','indicatorStatus','indicatorSignal','indicatorHistogram'])$(id).title=$(id).textContent;
    $('indicatorHelp').textContent=definitions[kind].help+(kind==='volume'?` · 현재 봉 ${s.volumeRatio==null?'20봉 비율 자료 부족':s.volumeRatio.toLocaleString('ko-KR',{maximumFractionDigits:3})+'배'}`:kind==='obv'?` · 누적 시작 ${s.seedTime==null?'자료 없음':fmtT(s.seedTime)}`:'');
    last=JSON.stringify(s);
  }
  function align(from,to){const r=from.timeScale().getVisibleLogicalRange();if(r&&!equalRange(r,to.timeScale().getVisibleLogicalRange()))to.timeScale().setVisibleLogicalRange(r);}
  function synchronize(){
    // MACD's four decimal places can make its axis wider than the candle axis.
    // A shared logical range also needs a shared plot width to align each bar.
    const width=Math.ceil(Math.max(chart.priceScale('right').width(),plot.priceScale('right').width()));
    if(width>0)for(const target of [chart,plot])if(target.options().rightPriceScale.minimumWidth!==width)target.applyOptions({rightPriceScale:{minimumWidth:width}});
    align(chart,plot);
  }
  function render(){
    if(!plot)return;readout();if(kind==='none')return;
    const f=frameOf(curSym()),data=build(f,kind,asOfIdx());
    plot.applyOptions({timeScale:{timeVisible:S.tf==='H4'},rightPriceScale:{minimumWidth:chart.priceScale('right').width()}});
    for(const threshold of thresholds)line.removePriceLine(threshold);thresholds=[];
    line.applyOptions({visible:kind!=='volume',color:kind==='atr'?'#7c3aed':kind==='obv'?'#0f766e':'#2962ff',priceFormat:kind==='obv'?{type:'volume'}:kind==='macd'?{type:'price',precision:4,minMove:.0001}:{type:'price',precision:2,minMove:.01},autoscaleInfoProvider:kind==='rsi'?()=>({priceRange:{minValue:0,maxValue:100}}):original=>original()});
    signalLine.applyOptions({visible:kind==='macd'});
    histogram.applyOptions({visible:kind==='volume'||kind==='macd',priceFormat:kind==='volume'?{type:'volume'}:{type:'price',precision:4,minMove:.0001}});
    line.setData(kind==='volume'?data.series.map(p=>({time:p.time})):data.series);
    signalLine.setData(kind==='macd'?data.signalSeries||[]:[]);
    histogram.setData(kind==='macd'?data.histogramSeries||[]:kind==='volume'?data.series:data.series.map(p=>({time:p.time})));
    if(kind==='rsi')for(const price of [30,70])thresholds.push(line.createPriceLine({price,color:'#94a3b8',lineWidth:1,lineStyle:2,title:String(price),axisLabelVisible:true}));
    if(kind==='macd')thresholds.push(line.createPriceLine({price:0,color:'#94a3b8',lineWidth:1,lineStyle:2,title:'0',axisLabelVisible:true}));
    synchronize();
    requestAnimationFrame(synchronize);
  }
  function tick(){if(plot&&JSON.stringify(current())!==last)readout();}
  window.IndicatorPanel={current,render,tick,chart:()=>plot,kind:()=>kind,series:()=>({line,signal:signalLine,histogram})};
  document.addEventListener('DOMContentLoaded',()=>{
    const host=$('indicatorChart');
    plot=LightweightCharts.createChart(host,{width:host.clientWidth,height:host.clientHeight,layout:{background:{type:'solid',color:'#fff'},textColor:'#536675',fontSize:12},grid:{vertLines:{color:'#E5EAF0'},horzLines:{color:'#E5EAF0'}},rightPriceScale:{scaleMargins:{top:.1,bottom:.1}},timeScale:{rightOffset:2},handleScroll:false,handleScale:false});
    line=plot.addSeries(LightweightCharts.LineSeries,{lineWidth:2,lastValueVisible:false,priceLineVisible:false});
    signalLine=plot.addSeries(LightweightCharts.LineSeries,{color:'#FF6D00',lineWidth:2,lastValueVisible:false,priceLineVisible:false,priceFormat:{type:'price',precision:4,minMove:.0001},visible:false});
    histogram=plot.addSeries(LightweightCharts.HistogramSeries,{priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false,visible:false});
    chart.timeScale().subscribeVisibleLogicalRangeChange(()=>{if(kind!=='none')synchronize();});
    const observer=new ResizeObserver(()=>{if(host.clientWidth){plot.applyOptions({width:host.clientWidth,height:host.clientHeight});synchronize();requestAnimationFrame(synchronize);}});observer.observe(host);
    $('indicatorChoice').onchange=e=>{kind=e.target.value;render();};
    document.addEventListener('visibilitychange',tick);render();
  });
})();
