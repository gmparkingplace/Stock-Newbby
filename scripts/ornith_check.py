"""Ornith 사용성 대조: 동일 이벤트에 Ornith 해설 생성 → muse 해설과 비교 판정.

서버: Ornith_로컬서버_실행.command (mlx_lm.server, http://127.0.0.1:8080/v1)
실행: .venv/bin/python scripts/ornith_check.py [--n 3]
출력: /tmp/ornith_check.json (판정 근거, 저장소 오염 없음)
판정: grounding 통과율 100% + 방향 일치 100% + 금지문구 0 → 사용 가능
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from commentary import BANNED, DISCLAIMER  # noqa: E402

URL = "http://127.0.0.1:8080/v1/chat/completions"
MODEL_ID = "osxest/Huihui-Ornith-1.5-9B-abliterated-mlx-6Bit"
FILES = ["results/exp005/commentaries_muse_005930KS.jsonl",
         "results/exp005/commentaries_muse_000660KS.jsonl",
         "results/exp002/commentaries_muse.jsonl"]


def prompt_for(ev: dict) -> str:
    side = "매수" if ev["side"] == "entry" else "청산"
    return (f"아래 주식 신호 JSON을 3문장 한국어로 해설하라. 날짜·가격·지표 수치는 JSON 값만 그대로 인용하고, "
            f"미래 예측과 매수·매도 권유는 금지. 마지막 문장은 반드시 '{DISCLAIMER}'로 끝낼 것. "
            f"신호 방향({side})을 첫 문장에 명시할 것.\n{json.dumps(ev, ensure_ascii=False)}")


def chat(prompt: str) -> str:
    req = urllib.request.Request(
        URL, data=json.dumps({"model": MODEL_ID, "messages": [{"role": "user", "content": prompt}],
                              "temperature": 0.2, "max_tokens": 500}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


def main() -> None:
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 3
    results = []
    for f in FILES:
        muse_rows = [json.loads(l) for l in (ROOT / f).read_text().splitlines()][-n:]
        lf = str(Path(f).parent / Path(f).name.replace("commentaries_muse", "ledger").replace("ledger_", "ledger"))
        if "exp002" in f:
            lf = "results/exp002/ledger.jsonl"
        else:
            stem = Path(f).name.replace("commentaries_muse_", "").replace(".jsonl", "")
            lf = f"results/exp005/ledger_{stem}.jsonl"
        evs = {json.loads(l)["event_id"]: json.loads(l) for l in (ROOT / lf).read_text().splitlines()}
        for m in muse_rows:
            ev = evs[m["event_id"]]
            try:
                text = chat(prompt_for(ev))
                err = ""
            except Exception as e:
                text, err = "", f"{type(e).__name__}: {str(e)[:120]}"
            want_side = "매수" if ev["side"] == "entry" else "청산"
            checks = {"date": ev["signal_bar_close"][:10] in text,
                      "price": str(ev["signal_price"]) in text,
                      "disclaimer": text.rstrip().endswith(DISCLAIMER),
                      "side": want_side in text,
                      "no_banned": not any(b in text for b in BANNED)}
            results.append({"event_id": ev["event_id"], "muse": m["commentary"],
                            "ornith": text, "error": err, "checks": checks})
            print(("PASS" if all(checks.values()) else "FAIL"), ev["event_id"],
                  "" if all(checks.values()) else str(checks))
    ok = [r for r in results if all(r["checks"].values())]
    verdict = ("사용 가능" if ok and len(ok) == len(results)
               else f"보류 ({len(ok)}/{len(results)} 통과)")
    Path("/tmp/ornith_check.json").write_text(
        json.dumps({"verdict": verdict, "results": results}, ensure_ascii=False, indent=1))
    print(f"{len(ok)}/{len(results)} 통과 → {verdict}")


if __name__ == "__main__":
    main()
