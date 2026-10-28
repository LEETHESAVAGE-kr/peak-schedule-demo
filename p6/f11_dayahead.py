# F11 — 전일 운전표. D−1 18:00에 아는 것만으로 내일 하루의 예측 f를 만들고,
# 그 f 위에서 하루 LP로 "이동 가능 부하 s·f를 ±2h 안에서 어디로 옮길지"를 정한 뒤, 같은 이동 비율을 실측 y에 적용해 채점한다.
# +60분 폐루프(f9 P2)가 0kW였던 원인이 지평(쓸 수 있는 창 −45~+60분)이라는 2장 격차 분해의 "다음 수"다.
# 후보 12개(예측기 4 × cap 3)는 **8월에서만** 고르고 테스트는 정확히 1회 읽는다 — --test는 build/f11_test_read.log가 있으면 거부한다.
# 실행: python -X utf8 f11_dayahead.py --select   (8월만 · table_f11_select.csv · table_f11_cap_ablation.csv · 통과 여부 판정)
#       python -X utf8 f11_dayahead.py --test     (기준 통과 시 1회 · table_f11.csv · f11_plan_test.csv)
# 선행: f9_closed_loop.py(table_f9.csv·table_f9_select.csv). f5·f8·f9·f10과 그 산출물은 건드리지 않는다 — 코어는 import만.
import sys, hashlib, datetime, pathlib
import pandas as pd, numpy as np, pulp
from sklearn.ensemble import RandomForestRegressor
from common import B, CAL, W, WIND, PROD, TR, VA, load
from closed_loop_core import (L, S_ROWS, S_SEL, qtl, fit_predictions, by_day, calendar, oracle, run,
                              POL_P0, POL_P1, POL_P2, POL_P3, R6_NOTE)

PREDS = ["naive_med4", "naive_q75", "rf_point", "rf_up90"]   # §3-1 — 후보는 이 4 × CAPS 3 = 12개로 고정
CAPS = [5, 10, 20]
S_GATE = [0.05, 0.10]                                         # §3-2 — 순위 평균에 쓰는 s
ALPHA_UP = 0.90                                               # rf_up90의 conformal 수준
GATE_MARGIN = 3.0                                             # §3-3 — P1 달력 − 3kW 이하
SEL_CSV = B / "build/table_f11_select.csv"
ABL_CSV = B / "build/table_f11_cap_ablation.csv"
TEST_LOG = B / "build/f11_test_read.log"
POL_P5 = "P5 전일 운전표"
POL_P5S = "P5* 진단(f=실측, 같은 cap)"                        # 예측 오차 몫을 가른다: P5*−P3 = cap·LP 몫, P5−P5* = 예측 오차 몫
RF_X = CAL + ["lag1w", "lag2w", "roll7d"] + [c for c in W if c != WIND] + PROD
CUT = pd.Timedelta(hours=6)                                   # D−1 18:00 = D 00:00 − 6h. 이 시각 이후의 kw는 f(d)에 들어가면 안 된다


def f9_rule():
    S = pd.read_csv(B / "build/table_f9_select.csv", encoding="utf-8-sig")
    r = S[S["선택"]].iloc[0]
    return r["규칙"], r["추정량"], r["거름"]


# ===== 1. 예측기 — 입력은 kw 시계열(시각 인덱스) 하나. 인과성 시험이 이 시계열을 흔들어 본다 =====
def day_matrix(kw):
    """완전한 날(96슬롯)만 {날짜: 96벡터}. 7/13·7/15(손상 제거일)처럼 빠진 날은 키가 없다."""
    return {d: g.values for d, g in kw.groupby(kw.index.normalize()) if len(g) == 96}


def naive(D, d, stat):
    """같은 요일 직전 4주(d−7·−14·−21·−28일) 슬롯별 중앙값/75% 분위. 결측일은 건너뛰고 남은 날로(3·2·1일), 0일이면 None."""
    hs = [D[d - pd.Timedelta(days=7 * k)] for k in range(1, 5) if d - pd.Timedelta(days=7 * k) in D]
    if not hs:
        return None
    return np.median(hs, 0) if stat == "med" else np.quantile(hs, 0.75, axis=0)


