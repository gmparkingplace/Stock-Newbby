(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.ChartTiming=factory();})(typeof self!=='undefined'?self:this,function(){
 'use strict';
 const SNAPSHOT_TTL_MS=90000;
 function patternContext({frame,analysis,selectedAsOf=null,lastError=null,enabled=true,now=Date.now()}){
  const latest=frame?.candles?.at(-1)?.time;
  const historical=selectedAsOf!=null&&selectedAsOf!==latest;
  const age=now-Date.parse(analysis?.sourceFetchedAt);
  const blocked=!historical&&(Boolean(lastError)||!frame?.confirmed&&(!enabled||!Number.isFinite(age)||age<0||age>SNAPSHOT_TTL_MS));
  return {historical,asOf:historical?selectedAsOf:null,blocked};
 }
 function synchronization(x){
  const blocked=(reason,message)=>({realtimeReady:false,reason,message});
  if(x.historical)return blocked('historical','과거 기준 분석 · 실시간 진입 판단 아님');
  const q=x.quote;
  if(!q||q.symbol!==x.symbol)return blocked('quote-missing','실시간 진입 판단 보류 · 같은 종목 체결 확인 대기');
  const t=Date.parse(q.timestamp),age=(x.now-t)/1000;
  if(!Number.isFinite(t))return blocked("invalid-time","실시간 진입 판단 보류 · 체결 시각 확인 불가");
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:/\.(KS|KQ)$/.test(x.symbol)?'Asia/Seoul':'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(t));
  if(x.tf==='D'&&x.basis!==day)return blocked('date-mismatch','실시간 진입 판단 보류 · 가격과 판단 날짜 불일치');
  if(!Number.isFinite(age)||age<0||age>15||q.kind!=='trade'||q.cached||q.connection!=='subscribed'||!q.enabled)
   return blocked('not-live','실시간 진입 판단 보류 · 새 체결 없음 또는 수신 지연');
  // 수집 시각은 캔들이 반영한 마지막 체결 시각이 아니다. 이를 대신 사용하지 않는다.
  const bar=Date.parse(x.barAsOf);
  if(x.source!=='toss'||!Number.isFinite(bar)||bar<t||bar>x.now||x.now-bar>15000)
   return blocked('bar-sync-unverified','실시간 진입 판단 보류 · 체결과 봉·지표 동기화 미확인');
  return {realtimeReady:true,reason:'aligned',message:'체결·판단 시각 일치 · 현재 봉 판단은 잠정'};
 }
 function assess(x){
  const sync=synchronization(x);
  const result=(judgmentMode,reason,message)=>({realtimeReady:sync.realtimeReady,syncReason:sync.reason,
   judgmentMode,judgmentReady:judgmentMode!=='blocked',reason,message});
  if(x.historical)return result('historical','historical','과거 기준 분석 · 당시 조건 비교');
  if(x.lastError)return result('blocked','request-error','진입 판단 보류 · 최신 조회 실패');
  if(!x.source||!x.fetchedAt)return result('blocked','data-missing','진입 판단 보류 · 서버 수집 자료 없음');
  const state=x.marketSession?.state;
  if(!['open','break','closed'].includes(state))return result('blocked','session-unknown','진입 판단 보류 · 시장 운영 정보 미확인');
  if(state==='open'||state==='break'){
   if(!x.enabled)return result('blocked','disabled','진입 판단 보류 · 자동갱신 OFF 또는 숨김 탭');
   const age=x.now-Date.parse(x.fetchedAt);
   if(!Number.isFinite(age)||age<0||age>SNAPSHOT_TTL_MS)return result('blocked','snapshot-expired','진입 판단 보류 · 마지막 조회 후 앱 유효기간 90초 초과');
   if(!x.snapshotEligible)return result('blocked','snapshot-ineligible','진입 판단 보류 · 현재 거래일 스냅샷 미확인');
   return result('live-snapshot','live-snapshot','최신 캔들 기반 잠정 · 공급처 지연 미확인 (앱 유효기간 90초)');
  }
  if(x.confirmed)return result('closed-confirmed','closed-confirmed','확정봉 기준 · 다음 거래 시점 가격 미반영');
  return result('blocked','confirmation-missing','진입 판단 보류 · 확정봉과 마감 후 재조회 미확인');
 }
 return {assess,patternContext};
});
