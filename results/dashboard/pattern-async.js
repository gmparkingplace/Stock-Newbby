/* 봉 응답과 분리된 패턴 작업만 읽는다. 시세 조회·차트 범위·진입 판단은 건드리지 않는다. */
(function(root){
  'use strict';
  const FIELDS=['patternAnalysis','flagAnalysis','triangleAnalysis','structureAnalysis','structureEvidenceV2'];
  const TFS=new Set(['D','M5','M15','M30','H1','H2','H4']);
  const KEYS=['symbol','timeframe','source','dataRevision','snapshotId','fetchedAt'];
  const normalized=v=>v==null?null:v;
  function identity(selection){
    const f=selection.frame;
    return {symbol:selection.symbol,timeframe:selection.tf,source:normalized(f.source),
      dataRevision:normalized(f.dataRevision),snapshotId:normalized(f.snapshotId),fetchedAt:normalized(f.fetchedAt)};
  }
  function matches(a,b){return !!a&&!!b&&KEYS.every(k=>normalized(a[k])===normalized(b[k]));}
  function create(options){
    const now=options.now||Date.now;
    const records=new WeakMap();
    let active=null,sequence=0,flight=null;
    function selection(){
      const s=options.selection();
      return s&&s.owner&&s.frame&&TFS.has(s.tf)&&s.owner.patternJob?.id?s:null;
    }
    function eligible(s){return !!s&&s.serverMode&&!s.hidden&&!s.refreshing&&s.online!==false;}
    function same(a,b){return !!a&&!!b&&a.owner===b.owner&&a.frame===b.frame&&a.job===b.owner.patternJob&&
      a.id===b.owner.patternJob.id&&matches(a.identity,identity(b))&&a.refresh===b.refresh&&a.api===(b.api||'');}
    function cancel(){
      sequence++;
      if(flight){flight.controller.abort();options.clearTimeout(flight.timer);flight=null;}
      active=null;
    }
    function publish(record,state,code){
      const s=selection();
      if(!eligible(s)||!same(record,s))return false;
      if(state==='error'){
        for(const key of FIELDS){
          const a=s.owner[key];
          if(!a?.enabled||a.sourceStatus==='unsupported')continue;
          // 새 객체로 교체하여 이전 시계열·사건·도형이 남지 않도록 한다.
          s.owner[key]={enabled:true,sourceStatus:'error',symbol:s.symbol,timeframe:s.tf,
            dataRevision:record.identity.dataRevision,sourceFetchedAt:record.identity.fetchedAt,errorCode:code};
        }
      }
      record.state=state;record.errorCode=code||null;
      // 작업 토큰 객체는 보존하고 진단용 상태만 함께 갱신한다.
      record.job.state=state;
      options.render();
      options.status(state,code);
      return true;
    }
    function fail(record,code){publish(record,'error',code);}
    function current(record,seq){
      return sequence===seq&&active===record&&eligible(selection())&&same(record,selection());
    }
    function accept(record,data){
      if(data?.id!==record.id||!matches(data.identity,record.identity))throw new Error('identity-mismatch');
      if(data.state==='error'){fail(record,'pattern-job-error');return;}
      if(data.state==='pending'){
        record.delay=Math.min(1500,Math.max(300,record.delay*1.35,Number(data.retryAfterMs)||0));
        record.nextAt=now()+record.delay;return;
      }
      if(data.state!=='ready'||!data.fields||typeof data.fields!=='object'||Array.isArray(data.fields))throw new Error('invalid-pattern-job');
      const patches={};
      for(const key of FIELDS){
        const value=data.fields[key];
        if(value!==undefined){
          if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('invalid-pattern-fields');
          patches[key]=value;
        }else if(record.owner[key]?.enabled&&record.owner[key]?.sourceStatus==='computing')throw new Error('missing-pattern-field');
      }
      // 명시된 다섯 분석 필드 외에는 어떤 응답 필드도 원 프레임에 복사하지 않는다.
      Object.assign(record.owner,patches);
      publish(record,'ready');
    }
    async function request(record){
      const seq=sequence,controller=new AbortController();
      const mine={controller,timer:null};flight=mine;
      let timedOut=false;
      mine.timer=options.setTimeout(()=>{timedOut=true;controller.abort();},Math.min(8000,Math.max(1,record.deadline-now())));
      try{
        const response=await options.fetch(record.api+'api/pattern-jobs?id='+encodeURIComponent(record.id),{signal:controller.signal,cache:'no-store'});
        if(!current(record,seq)||controller.signal.aborted)return;
        if(response.status===404){fail(record,'unknown-pattern-job');return;}
        if(!response.ok)throw new Error('pattern-job-http');
        const data=await response.json();
        if(!current(record,seq)||controller.signal.aborted)return;
        accept(record,data);
      }catch(error){
        if(!current(record,seq)||controller.signal.aborted&&!timedOut)return;
        record.errors++;
        if(now()>=record.deadline)fail(record,'pattern-job-timeout');
        else if(record.errors>=3)fail(record,'pattern-job-unavailable');
        else {record.delay=Math.min(1500,Math.max(300,record.delay*1.7));record.nextAt=now()+record.delay;}
      }finally{
        options.clearTimeout(mine.timer);
        if(flight===mine)flight=null;
      }
    }
    function tick(){
      const s=selection();
      if(!eligible(s)){cancel();options.status(null);return;}
      if(!same(active,s)){
        cancel();
        let record=records.get(s.owner);
        // 같은 작업의 원천 재조회 취소/실패는 60초 제한을 다시 시작하지 않는다.
        if(record&&same({...record,refresh:s.refresh},s))record.refresh=s.refresh;
        if(!same(record,s)){
          const job=s.owner.patternJob;
          record={owner:s.owner,frame:s.frame,job,id:job.id,identity:identity(s),refresh:s.refresh,
            api:s.api||'',state:job.state,deadline:now()+60000,delay:300,nextAt:now()+Math.max(300,Math.min(1500,Number(job.retryAfterMs)||300)),errors:0};
          records.set(s.owner,record);
        }
        active=record;
        if(!['pending','ready','error'].includes(record.state))record.state='error';
        if(record.state==='error'&&!record.errorCode){fail(record,'pattern-job-error');return;}
        options.status(record.state,record.errorCode);
      }
      if(active.state!=='pending')return;
      if(now()>=active.deadline){
        const record=active;
        if(flight){flight.controller.abort();options.clearTimeout(flight.timer);flight=null;sequence++;}
        fail(record,'pattern-job-timeout');return;
      }
      if(!flight&&now()>=active.nextAt)request(active);
    }
    return {tick,cancel};
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={create,identity,matches,FIELDS};return;}
  let controller=null;
  function status(state,code){
    let el=document.getElementById('patternComputeStatus');
    if(!el&&state){
      const wrap=document.getElementById('chartWrap')||document.getElementById('chart');
      if(!wrap?.parentNode)return;
      el=document.createElement('p');el.id='patternComputeStatus';el.className='hint';
      el.setAttribute('role','status');el.setAttribute('aria-live','polite');el.setAttribute('aria-atomic','true');
      wrap.parentNode.insertBefore(el,wrap);
    }
    if(!el)return;
    el.hidden=state!=='pending'&&state!=='error';
    const text=state==='pending'?'차트 표시 완료 · 패턴 계산 중… · 진입 판단은 별도입니다.'
      :state==='error'?(code==='pattern-job-timeout'?'차트 표시 완료 · 패턴 계산 시간 초과 · 진입 판단은 별도입니다.'
        :'차트 표시 완료 · 패턴 계산 오류 · 진입 판단은 별도입니다.') :'';
    if(el.textContent!==text)el.textContent=text;
    el.dataset.state=state||'';
  }
  function render(){
    for(const name of ['PatternPanel','FlagPanel','TrianglePanel','StructurePanel','StructureEvidencePanel'])root[name]?.render?.();
    // 각 패널이 패턴 도형과 근거선을 갱신한다. 원 캔들·확대 범위·원신호 표식은 그대로 둔다.
  }
  function selected(){
    if(typeof S==='undefined'||typeof curSym!=='function'||typeof frameOf!=='function')return null;
    const frame=frameOf(curSym()),owner=S.tf==='D'?curSym():frame;
    return {symbol:S.symbol,tf:S.tf,frame,owner,serverMode,api:API,hidden:document.hidden,
      refreshing:S.refreshing,online:typeof navigator==='undefined'||navigator.onLine!==false,
      refresh:typeof reqSeq==='undefined'?S.lastRefreshAttemptAt:reqSeq};
  }
  root.PatternAsync={tick:()=>controller?.tick()};
  document.addEventListener('DOMContentLoaded',()=>{
    controller=create({selection:selected,fetch:(...args)=>fetch(...args),render,status,
      setTimeout:(fn,ms)=>setTimeout(fn,ms),clearTimeout:id=>clearTimeout(id)});
    setInterval(()=>controller.tick(),250);
    document.addEventListener('visibilitychange',()=>controller.tick());
    root.addEventListener('offline',()=>controller.tick());
    root.addEventListener('online',()=>controller.tick());
    root.addEventListener('pagehide',()=>{controller.cancel();status(null);});
    controller.tick();
  });
})(typeof window==='undefined'?globalThis:window);
