#!/usr/bin/env python3
"""Create a local virtual environment and install the pinned runtime dependencies."""
import argparse
from pathlib import Path
import subprocess
import venv
import os

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description='차트 보조기 Python 환경 설치 (인터넷 필요)')
parser.add_argument('--dev', action='store_true', help='pytest도 설치')
parser.add_argument('--desktop', action='store_true', help='PySide6 데스크톱 앱 의존성도 설치')
args = parser.parse_args()
venv.EnvBuilder(with_pip=True).create(root / '.venv')
python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
files = ['requirements-dev.txt' if args.dev else 'requirements-lock.txt']
if args.desktop:
    files.append('requirements-desktop.txt')
for name in files:
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(root / name)], check=True)
print('설치 완료. start.sh 또는 start.bat으로 실행하세요.')
