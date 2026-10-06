(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.EntryModel=factory();})(typeof self!=='undefined'?self:this,function(){
 'use strict';
 const rules={
  A:{name:'추세 전환',rule:'20봉 평균이 60봉 평균을 아래에서 위로 교차하는 봉'},
  B:{name:'침체 반등',rule:'RSI가 직전 봉 30 이하에서 현재 봉 30 위로 회복'},
  C:{name:'고점 돌파',rule:'종가가 직전 20봉의 최고가를 초과'},
  F:{name:'추세·거래량 돌파',rule:'C 돌파 + 종가·20봉 평균이 60봉 평균 위 + 거래량 비율 > 1 + 돌파 폭 > 0.1 ATR'}
 };
 function evaluate({frame,index,selected=['F'],mode='all',maxAtr=.5,timing,provisional=false,historical=false}){
  provisional=timing?.judgmentMode==='live-snapshot';
  const cs=frame?.candles||[],states=frame?.state||[];
  const ids=[...new Set(selected)].filter(k=>rules[k]);
  const signal=(k,i)=>{
    const v=states[i]?.['sig'+k];
    if(['entry','exit','none'].includes(v))return v;
    if(!Array.isArray(frame?.marks?.[k]))return 'missing';
    return frame.marks[k].find(m=>m.time===cs[i]?.time)?.side||'none';
  };
  const line=(k,i)=>(frame?.lines?.[k]||[]).find(p=>String(p.time)===String(cs[i]?.time))?.value;
  const known=Number.isFinite;
  function readiness(k,i){
    const raw=signal(k,i);
    // Positive producer signals already passed the original common readiness gate.
    if(raw==='entry'||raw==='exit')return {ready:true,missing:[]};
    if(raw==='missing')return {ready:false,missing:['전략 자료']};
    // Legacy frames without indicator lines retain their existing signal contract.
    if(!frame?.lines)return {ready:null,missing:[]};
    const st=states[i]||{},requirements=[['SMA 60',line('sma60',i)],['RSI',st.rsi14],['20봉 고점',st.don_hi],['10봉 저점',st.don_lo]];
    if(k==='A')requirements.push(['SMA 20',line('sma20',i)],['직전 SMA 20',line('sma20',i-1)],['직전 SMA 60',line('sma60',i-1)]);
    if(k==='B')requirements.push(['직전 RSI',states[i-1]?.rsi14]);
    if(k==='F')requirements.push(['SMA 20',line('sma20',i)],['ATR',known(st.atr14)&&st.atr14>0?st.atr14:null],['거래량 비율',st.vol_ratio]);
    const missing=requirements.filter(([,v])=>!known(v)).map(([name])=>name);
    return {ready:missing.length===0,missing};
  }
  const rows=Object.keys(rules).map(k=>({id:k,...rules[k],signal:signal(k,index),readiness:readiness(k,index)}));
  const allKnown=ids.length>0&&ids.every(k=>readiness(k,index).ready!==false);
  const matches=i=>ids.length>0&&(mode==='any'?ids.some(k=>signal(k,i)==='entry'):ids.every(k=>signal(k,i)==='entry'));
  const matched=allKnown&&matches(index),exit=ids.some(k=>signal(k,index)==='exit');
  let anchor=null;
  // Only walk backward from the selected bar; future signals cannot affect a historical result.
  for(let i=index;i>=Math.max(0,index-20);i--){
    if(ids.some(k=>signal(k,i)==='exit'))break;
    if(matches(i)){anchor=i;while(anchor>0&&matches(anchor-1)&&index-anchor<20)anchor--;break;}
  }
  const held=(k,i=index)=>known(cs[i]?.close)&&known(states[i]?.don_lo)&&cs[i].close>=states[i].don_lo&&
    (k==='A'?known(line('sma20',i))&&known(line('sma60',i))&&line('sma20',i)>line('sma60',i):known(states[i]?.rsi14)&&states[i].rsi14>30);
  const heldSince=(k,i)=>{for(let j=i+1;j<=index;j++)if(!held(k,j)||signal(k,j)==='exit')return false;return true;};
  let reviewAnchor=null;
  // A/B continuation must originate in a real same-bar combination. C/F still need current entries.
  for(let i=index-1;i>=Math.max(0,index-3);i--){
    if(ids.some(k=>signal(k,i)==='exit'))break;
    if(!matches(i))continue;
    const qualifies=k=>['A','B'].includes(k)?signal(k,i)==='entry'&&heldSince(k,i):signal(k,index)==='entry';
    if(ids.some(k=>['A','B'].includes(k)&&signal(k,i)==='entry'&&heldSince(k,i))&&
      (mode==='any'?ids.some(qualifies):ids.every(qualifies))){reviewAnchor=i;break;}
  }
  const newEvent=matched&&ids.some(k=>['A','B'].includes(k)&&signal(k,index)==='entry');
  const continuation=!exit&&allKnown&&reviewAnchor!==null&&!newEvent;
  // A new crossing owns its reference bar even when an OR breakout was already maintained.
  if(newEvent)anchor=index;
  else if(continuation)anchor=reviewAnchor;
  const reviewMatched=matched||continuation;
  const atr=anchor===null?null:states[anchor]?.atr14;
  const price=cs[index]?.close;
  const breakout=anchor===null?null:states[anchor]?.don_hi;
  const ref=anchor===null?null:(ids.some(k=>k==='C'||k==='F')&&Number.isFinite(breakout)?Math.min(cs[anchor].close,breakout):cs[anchor]?.close);
  const limit=Number.isFinite(atr)&&atr>0&&Number.isFinite(ref)?ref+maxAtr*atr:null;
  const chase=limit!==null&&Number.isFinite(price)&&price>limit;
  const age=anchor===null?null:index-anchor;
  const reviewLowExit=anchor!==null&&ids.some(k=>['A','B'].includes(k)&&signal(k,anchor)==='entry')&&age>0&&age<=3&&known(states[index]?.don_lo)&&price<states[index].don_lo;
  for(const row of rows){
    const k=row.id;
    let recent=null;
    for(let i=index;i>=Math.max(0,index-3);i--){if(signal(k,i)==='exit')break;if(signal(k,i)==='entry'){recent=i;break;}}
    row.signalAge=recent===null?null:index-recent;
    row.phase=row.readiness.ready===false?'unavailable':row.signal==='exit'?'exit':row.signal==='entry'?
      (['C','F'].includes(k)&&signal(k,index-1)==='entry'?'maintained':'new'):
      ['A','B'].includes(k)&&recent!==null&&heldSince(k,recent)?'tracking':'wait';
  }
  const setup=exit||reviewLowExit?'이탈 신호':continuation?`A/B 신호 후 검토 · ${index-reviewAnchor}/3봉`:matched?(provisional?'진입 조건 충족 · 잠정':'진입 조건 충족'):'진입 조건 대기';
  let code='wait',label='조건 대기',reason='선택한 전략의 진입 신호가 아직 충족되지 않았어요.';
  if(!allKnown||!cs[index]){code='blocked';label='자료 부족 · 판단 보류';reason=ids.length?`선택 전략 계산에 필요한 자료 부족: ${[...new Set(ids.flatMap(k=>readiness(k,index).missing))].join(' · ')||'기준 봉'}. 원래 전략의 공통 준비 조건은 유지합니다.`:'전략을 선택하세요.';}
  else if(exit){code='avoid';label='진입 보류 · 이탈 신호';reason='선택한 전략 중 이탈 신호가 있어요. 진입 신호와 충돌하면 보수적으로 보류해요.';}
  else if(reviewLowExit){code='avoid';label='진입 보류 · 저점 이탈';reason='최근 10봉 저점 아래로 내려가 A/B 신호 후 검토를 중단합니다.';}
  else if(chase){code='chase';label='추격 주의 · 진입 보류';reason='신호 발생봉 종가에서 설정한 가격 상한을 넘었어요. 현재 가격을 따라 진입하지 않고 새 조건을 기다려요.';}
  else if(age!==null&&age>3){reason='이전 신호에서 3봉 넘게 지났어요. 과거 진입 화살표를 지금의 진입 허가로 사용하지 않아요.';}
  else if(reviewMatched&&limit===null){code='blocked';label='판단 보류';reason='추격 여부를 확인할 ATR 자료가 부족해요.';}
  else if(reviewMatched){code='candidate';label='진입 검토';reason=continuation?'A/B 신호 후 3봉 이내이며 유지 조건과 추격 상한을 통과했습니다.':'선택 조건과 가격 상한을 충족했어요. 실제 주문·체결을 의미하지 않아요.';}
  const setupDecision={code,label,reason};
  if(historical){code='historical';label='당시 조건 비교';reason='선택한 과거 봉의 결과예요. 현재 진입 안내가 아니에요.';}
  else if(!timing?.judgmentReady){code='blocked';label='진입 판단 보류';reason=timing?.message||'판단 자료를 확인하지 못했어요.';}
  else if(provisional&&code==='candidate'){code='wait';label='봉 확정 대기';reason='봉 마감 기반 전략이에요. 현재 조건은 잠정 충족이며 마감 전에 사라질 수 있어요.';}
  return {version:'ENTRY-2026-10-06',basis:cs[index]?.time,selected:ids,mode,maxAtr,rows,setup,matched,continuation,reviewMatched,
    setupDecision,code,label,reason,judgmentMode:timing?.judgmentMode||'blocked',modeMessage:timing?.message||'',anchorTime:anchor===null?null:cs[anchor].time,signalAge:age,
    referencePrice:ref,referenceType:ids.some(k=>k==='C'||k==='F')&&Number.isFinite(breakout)?'breakout':'signal-close',chaseLimit:limit,chase,provisional,
    combinationNote:ids.includes('C')&&ids.includes('F')?'F는 C 조건을 포함해요. 두 신호가 켜져도 독립적인 확인 두 번이나 높은 승률을 뜻하지 않아요.':null};
 }
 return {evaluate,rules};
});
