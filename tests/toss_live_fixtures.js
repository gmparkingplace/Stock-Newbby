'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
(async()=>{
 const listeners={},elements={},streams=[],intervals=[];let refreshes=0,priceLines=0;
 const S={symbol:'AAPL',tf:'D',autoRef:true,selectedAsOf:null,sourceKind:'live',refreshing:false,nextAutoAt:0};
 let now=Date.now(),frame={marketSession:{state:'open'}},options=[];
 class Clock extends Date {static now(){return now}}
 const document={hidden:false,addEventListener:(type,fn)=>{listeners[type]=fn},getElementById:id=>elements[id]||(elements[id]={hidden:true,textContent:'',addEventListener(){}})};
 class EventSource {constructor(url){this.url=url;streams.push(this)}close(){this.closed=true}}
 const context={S,document,EventSource,serverMode:true,API:'',location:{protocol:'http:'},Date:Clock,Number,JSON,
  frameOf:()=>frame,curSym:()=>({symbol:S.symbol}),
  setInterval:fn=>intervals.push(fn),fetch:async()=>({ok:true,json:async()=>({provider:'toss',realtime:true})}),
  window:{addEventListener(){}},fmtP:p=>'$'+p,refreshLive:opt=>{refreshes++;options.push(opt);S.lastRefreshAttemptAt=now;},
  candles:{createPriceLine:()=>{priceLines++;return {applyOptions(){}}},removePriceLine(){}}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../results/dashboard/toss-live.js'),'utf8'),context);
 await listeners.DOMContentLoaded();
 const a=streams[0];assert(a.url.endsWith('code=AAPL'));
 a.onmessage({data:JSON.stringify({kind:'status',state:'subscribed'})});
 a.onmessage({data:JSON.stringify({kind:'trade',price:240,timestamp:new Date(now).toISOString()})});
 assert(elements.realtimeLine.textContent.includes('시세 수신 시각'));
 assert(!elements.realtimeLine.textContent.includes('240'));
 assert.equal(priceLines,0);
 assert.equal(context.window.__tossQuote().price,240);
 a.onmessage({data:JSON.stringify({kind:'quote',price:241,cached:true,timestamp:new Date(now+1000).toISOString()})});
 assert(elements.realtimeLine.textContent.includes('마지막 시세 시각'),'캐시 시세는 새 체결이 아니다');
 a.onmessage({data:JSON.stringify({kind:'trade',price:239,timestamp:new Date(now-1000).toISOString()})});
 assert.equal(context.window.__tossQuote().price,241,'이전 시각의 체결이 최신 시세를 덮지 않는다');
 now+=16000;intervals[0]();assert(elements.realtimeLine.textContent.includes('새 체결 대기'));
 assert.equal(refreshes,1);
 intervals[0]();assert.equal(refreshes,1); // throttled, not one REST request per tick
 S.selectedAsOf='2026-01-01';assert.equal(context.window.__tossQuote(),null);
 intervals[0]();assert(a.closed);assert.equal(context.window.__tossQuote(),null);
 assert(elements.realtimeLine.textContent.includes('실시간 가격 표시 없음'));
 S.selectedAsOf=null;S.symbol='MSFT';intervals[0]();assert(a.closed);
 a.onmessage({data:JSON.stringify({kind:'trade',price:999,timestamp:new Date().toISOString()})});
 assert(!elements.realtimeLine.textContent.includes('999'));
 S.autoRef=false;intervals[0]();assert(streams[1].closed);assert(elements.realtimeLine.textContent.includes('OFF'));
 S.autoRef=true;now+=5001;intervals[0]();assert.equal(refreshes,1,'no five-second candle polling');
 now+=25000;intervals[0]();assert.equal(refreshes,1,'daily does not poll at thirty seconds');
 now+=30000;intervals[0]();assert.equal(refreshes,2,'daily polls at sixty seconds without another trade');
 S.refreshing=true;now+=5001;intervals[0]();assert.equal(refreshes,2,'do not overlap a pending request');
 S.refreshing=false;document.hidden=true;intervals[0]();assert.equal(refreshes,2,'hidden tab does not poll');
 document.hidden=false;S.nextAutoAt=now+10000;intervals[0]();assert.equal(refreshes,2,'preserve error backoff');
 now+=25001;intervals[0]();assert.equal(refreshes,2);
 now+=30000;intervals[0]();assert.equal(refreshes,3);
 frame={marketSession:{state:'closed'}};now+=5001;intervals[0]();assert.equal(refreshes,3,'closed does not poll every five seconds');
 now+=55000;intervals[0]();assert.equal(refreshes,4,'closed checks market transition at sixty seconds');
 frame={marketSession:{state:'closed'},fetchedAt:new Date(now-1000).toISOString(),nextConfirmationAt:new Date(now+5000).toISOString()};
 now+=5001;intervals[0]();assert.equal(refreshes,5);assert.equal(options.at(-1).force,true,'buffer transition bypasses source cache');
 now+=5001;intervals[0]();assert.equal(refreshes,5,'force same boundary only once');
 S.tf='H4';frame.source='toss';intervals[0]();
 assert(elements.realtimeLine.textContent.includes('4시간봉: 토스 1분봉 집계'));
 frame.source='yfinance';intervals[0]();
 assert(elements.realtimeLine.textContent.includes('4시간봉: yfinance 집계'));
 delete frame.source;intervals[0]();
 assert(elements.realtimeLine.textContent.includes('공급처 확인 중'));
 // 새 범위 계약도 이벤트 없이 전역 상태를 직접 바꿔 1초 동기화를 확인한다.
 const scopedListeners={},scopedElements={},scopedStreams=[],scopedIntervals=[];
 const scopedS={symbol:'AAPL',tf:'D',autoRef:true,selectedAsOf:null,sourceKind:'live',refreshing:false,nextAutoAt:Infinity};
 const scopedFrame={source:'yfinance',fetchedAt:new Date(now-1000).toISOString(),marketSession:{state:'open'},candles:[{close:123}]};
 let providerCalls=0,scopedRefreshes=0,provider={provider:'toss',realtime:true,realtimeScope:'intraday'};
 const intraTFs=['M5','M15','M30','H1','H2','H4'];
 const scopedDocument={hidden:false,addEventListener:(type,fn)=>{scopedListeners[type]=fn},
  getElementById:id=>scopedElements[id]||(scopedElements[id]={hidden:true,textContent:'',addEventListener(type,fn){this[type]=fn}})};
 class ScopedEventSource {constructor(url){this.url=url;scopedStreams.push(this)}close(){this.closed=true}}
 const scopedContext={S:scopedS,document:scopedDocument,EventSource:ScopedEventSource,serverMode:true,API:'',location:{protocol:'http:'},Date:Clock,Number,JSON,
  isIntraTF:tf=>intraTFs.includes(tf),frameOf:()=>scopedFrame,curSym:()=>({symbol:scopedS.symbol}),
  setInterval:(fn,ms)=>{assert.equal(ms,1000);scopedIntervals.push(fn)},
  fetch:async()=>{providerCalls++;return {ok:true,json:async()=>provider}},window:{addEventListener(){}},
  refreshLive:()=>{scopedRefreshes++;scopedS.lastRefreshAttemptAt=now}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../results/dashboard/toss-live.js'),'utf8'),scopedContext);
 await scopedListeners.DOMContentLoaded();
 const tick=()=>{now+=1000;scopedIntervals[0]()};
 assert.equal(scopedStreams.length,0,'새 범위 계약의 일봉은 처음부터 SSE를 열지 않는다');
 for(const tf of ['D','W','M']){
  scopedS.tf=tf;tick();
  assert.equal(scopedStreams.length,0);
  assert(scopedElements.realtimeLine.textContent.startsWith('Yahoo 일봉 기반'));
  assert(!scopedElements.realtimeLine.textContent.includes('새 체결 대기'));
 }
 for(const tf of intraTFs){
  scopedS.tf=tf;tick();
  const stream=scopedStreams.at(-1),before=JSON.stringify(scopedFrame);
  assert(!stream.closed,`${tf}는 1초 이내 SSE를 연다`);
  stream.onmessage({data:JSON.stringify({kind:'trade',price:240,timestamp:new Date(now).toISOString()})});
  assert.equal(scopedContext.window.__tossQuote().price,240);
  assert.equal(JSON.stringify(scopedFrame),before,'체결은 원봉을 바꾸지 않는다');
  scopedS.tf=['D','W','M'][intraTFs.indexOf(tf)%3];
  assert.equal(scopedContext.window.__tossQuote(),null,'다음 동기화 전에도 일·주·월봉 체결은 노출하지 않는다');
  tick();assert(stream.closed);assert.equal(scopedContext.window.__tossQuote(),null);
  stream.onmessage({data:JSON.stringify({kind:'trade',price:999,timestamp:new Date(now).toISOString()})});
  assert.equal(scopedContext.window.__tossQuote(),null,'닫힌 구독의 늦은 체결을 버린다');
 }
 scopedS.tf='M5';scopedS.selectedAsOf='2026-01-01';const count=scopedStreams.length;tick();
 assert.equal(scopedStreams.length,count,'과거 분봉은 구독하지 않는다');
 scopedS.selectedAsOf=null;tick();const live=scopedStreams.at(-1);
 live.onmessage({data:JSON.stringify({kind:'trade',price:240,timestamp:new Date(now).toISOString()})});
 scopedS.selectedAsOf='2026-01-01';tick();assert(live.closed);assert.equal(scopedContext.window.__tossQuote(),null);
 scopedS.selectedAsOf=null;tick();assert(!scopedStreams.at(-1).closed);
 scopedS.autoRef=false;tick();assert(scopedStreams.at(-1).closed);
 scopedS.autoRef=true;tick();scopedDocument.hidden=true;tick();assert(scopedStreams.at(-1).closed);
 scopedDocument.hidden=false;tick();scopedS.symbol='BTC-USD';tick();assert(scopedStreams.at(-1).closed);
 scopedS.symbol='AAPL';scopedContext.serverMode=false;tick();assert(scopedStreams.at(-1).closed);
 scopedContext.serverMode=true;scopedS.tf='D';tick();
 assert.equal(providerCalls,1,'상태 동기화는 공급처 발견 요청을 추가하지 않는다');
 scopedS.nextAutoAt=0;scopedS.lastRefreshAttemptAt=now;tick();assert.equal(scopedRefreshes,0);
 now+=29000;scopedIntervals[0]();assert.equal(scopedRefreshes,0,'장중 일봉은 30초 조회를 금지한다');
 now+=30000;scopedIntervals[0]();assert.equal(scopedRefreshes,1,'장중 일봉은 60초 조회한다');
 scopedS.tf='M5';now+=30000;scopedIntervals[0]();assert.equal(scopedRefreshes,2,'장중 분봉은 30초 조회를 유지한다');
 scopedS.tf='W';now+=30000;scopedIntervals[0]();assert.equal(scopedRefreshes,2,'직접 주봉 전환도 60초로 바뀐다');
 now+=30000;scopedIntervals[0]();assert.equal(scopedRefreshes,3);
 scopedS.tf='M';now+=30000;scopedIntervals[0]();assert.equal(scopedRefreshes,3);
 now+=30000;scopedIntervals[0]();assert.equal(scopedRefreshes,4);
 scopedS.tf='H1';scopedFrame.marketSession.state='break';now+=30000;scopedIntervals[0]();assert.equal(scopedRefreshes,5,'휴식 중 분봉도 기존 30초 주기를 유지한다');
 scopedFrame.marketSession.state='closed';now+=30000;scopedIntervals[0]();assert.equal(scopedRefreshes,5);
 now+=30000;scopedIntervals[0]();assert.equal(scopedRefreshes,6,'폐장 분봉은 60초 조회한다');
 scopedS.tf='D';scopedFrame.nextConfirmationAt=new Date(now+5000).toISOString();
 now+=5001;scopedIntervals[0]();assert.equal(scopedRefreshes,7,'60초 전이라도 확정 경계는 강제 조회한다');
 now+=5001;scopedIntervals[0]();assert.equal(scopedRefreshes,7,'같은 경계의 중복 강제 조회를 막는다');
 // 같은 발견 경로가 새 범위 필드에서 구버전 응답으로 바뀌어도 호환을 복원한다.
 provider={provider:'toss',realtime:true};await scopedElements.btnRefresh.click();
 assert(!scopedStreams.at(-1).closed,'범위 필드가 없는 서버는 일봉 SSE와 호환된다');
 console.log('Toss stream display, intraday scope and market-aware polling guards passed');
})().catch(e=>{console.error(e);process.exit(1)});