def rf_features(q0, kw, days):
    """날짜 d의 96슬롯 특징. lag1w·lag2w = 같은 시각 7·14일 전(시각 기준 — 행 shift는 손상 제거일에서 어긋난다),
    roll7d = [D−1 18:00 − 7일, D−1 18:00) 구간 kw 평균(하루 내내 같은 값). 기상은 실측을 '전일 예보'로 쓴다(가정).
    생산량·공장인원은 계획값(1장 감사 4항). lag_h·lag_h1h·lag1d·roll1d는 D−1 18:00 이후라 쓰지 않는다."""
    rows = []
    for d in days:
        idx = pd.date_range(d, periods=96, freq="15min")
        X = q0.loc[idx, CAL + [c for c in W if c != WIND] + PROD].copy()
        X["lag1w"] = kw.reindex(idx - pd.Timedelta(days=7)).values
        X["lag2w"] = kw.reindex(idx - pd.Timedelta(days=14)).values
        X["lag1w"] = X["lag1w"].fillna(X["lag2w"]); X["lag2w"] = X["lag2w"].fillna(X["lag1w"])
        t = d - CUT
        X["roll7d"] = kw[(kw.index >= t - pd.Timedelta(days=7)) & (kw.index < t)].mean()
        rows.append(X[RF_X])
    return pd.concat(rows)


class RFDayAhead:
    """학습 ≤7/31. 상단은 f9와 같은 방식: σ̂ 모형(학습 앞뒤 반분) + 정규화 잔차 분위. 8월 상단은 반월 2겹 교차 보정,
    테스트 상단은 8월 전체로 보정. 결정성을 위해 전부 n_jobs=1(n_jobs=-1의 5e-14 잡음이 LP에서 증폭될 수 있다)."""

    def __init__(self, q0, kw):
        self.q0 = q0
        days = [d for d in day_matrix(kw[TR]) if d >= pd.Timestamp("2021-01-15")]
        Xt = rf_features(q0, kw, days)
        ok = Xt[["lag1w", "lag2w"]].notna().all(1)
        Xt, yt = Xt[ok], kw.reindex(Xt.index)[ok]
        self.m = RandomForestRegressor(max_depth=20, random_state=42, n_jobs=1).fit(Xt, yt)
        half = len(Xt) // 2
        ma = RandomForestRegressor(max_depth=20, random_state=42, n_jobs=1).fit(Xt[:half], yt[:half])
        self.ms = RandomForestRegressor(max_depth=10, random_state=42, n_jobs=1).fit(Xt[half:], np.abs(yt.values[half:] - ma.predict(Xt[half:])))
        self.qa = self.qb = self.q_all = None

    def point_sigma(self, kw, d):
        X = rf_features(self.q0, kw, [d])
        if X[["lag1w", "lag2w"]].isna().any().any():
            return None, None
        return self.m.predict(X), np.maximum(self.ms.predict(X), 1e-3)

    def calibrate(self, kw, aug_days):
        """8월 정규화 잔차 z. qa = 8/1~15에 쓸 분위(8/16~31의 z로), qb = 그 반대, q_all = 테스트용(8월 전체)."""
        z, half = [], []
        for d in aug_days:
            p, sg = self.point_sigma(kw, d)
            if p is None:
                continue
            z.append((kw.reindex(pd.date_range(d, periods=96, freq="15min")).values - p) / sg); half.append(np.full(96, d.day > 15))
        z, half = np.concatenate(z), np.concatenate(half)
        self.qa, self.qb, self.q_all = qtl(z[half], ALPHA_UP), qtl(z[~half], ALPHA_UP), qtl(z, ALPHA_UP)

    def up(self, kw, d, mode):
        p, sg = self.point_sigma(kw, d)
        if p is None:
            return None
        q = self.q_all if mode == "test" else (self.qa if d.day <= 15 else self.qb)
        return p + q * sg


