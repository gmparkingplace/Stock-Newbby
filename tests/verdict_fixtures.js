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

const lowExit={strategy:'F',id:'prior-10-low',operator:'<',observed:67138.0938,reference:67653.07,status:'met'};
const btc=entry('avoid',{selected:['F'],exitEvidence:[lowExit],provisional:true});
const btcVerdict=verdictFor({entry:btc,formatPrice:n=>'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})});
assert.equal(btcVerdict.code,'sell');
assert.equal(btcVerdict.evidenceText,'F 매도 조건: 종가 $67,138.09 < 직전 10봉 저점 $67,653.07 · 진행봉 잠정');
assert(btcVerdict.reason.includes('기대가 깨져')&&btcVerdict.reason.includes('추가 하락 위험'),'관측 사실과 전략의 인과 해석을 함께 설명한다');
assert(btcVerdict.reason.includes('마감 전에 회복하면'),'잠정 신호의 한계를 설명한다');
assert(!btcVerdict.reason.includes('$67,'),'수치는 주 설명이 아닌 보조 근거다');
assert(!btcVerdict.reason.includes('거래량'),'F 이탈에 거래량 조건을 만들어 넣지 않는다');
assert(!verdictFor({entry:btc,historical:true}).reason.includes('67,'));
assert(!verdictFor({entry:btc,lastError:{kind:'provider'}}).reason.includes('67,'));
assert.equal(verdictFor({entry:{...btc,code:'blocked',reason:'원천 확인 필요'}}).reason,'원천 확인 필요');
const both={...btc,selected:['C','F'],exitEvidence:[{...lowExit,strategy:'C'},lowExit],provisional:false};
assert.equal((verdictFor({entry:both}).reason.match(/기대가 깨져/g)||[]).length,1,'공유 조건의 인과 설명을 중복하지 않는다');
assert(verdictFor({entry:both}).evidenceText.startsWith('C/F 매도 조건:'));
assert(!verdictFor({entry:{...btc,selected:['A']}}).evidenceText,'미선택 전략 근거로 설명하지 않는다');
assert(!verdictFor({entry:{...btc,exitEvidence:[{...lowExit,status:'unverified'}]}}).evidenceText,'반올림으로 검증 불가한 값은 단정하지 않는다');
const rsi={strategy:'B',id:'rsi-cross-down-70',observed:69.4,reference:70,previousObserved:72.1,previousReference:70,status:'met'};
assert(verdictFor({entry:entry('avoid',{selected:['B'],exitEvidence:[rsi]})}).evidenceText.includes('72.10에서 69.40'));
assert(verdictFor({entry:entry('avoid',{selected:['B'],exitEvidence:[rsi]})}).reason.includes('상승 속도가 둔화'));
assert(verdictFor({entry:both}).reason.includes('하락을 보장하지는 않아요'));
console.log('종합판단·실제 매도 조건/수치·전략 선택·잠정/과거/오류 격리 검사 통과');
