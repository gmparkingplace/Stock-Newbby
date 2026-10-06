#!/usr/bin/env node
'use strict';
const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const Rules=require('../results/dashboard/low-structure-rules'),Context=require('../results/dashboard/low-entry-context'),Window=require('../results/dashboard/pattern-window');
const profiles={baseline:{},'confirm-1':{rightBars:1},'confirm-3':{rightBars:3},'reclaim-2':{reclaimBars:2},'reclaim-5':{reclaimBars:5},'rise-0.1':{higherLowAtr:.1},'rise-0.5':{higherLowAtr:.5}};
function readCache(file){
 const script=`import sqlite3,json,sys\nfrom pathlib import Path\nc=sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=ro',uri=True)\nc.execute('BEGIN')\nrows=c.execute("SELECT key,value FROM entries WHERE key LIKE 'toss|%' OR key LIKE 'yfinance|%'").fetchall()\nc.close()\nf={}\nfor k,v in rows:\n j=json.loads(v);s=j.get('symbol');t=j.get('tf','D')\n if not s or t not in ('D','H4') or not j.get('candles'):continue\n if t=='H4' and not s.endswith('-USD'):continue\n key=(s,t)\n if key not in f or (j.get('fetchedAt') or '')>(f[key].get('fetchedAt') or ''):f[key]=j\nprint(json.dumps(list(f.values())))\n`;
 const r=spawnSync(process.env.PYTHON||'python3',['-c',script,path.resolve(file)],{encoding:'utf8',maxBuffer:40*1024*1024});
 if(r.status!==0)throw new Error('읽기 전용 캐시 조회 실패: '+r.stderr.slice(-350));return JSON.parse(r.stdout);
}
function analyzeFrame(frame,{asOf='latest',now=Date.now(),maxAtr=.5,selected=['R','H']}={}){
 const tf=frame.tf||'D',time=asOf==='latest'?frame.candles.at(-1)?.time:tf==='H4'?Number(asOf):asOf;
 const index=frame.candles.findIndex(b=>b.time===time);if(index<0)throw new Error('해당 시각의 봉 없음');
 return Context.evaluate({frame,index,symbol:frame.symbol,tf,maxAtr,selected,historical:asOf!=='latest',now});
}
function pathStats(s,bars,horizon){
 const from=s.signalIndex+1,rows=bars.slice(from,from+horizon);
 if(rows.length<horizon)return {horizon,complete:false,available:rows.length};
 if(rows.some(b=>![b.open,b.high,b.low,b.close].every(v=>typeof v==='number'&&Number.isFinite(v)&&v>0)))return {horizon,complete:false,reason:'missing-price'};
 if(rows.some((b,i)=>b.high<b.low||b.open<b.low||b.open>b.high||b.close<b.low||b.close>b.high||typeof b.time==='number'&&b.time-(i?rows[i-1].time:bars[s.signalIndex].time)!==14400))return {horizon,complete:false,reason:'gap-or-invalid-price'};
 const ref=rows[0].open;return {horizon,complete:true,nextOpen:ref,maxFavorable:Math.max(...rows.map(b=>b.high))/ref-1,
  maxAdverse:Math.min(...rows.map(b=>b.low))/ref-1,stopTouched:rows.some(b=>b.low<s.invalidationLevel),triggerLost:rows.some(b=>b.close<s.triggerLevel),
  gapPastStop:ref<s.invalidationLevel,gapPastChase:ref>s.chaseLimit};
}
function audit(frames){
 const samples=[];let checks=0;
 for(const frame of frames){
  const bars=frame.candles,cutoff=frame.lastConfirmedTime;
  if(cutoff==null||!bars.some(b=>b.time===cutoff)){samples.push({symbol:frame.symbol,timeframe:frame.tf||'D',status:'confirmation-missing'});continue;}
  const from=Window.start(cutoff),base={symbol:frame.symbol,timeframe:frame.tf||'D',candles:bars,observedThrough:cutoff,confirmedThrough:cutoff};
  const row={symbol:frame.symbol,timeframe:base.timeframe,group:(frame.symbol.endsWith('-USD')?'coin':'stock')+'-'+base.timeframe,
   source:frame.source,fetchedAt:frame.fetchedAt,confirmedThrough:cutoff,firstBar:bars[0].time,loadedBars:bars.length,version:Rules.version,
   priceAdjustment:'source consistency unverified',profiles:{}};
  for(const [name,params] of Object.entries(profiles)){
   const a=Rules.analyze({...base,params});if(a.status==='invalid-data')throw new Error(frame.symbol+': invalid-data '+JSON.stringify(a.error));
   const structures=a.structures.filter(s=>s.startedAt>=from),events=a.events.filter(e=>structures.some(s=>s.id===e.structureId));
   if(new Set(events.map(e=>e.id)).size!==events.length)throw new Error('duplicate-event');
   const phases={},reasons={};for(const e of events){phases[e.phase]=(phases[e.phase]||0)+1;if(['invalidated','expired'].includes(e.phase))reasons[e.reason]=(reasons[e.reason]||0)+1;}
   const signals=structures.filter(s=>s.signalAt),records=[];
   for(const s of signals){
    const at=Rules.analyze({...base,params,observedThrough:s.signalAt,confirmedThrough:s.signalAt});
    const past=at.structures.find(x=>x.id===s.id);
    if(!past||past.phase!=='ready'||past.signalAt!==s.signalAt||past.triggerLevel!==s.triggerLevel||past.invalidationLevel!==s.invalidationLevel)throw new Error('noncausal-signal '+JSON.stringify({symbol:frame.symbol,name,signal:s.signalAt,id:s.id,phase:past?.phase,at:past?.signalAt,trigger:[past?.triggerLevel,s.triggerLevel],stop:[past?.invalidationLevel,s.invalidationLevel],status:at.status,error:at.error}));checks++;
    records.push({family:s.family,knownAt:s.testKnownAt||s.knownAt,signalAt:s.signalAt,phase:s.phase,
     anchorTimes:s.anchorTimes,trigger:s.triggerLevel,invalidation:s.invalidationLevel,chase:s.chaseLimit,
     confirmationDelay:s.testKnownIndex!=null?s.testKnownIndex-s.testIndex:s.knownIndex-s.testIndex,
     evidence:past.evidence,paths:[5,10,20].map(n=>pathStats(s,bars.slice(0,bars.findIndex(b=>b.time===cutoff)+1),n))});
   }
   row.profiles[name]={parameters:{...Rules.defaults,...params},status:a.status,structures:structures.length,phases,reasons,signals:records};
  }
  samples.push(row);
 }
 return {version:Rules.version,scope:'cached confirmed OHLCV; recent three calendar months; no provider requests or cache writes; path statistics are not accuracy or realized returns',profiles,causalSignalChecks:checks,samples};
}
function main(argv){
 const args={};for(let i=0;i<argv.length;i++){if(!argv[i].startsWith('--')||i+1>=argv.length)throw new Error('옵션은 --이름 값 형식');args[argv[i].slice(2)]=argv[++i];}
 const sourceFile=args.input||args.cache||path.join(__dirname,'../logs/market-cache.sqlite3');
 if(args.out){
  const samePath=path.resolve(args.out)===path.resolve(sourceFile);
  const sameFile=fs.existsSync(args.out)&&fs.existsSync(sourceFile)&&fs.statSync(args.out).ino===fs.statSync(sourceFile).ino&&fs.statSync(args.out).dev===fs.statSync(sourceFile).dev;
  if(samePath||sameFile)throw new Error('원본 입력 덮어쓰기 금지');
 }
 const loaded=args.input?JSON.parse(fs.readFileSync(sourceFile,'utf8')):readCache(sourceFile);
 let frames=Array.isArray(loaded)?loaded:loaded.frames||[loaded];if(args.symbol)frames=frames.filter(f=>f.symbol===args.symbol.toUpperCase());if(args.tf)frames=frames.filter(f=>(f.tf||'D')===args.tf);
 if(!frames.length)throw new Error('저장된 종목·주기 자료 없음');
 if(args.strategy&&!['R','H','both'].includes(args.strategy))throw new Error('전략은 R/H/both');
 if(args['max-atr']&&![.25,.5,1].includes(Number(args['max-atr'])))throw new Error('추격 폭은 0.25/0.5/1 ATR');
 const result=args.audit==='true'?audit(frames):frames.map(frame=>{
  const x=analyzeFrame(frame,{asOf:args['as-of']||'latest',now:args.now?Date.parse(args.now):Date.now(),maxAtr:args['max-atr']?Number(args['max-atr']):.5,selected:args.strategy&&args.strategy!=='both'?[args.strategy]:['R','H']});
  if(args.detail==='true')return {symbol:frame.symbol,timeframe:frame.tf||'D',...x};
  const a=x.analysis,from=Window.start(a.observedThrough);
  return {symbol:frame.symbol,timeframe:frame.tf||'D',version:a.version,status:a.status,observedThrough:a.observedThrough,
   confirmedThrough:a.confirmedThrough,source:frame.source,fetchedAt:frame.fetchedAt,dataWarnings:a.dataWarnings,
   scope:'stored snapshot judgment; not current realtime quotes',priceAdjustment:'source consistency unverified',decision:x.decision,
   lowStructures:{current:a.current,comparison:a.comparison,events:a.events.filter(e=>e.time>=from)}};
 });
 const output=JSON.stringify(result,null,2)+'\n';if(args.out)fs.writeFileSync(args.out,output);else process.stdout.write(output);
}
if(require.main===module){try{main(process.argv.slice(2));}catch(e){console.error(e.message);process.exitCode=2;}}
module.exports={readCache,analyzeFrame,audit,pathStats,profiles,main};
