/* 관찰 상태 판정 모델 (순수 함수, chart-first.html과 검증 테스트가 공유).
   - 입력은 선택 시점 확정 봉에서만 읽는다 (don_hi/lo는 t-1 기준, 미래 참조 없음).
   - 임계값(OBS)은 관찰 설명 규칙 설정값이며 성과 검증값이 아니다.
   - 하나의 판정 결과에 statusId/label/reason/next와 evidence(조건별 근거)를 함께 반환한다.
   - E01: 상단 상태·판단 근거·차트 관찰·강조선이 모두 이 모델을 읽고, 영역마다 조건을 다시 계산하지 않는다.
   - E02: fallback을 무조건 '흐름 약세'라고 부르지 않는다. 약세를 뒷받침하는 조건(종가<장기평균)이
     있어야 '장기 평균 아래'로, 없으면 중립적으로 '추가 조건 확인 중'으로 표시한다.
   - null과 0을 구분한다: null이면 missingReason, 0은 실제 값으로 다룬다.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.ObsModel = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var OBS = { proxATR: 0.5, nearLowATR: 1.0, volOk: 1.0, rsiLo: 30, rsiHi: 50 };
  var RULE_VERSION = "OBS-2026-09-07";

  var UNIT_PRICE = "price", UNIT_RSI = "rsi", UNIT_RATIO = "ratio", UNIT_ATR = "atr";

  var FIELD_LABEL = {
    close: "종가", sma60: "장기 평균", sma20: "단기 평균",
    don_hi: "최근 고점", don_lo: "직전 저점", rsi14: "RSI",
    vol_ratio: "거래량 비율", atr14: "ATR",
  };

  function judgeObs(st, ctx) {
    ctx = ctx || {};
    var fmtP = ctx.price || function (v) { return (v == null) ? "-" : String(Math.round(v * 100) / 100); };
    var fmtA = ctx.atr || function (v) { return (v == null) ? "-" : (Math.round(v * 100) / 100) + " ATR"; };
    var avg = ctx.avgWord || function (n) { return n + "기간 평균"; };

    var base = {
      symbol: ctx.symbol || "", timeframe: ctx.timeframe || "D",
      sourceVersion: ctx.sourceVersion || "", ruleVersion: RULE_VERSION,
      barTime: st ? st.time : null, observationAsOf: st ? st.time : null,
      confirmed: !!ctx.confirmed,
    };
    var ev = [];
    function push(o) {
      var row = {
        role: "context", operator: null, result: "unknown", unit: UNIT_PRICE,
        basisTime: st ? st.time : null, sourceField: "", missingReason: null,
      };
      for (var k in o) { if (Object.prototype.hasOwnProperty.call(o, k)) row[k] = o[k]; }
      ev.push(row);
    }
    function comp(id, label, obs, ref, op, src) {
      var known = !(obs == null) && !(ref == null);
      var r = "unknown";
      if (known) {
        if (op === "<") r = obs < ref ? "pass" : "fail";
        else if (op === ">") r = obs > ref ? "pass" : "fail";
        else if (op === "<=") r = obs <= ref ? "pass" : "fail";
        else if (op === ">=") r = obs >= ref ? "pass" : "fail";
      }
      return { id: id, role: "decisive", label: label, observedRaw: obs, referenceRaw: ref,
        operator: op, result: r, unit: UNIT_PRICE, basisTime: st ? st.time : null,
        sourceField: src, missingReason: known ? null : "입력 부족" };
    }
    function compCtx(id, label, obs, ref, op, src) {
      var row = comp(id, label, obs, ref, op, src);
      row.role = "context";
      return row;
    }
    function within(id, label, obs, lo, hi, src, unit) {
      var known = !(obs == null);
      return { id: id, role: "decisive", label: label, observedRaw: obs,
        referenceRaw: lo + "~" + hi, operator: "within",
        result: !known ? "unknown" : (obs > lo && obs < hi) ? "pass" : "fail",
        unit: unit || UNIT_RSI, basisTime: st ? st.time : null, sourceField: src,
        missingReason: known ? null : "입력 부족" };
    }
    function fact(id, label, obs, src, unit) {
      return { id: id, role: "context", label: label, observedRaw: obs, referenceRaw: null,
        operator: null, result: obs == null ? "unknown" : "pass", unit: unit || UNIT_PRICE,
        basisTime: st ? st.time : null, sourceField: src,
        missingReason: obs == null ? "입력 부족" : null };
    }
    function finish(statusId, label, reason, next, matchedRule, ev2) {
      var m = {};
      for (var k in base) { if (Object.prototype.hasOwnProperty.call(base, k)) m[k] = base[k]; }
      m.statusId = statusId; m.label = label; m.reason = reason; m.next = next;
      m.matchedRule = matchedRule; m.evidence = ev2;
      return m;
    }

    if (!st || st.close == null) {
      push({ id: "close", role: "decisive", label: "종가", observedRaw: null, referenceRaw: null,
        result: "unknown", missingReason: "가격 자료 없음", sourceField: "close" });
      return finish("unknown", "확인 불가",
        "가격 자료가 부족해 관찰 상태를 판정하지 못했어요.",
        "자료가 들어오면 장기 평균과 거래량을 확인해요.",
        { id: "unknown", operator: "FALLBACK", conditionIds: [] }, ev);
    }
    var close = st.close;
    var miss = function (v) { return v == null; };
    var hasAny = !miss(st.sma60) || !miss(st.sma20) || !miss(st.don_hi) ||
      !miss(st.don_lo) || !miss(st.rsi14) || !miss(st.vol_ratio) || !miss(st.atr14);
    if (!hasAny) {
      push({ id: "close", role: "decisive", label: "종가", observedRaw: close, referenceRaw: null,
        operator: null, result: "pass", unit: UNIT_PRICE, basisTime: st.time,
        sourceField: "close", missingReason: null });
      ["sma60", "sma20", "don_hi", "don_lo", "rsi14", "vol_ratio", "atr14"].forEach(function (f) {
        if (miss(st[f])) push({ id: f, label: FIELD_LABEL[f] || f, observedRaw: null, referenceRaw: null,
          result: "unknown", missingReason: "판단 입력 없음", sourceField: f });
      });
      return finish("unknown", "확인 불가",
        "종가 " + fmtP(close) + "는 보이지만 판단 입력이 부족해요.",
        "평균·고점·거래량 입력이 들어오는지 확인해요.",
        { id: "unknown", operator: "FALLBACK", conditionIds: [] }, ev);
    }
    var atr = (!miss(st.atr14) && st.atr14 > 0) ? st.atr14 : null;

    // 1. 저점 이탈 확인 (종가 < 직전 저점)
    if (!miss(st.don_lo) && close < st.don_lo) {
      ev.push(comp("breaklow_low", "종가 < 직전 저점", close, st.don_lo, "<", "don_lo"));
      if (atr) {
        ev.push({ id: "breaklow_dist", role: "context", label: "이탈 거리",
          observedRaw: (st.don_lo - close) / atr, referenceRaw: null, operator: null,
          result: "pass", unit: UNIT_ATR, basisTime: st.time, sourceField: "atr14", missingReason: null });
      } else {
        ev.push({ id: "breaklow_dist", role: "context", label: "이탈 거리", observedRaw: null,
          referenceRaw: null, operator: null, result: "unknown", unit: UNIT_ATR,
          basisTime: st.time, sourceField: "atr14", missingReason: "ATR 입력 부족" });
      }
      if (!miss(st.vol_ratio)) ev.push(fact("breaklow_vol", "거래량 비율", st.vol_ratio, "vol_ratio", UNIT_RATIO));
      else ev.push({ id: "breaklow_vol", label: "거래량 비율", observedRaw: null, referenceRaw: null,
        operator: null, result: "unknown", unit: UNIT_RATIO, basisTime: st.time,
        sourceField: "vol_ratio", missingReason: "거래량 입력 부족", role: "context" });
      var distA = atr ? fmtA((st.don_lo - close) / atr) : "";
      return finish("breaklow", "최근 10봉 최저가 아래",
        (ctx.confirmed ? "종가 " : "현재 봉 가격 ") + fmtP(close) + "가 앞선 10개 봉의 최저가 " + fmtP(st.don_lo) + " 아래예요" +
          (distA ? " · 이탈 " + distA : "") + ".",
        "기준 가격 " + fmtP(st.don_lo) + " 위로 돌아오는지 확인해요. 이 표시만으로 바닥이나 반등을 판단하지 않아요.",
        { id: "breaklow", operator: "AND", conditionIds: ["breaklow_low"] }, ev);
    }
    // 2. 반등 시도 (RSI 30~50 + 종가 > 단기 평균)
    if (!miss(st.rsi14) && st.rsi14 > OBS.rsiLo && st.rsi14 < OBS.rsiHi &&
        !miss(st.sma20) && close > st.sma20) {
      ev.push(within("rebound_rsi", "RSI 범위", st.rsi14, OBS.rsiLo, OBS.rsiHi, "rsi14", UNIT_RSI));
      ev.push(comp("rebound_close_sma20", "종가 > " + avg(20), close, st.sma20, ">", "sma20"));
      if (!miss(st.sma60)) ev.push(compCtx("rebound_close_sma60", "장기 평균 회복 여부", close, st.sma60, ">", "sma60"));
      else ev.push({ id: "rebound_close_sma60", role: "context", label: "장기 평균 회복 여부",
        observedRaw: null, referenceRaw: null, operator: ">", result: "unknown", unit: UNIT_PRICE,
        basisTime: st.time, sourceField: "sma60", missingReason: "장기 평균 입력 부족" });
      return finish("rebound", "반등 시도",
        "RSI " + (st.rsi14 == null ? "-" : Math.round(st.rsi14 * 10) / 10) +
          "가 침체권 위, 종가가 " + avg(20) + " 위예요.",
        avg(60) + " 회복과 거래량 증가 여부를 확인해요.",
        { id: "rebound", operator: "AND", conditionIds: ["rebound_rsi", "rebound_close_sma20"] }, ev);
    }
    // 3. 상승 흐름 (종가 > 장기 평균 + 단기 > 장기)
    if (!miss(st.sma60) && !miss(st.sma20) && close > st.sma60 && st.sma20 > st.sma60) {
      ev.push(comp("uptrend_close_sma60", "종가 > " + avg(60), close, st.sma60, ">", "sma60"));
      ev.push(comp("uptrend_sma20_sma60", avg(20) + " > " + avg(60), st.sma20, st.sma60, ">", "sma60"));
      if (!miss(st.vol_ratio)) ev.push(fact("uptrend_vol", "거래량 비율(추가 맥락)", st.vol_ratio, "vol_ratio", UNIT_RATIO));
      else ev.push({ id: "uptrend_vol", label: "거래량 비율(추가 맥락)", observedRaw: null,
        referenceRaw: null, operator: null, result: "unknown", unit: UNIT_RATIO,
        basisTime: st.time, sourceField: "vol_ratio", missingReason: "거래량 입력 부족", role: "context" });
      var calm = !miss(st.vol_ratio) && st.vol_ratio < OBS.volOk;
      return finish("uptrend", "상승 흐름",
        "종가가 " + avg(60) + " 위, " + avg(20) + "도 " + avg(60) + " 위예요." +
          (calm ? " 거래량은 평균보다 적어 눌림인지 봐요." : ""),
        "평균 배열 유지와 거래량 되살아남 여부를 확인해요.",
        { id: "uptrend", operator: "AND", conditionIds: ["uptrend_close_sma60", "uptrend_sma20_sma60"] }, ev);
    }
    // 4. 기준선 접근 주시 (고점까지 거리 ATR proxATR 이내, 위쪽)
    if (!miss(st.don_hi) && atr &&
        (st.don_hi - close) / atr > 0 && (st.don_hi - close) / atr <= OBS.proxATR) {
      ev.push(comp("watch_close_hi", "종가 < 최근 고점", close, st.don_hi, "<", "don_hi"));
      ev.push({ id: "watch_dist_hi", role: "decisive", label: "고점까지 거리",
        observedRaw: (st.don_hi - close) / atr, referenceRaw: OBS.proxATR,
        operator: "<=", result: "pass", unit: UNIT_ATR, basisTime: st.time,
        sourceField: "don_hi", missingReason: null });
      if (!miss(st.vol_ratio)) ev.push(fact("watch_vol", "거래량 비율(보조)", st.vol_ratio, "vol_ratio", UNIT_RATIO));
      else ev.push({ id: "watch_vol", label: "거래량 비율(보조)", observedRaw: null, referenceRaw: null,
        operator: null, result: "unknown", unit: UNIT_RATIO, basisTime: st.time,
        sourceField: "vol_ratio", missingReason: "거래량 입력 부족", role: "context" });
      return finish("watch", "기준선 접근 주시",
        "종가가 최근 고점 " + fmtP(st.don_hi) + " 근처예요.",
        "기준선 돌파와 거래량 동반 여부를 확인해요.",
        { id: "watch", operator: "AND", conditionIds: ["watch_close_hi", "watch_dist_hi"] }, ev);
    }
    // 5. 저점 부근·지지 확인 중 (저점 위 거리 ATR nearLowATR 이내)
    if (!miss(st.don_lo) && atr &&
        (close - st.don_lo) / atr >= 0 && (close - st.don_lo) / atr <= OBS.nearLowATR) {
      ev.push(comp("support_close_lo", "종가 >= 직전 저점", close, st.don_lo, ">=", "don_lo"));
      ev.push({ id: "support_dist_lo", role: "decisive", label: "저점 위 거리",
        observedRaw: (close - st.don_lo) / atr, referenceRaw: OBS.nearLowATR,
        operator: "<=", result: "pass", unit: UNIT_ATR, basisTime: st.time,
        sourceField: "don_lo", missingReason: null });
      if (!miss(st.vol_ratio)) ev.push(fact("support_vol", "거래량 비율(보조)", st.vol_ratio, "vol_ratio", UNIT_RATIO));
      else ev.push({ id: "support_vol", label: "거래량 비율(보조)", observedRaw: null, referenceRaw: null,
        operator: null, result: "unknown", unit: UNIT_RATIO, basisTime: st.time,
        sourceField: "vol_ratio", missingReason: "거래량 입력 부족", role: "context" });
      return finish("support", "저점 부근·지지 확인 중",
        "종가가 직전 저점 " + fmtP(st.don_lo) + " 부근에 머물러요.",
        "저점 지지 유지와 이탈 여부를 확인해요.",
        { id: "support", operator: "AND", conditionIds: ["support_close_lo", "support_dist_lo"] }, ev);
    }
    // 6. 관망 (fallback) — 약세 증거가 없으면 중립 문구
    var underTxt = !miss(st.sma60) ? (close < st.sma60 ? "장기 평균 아래" : "장기 평균 위") + " · " : "";
    var volTxt = !miss(st.vol_ratio) ? "거래량 평균의 " + (Math.round(st.vol_ratio * 100) / 100) + "배" : "거래량 확인 불가";
    var weak = !miss(st.sma60) && close < st.sma60;
    var label = weak ? "관망 · 장기 평균 아래" : "관망 · 추가 조건 확인 중";
    ev.push(fact("flat_close", "종가", close, "close", UNIT_PRICE));
    if (!miss(st.sma60)) ev.push(compCtx("flat_sma60", "종가 > " + avg(60), close, st.sma60, ">", "sma60"));
    else ev.push({ id: "flat_sma60", role: "context", label: "종가 > " + avg(60), observedRaw: null,
      referenceRaw: null, operator: ">", result: "unknown", unit: UNIT_PRICE,
      basisTime: st.time, sourceField: "sma60", missingReason: "장기 평균 입력 부족" });
    if (!miss(st.sma20)) ev.push(compCtx("flat_sma20", "종가 > " + avg(20), close, st.sma20, ">", "sma20"));
    else ev.push({ id: "flat_sma20", role: "context", label: "종가 > " + avg(20), observedRaw: null,
      referenceRaw: null, operator: ">", result: "unknown", unit: UNIT_PRICE,
      basisTime: st.time, sourceField: "sma20", missingReason: "단기 평균 입력 부족" });
    if (!miss(st.sma20) && !miss(st.sma60)) ev.push(compCtx("flat_sma20_sma60", avg(20) + " > " + avg(60), st.sma20, st.sma60, ">", "sma60"));
    else ev.push({ id: "flat_sma20_sma60", role: "context", label: avg(20) + " > " + avg(60), observedRaw: null,
      referenceRaw: null, operator: ">", result: "unknown", unit: UNIT_PRICE,
      basisTime: st.time, sourceField: "sma60", missingReason: "평균 입력 부족" });
    if (!miss(st.vol_ratio)) ev.push(fact("flat_vol", "거래량 비율", st.vol_ratio, "vol_ratio", UNIT_RATIO));
    else ev.push({ id: "flat_vol", label: "거래량 비율", observedRaw: null, referenceRaw: null,
      operator: null, result: "unknown", unit: UNIT_RATIO, basisTime: st.time,
      sourceField: "vol_ratio", missingReason: "거래량 입력 부족", role: "context" });
    var next;
    if (weak) next = avg(60) + " 위 복귀와 거래량 증가를 확인해요.";
    else if (!miss(st.sma20) && !miss(st.sma60) && st.sma20 <= st.sma60)
      next = avg(20) + "이 " + avg(60) + " 위로 오르는지와 거래량을 확인해요.";
    else next = "평균 배열과 거래량 변화를 확인해요.";
    return finish("flat", label,
      "종가 " + fmtP(close) + " · " + underTxt + volTxt + ".",
      next, { id: "flat", operator: "FALLBACK", conditionIds: [] }, ev);
  }

  return { OBS: OBS, RULE_VERSION: RULE_VERSION, judgeObs: judgeObs, FIELD_LABEL: FIELD_LABEL };
});