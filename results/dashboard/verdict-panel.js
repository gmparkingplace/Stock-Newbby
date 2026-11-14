'use strict';
/* 종합판단 패널: 기존 진입 판단 렌더가 끝날 때마다 같은 입력으로 요약을 갱신한다.
   판단 계산은 verdict.js의 순수 매핑만 사용하고, 화면 표시 외의 상태는 바꾸지 않는다. */
(function () {
  function stateOf(obs) {
    var historical = !!(typeof S !== 'undefined' && S.selectedAsOf && obs && typeof latestTime === 'function'
      && S.selectedAsOf !== latestTime(obs.f));
    var entry = null;
    if (typeof entryEvaluation === 'function') {
      try { entry = entryEvaluation(obs); } catch (e) { entry = null; }
    }
    return { historical: historical, entry: entry };
  }

  function metaLine(obs, entry) {
    var parts = [];
    if (entry && entry.basis != null && typeof fmtT === 'function') parts.push('기준 봉 ' + fmtT(entry.basis));
    if (entry) {
      parts.push(entry.provisional ? '진행봉 · 잠정' : '확정봉 기준');
      parts.push(entry.family === 'low' ? '저점 매수' : '추세·돌파');
    }
    if (typeof S !== 'undefined' && S.tf) parts.push(S.tf);
    if (entry && entry.fetchedAt && typeof fmtClock === 'function') parts.push('조회 ' + fmtClock(entry.fetchedAt));
    if (typeof S !== 'undefined' && S.lastErr) parts.push('최근 조회 오류');
    return parts.join(' · ');
  }

  function renderVerdictPanel(obs) {
    var panel = document.getElementById('verdictPanel');
    if (!panel) return;
    var st = stateOf(obs);
    var v = window.Verdict.verdictFor({
      entry: st.entry, historical: st.historical,
      lastError: (typeof S !== 'undefined' && S.lastErr) || null,
      market: typeof window.__marketContext === 'function' ? window.__marketContext() : null,
      formatPrice: typeof fmtP === 'function' ? fmtP : null
    });
    var label = document.getElementById('verdictLabel');
    var reason = document.getElementById('verdictReason');
    var meta = document.getElementById('verdictMeta');
    if (label) label.textContent = v.label;
    if (reason) reason.textContent = v.reason;
    var evidence = document.getElementById('verdictEvidence');
    if (evidence) { evidence.textContent = v.evidenceText || ''; evidence.hidden = !v.evidenceText; }
    if (meta) meta.textContent = metaLine(obs, st.entry);
    panel.dataset.verdict = v.code;
    panel.dataset.tone = v.tone;
    panel.dataset.detail = v.detail;
    return v;
  }

  window.VerdictPanel = { render: renderVerdictPanel };

  if (typeof window.renderEntryPanel === 'function') {
    var original = window.renderEntryPanel;
    window.renderEntryPanel = function (obs) {
      var out = original.apply(this, arguments);
      try { renderVerdictPanel(obs); } catch (e) { /* 요약 실패가 진입 판단을 막지 않는다 */ }
      return out;
    };
  }
})();
