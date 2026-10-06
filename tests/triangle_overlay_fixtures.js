const assert=require('node:assert/strict');
const {project,choose}=require('../results/dashboard/pattern-overlay.js');
const {view,name,label,errorText,fitBounds}=require('../results/dashboard/triangle-panel.js');
const bars=[{time:'2026-01-01'},{time:'2026-01-02'}];
const geometry={points:[{time:'2026-01-01',price:10},{anchorTime:'2026-01-01',logicalOffset:5.5,price:7},{time:'2026-01-01',price:4}]};
const shape=project(geometry,bars,x=>x*20,p=>100-p);assert.equal(shape.points[1].x,110);assert.equal(shape.points.length,3);
// Mimic the chart library returning zero for future whitespace.
const future=project(geometry,bars,x=>x>=bars.length?0:30+x*20,p=>100-p);
assert.equal(future.points[1].x,140);assert(future.points[1].x>future.points[0].x);
// Real v5 library: fractional logical indexes return zero even inside the data.
const integerOnly=x=>Number.isInteger(x)?30+x*20:0;
const inside={points:[{time:'2026-01-01',price:10},{anchorTime:'2026-01-01',logicalOffset:.5,price:7},{time:'2026-01-01',price:4}]};
assert.equal(project(inside,bars,integerOnly,p=>100-p).points[1].x,40);
assert.equal(project(inside,bars,x=>x===1?null:30,p=>p),null,'missing interpolation neighbor withholds the shape');
// VELO's cached September triangle apex is inside the October history window.
const veloBars=Array.from({length:23},(_,i)=>({time:String(i)}));
const velo={points:[{time:'0',price:12.166015},{anchorTime:'0',logicalOffset:17.156727543794318,price:11.364293},{time:'0',price:8.705}]};
const veloShape=project(velo,veloBars,integerOnly,p=>200-p*10);
assert(Math.abs(veloShape.points[1].x-(30+17.156727543794318*20))<1e-9);
assert(veloShape.points[1].x>veloShape.points[0].x);
assert.equal(project(geometry,[bars[1]],x=>x,p=>p),null);
const fitPattern={status:'forming',geometry:{...geometry,observedThrough:bars[0].time},barTime:bars[0].time};
const fitBars=bars.map((b,i)=>({...b,high:i?9999:11,low:i?.01:3}));
const fit=fitBounds(fitPattern,fitBars);assert.equal(fit.range.from,-3);assert.equal(fit.range.to,8.5);assert(fit.priceRange.maxValue<20,'future candles changed historical fit scale');
assert.equal(fitBounds({...fitPattern,status:'expired'},fitBars),null);assert.equal(fitBounds({...fitPattern,geometry:null},fitBars),null);
const flag={type:'bull-flag',status:'forming',discoveredTime:'2026-01-01'},tri={type:'ascending-triangle',status:'confirmed',direction:'down',discoveredTime:'2026-01-02'};
assert.equal(choose(flag,tri),tri);assert.equal(choose(flag,tri,'flag'),flag);assert.equal(choose(flag,{...tri,status:'paused'},'triangle'),null);
assert.equal(name(tri),'상승 삼각형');assert(label(tri).includes('아래쪽'));
assert.equal(errorText('invalid-data'),'봉 자료 형식 오류');
assert.equal(errorText('storage-error'),'분석 저장 오류');
assert.equal(errorText('calculation-error'),'삼각수렴 계산 오류');
assert.equal(errorText(undefined),'삼각수렴 처리 오류');
const a={enabled:true,sourceStatus:'ready',provisionalEligible:true,timeline:[{barTime:'2026-01-02',confirmed:false,status:'ready',patterns:[tri]}],recentEvents:[{confirmedBarTime:'2026-01-03'}]};
assert.equal(view(a,'D','2026-01-02',false).events.length,0);assert.equal(view(a,'D',null,true).patterns[0].status,'paused');
console.log('Triangle fractional apex, one selected overlay and direction labels passed');