def forecast(name, kw, D, rf, d, mode):
    if name == "naive_med4":
        return naive(D, d, "med")
    if name == "naive_q75":
        return naive(D, d, "q75")
    if name == "rf_point":
        return rf.point_sigma(kw, d)[0]
    return rf.up(kw, d, mode)


# ===== 2. 하루 계획 LP — closed_loop_core.oracle()의 일반화(입력 f, 받는 쪽 cap) =====
def plan(f, s, cap):
    """이동 비율 F[t,w](96×96, 행 합 1). fl[t,w] ≥ 0(|t−w| ≤ L), Σ_w fl[t,w] = s·f[t], (1−s)·f[w] + Σ_t fl[t,w] ≤ Pk,
    Σ_{t≠w} fl[t,w] ≤ cap(받는 슬롯 증가량 — **예측 f 기준**이다. 실현 y 기준 증가량은 s·y/s·f 비율만큼 달라질 수 있다).
    목적 min Pk. min-max LP는 최적해가 여럿이라(피크와 무관한 슬롯의 흐름이 임의) CBC가 아무 꼭짓점이나 돌려준다 —
    2단계로 Pk ≤ Pk*을 묶고 이동량 Σ_{t≠w} fl을 최소화해 '필요한 만큼만 옮기는' 해로 고정한다(목적식의 동률 깨기).
    f[t]=0(또는 s=0)인 슬롯은 F[t,t]=1 — 스파이크에서 이 처리를 빠뜨려 부하가 사라졌다."""
    F = np.eye(96)
    if s == 0:
        return F
    rng = lambda t: range(max(0, t - L), min(95, t + L) + 1)
    m = pulp.LpProblem("dayahead", pulp.LpMinimize)
    Pk = pulp.LpVariable("Pk", 0)
    fl = {(t, w): pulp.LpVariable(f"f_{t}_{w}", 0) for t in range(96) for w in rng(t)}
    for t in range(96):
        m += pulp.lpSum(fl[t, w] for w in rng(t)) == s * f[t]
    for w in range(96):
        m += (1 - s) * f[w] + pulp.lpSum(fl[t, w] for t in rng(w)) <= Pk
        if np.isfinite(cap):
            m += pulp.lpSum(fl[t, w] for t in rng(w) if t != w) <= cap
    m += Pk
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    assert pulp.LpStatus[m.status] == "Optimal"
    pk = pulp.value(Pk)
    m += Pk <= pk + 1e-6 * max(1.0, pk)
    m.setObjective(pulp.lpSum(v for (t, w), v in fl.items() if t != w))
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    assert pulp.LpStatus[m.status] == "Optimal"
    for t in range(96):
        if s * f[t] > 1e-9:
            F[t, t] = 0.0
            for w in rng(t):
                F[t, w] = max(pulp.value(fl[t, w]), 0.0) / (s * f[t])
            F[t] /= F[t].sum()                                    # 수치 잡음 정리(행 합 = 1)
    return F


def realize(y, s, F):
    """out[w] = (1−s)·y[w] + Σ_t s·y[t]·F[t,w]. 같은 날 안이고 일 합이 보존된다."""
    return (1 - s) * y + (s * y) @ F


def moved_kwh(y, s, F):
    return float(((s * y)[:, None] * (F - np.diag(np.diag(F)))).sum() / 4)


# ===== 3. 정책 실행 =====
def run_p5(days, fc, s, cap):
    """fc: {날짜: f 또는 None}. f가 None이면 계획을 세우지 않고 현행대로(F = I). 반환: 실현 부하 리스트, F 리스트, 무계획 일수."""
    outs, Fs, nop = [], [], 0
    for g in days:
        d, y = g.index[0].normalize(), g["y"].values
        f = fc.get(d)
        if f is None:
            F = np.eye(96); nop += 1
        else:
            F = plan(np.asarray(f, float), s, cap)
        Fs.append(F); outs.append(realize(y, s, F))
    return outs, Fs, nop


