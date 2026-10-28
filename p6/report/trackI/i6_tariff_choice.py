# I6 (d) — A사 데이터로 요금제 선택 비교 1회 시험 계산(재집계). 식은 I2 §4(봉인 d8948add…) 그대로, 단가는 2023-11-09판(F7과 같은 판).
# 출력: build/table_i6_tariff_choice_A.csv · trackI/_i6_run.log
import sys, json
from pathlib import Path
import numpy as np, pandas as pd

B = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(B)); sys.path.insert(0, str(Path(__file__).parent))
import precheck as P
import i3_bill_metrics as I3

OUT, LOG = B / "build/table_i6_tariff_choice_A.csv", B / "report/trackI/_i6_run.log"
SEA = {"여름": "여름(6~8월)", "봄가을": "봄가을(3~5·9~10월)", "겨울": "겨울(11~2월)"}
BN = ["경부하", "중간부하", "최대부하"]
lines = []


def log(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)


def season_of(m):
    return "여름" if m in (6, 7, 8) else ("겨울" if m in (11, 12, 1, 2) else "봄가을")


def tariffs():
    g = pd.read_csv(B / "data/ext/kepco_tariff_industrial_20241024.csv", encoding="utf-8-sig")
    g = g[(g.적용일자 == "2023-11-09")]
    e = pd.read_csv(B / "data/ext/kepco_tariff_industrial_eul_HVA_20231109.csv", encoding="utf-8-sig")
    T = {}
    for df in (g, e):
        for plan, G in df.groupby("요금제"):
            T[plan] = dict(base=int(G.기본요금_원per_kW.iloc[0]),
                           e={s: {b: float(G[G.계절 == SEA[s]][b].iloc[0]) for b in BN} for s in SEA})
    assert set(T) == {"산업용(갑)Ⅱ 고압A 선택Ⅰ", "산업용(갑)Ⅱ 고압A 선택Ⅱ", "산업용(을) 고압A 선택Ⅰ", "산업용(을) 고압A 선택Ⅱ", "산업용(을) 고압A 선택Ⅲ"}, T.keys()
    return T


def band_kwh(day, season, hol):
    """별표3(I3와 같은 규칙, 계절만 인자로) — kWh 집계용 라벨 0/1/2."""
    h = np.arange(96) // 4
    peak = np.isin(h, [9, 10, 11, 16, 17, 18]) if season == "겨울" else np.isin(h, [11, 13, 14, 15, 16, 17])
    b = np.where((h >= 22) | (h < 8), 0, np.where(peak, 2, 1))
    if day.weekday() == 6 or day.date() in hol:
        return np.zeros(96, int)
    return np.where((b == 2) & (day.weekday() == 5), 1, b)


def selfcheck_f7(T):
    """F7 저장값 재현: 같은 입력(_b4b_plan_test.csv '시간창 07~20시' − 실측)을 이 스크립트의 시간대·단가 경로에 넣는다."""
    pl = pd.read_csv(B / "report/trackB/_b4b_plan_test.csv", encoding="utf-8-sig"); pl["ts"] = pd.to_datetime(pl.ts)
    js = json.load(open(B / "report/trackB/_b4b_tariff.json", encoding="utf-8"))["시간창 07~20시"]
    vr = pd.read_csv(B / "build/value_tariff_range.csv", encoding="utf-8-sig")
    row = vr[vr.항목.str.startswith("월 요금 절감 — 전력량요금분")].iloc[0]
    diff = (pl["시간창 07~20시"] - pl["실측"]).values / 4
    out = {}
    for plan, col in [("산업용(을) 고압A 선택Ⅰ", "을_고압A_선택I_7220"), ("산업용(갑)Ⅱ 고압A 선택Ⅰ", "갑II_고압A_선택I_6490")]:
        e = 0.0
        for d, G in pl.assign(v=diff).groupby(pl.ts.dt.normalize()):
            assert len(G) == 96
            lab = band_kwh(d, "봄가을", I3.KR)
            e += sum(G.v.values[lab == k].sum() * T[plan]["e"]["봄가을"][BN[k]] for k in range(3))
        out[plan] = round(e * 30 / 14)
        assert out[plan] == int(row[col]), f"F7 재현 실패 {plan}: {out[plan]} vs {row[col]}"
    base = round((222 - js["요금적용전력kW"]) * T["산업용(을) 고압A 선택Ⅰ"]["base"])
    assert -base == int(vr[vr.항목 == "월 요금 절감 — 기본요금분"].iloc[0]["을_고압A_선택I_7220"])
    log(f"self-check F7 재현: 전력량 봄가을 을Ⅰ {out['산업용(을) 고압A 선택Ⅰ']:,} · 갑ⅡⅠ {out['산업용(갑)Ⅱ 고압A 선택Ⅰ']:,} · 기본 −{base:,} = value_tariff_range.csv 저장값")


