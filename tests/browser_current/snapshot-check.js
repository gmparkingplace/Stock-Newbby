'use strict';
const assert = require('node:assert/strict');

function sameProfile(actual, expected) {
  if (actual == null || expected == null) { assert.equal(actual, expected); return; }
  const {bins: aBins, ...aRest} = actual, {bins: bBins, ...bRest} = expected;
  assert.deepEqual(aRest, bRest);
  assert.equal(aBins.length, bBins.length);
  for (let i = 0; i < aBins.length; i++) {
    const {share: a, ...aBin} = aBins[i], {share: b, ...bBin} = bBins[i];
    assert.deepEqual(aBin, bBin);
    // A division recomputed across JS engines/JIT tiers can differ by a final bit.
    assert(Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= 2 * Number.EPSILON,
      `volume share differs at bin ${i}: ${a} versus ${b}`);
  }
}

function sameSnapshot(actual, expected) {
  const {volumeProfile: a, ...aRest} = actual, {volumeProfile: b, ...bRest} = expected;
  assert.deepEqual(aRest, bRest);
  sameProfile(a, b);
}

function sameComputedModel(actual, expected, location = 'model') {
  if (typeof actual === 'number' && typeof expected === 'number') {
    assert(Number.isFinite(actual) && Number.isFinite(expected), `${location}: non-finite number`);
    // Arithmetic transported through different JS engines may differ by a few final bits.
    const tolerance = 4 * Number.EPSILON * Math.max(1, Math.abs(actual), Math.abs(expected));
    assert(Math.abs(actual - expected) <= tolerance, `${location}: ${actual} versus ${expected}`);
    return;
  }
  if (actual !== null && expected !== null && typeof actual === 'object' && typeof expected === 'object') {
    assert.equal(Array.isArray(actual), Array.isArray(expected), `${location}: container type`);
    assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort(), `${location}: keys`);
    for (const key of Object.keys(actual)) sameComputedModel(actual[key], expected[key], `${location}.${key}`);
    return;
  }
  assert.deepEqual(actual, expected, location);
}

function samePatternSnapshot(actual, expected) {
  const {candles: a, ...aRest} = actual, {candles: b, ...bRest} = expected;
  assert.deepEqual(a, b, 'raw snapshot candles');
  sameComputedModel(aRest, bRest);
}

module.exports = {sameProfile, sameSnapshot, sameComputedModel, samePatternSnapshot};
