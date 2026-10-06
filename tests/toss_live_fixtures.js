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
 intervals[0]();assert.equal(refreshes,1);
 intervals[0]();assert.equal(refreshes,1); // throttled, not one REST request per tick
 S.selectedAsOf='2026-01-01';intervals[0]();assert(elements.realtimeLine.textContent.includes('실시간 가격 표시 없음'));
 S.selectedAsOf=null;S.symbol='MSFT';intervals[0]();assert(a.closed);
 a.onmessage({data:JSON.stringify({kind:'trade',price:999,timestamp:new Date().toISOString()})});
 assert(!elements.realtimeLine.textContent.includes('999'));
 S.autoRef=false;intervals[0]();assert(streams[1].closed);assert(elements.realtimeLine.textContent.includes('OFF'));
 S.autoRef=true;now+=5001;intervals[0]();assert.equal(refreshes,1,'no five-second candle polling');
 now+=25000;intervals[0]();assert.equal(refreshes,2,'poll without another trade');
 S.refreshing=true;now+=5001;intervals[0]();assert.equal(refreshes,2,'do not overlap a pending request');
 S.refreshing=false;document.hidden=true;intervals[0]();assert.equal(refreshes,2,'hidden tab does not poll');
 document.hidden=false;S.nextAutoAt=now+10000;intervals[0]();assert.equal(refreshes,2,'preserve error backoff');
 now+=25001;intervals[0]();assert.equal(refreshes,3);
 frame={marketSession:{state:'closed'}};now+=5001;intervals[0]();assert.equal(refreshes,3,'closed does not poll every five seconds');
 now+=55000;intervals[0]();assert.equal(refreshes,4,'closed checks market transition at sixty seconds');
 frame={marketSession:{state:'closed'},fetchedAt:new Date(now-1000).toISOString(),nextConfirmationAt:new Date(now+5000).toISOString()};
 now+=5001;intervals[0]();assert.equal(refreshes,5);assert.equal(options.at(-1).force,true,'buffer transition bypasses source cache');
 now+=5001;intervals[0]();assert.equal(refreshes,5,'force same boundary only once');
 console.log('Toss stream display and market-aware polling guards passed');
})().catch(e=>{console.error(e);process.exit(1)});
