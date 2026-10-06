"""P3 차트 표시: 평가구간 종가·SMA·매수/청산 표식 + 봉 단위 스테퍼, 단일 HTML.

실행: .venv/bin/python scripts/chart_p3.py [exp] [지표파일] [출력파일]
  기본값: exp002 indicators_satl.csv chart_p3.html (P5 한국: exp003 indicators_kr.csv chart_kr.html)
입력: 지표 CSV + trades_{A,B,C}.csv (해당 실험 폴더)
출력: 단일 HTML (외부 의존성 없음, 인라인 SVG+JS)
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / (sys.argv[1] if len(sys.argv) > 1 else "exp002")
IND_FILE = sys.argv[2] if len(sys.argv) > 2 else "indicators_satl.csv"
OUT_FILE = sys.argv[3] if len(sys.argv) > 3 else "chart_p3.html"
TITLE_SYM = sys.argv[4] if len(sys.argv) > 4 else "SATL"
TRADE_SUFFIX = sys.argv[5] if len(sys.argv) > 5 else ""  # exp004: _005930KS 등
STRATS = ("A", "B", "C")  # main()에서 지표 CSV의 sig* 열로 확장
RULES = {
    "A": "이동평균 교차: SMA20이 SMA60을 상향 교차하면 매수, 하향 교차하면 청산 (FAST=20, SLOW=60).",
    "B": "RSI: RSI14가 30을 상향 교차하면 매수, 70을 하향 교차하면 청산 (PERIOD=14).",
    "C": "가격 돌파: 종가가 직전 20봉 최고가 초과하면 매수, 직전 10봉 최저가 하회하면 청산.",
    "F": "게이트 돌파: C 돌파 + 추세순행(SMA20>SMA60, 종가>SMA60) + 거래량 1.0 초과 + ATR 강도 0.1 초과 시 매수.",
}
W, H, PL, PR, PT, PB = 960, 340, 56, 12, 12, 26


def svg_paths(xs: list[float], ys: list[float | None]) -> str:
    d, started = "", False
    for x, y in zip(xs, ys):
        if y is None:
            started = False
            continue
        d += ("M" if not started else "L") + f"{x:.1f},{y:.1f}"
        started = True
    return d


def main() -> None:
    global STRATS
    ind = pd.read_csv(RES / IND_FILE, parse_dates=["date"])
    extra = sorted({c[3:] for c in ind.columns if c.startswith("sig") and len(c) == 4}
                   - set(STRATS))
    STRATS = STRATS + tuple(extra)
    ev = ind[ind["in_eval"]].reset_index(drop=True)
    dates = ev["date"].dt.date.astype(str).tolist()
    close = ev["close"].tolist()
    lo, hi = min(close), max(close)
    pad = (hi - lo) * 0.12 or 1.0
    lo, hi = lo - pad, hi + pad
    n = len(ev)
    xs = [PL + i * (W - PL - PR) / max(n - 1, 1) for i in range(n)]
    y = lambda v: PT + (hi - v) / (hi - lo) * (H - PT - PB)  # noqa: E731
    yc = [y(v) for v in close]

    def col(name: str) -> list[float | None]:
        return [None if pd.isna(v) else y(float(v)) for v in ev[name].tolist()]

    ys20, ys60 = col("sma20"), col("sma60")
    marks = {}
    for s in STRATS:
        m = []
        for i, r in ev.iterrows():
            sig = r[f"sig{s}"]
            if sig in ("entry", "exit"):
                m.append({"i": int(i), "side": sig, "date": dates[int(i)],
                          "close": close[int(i)]})
        marks[s] = m
    trades = {}
    for s in STRATS:
        t = pd.read_csv(RES / f"trades_{s}{TRADE_SUFFIX}.csv", dtype=str).fillna("")
        trades[s] = t.to_dict(orient="records")
    data = {"dates": dates, "close": [round(v, 4) for v in close],
            "sma20": ev["sma20"].round(4).where(ev["sma20"].notna(), None).tolist(),
            "sma60": ev["sma60"].round(4).where(ev["sma60"].notna(), None).tolist(),
            "rsi14": ev["rsi14"].round(2).where(ev["rsi14"].notna(), None).tolist(),
            "marks": marks, "n": n}

    grid = "".join(
        f'<line x1="{PL}" y1="{yy:.0f}" x2="{W-PR}" y2="{yy:.0f}" stroke="#eee"/>'
        f'<text x="{PL-6}" y="{yy+4:.0f}" font-size="11" text-anchor="end" fill="#666">{vv:.1f}</text>'
        for yy, vv in ((y(v), v) for v in
                       (lo + pad * 0, (lo + hi) / 2, hi - pad * 0)))
    price_d = svg_paths(xs, yc)
    sma20_d = svg_paths(xs, ys20)
    sma60_d = svg_paths(xs, ys60)
    ticks = "".join(
        f'<text x="{xs[i]:.0f}" y="{H-8}" font-size="11" text-anchor="middle" fill="#666">{dates[i][:7]}</text>'
        for i in range(0, n, max(n // 6, 1)))

    trades_rows = {}
    for s in STRATS:
        rows = "".join(
            "<tr>" + "".join(f"<td>{t.get(k,'')}</td>" for k in
                             ("entry_signal_date", "entry_exec_date", "entry_price",
                              "exit_signal_date", "exit_exec_date", "exit_price",
                              "pnl", "ret_pct", "status")) + "</tr>"
            for t in trades[s]) or '<tr><td colspan="9">거래 없음</td></tr>'
        trades_rows[s] = rows
    rule_ps = "".join(f"<p><b>전략 {s}</b> — {RULES[s]}</p>" for s in STRATS)
    tabs = "".join(f'<button onclick="showStrat(\'{s}\')" id="tab{s}">전략 {s}</button>'
                   for s in STRATS)
    tables = "".join(
        f'<div id="tbl{s}"><h3>전략 {s} 거래 목록</h3>'
        f'<table border="1" cellspacing="0" cellpadding="4"><tr>'
        f'<th>매수신호봉</th><th>매수체결일</th><th>매수가</th>'
        f'<th>청산신호봉</th><th>청산체결일</th><th>청산가</th>'
        f'<th>손익</th><th>수익률%</th><th>상태</th></tr>{trades_rows[s]}</table></div>'
        for s in STRATS)
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>P3 {TITLE_SYM} 신호 차트</title></head><body style="font-family:sans-serif;max-width:1000px;margin:auto">
<h2>P3 {TITLE_SYM} 신호 차트 — 평가 {dates[0]} ~ {dates[-1]} (t봉 신호 / t+1봉 시가 체결)</h2>
<div>{tabs}</div>
<svg id="chart" width="{W}" height="{H}" style="border:1px solid #ccc">
{grid}{ticks}
<path d="{price_d}" fill="none" stroke="#111" stroke-width="1.5"/>
<path d="{sma20_d}" fill="none" stroke="#06c" stroke-width="1"/>
<path d="{sma60_d}" fill="none" stroke="#c60" stroke-width="1"/>
<g id="marks"></g><line id="cursor" y1="{PT}" y2="{H-PB}" stroke="#999" stroke-dasharray="3,3"/>
</svg>
<div><input type="range" id="slider" min="0" max="{n-1}" value="{n-1}" style="width:90%">
<span id="info"></span></div>
<div id="legend">검정=종가, 파랑=SMA20, 주황=SMA60, ▲매수 / ▼청산</div>
{tables}
<h3>신호 규칙</h3>{rule_ps}
<p>일봉·현물 매수/전량청산·전액/전량·비용 0·소수점 주식 허용(연구용). 미확정봉 없음(확정봉만). 기말 미청산은 자동 청산하지 않고 평가로 표시.</p>
<script>
const D = {json.dumps(data, ensure_ascii=False)};
const NS = {{"X": {xs}, "YC": {[round(v, 1) for v in yc]},
  "H": {H}, "PB": {PB}}};
let strat = "A";
function showStrat(s) {{ strat = s; draw(); }}
function draw() {{
  const k = +document.getElementById("slider").value;
  const g = document.getElementById("marks"); g.innerHTML = "";
  for (const m of D.marks[strat]) {{
    if (m.i > k) continue;
    const cx = NS.X[m.i], cy = NS.YC[m.i];
    const up = m.side === "entry";
    const yy = up ? cy + 16 : cy - 16;
    g.innerHTML += `<text x="${{cx}}" y="${{yy}}" font-size="15" text-anchor="middle" `
      + `fill="${{up ? "red" : "blue"}}">${{up ? "▲매수" : "▼청산"}}</text>`;
  }}
  for (const s of Object.keys(D.marks)) {{
    document.getElementById("tbl"+s).style.display = s === strat ? "" : "none";
    document.getElementById("tab"+s).style.fontWeight = s === strat ? "bold" : "";
  }}
  const cur = document.getElementById("cursor");
  const cx0 = NS.X[k] !== undefined ? NS.X[k] : 0;
  cur.setAttribute("x1", cx0); cur.setAttribute("x2", cx0);
  document.getElementById("info").textContent =
    `${{D.dates[k]}} 종가 ${{D.close[k]}} SMA20 ${{D.sma20[k] ?? "-"}} SMA60 ${{D.sma60[k] ?? "-"}} RSI ${{D.rsi14[k] ?? "-"}}`;
}}
document.getElementById("slider").addEventListener("input", draw);
draw();
</script></body></html>"""
    (RES / OUT_FILE).write_text(html)
    print(f"chart bars={n} marks=" + str({s: len(marks[s]) for s in STRATS}))


if __name__ == "__main__":
    main()
