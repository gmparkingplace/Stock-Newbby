(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.ChartLayout=factory();})(typeof self!=='undefined'?self:this,function(){
'use strict';
// 화면 표시만 간추린다. 원신호와 판단 기준은 바꾸지 않는다.
function arrange(markers, {coordinate, width, selectedTime, measure}) {
  const icons=[], boxes=[], kept=[];
  const candidates=markers.map((marker,index)=>({marker,index,x:coordinate(marker.time)}))
    .filter(c=>Number.isFinite(c.x) && c.x>=8 && c.x<=width-8)
    .sort((a,b)=>priority(b.marker)-priority(a.marker)||a.index-b.index);
  function priority(m){return (m.time===selectedTime?4:0)+(m.shape==='circle'?0:2);}
  for(const {marker,index,x} of candidates){
    const lane=marker.position;
    if(icons.some(b=>b.lane===lane && Math.abs(b.x-x)<18)) continue;
    icons.push({lane,x});
    kept.push({marker:{...marker,text:''},index,x,lane});
  }
  // 텍스트가 다른 마커 아이콘에 닿아도 생략한다. 선택 봉/전략 신호 우선.
  for(const item of kept){
    const original=markers[item.index];
    if(!original.text) continue;
    const half=measure(original.text)/2+6, left=item.x-half, right=item.x+half;
    if(left<4 || right>width-4) continue;
    if(boxes.some(b=>b.lane===item.lane && left<b.right+8 && right>b.left-8)) continue;
    if(icons.some(b=>b.lane===item.lane && b.x!==item.x && b.x>=left-8 && b.x<=right+8)) continue;
    item.marker.text=original.text;
    boxes.push({lane:item.lane,left,right,time:original.time});
  }
  kept.sort((a,b)=>a.index-b.index);
  return {markers:kept.map(c=>c.marker), boxes, icons};
}
return {arrange};
});
