#!/usr/bin/env python3
"""Control an existing chart tab using its loopback mailbox; stdlib only."""
import argparse,json,os,shutil,sys,tempfile,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlparse


def _lookup_candles(base_url, code):
    try:
        with urlopen(base_url + '/api/lookup?code=' + quote(code), timeout=20) as r:
            j = json.load(r)
    except HTTPError as e:
        raise RuntimeError('조회 실패 HTTP ' + str(e.code)) from None
    except (URLError, TimeoutError):
        raise RuntimeError('Local chart unavailable. Start the integrated app.') from None
    if isinstance(j, dict) and 'error' in j:
        raise RuntimeError('조회 오류: ' + str(j.get('error'))[:100])
    candles = j.get('candles') if isinstance(j, dict) else None
    if not candles:
        raise RuntimeError('차트 자료 없음: ' + code)
    return j, candles


def _resolve_vp_js(script_dir, base_url):
    """volume-profile.js 원문. 저장소 배치면 직접, 설치본이면 서버 정적 경로에서 가져온다."""
    for ancestor in Path(script_dir).parents:
        cand = ancestor / 'results' / 'dashboard' / 'volume-profile.js'
        if cand.is_file():
            return cand.read_text(encoding='utf-8'), 'repo-tree'
    last = None
    for path in ('/volume-profile.js', '/results/dashboard/volume-profile.js'):
        try:
            with urlopen(base_url + path, timeout=10) as r:
                return r.read().decode('utf-8'), 'server:' + path
        except Exception as e:
            last = e
    raise RuntimeError('volume-profile.js를 찾지 못했습니다') from last


_VP_DRIVER = (
    "const fs=require('fs');"
    "const vp=require(process.argv[1]);"
    "const candles=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
    "process.stdout.write(JSON.stringify(vp.build(candles,Number(process.argv[3]))));"
)