def stats(days, outs):
    M = np.array(outs)
    wk = np.array([g.index[0].dayofweek < 5 for g in days])
    return M.max(), float(np.median(M.max(1)[wk]))


def build_forecasts(kw, rf, days, mode):
    D = day_matrix(kw)
    return {p: {g.index[0].normalize(): forecast(p, kw, D, rf, g.index[0].normalize(), mode) for g in days} for p in PREDS}


def fc_mae(fc, days):
    e = [np.abs(f - g["y"].values) for g in days if (f := fc.get(g.index[0].normalize())) is not None]
    return float(np.mean(e)) if e else np.nan


# ===== 4. 8월 선택 =====
def select(VAL, fcs):
    days = by_day(VAL)
    rule, est, guard = f9_rule()
    rows = []
    for s in S_GATE:
        _, out, _ = run(VAL, s, rule, est, guard)
        p0 = np.array(out[POL_P0]).max()
        for k in [POL_P0, POL_P1, POL_P2, POL_P3]:
            mx, wkmed = stats(days, out[k])
            rows.append(dict(s=s, 정책=k, 예측기="", cap=np.nan, 월최대=mx, P0대비kW=mx - p0, 평일일피크중앙=wkmed, 이동량kWh=np.nan,
                             무계획일=np.nan, 예측MAE=np.nan))
        yfc = {g.index[0].normalize(): g["y"].values for g in days}
        for cap in CAPS:
            o, Fs, _ = run_p5(days, yfc, s, cap)
            mx, wkmed = stats(days, o)
            rows.append(dict(s=s, 정책=POL_P5S, 예측기="실측", cap=cap, 월최대=mx, P0대비kW=mx - p0, 평일일피크중앙=wkmed,
                             이동량kWh=sum(moved_kwh(g["y"].values, s, F) for g, F in zip(days, Fs)), 무계획일=0, 예측MAE=0.0))
        for p in PREDS:
            for cap in CAPS:
                o, Fs, nop = run_p5(days, fcs[p], s, cap)
                mx, wkmed = stats(days, o)
                rows.append(dict(s=s, 정책=POL_P5, 예측기=p, cap=cap, 월최대=mx, P0대비kW=mx - p0, 평일일피크중앙=wkmed,
                                 이동량kWh=sum(moved_kwh(g["y"].values, s, F) for g, F in zip(days, Fs)), 무계획일=nop,
                                 예측MAE=fc_mae(fcs[p], days)))
        print(f"  s={s} 완료", flush=True)
    T = pd.DataFrame(rows)
    c = T.정책 == POL_P5
    T.loc[c, "순위"] = T[c].groupby("s")["월최대"].rank(method="average")
    agg = T[c].groupby(["예측기", "cap"]).agg(평균순위=("순위", "mean"), 평일피크=("평일일피크중앙", "mean")).reset_index()
    best = agg.sort_values(["평균순위", "평일피크", "cap"]).iloc[0]          # §3-2 동률: 평일 일 피크 중앙(두 s 평균) → cap 작은 쪽
    T = T.merge(agg[["예측기", "cap", "평균순위"]], on=["예측기", "cap"], how="left")
    T["선택"] = c.values & (T.예측기 == best["예측기"]).values & (T.cap == best["cap"]).values
    return T


def gate(T):
    """(통과 여부, 선택 행 s=10%, P1 s=10%) — 8월 표만으로."""
    r = T[T.선택 & (T.s == S_SEL)].iloc[0]
    p1 = T.loc[(T.정책 == POL_P1) & (T.s == S_SEL), "월최대"].iloc[0]
    return bool(r["월최대"] <= p1 - GATE_MARGIN + 1e-9), r, p1


