'use strict';
// 스킬 스냅샷의 volumeProfile이 화면과 같은 VolumeProfile.build 결과인지 검증.
// chart-control.js snapshot() 본문을 추출해 vm에서 실행한다.
const fs = require('fs'), vm = require('vm'), assert = require('assert'), path = require('path');
const html = fs.readFileSync(path.join(__dirname, '../results/dashboard/chart-control.js'), 'utf8');
const body = html.split('function snapshot() {')[1].split('async function idle')[0];
const VolumeProfile = require('../results/dashboard/volume-profile.js');
const candles = Array.from({ length: 20 }, (_, i) => ({
  time: `2026-08-${String(i + 1).padStart(2, '0')}`,
  open: 100 + i, high: 103 + i, low: 99 + i, close: 101 + i, volume: 1000 + i * 50,
}));
const frame = { candles, source: 'toss', marketAsOf: '2026-08-20', fetchedAt: '2026-08-20T00:00:00Z', delayStatus: 'unknown' };
const el = () => ({ textContent: '' });
const ctx = {
  frameOf: () => frame, curSym: () => ({ name: '테스트' }), currentObs: () => null,
  asOfIdx: () => 19, VolumeProfile,
  S: { symbol: 'T', tf: 'D', preset: '6M', selectedAsOf: null, autoRef: true, refreshing: false, sourceKind: 'live', lastErr: null },
  window: { __CF: { visible: () => null } }, $: el,
  latestTime: f => (f.candles || []).at(-1)?.time ?? null,
};
vm.createContext(ctx);
vm.runInContext('function snapshot() {' + body, ctx);
const snap = vm.runInContext('snapshot()', ctx);
const direct = VolumeProfile.build(candles, 19);
// 스냅샷이 화면과 동일한 함수의 동일한 결과를 담는다
assert.deepEqual(snap.volumeProfile, direct);
for (const k of ['version', 'method', 'binCount', 'from', 'to', 'count', 'total', 'bins'])
  assert(k in snap.volumeProfile, k);
assert.equal(snap.volumeProfile.version, 'vp-1');
// 봉 부족 시 null (추측 금지 계약)
ctx.asOfIdx = () => 4;
ctx.frameOf = () => ({ candles: candles.slice(0, 5) });
const short = vm.runInContext('snapshot()', ctx);
assert.equal(short.volumeProfile, null);
console.log('Snapshot volume: 11 passed');
