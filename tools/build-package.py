#!/usr/bin/env python3
"""Build a portable archive without machine-local config, credentials or logs."""
from pathlib import Path
import argparse,hashlib,json,sys,zipfile
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,help='archive output path')
args=parser.parse_args()
out=args.output.resolve() if args.output else root.parent/'chart-assistant-unified.zip'
if out==root or root in out.parents:
    parser.error('ZIP은 프로젝트 폴더 바깥에 저장하세요.')
ignored={'.venv','__pycache__','.pytest_cache','.git','logs','shots','work','private-backups'}
secrets=[]
if (root/'.local.json').is_file():
    sys.path.insert(0,str(root/'scripts'))
    from toss_market import read_credentials
    secrets=[s.encode() for s in read_credentials().values()]
files=[]
for p in sorted(root.rglob('*')):
    rel=p.relative_to(root)
    if any(part in ignored for part in rel.parts):continue
    if p.is_symlink():raise SystemExit('심볼릭 링크는 배포하지 않습니다: '+str(rel))
    if not p.is_file():continue
    if any(part in ignored for part in rel.parts):continue
    if p.name in {'.local.json','PACKAGE-MANIFEST.json','Open API.txt'}:continue
    if p.name=='.env' or (p.name.startswith('.env.') and p.name!='.env.example'):continue
    if p.suffix.lower() in {'.db','.sqlite','.sqlite3','.pem','.p12','.pfx','.log','.patch'}:continue
    if 'credentials' in p.name.lower() and p.suffix=='.txt' and p.name!='toss-credentials.example.txt':continue
    raw=p.read_bytes()
    if any(value and value in raw for value in secrets):
        raise SystemExit('민감한 값이 포함되어 패키징을 중단했습니다: '+str(rel))
    files.append({'path':str(rel),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
version=json.loads((root/'package.json').read_text())['version']
manifest={'name':'chart-assistant','version':version,'entry':'run.py','files':files}
(root/'PACKAGE-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for row in files:z.write(root/row['path'],'chart-assistant/'+row['path'])
    z.write(root/'PACKAGE-MANIFEST.json','chart-assistant/PACKAGE-MANIFEST.json')
with zipfile.ZipFile(out) as z:
    assert z.testzip() is None
    assert not any(name.endswith('/.local.json') for name in z.namelist())
print(f'패키지 {version}: {len(files)+1}개 파일, 로컬 설정·키·로그 제외, 무결성 검사 통과')
