/* 양수 가격의 급락 구간에서는 하단 고정 여백만 줄인다. 자동축척·자료·시간 범위는 보존한다. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.PriceScaleGuard=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function margins(infos,height){
    const ranges=infos.filter(Boolean).filter(x=>Number.isFinite(x.priceRange?.minValue)&&Number.isFinite(x.priceRange?.maxValue));
    if(!ranges.length||!(height>0))return {top:.12,bottom:.25};
    const min=Math.min(...ranges.map(x=>x.priceRange.minValue)),max=Math.max(...ranges.map(x=>x.priceRange.maxValue));
    if(!(min>0)||!(max>min))return {top:.12,bottom:.25};
    const above=Math.max(0,...ranges.map(x=>x.margins?.above||0)),below=Math.max(0,...ranges.map(x=>x.margins?.below||0));
    // 8px 여유를 두되 마커의 고유 공간까지 줄이거나 가격을 잘라내지는 않는다.
    return {top:.12,bottom:Math.min(.25,Math.max(0,(min/max*(height*.88-above-1)-below-8)/height))};
  }
  function attach(chart,host,seriesList,enqueue){
    const records=new Set();let queued=false;
    const raf=enqueue||(fn=>requestAnimationFrame(fn));
    function update(){
      queued=false;
      const scale=chart.priceScale('right'),options=scale.options();
      if(!options.autoScale||options.invertScale||options.mode!==0)return;
      const range=scale.getVisibleRange?.(),height=chart.panes?.()[0]?.getHeight?.()||host.clientHeight;
      if(!range||!(height>0))return;
      const series=seriesList()[0],top=options.scaleMargins.top,bottom=options.scaleMargins.bottom;
      const upper=series.priceToCoordinate(range.to),lower=series.priceToCoordinate(range.from);
      if(upper==null||lower==null)return;
      const info={priceRange:{minValue:range.from,maxValue:range.to},margins:{above:Math.max(0,upper-height*top),below:Math.max(0,height-1-lower-height*bottom)}};
      const next=margins([info],height);
      if(Math.abs(next.bottom-bottom)<.0001)return;
      // 자동축척 설정을 바꾸지 않아 사용자의 수동 가격축 조작도 유지한다.
      scale.applyOptions({scaleMargins:{top,bottom:next.bottom}});
    }
    function schedule(){if(!queued){queued=true;raf(update);}}
    function track(series){
      if(records.has(series))return series;
      records.add(series);
      series.applyOptions({autoscaleInfoProvider:base=>{const info=base();schedule();return info;}});
      return series;
    }
    function sync(){for(const s of seriesList())if(s)track(s);schedule();}
    chart.timeScale().subscribeVisibleLogicalRangeChange(sync);
    chart.timeScale().subscribeSizeChange(sync);
    sync();
    return {sync,track};
  }
  return {margins,attach};
});
if(typeof window!=='undefined'&&typeof document!=='undefined')document.addEventListener('DOMContentLoaded',()=>{
  const list=()=>[candles,...(window.PriceIndicators?.series?.()||[sma20S,sma60S])];
  const guard=PriceScaleGuard.attach(chart,document.getElementById('chart'),list);
  for(const id of ['priceIndicatorChoice','indicatorChoice'])document.getElementById(id)?.addEventListener('change',guard.sync);
  window.PriceScaleGuard.current=guard;
});
