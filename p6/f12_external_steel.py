# F12 — 외부 연간 이전 검증. 다른 공장(UCI Steel Industry Energy Consumption 2018, CC BY 4.0)의 1년 15분 전력에
# F11이 주 데이터 8월에서 고른 설정(예측기·cap)을 **재조정 없이** 그대로 적용한다. 이 데이터에서는 아무것도 고르지 않는다.
# 래칫(요금적용전력 = 당월과 직전 12개월 중 12·1·2·7·8·9월 최대 중 가장 큰 값)을 1년치로 계산할 수 있는 유일한 길이다.
# 입력: data/ext/Steel_industry_data.csv(출처·변환 규칙은 data/ext/SOURCE.md) · build/table_f11_select.csv(선택 행)
# 출력: build/table_f12.csv(s × 정책 연간 요약) · build/table_f12_month.csv(월 × s × 정책)
# 실행: python -X utf8 f12_external_steel.py
import hashlib
import numpy as np, pandas as pd
from common import B
from closed_loop_core import S_ROWS, DANGA, calendar, oracle
import f11_dayahead as F11

RAW = B / "data/ext/Steel_industry_data.csv"
OUT, OUT_M, OUT_D = B / "build/table_f12.csv", B / "build/table_f12_month.csv", B / "build/table_f12_diag.csv"
RATCHET_MONTHS = {12, 1, 2, 7, 8, 9}                   # 요금적용전력 산정 대상 월(가정 — 4장 4-6, 약관 원문 미확인)
POL = ["P0 현행", "P1 달력 규칙", "P5 전일 운전표", "P3 오라클(실측, LP)"]


def load_steel():
    d = pd.read_csv(RAW)
    day = pd.to_datetime(d["date"].str[:10], format="%d/%m/%Y")
    start = day + pd.to_timedelta(np.where(d["NSM"] == 0, 23 * 3600 + 45 * 60, d["NSM"] - 900), unit="s")
    s = pd.Series(d["Usage_kWh"].values * 4.0, index=pd.DatetimeIndex(start), name="kw").sort_index()
    return s, d


def selected():
    S = pd.read_csv(F11.SEL_CSV, encoding="utf-8-sig")
    r = S[S["선택"]].iloc[0]
    return r["예측기"], float(r["cap"]), hashlib.sha256(f"{r['예측기']}|{float(r['cap'])}".encode()).hexdigest()


def run(kw, pred, cap):
    D = F11.day_matrix(kw)
    stat = {"naive_med4": "med", "naive_q75": "q75"}[pred]    # RF 예측기는 이 데이터에 특징이 없어 이전할 수 없다(선택이 naive라 해당 없음)
    days = [pd.DataFrame({"y": D[d]}, index=pd.date_range(d, periods=96, freq="15min")) for d in sorted(D)]
    rows, loads = [], {}
    for s in S_ROWS:
        fc = {d: F11.naive(D, d, stat) for d in D}
        o5, F5, nop = F11.run_p5(days, fc, s, cap)
        out = {POL[0]: [g["y"].values * 1.0 for g in days], POL[1]: [calendar(g, s) for g in days], POL[2]: o5,
               POL[3]: [oracle(g, s) for g in days]}
        loads[s] = out
        for k, v in out.items():
            M = pd.Series(np.array(v).max(1), index=[g.index[0] for g in days])
            for m, x in M.groupby(M.index.month).max().items():
                rows.append(dict(s=s, 정책=k, 월=m, 월최대kW=x))
        print(f"  s={s} 완료 (무계획일 {nop})", flush=True)
    return days, pd.DataFrame(rows), loads


def ratchet(mm):
    """월 최대 Series(1~12) → 요금적용전력. 2017년 이력이 없으므로 '직전 12개월의 해당 월'을 2018년 같은 달로 근사한다
    (같은 정책을 해마다 운영하는 정상상태). 결과: 월 m의 요금적용전력 = max(당월, 12·1·2·7·8·9월 최대)."""
    base = max(mm[m] for m in RATCHET_MONTHS)
    return pd.Series({m: max(mm[m], base) for m in mm.index})


def summarize(Mo):
    rows = []
    for s in S_ROWS:
        p0 = Mo[(Mo.s == s) & (Mo.정책 == POL[0])].set_index("월")["월최대kW"]
        r0 = ratchet(p0)
        for k in POL:
            mm = Mo[(Mo.s == s) & (Mo.정책 == k)].set_index("월")["월최대kW"]
            r = ratchet(mm)
            rows.append(dict(s=s, 정책=k, 연최대kW=round(mm.max(), 2), P0대비_연최대kW=round(mm.max() - p0.max(), 2),
                             월최대_평균kW=round(mm.mean(), 2), P0대비_월최대평균kW=round(mm.mean() - p0.mean(), 2),
                             P5가P0보다나쁜달=int((mm > p0 + 1e-6).sum()), 요금적용전력_연합kW=round(r.sum(), 1),
                             **{f"래칫_기본요금_{n}_연간원": round(r.sum() * v) for n, v in DANGA.items()},
                             **{f"래칫_변화_{n}_연간원": round((r.sum() - r0.sum()) * v) for n, v in DANGA.items()},
                             래칫없이_변화_선택II_연간원=round((mm.sum() - p0.sum()) * DANGA["선택II"])))
    T = pd.DataFrame(rows)
    T["가정"] = ("외부 공장(UCI Steel Industry Energy Consumption 2018, CC BY 4.0) · s = 이동 가능 부하 비중(가정, 이 공장도 모름 — 연속 공정 비중이 커 10%도 과대일 수 있다) · "
                "예측기·cap은 주 데이터 8월 선택 그대로(재조정 0, cap 20kW는 이 공장 규모에 맞추지 않았다) · 달력 규칙도 원래 08~09·16~17시 그대로 · "
                "요금적용전력 = max(당월, 12·1·2·7·8·9월 최대), 직전 12개월을 2018년 같은 달로 근사(정상상태) · 단가는 4장 4-6 산업용(을) 고압A, 이 공장의 요금제 아님")
    return T


