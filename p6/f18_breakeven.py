# F18 — 손익분기 s*.
# 테스트(9/1~14) 밖에서만: 테스트 밖 달 2·4·5·7월 + 선택 8월, s 격자 × {P0, P1 고정 시간대 규칙, v2-B(±4h·TOU)}로 효과가 성립하는 최소 s를 찾는다.
#   s*₁ = 4·5·7·8월 모두 v2 ≤ P1 − 1kW 인 최소 s
#   s*₂ = 7월 v2 월 최대 < 218kW(8월 현행 최대)인 최소 s — 그 아래로 내려가야 요금적용전력이 움직인다
#   s*₃ = max(7·8월 v2) ≤ 0.95 × max(7·8월 현행) 인 최소 s
# 각 s*에 대해 "그보다 큰 격자 s에서도 계속 성립하는가"(단조성)를 함께 적는다.
# 변형 강건성(L2-d): s ∈ {s_kr, 0.337}에서 v1·A·B·C 네 변형. 3·6월은 복제일을 빼면 평일 0일이라 "복제 포함 민감도" 행으로만.
# v2 설정(예측기 naive_med4 · cap 20 · ±4h · 2단 TOU)은 f14에서 그대로 가져오고 여기서 아무것도 고르지 않는다.
# 실행: python -X utf8 f18_breakeven.py [--mutate N] → build/table_f18_breakeven.csv · table_f18_sstar.csv
import sys, pathlib
import numpy as np, pandas as pd
from common import B, load
from closed_loop_core import by_day, calendar
import f14_schedule_v2 as F14
from f11b_twolayer import dedup_days

OUT, OUT_S = B / "build/table_f18_breakeven.csv", B / "build/table_f18_sstar.csv"
GRID = [0.05, 0.075, 0.10, 0.125, 0.15, 0.175, 0.20, 0.225, 0.25, 0.30, 0.337]
MONTHS = [2, 4, 5, 7, 8]
SENS = [3, 6]
MUT = 0
QUICK = False


def s_kr():
    T = pd.read_csv(B / "build/table_f17_kr_flex.csv", encoding="utf-8-sig")
    return round(float(T["s_kr(두 공장 중 작은 쪽)"].iloc[0]), 4)


def kw_upto_aug():
    kw = load()["kw"]
    return kw if MUT == 1 else kw[:"2021-08-31"]                  # 재삽입 1: 테스트 구간까지 메모리에 둔다


def month_days(kw, m, dedup=True):
    days = by_day(F14.month_frame(kw, m))
    fc, D = F14.forecasts(kw, days)
    if dedup:
        days, drop = dedup_days(days, D)
    else:
        drop = 0
    return days, fc, drop


def run_cell(days, fc, s, cap, pols):
    y0 = [g["y"].values * 1.0 for g in days]
    out = {"P0 현행": y0, "P1 달력 규칙": [calendar(g, s) for g in days]}
    for name in pols:
        L, tou, carry = (8, False, False) if name == F14.POL_V1 else F14.VARIANTS[name.replace("P5v2 ", "")]
        o, *_ = F14.run_variant(days, fc, s, cap, L, tou, carry)
        out[name] = o
    if MUT == 2:
        out["P5v2 B ±4h·TOU"] = [x * 0.95 for x in out["P5v2 B ±4h·TOU"]]   # 재삽입 2: 에너지 비보존
    return out, y0


