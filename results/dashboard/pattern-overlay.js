/* Opaque geometry behind transparent chart canvases; never a signal calculator. */
(function(){
  'use strict';
  function project(geometry,bars,toX,toY){
    const indexes=new Map(bars.map((b,i)=>[String(b.time),i]));
    // v5 accepts integer indexes only and returns zero for a fractional apex.
    // Interpolate actual bar coordinates; extend their spacing beyond the data.
    const coordinate=i=>{
      if(i>=0&&i<=bars.length-1){
        if(Number.isInteger(i))return toX(i);
        const before=Math.floor(i),after=Math.ceil(i),x=toX(before),next=toX(after);
        return Number.isFinite(x)&&Number.isFinite(next)?x+(i-before)*(next-x):null;
      }
      if(bars.length<2)return null;
      const edge=i<0?0:bars.length-1,neighbor=i<0?1:edge-1;
      const x=toX(edge),near=toX(neighbor);
      return Number.isFinite(x)&&Number.isFinite(near)?x+(i-edge)*(near-x)/(neighbor-edge):null;
    };
    const point=p=>{const base=indexes.get(String(p.time??p.anchorTime));if(base===undefined)return null;const i=p.time!=null?base:base+Number(p.logicalOffset);if(!Number.isFinite(i))return null;const x=coordinate(i),y=toY(p.price);return Number.isFinite(x)&&Number.isFinite(y)?{x,y}:null;};
    const points=(geometry?.points||[]).map(point);
    if(points.length<3||points.some(p=>!p))return null;
    return {points,pole:(geometry.pole||[]).map(point).filter(Boolean)};
  }
  function choose(flag,triangle,category='auto'){
    const valid=p=>p&&!['failed','expired','paused'].includes(p.status);
    if(category==='flag')return valid(flag)?flag:null;
    if(category==='triangle')return valid(triangle)?triangle:null;
    const rank={confirmed:0,retested:0,'breakout-pending':1,forming:2};
    return [flag,triangle].filter(valid).sort((a,b)=>(rank[a.status]??3)-(rank[b.status]??3)||String(b.discoveredTime||'').localeCompare(a.discoveredTime||''))[0]||null;
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={project,choose};return;}
  const ns='http://www.w3.org/2000/svg';let serial=0;
  function create(host,chart,series,getBars){
    const svg=document.createElementNS(ns,'svg');svg.classList.add('patternUnderlay');svg.setAttribute('aria-hidden','true');host.prepend(svg);
    const id='pattern-grid-'+(++serial);let model=null,raf=0,removed=false,lastSignature='';
    const node=(tag,attrs,parent=svg)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);parent.append(e);return e;};
    function draw(){
      raf=0;if(removed)return;
      const w=host.clientWidth,h=host.clientHeight;svg.setAttribute('viewBox',`0 0 ${w} ${h}`);
      if(!model||!w||!h){svg.replaceChildren();lastSignature='';return;}
      const shape=project(model.geometry,getBars(),i=>chart.timeScale().logicalToCoordinate(i),p=>series.priceToCoordinate(p));if(!shape){svg.replaceChildren();lastSignature='';return;}
      const right=chart.priceScale('right').width(),left=chart.priceScale('left').width();
      const plotHeight=h-chart.timeScale().height();
      const signature=JSON.stringify([model.patternId,model.status,model.direction,shape,w,h,right,left,plotHeight]);
      if(signature===lastSignature)return;lastSignature=signature;svg.replaceChildren();
      const defs=node('defs',{}),clip=node('clipPath',{id:id+'-plot'},defs);
      node('rect',{x:left,y:0,width:Math.max(0,w-right-left),height:Math.max(0,plotHeight)},clip);
      const polygon=shape.points.map(p=>`${p.x},${p.y}`).join(' ');
      const area=node('clipPath',{id:id+'-shape'},defs);node('polygon',{points:polygon},area);
      const up=model.direction==='up',neutral=model.direction==='neutral',fill=neutral?'#e2e8f0':up?'#dbeafe':'#fee2e2',stroke=neutral?'#64748b':up?'#2563eb':'#b91c1c';
      const group=node('g',{'clip-path':`url(#${id}-plot)`});
      node('polygon',{points:polygon,fill,stroke,'stroke-width':2,'stroke-dasharray':['confirmed','retested'].includes(model.status)?'none':'6 4','data-pattern':model.patternId||'shape'},group);
      const hatch=node('g',{'clip-path':`url(#${id}-shape)`},group);
      for(let x=-h;x<w;x+=20)node('line',{x1:x,y1:0,x2:x+h,y2:h,stroke:neutral?'#cbd5e1':up?'#bfdbfe':'#fecaca','stroke-width':1},hatch);
      if(shape.pole.length===2)node('polyline',{points:shape.pole.map(p=>`${p.x},${p.y}`).join(' '),fill:'none',stroke,'stroke-width':3},group);
    }
    function schedule(){if(!removed&&!raf)raf=requestAnimationFrame(draw);}
    const size=new ResizeObserver(schedule);size.observe(host);
    chart.timeScale().subscribeVisibleLogicalRangeChange(schedule);
    chart.timeScale().subscribeVisibleTimeRangeChange(schedule);
    // Covers vertical scale drags/auto-scaling without a persistent animation loop.
    host.addEventListener('pointermove',schedule);host.addEventListener('wheel',schedule,{passive:true});
    host.addEventListener('pointerup',schedule);host.addEventListener('dblclick',schedule);
    return {set(p){model=p;schedule();},render:schedule,element:svg,
      destroy(){removed=true;if(raf)cancelAnimationFrame(raf);size.disconnect();chart.timeScale().unsubscribeVisibleLogicalRangeChange(schedule);chart.timeScale().unsubscribeVisibleTimeRangeChange(schedule);for(const type of ['pointermove','wheel','pointerup','dblclick'])host.removeEventListener(type,schedule);svg.remove();}};
  }
  window.PatternOverlay={create,project,choose};
})();
