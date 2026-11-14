'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const base=path.join(__dirname,'../results/dashboard');
const Theme=require(path.join(base,'chart-theme.js'));
const {colors}=Theme;
const {observations}=require(path.join(base,'chart-legend.js'));
const {build}=require(path.join(base,'indicator-panel.js'));
function luminance(hex){
  const values=hex.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  return values[0]*.2126+values[1]*.7152+values[2]*.0722;
}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
const first=Theme.options(),second=Theme.options();
assert.deepEqual(first,second);
assert.notEqual(first,second);assert.notEqual(first.layout.background,second.layout.background);
first.layout.background.color='#ffffff';first.grid.vertLines.color='#ffffff';first.crosshair.vertLine.color='#ffffff';
assert.equal(Theme.options().layout.background.color,'#151a22');
assert.equal(second.grid.vertLines.color,'#262e3c');assert.equal(second.crosshair.vertLine.color,'#73839a');
assert(Object.isFrozen(Theme));assert(Object.isFrozen(colors));
assert.throws(()=>{colors.up='#ffffff';},TypeError);
const extra={width:910,height:400,layout:{fontFamily:'Pretendard, system-ui, sans-serif',fontSize:12},timeScale:{rightOffset:2,timeVisible:true},rightPriceScale:{scaleMargins:{top:.12,bottom:.25}}};
const before=JSON.stringify(extra),custom=Theme.options(extra);
assert.equal(JSON.stringify(extra),before);assert.equal(custom.width,910);assert.equal(custom.height,400);
assert.equal(custom.layout.fontFamily,extra.layout.fontFamily);assert.equal(custom.timeScale.rightOffset,2);
assert.equal(custom.rightPriceScale.borderColor,'#364051');assert.equal(custom.rightPriceScale.scaleMargins.top,.12);
custom.rightPriceScale.scaleMargins.top=999;assert.equal(extra.rightPriceScale.scaleMargins.top,.12);
assert.equal(Theme.plotFor(extra).layout.background.color,'rgba(21,26,34,0)');
assert.equal(Theme.plotFor(extra).layout.textColor,colors.text);
assert.equal(Theme.options().layout.background.color,colors.background);
for(const key of ['width','height','handleScale','handleScroll','localization'])assert(!(key in Theme.options()));
assert(!('fontFamily' in Theme.options().layout));assert(!('fontSize' in Theme.options().layout));
assert(!('rightOffset' in Theme.options().timeScale));assert(!('scaleMargins' in Theme.options().rightPriceScale));
for(const color of [colors.text,colors.up,colors.down,colors.sma20,colors.sma60,colors.sma120,colors.sma200,colors.threshold,...observations.map(x=>x.color)]){
  assert(contrast(color,colors.background)>=4.5,`${color}: 어두운 바탕에서 문자 대비 부족`);
}
assert.equal(colors.up,'#ff777f');assert.equal(colors.down,'#75aaff');
assert.equal(new Set([colors.sma20,colors.sma60,colors.sma120,colors.sma200]).size,4);
for(const color of [colors.up,colors.down,colors.neutral])assert(contrast(color,colors.patternNeutralFill)>=3);
const browser={};vm.runInNewContext(fs.readFileSync(path.join(base,'chart-theme.js'),'utf8'),browser);
assert.equal(browser.ChartTheme.options().layout.background.color,colors.background);
assert.equal(browser.ChartTheme.colors.up,colors.up);
const frame={candles:[{time:'2026-01-01',open:10,close:12,volume:20},{time:'2026-01-02',open:12,close:10,volume:30}],state:[]};
const data=build(frame,'volume',1);assert.equal(data.series[0].color,colors.volumeUp);assert.equal(data.series[1].color,colors.volumeDown);
assert.equal(data.series[0].value,20);assert.equal(data.series[1].value,30);
const html=fs.readFileSync(path.join(base,'chart-first.html'),'utf8');
const themeIndex=html.indexOf('src="chart-theme.js"');assert(themeIndex>=0);
for(const script of ['indicator-panel.js','pattern-panel.js','price-indicators.js','pattern-overlay.js'])assert(themeIndex<html.indexOf(`src="${script}"`),`${script}: 공유 테마보다 먼저 불러옴`);
assert.match(html,/createChart\(el, typeof ChartTheme!=="undefined" \? ChartTheme\.plotFor\(/);
assert.match(html,/const UP = "#ff777f", DOWN = "#75aaff"/);
assert.match(html,/markerMeasure\.font="12px Pretendard, system-ui, sans-serif"/);
assert.match(fs.readFileSync(path.join(base,'indicator-panel.js'),'utf8'),/createChart\(host,theme\?theme\.options\(/);
assert.match(fs.readFileSync(path.join(base,'pattern-panel.js'),'utf8'),/createChart\(el,typeof ChartTheme!=='undefined'\?ChartTheme\.plotFor\(/);
const source=fs.readFileSync(path.join(base,'chart-theme.js'),'utf8');
assert.doesNotMatch(source,/\bfetch\s*\(|XMLHttpRequest|localStorage|sessionStorage|setVisible|setData/);
console.log('공유 다크 차트 옵션·불변성·색상 대비·지표 색상·스크립트 연결 검사 통과');
