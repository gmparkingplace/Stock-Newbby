"""Optional asynchronous market lookup API; loopback origin and session protected."""
from copy import deepcopy
import json
from secrets import token_urlsafe, compare_digest
from threading import RLock, Thread
from time import time
from urllib.parse import urlparse

SESSION_TOKEN = token_urlsafe(32)


class AnalysisJobs:
    def __init__(self, clock=time, max_jobs=64, max_active=32):
        self.clock,self.max_jobs,self.max_active=clock,max_jobs,max_active
        self.lock=RLock()
        self.jobs,self.active={},{}

    def submit(self, symbol, timeframe, force, fn):
        from request_scheduler import QueueBusy
        with self.lock:
            now=self.clock()
            for ident,job in list(self.jobs.items()):
                if job['status'] in ('done','failed') and now-job['updatedAt']>300:
                    del self.jobs[ident]
            key=(symbol,timeframe)
            if key in self.active:
                return deepcopy(self.jobs[self.active[key]])
            if len(self.active)>=self.max_active:
                raise QueueBusy()
            if len(self.jobs)>=self.max_jobs:
                finished=[j for j in self.jobs.values() if j['status'] in ('done','failed')]
                if not finished:raise QueueBusy()
                del self.jobs[min(finished,key=lambda j:j['updatedAt'])['jobId']]
            ident=token_urlsafe(18)
            job=dict(jobId=ident,status='queued',symbol=symbol,timeframe=timeframe,updatedAt=now)
            self.jobs[ident]=job;self.active[key]=ident
            Thread(target=self._run,args=(key,ident,fn),daemon=True,name='chart-analysis').start()
            return deepcopy(job)

    def _run(self, key, ident, fn):
        with self.lock:self.jobs[ident].update(status='running',updatedAt=self.clock())
        try:
            result=fn()
            value=dict(status='done',result=result)
        except Exception as error:
            value=dict(status='failed',error={
                'kind':getattr(error,'code','provider'),'upstreamStatus':None if getattr(error,'code',None)=='queue-busy' else getattr(error,'status',None),
                'retryAt':getattr(error,'retry_at',None),'lastSuccessAt':getattr(error,'last_success_at',None),
                'stale':True})
        with self.lock:
            self.jobs[ident].update(**value,updatedAt=self.clock())
            self.active.pop(key,None)

    def get(self, ident):
        with self.lock:
            job=self.jobs.get(ident)
            if job and job['status'] in ('done','failed') and self.clock()-job['updatedAt']>300:
                del self.jobs[ident]
                return None
            return deepcopy(job)


JOBS=AnalysisJobs()


def _reply(handler, status, payload):
    body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
    handler.send_response(status)
    handler.send_header('Content-Type','application/json; charset=utf-8')
    handler.send_header('Content-Length',str(len(body)))
    handler.send_header('Cache-Control','no-store')
    # These endpoints intentionally do not provide wildcard CORS.
    handler.end_headers();handler.wfile.write(body)
    return True


def _local(handler):
    allowed={f'127.0.0.1:{handler.server.server_port}',f'localhost:{handler.server.server_port}'}
    host=handler.headers.get('Host','')
    origin=handler.headers.get('Origin')
    return host in allowed and (not origin or origin=='http://'+host) and handler.headers.get('Sec-Fetch-Site','none') in ('none','same-origin')


def handle(handler):
    path=urlparse(handler.path).path
    if path!='/api/analysis-session' and path!='/api/analysis-jobs' and not path.startswith('/api/analysis-jobs/'):
        return False
    if not _local(handler):return _reply(handler,403,{'kind':'same-origin-required'})
    import market_cache
    if not market_cache.enabled():return _reply(handler,503,{'kind':'shared-cache-disabled'})
    method=handler.command
    if path=='/api/analysis-session' and method=='GET':
        return _reply(handler,200,{'sessionToken':SESSION_TOKEN})
    supplied=handler.headers.get('X-Chart-Session','')
    if len(supplied)>128 or not supplied.isascii() or not compare_digest(supplied,SESSION_TOKEN):
        return _reply(handler,403,{'kind':'session-required'})
    if path.startswith('/api/analysis-jobs/') and method=='GET':
        job=JOBS.get(path.rsplit('/',1)[1])
        return _reply(handler,200 if job else 404,job or {'kind':'job-not-found'})
    if path!='/api/analysis-jobs' or method!='POST':return _reply(handler,405,{'kind':'method-not-allowed'})
    try:
        length=int(handler.headers.get('Content-Length','0'))
        if not 0<length<=1024 or handler.headers.get('Content-Type','').split(';')[0]!='application/json':
            raise ValueError('invalid-request')
        data=json.loads(handler.rfile.read(length))
        from universe import norm_code
        raw=data.get('symbol')
        if not isinstance(raw,str) or not 0<len(raw)<=80:raise ValueError('invalid-symbol')
        symbol=norm_code(raw)
        tf=data.get('timeframe','D');force=data.get('force',False)
        if not symbol or tf not in ('D','W','M','H4') or not isinstance(force,bool):raise ValueError('invalid-request')
        from serve_dashboard import market_lookup, market_intraday
        fn=market_intraday if tf=='H4' else market_lookup
        job=JOBS.submit(symbol,tf,force,lambda:fn(symbol,force=force,background=True))
        return _reply(handler,202,job)
    except (ValueError,TypeError,AttributeError):
        return _reply(handler,400,{'kind':'invalid-request'})
    except Exception as error:
        return _reply(handler,503,{'kind':getattr(error,'code','queue-busy'),'retryAt':getattr(error,'retry_at',None)})
