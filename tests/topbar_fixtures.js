'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../results/dashboard/chart-first.html'), 'utf8');
const elements = Object.fromEntries(['btnRefresh', 'netState', 'symTitle', 'basisLine'].map(id => [id, {
  textContent:'', title:'', attributes:{}, setAttribute(key,value){this.attributes[key]=value;}
}]));
let symbol = {name:'긴 종목명 '.repeat(12), symbol:'AAPL'};
const context = {S:{tf:'D',symbol:'AAPL',lastErr:null}, serverMode:true, $:id=>elements[id],
  curSym:()=>symbol, frameOf:()=>({candles:[{time:'2026-09-07',close:200}]}),
  LIVE_D:{AAPL:{}}, LIVE_H4:{}, LIVE_META:{}, metaKey:()=> 'AAPL|D',
  latestTime:()=> '2026-09-07', fmtP:String, fmtT:String, fmtClock:String, tfWord:()=> '일봉', ERR_TXT:{rate:'조회 제한'}};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('function paintNet('),html.indexOf('function h4CacheGet(')), context);
vm.runInContext(html.slice(html.indexOf('function paintBasis('),html.indexOf('function paintPreset(')), context);
const detail = '장기 분봉 이력 조회 중 · '.repeat(30);
context.setBusy(true,detail);
assert.equal(elements.btnRefresh.textContent,'조회 중…');
assert.equal(elements.btnRefresh.disabled,true);
assert.equal(elements.btnRefresh.attributes['aria-busy'],'true');
assert.equal(elements.netState.textContent,detail);
assert.equal(elements.netState.title,detail,'full status stays accessible when visual text is clamped');
context.setBusy(false);
assert.equal(elements.btnRefresh.textContent,'새로고침');
assert.equal(elements.btnRefresh.disabled,false);
assert.equal(elements.btnRefresh.attributes['aria-busy'],'false');
context.paintBasis();
assert.equal(elements.symTitle.title,elements.symTitle.textContent);
context.S.lastErr={kind:'rate'}; context.paintBasis();
assert.match(elements.basisLine.textContent,/최신 조회 실패\(조회 제한\)/);
assert.equal(elements.basisLine.title,elements.basisLine.textContent);
symbol=null; context.paintBasis();
assert.equal(elements.symTitle.textContent,'종목 없음');
assert.equal(elements.basisLine.textContent,'자료 기준 없음','clears previous symbol basis');
assert.equal(elements.basisLine.title,'자료 기준 없음');
console.log('Topbar: bounded busy label, full status titles, busy recovery and cleared missing-symbol basis passed');
