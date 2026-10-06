'use strict';
const assert=require('node:assert/strict');
const {get}=require('../results/dashboard/chart-api.js');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const originalFetch=global.fetch;
(async()=>{
  let aborted=false;
  global.fetch=async(url,{signal})=>new Promise((resolve,reject)=>{
    const fail=()=>{aborted=true;reject(new DOMException('cancelled','AbortError'));};
    if(signal.aborted)fail();else signal.addEventListener('abort',fail,{once:true});
  });
  const ctl=new AbortController();
  const pending=get('/held',1000,ctl.signal);
  ctl.abort();
  await assert.rejects(pending,e=>e.name==='AbortError'&&!e.kind);
  assert(aborted,'caller cancellation must reach fetch');
  await assert.rejects(get('/held',5),e=>e.kind==='timeout'&&e.message.includes('0.005초'));
  global.fetch=async()=>({ok:false,status:429,json:async()=>({kind:'rate-limited',error:'rate limit',upstreamStatus:429,retryAt:'2026-10-04T00:03:00Z'})});
  await assert.rejects(get('/error'),e=>e.status===429&&e.upstreamStatus===429&&e.retryAt==='2026-10-04T00:03:00Z');
  global.fetch=async()=>({ok:true,json:async()=>({symbol:'A'})});
  assert.deepEqual(await get('/ok'),{symbol:'A'});
  // Run the production refresh function: same-selection requests merge, a new
  // selection cancels the old fetch and the cancellation never becomes an error.
  const calls=[];
  global.fetch=async(url,{signal})=>new Promise((resolve,reject)=>{
    calls.push({url,signal,resolve});
    signal.addEventListener('abort',()=>reject(new DOMException('cancelled','AbortError')),{once:true});
  });
  const S={symbol:'A',tf:'D',refreshing:false,failStreak:0,preset:'custom',nextAutoAt:0};
  const ctx={S,Date,Math,AbortController,serverMode:true,reqSeq:0,liveCtl:null,liveRequestKey:null,
    API:'/',REFRESH_MS:60000,apiGet:get,metaKey:(s,t)=>s+'#'+t,
    setBusy:b=>{S.refreshing=b},hideOverlayIfLoading(){},validFrame:()=>true,
    LIVE_D:{},LIVE_H4:{},rememberLiveMeta(){},hideOverlay(){},renderAll(){},renderMarkers(){},paintBasis(){},window:{}};
  vm.createContext(ctx);
  const html=fs.readFileSync(path.join(__dirname,'../results/dashboard/chart-first.html'),'utf8');
  const source=html.slice(html.indexOf('async function refreshLive(opt)'),html.indexOf('/* 검색 제안 선택'));
  vm.runInContext(source,ctx);
  const first=ctx.refreshLive({reason:'manual'});
  await ctx.refreshLive({reason:'manual',force:true});
  assert.equal(calls.length,1,'manual refresh must merge with pending same selection');
  S.symbol='B';
  const next=ctx.refreshLive({reason:'select'});
  assert.equal(calls.length,2);
  assert(calls[0].signal.aborted,'selection change must cancel old network request');
  calls[1].resolve({ok:true,json:async()=>({symbol:'B'})});
  await Promise.all([first,next]);
  assert.equal(S.failStreak,0);
  assert.equal(S.lastErr,null);
  assert.equal(S.refreshing,false);
  assert(ctx.LIVE_D.B&&!ctx.LIVE_D.A,'cancelled response must not update current data');
  console.log('Chart API cancellation, timeout and rate-limit metadata passed');
})().catch(e=>{console.error(e);process.exitCode=1}).finally(()=>{global.fetch=originalFetch});
