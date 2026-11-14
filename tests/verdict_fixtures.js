const assert = require('assert');
const { verdictFor } = require('../results/dashboard/verdict.js');

const entry = (code, extra) => Object.assign({ code, label: 'x', reason: '기존 사유', continuation: false }, extra);
const market = (level, extra) => Object.assign({ available: true, applicable: true, level, value: 31, stale: false }, extra);

// 기본 대응: 기존 진입 코드 → 관망·홀드·매수·매도
assert.equal(verdictFor({ entry: entry('candidate') }).code, 'buy');
assert.equal(verdictFor({ entry: entry('candidate', { continuation: true }) }).code, 'hold');
assert.equal(verdictFor({ entry: entry('avoid') }).code, 'sell');
assert.equal(verdictFor({ entry: entry('wait') }).code, 'wait');
assert.equal(verdictFor({ entry: entry('chase') }).code, 'wait');
assert.equal(verdictFor({ entry: entry('blocked') }).code, 'blocked');
assert.equal(verdictFor({ entry: null }).code, 'blocked');
assert.equal(verdictFor({ entry: entry('candidate'), historical: true }).code, 'blocked');
assert.equal(verdictFor({ entry: entry('candidate'), lastError: { kind: 'provider' } }).code, 'blocked');

// 확인된 매도 신호는 시장 위험으로 뒤집지 않는다
assert.equal(verdictFor({ entry: entry('avoid'), market: market('high') }).code, 'sell');
// 판단 보류도 그대로 유지
assert.equal(verdictFor({ entry: entry('blocked'), market: market('high') }).code, 'blocked');

// 시장 위험 국면: 매수·홀드만 관망으로 낮춘다
const buyRisk = verdictFor({ entry: entry('candidate'), market: market('high') });
assert.equal(buyRisk.code, 'wait');
assert.equal(buyRisk.detail, '시장 위험');
const holdRisk = verdictFor({ entry: entry('candidate', { continuation: true }), market: market('high') });
assert.equal(holdRisk.code, 'wait');
// 관망은 매수로 올리지 않는다
assert.equal(verdictFor({ entry: entry('wait'), market: market('high') }).code, 'wait');

// 상승 국면은 라벨을 유지하되 사유에만 반영한다
const elevated = verdictFor({ entry: entry('candidate'), market: market('elevated') });
assert.equal(elevated.code, 'buy');
assert(elevated.reason.includes('시장 변동성'));

// 자료 없음·적용 대상 아님·오래된 자료는 기존 판단을 바꾸지 않는다
assert.equal(verdictFor({ entry: entry('candidate'), market: { available: false, applicable: true } }).code, 'buy');
assert.equal(verdictFor({ entry: entry('candidate'), market: market('high', { applicable: false }) }).code, 'buy');
assert.equal(verdictFor({ entry: entry('candidate'), market: market('high', { stale: true }) }).code, 'buy');
assert.equal(verdictFor({ entry: entry('candidate'), market: null }).code, 'buy');

console.log('Verdict: 20 assertions passed');
