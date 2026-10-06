(function(root,factory){
 if(typeof module==='object'&&module.exports)module.exports=factory(require('./low-structure-model.js'));
 else root.LowStructureRules=factory(root.LowStructureModel);
})(typeof self!=='undefined'?self:this,function(Foundation){
 'use strict';
 const version='low-entry-v1';
 const defaults=Object.freeze({leftBars:2,rightBars:2,atrPeriod:14,lookback:60,minSeparation:3,maxSeparation:30,
  minSwingAtr:1,zoneAtr:.2,breachAtr:.1,maxDepthAtr:1,reclaimBars:3,retestBars:8,higherLowAtr:.25,
  testRiseAtr:.1,testNearAtr:.5,triggerAtr:.1,triggerBars:5,reviewBars:3,stopAtr:.2,maxAtr:.5});
 const known=v=>typeof v==='number'&&Number.isFinite(v),terminal=s=>['invalidated','expired','superseded'].includes(s.phase);
 const labels={breached:'지지 이탈 · 회복 대기',reclaimed:'저점 회복 · 재시험 대기',tested:'지지 재확인 · 반등 대기',
  rising:'저점 상승 · 고점 돌파 대기',ready:'진입 검토',invalidated:'구조 실패 · 진입 보류',expired:'조건 만료',superseded:'새 구조로 전환'};
 function parameters(input={}){
  if(!input||typeof input!=='object'||Array.isArray(input)||Object.keys(input).some(k=>!Object.hasOwn(defaults,k)))return null;
  const p={...defaults,...input};
  for(const k of ['leftBars','rightBars','lookback','minSeparation','maxSeparation','reclaimBars','retestBars','triggerBars','reviewBars'])
   if(!Number.isInteger(p[k])||p[k]<1||p[k]>300)return null;
  for(const k of ['minSwingAtr','zoneAtr','breachAtr','maxDepthAtr','higherLowAtr','testRiseAtr','testNearAtr','triggerAtr','stopAtr','maxAtr'])
   if(!known(p[k])||p[k]<=0||p[k]>10)return null;
  if(p.minSeparation>p.maxSeparation||p.maxSeparation>p.lookback||p.breachAtr>=p.maxDepthAtr)return null;
  return p;
 }
 function analyze(input={}){
  if(!input||typeof input!=='object')return Foundation.analyze(input);
  const p=parameters(input.params);
  const foundation=Foundation.analyze({...input,version:Foundation.version,params:p?{leftBars:p.leftBars,rightBars:p.rightBars,atrPeriod:p.atrPeriod}:input.params});
  if(!p||input.version!==undefined&&input.version!==version)return {...foundation,version,stage:'structures',status:'invalid-data',error:{code:!p?'invalid-parameters':'unsupported-version'}};
  const out={...foundation,version,stage:'structures',parameters:p,structures:[],events:[],current:{R:null,H:null},comparison:null};
  if(foundation.error||['unsupported','unavailable','unconfirmed'].includes(foundation.status))return out;
  const bars=input.candles,series=foundation.series,end=series.findLastIndex(b=>b.confirmed);
  const byKnown=new Map();for(const pivot of foundation.pivots){if(!byKnown.has(pivot.knownIndex))byKnown.set(pivot.knownIndex,[]);byKnown.get(pivot.knownIndex).push(pivot);}
  const history=[],events=[],active={R:null,H:null},spent=new Set(),lows=[];let lastLow=null;
  const stamp=i=>bars[i].time;
  const high=(a,b)=>{let index=a;for(let j=a+1;j<=b;j++)if(bars[j].high>bars[index].high)index=j;return {price:bars[index].high,index};};
  const low=(a,b)=>{let index=a;for(let j=a+1;j<=b;j++)if(bars[j].low<bars[index].low)index=j;return {price:bars[index].low,index};};
  const id=(family,indexes)=>JSON.stringify([version,input.symbol.toUpperCase(),input.timeframe,family,indexes.map(stamp),Object.values(p)]);
  function move(s,phase,i,reason){
   if(s.phase===phase)return;s.phase=phase;s.reason=reason||labels[phase];s.phaseAt=stamp(i);s.phaseIndex=i;
   if(terminal(s)){s.endedAt=stamp(i);s.endedIndex=i;}
   events.push({id:JSON.stringify([s.id,phase,stamp(i)]),structureId:s.id,family:s.family,phase,time:stamp(i),index:i,reason:s.reason});
  }
  function create(family,indexes,i,atr,phase,extra){
   const previous=active[family];if(previous&&!terminal(previous))move(previous,'superseded',i,'새로 확인된 구조로 전환');
   const s={id:id(family,indexes),family,phase:null,startedAt:stamp(indexes[0]),knownAt:stamp(i),knownIndex:i,
    anchorTimes:indexes.map(stamp),anchorIndexes:indexes,atrAnchor:atr,signalAt:null,signalIndex:null,
    triggerLevel:null,invalidationLevel:null,chaseLimit:null,...extra};
   history.push(s);active[family]=s;move(s,phase,i);return s;
  }
  function check(s,i,allowSignal=true){
   if(!s||terminal(s))return;
   const b=bars[i],a=s.atrAnchor;
   if(!series[i].priceReady||series[i].segment!==s.segment){move(s,'invalidated',i,'가격 자료 단절 · 구조 종료');return;}
   if(s.family==='R'&&s.recoveredIndex!=null&&b.low<s.springLow-p.testRiseAtr*a){move(s,'invalidated',i,'회복 당시 저점 재이탈');return;}
   if(s.invalidationLevel!=null&&b.low<s.invalidationLevel){move(s,'invalidated',i,'고정 무효선 이탈');return;}
   if(s.phase==='breached'){
    if(b.low<s.springLow){s.springLow=b.low;s.springIndex=i;s.springTime=stamp(i);}
    if(b.low<s.supportZone.lower-p.maxDepthAtr*a){move(s,'invalidated',i,'깊은 이탈 · 해당 전략 제외');return;}
    if(i-s.breachIndex>=p.reclaimBars){move(s,'expired',i,'회복 기한 초과');return;}
    if(b.close>=s.supportZone.upper){s.recoveredIndex=i;s.recoveredAt=stamp(i);s.invalidationLevel=s.springLow-p.testRiseAtr*a;move(s,'reclaimed',i);}
   }
   if(s.phase==='reclaimed'){
    if(i-s.recoveredIndex>p.retestBars){move(s,'expired',i,'재시험 확인 기한 초과');return;}
    const pivot=(byKnown.get(i)||[]).find(q=>q.kind==='low'&&q.index>s.recoveredIndex&&q.segment===s.segment&&
     q.price>=s.springLow+p.testRiseAtr*a&&q.price>=s.supportZone.lower&&q.price<=s.supportZone.upper+p.testNearAtr*a);
    if(pivot){
     const peak=high(s.recoveredIndex,pivot.index-1);
     if(peak.price-pivot.price>=p.minSwingAtr*a){
      s.testIndex=pivot.index;s.testTime=pivot.occurredAt;s.testPrice=pivot.price;s.testKnownAt=pivot.knownAt;
      s.testKnownIndex=i;s.peakIndex=peak.index;s.peakPrice=peak.price;s.triggerLevel=peak.price+p.triggerAtr*a;
      s.invalidationLevel=pivot.price-p.stopAtr*a;
      move(s,'tested',i);
      if(low(pivot.index,i).price<s.invalidationLevel){move(s,'invalidated',i,'저점 확인 전에 무효선 이탈');return;}
     }
    }
   }
   if(['tested','rising'].includes(s.phase)){
    const q=s.family==='R'?s.testKnownIndex:s.knownIndex;
    if(i-q>=p.triggerBars){move(s,'expired',i,'반등 돌파 대기 기한 초과');return;}
    if(allowSignal&&b.close>s.triggerLevel){s.signalAt=stamp(i);s.signalIndex=i;s.referencePrice=b.close;
     s.chaseLimit=b.close+p.maxAtr*a;move(s,'ready',i);}
   }
   if(s.phase==='ready'){
    if(i-s.signalIndex>p.reviewBars)move(s,'expired',i,'신호 후 검토 기한 초과');
    else if(b.close<s.triggerLevel)move(s,'invalidated',i,'반등 기준 아래로 종가 복귀');
   }
  }
  for(let i=0;i<=end;i++){
   check(active.R,i);check(active.H,i,false);
   if(!series[i].priceReady){lastLow=null;continue;}
   for(const pivot of byKnown.get(i)||[]){
    if(pivot.kind!=='low')continue;
    const previous=lastLow,a=pivot.atrBefore;
    lows.push(pivot);
    if(previous&&previous.segment===pivot.segment&&known(a)&&a>0){
     const gap=pivot.index-previous.index,peak=high(previous.index+1,pivot.index-1);
     if(gap>=p.minSeparation&&gap<=p.maxSeparation&&peak.price-previous.price>=p.minSwingAtr*a){
      out.comparison={knownAt:pivot.knownAt,previousLow:previous.price,latestLow:pivot.price,
       direction:pivot.price-previous.price>=p.higherLowAtr*a?'higher':pivot.price<previous.price?'lower':'same'};
      if(out.comparison.direction==='higher'){
       const s=create('H',[previous.index,pivot.index],i,a,'rising',{segment:pivot.segment,
        previousLow:previous.price,low1Index:previous.index,testIndex:pivot.index,testTime:pivot.occurredAt,
        testKnownAt:pivot.knownAt,testPrice:pivot.price,peakIndex:peak.index,peakPrice:peak.price,
        triggerLevel:peak.price+p.triggerAtr*a,invalidationLevel:pivot.price-p.stopAtr*a});
       if(low(pivot.index,i).price<s.invalidationLevel)move(s,'invalidated',i,'저점 확인 전에 무효선 이탈');else check(s,i);
      }
      lastLow=pivot;
     }else if(gap>p.maxSeparation||gap<p.minSeparation&&pivot.price<previous.price||peak.price-previous.price<p.minSwingAtr*a&&pivot.price<previous.price)lastLow=pivot;
    }else lastLow=pivot;
   }
   check(active.H,i);
   if(i<1||!series[i-1].priceReady||!known(series[i-1].atr)||series[i-1].atr<=0||active.R&&!terminal(active.R))continue;
   const a=series[i-1].atr;
   const support=lows.findLast(q=>q.knownIndex<i&&q.segment===series[i].segment&&i-q.index<=p.lookback&&!spent.has(q.index)&&
    high(q.index+1,i-1).price-q.price>=p.minSwingAtr*a);
   if(!support)continue;
   const lower=support.price-p.zoneAtr*a,upper=support.price+p.zoneAtr*a;
   if(bars[i-1].close>=lower&&bars[i].low<lower-p.breachAtr*a){
    spent.add(support.index);
    const s=create('R',[support.index,i],i,a,'breached',{segment:series[i].segment,supportPrice:support.price,
     supportIndex:support.index,supportKnownAt:support.knownAt,supportZone:{lower,upper},breachIndex:i,breachTime:stamp(i),
     springLow:bars[i].low,springIndex:i,springTime:stamp(i)});
    check(s,i);
   }
  }
  out.structures=history.map(s=>({...s,label:labels[s.phase],evidence:evidence(s,bars,series,end,foundation.pivots,p)}));
  out.events=events;
  out.price=bars[end]?.close??null;
  for(const family of ['R','H'])out.current[family]=out.structures.findLast(s=>s.family===family)||null;
  return out;
 }
 function evidence(s,bars,series,index,pivots,p){
  const b=bars[index],a=s.atrAnchor,result=[];
  const add=(id,label,observed,reference,supportive,detail)=>result.push({id,label,basisTime:b.time,knownAt:b.time,
   observed:known(observed)?observed:null,reference:known(reference)?reference:null,
   result:!known(observed)||!known(reference)?'unknown':supportive?'supportive':'warning',detail});
  const mean=(from,to)=>{const rows=bars.slice(from,to+1);return from<0||from>to||!rows.length||rows.some(r=>!known(r.volume))?null:rows.reduce((v,r,j)=>v+(r.volume-v)/(j+1),0);};
  const previous=mean(index-20,index-1),relative=known(previous)&&previous>0&&known(b.volume)?b.volume/previous:null;
  add('relative-volume','직전 20봉 대비 거래량',relative,1,relative>=1,'현재 봉을 평균에서 제외');
  const range=series[index].priceReady?(b.high-b.low)/a:null,position=series[index].priceReady&&b.high>b.low?(b.close-b.low)/(b.high-b.low):null;
  add('range','ATR 대비 봉 범위',range,1,range>=1,'가격 변동 폭이며 방향 신호가 아님');
  add('close-position','봉 안의 종가 위치',position,.6,position>=.6,'범위0 또는 가격 누락은 미확인');
  const extension=known(s.referencePrice)&&known(s.triggerLevel)?(s.referencePrice-s.triggerLevel)/a:null;
  add('initial-extension','최초 돌파봉 상승 폭',extension,p.maxAtr,extension<=p.maxAtr,'첫 신호봉 급등은 별도 위험이며 현재 추격 상한 검사와 다름');
  const peaks=pivots.filter(q=>q.kind==='high'&&q.segment===s.segment&&q.knownIndex<=index&&known(q.price));
  const upper=peaks.filter(q=>q.price>=b.close).sort((x,y)=>x.price-y.price)[0]?.price;
  const stalled=known(relative)&&known(range)&&known(position)&&known(upper)?relative>=1.5&&range<.75&&position<=.4&&upper-b.close<=a:null;
  add('upward-stall','저항 부근 상승 정체',stalled===null?null:Number(stalled),1,stalled===false,'고거래량·좁은 범위도 위치에 따라 다른 의미, 분산 확정 아님');
  let initial=null,test=null;
  if(s.family==='R'){
   const stop=s.springIndex,from=s.supportIndex+1;
   let peak=from;for(let j=from;j<stop;j++)if(bars[j].high>bars[peak].high)peak=j;
   initial=mean(peak,stop);
   if(s.testIndex!=null)test=mean(s.peakIndex,s.testIndex);
  }else{
   let peak=Math.max(0,s.low1Index-10);for(let j=peak+1;j<s.low1Index;j++)if(bars[j].high>bars[peak].high)peak=j;
   initial=mean(peak,s.low1Index);test=mean(s.peakIndex,s.testIndex);
  }
  const ratio=known(initial)&&initial>0&&known(test)?test/initial:null;
  add('test-volume','조정 파동의 평균 거래량',ratio,1,ratio<1,'파동 길이가 달라도 봉당 평균을 비교');
  const rebound=s.testIndex!=null?mean(s.testIndex+1,index):null;
  const reboundRatio=known(test)&&test>0&&known(rebound)?rebound/test:null;
  add('rebound-volume','반등 파동의 평균 거래량',reboundRatio,1,reboundRatio>=1,'낮은 거래량만으로 공급 약화를 확정하지 않음');
  const trough=s.family==='R'?s.springLow:s.previousLow,top=s.peakPrice;
  const progress=known(top)&&known(trough)&&top>trough&&known(b.close)?(b.close-trough)/(top-trough):null;
  add('rebound-progress','직전 하락폭 대비 회복',progress,1,progress>=1,'보조 비율, 반등 고점 종가 돌파를 대신하지 않음');
  const reference=s.supportPrice??s.testPrice;
  const near=known(reference)&&b.close>=reference&&b.close-reference<=a;
  const absorption=known(relative)&&known(range)&&known(position)?relative>=1.5&&range<.75&&position>=.6&&near:null;
  add('price-response','지지 부근 하락 둔화',absorption===null?null:Number(absorption),1,absorption===true,'거래량 대비 가격 반응의 근사, 매집·흡수 확정 아님');
  let obv=0,valid=true;
  for(let i=s.anchorIndexes[0]+1;i<=index;i++){if(!known(bars[i].volume)||!series[i].priceReady||!series[i-1].priceReady||series[i].segment!==s.segment){valid=false;break;}obv+=Math.sign(bars[i].close-bars[i-1].close)*bars[i].volume;}
  add('obv-change','구조 시작 후 OBV 변화',valid?obv:null,0,obv>=0,'누적값 차이, 실제 순매수 금액 아님');
  const resistance=pivots.filter(q=>q.kind==='high'&&q.segment===s.segment&&q.price>Math.max(s.triggerLevel??Infinity,b.close)).reduce((min,q)=>Math.min(min,q.price),Infinity);
  const risk=known(s.invalidationLevel)?b.close-s.invalidationLevel:null;
  const room=Number.isFinite(resistance)&&risk>0?(resistance-b.close)/risk:null;
  add('resistance-room','알려진 저항까지 가격 여유',room,1.5,room>=1.5,'목표 수익률 아님, 미확인이나 가까운 저항으로 자동 탈락시키지 않음');
  return result;
 }
 return {version,defaults,analyze,labels};
});