def main():
    global MUT, QUICK
    QUICK = "--quick" in sys.argv
    if "--mutate" in sys.argv:
        MUT = int(sys.argv[sys.argv.index("--mutate") + 1])
    pred, cap = F14.f11_choice(); sk = s_kr()
    sel = pd.read_csv(B / "build/table_f14_select.csv", encoding="utf-8-sig").query("선택").iloc[0]["정책"]
    assert sel == "P5v2 B ±4h·TOU", sel
    kw = kw_upto_aug()
    assert kw.index.max() < pd.Timestamp("2021-09-01") or MUT == 1
    base = [0.10, 0.337] if MUT else GRID                          # 재삽입 시험은 축약판(7월 · s 3개) — 무결함 축약판(--mutate 0 --quick)이 먼저 통과해야 한다
    grid = sorted(set(base + [sk])) if MUT != 3 else base          # 재삽입 3: s_kr를 격자에서 뺀다
    months, sens = ([7], []) if (MUT or QUICK) else (MONTHS, SENS)
    rows = []
    allv = ["P5v2 A ±2h·TOU", "P5v2 B ±4h·TOU", "P5v2 C ±4h·TOU·익일이월", F14.POL_V1]
    for m in months + sens:
        dd = (m not in SENS) and MUT != 4                         # 재삽입 4: 복제일을 빼지 않는다
        days, fc, drop = month_days(kw, m, dedup=dd)
        if not days:
            print(f"  {m}월: 평가일 0"); continue
        for s in grid:
            pols = allv if (abs(s - sk) < 1e-9 or abs(s - 0.337) < 1e-9) else ["P5v2 B ±4h·TOU"]
            out, y0 = run_cell(days, fc, s, cap, pols)
            tot = sum(g["y"].sum() for g in days)
            for k, v in out.items():
                assert abs(sum(x.sum() for x in v) - tot) < 1e-6, f"{m}월 s={s} {k}: 에너지 불보존"
                rows.append(dict(월=m, 구분="롤링" if m != 8 else "선택 월", 복제처리="제외" if dd else "포함(민감도)", s=s, 정책=k,
                                 월최대=round(float(np.array(v).max()), 2), 청구기준월최대=round(F14.bill_max(days, v), 2),
                                 전력량요금Δ_선택Ⅰ=round(F14.cost(v, days, "선택Ⅰ") - F14.cost(y0, days, "선택Ⅰ")),
                                 평가일=len(days), 복제제외일=drop))
        print(f"  {m}월 완료(평가 {len(days)}일, 복제 제외 {drop}일)", flush=True)
    R = pd.DataFrame(rows)
    S = sstar(R, grid) if not (MUT or QUICK) else pd.DataFrame()
    check(R, S, sk)
    if MUT or QUICK:
        print(f"[{'재삽입 ' + str(MUT) if MUT else '축약판 무결함'}] self-check 통과" + (" — 검사가 이 결함을 못 본다" if MUT else "")); return
    if False:
        print(f"[재삽입 {MUT}] self-check 통과 — 검사가 이 결함을 못 본다"); return
    R.to_csv(OUT, index=False, encoding="utf-8-sig"); S.to_csv(OUT_S, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    pv = R[(R.복제처리 == "제외") & R.정책.isin(["P0 현행", "P1 달력 규칙", "P5v2 B ±4h·TOU"])].pivot_table(index="s", columns=["월", "정책"], values="월최대")
    print(pv.round(1).to_string()); print(); print(S.to_string(index=False))
    print(f"→ {OUT.relative_to(B)} · {OUT_S.relative_to(B)}")


def sstar(R, grid):
    V = "P5v2 B ±4h·TOU"
    E = R[R.복제처리 == "제외"]
    w = lambda m, k, s: float(E[(E.월 == m) & (E.정책 == k) & np.isclose(E.s, s)]["월최대"].iloc[0])
    c1 = {s: all(w(m, V, s) <= w(m, "P1 달력 규칙", s) - 1 for m in (4, 5, 7, 8)) for s in grid}
    c1b = {s: all(w(m, V, s) <= w(m, "P1 달력 규칙", s) - 1 for m in MONTHS) for s in grid}
    c2 = {s: w(7, V, s) < 218.0 for s in grid}
    p78 = max(w(7, "P0 현행", grid[0]), w(8, "P0 현행", grid[0]))
    c3 = {s: max(w(7, V, s), w(8, V, s)) <= 0.95 * p78 for s in grid}
    rows = []
    for name, c, txt in [("s*1", c1, "4·5·7·8월 모두 v2 ≤ 고정 시간대 규칙 − 1kW"), ("s*1b", c1b, "2·4·5·7·8월 모두 (2월 포함)"),
                         ("s*2", c2, "7월 v2 < 218kW"), ("s*3", c3, f"max(7·8월 v2) ≤ 0.95 × {p78:.0f}kW")]:
        ok = [s for s in grid if c[s]]
        smin = min(ok) if ok else np.nan
        mono = bool(ok) and all(c[s] for s in grid if s >= smin)
        rows.append(dict(기준=name, 정의=txt, s_star=smin, 그보다_큰_격자에서_계속_성립=mono, 성립한_격자=" ".join(f"{s:g}" for s in ok)))
    return pd.DataFrame(rows)


def check(R, S, sk):
    # 1. 9월 슬롯을 하나도 읽지 않았다 — 평가 달에 9가 없고, 메모리의 kw가 8/31까지
    assert 9 not in set(R.월), "9월(테스트)이 평가에 들어갔다"
    assert kw_upto_aug().index.max() < pd.Timestamp("2021-09-01"), "테스트 구간이 메모리에 있다"
    # 2. f14 테스트 밖 달과 같은 정의 — s ∈ {0.10, 0.255(격자에 없음 → 0.25 아님, 건너뜀), 0.337} × 4·5·7·8월 v2·P0·P1이 table_f14_rolling과 같다
    F = pd.read_csv(B / "build/table_f14_rolling.csv", encoding="utf-8-sig")
    for s in (0.10, 0.337):
        for m in sorted(set(R.월) & {4, 5, 7, 8}):
            for k in ("P0 현행", "P1 달력 규칙", "P5v2 B ±4h·TOU", F14.POL_V1):
                a = R[(R.월 == m) & np.isclose(R.s, s) & (R.정책 == k) & (R.복제처리 == "제외")]["월최대"]
                b = F[(F.월 == m) & np.isclose(F.s, s) & (F.정책 == k)]["월최대"]
                if len(a) and len(b):
                    assert abs(a.iloc[0] - b.iloc[0]) < 0.01, f"{m}월 s={s} {k}: {a.iloc[0]} ≠ f14 롤링 {b.iloc[0]}"
    # 3. s_kr가 격자에 있다
    assert (np.isclose(R.s, sk)).any(), "s_kr가 격자에 없다"
    # 4. 변형 강건성 행이 s_kr·0.337에서 네 변형 모두 있다
    for s in (sk, 0.337):
        n = R[np.isclose(R.s, s) & (R.월 == 7) & (R.복제처리 == "제외")].정책.nunique()
        assert n == 6, f"s={s}: 정책 {n}개(P0·P1·변형 4 = 6이어야)"
    print("self-check OK (1 테스트 미사용 · 2 f14 롤링과 일치 · 3 s_kr 포함 · 4 변형 강건성 행)")


if __name__ == "__main__":
    main()
