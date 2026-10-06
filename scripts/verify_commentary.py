"""해설 검증: 원장 대조(날짜·가격 인용), 면책 고지, 권유 금지문구 확인.

실행: .venv/bin/python scripts/verify_commentary.py <exp>  (종료코드 0 = 통과)
출력: 결과만 표준출력
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from commentary import BANNED, DISCLAIMER  # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)


def main() -> None:
    exp = sys.argv[1] if len(sys.argv) > 1 else "exp005"
    d = ROOT / "results" / exp
    ledgers = sorted(d.glob("ledger_*.jsonl")) or [d / "ledger.jsonl"]
    total, bad = 0, []
    for lf in ledgers:
        stem = lf.name.replace("ledger", "commentaries")
        cf = d / stem
        check(f"{lf.name} 해설 존재", cf.exists(), stem)
        if not cf.exists():
            continue
        evs = {json.loads(ln)["event_id"]: json.loads(ln)
               for ln in lf.read_text().splitlines() if ln.strip()}
        coms = [json.loads(ln) for ln in cf.read_text().splitlines() if ln.strip()]
        check(f"{stem} 전건 커버", {c["event_id"] for c in coms} == set(evs),
              f"{len(coms)} vs {len(evs)}")
        for c in coms:
            total += 1
            t, ev = c["commentary"], evs[c["event_id"]]
            ok = (ev["signal_bar_close"][:10] in t
                  and str(ev["signal_price"]) in t
                  and t.rstrip().endswith(DISCLAIMER)
                  and t.count("추천") == 1
                  and not any(b in t for b in BANNED)
                  and 50 <= len(t) <= 2000)
            if not ok:
                bad.append(c["event_id"])
    check("전 해설 근거·면책·길이", not bad, f"{total}건 중 {len(bad)}건 불량")
    print("RESULT:", "FAIL" if fails else "ALL PASS", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
