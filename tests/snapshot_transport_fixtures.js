'use strict';
const assert = require('node:assert/strict');
const {sameProfile, sameSnapshot, sameComputedModel, samePatternSnapshot} = require('./browser_current/snapshot-check');
const profile = share => ({count:20, total:100, bins:[{low:10, high:11, volume:20, peak:false, share}]});
sameProfile(profile(.044494951346375516), profile(.04449495134637552));
assert.throws(() => sameProfile(profile(.04449495134637552 + 1e-10), profile(.04449495134637552)));
const wrongVolume = profile(.04449495134637552); wrongVolume.bins[0].volume++;
assert.throws(() => sameProfile(wrongVolume, profile(.04449495134637552)));
assert.throws(() => sameSnapshot({symbol:'A', volumeProfile:profile(.2)}, {symbol:'B', volumeProfile:profile(.2)}));
sameProfile(null, null);
assert.throws(() => sameProfile(null, profile(.2)));
assert.throws(() => sameProfile(profile(NaN), profile(.2)));
console.log('Snapshot transport: final-bit shares tolerated; changed data/identity still rejected');

sameComputedModel({price:114.99999999999999, line:{slope:-.09999999999999787}}, {price:115, line:{slope:-.09999999999999788}});
assert.throws(() => sameComputedModel({price:115 + 1e-9}, {price:115}));
assert.throws(() => sameComputedModel({volume:1001}, {volume:1000}));
assert.throws(() => sameComputedModel({status:'confirmed'}, {status:'pending'}));
assert.throws(() => sameComputedModel({date:'2026-09-06'}, {date:'2026-09-07'}));
assert.throws(() => sameComputedModel({price:NaN}, {price:115}));
assert.throws(() => sameComputedModel([115], {0:115}));
console.log('Computed model transport: final-bit arithmetic tolerated; changed price, volume, status and date rejected');

samePatternSnapshot({candles:[{close:115}],event:{price:114.99999999999999}}, {candles:[{close:115}],event:{price:115}});
assert.throws(() => samePatternSnapshot({candles:[{close:114.99999999999999}],event:{price:115}}, {candles:[{close:115}],event:{price:115}}));
