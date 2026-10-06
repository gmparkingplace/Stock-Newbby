const assert=require('node:assert/strict');
const {importItems,rowLabel}=require('../results/dashboard/monitor-panel.js');
const groups={groups:[{name:'스윙',symbols:[{symbol:'AAPL',name:'애플'}]},{name:'기술',symbols:[{symbol:'AAPL',name:'애플'},{symbol:'BTC-USD',name:'코인'}]}]};
const before=JSON.stringify(groups),items=importItems(groups);
assert.equal(items.length,3);assert.equal(JSON.stringify(groups),before);assert.deepEqual(items[0].groups,['스윙']);
assert(rowLabel({enabled:true,profile:'normal',status:'watching'},true).includes('5분'));
assert(rowLabel({enabled:true,profile:'focus',status:'confirmed-history'},true).includes('현재 가격 미반영'));
assert.equal(rowLabel({enabled:true},false),'서버 감시 중지');
console.log('Monitor migration preview and freshness labels passed');
