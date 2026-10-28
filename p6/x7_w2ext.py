# X7 — 진단 28개 공장-월에 최종 운영 모델 W2를 '현행'으로 다시 세운다(외부이전 재조사 Phase 2 선행). 비블라인드 진단.
# W2 = 직전 4주(A) ∪ 유사일 kNN(B) 시나리오의 평균 피크 LP (f24_scenario_schedule.py SPEC["W2"]).
# kNN 특징 7개 중 생산계획 5개·기온은 외부 공장에 없다 → **W2 코드 그대로, 없는 특징은 NaN**(F21.knn이 nansum으로 건너뛴다)
#   = "W2-외부판"(요일유형 일치 + 직전 같은 요일 피크 시각 거리). A사에서는 실제 W2와 W2-외부판(특징 가림)을 둘 다 계산해 특징 손실을 잰다.
# 같이 계산: R2-외부판(A∪B 최악 시나리오 min-max) — 개선안 후보. 적중률(통일 정의: 복제 제외·평일·D−1 18시·±1시간).
# 실행: python -X utf8 x7_w2ext.py [--quick] [--mutate N]  → build/table_x_w2ext.csv · build/x7_run.log
#   재삽입: 1 누설(시나리오에 당일) · 2 휴일 누락 · 3 단위(철강 kWh) · 4 시간대(+9h) · 5 보류 공장 접근
import sys, datetime
import numpy as np, pandas as pd
from common import B, load
import f11_dayahead as F11
import f19_kr_blind as F19
import f21_decision_forecaster as F21
import k7_tariff_cost as K7
import f24_scenario_schedule as F24
import x5_decomp as X5
from f11b_twolayer import dedup_days

OUT, LOG = B / "build/table_x_w2ext.csv", B / "build/x7_run.log"
S = X5.S
MUT = 0


def feats_power_only(D):
    """F21.day_feats와 같은 7칸 — 생산 5칸·기온은 NaN, 7번째 = 직전 같은 요일(없으면 2주 전) 최대 슬롯."""
    out = {}
    for d in D:
        prev = D.get(d - pd.Timedelta(days=7))
        prev = prev if prev is not None else D.get(d - pd.Timedelta(days=14))
        out[d] = np.array([np.nan] * 6 + [float(np.argmax(prev)) if prev is not None else np.nan])
    return out


def hit_wd(days, D, holi):
    """통일 적중률: 평일(공휴일 제외)·D−1 18:00에 아는 같은 요일 직전 4주 중앙값의 최대 슬롯이 실측 최대 슬롯 ±4슬롯 안."""
    h = []
    for g in days:
        d = g.index[0].normalize()
        if d.weekday() >= 5 or d.date() in holi:
            continue
        f = F11.naive(D, d, "med")
        if f is not None:
            h.append(abs(int(np.argmax(f)) - int(np.argmax(g["y"].values))) <= 4)
    return (float(np.mean(h)) if h else np.nan), len(h)


def run(fac, y, m, days, D, cap, holi, Fx_full=None):
    K7.HOLI = holi
    if fac.startswith("Forge"):
        assert F21.dtype(pd.Timestamp("2019-08-15")) == "일휴", "2019 공휴일 미적용(요일유형·요금 시간대가 틀린다)"
    start = pd.Timestamp(y, m, 1)
    fc0 = {g.index[0].normalize(): F11.naive(D, g.index[0].normalize(), "med") for g in days}
    Fp = feats_power_only(D); sdp = F21.scale(Fp, start)
    mx = lambda o: float(np.array(o).max())
    r = dict(공장=fac, 연=y, 월=m, 현행월최대=max(g["y"].max() for g in days), 평가일=len(days))
    r["W2외부판"] = mx(F24.run_scen(days, D, Fp, sdp, "AB", "mean", S, cap, fc0)[0])
    r["R2외부판"] = mx(F24.run_scen(days, D, Fp, sdp, "AB", "max", S, cap, fc0)[0])
    if Fx_full is not None:
        sdf = F21.scale(Fx_full, start)
        r["W2"] = mx(F24.run_scen(days, D, Fx_full, sdf, "AB", "mean", S, cap, fc0)[0])
    r["적중률_평일_통일"], r["적중평일수"] = hit_wd(days, D, holi)
    return r


