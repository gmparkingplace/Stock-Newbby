"""신호 해설: 원장 이벤트를 근거로 한국어 해설 생성 (추천 아님 명시).

백엔드: template(결정적, 전건 기본) | ollama(로컬 LLM) | muse(`muse exec` 구독 모델, 최신 신호용).
실행: .venv/bin/python scripts/commentary.py <exp> [--backend template|ollama|muse] [--recent N]
muse 백엔드는 샌드박스 인증 정책상 실패할 수 있으며, 그 경우 터미널 대화형으로 대체한다.
입력: results/<exp>/ledger[_<stem>].jsonl
출력: results/<exp>/commentaries[_<stem>].jsonl
검증: scripts/verify_commentary.py (수치 인용·면책·금지문구)
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISCLAIMER = "본 해설은 매수·매도 추천이 아닙니다 (개인 연구용 기록 해설)."
BANNED = ["매수하세요", "매도하세요", "사세요", "파세요", "반드시 오릅니다",
          "반드시 내립니다", "확실한 수익", "무조건"]
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


IND_LABEL = {"don_hi20": "돈치안상단20", "don_lo10": "돈치안하단10",
             "sma20": "SMA20", "sma60": "SMA60", "atr14": "ATR14",
             "rsi14": "RSI14", "vol_ratio": "거래량비율"}


def fmt_ind(ind: dict) -> str:
    parts = []
    for k, v in ind.items():
        lab = IND_LABEL.get(k, k)
        if isinstance(v, (int, float)):
            s = f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"
        else:
            s = str(v)
        parts.append(f"{lab} {s}")
    return "·".join(parts)


def template(ev: dict) -> str:
    side = "매수" if ev["side"] == "entry" else "청산"
    m, s = ev["market_ref"], ev["sector_ref"]
    pos = ("신규 진입" if ev["position_before"] == 0 and ev["side"] == "entry"
           else "보유 중 중복매수(거래 제외)" if ev.get("repeated_signal") and ev["side"] == "entry"
           else "미보유 청산(거래 제외)" if ev.get("repeated_signal")
           else "전량 청산" if ev["side"] == "exit" else "상태 유지")
    return (f"{ev['signal_bar_close'][:10]} {ev['symbol']} 전략{ev['strategy']} {side} 신호. "
            f"근거: {ev['reason_desc']} (지표 {fmt_ind(ev['indicator_now'])}, 체결 참고가 {ev['signal_price']}). "
            f"당시 시장 {m['id']} 추세 {m['trend']}·베타 {m['beta_60']}, 섹터 {s['id']} 추세 {s['trend']}·"
            f"베타 {s['beta_60']}, 종목-시장 상대 {ev['rel_pp']['stock_mkt']}%p. "
            f"포지션: {pos}. {DISCLAIMER}")


def ollama_prompt(ev: dict) -> str:
    return f"""주식 연구 기록 해설자. 아래 JSON의 값만 사용해 3문장 한국어 해설을 작성하라.
모르는 값은 만들지 말고, 미래를 예측하지 말라. 마지막 문장은 반드시 '{DISCLAIMER}'로 끝내라.
'추천', '매수하세요', '매도하세요' 같은 권유 표현을 쓰지 말라.
{json.dumps(ev, ensure_ascii=False)}"""


def ollama_call(prompt: str, model: str) -> str:
    req = urllib.request.Request(
        OLLAMA_URL, data=json.dumps({"model": model, "prompt": prompt,
                                     "stream": False}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["response"].strip()


def muse_call(prompt: str, model: str = "") -> str:
    """구독 모델 파이프라인 백엔드: `muse exec` 헤드리스 호출.
    샌드박스에서 인증 파일을 못 읽으면 실패하고 대화형 대체를 안내한다."""
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        pf = f.name
    cmd = ["muse", "exec", "--prompt-file", pf, "--reasoning-effort", "minimal",
           "--max-model-steps", "2"]
    if model:
        cmd += ["--model", model]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    finally:
        Path(pf).unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"muse exec 실패: {(r.stderr or r.stdout)[-300:]} "
                           "(대화형 대체: 터미널에서 직접 요청)")
    return r.stdout.strip()


def ledger_files(exp: str) -> list[Path]:
    d = ROOT / "results" / exp
    files = sorted(d.glob("ledger_*.jsonl"))
    return files or ([d / "ledger.jsonl"] if (d / "ledger.jsonl").exists() else [])


def main() -> None:
    exp = sys.argv[1] if len(sys.argv) > 1 else "exp005"
    backend = "template"
    model, recent = "", 0
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--backend":
            backend, i = args[i + 1], i + 1
        elif args[i] == "--model":
            model, i = args[i + 1], i + 1
        elif args[i] == "--recent":
            recent, i = int(args[i + 1]), i + 1
        i += 1
    for lf in ledger_files(exp):
        events = [json.loads(ln) for ln in lf.read_text().splitlines() if ln.strip()]
        if recent:
            events = events[-recent:]
        out = lf.parent / lf.name.replace("ledger", "commentaries")
        rows = []
        for ev in events:
            if backend == "template":
                text = template(ev)
            elif backend == "ollama":
                text = ollama_call(ollama_prompt(ev), model)
            elif backend == "muse":
                text = muse_call(ollama_prompt(ev), model)
            else:
                raise SystemExit(f"unknown backend: {backend}")
            rows.append({"event_id": ev["event_id"], "backend": backend, "model": model,
                         "commentary": text,
                         "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
        print(f"{lf.name} -> {out.name}: {len(rows)}건 ({backend})")


if __name__ == "__main__":
    main()
