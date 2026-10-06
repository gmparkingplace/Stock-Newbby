'use strict';
const day=i=>new Date(Date.UTC(2026,0,1+i)).toISOString().slice(0,10);
function sample(family='H'){
 const bars=Array.from({length:44},(_,i)=>({time:day(i),open:100,high:102,low:98,close:100,volume:100}));
 const set=(i,low,high,close,volume=100)=>{bars[i]={time:day(i),open:Math.min(high,Math.max(low,close-.5)),low,high,close,volume};};
 set(18,95,99,97,200);set(19,97,103,100);set(20,98,104,101);
 if(family==='H'){
  set(23,98,103,100);set(24,97,100,98,80);set(25,98,103,101);set(26,99,106,105,200);
  for(let i=27;i<44;i++)set(i,103,107,105,150);
 }else{
  set(24,93.7,100,97,200);set(25,97,103,101);set(26,98,104,102);
  set(27,97,101,99);set(28,95.5,99,97,60);set(29,97,103,100,70);set(30,98,107,105,200);
  for(let i=31;i<44;i++)set(i,103,107,105,150);
 }
 return bars;
}
module.exports={day,sample};