def main():
    global MUT
    a = sys.argv[1:]
    if "--mutate" in a:
        MUT = int(a[a.index("--mutate") + 1]); X5.MUT = MUT if MUT in (3, 4, 5) else 0; F24.MUT = 1 if MUT == 1 else 0
    quick = bool(MUT) or "--quick" in a
    t0 = datetime.datetime.now(); hol21 = K7.HOLI
    rows = []
    ks = X5.steel(); assert abs(ks.max() - 628.72) < 0.01, f"철강 연최대 {ks.max():.2f} ≠ 628.72kW — 단위 오류"
    for f in (["Forge_1"] if quick else F19.FORGES):
        q = X5.forge(f); D = F19.complete_days(q)
        A1 = pd.read_csv(B / "data/ext/korea_factory/x2_an1_monthly.csv", encoding="utf-8-sig")   # 원자료에서 잰 월 최대 시각(시간대 기준점)
        for _, a1 in A1[A1.factory == f].iterrows():
            mm = q[q.index.month == a1.month]
            assert mm.idxmax().strftime("%m-%d %H:%M") == a1["at"], f"{f} {a1.month}월 최대 시각 {mm.idxmax():%m-%d %H:%M} ≠ 원자료 {a1['at']} (시간대·정렬 오류)"
        for m in ([8] if quick else F19.MONTHS):
            days = [pd.DataFrame(dict(y=v), index=pd.date_range(d, periods=96, freq="15min")) for d, v in D.items() if d.month == m]
            days, _ = dedup_days(days, D)
            rows.append(run(f, 2019, m, days, D, F19.cap_for(q, m), F19.HOL19 if MUT != 2 else hol21))
            print(f"  {f} {m}월 {datetime.datetime.now():%H:%M:%S}", flush=True)
    kw = X5.main_kw(); DA = F11.day_matrix(kw)
    q0 = load(); q0 = q0[q0.index < "2021-09-01"]
    FxA = F21.day_feats(q0, DA)
    for m in ([7] if quick else F24.MONTHS):
        days = X5.month_days(kw, 2021, m, True, DA)
        rows.append(run("A사", 2021, m, days, DA, F24.CAP, hol21, FxA))
        print(f"  A사 {m}월 {datetime.datetime.now():%H:%M:%S}", flush=True)
    if not quick:
        DS = F11.day_matrix(ks)
        for m in range(2, 13):
            days = X5.month_days(ks, 2018, m)
            prev = ks[ks.index.month == m - 1]
            rows.append(run("UCI 철강", 2018, m, days, DS, 20.0 / 204.0 * float(prev.max()), X5.HOL18))
            print(f"  철강 {m}월 {datetime.datetime.now():%H:%M:%S}", flush=True)
    K7.HOLI = hol21
    T = pd.DataFrame(rows)
    # self-check: A사 실제 W2 = table_f24_rolling(복제 제외, s_kr) · 단조 C0 대조는 X5와 같은 경로라 x5 표와 현행월최대 일치
    R = pd.read_csv(B / "build/table_f24_rolling.csv", encoding="utf-8-sig"); R = R[(R.복제처리 == "제외") & np.isclose(R.s, S)]
    X = pd.read_csv(B / "build/table_x_decomp.csv", encoding="utf-8-sig")
    for _, r in T.iterrows():
        if r.공장 == "A사":
            w = float(R[(R.월 == r.월) & (R.후보 == "W2")].월최대.iloc[0])
            assert abs(r.W2 - w) < 0.01, f"A사 {r.월}월 W2 {r.W2:.2f} ≠ f24 {w}"
        x = X[(X.공장 == r.공장) & (X.월 == r.월)]
        assert len(x) == 1 and abs(x.현행월최대.iloc[0] - r.현행월최대) < 0.01, f"{r.공장} {r.월}월 현행 {r.현행월최대} ≠ x5"
    print("self-check OK (A사 W2 = f24 · 현행 월 최대 = x5 · 철강 단위 · 보류 공장 미접근 · 테스트 구간 미적재)")
    for c in ["W2외부판", "R2외부판", "W2"]:
        if c in T:
            T[c + "_pct"] = ((T[c] / T.현행월최대 - 1) * 100).round(3); T[c + "_현행초과"] = T[c] > T.현행월최대 + 0.005
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(T.round(3).to_string(index=False))
    if quick:
        print(f"[{'재삽입 ' + str(MUT) if MUT else '축약판 무결함'}] self-check 통과" + (" — 검사가 이 결함을 못 본다" if MUT else "")); return
    T.to_csv(OUT, index=False, encoding="utf-8-sig")
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{t0.isoformat(timespec='seconds')} → {datetime.datetime.now().isoformat(timespec='seconds')} · 비블라인드 진단 · {len(T)}공장-월\n")
    print(f"→ {OUT.relative_to(B)}")


if __name__ == "__main__":
    main()
