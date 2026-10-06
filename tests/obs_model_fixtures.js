#!/usr/bin/env node
/* 관찰 모델 fixture 검증 (E04 1~6).
   실행: node tests/obs_model_fixtures.js
   공통 모델(results/dashboard/obs-model.js)과 페이지가 같은 판정을 사용함을 검증한다.
   - fixture별 제목(label)·핵심 근거(decisive evidence)·관측값·기준값·연산자·결과 대조
   - AND 미충족 사례(종가>SMA60 참, SMA20>SMA60 거짓)의 미충족 원인 설명
   - fallback 약세 단정 금지, 보조 조건은 '추가 맥락'만, null/0 구분
 */
"use strict";
const M = require("../results/dashboard/obs-model.js");

let pass = 0, fail = 0;
function ok(cond, msg) {
  if (cond) { pass++; console.log("  ok - " + msg); }
  else { fail++; console.log("  FAIL - " + msg); }
}
function eq(a, b, msg) { ok(a === b, msg + " (" + JSON.stringify(a) + " == " + JSON.stringify(b) + ")"); }

function ev(model, id) { return model.evidence.find(e => e.id === id); }
function decide(model, id) { return ev(model, id) && ev(model, id).role === "decisive"; }

console.log("== 최근 10봉 최저가 아래 (breaklow) ==");
{
  const m = M.judgeObs({ close: 90, don_lo: 95, atr14: 5, vol_ratio: 1.2, sma20: 92, sma60: 100, rsi14: 25, don_hi: 120, time: "2026-09-03" }, {});
  eq(m.statusId, "breaklow", "statusId");
  eq(m.label, "최근 10봉 최저가 아래", "제목");
  eq(m.matchedRule.operator, "AND", "AND 규칙");
  ok(m.reason.indexOf("90") >= 0 && m.reason.indexOf("95") >= 0, "reason에 실제 관측/기준값 사용");
  const d = ev(m, "breaklow_low");
  ok(d, "핵심 근거 존재");
  eq(d.role, "decisive", "핵심 근거 역할");
  eq(d.observedRaw, 90, "관측값");
  eq(d.referenceRaw, 95, "기준값");
  eq(d.operator, "<", "연산자");
  eq(d.result, "pass", "결과");
  eq(d.sourceField, "don_lo", "sourceField");
  ok(ev(m, "breaklow_dist").observedRaw === 1 && ev(m, "breaklow_dist").unit === "atr", "이탈 거리 ATR 맥락");
  ok(ev(m, "breaklow_vol").role === "context", "거래량은 추가 맥락");
}

console.log("== 반등 시도 (rebound) ==");
{
  const m = M.judgeObs({ close: 105, sma20: 100, sma60: 110, rsi14: 40, vol_ratio: 1.0, don_hi: 140, don_lo: 95, atr14: 8, time: "2026-09-03" }, {});
  eq(m.statusId, "rebound", "statusId");
  eq(m.label, "반등 시도", "제목");
  eq(m.matchedRule.operator, "AND", "AND 규칙");
  const r = ev(m, "rebound_rsi");
  eq(r.observedRaw, 40, "RSI 관측값");
  eq(r.referenceRaw, "30~50", "RSI 기준 범위");
  eq(r.operator, "within", "RSI 범위 연산자");
  eq(r.result, "pass", "RSI 결과");
  const c = ev(m, "rebound_close_sma20");
  eq(c.observedRaw, 105); eq(c.referenceRaw, 100); eq(c.operator, ">"); eq(c.result, "pass");
  ok(ev(m, "rebound_close_sma60").role === "context" && ev(m, "rebound_close_sma60").result === "fail",
    "장기 평균 회복은 추가 맥락(미충족으로 표시)");
}

console.log("== 상승 흐름 (uptrend) ==");
{
  const m = M.judgeObs({ close: 120, sma20: 115, sma60: 100, vol_ratio: 0.8, rsi14: 55, don_hi: 122, don_lo: 105, atr14: 6, time: "2026-09-03" }, {});
  eq(m.statusId, "uptrend", "statusId");
  eq(m.label, "상승 흐름", "제목(눌림 확인 단정 없음)");
  ok(m.reason.indexOf("눌림인지 봐요") >= 0, "거래량 약세를 눌림 확인 완료로 단정하지 않음");
  ok(decide(m, "uptrend_close_sma60") && decide(m, "uptrend_sma20_sma60"), "AND 두 조건이 모두 판정 근거");
  eq(ev(m, "uptrend_vol").role, "context", "거래량은 추가 맥락만");
  ok(m.matchedRule.conditionIds.indexOf("uptrend_vol") < 0, "보조 조건이 matchedRule에 없음");
  ok(ev(m, "uptrend_vol").observedRaw === 0.8 && ev(m, "uptrend_vol").missingReason === null, "거래량 0.8은 값으로 처리(null 아님)");
}

