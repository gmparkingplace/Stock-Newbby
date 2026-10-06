(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.ChartUtil=factory();})(typeof self!=='undefined'?self:this,function(){
'use strict';
// chart-first.html 인라인에서 분리한 순수 헬퍼 (DOM·상태·통신 의존 없음).
// 브라우저에서는 <script src="chart-util.js"> 다음 인라인이 ChartUtil에서 구조분해한다.
function metaKey(sym, tf) { return sym + "#" + tf; }
function validFrame(j) {
  return j && typeof j.symbol === "string" && Array.isArray(j.candles) && j.candles.length > 0;
}
// 주기 자료가 없으면 다른 주기로 대체하지 않는다. 화면과 관심목록 공통 계약.
function selectFrame(payload, tf, intraday) {
  if (!payload) return null;
  if (tf === 'W') return payload.weekly || null;
  if (tf === 'M') return payload.monthly || null;
  if (tf === 'H4') return intraday || payload.h4 || (payload.tf === 'H4' ? payload : null);
  return tf === 'D' ? payload : null;
}
function barDateVal(t) { return typeof t === "number" ? new Date(t * 1000) : new Date(t + "T00:00:00"); }
function latestTime(f) { const cs = f.candles || []; return cs.length ? cs[cs.length - 1].time : null; }
function rangeStartIdx(f, preset) {
  const cs = f.candles || [];
  if (!cs.length) return 0;
  if (preset === "ALL") return 0;
  const months = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12 }[preset] || 3;
  const lt = barDateVal(latestTime(f));
  const start = new Date(lt); start.setMonth(start.getMonth() - months);
  let idx = cs.findIndex(c => barDateVal(c.time) >= start);
  return idx < 0 ? 0 : idx;
}
function obsTransitions(arr) {
  const out = []; let prev = null;
  for (let i = 0; i < arr.length; i++) {
    const m = arr[i];
    if (!m || !m.statusId) continue;
    if (m.statusId !== prev) out.push({ i, m });
    prev = m.statusId;
  }
  return out;
}
function pickObsLabels(f, arr, selIdx) {
  // 전체 시계열에서 12봉 이상 떨어진 전환점만 표시한다.
  // 화면 경계/줌/선택 봉으로 기존 표시 위치를 재선정하지 않는다.
  const chosen = new Set();let lastMarker=-Infinity;
  for(const {i} of obsTransitions(arr)){
    if(i-lastMarker>=12){chosen.add(i);lastMarker=i;}
  }
  if (selIdx != null && selIdx >= 0 && selIdx < arr.length) chosen.add(selIdx);
  let lastText = -Infinity;
  return [...chosen].sort((a, b) => a - b).map(i => {
    const showText = i === selIdx || i - lastText >= 12;
    if (showText) lastText = i;
    return { i, m: arr[i], showText };
  });
}
function bidxOf(f, t) { return (f.candles || []).findIndex(c => c.time === t); }
return {metaKey, validFrame, selectFrame, barDateVal, latestTime, rangeStartIdx, obsTransitions, pickObsLabels, bidxOf};
});
