/* 차트 그림의 공통 색상만 정의한다. 자료·범위·글꼴·개인 설정은 변경하지 않는다. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.ChartTheme=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const colors=Object.freeze({
    background:'#151a22',text:'#abb8cc',grid:'#262e3c',border:'#364051',
    crosshair:'#73839a',crosshairLabel:'#344155',
    up:'#ff777f',down:'#75aaff',
    volumeUp:'rgba(255,119,127,.55)',volumeDown:'rgba(117,170,255,.55)',
    histogramUp:'rgba(255,119,127,.7)',histogramDown:'rgba(117,170,255,.7)',
    sma20:'#9cafff',sma60:'#f1b65d',sma120:'#bf9bff',sma200:'#65cdb6',
    rsi:'#9cafff',macd:'#75aaff',signal:'#f1b65d',atr:'#bf9bff',obv:'#65cdb6',
    threshold:'#8c9ab0',positive:'#69d39b',warning:'#f1b65d',neutral:'#a4afc0',muted:'#8996aa',
    patternUpFill:'#38242c',patternDownFill:'#22324a',patternNeutralFill:'#29313e',
    patternUpHatch:'#65404a',patternDownHatch:'#3c5274',patternNeutralHatch:'#485465'
  });
  function merge(base,extra){
    const result={...base};
    for(const [key,value] of Object.entries(extra||{})){
      if(value&&typeof value==='object'&&!Array.isArray(value))result[key]=merge(base?.[key]||{},value);
      else result[key]=value;
    }
    return result;
  }
  function options(extra){
    return merge({
      layout:{background:{type:'solid',color:colors.background},textColor:colors.text},
      grid:{vertLines:{color:colors.grid},horzLines:{color:colors.grid}},
      rightPriceScale:{borderColor:colors.border},timeScale:{borderColor:colors.border},
      crosshair:{vertLine:{color:colors.crosshair,labelBackgroundColor:colors.crosshairLabel},horzLine:{color:colors.crosshair,labelBackgroundColor:colors.crosshairLabel}}
    },extra);
  }
  // 패턴 SVG 밑그림을 가리지 않으며 실제 배경은 같은 색의 차트 호스트가 담당한다.
  function plotFor(extra){return options(merge({layout:{background:{type:'solid',color:'rgba(21,26,34,0)'}}},extra));}
  return Object.freeze({colors,options,plotFor});
});
