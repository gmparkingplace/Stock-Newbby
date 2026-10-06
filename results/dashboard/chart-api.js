(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.ChartApi=factory();})(typeof self!=='undefined'?self:this,function(){
'use strict';
// Caller cancellation and network timeout have different outcomes.
async function get(url, timeoutMs = 20000, signal) {
  const ctl = new AbortController();
  let timedOut = false;
  const cancel = () => ctl.abort();
  if (signal?.aborted) cancel();
  else signal?.addEventListener('abort', cancel, {once:true});
  const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, timeoutMs);
  try {
    const response = await fetch(url, {signal:ctl.signal,cache:'no-store'});
    if (!response.ok) {
      let data = {};
      try { data = await response.json(); } catch (_) {}
      const error = new Error(data.error || 'HTTP ' + response.status);
      error.kind = data.kind || 'provider';
      error.status = response.status;
      error.upstreamStatus = data.upstreamStatus || null;
      error.retryAt = data.retryAt || null;
      throw error;
    }
    return await response.json();
  } catch (error) {
    if (signal?.aborted) throw error;
    if (timedOut) {
      const failure = new Error('조회 시간초과(' + timeoutMs/1000 + '초)');
      failure.kind = 'timeout';
      throw failure;
    }
    if (!error.kind) error.kind = 'network';
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
  }
}
return {get};
});
