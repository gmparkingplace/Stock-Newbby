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
    return withMarket(baseVerdict(entry), market);
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

  function baseVerdict(entry) {
    var code = entry.code;
    if (code === 'blocked') {
      return make('blocked', entry.reason || '판단 자료를 확인하지 못했어요.', '자료 확인 필요');
    }
    if (code === 'historical') {
      return make('blocked', '과거 봉의 조건 비교예요. 현재 판단이 아니에요.', '과거 봉');
    }
    if (code === 'avoid') {
      return make('sell', entry.reason || '선택한 전략의 이탈 신호가 있어요.', '이탈 신호');
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
