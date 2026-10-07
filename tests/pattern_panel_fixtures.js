'use strict';
const assert=require('node:assert/strict');
const {view}=require('../results/dashboard/pattern-panel.js');
const analysis={enabled:true,symbol:'TEST',sourceStatus:'ready',provisionalEligible:true,ruleVersion:'fixture',dataRevision:'r1',sourceFetchedAt:'fixture',
  timeline:[{barTime:'2026-01-01',confirmed:true,status:'ready',levels:[{status:'forming',boundary:100}]},{barTime:'2026-01-02',confirmed:false,status:'ready',levels:[{status:'breakout-pending',boundary:100}]}],
  recentEvents:[{confirmedBarTime:'2026-01-02',eventId:'future'},{confirmedBarTime:'2026-01-01',eventId:'past'}]};
assert.equal(view(null,'D',null,false).status,'disabled');
assert.equal(view(null,'W',null,false).status,'disabled');
assert.equal(view(analysis,'M',null,false).status,'unsupported');
assert.equal(view(analysis,'D',null,false).levels[0].status,'breakout-pending');
assert.equal(view(analysis,'D',null,true).levels[0].status,'paused');
assert.equal(view({...analysis,provisionalEligible:false},'D',null,false).levels[0].status,'paused');
const historical=view(analysis,'D','2026-01-01',false);
assert.deepEqual(historical.events.map(x=>x.eventId),['past']);
assert.equal(historical.levels[0].status,'forming');
assert.equal(analysis.timeline[1].levels[0].status,'breakout-pending');
const h4={...analysis,timeframe:'H4',timeline:analysis.timeline.map((r,i)=>({...r,barTime:1791200000+i*14400,levels:r.levels.map(l=>({...l,barTime:1791200000+i*14400}))})),recentEvents:[]};
assert.equal(view(h4,'H4',null,false).levels[0].status,'breakout-pending');
assert.equal(view(analysis,'H4',null,false).status,'unsupported','daily results must not leak into H4');
assert.equal(view(h4,'H4',1791200000,false).levels[0].status,'forming');
console.log('Pattern panel fixtures passed');
