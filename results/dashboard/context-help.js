/* Contextual explanations reuse their live DOM; no polling, copying or data requests. */
(function(){
  'use strict';
  function place(anchor,width,height,viewportWidth,viewportHeight){
    const margin=12,gap=8;
    width=Math.min(width,Math.max(0,viewportWidth-margin*2));
    const below=Math.max(0,viewportHeight-anchor.bottom-gap-margin),above=Math.max(0,anchor.top-gap-margin);
    const down=height<=below||below>=above,maxHeight=Math.max(0,down?below:above);
    return {left:Math.max(margin,Math.min(anchor.left,viewportWidth-margin-width)),
      top:down?anchor.bottom+gap:Math.max(margin,anchor.top-gap-Math.min(height,maxHeight)),maxHeight};
  }
  function install(doc,win){
    let active=null,pinned=false,hovered=false,timer=null,suppressFocus=false;
    const pairs=new Map();
    function cancel(){if(timer!==null)win.clearTimeout(timer);timer=null;}
    function position(){
      if(!active)return;
      const {button,popup}=active,r=button.getBoundingClientRect();
      // Scrolling the anchor away must not leave an unrelated floating explanation.
      if(r.bottom<0||r.top>win.innerHeight||(button.getClientRects&&button.getClientRects().length===0)){close();return;}
      popup.style.maxHeight=(win.innerHeight-24)+'px';
      const p=place(r,popup.offsetWidth,popup.scrollHeight,win.innerWidth,win.innerHeight);
      popup.style.left=p.left+'px';popup.style.top=p.top+'px';popup.style.maxHeight=p.maxHeight+'px';
    }
    function close(restore=false){
      cancel();if(!active)return;
      const {button,popup}=active;
      active=null;pinned=false;hovered=false;
      popup.classList.remove('isOpen');button.setAttribute('aria-expanded','false');
      if(restore){suppressFocus=true;button.focus();suppressFocus=false;}
    }
    function open(pair){
      cancel();if(active!==pair){close();active=pair;pair.popup.classList.add('isOpen');pair.button.setAttribute('aria-expanded','true');}
      position();
    }
    function delayedClose(){
      cancel();timer=win.setTimeout(()=>{
        timer=null;if(!active||pinned||hovered)return;
        const focus=doc.activeElement;
        if(focus!==active.button&&!active.popup.contains(focus))close();
      },180);
    }
    for(const button of doc.querySelectorAll('[data-help]')){
      const popup=doc.getElementById(button.dataset.help);if(!popup)continue;
      const pair={button,popup};pairs.set(button,pair);
      const label=button.getAttribute('aria-label')||'도움말';
      popup.setAttribute('role','region');popup.setAttribute('aria-label',label);
      const top=doc.createElement('div'),title=doc.createElement('strong'),dismiss=doc.createElement('button');
      top.className='helpTop';title.textContent=label;dismiss.className='helpClose';dismiss.type='button';dismiss.textContent='×';dismiss.setAttribute('aria-label','도움말 닫기');
      top.append(title,dismiss);popup.prepend(top);
      dismiss.addEventListener('click',()=>close(true));
      button.addEventListener('mouseenter',()=>{open(pair);hovered=true;});
      button.addEventListener('mouseleave',()=>{if(active===pair){hovered=false;delayedClose();}});
      button.addEventListener('focus',()=>{if(!suppressFocus)open(pair);});
      button.addEventListener('blur',delayedClose);
      button.addEventListener('click',()=>{if(active===pair&&pinned)close();else{open(pair);pinned=true;}});
      popup.addEventListener('mouseenter',()=>{if(active===pair){cancel();hovered=true;}});
      popup.addEventListener('mouseleave',()=>{if(active===pair){hovered=false;delayedClose();}});
      popup.addEventListener('focusout',delayedClose);
      popup.addEventListener('focusin',cancel);
    }
    doc.addEventListener('click',event=>{
      if(active&&event.target!==active.button&&!active.button.contains(event.target)&&!active.popup.contains(event.target))close();
    });
    doc.addEventListener('keydown',event=>{
      if(active&&event.key==='Escape'){
        const restore=active.popup.contains(doc.activeElement);close(restore);event.preventDefault();event.stopPropagation();
      }
    },true);
    win.addEventListener('resize',position);
    win.addEventListener('scroll',position,true);
    // Keep an open live explanation within the viewport when its text changes.
    const observer=win.ResizeObserver?new win.ResizeObserver(()=>{if(active)position();}):null;
    if(observer)for(const {popup} of pairs.values())observer.observe(popup);
    return {close,position};
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={place,install};return;}
  document.addEventListener('DOMContentLoaded',()=>install(document,window));
})();
