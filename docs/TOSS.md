# 토스증권 연결

배포 기본값은 미설정입니다. `toss-credentials.example.txt`의 Client Id·Client Secret은 비어 있습니다. 외부 개인 파일에 자신의 값을 입력하고 `python3 tools/configure-toss.py "/키/파일/경로"`로 등록하거나 `TOSS_CREDENTIALS_FILE` 환경변수에 파일 경로를 지정합니다.

`.local.json`은 외부 파일 경로만 저장합니다. 토큰은 서버 메모리에만 보관합니다. 설정 도구는 인증하지 않으며 실제 시세 요청이 시작되면 서버가 인증합니다. 브라우저에는 인증 정보를 전달하지 않습니다. 계좌·보유·주문 API는 지원하지 않습니다.

국내·미국 주식은 키 설정 시 토스 캔들을 조회합니다. 키가 없으면 yfinance를 사용합니다. 주식 4시간봉도 토스 수정주가 1분봉을 집계합니다. 코인·지수는 yfinance를 사용합니다. 토스 조회 실패 시 yfinance로 자동 전환하지 않습니다. 최초 분봉 이력 적재는 시간이 걸릴 수 있으며, 진행 중인 동일 조회는 병합됩니다. 실시간 연결 상태와 시장 시각을 표시하지만 체결가 숫자·가격선은 표시하지 않습니다. 틱 수신과 캔들/지표의 원자적 동기화는 보장하지 않습니다.

서버 하나에서 WebSocket 연결을 공유합니다. 429 응답의 재시도 시각과 백오프를 따릅니다. 키·권한·허용 IP를 변경한 뒤에는 서버를 다시 실행합니다. 자동갱신을 끄거나 탭을 숨기면 화면 조회를 멈춥니다. 서버 감시는 별도 시작/일시정지 설정을 사용합니다.

공식 명세: [REST](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json), [WebSocket](https://openapi.tossinvest.com/openapi-docs/latest/asyncapi.json), [연동 안내](https://openapi.tossinvest.com/openapi-docs/overview.md).
