const assert = require('assert');
const { build, gaps, levels, pivots } = require('../results/dashboard/price-zones.js');

const day = 86400;
const c = (i, low, high, close, volume) => ({ time: day * i, open: close, high, low, close, volume: volume == null ? 1000 : volume });

// 완전히 비어 있는 갭상승: 앞봉 고가 100 → 다음 봉 저가 110
const up = [c(0, 95, 100, 99), c(1, 110, 118, 115)];
const gapsUp = gaps(up, { atr: 5, minAtr: 0.25 });
assert.equal(gapsUp.length, 1);
assert.equal(gapsUp[0].dir, 'up');
assert.equal(gapsUp[0].low, 100);
assert.equal(gapsUp[0].high, 110);
assert.equal(gapsUp[0].state, 'none');

// 갭하락
const down = [c(0, 100, 108, 102), c(1, 90, 96, 92)];
const gapsDown = gaps(down, { atr: 5 });
assert.equal(gapsDown[0].dir, 'down');
assert.equal(gapsDown[0].low, 96);
assert.equal(gapsDown[0].high, 100);

// 이후 봉이 구간을 완전히 지나면 채움
const filled = [c(0, 95, 100, 99), c(1, 110, 118, 115), c(2, 98, 112, 99)];
assert.equal(gaps(filled, { atr: 5 })[0].state, 'full');
// 일부만 들어오면 부분 채움
const partial = [c(0, 95, 100, 99), c(1, 110, 118, 115), c(2, 104, 112, 106)];
assert.equal(gaps(partial, { atr: 5 })[0].state, 'partial');

// 자료가 빠진 구간(봉 간격이 크게 벌어짐)은 갭으로 세지 않는다
const missing = [c(0, 95, 100, 99), c(1, 96, 101, 100), c(2, 97, 102, 101),
  c(3, 98, 103, 102), c(4, 99, 104, 103), c(15, 110, 118, 115)];
assert.equal(gaps(missing, { atr: 5 }).length, 0);
// 간격이 정상이면 같은 가격 이동도 갭으로 남는다
const normal = missing.slice(0, 5).concat([c(5, 110, 118, 115)]);
assert.equal(gaps(normal, { atr: 5 }).length, 1);

// 작은 갭은 ATR 기준으로 걸러진다
const tiny = [c(0, 95, 100, 99), c(1, 100.2, 118, 115)];
assert.equal(gaps(tiny, { atr: 5, minAtr: 0.25 }).length, 0);
assert.equal(gaps(tiny, { atr: 0.1, minAtr: 0.25 }).length, 1);

// 지지·저항: 같은 가격대에서 두 번 반응하면 하나의 후보로 묶인다
const series = [];
for (let i = 0; i < 20; i++) series.push(c(i, 90, 100, 95, 1000 + i * 10));
series[3] = c(3, 88, 100.5, 92);   // 고점
series[9] = c(9, 89, 100.4, 93);   // 같은 높이의 고점
series[5] = c(5, 80, 95, 85);      // 저점
series[12] = c(12, 80.2, 95, 86);  // 같은 낮이의 저점
const lv = levels(series, { atr: 4, tolerance: 0.5 });
assert(lv.length >= 2);
assert(lv.every(l => l.touches >= 1));
assert(lv.some(l => l.touches >= 2));
assert(lv.some(l => l.pivotKind === 'high'));
assert(lv.some(l => l.pivotKind === 'low'));
assert(lv.every(l => l.role === '저항 후보' || l.role === '지지 후보'));
assert(lv.some(l => l.role === '지지 후보'));  // 종가 86 아래 저점
assert.equal(pivots(series, 3).length >= 2, true);
// 반복 반응이 적어도 최근 지점으로 후보를 채운다
const sparse = levels(series.slice(0, 8), { atr: 4, tolerance: 0.5 });
assert(sparse.length <= 3);

// 매물대는 거래량이 몰린 구간만 남긴다
const heavy = [];
for (let i = 0; i < 20; i++) heavy.push(c(i, 100, 101, 100.5, i === 5 ? 9000 : 100));
const out = build(heavy, 19);
assert(out);
assert.equal(out.version, 'zones-1');
assert(out.clusters.length >= 1);
assert(out.clusters.every(x => x.kind === 'cluster' && x.high >= x.low));
// 봉이 부족하면 null
assert.equal(build(heavy.slice(0, 5), 4), null);

// 일봉 문자열 시간에서도 계산된다(시간 표기는 그대로 유지)
const daily = [];
for (let i = 1; i <= 20; i++) daily.push({ time: `2026-08-${String(i).padStart(2, '0')}`, open: 100, high: 102, low: 99, close: 101, volume: 1000 });
daily[10] = { time: '2026-08-11', open: 112, high: 118, low: 110, close: 115, volume: 3000 };
const dailyOut = build(daily, 19);
assert(dailyOut, 'daily string time builds');
assert.equal(dailyOut.to, '2026-08-20');
assert(dailyOut.gaps.some(g => g.dir === 'up' && g.time === '2026-08-11'));
assert.equal(typeof dailyOut.gaps[0].low, 'number');

console.log('Price zones: 31 assertions passed');