def cap_ablation(VAL, fcs, T):
    """선택된 예측기에서 cap=∞ — 받는 쪽 cap이 conformal 상단과 같은 안전장치인지 8월에서 본다(테스트 아님)."""
    days = by_day(VAL)
    p = T[T.선택].iloc[0]["예측기"]
    rows = []
    for s in S_GATE:
        p0 = max(g["y"].max() for g in days)
        for cap in CAPS + [np.inf]:
            o, Fs, nop = run_p5(days, fcs[p], s, cap)
            mx, wkmed = stats(days, o)
            rows.append(dict(s=s, 예측기=p, cap=cap, 월최대=round(mx, 2), P0대비kW=round(mx - p0, 2), 평일일피크중앙=round(wkmed, 2),
                             이동량kWh=round(sum(moved_kwh(g["y"].values, s, F) for g, F in zip(days, Fs)), 1)))
    return pd.DataFrame(rows)


# ===== 5. 테스트 1회 =====
def refuse_test(sel_csv=SEL_CSV, log=TEST_LOG):
    if not pathlib.Path(sel_csv).exists():
        raise SystemExit(f"[거부] {sel_csv} 없음 — 먼저 --select")
    if pathlib.Path(log).exists():
        raise SystemExit(f"[거부] {log} 가 이미 있다 — 테스트는 1회만 읽는다. 코드 결함으로 재실행하려면 사람이 로그를 지우고 6장 6-5에 기록할 것")
    T = pd.read_csv(sel_csv, encoding="utf-8-sig")
    ok, r, _ = gate(T)
    if not ok:
        raise SystemExit("[거부] 8월 게이트 실패 — 테스트를 읽지 않는다(§3-3)")
    return r, hashlib.sha256(pathlib.Path(sel_csv).read_bytes()).hexdigest()


def evaluate(df, fc, cap, p3_ref=None):
    """테스트 표(s 3행 × 정책)와 운전표. P0·P1·P3는 여기서 다시 계산해 f9 값과 맞는지 본다(P2는 f9 값을 읽는다 — +60분 모형을 다시 돌리지 않는다)."""
    days = by_day(df)
    rows, plans = [], []
    for s in S_ROWS:
        y0 = [g["y"].values * 1.0 for g in days]
        p0 = np.array(y0).max()
        p1 = np.array([calendar(g, s) for g in days]).max()
        p3 = np.array([oracle(g, s) for g in days]).max()
        o5, F5, nop = run_p5(days, fc, s, cap)
        o5s, F5s, _ = run_p5(days, {g.index[0].normalize(): g["y"].values for g in days}, s, cap)
        for k, mx, mv in [(POL_P0, p0, 0.0), (POL_P1, p1, np.nan), (POL_P3, p3, np.nan),
                          (POL_P5, np.array(o5).max(), sum(moved_kwh(g["y"].values, s, F) for g, F in zip(days, F5))),
                          (POL_P5S, np.array(o5s).max(), sum(moved_kwh(g["y"].values, s, F) for g, F in zip(days, F5s)))]:
            rows.append(dict(s=s, 정책=k, 월최대kW=round(mx, 2), P0대비kW=round(mx - p0, 2),
                             예측의가치=round((p0 - mx) / (p0 - p3), 3) if k.startswith("P5") and p0 > p3 else np.nan,
                             이동량kWh=round(mv, 1) if mv == mv else np.nan, 생산손실kWh=0.0, 무계획일=nop if k == POL_P5 else 0))
        for g, F, o in zip(days, F5, o5):
            d = g.index[0].normalize()
            f = fc.get(d)
            fh = np.full(96, np.nan) if f is None else np.asarray(f, float)
            plans.append(pd.DataFrame({"s": s, "예측f": fh.round(2), "내보냄비율": (1 - np.diag(F)).round(4),
                                       "계획_받음kW": ((s * np.nan_to_num(fh)) @ (F - np.diag(np.diag(F)))).round(2),
                                       "계획_총부하kW": ((1 - s) * np.nan_to_num(fh) + (s * np.nan_to_num(fh)) @ F).round(2),
                                       "실측": g["y"].values, "실현": o.round(3)}, index=g.index))
    return pd.DataFrame(rows), pd.concat(plans)


