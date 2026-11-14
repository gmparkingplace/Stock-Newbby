/* 기존 관심종목 검색 핸들러 뒤에 포함한다. 차트 검색·시세 수집은 변경하지 않는다. */
(function () {
  'use strict';

  function install() {
    const byId = id => document.getElementById(id);
    const opener = byId('wlAddSymbol');
    const dialog = byId('wlSymbolDlg');
    const input = byId('wlSymbolQ');
    const list = byId('wlSymbolList');
    const error = byId('wlSymbolErr');
    const close = byId('wlSymbolClose');
    const watchlist = window.Watchlist;
    if (!opener || !dialog || !input || !list || !error || !close || !watchlist) return;
    if (dialog.dataset.watchlistSearch === 'ready') return;
    dialog.dataset.watchlistSearch = 'ready';

    let heading = byId('wlSymbolT');
    if (!heading) {
      heading = document.createElement('h2');
      heading.id = 'wlSymbolT';
      dialog.prepend(heading);
    }
    heading.classList.add('wl-symbol-heading');
    dialog.setAttribute('aria-labelledby', heading.id);
    const groupHeading = document.createElement('p');
    groupHeading.id = 'wlSymbolGroup';
    groupHeading.className = 'wl-symbol-group';
    heading.after(groupHeading);
    const status = document.createElement('p');
    status.id = 'wlSymbolStatus';
    status.className = 'hint wl-symbol-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.setAttribute('aria-atomic', 'true');
    list.before(status);
    const descriptions = new Set((input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
    descriptions.add(status.id);
    input.setAttribute('aria-describedby', [...descriptions].join(' '));
    input.setAttribute('aria-controls', list.id);

    let timer = null;
    let controller = null;
    let sequence = 0;
    let groupId = null;
    let addedNotice = '';
    const rows = new Map();
    const symbolKey = symbol => String(symbol || '').trim().toUpperCase();
    const activeGroup = () => watchlist.state.groups.find(group => group.id === watchlist.state.activeGroupId);
    const targetGroup = () => activeGroup()?.id === groupId ? activeGroup() : null;
    const hasSymbol = (group, symbol) => !!group?.symbols.some(item => symbolKey(item.symbol) === symbolKey(symbol));

    function announce(message, state) {
      status.dataset.state = state;
      status.textContent = addedNotice && message !== addedNotice ? addedNotice + ' · ' + message : message;
    }

    function clearError() {
      error.hidden = true;
      error.textContent = '';
    }

    function fail(message) {
      error.textContent = message;
      error.hidden = false;
      announce(message, 'error');
    }

    function invalidate() {
      sequence++;
      clearTimeout(timer);
      timer = null;
      controller?.abort();
      controller = null;
      list.setAttribute('aria-busy', 'false');
    }

    function syncButtons() {
      const group = targetGroup();
      for (const { candidate, button } of rows.values()) {
        const added = hasSymbol(group, candidate.symbol);
        button.disabled = !group || added;
        button.textContent = added ? '추가됨' : '추가';
        button.dataset.added = String(added);
        button.setAttribute('aria-label', candidate.name + ' (' + candidate.symbol + ') ' + (added ? '추가됨' : '추가'));
      }
    }

    function appendCandidate(item) {
      if (!item || typeof item.symbol !== 'string') return;
      const symbol = symbolKey(item.symbol);
      if (!symbol || rows.has(symbol)) return;
      const candidate = {
        symbol,
        name: typeof item.name === 'string' && item.name.trim() ? item.name.trim() : symbol,
        market: typeof item.market === 'string' ? item.market.trim() : ''
      };
      const row = document.createElement('li');
      row.className = 'wl-symbol-result';
      row.dataset.symbol = symbol;
      const identity = document.createElement('span');
      identity.className = 'wl-symbol-identity';
      const name = document.createElement('span');
      name.className = 'wl-symbol-name';
      name.textContent = candidate.name;
      const code = document.createElement('span');
      code.className = 'wl-symbol-code';
      code.textContent = candidate.symbol;
      identity.append(name, document.createTextNode(' '), code);
      if (candidate.market) {
        const market = document.createElement('span');
        market.className = 'wl-symbol-market';
        market.textContent = candidate.market;
        identity.append(document.createTextNode(' '), market);
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'wl-symbol-add';
      button.onclick = () => {
        if (!dialog.open) return;
        const group = targetGroup();
        if (!group) {
          invalidate();
          syncButtons();
          fail('선택 카테고리가 바뀌었어요. 창을 다시 열어 주세요.');
          return;
        }
        // 표시 이후 다른 경로로 등록되었어도 같은 카테고리에는 다시 추가하지 않는다.
        if (hasSymbol(group, candidate.symbol)) {
          syncButtons();
          fail('이미 등록된 종목');
          return;
        }
        button.disabled = true;
        const result = watchlist.addSymbol(candidate.symbol, candidate.name);
        syncButtons();
        if (!result?.ok) {
          fail(result?.error || '종목을 추가하지 못했어요. 다시 시도해 주세요.');
          return;
        }
        clearError();
        addedNotice = candidate.name + ' · ' + group.name + '에 추가했어요';
        if (watchlist.storageBlocked) fail('목록에는 추가했지만 저장하지 못했어요. 저장 오류를 확인해 주세요.');
        else announce(addedNotice, 'success');
      };
      rows.set(symbol, { candidate, button });
      row.append(identity, document.createTextNode(' '), button);
      list.append(row);
    }

    function localCandidates(query) {
      const key = query.toUpperCase();
      const sources = [typeof EXP !== 'undefined' ? EXP.symbols : {}, typeof LIVE_D !== 'undefined' ? LIVE_D : {}];
      for (const source of sources) {
        for (const [symbol, item] of Object.entries(source || {})) {
          const name = item?.name || symbol;
          if (!key || symbol.toUpperCase().includes(key) || String(name).toUpperCase().includes(key)) {
            appendCandidate({ symbol, name });
          }
        }
      }
    }

    function search() {
      invalidate();
      if (!dialog.open) return;
      clearError();
      addedNotice = '';
      rows.clear();
      list.replaceChildren();
      if (!targetGroup()) {
        fail('선택 카테고리가 없어요. 카테고리를 선택한 뒤 다시 열어 주세요.');
        return;
      }
      const query = input.value.trim();
      const current = sequence;
      localCandidates(query);
      syncButtons();
      if (!query) {
        announce(rows.size ? '저장된 종목 ' + rows.size + '개 · 이름이나 코드로 검색하세요' : '종목명이나 코드를 입력해 검색하세요', 'idle');
        return;
      }
      if (typeof serverMode === 'undefined' || !serverMode || typeof apiGet !== 'function') {
        announce(rows.size ? '저장된 종목 ' + rows.size + '개 · 서버 미연결' : '일치하는 저장 종목 없음 · 서버 연결 후 다시 검색하세요', rows.size ? 'results' : 'empty');
        return;
      }
      list.setAttribute('aria-busy', 'true');
      announce(rows.size ? '검색 중… · 저장된 종목 ' + rows.size + '개' : '검색 중…', 'searching');
      const requestController = new AbortController();
      controller = requestController;
      const isCurrent = () => current === sequence && !requestController.signal.aborted && dialog.open
        && input.value.trim() === query && !!targetGroup();
      timer = setTimeout(async () => {
        timer = null;
        try {
          const data = await apiGet(API + 'api/search?q=' + encodeURIComponent(query), 20000, requestController.signal);
          if (!isCurrent()) return;
          if (!Array.isArray(data?.results)) throw new Error('검색 응답 형식 오류');
          for (const item of data.results) appendCandidate(item);
          syncButtons();
          // 로컬 결과와 합친 수를 사용한다. 원격 결과가 비어도 로컬 후보를 지우지 않는다.
          announce(rows.size ? '검색 결과 ' + rows.size + '개' : '일치하는 종목 없음', rows.size ? 'results' : 'empty');
        } catch (_) {
          if (!isCurrent()) return;
          fail(rows.size ? '원격 검색 실패 · 저장된 검색 결과는 추가할 수 있어요' : '종목 검색 실패 · 잠시 후 다시 검색하세요');
        } finally {
          if (current === sequence && controller === requestController) {
            list.setAttribute('aria-busy', 'false');
            controller = null;
          }
        }
      }, 300);
    }

    // 기존 onclick/oninput만 대체한다. 닫기와 초점 복귀는 원래의 네이티브 모달에 맡긴다.
    opener.onclick = () => {
      invalidate();
      groupId = activeGroup()?.id || null;
      heading.textContent = '종목 추가';
      groupHeading.textContent = activeGroup() ? '선택 카테고리 · ' + activeGroup().name : '선택 카테고리 없음';
      input.value = '';
      if (!dialog.open) dialog.showModal();
      search();
      input.focus();
    };
    input.oninput = search;
    close.addEventListener('click', invalidate, { capture: true });
    dialog.addEventListener('cancel', invalidate);
    dialog.addEventListener('close', () => {
      // 닫기 직후 다시 열었을 때 큐에 남은 이전 close 이벤트가 새 검색을 취소하지 않는다.
      if (!dialog.open) invalidate();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, { once: true });
  else install();
})();
