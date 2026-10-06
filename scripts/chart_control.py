"""Loopback-only command mailbox. Browser acknowledges actual rendered results."""
import json
import re
import threading
import time
import uuid
from urllib.parse import urlparse, parse_qs

class ControlStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.tabs = {}
        self.commands = {}

    def prune(self):
        now = time.time()
        self.tabs = {k:v for k,v in self.tabs.items() if now-v['seenAt'] < 120}
        self.commands = {k:v for k,v in self.commands.items() if now-v['createdAt'] < 600}
        for c in self.commands.values():
            if c['status'] in ('queued','running') and now > c['deadline']:
                c['status'] = 'expired'

    def register(self, body):
        tab = body.get('tab')
        if not isinstance(tab,str) or not re.fullmatch(r'[a-zA-Z0-9-]{8,80}',tab):
            raise ValueError('invalid tab')
        with self.lock:
            self.prune()
            if tab not in self.tabs and len(self.tabs) >= 32: raise ValueError('too many tabs')
            self.tabs[tab] = {'tab':tab,'seenAt':time.time(),'snapshot':body.get('snapshot')}
            for c in self.commands.values():
                if c['tab']==tab and c['status']=='queued':
                    c['status']='running'
                    return {'command':dict(c)}
            return {'command':None}

    def submit(self, body):
        action = body.get('action')
        if action not in ('view','inspect','auto'): raise ValueError('unsupported action')
        args = body.get('args',{})
        if not isinstance(args,dict): raise ValueError('invalid args')
        allowed = {'view':{'symbol','tf','period','asOf'},'inspect':set(),'auto':{'enabled'}}[action]
        if set(args)-allowed: raise ValueError('unsupported arguments')
        if 'symbol' in args and (not isinstance(args['symbol'],str) or not re.fullmatch(r'[A-Za-z0-9^][A-Za-z0-9.^=-]{0,29}',args['symbol'])): raise ValueError('invalid symbol')
        if 'tf' in args and args['tf'] not in ('D','W','H4','M'): raise ValueError('invalid timeframe')
        if 'period' in args and args['period'] not in ('1M','3M','6M','1Y','ALL'): raise ValueError('invalid period')
        if 'asOf' in args and args['asOf'] is not None and (not isinstance(args['asOf'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',args['asOf'])): raise ValueError('invalid date')
        if action=='auto' and type(args.get('enabled')) is not bool: raise ValueError('enabled must be boolean')
        with self.lock:
            self.prune()
            active=[k for k,v in self.tabs.items() if time.time()-v['seenAt']<15]
            tab=body.get('tab')
            if tab is None:
                if len(active)!=1: raise ValueError('choose one connected tab with --tab; use tabs first')
                tab=active[0]
            if tab not in active: raise ValueError('tab disconnected; open or refresh the chart')
            if any(c['tab']==tab and c['status'] in ('queued','running') for c in self.commands.values()): raise ValueError('tab busy; inspect previous command result')
            if len(self.commands)>=512: raise ValueError('command capacity reached')
            now=time.time();cid=uuid.uuid4().hex
            command={'id':cid,'tab':tab,'action':action,'args':args,'status':'queued','createdAt':now,'deadline':now+45}
            self.commands[cid]=command
            return dict(command)

    def result(self, body):
        with self.lock:
            self.prune();c=self.commands.get(body.get('id'))
            if not c or c['tab']!=body.get('tab'): raise ValueError('unknown command')
            if c['status']=='running':
                c.update(status='failed' if body.get('error') else 'done',result=body.get('snapshot'),error=body.get('error'))
            return dict(c)

STORE=ControlStore()

def handle(handler):
    u=urlparse(handler.path)
    if not u.path.startswith('/api/control/'): return False
    def reply(code, payload):
        raw=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
        handler.send_response(code);handler.send_header('Content-Type','application/json; charset=utf-8')
        handler.send_header('Cache-Control','no-store');handler.send_header('Content-Length',str(len(raw)))
        handler.end_headers();handler.wfile.write(raw)
    hosts={f'127.0.0.1:{handler.server.server_port}',f'localhost:{handler.server.server_port}'}
    origin=handler.headers.get('Origin')
    if handler.headers.get('Host') not in hosts or handler.headers.get('X-Chart-Control')!='1' or (origin and origin not in {'http://'+h for h in hosts}):
        reply(403,{'error':'local control header and same origin required'});return True
    try:
        if handler.command=='GET':
            with STORE.lock:
                STORE.prune()
                if u.path=='/api/control/tabs':
                    reply(200,{'tabs':list(STORE.tabs.values())})
                elif u.path=='/api/control/result':
                    cid=parse_qs(u.query).get('id',[''])[0]
                    reply(200,dict(STORE.commands[cid])) if cid in STORE.commands else reply(404,{'error':'unknown command'})
                else:reply(404,{'error':'unknown endpoint'})
        elif handler.command=='POST':
            length=int(handler.headers.get('Content-Length','0'))
            if not 0<length<=65536: raise ValueError('invalid body size')
            if handler.headers.get_content_type()!='application/json': raise ValueError('JSON required')
            body=json.loads(handler.rfile.read(length))
            if not isinstance(body,dict): raise ValueError('JSON object required')
            fn={'/api/control/poll':STORE.register,'/api/control/command':STORE.submit,'/api/control/result':STORE.result}.get(u.path)
            if fn is None:reply(404,{'error':'unknown endpoint'})
            else:reply(200,fn(body))
        else:reply(405,{'error':'method not allowed'})
    except (ValueError,TypeError,KeyError):
        reply(400,{'error':'Invalid command, unavailable/busy tab or ambiguous tab. Check tabs and arguments.'})
    return True
