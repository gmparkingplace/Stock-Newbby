'use strict';
const assert=require('node:assert/strict');
const {arrange}=require('../results/dashboard/chart-layout');
const marks=Array.from({length:30},(_,i)=>({time:i,position:'belowBar',shape:i%3?'circle':'arrowUp',text:'F 진입 조건',color:'red'}));
const original=JSON.stringify(marks);
function layout(spacing,width){return arrange(marks,{coordinate:t=>t*spacing+10,width,selectedTime:12,measure:t=>t.length*10});}
for(const [spacing,width] of [[8,320],[24,800],[90,2800]]){
  const r=layout(spacing,width);
  for(const b of r.boxes){
    assert(b.left>=4 && b.right<=width-4);
    assert(!r.boxes.some(other=>other!==b && other.lane===b.lane && b.left<other.right+8 && b.right>other.left-8));
    assert(!r.icons.some(icon=>icon.lane===b.lane && icon.x!== (b.left+b.right)/2 && icon.x>=b.left-8 && icon.x<=b.right+8));
  }
  for(let i=0;i<r.icons.length;i++)for(let j=i+1;j<r.icons.length;j++)
    if(r.icons[i].lane===r.icons[j].lane)assert(Math.abs(r.icons[i].x-r.icons[j].x)>=18);
  assert(r.markers.some(m=>m.time===12),'selected signal retained');
}
assert(layout(8,320).markers.length<marks.length);
assert(layout(90,2800).boxes.length>layout(8,320).boxes.length);
assert.equal(JSON.stringify(marks),original);
assert.deepEqual(arrange(marks,{coordinate:()=>null,width:0,measure:()=>0}).markers,[]);
const opposite=arrange([{time:1,position:'aboveBar',shape:'arrowDown',text:'이탈'},{time:1,position:'belowBar',shape:'arrowUp',text:'진입'}],{coordinate:()=>100,width:300,measure:()=>30});
assert.equal(opposite.markers.length,2);assert.equal(opposite.boxes.length,2);
console.log('chart layout fixtures passed');
