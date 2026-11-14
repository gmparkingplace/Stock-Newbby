/* 화면 배치만 정리한다. 기존 제어 요소·저장 키·판단 입력은 그대로 사용한다. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', () => {
    const $ = id => document.getElementById(id);
    const make = (tag, attrs = {}, text) => {
      const el = document.createElement(tag);
      for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
      if (text) el.textContent = text;
      return el;
    };
    function dialog(id, title) {
      const el = make('dialog', {id, class:'workspaceDialog', 'aria-labelledby':id+'Title'});
      const head = make('header', {class:'dialogHead'});
      const h = make('h2', {id:id+'Title'}, title);
      const close = make('button', {type:'button', 'aria-label':title+' 닫기'}, '닫기');
      const body = make('div', {class:'dialogBody'});
      head.append(h, close); el.append(head, body); document.body.append(el);
      let opener;
      const open = trigger => {
        if (!el.open) { window.ContextHelp?.close(); opener = trigger || document.activeElement; el.showModal(); }
      };
      close.addEventListener('click', () => el.close());
      el.addEventListener('cancel', event => {
        if (el.querySelector('.helpContent.isOpen')) { event.preventDefault(); window.ContextHelp?.close(true); }
      });
      el.addEventListener('close', () => {
        window.ContextHelp?.close();
        if (opener?.isConnected) opener.focus({preventScroll:true});
      });
      return {el, body, open};
    }
    const settings = dialog('settingsDialog', '표시 설정');
    const analysis = dialog('analysisDialog', '상세 분석');
    const actions = make('div', {class:'workspaceActions'});
    function action(id, label, target) {
      const b = make('button', {id, type:'button', 'aria-haspopup':'dialog', 'aria-controls':target.el.id}, label);
      b.addEventListener('click', () => target.open(b)); actions.append(b); return b;
    }
    action('openSettings', '표시 설정', settings);
    action('openAnalysis', '상세 보기', analysis);
    document.querySelector('.toolbarActions').append(actions);

    // 차트 주기는 차트 위로 모으고, 장황한 연결 정보는 상세 분석으로 옮긴다.
    const mainTf = document.querySelector('.topbar > .seg');
    mainTf.classList.add('mainTfBar');
    document.querySelector('.chartToolbar').prepend(mainTf);
    const intraday = document.querySelector('.intradayTfBar');
    document.querySelector('.chartToolbar').after(intraday);
    const health = make('p', {id:'dataHealth', class:'dataHealth', role:'status'});
    document.querySelector('.titleline').append(health);
    const feedback = make('p', {id:'lookupFeedback', class:'lookupFeedback', role:'status', hidden:''});
    document.querySelector('.appHeader').append(feedback);
    const originalNet = window.paintNet;
    window.paintNet = function (text) {
      const result = originalNet.apply(this, arguments);
      const quiet = !text || text === '서버 연결됨' || text === '서버 미연결 · 내장 자료';
      feedback.hidden = quiet;
      feedback.textContent = quiet ? '' : text;
      return result;
    };
    const change = make('span', {id:'priceChange', class:'priceChange'});
    const symbolHeading = make('div', {class:'symbolHeading'});
    symbolHeading.append($('symTitle'), make('span', {id:'symbolCode', class:'symbolCode'}));
    const quoteHeading = make('div', {class:'quoteHeading'});
    quoteHeading.append(make('span', {id:'symbolPrice', class:'symbolPrice', 'aria-label':'마지막 자료 가격'}), change);
    document.querySelector('.titleline').prepend(symbolHeading, quoteHeading);

    settings.body.append($('settingsPanel'), $('monitorPanel'));
    const pricePanel = $('priceIndicatorPanel');
    // 도움말과 제어를 같은 창에 둬 팝업이 닫힌 조상에 가려지지 않게 한다.
    settings.body.prepend(pricePanel);
    const readoutSection = make('section', {class:'statusbox', 'aria-label':'선택 봉과 지표 수치'});
    readoutSection.append(make('h2', {}, '봉·지표 수치'), $('selline'), $('priceIndicatorReadout'));
    const details = document.querySelector('.workspaceDetails');
    const groups = [$('groupEntry'), $('groupPatterns'), $('groupEvidence')];
    // 기존 패턴/근거 그룹이 서로 안에 들어가 있던 중첩을 해소한다.
    const patternBody = $('groupPatterns').querySelector('.dgBody');
    const evidenceBody = $('groupEvidence').querySelector('.dgBody');
    for (const id of ['flagPanel','trianglePanel','structurePanel','structureEvidencePanel','patternPanel']) patternBody.append($(id));
    for (const id of ['chartTerms','volumeProfilePanel','priceZonesPanel','cardsHead','cards','evDetail','srcWrap']) evidenceBody.append($(id));
    $('groupEvidence').remove();
    const snapshotDialog = $('patternDialog');
    document.body.append(snapshotDialog); // 사건 팝업은 독립 최상위 창으로 유지
    for (const id of ['basisLine','netState','verdictMeta']) {
      const row = make('div', {class:'sourceStatusRow'}); row.append($(id)); evidenceBody.append(row);
    }
    evidenceBody.prepend($('obsOverlay'));
    // 관찰 오버레이는 기존 렌더러 참조를 위해 원래 노드를 보존한다.
    analysis.body.append(...groups, readoutSection, details);
    // 상세 아래의 앱 정보 외 빈 컨테이너는 화면 레이아웃에 관여하지 않는다.
    $('btnGrounds').addEventListener('click', () => {
      analysis.open(document.activeElement); $('groupEvidence').open = true;
      $('btnGrounds').scrollIntoView({block:'center'});
    });
    // 차트 키보드 Enter는 기존 근거 버튼을 통해 같은 상세 창으로 연결된다.
    const quick = make('button', {type:'button', class:'verdictDetails', 'aria-haspopup':'dialog', 'aria-controls':'analysisDialog'}, '판단 근거 ›');
    quick.addEventListener('click', () => { analysis.open(quick); $('groupEntry').open = true; $('groupEntry').scrollIntoView({block:'start'}); });
    $('verdictPanel').append(quick);
    // 전략군은 자주 바꾸는 판단 입력이므로 상세 설정 밖에서 바로 선택한다.
    // 기존 select의 change 경로를 사용해 판단·근거·표식 갱신을 한 번에 유지한다.
    const familySelect = $('entryFamily');
    const familySwitch = make('div', {id:'strategyFamilySwitch', class:'strategyFamilySwitch', role:'group', 'aria-label':'판단 전략 선택'});
    const familyButtons = [];
    for (const [value, label] of [['legacy','추세추종'], ['low','저점 매수']]) {
      const button = make('button', {type:'button', 'data-entry-family':value, 'aria-pressed':'false', 'aria-controls':'verdictPanel entryPanel chart'}, label);
      button.addEventListener('click', () => {
        if (familySelect.value === value) return;
        familySelect.value = value;
        familySelect.dispatchEvent(new Event('change', {bubbles:true}));
      });
      familyButtons.push(button); familySwitch.append(button);
    }
    $('verdictPanel').before(familySwitch);
    familySelect.closest('label').hidden = true;
    function syncFamilySwitch() {
      const low = S.entryFamily === 'low';
      for (const button of familyButtons) button.setAttribute('aria-pressed', String(button.dataset.entryFamily === (low ? 'low' : 'legacy')));
      familySelect.value = low ? 'low' : 'legacy';
      $('verdictPanel').dataset.family = low ? 'low' : 'legacy';
      $('verdictTag').textContent = (low ? '저점 매수' : '추세추종') + ' · 차트 신호';
    }
    const renderEntry = window.renderEntryPanel;
    window.renderEntryPanel = function () {
      const result = renderEntry.apply(this, arguments); syncFamilySwitch(); return result;
    };
    syncFamilySwitch();
    $('verdictTag').title = '실제 보유와 무관한 차트 신호이며 주문을 실행하지 않습니다.';
    document.querySelector('#groupEntry > summary').textContent = '진입 판단';
    document.querySelector('#groupPatterns > summary').textContent = '패턴·구조';
    document.querySelector('#groupEvidence > summary').textContent = '가격 구간·판단 근거·자료';
    const watchTitle = make('div', {class:'watchTitle'});
    watchTitle.append(make('h2', {}, '관심종목'));
    const watchManage = make('details', {class:'watchManage'});
    watchManage.append(make('summary', {}, '관리'), document.querySelector('#watchlistPanel .wl-actions'));
    watchManage.querySelector('.wl-actions').append($('wlInfo'));
    watchTitle.append(watchManage); $('watchlistPanel').prepend(watchTitle);
    // 자주 쓰는 종목 추가는 관리 메뉴를 거치지 않고 현재 카테고리 아래에서 연다.
    const addSymbol = $('wlAddSymbol');
    addSymbol.textContent = '+ 종목 추가';
    addSymbol.setAttribute('aria-haspopup', 'dialog');
    addSymbol.setAttribute('aria-controls', 'wlSymbolDlg');
    $('wlGroupStrip').after(addSymbol);
    const manageSummary = watchManage.querySelector('summary');
    manageSummary.setAttribute('aria-label', '관심종목 관리');
    manageSummary.setAttribute('aria-expanded', 'false');
    watchManage.addEventListener('toggle', () => manageSummary.setAttribute('aria-expanded', String(watchManage.open)));
    document.addEventListener('click', event => { if (watchManage.open && !watchManage.contains(event.target)) watchManage.open = false; });
    watchManage.addEventListener('keydown', event => {
      if (event.key === 'Escape' && watchManage.open) { event.preventDefault(); event.stopPropagation(); watchManage.open = false; manageSummary.focus(); }
    });
    for (const button of watchManage.querySelectorAll('button')) button.addEventListener('click', () => { watchManage.open = false; });
    for (const id of ['wlGroupDlg','wlManageDlg']) $(id).addEventListener('close', () => { if (!$(id).open) manageSummary.focus({preventScroll:true}); });
    // 기본 화면의 용어 설명·중복 범례는 상세 창에서만 확인한다.
    for (const id of ['chartLegend','lowMarkerLegend']) evidenceBody.append($(id));
    const periodHelp = $('patternPeriodHelp');
    const periodRow = periodHelp.previousElementSibling;
    evidenceBody.append(periodRow, periodHelp, $('chartSignalHelp'));
    const signalHelp = $('chartHead').querySelector('.helpTrigger');
    const helpRow = make('div', {class:'helpRow'}, '차트 신호');
    helpRow.append(signalHelp); evidenceBody.append(helpRow);
    $('chartHead').textContent = '차트';

    function updateHeader() {
      const symbol = curSym(), f = frameOf(symbol), m = LIVE_META[metaKey(S.symbol, S.tf)];
      const lastPrice = f?.candles?.at(-1)?.close;
      $('symTitle').textContent = symbol?.name || symbol?.symbol || '종목 없음';
      $('symTitle').title = $('symTitle').textContent;
      $('symbolCode').textContent = symbol?.symbol || '';
      $('symbolPrice').textContent = Number.isFinite(lastPrice) ? fmtP(lastPrice) : '—';
      $('symbolPrice').title = '마지막 자료 가격 · ' + $('symbolPrice').textContent;
      const parts = [tfWord(), f?.candles?.length ? fmtT(latestTime(f)) : '자료 없음'];
      if (S.lastErr) parts.push(S.lastErr.kind === 'stale' ? '이전 자료 · 갱신 필요' : S.lastErr.kind === 'queue-busy' ? '자료 수집 중' : S.lastErr.kind === 'rate-limited' ? '호출 한도 대기' : '조회 오류 · 이전 자료');
      else if (!serverMode) parts.push('저장 자료');
      else if (m?.cacheHit) parts.push('저장 자료 재사용');
      if (f?.confirmed === false) parts.push('진행봉 포함');
      if (S.tf === 'M' && (f?.candles?.length || 0) < 60) parts.push('월봉 60개 미만 · 전략 자료 부족');
      if (f?.dataWarnings?.length) parts.push('원천 자료 주의 · 상세 확인');
      if (INTRA_TRIAL.has(S.tf)) parts.push('분봉 패턴 시험');
      health.textContent = parts.join(' · ');
      health.dataset.warning = String(!!S.lastErr || INTRA_TRIAL.has(S.tf) || !!f?.dataWarnings?.length);
      const bars = f?.candles || [], last = bars.at(-1), prev = bars.at(-2);
      if (last && prev && prev.close > 0) {
        const percent = (last.close / prev.close - 1) * 100;
        change.textContent = `${percent > 0 ? '+' : ''}${percent.toFixed(2)}%`;
        change.dataset.tone = percent > 0 ? 'up' : percent < 0 ? 'down' : 'neutral';
        change.title = '현재 주기 직전 봉 종가 대비 · 마지막 자료 기준';
      } else change.textContent = '';
    }
    const paint = window.paintBasis;
    window.paintBasis = function () { const result = paint.apply(this, arguments); updateHeader(); return result; };
    updateHeader();
    document.fonts.ready.then(() => {
      const family = 'Pretendard, system-ui, sans-serif';
      chart.applyOptions({layout:{fontFamily:family}});
      window.IndicatorPanel?.chart()?.applyOptions({layout:{fontFamily:family}});
      renderMarkers();
    });
    window.WorkspaceUI = {settings, analysis};
  });
})();