# ===== 6. self-check — 결함을 되살리면 깨진다 =====
def check(VAL, kw, rf, fcs, T, aug_days):
    days = by_day(VAL)
    rng = np.random.default_rng(0)
    p = T[T.선택].iloc[0]["예측기"]; cap = float(T[T.선택].iloc[0]["cap"])
    # 1. s=0 → P5 = P0
    o, _, _ = run_p5(days, fcs[p], 0.0, cap)
    assert np.allclose(np.array(o), np.array([g["y"].values for g in days])), "s=0인데 P5 ≠ P0"
    # 2. 일 부하 합 보존 — 12후보 × 2 s 전부
    for pp in PREDS:
        for c in CAPS:
            for s in S_GATE:
                o, Fs, _ = run_p5(days[:5], fcs[pp], s, c)
                assert np.allclose([x.sum() for x in o], [g["y"].sum() for g in days[:5]], atol=1e-6), f"{pp} cap={c} s={s}: 일 합 불보존"
    # 3. f[t]=0 슬롯의 부하가 사라지지 않음 — 0을 섞은 f로
    g = days[3]
    f0 = g["y"].values.copy(); f0[rng.choice(96, 20, replace=False)] = 0.0
    F = plan(f0, 0.10, cap)
    assert np.allclose(F.sum(1), 1.0), "F 행 합 ≠ 1 — f[t]=0 슬롯 처리 누락"
    assert abs(realize(g["y"].values, 0.10, F).sum() - g["y"].sum()) < 1e-6, "f[t]=0 슬롯에서 부하가 사라졌다"
    # 4. 받는 슬롯 증가량 ≤ cap (예측 f 기준 — 실현 y 기준이 아니다)
    for c in CAPS:
        f = fcs[p][days[5].index[0].normalize()]
        F = plan(np.asarray(f, float), 0.10, c)
        inflow = (0.10 * np.asarray(f)) @ (F - np.diag(np.diag(F)))
        assert inflow.max() <= c + 1e-6, f"cap={c}: 받는 슬롯 증가량 {inflow.max():.3f} > cap"
    # 5. 인과성 — D−1 18:00 이후 kw를 흔들어도 f(d)가 불변. 예측기 4종 × 날짜 여러 개.
    #    (8월 rf_up90의 conformal 분위는 f9와 같은 반월 교차 보정이라 그 분위 자체는 같은 달 다른 반의 사후 잔차를 쓴다 —
    #     설계 문서가 'f9와 같은 방식'으로 정한 예외. 여기서는 분위를 고정하고 점 예측·σ̂의 인과성만 본다. 테스트 상단은 8월로만 보정해 인과적이다.)
    D = day_matrix(kw)
    for d in [days[i].index[0].normalize() for i in (0, 9, 20, 30)]:
        kw2 = kw.copy()
        late = kw2.index >= d - CUT
        kw2[late] = kw2[late].values[rng.permutation(late.sum())] * rng.uniform(0.3, 2.0, late.sum())
        D2 = day_matrix(kw2)
        for pp in PREDS:
            a, b = forecast(pp, kw, D, rf, d, "val"), forecast(pp, kw2, D2, rf, d, "val")
            assert (a is None and b is None) or np.allclose(a, b), f"{pp} {d.date()}: f(d)가 D−1 18:00 이후 kw에 의존한다"
        kw3 = kw.copy(); kw3[kw3.index >= d - CUT - pd.Timedelta(minutes=15)] *= 3   # 대조: 컷오프 직전(17:45)까지 흔들면 roll7d가 움직여야 한다
        # 예측값이 아니라 특징값으로 본다 — 672슬롯 평균의 작은 변화는 RF 분기를 못 넘어 예측이 그대로일 수 있다(1차 실행에서 확인)
        assert rf_features(rf.q0, kw3, [d])["roll7d"].iloc[0] != rf_features(rf.q0, kw, [d])["roll7d"].iloc[0], \
            "대조 실패 — 시험이 아무것도 못 보고 있다(roll7d가 컷오프 직전 값을 안 쓴다)"
    # 5b. 복제 — 평가일(8월)의 부하 벡터가 예측 이력(직전 4주)에 그대로 있으면 예측이 실측을 베낀다
    for g in days:
        d = g.index[0].normalize()
        for k in range(1, 5):
            h = D.get(d - pd.Timedelta(days=7 * k))
            assert h is None or not np.array_equal(h, g["y"].values), f"{d.date()}: 직전 {k}주 날과 부하 벡터가 같다(복제)"
    # 6. P3 ≤ P5 (P5 ≤ P0는 단언하지 않는다 — 전일 계획은 P0보다 나빠질 수 있고 그것도 결과다)
    for s in S_GATE:
        p3 = T.loc[(T.정책 == POL_P3) & (T.s == s), "월최대"].iloc[0]
        assert (T.loc[(T.정책.str.startswith("P5")) & (T.s == s), "월최대"] >= p3 - 1e-6).all(), f"s={s}: P5 < P3(오라클 하한 위반)"
    # 6b. 8월 비교 행이 f9 선택표와 같다(같은 정의를 쓰고 있는지)
    f9 = pd.read_csv(B / "build/table_f9_select.csv", encoding="utf-8-sig").query("선택").iloc[0]
    r10 = T[T.s == S_SEL].set_index("정책")["월최대"]
    for k, col in [(POL_P0, "P0"), (POL_P2, "P2"), (POL_P3, "P3")]:
        assert abs(r10.loc[k] - f9[col]) < 0.01, f"8월 {k} {r10.loc[k]:.2f} ≠ f9 {f9[col]}"
    # 7. --test 단일 실행 강제
    tmp, tsel = B / "build/_f11_check_dummy.log", B / "build/_f11_check_dummy.csv"
    tmp.write_text("x", encoding="utf-8")
    T.to_csv(tsel, index=False, encoding="utf-8-sig")
    try:
        try:
            refuse_test(tsel, tmp)
            raise AssertionError("로그가 있는데 --test가 거부되지 않는다")
        except SystemExit:
            pass
    finally:
        tmp.unlink(); tsel.unlink()
    try:
        refuse_test(B / "build/_없는_파일.csv", B / "build/_없는_로그.log")
        raise AssertionError("선택표가 없는데 --test가 거부되지 않는다")
    except SystemExit:
        pass
    # 8. 테스트 코드 경로를 8월로 미리 돌려 본다(산출물은 쓰지 않는다)
    E, Pl = evaluate(VAL, fcs[p], cap)
    assert len(E) == 3 * 5 and len(Pl) == 3 * len(days) * 96 and (E.생산손실kWh == 0).all()
    print("self-check OK (1~7 + 5b 복제 + 6b f9 정합 + 테스트 경로 8월 시운전)")


