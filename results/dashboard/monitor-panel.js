/* Server-owned daily monitoring. Browser polling reads state, never source prices. */
(function(){
  'use strict';
  function importItems(state){
    const items=[];
    for(const group of state?.groups||[])for(const row of group.symbols||[])items.push({symbol:row.symbol,name:row.name,groups:[group.name]});
    return items;
  }
  function rowLabel(row,enabled){
    if(!enabled||!row.enabled)return '서버 감시 중지';
    const status={'rules-disabled':'선택한 규칙 꺼짐 · 보류',waiting:'수집 대기',collecting:'수집 중',watching:'최근 일봉 확인 · 잠정','confirmed-history':'확정봉 기록 · 현재 가격 미반영','waiting-session':'다음 세션 대기','calendar-unknown':'시장 일정 미확인 · 보류','waiting-confirmation':'마감 자료 확인 대기',error:'조회 실패 · 새 판단 보류'}[row.status]||'감시 대기';
    if(row.status==='watching'&&!row.provisionalEligible)return `${row.profile==='focus'?'집중 30초':'일반 5분'} · 이전 일봉 조회 · 현재 판단 보류`;
    return `${row.profile==='focus'?'집중 30초':'일반 5분'} · ${status}`;
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={importItems,rowLabel};return;}
  const $=id=>document.getElementById(id);let state=null,token=null,busy=false,timer=null,preview=null,cursor=0,events=[],stopped=false,windowEnds={};
  const eventLabels={confirmed:'종가 확인',retested:'돌파선 재확인',failed:'패턴 실패',revised:'원천 정정'};
  const types={'bull-flag':'상승 플래그 (Bull)','bear-flag':'하락 플래그 (Bear)','prior-20-high':'직전 20봉 고점','prior-10-low':'직전 10봉 저점','user-resistance':'지정 저항','user-support':'지정 지지','ascending-triangle':'상승 삼각형','descending-triangle':'하락 삼각형','symmetrical-triangle':'대칭 삼각형'};
  async function request(path,body,method='POST'){
    const headers={'Content-Type':'application/json'};
    if(body){
      if(!token)token=(await request('/api/analysis-session')).sessionToken;
      headers['X-Chart-Session']=token;
    }
    const response=await fetch(API+path.replace(/^\//,''),{method:body?method:'GET',headers,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(10000)});
    const data=await response.json();
    if(!response.ok){if(response.status===403)token=null;const error=new Error(data.kind||'조회 실패');error.status=response.status;throw error;}
    return data;
  }
  function error(e){$('monitorError').hidden=false;$('monitorError').textContent=({ 'configuration-changed':'설정이 변경됐습니다. 최신 목록을 확인하고 다시 저장하세요.','invalid-request-or-limit':'주식 최대 20개, 집중 최대 3개를 확인하세요.'})[e.message]||'서버 감시 요청 실패 · 기존 설정은 유지합니다.';}
  function clock(t){return t?new Date(t).toLocaleString('ko-KR'):'—';}
  function render(){
    if(!state)return;
    $('monitorPanel').hidden=false;
    $('monitorToggle').textContent=state.enabled?'감시 일시정지':'감시 시작';$('monitorToggle').setAttribute('aria-pressed',String(state.enabled));
    $('monitorState').textContent=`${state.enabled?'감시 실행 중':'감시 중지'} · ${state.items.length}/20종목 · 오류 ${state.errorCount} · 마지막 성공 ${clock(state.lastSuccessAt)} · 다음 예정 ${clock(state.nextDueAt)}`+(state.interruption?` · 서버 중단 ${clock(state.interruption.fromAt)} ~ ${clock(state.interruption.resumedAt)}`:'');
    $('monitorImport').disabled=state.migrations.includes('local-watchlists-v1');
    const list=$('monitorRows');
    const preserveFocus=list.contains(document.activeElement);
    if(!preserveFocus)list.replaceChildren();
    for(const r of preserveFocus?[]:state.items){
      const div=document.createElement('div');div.className='monitorRow';
      const name=document.createElement('strong');name.textContent=r.name;div.append(name);
      const desc=document.createElement('span');desc.className='monitorStatus';desc.textContent=rowLabel(r,state.enabled)+(r.sourceDate?` · 봉 ${r.sourceDate}`:'');desc.title=`원천 조회 ${clock(r.lastSuccessAt)} · 다음 예정 ${clock(r.nextDueAt)}`;div.append(desc);
      const select=document.createElement('select');select.setAttribute('aria-label',`${r.name} 감시 주기`);
      for(const [v,t] of [['normal','일반 5분'],['focus','집중 30초']]){const o=document.createElement('option');o.value=v;o.textContent=t;select.append(o);}select.value=r.profile;
      select.onchange=()=>edit(r.symbol,{profile:select.value});div.append(select);
      const label=document.createElement('label');const check=document.createElement('input');check.type='checkbox';check.checked=r.enabled;check.onchange=()=>edit(r.symbol,{enabled:check.checked});label.append(check,document.createTextNode('감시'));div.append(label);
      const remove=document.createElement('button');remove.type='button';remove.textContent='삭제';remove.onclick=()=>edit(r.symbol,null);div.append(remove);list.append(div);
    }
    const history=$('monitorEvents');history.replaceChildren();
    const visibleEvents=events.filter(e=>PatternWindow.within(e,[state.items.find(r=>r.symbol===e.symbol)?.sourceDate,windowEnds[e.symbol]].filter(Boolean).sort().at(-1)));
    for(const e of visibleEvents){const b=document.createElement('button');b.type='button';b.textContent=`${e.symbol} · ${e.confirmedBarTime} · ${types[e.type]||e.type} · ${eventLabels[e.eventType]||e.eventType}${e.origin==='initial-history'?' · 초기 이력':''}`;b.onclick=()=>PatternPanel.openEvent(e);history.append(b);}
    if(!visibleEvents.length)history.textContent='최근 3개월 발생 기록 없음';
    if(window.Watchlist)Watchlist.render();
  }
  function plain(r){return {symbol:r.symbol,name:r.name,enabled:r.enabled,profile:r.profile,rules:r.rules,note:r.note,groups:r.groups};}
  async function mutate(path,body){
    if(busy)return;busy=true;
    try{state=await request(path,body);$('monitorError').hidden=true;render();}
    catch(e){error(e);await pollState().catch(()=>{});}
    finally{busy=false;}
  }
  function edit(symbol,patch){
    const items=state.items.filter(r=>patch||r.symbol!==symbol).map(r=>r.symbol===symbol?{...plain(r),...patch}:plain(r));
    return mutate('/api/monitor/watchlist',{items,configRevision:state.configRevision});
  }
  async function pollState(){state=await request('/api/monitor/status');render();}
  async function more(){
    const data=await request('/api/monitor/events?cursor='+cursor);cursor=data.nextCursor;
    Object.assign(windowEnds,data.windowEnds||{});
    const ids=new Set(events.map(e=>e.eventId));events.push(...data.events.filter(e=>!ids.has(e.eventId)));events=events.slice(-200);render();
  }
  async function poll(){
    clearTimeout(timer);
    if(document.hidden||stopped)return;
    if(!serverMode){timer=setTimeout(poll,1000);return;}
    try{if(!busy){await pollState();await more();}}
    catch(e){if(e.status===503){stopped=true;$('monitorPanel').hidden=true;state=null;}else error(e);}
    finally{if(!stopped)timer=setTimeout(poll,5000);}
  }
  window.MonitorPanel={active:()=>!!state,manages:s=>!!state?.items.some(r=>r.symbol===s),row:s=>{const r=state?.items.find(r=>r.symbol===s);return r?{label:rowLabel(r,state.enabled),basis:r.sourceDate,fetchedAt:r.lastSuccessAt}:null;},state:()=>state,poll};
  document.addEventListener('DOMContentLoaded',()=>{
    if(!/^https?:$/.test(location.protocol))return;
    $('monitorToggle').onclick=()=>mutate('/api/monitor/control',{action:state.enabled?'pause':'start'});
    $('monitorAdd').onclick=()=>{
      if(!state)return;
      const symbol=S.symbol;if(state.items.some(r=>r.symbol===symbol))return;
      mutate('/api/monitor/watchlist',{items:[...state.items.map(plain),{symbol,name:curSym()?.name||symbol}],configRevision:state.configRevision});
    };
    $('monitorImport').onclick=async()=>{
      try{const items=importItems(Watchlist.state);const p=await request('/api/monitor/watchlist',{items,mode:'preview',migration:'local-watchlists-v1'});preview={items,configRevision:p.configRevision,mode:'import',migration:'local-watchlists-v1'};
        $('monitorPreviewText').textContent=`저장 후 ${p.items.length}종목 · 신규 ${p.added} · 중복 ${p.duplicates} · 제외 ${p.skipped.join(', ')||'없음'}. 기존 즐겨찾기는 유지합니다.`;$('monitorPreview').hidden=false;
      }catch(e){error(e);}
    };
    $('monitorImportSave').onclick=async()=>{if(!preview)return;await mutate('/api/monitor/watchlist',preview);$('monitorPreview').hidden=true;preview=null;};
    $('monitorRows').addEventListener('focusout',()=>setTimeout(render,0));
    $('monitorImportCancel').onclick=()=>{$('monitorPreview').hidden=true;preview=null;};
    $('monitorMore').onclick=()=>more().catch(error);
    document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)poll();});
    poll();
  });
})();