def run_vp(base_url, code, as_of):
    import subprocess
    node = shutil.which('node')
    if node is None:
        raise RuntimeError('node가 필요합니다 (engines: node>=22)')
    j, candles = _lookup_candles(base_url, code)
    if as_of is None:
        idx = len(candles) - 1
    else:
        idx = next((i for i, c in enumerate(candles) if c.get('time') == as_of), None)
        if idx is None:
            raise RuntimeError('해당 날짜 봉 없음 (정확한 봉 날짜 사용): ' + as_of)
    source, origin = _resolve_vp_js(Path(__file__).resolve().parent, base_url)
    with tempfile.TemporaryDirectory(prefix='chart-vp-') as tmp:
        vplib, datafile = Path(tmp, 'volume-profile.js'), Path(tmp, 'candles.json')
        vplib.write_text(source, encoding='utf-8')
        datafile.write_text(json.dumps(candles), encoding='utf-8')
        try:
            proc = subprocess.run([node, '-e', _VP_DRIVER, str(vplib), str(datafile), str(idx)],
                                  capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError('node 실행 실패: ' + str(e)[:100]) from None
    if proc.returncode != 0:
        raise RuntimeError('매물대 계산 실패: ' + proc.stderr.strip()[-200:])
    return {'symbol': j.get('symbol', code), 'asOf': candles[idx].get('time'),
            'index': idx, 'source': j.get('source'), 'jsOrigin': origin,
            'volumeProfile': json.loads(proc.stdout)}


def run_low(args):
    """Pure shared JS engine; only read the local candle cache or an explicit input."""
    import subprocess
    project = Path(args.project).resolve() if args.project else next(
        (root for root in Path(__file__).resolve().parents if (root / 'tools/audit-low-entry.js').is_file()), None)
    if project is None:
        raise RuntimeError('설치본에서는 low --project 통합프로젝트폴더를 지정하세요.')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('node>=22가 필요합니다')
    command = [node, str(project / 'tools/audit-low-entry.js'), '--symbol', args.symbol,
               '--tf', args.tf, '--as-of', args.as_of, '--max-atr', str(args.max_atr), '--strategy', args.strategy]
    if args.input:
        command += ['--input', str(Path(args.input).resolve())]
    else:
        command += ['--cache', str(Path(args.cache).resolve() if args.cache else project / 'logs/market-cache.sqlite3')]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if proc.returncode:
        raise RuntimeError('저점 구조 계산 실패: ' + proc.stderr.strip()[-300:])
    return json.loads(proc.stdout)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default=os.environ.get('CHART_ASSISTANT_URL','http://127.0.0.1:8734'))
    p.add_argument('--tab',help='tab ID from tabs; required if multiple tabs are connected')
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('tabs');sub.add_parser('inspect')
    r=sub.add_parser('result');r.add_argument('id')
    v=sub.add_parser('view');v.add_argument('--symbol');v.add_argument('--tf',choices=['D','W','H4','M']);v.add_argument('--period',choices=['1M','3M','6M','1Y','ALL']);v.add_argument('--as-of',help='exact bar date (YYYY-MM-DD; M uses month-end label) or latest')
    a=sub.add_parser('auto');a.add_argument('enabled',choices=['on','off'])
    v=sub.add_parser('vp');v.add_argument('--symbol',required=True);v.add_argument('--as-of',default='latest',help='exact bar date or latest')
    v=sub.add_parser('patterns');v.add_argument('--symbol',required=True);v.add_argument('--tf',choices=['D','W','M','H4'],default='D');v.add_argument('--kind',choices=['horizontal','flag','triangle'],default='horizontal')
    e=sub.add_parser('events');es=e.add_subparsers(dest='event_action',required=True)
    el=es.add_parser('list');el.add_argument('--symbol');el.add_argument('--cursor',type=int,default=0);el.add_argument('--tf',choices=['D','H4'])
    ev=es.add_parser('show');ev.add_argument('--id',required=True)
    low=sub.add_parser('low',help='저장 자료로 R/H 구조 계산; API 조회 없음')
    low.add_argument('--symbol',required=True);low.add_argument('--tf',choices=['D','H4'],default='D');low.add_argument('--as-of',default='latest')
    low.add_argument('--input');low.add_argument('--cache');low.add_argument('--project')
    low.add_argument('--max-atr',type=float,choices=[0.25,0.5,1],default=0.5);low.add_argument('--strategy',choices=['R','H','both'],default='both')
    m=sub.add_parser('monitor');ms=m.add_subparsers(dest='monitor_action',required=True)
    ms.add_parser('status');ms.add_parser('start');ms.add_parser('pause')
    args=p.parse_args();url=args.url.rstrip('/');u=urlparse(url)
    if u.scheme!='http' or u.hostname not in ('127.0.0.1','localhost') or u.path or u.username or u.password or u.query or u.fragment:
        p.error('Only a local chart server URL is allowed')
    def call(endpoint,body=None):
        data=json.dumps(body).encode() if body is not None else None
        req=Request(url+'/api/control/'+endpoint,data=data,headers={'Content-Type':'application/json','X-Chart-Control':'1'})
        try:
            with urlopen(req,timeout=8) as response:return json.load(response)
        except HTTPError as e:
            raise RuntimeError('Control API returned HTTP '+str(e.code)+'. Check tabs, arguments, and whether the updated server is running.') from None
        except (URLError,TimeoutError):raise RuntimeError('Local chart unavailable. Start the integrated app and refresh its browser tab.') from None
    def cached(path):
        try:
            with urlopen(url+path,timeout=8) as response:return json.load(response)
        except HTTPError as e:raise RuntimeError('패턴 캐시 HTTP '+str(e.code)+'. 기능 설정과 서버 버전을 확인하세요.') from None
        except (URLError,TimeoutError):raise RuntimeError('Local chart unavailable. Start the integrated app.') from None
    if args.action=='low':
        print(json.dumps(run_low(args),ensure_ascii=False,indent=2));return 0
    if args.action=='monitor':
        if args.monitor_action=='status':result=cached('/api/monitor/status')
        else:
            session=cached('/api/analysis-session')['sessionToken']
            req=Request(url+'/api/monitor/control',data=json.dumps({'action':args.monitor_action}).encode(),headers={'Content-Type':'application/json','X-Chart-Session':session})
            try:
                with urlopen(req,timeout=8) as response:result=json.load(response)
            except HTTPError as e:raise RuntimeError('서버 감시 HTTP '+str(e.code)) from None
            except (URLError,TimeoutError):raise RuntimeError('Local chart unavailable.') from None
    elif args.action=='patterns':
        result=cached('/api/patterns?symbol='+quote(args.symbol)+'&tf='+args.tf+'&kind='+args.kind)
    elif args.action=='events':
        if args.event_action=='list':
            result=cached('/api/events?cursor='+str(args.cursor)+('&symbol='+quote(args.symbol) if args.symbol else '')+('&tf='+args.tf if args.tf else ''))
        else:
            event=cached('/api/events/'+quote(args.id,safe=''))
            result=cached('/api/snapshots/'+quote(event['basisSnapshotId'],safe=''))
    elif args.action=='tabs':result=call('tabs')
    elif args.action=='result':result=call('result?id='+args.id)
    elif args.action=='vp':
        print(json.dumps(run_vp(url,args.symbol,None if args.as_of=='latest' else args.as_of),ensure_ascii=False,indent=2));return 0
    else:
        values={}
        if args.action=='view':
            values={k:v for k,v in {'symbol':args.symbol,'tf':args.tf,'period':args.period}.items() if v is not None}
            if args.as_of is not None:values['asOf']=None if args.as_of=='latest' else args.as_of
        elif args.action=='auto':values={'enabled':args.enabled=='on'}
        result=call('command',{'tab':args.tab,'action':args.action,'args':values})
        cid=result['id'];end=time.monotonic()+48
        while result['status'] in ('queued','running') and time.monotonic()<end:
            time.sleep(.4);result=call('result?id='+cid)
        if result['status']!='done':
            print(json.dumps(result,ensure_ascii=False,indent=2));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,ValueError) as e:print(str(e),file=sys.stderr);sys.exit(2)