def diagnose(kw, days, cap, s=0.10):
    """이전 실패의 원인 분해(선택에 쓰지 않는다): 예측을 실측으로 바꾸면(P5*) / cap을 공장 규모에 비례해 키우면 / cap을 없애면."""
    D = F11.day_matrix(kw)
    fc, yfc = {d: F11.naive(D, d, "med") for d in D}, {d: D[d] for d in D}
    big = cap * kw.max() / 204.0                               # 주 데이터 테스트 월 최대 204kW 대비 이 공장 연 최대의 비율
    rows = []
    for name, f, c in [("P5 전일 운전표(선택 설정)", fc, cap), ("P5* 진단 — 예측 대신 실측, 같은 cap", yfc, cap),
                       (f"진단 — cap을 규모 비례 {big:.0f}kW로", fc, big), ("진단 — cap 없음", fc, np.inf)]:
        o, _, _ = F11.run_p5(days, f, s, c)
        rows.append(dict(s=s, 구성=name, 연최대kW=round(float(np.array(o).max()), 2)))
    e = [np.abs(fc[d] - D[d]).mean() for d in D if fc[d] is not None]
    rows.append(dict(s=np.nan, 구성=f"전일 예측 MAE(kW) / 평균 부하 {kw.mean():.1f}kW", 연최대kW=round(float(np.mean(e)), 2)))
    return pd.DataFrame(rows)


def check(kw, raw, days, Mo, T, loads, sha):
    # 1. 변환 — 365일 × 96구간, 중복·결측 없음, 연 최대 = 원 데이터 최대 × 4
    assert len(kw) == 35040 and kw.index.is_unique and len(days) == 365, "15분 격자 변환 오류"
    assert raw.groupby(raw["date"].str[:10])["NSM"].apply(lambda x: sorted(x) == list(range(0, 86400, 900))).all(), "날짜별 NSM 96개가 아니다"
    p0max = T[(T.정책 == POL[0])]["연최대kW"].iloc[0]
    assert abs(p0max - raw["Usage_kWh"].max() * 4) < 1e-6, "P0 연 최대 ≠ 원 데이터 최대 × 4"
    # 2. 일 합 보존 · 3. P3 ≤ P1·P5
    y = np.array([g["y"].values for g in days])
    for s, out in loads.items():
        for k, v in out.items():
            assert np.allclose(np.array(v).sum(1), y.sum(1), atol=1e-6), f"s={s} {k}: 일 합 불보존"
        assert np.array(out[POL[3]]).max(1).max() <= min(np.array(out[POL[1]]).max(), np.array(out[POL[2]]).max()) + 1e-6, f"s={s}: 오라클 하한 위반"
    # 4. 재조정 0 — 쓴 설정의 해시가 table_f11_select.csv 선택 행의 해시와 같다
    assert selected()[2] == sha, "설정이 F11 선택 행과 다르다(재조정)"
    # 5. 래칫 — 래칫 요금적용전력 ≥ 당월 최대, 12·1·2·7·8·9월 최대가 하한
    for s in S_ROWS:
        mm = Mo[(Mo.s == s) & (Mo.정책 == POL[0])].set_index("월")["월최대kW"]
        r = ratchet(mm)
        assert (r >= mm - 1e-9).all() and (r >= max(mm[m] for m in RATCHET_MONTHS) - 1e-9).all(), "래칫 계산 오류"
    print("self-check OK (변환 · 일 합 · 오라클 하한 · 재조정 0 · 래칫)")


def main():
    pd.set_option("display.width", 250)
    pred, cap, sha = selected()
    kw, raw = load_steel()
    print(f"[F12] 외부 철강 2018 · {len(kw)}슬롯 · 연 최대 {kw.max():.2f}kW · 설정 {pred}·cap {cap:.0f}(F11 8월 선택, 재조정 0)", flush=True)
    days, Mo, loads = run(kw, pred, cap)
    T = summarize(Mo)
    check(kw, raw, days, Mo, T, loads, sha)
    Mo["월최대kW"] = Mo["월최대kW"].round(2)
    T.to_csv(OUT, index=False, encoding="utf-8-sig")
    Mo.to_csv(OUT_M, index=False, encoding="utf-8-sig")
    Dg = diagnose(kw, days, cap)
    Dg.to_csv(OUT_D, index=False, encoding="utf-8-sig")
    print("\n[원인 분해 · 선택에 쓰지 않음]"); print(Dg.to_string(index=False))
    print(T.drop(columns="가정").to_string(index=False))
    w = Mo[Mo.s == 0.1].pivot(index="월", columns="정책", values="월최대kW")[POL]
    print("\n[월 최대 · s=10%]"); print(w.to_string())
    print(f"→ {OUT.relative_to(B)} · {OUT_M.relative_to(B)} · {OUT_D.relative_to(B)}")


if __name__ == "__main__":
    main()
