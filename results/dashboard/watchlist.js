'use strict';
/* Grouped watchlist: user-defined groups, per-symbol entry status, background sequential lookup.
   Does not modify S, LIVE_D, LIVE_H4, renderAll, or chart-control state.
   Non-selected symbol responses are stored only in the list-only memory cache. */
window.Watchlist = (() => {
  const KEY = 'cf_watchlists_v1';
  const REFRESH_MS = 60000;
  const BACKOFF_MAX = 480000;

  let state = { version: 1, activeGroupId: null, groups: [] };
  let mem = {}; // per symbol#tf: {payload, lastError, failStreak, nextAt, generation}
  let nextRequestAt = 0;
  let inFlight = null; // {symbol, tf, generation}
  let corrupted = false;
  let storageBlocked = false;

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (parsed.version !== 1) return null;
      if (!Array.isArray(parsed.groups)) return null;
      for (const g of parsed.groups) {
        if (typeof g.id !== 'string' || typeof g.name !== 'string') return null;
        if (!Array.isArray(g.symbols)) return null;
        for (const s of g.symbols) {
          if (typeof s.symbol !== 'string' || typeof s.name !== 'string') return null;
        }
      }
      const ids = new Set();
      for (const g of parsed.groups) {
        if (ids.has(g.id)) return null;
        ids.add(g.id);
      }
      for (const g of parsed.groups) {
        const syms = new Set();
        for (const s of g.symbols) {
          if (syms.has(s.symbol)) return null;
          syms.add(s.symbol);
        }
      }
      return parsed;
    } catch (e) {
      return null;
    }
  }

  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify(state));
      storageBlocked = false;
    } catch (e) {
      storageBlocked = true;
    }
  }

  function activeGroup() {
    return state.groups.find(g => g.id === state.activeGroupId) || null;
  }

  function groupKey(symbol, tf) {
    return symbol + '#' + tf;
  }

  function memFor(symbol, tf) {
    const key = groupKey(symbol, tf);
    if (!mem[key]) mem[key] = { payload: null, lastError: null, failStreak: 0, nextAt: 0, generation: 0 };
    return mem[key];
  }

  function invalidate(symbol, tf) {
    const key = groupKey(symbol, tf);
    if (mem[key]) mem[key].generation++;
  }

  function init() {
    const loaded = load();
    if (loaded) {
      state = loaded;
      if (!state.activeGroupId || !state.groups.some(g => g.id === state.activeGroupId)) {
        state.activeGroupId = state.groups[0]?.id || null;
      }
    } else {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        corrupted = true;
        render();
        return;
      }
      const id = crypto.randomUUID();
      state = { version: 1, activeGroupId: id, groups: [{ id, name: '관심 종목', symbols: [] }] };
      save();
    }
    render();
  }

  function tick(now) {
    if (inFlight || now < nextRequestAt || now < S.nextAutoAt) return;
    if (!serverMode || !S.autoRef || document.hidden || S.refreshing) return;
    const group = activeGroup();
    if (!group) return;
    let oldest = null;
    for (const s of group.symbols) {
      if (s.symbol === S.symbol || window.MonitorPanel?.manages(s.symbol)) continue;
      const m = memFor(s.symbol, S.tf);
      if (m.nextAt <= now) {
        if (!oldest || m.nextAt < oldest.m.nextAt) oldest = { symbol: s.symbol, m };
      }
    }
    if (!oldest) return;
    nextRequestAt = now + 10000;
    inFlight = { symbol: oldest.symbol, tf: S.tf, generation: oldest.m.generation };
    fetchSymbol(oldest.symbol, S.tf).then(() => {
      inFlight = null;
      render();
    }).catch(() => {
      inFlight = null;
      render();
    });
  }

  async function fetchSymbol(symbol, tf) {
    const m = memFor(symbol, tf);
    const gen = m.generation;
    try {
      const ep = tf === 'H4' ? 'api/intraday' : 'api/lookup';
      const j = await apiGet(API + ep + '?code=' + encodeURIComponent(symbol));
      if (gen !== m.generation) return;
      if (!validFrame(j)) {
        m.lastError = { kind: 'provider', msg: '응답 형식 오류(봉 없음)', at: new Date() };
        m.failStreak++;
        m.nextAt = Date.now() + Math.min(REFRESH_MS * Math.pow(2, m.failStreak), BACKOFF_MAX);
        return;
      }
      m.payload = j;
      m.lastError = null;
      m.failStreak = 0;
      m.nextAt = Date.now() + REFRESH_MS;
    } catch (e) {
      if (gen !== m.generation) return;
      m.lastError = { kind: (e && e.kind) || 'network', msg: String((e && e.message) || e).slice(0, 120), at: new Date() };
      m.failStreak++;
      m.nextAt = Math.max(Date.now() + Math.min(REFRESH_MS * Math.pow(2, m.failStreak), BACKOFF_MAX), Date.parse(e?.retryAt) || 0);
    }
  }

  function rowState(symbol, tf) {
    const monitored = window.MonitorPanel?.row(symbol);
    if (monitored && symbol !== S.symbol) return {code:'wait',label:'일봉 패턴 감시 · '+monitored.label,basis:monitored.basis,fetchedAt:monitored.fetchedAt,provisional:false,timeframe:'D',family:'pattern-monitor'};
    const m = memFor(symbol, tf);
    if (symbol === S.symbol) {
      const f = frameOf(curSym());
      if (!f || !f.candles.length) return { code: 'blocked', label: '자료 없음', basis: null, fetchedAt: null, source: null, provisional: false };
      const out = evaluateEntryContext({ family:S.entryFamily||'legacy',lowSelected:S.lowStrategies||['R','H'],frame: f, index: f.candles.length - 1, symbol, tf, historical: false,
        selected: S.entryStrategies || ['F'], mode: S.entryMode || 'all', maxAtr: S.entryMaxAtr || .5,
        quote: window.__tossQuote?.()||null, lastError: S.lastErr, enabled: S.autoRef && !document.hidden, now: Date.now() });
      if (!out) return { code: 'blocked', label: '자료 없음', basis: null, fetchedAt: null, source: null, provisional: false };
      return { code: out.code, label: out.label, basis: out.observationBasis, fetchedAt: out.fetchedAt, source: out.source, provisional: out.provisional,family:out.family,settingsId:out.settingsId };
    }
    if (!serverMode) return { code: 'blocked', label: '서버 미연결 · 판단 보류', basis: null, fetchedAt: null, source: null, provisional: false };
    if (m.lastError) return { code: 'blocked', label: '조회 실패 · 판단 보류', basis: null, fetchedAt: null, source: null, provisional: false, error: m.lastError };
    if (!m.payload) return { code: 'wait', label: inFlight && inFlight.symbol === symbol ? '조회 중' : '조회 대기', basis: null, fetchedAt: null, source: null, provisional: false };
    const f = ChartUtil.selectFrame(m.payload, tf, tf === 'H4' ? m.payload : null);
    if (!f?.candles || !f.candles.length) return { code: 'blocked', label: '자료 없음', basis: null, fetchedAt: null, source: null, provisional: false };
    const out = evaluateEntryContext({ family:S.entryFamily||'legacy',lowSelected:S.lowStrategies||['R','H'],frame: f, index: f.candles.length - 1, symbol, tf, historical: false,
      selected: S.entryStrategies || ['F'], mode: S.entryMode || 'all', maxAtr: S.entryMaxAtr || .5,
      quote: null, lastError: null, enabled: S.autoRef && !document.hidden, now: Date.now() });
    if (!out) return { code: 'blocked', label: '자료 없음', basis: null, fetchedAt: null, source: null, provisional: false };
    return { code: out.code, label: out.label, basis: out.observationBasis, fetchedAt: out.fetchedAt, source: out.source, provisional: out.provisional,family:out.family,settingsId:out.settingsId };
  }

  function render() {
    const panel = document.getElementById('watchlistPanel');
    if (!panel) return;
    const strip = document.getElementById('wlGroupStrip');
    const rows = document.getElementById('wlRows');
    const empty = document.getElementById('wlEmpty');
    const info = document.getElementById('wlInfo');
    const err = document.getElementById('wlStorageErr');

    if (corrupted) {
      strip.replaceChildren();
      rows.replaceChildren();
      empty.hidden = false;
      empty.textContent = '즐겨찾기 저장 내용을 읽을 수 없어요';
      info.textContent = '';
      if (err) err.hidden = false;
      return;
    }

    if (storageBlocked) {
      if (err) err.hidden = false;
    } else {
      if (err) err.hidden = true;
    }

    strip.replaceChildren();
    for (const g of state.groups) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = g.name;
      btn.setAttribute('aria-pressed', String(g.id === state.activeGroupId));
      btn.onclick = () => {
        state.activeGroupId = g.id;
        save();
        render();
      };
      strip.appendChild(btn);
    }

    const group = activeGroup();
    if (!group || !group.symbols.length) {
      rows.replaceChildren();
      empty.hidden = false;
      empty.textContent = '등록된 종목이 없어요';
    } else {
      empty.hidden = true;
      const existing = new Map();
      for (const child of rows.children) existing.set(child.dataset.symbol, child);
      // 기존 행 노드를 symbol 키로 갱신 (포커스/스크롤 보존)
      const seen = new Set();
      for (const s of group.symbols) {
        seen.add(s.symbol);
        const st = rowState(s.symbol, S.tf);
        let btn = existing.get(s.symbol);
        if (!btn) {
          btn = document.createElement('button');
          btn.type = 'button';
          btn.dataset.symbol = s.symbol;
          btn.className = 'wl-row';
          const tone = document.createElement('span');
          tone.className = 'wl-tone';
          tone.setAttribute('aria-hidden', 'true');
          btn.appendChild(tone);
          const nameCell = document.createElement('span');
          nameCell.className = 'wl-row-name';
          btn.appendChild(nameCell);
          const stateCell = document.createElement('span');
          stateCell.className = 'wl-row-state';
          btn.appendChild(stateCell);
          btn.onclick = () => select(s.symbol);
          rows.appendChild(btn);
        }
        const toneName = st.code === 'candidate' ? 'entry' : (st.code === 'avoid' || st.code === 'chase') ? 'exit' : 'neutral';
        const toneEl = btn.querySelector('.wl-tone');
        toneEl.dataset.tone = toneName;
        toneEl.title = toneName === 'entry' ? '진입' : toneName === 'exit' ? '이탈·주의' : '관망';
        btn.querySelector('.wl-row-name').textContent = s.name;
        btn.querySelector('.wl-row-state').textContent = st.label + (st.provisional ? ' (잠정)' : '');
        btn.dataset.timeframe = st.timeframe||S.tf;
        btn.dataset.family = st.family||S.entryFamily||'legacy';
        btn.dataset.basis = st.basis == null ? '' : String(st.basis);
        const titleParts = [s.name, st.label];
        if (st.basis) titleParts.push('판단 기준 ' + fmtT(st.basis));
        if (st.fetchedAt) titleParts.push('자료 조회 ' + fmtClock(st.fetchedAt));
        if (st.error) titleParts.push('오류: ' + st.error.msg);
        btn.title = titleParts.join(' · ');
        btn.setAttribute('aria-label', s.name + ' · ' + st.label + (st.provisional ? ' (잠정)' : ''));
      }
      // 삭제된 종목의 행 제거
      for (const child of [...rows.children]) {
        if (!seen.has(child.dataset.symbol)) child.remove();
      }
    }

    const low=S.entryFamily==='low';
    const strat = low?(S.lowStrategies||['R','H']).map(id=>LowEntryModel.names[id]).join(' + '):(S.entryStrategies || ['F']).join(' + ');
    const mode = low||S.entryMode === 'any' ? 'OR' : 'AND';
    const atr = S.entryMaxAtr || .5;
    info.textContent = `${window.MonitorPanel?.active() ? "서버 등록 종목은 일봉 감시 · " : ""}${tfWord()} · 전략 ${strat} · ${mode} · ${atr} ATR · 최신 기준 · ${!window.MonitorPanel?.active()||group?.symbols.some(s=>!window.MonitorPanel?.manages(s.symbol))?"미등록 목록은 60초 간격 순차 조회":"서버 목록은 일반 5분 / 집중 30초"}`;
  }

  async function select(symbol) {
    const key = groupKey(symbol, S.tf);
    const m = mem[key];
    if (m && m.payload && validFrame(m.payload)) {
      const existing = S.tf === 'H4' ? LIVE_H4[symbol] : LIVE_D[symbol];
      if (!existing || (m.payload.fetchedAt && existing.fetchedAt && m.payload.fetchedAt >= existing.fetchedAt)) {
        if (S.tf === 'H4') LIVE_H4[symbol] = m.payload;
        else LIVE_D[symbol] = m.payload;
        rememberLiveMeta(symbol, m.payload, S.tf);
      }
    }
    S.lastErr = null;
    S.failStreak = 0;
    S.nextAutoAt = 0;
    if (m && m.lastError) S.lastErr = m.lastError;

    if (EXP.symbols[symbol] || LIVE_D[symbol]) {
      buildSymList('');
      onSymbolChange(symbol);
    } else {
      const result = await requestNewTicker(symbol);
      if (result && !result.ok && !result.cancelled) {
        if (mem[key]) {
          mem[key].lastError = result.error;
          mem[key].failStreak++;
          mem[key].nextAt = Date.now() + Math.min(REFRESH_MS * Math.pow(2, mem[key].failStreak), BACKOFF_MAX);
        }
        render();
      }
    }
  }

  function addGroup(name) {
    const trimmed = (name || '').trim();
    if (!trimmed) return { ok: false, error: '그룹 이름을 입력해 주세요' };
    if (state.groups.some(g => g.name === trimmed)) return { ok: false, error: '같은 이름의 그룹이 이미 있어요' };
    const id = crypto.randomUUID();
    state.groups.push({ id, name: trimmed, symbols: [] });
    state.activeGroupId = id;
    save();
    render();
    return { ok: true };
  }

  function renameGroup(id, name) {
    const trimmed = (name || '').trim();
    if (!trimmed) return { ok: false, error: '그룹 이름을 입력해 주세요' };
    if (state.groups.some(g => g.name === trimmed && g.id !== id)) return { ok: false, error: '같은 이름의 그룹이 이미 있어요' };
    const g = state.groups.find(g => g.id === id);
    if (!g) return { ok: false, error: '그룹을 찾을 수 없어요' };
    g.name = trimmed;
    save();
    render();
    return { ok: true };
  }

  function deleteGroup(id) {
    if (state.groups.length <= 1) return { ok: false, error: '마지막 하나의 그룹은 삭제할 수 없어요' };
    const g = state.groups.find(g => g.id === id);
    if (!g) return { ok: false, error: '그룹을 찾을 수 없어요' };
    state.groups = state.groups.filter(g => g.id !== id);
    if (state.activeGroupId === id) state.activeGroupId = state.groups[0]?.id || null;
    save();
    render();
    return { ok: true };
  }

  function addSymbol(symbol, name) {
    const fail = error => {
      const el = document.getElementById('wlSymbolErr');
      if (el) { el.hidden = false; el.textContent = error; }
      return { ok: false, error };
    };
    const group = activeGroup();
    if (!group) return fail('활성 그룹이 없어요');
    if (group.symbols.some(s => s.symbol === symbol)) return fail('이미 등록된 종목');
    group.symbols.push({ symbol, name });
    save();
    render();
    const el = document.getElementById('wlSymbolErr');
    if (el) el.hidden = true;
    return { ok: true };
  }

  function removeSymbol(symbol) {
    const group = activeGroup();
    if (!group) return { ok: false, error: '활성 그룹이 없어요' };
    group.symbols = group.symbols.filter(s => s.symbol !== symbol);
    save();
    render();
    return { ok: true };
  }

  function reset() {
    const id = crypto.randomUUID();
    state = { version: 1, activeGroupId: id, groups: [{ id, name: '관심 종목', symbols: [] }] };
    corrupted = false;
    save();
    render();
  }

  function refresh() {
    const group = activeGroup();
    if (!group) return;
    for (const s of group.symbols) {
      if (s.symbol === S.symbol || window.MonitorPanel?.manages(s.symbol)) continue;
      const m = memFor(s.symbol, S.tf);
      m.nextAt = 0;
    }
    render();
  }

  function onSymbolChangeHook(prevSym) {
    // 이전 선택 종목의 LIVE payload와 오류를 목록 메모리에 이관
    if (prevSym) {
      const m = memFor(prevSym, S.tf);
      const live = S.tf === 'H4' ? LIVE_H4[prevSym] : LIVE_D[prevSym];
      if (live && validFrame(live)) {
        if (!m.payload || (live.fetchedAt && m.payload.fetchedAt && live.fetchedAt >= m.payload.fetchedAt)) {
          m.payload = live;
        }
      }
      if (S.lastErr) m.lastError = S.lastErr;
      if (S.failStreak) m.failStreak = S.failStreak;
    }
    // 새 종목의 mem entry를 무효화해 재조회를 유도
    invalidate(S.symbol, S.tf);
    render();
  }

  function onTFChangeHook() {
    invalidate(S.symbol, S.tf);
    render();
  }

  return {
    init, tick, render, select,
    addGroup, renameGroup, deleteGroup, addSymbol, removeSymbol,
    reset, refresh,
    onSymbolChangeHook, onTFChangeHook,
    get state() { return state; },
    get corrupted() { return corrupted; },
    get storageBlocked() { return storageBlocked; },
  };
})();
