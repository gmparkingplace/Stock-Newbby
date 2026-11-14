/* 앱 내부 제작 선형 아이콘. 장식만 추가하고 기존 텍스트·이벤트는 유지한다. */
(function () {
  'use strict';
  const paths = {
    search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    refresh:'<path d="M20 7v5h-5M4 17v-5h5M5.4 7a8 8 0 0 1 13.2-1L20 8M4 16l1.4 2A8 8 0 0 0 18.6 17"/>',
    auto:'<path d="M8 4H5a1 1 0 0 0-1 1v3M16 4h3a1 1 0 0 1 1 1v3M4 16v3a1 1 0 0 0 1 1h3M20 16v3a1 1 0 0 1-1 1h-3M2 12h5l3-5 4 10 3-5h5"/>',
    help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4.2 1.8c-1 .7-1.7 1.1-1.7 2.7M12 17h.01"/>',
    sliders:'<path d="M4 7h3m4 0h9M4 17h9m4 0h3"/><circle cx="9" cy="7" r="2"/><circle cx="15" cy="17" r="2"/>',
    analysis:'<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M7 16v-4m5 4V8m5 8v-6"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    minus:'<path d="M5 12h14"/>',
    recent:'<path d="m5 7 5 5-5 5m6-10 5 5-5 5M20 5v14"/>',
    list:'<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    folder:'<path d="M3 8V6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    close:'<path d="m6 6 12 12M18 6 6 18"/>',
    eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    chart:'<path d="M4 4v16h16M8 14l4-5 4 3 5-7"/>',
    bookmark:'<path d="M6 4h12v17l-6-4-6 4Z"/>',
    more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
  };
  const urls = Object.fromEntries(Object.entries(paths).map(([name, shape]) => [name,
    'url("data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+shape+'</svg>') + '")']));
  document.addEventListener('DOMContentLoaded', () => {
    function decorate(el, name, label, iconOnly = false) {
      if (!el || !urls[name]) return;
      el.dataset.uiIcon = name;
      el.style.setProperty('--ui-icon', urls[name]);
      if (label) { el.setAttribute('aria-label', label); el.title = label; }
      if (iconOnly) el.classList.add('uiIconOnly');
    }
    const byId = (id, icon, label, only) => decorate(document.getElementById(id), icon, label, only);
    byId('btnLookup','search','종목 조회',true);
    byId('btnRefresh','refresh','시세 새로고침');
    byId('btnAuto','auto'); // ON/OFF 접근 이름은 기존 동적 문구를 따른다.
    byId('btnHelp','help','도움말',true);
    byId('openSettings','sliders','표시 설정');
    byId('openAnalysis','analysis','상세 보기');
    byId('zoomOut','minus','차트 축소',true);
    byId('zoomIn','plus','차트 확대',true);
    byId('btnRecent','recent','최근 봉으로 이동');
    byId('wlAddSymbol','plus','선택 카테고리에 종목 추가');
    document.getElementById('wlAddSymbol').textContent = '종목 추가';
    byId('wlAddGroup','folder','관심종목 그룹 추가');
    byId('wlManageGroup','list','관심종목 그룹 관리');
    byId('wlRefresh','refresh','관심종목 목록 새로고침');
    byId('tglObs','eye'); byId('tglSig','chart');
    for (const el of document.querySelectorAll('.helpTrigger')) decorate(el,'help',null,true);
    for (const el of document.querySelectorAll('.dialogHead>button')) decorate(el,'close',null,false);
    for (const id of ['wlSymbolClose','wlGroupClose','wlManageClose','patternClose','helpClose']) byId(id,'close');
    decorate(document.querySelector('.watchTitle h2'),'bookmark');
    decorate(document.querySelector('.watchManage>summary'),'more','관심종목 관리');
    document.documentElement.dataset.uiStyle = 'apple';
  });
})();
