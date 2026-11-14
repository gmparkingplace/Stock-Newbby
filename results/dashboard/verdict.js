'use strict';
/* 종합판단: 기존 진입 판단 코드를 관망·홀드·매수·매도로 명시적으로 대응시킨다.
   보유 여부·계좌·주문과 무관한 차트 신호이며, 매핑되지 않은 상태는 판단 보류로 둔다.
   자료 이상(오류·미확정·과거 봉)은 매수·매도로 승격하지 않는다. */
(function (root) {
  var TONES = { buy: 'up', sell: 'down', hold: 'accent', wait: 'neutral', blocked: 'warn' };
  var LABELS = { buy: '매수', sell: '매도', hold: '홀드', wait: '관망', blocked: '판단 보류' };

  function make(code, reason, detail) {
    return { code: code, label: LABELS[code], tone: TONES[code], reason: reason, detail: detail || '' };
  }

  /* 입력: {entry, historical, lastError, market}
     market는 /api/market-context 응답(VIX). 최종 판단에 합치되 보수적 하향에만 쓴다. */
  function usableMarket(market) {
    return !!(market && market.available && market.applicable !== false && !market.stale);
  }

  function verdictFor(input) {
    var entry = (input && input.entry) || null;
    var historical = !!(input && input.historical);
    var market = (input && input.market) || null;

    if (historical) {
      return make('blocked', '과거 봉을 보고 있어요. 현재 판단이 아니에요.', '과거 봉');
    }
    if (!entry) {
      return make('blocked', '선택한 주기의 자료가 필요해요.', '자료 없음');
    }
    if (input.lastError) {
      return make('blocked', '최근 조회에 문제가 있어 판단을 보류해요.', '조회 오류');
    }
    return withMarket(baseVerdict(entry, input.formatPrice), market);
  }

  /* VIX 위험 국면은 매수·홀드를 관망으로 낮춘다. 매도를 매수로 뒤집거나
     관망을 매수로 올리지 않는다. 확인된 이탈 신호와 판단 보류는 그대로 둔다. */
  function withMarket(base, market) {
    if (!usableMarket(market) || base.code === 'blocked') return base;
    if (market.level === 'high') {
      if (base.code === 'buy' || base.code === 'hold') {
        return make('wait', '시장 변동성이 매우 큰 구간이라 신규 진입 판단을 보류했어요.', '시장 위험');
      }
      return base;
    }
    if (market.level === 'elevated' && (base.code === 'buy' || base.code === 'hold')) {
      return { code: base.code, label: base.label, tone: base.tone,
        reason: base.reason + ' 시장 변동성이 평소보다 높아요.', detail: base.detail };
    }
    return base;
  }

  function sellNumbers(entry, formatPrice) {
    var selected = entry.selected || [];
    var evidence = (entry.exitEvidence || []).filter(function (e) {
      return selected.includes(e.strategy) && e.status === 'met' &&
        (e.basis == null || entry.basis == null || e.basis === entry.basis) &&
        Number.isFinite(e.observed) && Number.isFinite(e.reference);
    });
    var seen = new Set();
    var parts = evidence.filter(function (e) {
      var key = [e.id, e.observed, e.reference, e.previousObserved, e.previousReference].join('|');
      if (seen.has(key)) return false;
      seen.add(key); return true;
    }).map(function (e) {
      var fmt = function (v) {
        if (e.id === 'rsi-cross-down-70') return Number(v).toFixed(2).replace(/\.00$/, '');
        return typeof formatPrice === 'function' ? formatPrice(v) : Number(v).toLocaleString('ko-KR', { maximumFractionDigits: 4 });
      };
      if (e.id === 'prior-10-low') return '종가 ' + fmt(e.observed) + ' < 직전 10봉 저점 ' + fmt(e.reference);
      if (e.id === 'sma-cross-down') return '20봉 평균 ' + fmt(e.observed) + '이 60봉 평균 ' + fmt(e.reference) + ' 아래로 교차';
      if (e.id === 'rsi-cross-down-70') return 'RSI가 ' + fmt(e.previousObserved) + '에서 ' + fmt(e.observed) + '로 내려와 70 하향 이탈';
      return e.label + ' · ' + fmt(e.observed) + ' ' + (e.operator || '<') + ' ' + fmt(e.reference);
    });
    if (!parts.length) return '';
    var triggered = Array.from(new Set(evidence.map(function (e) { return e.strategy; }))).join('/');
    return triggered + ' 매도 조건: ' + parts.join(' · ') + (entry.provisional ? ' · 진행봉 잠정' : ' · 확정봉 기준');
  }

  function sellExplanation(entry) {
    var evidence = (entry.exitEvidence || []).filter(function(e) {
      return (entry.selected || []).includes(e.strategy) && e.status === 'met' &&
        (e.basis == null || entry.basis == null || e.basis === entry.basis);
    });
    var ids = new Set(evidence.map(function(e) { return e.id; }));
    var parts = [];
    if (ids.has('prior-10-low')) parts.push('최근 10개 봉의 최저가보다 가격이 낮아졌어요. 최근 저점을 지키며 반등할 것이라는 기대가 깨져, 이 전략은 추가 하락 위험을 줄이는 쪽으로 매도 신호를 내요.');
    if (ids.has('sma-cross-down')) parts.push('최근 20개 봉의 평균 가격이 60개 봉의 평균 아래로 내려왔어요. 단기 흐름이 장기 흐름보다 약해지는 전환이라, 이 전략은 상승 흐름을 따라 보유할 근거가 약해졌다고 봐요.');
    if (ids.has('rsi-cross-down-70')) parts.push('RSI가 과열 기준인 70 이상에서 그 아래로 내려왔어요. 강했던 상승 속도가 둔화된 것으로 보고, 이 전략은 반등 수익을 지키는 쪽으로 매도 신호를 내요.');
    if (!parts.length) {
      if (entry.family === 'low') return entry.reason + ' 이 전략에서 해당 저점 구조를 매수 근거로 더 이상 사용하지 않는다는 뜻이에요. 실제 보유 여부를 확인한 주문 지시는 아니에요.';
      return (entry.reason || '선택한 전략에서 원천 이탈 신호가 나왔어요.') + ' 세부 조건을 검증할 자료가 없어 매도 이유를 더 구체적으로 단정할 수 없어요.';
    }
    parts.push(entry.provisional ? '다만 진행 중인 봉이라 마감 전에 회복하면 이 신호가 사라질 수 있어요.' : '확정봉에서 확인된 조건이지만, 이후 가격의 하락을 보장하지는 않아요.');
    return parts.join(' ');
  }

  function baseVerdict(entry, formatPrice) {
    var code = entry.code;
    if (code === 'blocked') {
      return make('blocked', entry.reason || '판단 자료를 확인하지 못했어요.', '자료 확인 필요');
    }
    if (code === 'historical') {
      return make('blocked', '과거 봉의 조건 비교예요. 현재 판단이 아니에요.', '과거 봉');
    }
    if (code === 'avoid') {
      return Object.assign(make('sell', sellExplanation(entry), '이탈 신호'), { evidenceText: sellNumbers(entry, formatPrice) });
    }
    if (code === 'candidate') {
      if (entry.continuation) {
        return make('hold', '앞선 신호의 유지 조건이 계속 충족되고 있어요. 신규 진입은 추격 여부를 확인하세요.', '신호 유지');
      }
      return make('buy', entry.reason || '선택한 전략의 진입 조건을 충족했어요.', '신규 신호');
    }
    if (code === 'chase') {
      return make('wait', '추격 주의선을 넘었어요. 새 조건을 기다리세요.', '추격 주의');
    }
    if (code === 'wait') {
      return make('wait', entry.reason || '선택한 전략의 진입 신호가 아직 없어요.', '조건 대기');
    }
    return make('blocked', '이 상태는 종합판단으로 표시하지 않아요.', '확인 필요');
  }

  var api = { verdictFor: verdictFor, LABELS: LABELS, TONES: TONES, usableMarket: usableMarket };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.Verdict = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
