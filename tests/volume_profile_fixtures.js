const assert = require('assert'), { build } = require('../results/dashboard/volume-profile.js');
const candles = Array.from({ length: 20 }, (_, i) => ({
  time: `2026-08-${String(i + 1).padStart(2, '0')}`,
  open: 100 + i, high: 103 + i, low: 99 + i, close: 101 + i, volume: 1000 + i * 50,
}));
const out = build(candles, 19);
// 계산 조건 계약: 버전·추정방식·분할수·기간·봉수
assert.equal(out.version, 'vp-1');
assert.equal(out.method, 'hlc3');
assert.equal(out.binCount, 12);
assert.equal(out.bins.length, 12);
assert.equal(out.from, '2026-08-01');
assert.equal(out.to, '2026-08-20');
assert.equal(out.count, 20);
// 비중 합 = 1, 피크 1개 이상
const share = out.bins.reduce((a, b) => a + b.share, 0);
assert(Math.abs(share - 1) < 1e-9);
assert(out.bins.some(b => b.peak));
// 윈도우 분리: 확대 범위가 아니라 전달된 index까지만 반영
const part = build(candles, 9);
assert.equal(part.to, '2026-08-10');
assert.equal(part.count, 10);
// 부족 시 null
assert.equal(build(candles.slice(0, 5), 4), null);
// 평탄가: 분할 1
const flat = candles.map(c => ({ ...c, high: 100, low: 100, close: 100 }));
assert.equal(build(flat, 19).binCount, 1);
console.log('Volume profile: 8 passed');
