'use strict';
/* 가격 구간 패널: 계산된 갭·지지저항·매물대를 목록과 차트 선으로 표시한다.
   표시 항목은 사용자가 선택하며, 이 값은 종합판단 계산에 자동으로 들어가지 않는다. */
(function () {
  var pref = { gaps: true, levels: true, clusters: true };
  var lines = [];
  var COLORS = { gapUp: '#f2bb68', gapDown: '#75aaff', level: '#a4afc0', cluster: '#8996aa' };

  function chartSeries() {
    try { return typeof candles !== 'undefined' && candles && candles.createPriceLine ? candles : null; }
    catch (e) { return null; }
  }

  function clearLines() {
    var series = chartSeries();
    if (series) for (var i = 0; i < lines.length; i++) { try { series.removePriceLine(lines[i]); } catch (e) { } }
    lines = [];
  }

  function addLine(price, color, title, style, label) {
    var series = chartSeries();
    if (!series || !isFinite(price)) return;
    // 같은 가격대에 선이 겹치면 라벨만 늘고 화면이 지저분해진다.
    if (lines.some(function (x) { return Math.abs(x.__price - price) < Math.abs(price || 1) * 0.0005; })) return;
    try {
      var handle = series.createPriceLine({ price: price, color: color, lineWidth: 1,
        lineStyle: style == null ? 2 : style, title: title || '',
        axisLabelVisible: !!label });
      handle.__price = price;
      lines.push(handle);
    } catch (e) { }
  }

  function fmt(p) { return typeof fmtP === 'function' ? fmtP(p) : String(Math.round(p * 100) / 100); }
  function fmtTime(t) { return typeof fmtT === 'function' ? fmtT(t) : String(t); }

  function row(text, cls) {
    var li = document.createElement('li');
    if (cls) li.className = cls;
    li.textContent = text;
    return li;
  }

  function fillText(state) {
    return state === 'full' ? '전체 채움' : state === 'partial' ? '일부 채움' : '미채움';
  }

  function near(list, price, key, limit) {
    return list.slice().sort(function (a, b) {
      return Math.abs((a[key] || 0) - price) - Math.abs((b[key] || 0) - price);
    }).slice(0, limit);
  }

  function render() {
    var box = document.getElementById('priceZonesBody');
    clearLines();
    if (!box) return;
    var obs = typeof currentObs === 'function' ? currentObs() : null;
    var frame = obs && obs.f;
    var data = frame && frame.candles && typeof PriceZones !== 'undefined'
      ? PriceZones.build(frame.candles, obs.oi) : null;
    var summary = document.getElementById('priceZonesSummary');
    box.replaceChildren();
    if (!data) {
      if (summary) summary.textContent = '가격 구간을 계산할 봉이 부족해요.';
      return;
    }
    if (summary) {
      summary.textContent = '기준 봉 ' + fmtTime(data.to) + ' · 갭 ' + data.gaps.length + '곳 · 지지저항 후보 ' + data.levels.length + '개 · 매물대 ' + data.clusters.length + '구간';
    }

    if (pref.gaps) {
      var g = document.createElement('ul');
      g.className = 'zoneList';
      var pending = data.gaps.filter(function (x) { return x.state !== 'full'; });
      var shown = near(pending.map(function (x) { return { z: x, mid: (x.low + x.high) / 2 }; }), data.close, 'mid', 3);
      var filled = data.gaps.length - pending.length;
      if (!pending.length) g.appendChild(row('최근 미채움 갭이 없어요.', 'zoneEmpty'));
      shown.forEach(function (item) {
        var x = item.z;
        var dir = x.dir === 'up' ? '갭상승' : '갭하락';
        g.appendChild(row(dir + ' ' + fmt(x.low) + ' ~ ' + fmt(x.high) + ' · ' + fillText(x.state) + ' · ' + fmtTime(x.time)));
        addLine(x.high, x.dir === 'up' ? COLORS.gapUp : COLORS.gapDown, dir, 2, false);
        addLine(x.low, x.dir === 'up' ? COLORS.gapUp : COLORS.gapDown, '', 2, false);
      });
      if (pending.length > shown.length) g.appendChild(row('가까운 3곳만 차트에 표시했어요. 나머지 ' + (pending.length - shown.length) + '곳은 목록에만 있어요.', 'zoneEmpty'));
      if (filled) g.appendChild(row('채워진 갭 ' + filled + '곳은 표시하지 않았어요.', 'zoneEmpty'));
      box.appendChild(group('미채움 갭', g));
    }

    if (pref.levels) {
      var l = document.createElement('ul');
      l.className = 'zoneList';
      if (!data.levels.length) l.appendChild(row('반복해서 반응한 가격대가 아직 없어요.', 'zoneEmpty'));
      var picked = near(data.levels, data.close, 'price', 3);
      picked.forEach(function (x) {
        l.appendChild(row(x.role + ' ' + fmt(x.price) + ' · ' + x.touches + '회 반응 · 마지막 ' + fmtTime(x.lastTime)));
        addLine(x.price, COLORS.level, x.role, 0, true);
      });
      if (data.levels.length > picked.length) l.appendChild(row('가까운 3개만 차트에 표시했어요.', 'zoneEmpty'));
      box.appendChild(group('지지·저항 후보', l));
    }

    if (pref.clusters) {
      var c = document.createElement('ul');
      c.className = 'zoneList';
      if (!data.clusters.length) c.appendChild(row('거래가 몰린 구간이 아직 없어요.', 'zoneEmpty'));
      near(data.clusters, data.close, 'low', 2).forEach(function (x) {
        c.appendChild(row(fmt(x.low) + ' ~ ' + fmt(x.high) + ' · 거래량 비중 ' + (x.share * 100).toFixed(1) + '%' + (x.peak ? ' · 최다' : '')));
        addLine(x.high, COLORS.cluster, '매물대', 3, false);
        addLine(x.low, COLORS.cluster, '', 3, false);
      });
      box.appendChild(group('매물대', c));
    }
  }

  function group(title, list) {
    var wrap = document.createElement('div');
    wrap.className = 'zoneGroup';
    var h = document.createElement('h3');
    h.textContent = title;
    wrap.appendChild(h);
    wrap.appendChild(list);
    return wrap;
  }

  function bind(id, key) {
    var el = document.getElementById(id);
    if (!el) return;
    el.checked = pref[key];
    el.onchange = function () { pref[key] = el.checked; render(); };
  }

  function init() {
    bind('zoneShowGaps', 'gaps');
    bind('zoneShowLevels', 'levels');
    bind('zoneShowClusters', 'clusters');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  window.PriceZonesPanel = { render: render, clear: clearLines, pref: pref };
})();
