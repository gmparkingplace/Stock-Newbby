"""종목 분류 리프: 이름·코인·별칭·유니버스·시장 매핑 (serve_dashboard에서 분리, 동작 동일)."""
NAMES = {"005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "069500.KS": "KODEX 200",
         "091160.KS": "KODEX 반도체", "^KS11": "KOSPI", "^KQ11": "KOSDAQ",
         "QQQ": "나스닥100", "SPY": "S&P500", "XLK": "미국 기술섹터", "IWM": "러셀2000",
         "ITA": "미국 방산", "AAPL": "애플", "NVDA": "엔비디아", "SATL": "새틀러직",
         "TSLA": "테슬라", "MSFT": "마이크로소프트", "005380.KS": "현대차",
         "000270.KS": "기아", "035420.KS": "NAVER", "005490.KS": "POSCO홀딩스",
         "BTC-USD": "비트코인", "ETH-USD": "이더리움", "BNB-USD": "비앤비",
         "XRP-USD": "리플", "SOL-USD": "솔라나", "TRX-USD": "트론",
         "DOGE-USD": "도지코인", "ADA-USD": "에이다", "XLM-USD": "스텔라루멘",
         "LINK-USD": "체인링크", "TON-USD": "톤코인", "BCH-USD": "비트코인캐시",
         "LTC-USD": "라이트코인", "XMR-USD": "모네로", "ZEC-USD": "지캐시",
         "HBAR-USD": "헤데라", "AVAX-USD": "아발란체", "SHIB-USD": "시바이누",
         "DOT-USD": "폴카닷", "NEAR-USD": "니어프로토콜", "ARB-USD": "아비트럼",
         "ATOM-USD": "코스모스", "ETC-USD": "이더리움클래식", "FIL-USD": "파일코인",
         "OP-USD": "옵티미즘", "INJ-USD": "인젝티브", "LEO-USD": "레오",
         "ALGO-USD": "알고랜드", "AAVE-USD": "에이브", "VET-USD": "비체인"}
COINS = ["BTC-USD", "ETH-USD", "BNB-USD", "XRP-USD", "SOL-USD", "TRX-USD",
         "DOGE-USD", "ADA-USD", "XLM-USD", "LINK-USD", "TON-USD", "BCH-USD",
         "LTC-USD", "XMR-USD", "ZEC-USD", "HBAR-USD", "AVAX-USD", "SHIB-USD",
         "DOT-USD", "NEAR-USD", "ARB-USD", "ATOM-USD", "ETC-USD", "FIL-USD",
         "OP-USD", "INJ-USD", "LEO-USD", "ALGO-USD", "AAVE-USD", "VET-USD"]
COIN_ALIAS = {"BTC": "BTC-USD", "ETH": "ETH-USD", "BNB": "BNB-USD",
              "XRP": "XRP-USD", "SOL": "SOL-USD", "TRX": "TRX-USD",
              "DOGE": "DOGE-USD", "ADA": "ADA-USD", "XLM": "XLM-USD",
              "LINK": "LINK-USD", "TON": "TON-USD", "BCH": "BCH-USD",
              "LTC": "LTC-USD", "XMR": "XMR-USD", "ZEC": "ZEC-USD",
              "HBAR": "HBAR-USD", "AVAX": "AVAX-USD", "SHIB": "SHIB-USD",
              "DOT": "DOT-USD", "NEAR": "NEAR-USD", "ARB": "ARB-USD",
              "ATOM": "ATOM-USD", "ETC": "ETC-USD", "FIL": "FIL-USD",
              "OP": "OP-USD", "INJ": "INJ-USD", "LEO": "LEO-USD",
              "ALGO": "ALGO-USD", "AAVE": "AAVE-USD", "VET": "VET-USD"}
UNIVERSE = ["005930.KS", "000660.KS", "005380.KS", "000270.KS", "035420.KS", "005490.KS",
            "069500.KS", "091160.KS", "^KS11", "^KQ11", "AAPL", "NVDA", "MSFT", "TSLA",
            "SATL", "SPY", "QQQ", "XLK", "IWM", "ITA"]


def is_coin(s: str) -> bool:
    return s in COINS or s.endswith("-USD")


def is_kr(s: str) -> bool:
    return s.endswith((".KS", ".KQ")) or s in ("^KS11", "^KQ11")


def norm_code(code: str) -> str:
    code = code.strip().upper()
    code = next((symbol for symbol in COINS if NAMES.get(symbol, "").upper() == code), code)
    if code.isdigit() and len(code) == 6:
        code += ".KS"
    return COIN_ALIAS.get(code, code)


def market_of(code: str) -> tuple[str, str, str]:
    if is_kr(code):
        return "Asia/Seoul", "069500.KS", "091160.KS"
    if is_coin(code):
        return "UTC", "BTC-USD", "ETH-USD"
    return "America/New_York", "SPY", "XLK"