console.log("== 기준선 접근 주시 (watch) ==");
{
  const m = M.judgeObs({ close: 198, don_hi: 200, atr14: 5, vol_ratio: 1.1, sma20: 185, sma60: 190, rsi14: 60, don_lo: 180, time: "2026-09-03" }, {});
  eq(m.statusId, "watch", "statusId");
  eq(m.label, "기준선 접근 주시", "제목");
  ok(decide(m, "watch_close_hi") && decide(m, "watch_dist_hi"), "종가<고점 + 거리/ATR 범위가 판정 근거");
  const d = ev(m, "watch_dist_hi");
  eq(d.observedRaw, 0.4, "고점까지 거리 관측값(ATR)");
  eq(d.referenceRaw, 0.5, "거리 기준(proxATR)");
  eq(d.operator, "<="); eq(d.result, "pass");
  ok(ev(m, "watch_vol").role === "context", "거래량은 보조 조건 구분");
}

console.log("== 저점 부근·지지 확인 중 (support) ==");
{
  const m = M.judgeObs({ close: 98, don_lo: 95, atr14: 5, don_hi: 150, sma20: 100, sma60: 102, rsi14: 45, vol_ratio: 0.9, time: "2026-09-03" }, {});
  eq(m.statusId, "support", "statusId");
  eq(m.label, "저점 부근·지지 확인 중", "제목");
  ok(decide(m, "support_close_lo") && decide(m, "support_dist_lo"), "종가>=저점 + 거리/ATR 범위가 판정 근거");
  const d = ev(m, "support_dist_lo");
  eq(d.observedRaw, 0.6); eq(d.referenceRaw, 1.0); eq(d.operator, "<="); eq(d.result, "pass");
  ok(ev(m, "support_close_lo").observedRaw === 98 && ev(m, "support_close_lo").referenceRaw === 95, "기준선 값(don_lo)을 실제 값으로 표시");
}

console.log("== 관망 · 추가 조건 확인 중 (flat, E04#2: 종가>SMA60 참 / SMA20>SMA60 거짓) ==");
{
  const m = M.judgeObs({ close: 110, sma60: 100, sma20: 95, rsi14: 60, don_hi: 200, don_lo: 80, atr14: 20, vol_ratio: 0.9, time: "2026-09-03" }, {});
  eq(m.statusId, "flat", "statusId");
  eq(m.label, "관망 · 추가 조건 확인 중", "약세 증거 없으면 중립 문구");
  ok(m.label.indexOf("흐름 약세") < 0, "'흐름 약세' 단정 없음");
  eq(m.matchedRule.operator, "FALLBACK", "fallback 표기");
  const c60 = ev(m, "flat_sma60");
  eq(c60.observedRaw, 110); eq(c60.referenceRaw, 100); eq(c60.operator, ">"); eq(c60.result, "pass");
  const a = ev(m, "flat_sma20_sma60");
  eq(a.observedRaw, 95); eq(a.referenceRaw, 100); eq(a.operator, ">"); eq(a.result, "fail");
  ok(a.role === "context", "미충족 원인(단기>장기 실패)이 맥락 근거로 표시");
  ok(m.next.indexOf("20기간 평균") >= 0 && m.next.indexOf("60기간 평균") >= 0, "다음 확인이 구체적 기준 제시");
}

console.log("== 관망 · 장기 평균 아래 (약세 증거 존재) ==");
{
  const m = M.judgeObs({ close: 100, sma60: 105, sma20: 98, rsi14: 60, don_hi: 150, don_lo: 85, atr14: 10, vol_ratio: 1.0, time: "2026-09-03" }, {});
  eq(m.statusId, "flat", "statusId");
  eq(m.label, "관망 · 장기 평균 아래", "종가<장기평균일 때만 장기 평균 아래");
  ok(m.label.indexOf("흐름 약세") < 0, "여전히 '흐름 약세' 단정 없음");
}

console.log("== 확인 불가 (unknown) ==");
{
  const m = M.judgeObs({ close: 100, time: "2026-09-03" }, {});
  eq(m.statusId, "unknown", "statusId");
  eq(m.label, "확인 불가", "제목");
  eq(m.matchedRule.operator, "FALLBACK", "fallback 표기");
  const missing = m.evidence.filter(e => e.missingReason);
  ok(missing.length >= 7, "부족 입력이 missingReason으로 나열");
  ok(ev(m, "close").result === "pass", "제공된 종가는 사실로 표시");
}

console.log("== null vs 0 구분 ==");
{
  const zeroVol = M.judgeObs({ close: 120, sma20: 115, sma60: 100, vol_ratio: 0, rsi14: 55, don_hi: 122, don_lo: 105, atr14: 6, time: "2026-09-03" }, {});
  eq(zeroVol.statusId, "uptrend");
  ok(ev(zeroVol, "uptrend_vol").observedRaw === 0 && ev(zeroVol, "uptrend_vol").missingReason === null, "거래량 0은 실제 값(부족 아님)");
  const noVol = M.judgeObs({ close: 110, sma60: 100, sma20: 95, rsi14: 60, don_hi: 200, don_lo: 80, atr14: 20, vol_ratio: null, time: "2026-09-03" }, {});
  eq(noVol.statusId, "flat");
  ok(ev(noVol, "flat_vol").missingReason === "거래량 입력 부족", "null은 입력 부족으로 구분");
}

console.log("\n결과: pass=" + pass + " fail=" + fail);
process.exit(fail ? 1 : 0);