def main():
    assert I3.sha(I3.RULES) == I3.RULES_SHA
    T = tariffs()
    selfcheck_f7(T)
    S = I3.load_all(); _, q, hol, _ = S["A사"]
    D = P._dedup(P._days(q))
    M = {}
    for d, v in D.items():
        m = d.month; s = season_of(m)
        r = M.setdefault(m, dict(유효일=0, kwh=np.zeros(3), dm=-np.inf, 달력일=pd.Timestamp(d).days_in_month))
        lab = band_kwh(d, s, hol); r["유효일"] += 1
        for k in range(3):
            r["kwh"][k] += v[lab == k].sum() * 0.25
        if lab.any():
            r["dm"] = max(r["dm"], float(v[lab > 0].max()))
    raw = float(q[q.index.normalize().isin(list(D))].sum()) * 0.25
    assert abs(sum(r["kwh"].sum() for r in M.values()) - raw) < 1e-6 * raw, "월 kWh 합 ≠ 원본"
    V = {m: r for m, r in sorted(M.items()) if r["유효일"] >= I3.MIN_VALID_DAYS}
    I3m = pd.read_csv(B / "build/table_i3_bill_metrics.csv", encoding="utf-8-sig"); I3m = I3m[(I3m.공장 == "A사") & I3m.유효달]
    assert sorted(V) == sorted(I3m.월.tolist()) and np.allclose([V[m]["dm"] for m in sorted(V)], I3m.sort_values("월").D_m), "I3 A사 월 지표와 불일치"
    log(f"A사 유효 달 {sorted(V)} (유효일 {[V[m]['유효일'] for m in sorted(V)]}) · 월 kWh 합 = 원본 {raw:,.1f}kWh · I3 월 지표와 일치")
    Pm, run = {}, -np.inf
    for m in sorted(V):
        if m in I3.RATCHET:
            run = max(run, V[m]["dm"])
        Pm[m] = max(run, V[m]["dm"])
        h = V[m]["kwh"].sum() / Pm[m]
        log(f"  {m}월 D_m {V[m]['dm']:.1f} · 요금적용전력 모사 {Pm[m]:.1f} · kWh {V[m]['kwh'].sum():,.0f} (경 {V[m]['kwh'][0]:,.0f}/중 {V[m]['kwh'][1]:,.0f}/최 {V[m]['kwh'][2]:,.0f}) · 사용시간 {h:.0f}h(유효일) / {h * V[m]['달력일'] / V[m]['유효일']:.0f}h(달력 환산)")
    rows = []
    for plan, t in T.items():
        for mode in ["유효일 그대로(I2 식)", "달력일 환산(사후 민감도)"]:
            base = en = 0.0
            for m, r in V.items():
                k = 1.0 if mode.startswith("유효") else r["달력일"] / r["유효일"]
                base += Pm[m] * t["base"]
                en += sum(r["kwh"][j] * k * t["e"][season_of(m)][BN[j]] for j in range(3))
            rows.append(dict(요금제=plan, 계산=mode, 기본단가=t["base"], 기본요금=round(base), 전력량요금=round(en), 합계=round(base + en),
                             연환산_12개월=round((base + en) * 12 / len(V)), 대상달=",".join(map(str, sorted(V))), 단가판="2023-11-09"))
    R = pd.DataFrame(rows)
    for (mode, grp), G in R.groupby([R.계산, R.요금제.str.slice(0, 8)]):
        R.loc[G.index, "같은종별_선택Ⅰ대비"] = G.합계 - G[G.요금제.str.endswith("선택Ⅰ")].합계.iloc[0]
        R.loc[G.index, "같은종별_최저"] = G.합계 == G.합계.min()
    R.to_csv(OUT, index=False, encoding="utf-8-sig")
    log(R.to_string(index=False))
    log(f"행 수: {OUT.name} {len(R)}")
    LOG.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