def main():
    mode = [a for a in sys.argv[1:] if a in ("--select", "--test")]
    assert len(mode) == 1, "실행 인자: --select 또는 --test"
    q0 = load()
    if mode[0] == "--test":
        r, sha = refuse_test()
        TEST_LOG.write_text(f"{datetime.datetime.now().isoformat(timespec='seconds')} · 예측기={r['예측기']} · cap={r['cap']} · "
                            f"table_f11_select.csv SHA256 {sha}\n", encoding="utf-8")
        print(f"[로그 먼저 기록] {TEST_LOG.name}: {TEST_LOG.read_text(encoding='utf-8').strip()}")
        kw = q0["kw"]
        rf = RFDayAhead(q0, kw)
        rf.calibrate(kw, [d for d in day_matrix(kw[VA])])
        _, TEST = fit_predictions()
        days = by_day(TEST)
        D = day_matrix(kw)
        fc = {g.index[0].normalize(): forecast(r["예측기"], kw, D, rf, g.index[0].normalize(), "test") for g in days}
        E, Pl = evaluate(TEST, fc, float(r["cap"]))
        f9 = pd.read_csv(B / "build/table_f9.csv", encoding="utf-8-sig")
        for s in S_ROWS:
            g9 = f9[np.isclose(f9.s, s)].set_index("정책")["기간최대kW"]
            e = E[np.isclose(E.s, s)].set_index("정책")["월최대kW"]
            for k in [POL_P0, POL_P1, POL_P3]:
                assert abs(e[k] - g9[k]) < 0.01, f"테스트 s={s} {k} {e[k]} ≠ f9 {g9[k]}"
            p0, p3 = g9[POL_P0], g9[POL_P3]
            E = pd.concat([E, pd.DataFrame([dict(s=s, 정책=POL_P2, 월최대kW=g9[POL_P2], P0대비kW=round(g9[POL_P2] - p0, 2),
                                                  예측의가치=round((p0 - g9[POL_P2]) / (p0 - p3), 3), 이동량kWh=np.nan, 생산손실kWh=0.0, 무계획일=0)])])
            assert e[POL_P5] >= e[POL_P3] - 1e-6, f"테스트 s={s}: P5 < P3"
        E = E.sort_values(["s", "정책"]).reset_index(drop=True)
        E["예측기"], E["cap"] = r["예측기"], r["cap"]
        E["가정"] = ("s = 이동 가능 부하 비중(가정, 데이터에 없음) · 이동 폭 ±2h · 같은 날 안 · 에너지·생산 보존(차단 없음) · "
                    "예측기·cap은 8월에서 고정 · 기상은 실측을 전일 예보로 사용(가정) · P2는 f9 값" + R6_NOTE)
        E.to_csv(B / "build/table_f11.csv", index=False, encoding="utf-8-sig")
        Pl.to_csv(B / "build/f11_plan_test.csv", encoding="utf-8-sig")
        print(f"[테스트 1회 · 9/1~14 · {r['예측기']} · cap {r['cap']}]")
        print(E.drop(columns="가정").to_string(index=False))
        print("→ build/table_f11.csv · f11_plan_test.csv")
        return
    # --select: 테스트 구간 kw를 아예 잘라 낸다(8/31까지만 메모리에 둔다)
    kw = q0["kw"][:"2021-08-31"]
    VAL, TEST = fit_predictions()
    del TEST
    rf = RFDayAhead(q0, kw)
    aug = list(day_matrix(kw[VA]))
    rf.calibrate(kw, aug)
    days = by_day(VAL)
    fcs = build_forecasts(kw, rf, days, "val")
    print("[예측 8월 MAE] " + " · ".join(f"{p} {fc_mae(fcs[p], days):.2f}" for p in PREDS), flush=True)
    T = select(VAL, fcs)
    check(VAL, kw, rf, fcs, T, aug)
    A = cap_ablation(VAL, fcs, T)
    cols = ["s", "정책", "예측기", "cap", "월최대", "P0대비kW", "평일일피크중앙", "이동량kWh", "무계획일", "예측MAE", "순위", "평균순위", "선택"]
    T = T[cols]
    T[["월최대", "P0대비kW", "평일일피크중앙", "예측MAE"]] = T[["월최대", "P0대비kW", "평일일피크중앙", "예측MAE"]].round(2)
    T["이동량kWh"] = T["이동량kWh"].round(1)
    T.to_csv(SEL_CSV, index=False, encoding="utf-8-sig")
    A.to_csv(ABL_CSV, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(f"\n[8월 선택 · 후보 {len(PREDS)}×{len(CAPS)} · s∈{S_GATE}]")
    print(T.to_string(index=False))
    print("\n[cap 제거실험 · 8월]")
    print(A.to_string(index=False))
    ok, r, p1 = gate(T)
    print(f"\n[게이트] {'통과' if ok else '실패'} — 선택 {r['예측기']} · cap {r['cap']:.0f} · 8월 s=10% 월최대 {r['월최대']:.2f}kW "
          f"(P0대비 {r['P0대비kW']:+.2f}) vs 기준 P1 {p1:.2f} − {GATE_MARGIN:.0f} = {p1 - GATE_MARGIN:.2f}")
    print(f"→ {SEL_CSV.relative_to(B)} · {ABL_CSV.relative_to(B)}")


if __name__ == "__main__":
    main()
