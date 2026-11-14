'use strict';
/* 가격 구간 계산: 미채움 갭, 지지·저항 후보, 거래가 모인 가격대.
   모두 불러온 봉에서 추정한 관찰 근거이며 지지·저항을 보장하지 않는다.
   자료가 빠진 구간(봉 간격이 평소보다 크게 벌어진 곳)은 가격 갭으로 계산하지 않는다. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PriceZones = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  function finite(v) { return typeof v === 'number' && isFinite(v); }

  /* 봉 시간은 숫자(분봉 epoch)일 수도, 'YYYY-MM-DD' 문자열(일·주·월봉)일 수도 있다. */
  function toEpoch(t) {
    if (finite(t)) return t;
    var ms = Date.parse(t);
    return isFinite(ms) ? ms / 1000 : NaN;
  }

  function withEpoch(cs) {
    return (cs || []).map(c => finite(c && c._t) ? c : Object.assign({ _t: toEpoch(c && c.time) }, c));
  }

  function usable(candles) {
    return (candles || []).filter(c => c && finite(toEpoch(c.time)) && finite(c.high) && finite(c.low) && finite(c.close)
      && c.low > 0 && c.high >= c.low).map(c => Object.assign({ _t: toEpoch(c.time) }, c));
  }

  function medianStep(cs) {
    var steps = [];
    for (var i = 1; i < cs.length; i++) {
      var d = cs[i]._t - cs[i - 1]._t;
      if (d > 0) steps.push(d);
    }
    if (!steps.length) return null;
    steps.sort(function (a, b) { return a - b; });
    return steps[Math.floor(steps.length / 2)];
  }

  function atrOf(cs, n) {
    n = n || 14;
    if (cs.length < n + 1) return null;
    var sum = 0;
    for (var i = cs.length - n; i < cs.length; i++) {
      var prev = cs[i - 1];
      var tr = Math.max(cs[i].high - cs[i].low,
        Math.abs(cs[i].high - prev.close), Math.abs(cs[i].low - prev.close));
      if (!finite(tr)) return null;
      sum += tr;
    }
    return sum / n;
  }

  /* 빈 구간: 앞봉 고가보다 다음 봉 저가가 높거나(위쪽), 앞봉 저가보다 다음 봉 고가가 낮은(아래쪽) 구간. */
  function gaps(cs, opts) {
    opts = opts || {};
    cs = withEpoch(cs);
    var atr = opts.atr, step = opts.stepSeconds || medianStep(cs);
    var minAtr = opts.minAtr == null ? 0.25 : opts.minAtr;
    var out = [];
    for (var i = 1; i < cs.length; i++) {
      var a = cs[i - 1], b = cs[i];
      if (step && b._t - a._t > step * (opts.gapRatio || 5)) continue; // 자료 누락 구간은 갭이 아니다
      var dir, low, high;
      if (b.low > a.high) { dir = 'up'; low = a.high; high = b.low; }
      else if (b.high < a.low) { dir = 'down'; low = b.high; high = a.low; }
      else continue;
      var size = high - low;
      if (!(size > 0)) continue;
      if (atr && size < atr * minAtr) continue;
      var state = 'none', fillTime = null;
      for (var j = i + 1; j < cs.length; j++) {
        var c = cs[j];
        if (dir === 'up') {
          if (c.low <= low) { state = 'full'; fillTime = c.time; break; }
          if (c.low < high) state = 'partial';
        } else {
          if (c.high >= high) { state = 'full'; fillTime = c.time; break; }
          if (c.high > low) state = 'partial';
        }
      }
      out.push({ kind: 'gap', dir: dir, low: low, high: high, size: size,
        atrRatio: atr ? size / atr : null, fromIndex: i, time: b.time,
        state: state, fillTime: fillTime });
    }
    return out;
  }

  function pivots(cs, span) {
    span = span || 3;
    cs = withEpoch(cs);
    var highs = [], lows = [];
    for (var i = span; i < cs.length - span; i++) {
      var isHigh = true, isLow = true;
      for (var k = 1; k <= span; k++) {
        if (cs[i].high < cs[i - k].high || cs[i].high <= cs[i + k].high) isHigh = false;
        if (cs[i].low > cs[i - k].low || cs[i].low >= cs[i + k].low) isLow = false;
      }
      if (isHigh) highs.push({ price: cs[i].high, time: cs[i].time, _t: cs[i]._t, kind: 'high', index: i });
      if (isLow) lows.push({ price: cs[i].low, time: cs[i].time, _t: cs[i]._t, kind: 'low', index: i });
    }
    return highs.concat(lows);
  }

  /* 반복해서 반응한 가격대를 하나의 선으로 묶는다. 허용 폭은 ATR 비율로 정한다. */
  function levels(cs, opts) {
    opts = opts || {};
    cs = withEpoch(cs);
    var atr = opts.atr, tol = atr ? atr * (opts.tolerance == null ? 0.5 : opts.tolerance) : 0;
    var pts = pivots(cs, opts.span == null ? 3 : opts.span).sort(function (a, b) { return a.price - b.price; });
    var groups = [];
    for (var i = 0; i < pts.length; i++) {
      var g = groups[groups.length - 1];
      if (g && pts[i].price - g.max <= tol) {
        g.items.push(pts[i]);
        g.max = Math.max(g.max, pts[i].price);
      } else groups.push({ min: pts[i].price, max: pts[i].price, items: [pts[i]] });
    }
    var close = cs[cs.length - 1].close;
    return groups.map(function (g) {
      var prices = g.items.map(function (p) { return p.price; });
      var price = prices.reduce(function (a, b) { return a + b; }, 0) / prices.length;
      var kinds = g.items.map(function (p) { return p.kind; });
      var kind = kinds.every(function (k) { return k === 'high'; }) ? 'high'
        : kinds.every(function (k) { return k === 'low'; }) ? 'low' : 'mixed';
      var latest = g.items.reduce(function (a, b) { return (b._t > a._t) ? b : a; });
      return { kind: 'level', price: price, touches: g.items.length, pivotKind: kind,
        role: price >= close ? '저항 후보' : '지지 후보', lastTime: latest.time, lastEpoch: latest._t };
    }).filter(function (l) { return l.touches >= (opts.minTouches || 2); })
      .sort(function (a, b) { return b.touches - a.touches || b.lastEpoch - a.lastEpoch; })
      .slice(0, opts.maxLevels || 6)
      .concat(recentSingles(cs, groups, tol, pts, 3));
  }

  /* VolumeProfile 모듈이 없을 때(단독 실행·검사) 쓰는 같은 방식의 대체 계산. */
  function localProfile(candles, index) {
    var cs = (candles || []).slice(0, index + 1).filter(function (c) {
      return c && [c.low, c.high, c.close, c.volume].every(finite) && c.low > 0 && c.high >= c.low && c.volume >= 0;
    });
    if (cs.length < 10) return null;
    var low = Math.min.apply(null, cs.map(function (c) { return c.low; }));
    var high = Math.max.apply(null, cs.map(function (c) { return c.high; }));
    var n = high === low ? 1 : 12, step = (high - low) / n;
    var bins = [];
    for (var i = 0; i < n; i++) bins.push({ low: low + i * step, high: low + (i + 1) * step, volume: 0 });
    cs.forEach(function (c) {
      var k = step ? Math.min(n - 1, Math.max(0, Math.floor(((c.high + c.low + c.close) / 3 - low) / step))) : 0;
      bins[k].volume += c.volume;
    });
    var total = bins.reduce(function (a, b) { return a + b.volume; }, 0);
    var max = Math.max.apply(null, bins.map(function (b) { return b.volume; }));
    return { bins: bins.map(function (b) {
      return { low: b.low, high: b.high, volume: b.volume, share: total ? b.volume / total : 0, peak: total > 0 && b.volume === max };
    }), total: total };
  }

  /* 반복 반응이 적은 구간에서도 최근 고점·저점을 관찰 후보로 채운다(1회 반응 표기). */
  function recentSingles(cs, groups, tol, pts, want) {
    var chosen = groups.filter(function (g) { return g.items.length >= 2; })
      .map(function (g) { return g.items.reduce(function (a, b) { return a + b.price; }, 0) / g.items.length; });
    var singles = pts.slice().sort(function (a, b) { return b._t - a._t; });
    var out = [];
    for (var i = 0; i < singles.length && out.length < want; i++) {
      var p = singles[i];
      if (chosen.some(function (c) { return Math.abs(c - p.price) <= tol; })) continue;
      if (out.some(function (o) { return Math.abs(o.price - p.price) <= tol; })) continue;
      out.push({ kind: 'level', price: p.price, touches: 1, pivotKind: p.kind,
        role: p.price >= cs[cs.length - 1].close ? '저항 후보' : '지지 후보',
        lastTime: p.time, lastEpoch: p._t });
    }
    return out;
  }

  /* 거래량이 몰린 가격대. VolumeProfile이 있으면 그 결과를 쓰고, 없으면 같은 방식으로 직접 나눈다. */
  function clusters(candles, index, opts) {
    opts = opts || {};
    var profile = null;
    if (typeof VolumeProfile !== 'undefined' && VolumeProfile.build) {
      try { profile = VolumeProfile.build(candles, index); } catch (e) { profile = null; }
    }
    if (!profile) profile = localProfile(candles, index);
    if (!profile) return [];
    var bins = profile.bins.slice().sort(function (a, b) { return b.volume - a.volume; });
    var mean = profile.total / (profile.bins.length || 1);
    var picked = bins.filter(function (b) { return b.volume >= mean * 1.2 && b.volume > 0; })
      .slice(0, opts.maxClusters || 3);
    return picked.map(function (b) {
      return { kind: 'cluster', low: b.low, high: b.high, volume: b.volume, share: b.share, peak: !!b.peak };
    }).sort(function (a, b) { return a.low - b.low; });
  }

  function build(candles, index, opts) {
    opts = opts || {};
    var limit = opts.index == null ? Infinity : toEpoch(candles[opts.index] && candles[opts.index].time);
    var cs = usable(candles).filter(function (c) { return !isFinite(limit) || c._t <= limit; });
    if (cs.length < 10) return null;
    var atr = atrOf(cs, 14);
    var step = opts.stepSeconds || medianStep(cs);
    return {
      version: 'zones-1',
      atr: atr,
      from: cs[0].time,
      to: cs[cs.length - 1].time,
      close: cs[cs.length - 1].close,
      gaps: gaps(cs, { atr: atr, stepSeconds: step, minAtr: opts.minGapAtr }),
      levels: levels(cs, { atr: atr, tolerance: opts.tolerance, maxLevels: opts.maxLevels }),
      clusters: clusters(candles, opts.index == null ? candles.length - 1 : opts.index, opts)
    };
  }

  return { build: build, gaps: gaps, levels: levels, clusters: clusters, pivots: pivots, atr: atrOf };
});
