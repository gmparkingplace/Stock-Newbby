#!/usr/bin/env python3
"""Configure an external credential file. This command never authenticates."""
import argparse
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='토스 외부 키 파일 위치 설정 (키 복사·인증 없음)')
parser.add_argument('credentials_file', type=Path)
args = parser.parse_args()
file = args.credentials_file.expanduser().resolve()
if not file.is_file():parser.error('지정한 파일이 없습니다.')
config = root / '.local.json'
current = json.loads(config.read_text()) if config.exists() else {}
current['tossCredentialsFile'] = str(file)
config.write_text(json.dumps(current,ensure_ascii=False,indent=2))
config.chmod(0o600)
print('외부 키 파일 위치를 설정했습니다. 다음 서버 실행부터 적용됩니다.')
