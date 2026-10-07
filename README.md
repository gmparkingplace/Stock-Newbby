# 초보자 차트 보조기

주식·코인 차트에서 진입 조건, 저점 회복·상승, 플래그·삼각수렴, 지지·저항과 매물대를 확인하는 로컬 앱입니다. 데스크톱 PC용이며 모바일 사용은 지원하지 않습니다. 신호는 조건 검토를 위한 표시이며 주문을 실행하지 않습니다.

배포판에는 API 키·토큰·계좌/보유/매매 내역·관심목록·조회 캐시·개인 개발 기록을 포함하지 않습니다. 내장 차트는 **합성 예시 데이터이며 실제 시세가 아닙니다.**

## 설치와 실행

Python 3.11 이상을 권장합니다. 채팅 분석 도구와 개발 검사는 Node.js 22 이상이 필요합니다. 차트만 사용할 때 Node.js 설치는 필요하지 않습니다.

```bash
git clone https://github.com/gmparkingplace/Stock-Newbby.git
cd Stock-Newbby
python3 setup.py
cp .local.example.json .local.json
bash start.sh
```

Windows에서는 `python setup.py`, `.local.example.json`을 `.local.json`으로 복사한 뒤 `start.bat`을 실행합니다. 브라우저에서 `http://127.0.0.1:8734/chart-first.html`을 엽니다. 기본 브라우저 하나를 사용하며, 종료는 실행 터미널의 Ctrl+C입니다.

키 없이 실행하면 주식·코인은 yfinance로 조회합니다. 설치 없이 합성 예시만 보려면 `python3 run.py --offline`을 실행합니다. 월봉도 합성 예시이며 예측 자료가 아닙니다. 기본 포트를 사용 중이면 `python3 run.py --port 8735`로 변경합니다.

주식 조회는 **설정된 토스 API → 미설정·미지원 시 Yahoo Finance** 순서입니다. 토스 조회가 실패하면 오류를 표시하며 공급처를 자동으로 바꾸지 않습니다. 코인·지수는 Yahoo Finance를 사용합니다. 토스가 미설정이면 `exchange-calendars`의 한국·미국 정규장 캘린더로 휴장일·단축장·서머타임과 봉 확정을 처리합니다. 캘린더는 실시간 거래소 운영 상태가 아니며, 시세 지연·확정봉 재조회 검사는 계속 적용됩니다.

야후 과거 봉에 가격·거래량 오류가 있으면 마지막 오류 봉 뒤의 정상 구간부터 지표·패턴을 다시 계산합니다. 상단 자료 안내와 출처 상세에 제외한 구간을 표시합니다. 최신 봉이 잘못됐거나 정상 자료가 부족하면 판단을 보류합니다.

## 토스 API 설정 — 배포판은 빈 값

[토스 연결 안내](docs/TOSS.md)를 따라 **사용자 자신의 키**를 설정합니다. 빈 양식은 `toss-credentials.example.txt`입니다.

```text
Client Id:
Client Secret:
```

양식을 프로젝트 바깥의 개인 파일로 복사해 값을 입력한 뒤 경로를 등록합니다.

```bash
python3 tools/configure-toss.py "/개인/설정/폴더/toss-credentials.txt"
```

설정 후 서버를 다시 실행합니다. 키는 외부 파일에 남고 서버만 읽습니다. 브라우저·스킬·Git에 키를 넣지 않습니다. 주식 4시간봉은 토스 1분봉을 집계하며, 미설정 시 yfinance를 사용합니다. 코인·지수는 토스 키 유무와 관계없이 yfinance를 사용합니다. `.local.json`과 `logs/`는 각 사용자의 로컬 설정·자료이며 배포에서 제외됩니다.

## 주요 기능

- 일봉·주봉·월봉·4시간봉과 과거 기준일 비교
- A 추세 전환·B 침체 반등·돌파 전략, A/B 신호 이후 최대 3봉 검토
- R 저점 회복·재시험·반등 돌파, H 높은 저점·중간 고점 돌파
- SMA/EMA/WMA 20·60·120·200, 볼린저밴드·돈치안 채널
- RSI·ATR·거래량·MACD·OBV, 금액별 매물대
- 최근 3개월 플래그·삼각수렴 영역, 지지·저항 돌파와 사건 이력
- 관심종목과 서버 일봉 패턴 감시, 로컬 채팅 제어·저장 자료 분석

`.local.example.json`은 공유 캐시와 패턴·감시 기능을 활성화하는 예시입니다. 서버 감시는 화면 자동갱신과 별도이며 등록·시작해야 작동합니다. 저점 매수는 화면의 **전략군 → 저점 매수**에서 선택합니다. 용어 설명은 `?`에서 확인합니다.

앱은 수집 시각·판단 봉·확정 여부를 구별합니다. 장중 판단은 잠정이며 공급처 지연을 보증하지 않습니다. 캐시 분석을 실시간 시세로 표시하지 않습니다. 신호의 수익성은 검증되지 않았습니다.

## 채팅 스킬

```bash
python3 tools/install-chart-skill.py
# 기존 설치본 갱신:
python3 tools/install-chart-skill.py --update
```

Codex에서 `$chart-assistant`로 호출합니다. 화면 제어에는 실행 중인 서버와 차트 탭이 필요합니다. 저장 자료 R/H 분석은 서버·브라우저 없이 실행합니다.

```bash
python3 skills/chart-assistant/scripts/chartctl.py low --symbol BTC-USD --tf H4
```

조회한 캐시가 먼저 있어야 합니다. 설치된 스킬을 직접 실행할 때에는 `low --project "/프로젝트/폴더"`를 지정합니다. 스킬은 키와 주문 권한을 갖지 않습니다.

## 개발과 재배포

```bash
python3 setup.py --dev
npm test
.venv/bin/python -m pytest -q
python3 tools/build-package.py
python3 tools/verify-package.py
```

개발 작업본에서 개인 자료 없는 배포 트리를 만들려면 `python3 tools/build-public-release.py --output /새/배포/폴더`를 실행합니다. 기존 파일이 있는 폴더에는 덮어쓰지 않습니다. 배포 ZIP은 로컬 설정·키·로그를 제외합니다.

화면: `results/dashboard/chart-first.html`, 서버: `scripts/serve_dashboard.py`, 저점 모델: `results/dashboard/low-structure-rules.js`, 기능 계약: [docs/FEATURES.md](docs/FEATURES.md). 차트 라이브러리 출처는 `results/dashboard/lib/SOURCE.txt`입니다.

## 보안

외부 웹사이트의 로컬 서버 요청과 폴더 밖 파일 접근을 차단합니다. 키·개인 자료는 저장소에 올리지 않습니다. 지원 범위와 신고 방법은 [보안 안내](SECURITY.md)를 확인하세요.
