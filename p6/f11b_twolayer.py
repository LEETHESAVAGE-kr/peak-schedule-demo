# F11b — 2층 보정 P6(규칙 사전 고정: ..\KAMP_제6회_2층보정_선택규칙_20261005.md).
# 1층 = F11 전일 운전표(naive_med4 · cap 20, 8월 선택 그대로). 2층 = 당일 +60분 상단으로 위험한 슬롯에 들어올 계획 이동을 취소(원위치).
# **테스트(9/1~14)는 읽지 않는다** — P6 개발 동기가 F11 테스트 결과에서 나왔으므로 테스트 모드를 두지 않는다.
# 검증 = 8월(선택·통과 기준) + 테스트 밖 달 4·5·7월(확인, 복제일 제외).
# 실행: python -X utf8 f11b_twolayer.py   → build/table_f11b_select.csv · table_f11b_rolling.csv
import numpy as np, pandas as pd
from sklearn.ensemble import RandomForestRegressor
from common import B, B3, load, frame
from closed_loop_core import H, ALPHA, qtl, fit_predictions, by_day, calendar, oracle
import f11_dayahead as F11

THETAS, AMOUNTS = ["T0", "plan"], ["need", "all"]
T0 = 190.0
S_GATE = [0.05, 0.10]
ROLL = [4, 5, 7]
SEL_CSV, ROLL_CSV = B / "build/table_f11b_select.csv", B / "build/table_f11b_rolling.csv"
POL_P6 = "P6 2층(전일+60분 보정)"


def layer1():
    S = pd.read_csv(F11.SEL_CSV, encoding="utf-8-sig")
    r = S[S["선택"]].iloc[0]
    return r["예측기"], float(r["cap"])


# ===== 2층 =====
def second_layer(F, f, up, s, theta, amount, log=None):
    """F: 1층 이동 비율(96×96, 행 합 1) · f: 1층 예측 · up: +60분 상단. 반환 F′(취소 반영).
    시각 k에 r=k+H가 드러난다. 취소 대상은 출발 슬롯 t > k인 이동뿐(이미 시작 시각이 지난 작업은 고정).
    log가 list면 (결정시각 k, 출발 t, 도착 r, 취소 비율) 을 쌓는다 — 인과성 시험용."""
    Fp = F.copy()
    if s == 0 or not np.isfinite(theta):
        return Fp
    est = np.asarray(f, float).copy()
    off = lambda: Fp - np.diag(np.diag(Fp))

    def hat(w):
        O = off()
        return est[w] * (1 - s * O[w].sum()) + s * (est @ O[:, w])

    for k in range(-H, 96):
        r = k + H
        if not (0 <= r <= 95):
            continue
        est[r] = up[r]
        hr = hat(r)
        if hr < theta:
            continue
        origins = [t for t in range(max(k + 1, 0), 96) if t != r and Fp[t, r] > 1e-12 and est[t] > 0]
        for t in sorted(origins, key=hat):
            full = s * est[t] * Fp[t, r]
            a = full if amount == "all" else min(full, hr - theta)
            if a <= 1e-9:
                break
            if not (hat(t) + a < theta):
                continue
            d = a / (s * est[t])
            Fp[t, r] -= d; Fp[t, t] += d
            hr -= a
            if log is not None:
                log.append((k, t, r, d))
            if amount == "need" and hr < theta:
                break
    return Fp


def theta_of(name, f, s, F):
    return T0 if name == "T0" else float(((1 - s) * f + (s * f) @ F).max())


def run_days(days, fc, s, cap, theta_name=None, amount=None):
    """1층(+선택 시 2층) 실현 부하 리스트. fc: {날짜: f}. days의 g는 y·up 열을 가진다."""
    outs = []
    for g in days:
        d, y = g.index[0].normalize(), g["y"].values
        f = fc.get(d)
        if f is None:
            outs.append(y * 1.0); continue
        F = F11.plan(np.asarray(f, float), s, cap)
        if theta_name is not None:
            F = second_layer(F, f, g["up"].values, s, theta_of(theta_name, f, s, F), amount)
        outs.append(F11.realize(y, s, F))
    return outs


def stats(days, outs):
    M = np.array(outs)
    wk = np.array([g.index[0].dayofweek < 5 for g in days])
    return float(M.max()), float(np.median(M.max(1)[wk])) if wk.any() else np.nan


def compare(days, fc, s, cap, cands):
    """한 구간의 정책별 월 최대. cands: [(θ, 취소량)]"""
    R = {"P0 현행": stats(days, [g["y"].values * 1.0 for g in days]),
         "P1 달력 규칙": stats(days, [calendar(g, s) for g in days]),
         "P3 오라클(실측, LP)": stats(days, [oracle(g, s) for g in days]),
         "P5 전일 운전표": stats(days, run_days(days, fc, s, cap))}
    for th, am in cands:
        R[(th, am)] = stats(days, run_days(days, fc, s, cap, th, am))
    return R


# ===== 테스트 밖 달 분할 — +60분 모형을 그 달 이전 데이터로 다시 적합(f9 레시피, n_jobs=1) =====
def fit_fold(m):
    q0 = load()
    d = frame(q0, H)
    start = pd.Timestamp(2021, m, 1)
    tr, ev = d[d.index < start], d[(d.index >= start) & (d.index < start + pd.offsets.MonthBegin(1))]
    mdl = RandomForestRegressor(max_depth=20, random_state=42, n_jobs=1).fit(tr[B3], tr["kw"])
    pv = mdl.predict(ev[B3])
    half = len(tr) // 2
    ma = RandomForestRegressor(max_depth=20, random_state=42, n_jobs=1).fit(tr[B3][:half], tr["kw"][:half])
    ms = RandomForestRegressor(max_depth=10, random_state=42, n_jobs=1).fit(tr[B3][half:], np.abs(tr["kw"].values[half:] - ma.predict(tr[B3][half:])))
    sv = np.maximum(ms.predict(ev[B3]), 1e-3)
    z = (ev["kw"].values - pv) / sv
    fold = (ev.index.day > 15).astype(int)
    up = np.where(fold == 0, pv + qtl(z[fold == 1], ALPHA) * sv, pv + qtl(z[fold == 0], ALPHA) * sv)
    return pd.DataFrame(dict(y=ev["kw"].values, pred=pv, up=up), index=ev.index)


def dedup_days(days, D):
    """평가일 부하 벡터가 그 전 어느 날과 같으면 뺀다(복제 — 예측 이력·학습이 실측을 베낀다)."""
    keep, drop = [], 0
    for g in days:
        d = g.index[0].normalize()
        if any(np.array_equal(D[d], D[x]) for x in D if x < d):
            drop += 1
        else:
            keep.append(g)
    return keep, drop


# ===== self-check — 결함을 되살리면 깨진다 =====
def check(VAL, fc, cap):
    days = by_day(VAL)
    rng = np.random.default_rng(0)
    g = max(days, key=lambda g: g["y"].max())                  # 8월 피크일 + 몇 날
    sample = [g] + [days[i] for i in (9, 12, 23)]
    for g in sample:
        d, y, f = g.index[0].normalize(), g["y"].values, np.asarray(fc[g.index[0].normalize()], float)
        F = F11.plan(f, 0.10, cap)
        # 1. θ=∞ → P6 = P5 · s=0 → F′ = I
        assert np.allclose(second_layer(F, f, g["up"].values, 0.10, np.inf, "all"), F), "θ=∞인데 P6 ≠ P5"
        assert np.allclose(second_layer(np.eye(96), f, g["up"].values, 0.0, 190, "all"), np.eye(96)), "s=0인데 이동이 생겼다"
        for th in THETAS:
            for am in AMOUNTS:
                Fp = second_layer(F, f, g["up"].values, 0.10, theta_of(th, f, 0.10, F), am)
                # 2. 행 합 1·비음수 → 일 합 보존
                assert np.allclose(Fp.sum(1), 1) and (Fp >= -1e-12).all(), f"{th}/{am}: F′ 행 합·부호 위반"
                assert abs(F11.realize(y, 0.10, Fp).sum() - y.sum()) < 1e-6, f"{th}/{am}: 일 합 불보존"
                # 3. 취소만 한다 — 1층에 없던 이동을 새로 만들지 않는다
                assert ((Fp - np.diag(np.diag(Fp))) <= (F - np.diag(np.diag(F))) + 1e-12).all(), f"{th}/{am}: 새 이동이 생겼다"
        # 4. 인과성 — 결정 시각 k의 취소는 up[≤k+H]·f만 쓴다. up[j:]를 흔들어도 k < j−H인 결정은 불변
        lg = []; second_layer(F, f, g["up"].values, 0.10, T0, "need", lg)
        for j in [40, 60, 80]:
            u2 = g["up"].values.copy(); u2[j:] = u2[j:] * rng.uniform(0.5, 1.5, 96 - j)
            lg2 = []; second_layer(F, f, u2, 0.10, T0, "need", lg2)
            a = [x for x in lg if x[0] < j - H]; b = [x for x in lg2 if x[0] < j - H]
            assert len(a) == len(b) and all(x[:3] == z[:3] and abs(x[3] - z[3]) < 1e-12 for x, z in zip(a, b)), f"j={j}: 취소가 미래 상단에 의존한다"
        # 5. 이미 출발 시각이 지난 이동은 취소하지 않는다
        assert all(t > k for k, t, r, _ in lg), "출발 시각이 지난 이동을 취소했다"
    print("self-check OK (1~5)")


def main():
    pd.set_option("display.width", 250)
    pred, cap = layer1()
    q0 = load(); kw = q0["kw"][:"2021-08-31"]
    D = F11.day_matrix(kw)
    assert pred.startswith("naive"), "1층이 naive가 아니면 RF 예측기 적합이 필요하다 — 이 스크립트는 naive만 다룬다"
    stat = "med" if pred == "naive_med4" else "q75"
    fc_all = {d: F11.naive(D, d, stat) for d in D}
    VAL, TEST = fit_predictions(); del TEST
    check(VAL, fc_all, cap)
    cands = [(th, am) for th in THETAS for am in AMOUNTS]
    # ---- 8월 선택 ----
    days = by_day(VAL)
    rows = []
    for s in S_GATE:
        R = compare(days, fc_all, s, cap, cands)
        for k, (mx, wk) in R.items():
            rows.append(dict(s=s, 정책=POL_P6 if isinstance(k, tuple) else k, θ=k[0] if isinstance(k, tuple) else "",
                             취소량=k[1] if isinstance(k, tuple) else "", 월최대=round(mx, 2), 평일일피크중앙=round(wk, 2)))
        print(f"  8월 s={s} 완료", flush=True)
    T = pd.DataFrame(rows)
    c = T.정책 == POL_P6
    T.loc[c, "순위"] = T[c].groupby("s")["월최대"].rank(method="average")
    agg = T[c].groupby(["θ", "취소량"]).agg(평균순위=("순위", "mean"), 평일=("평일일피크중앙", "mean")).reset_index()
    agg["_am"], agg["_th"] = (agg.취소량 != "need").astype(int), (agg.θ != "T0").astype(int)
    best = agg.sort_values(["평균순위", "평일", "_am", "_th"]).iloc[0]
    T["선택"] = c & (T.θ == best["θ"]) & (T.취소량 == best["취소량"])
    T.to_csv(SEL_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[8월 · 1층 {pred} cap {cap:.0f} 고정]"); print(T.to_string(index=False))
    sel = (best["θ"], best["취소량"])
    g8 = {s: T[T.s == s].set_index("정책") for s in S_GATE}
    p6 = {s: T[(T.s == s) & T.선택]["월최대"].iloc[0] for s in S_GATE}
    p5 = {s: g8[s].loc["P5 전일 운전표", "월최대"] for s in S_GATE}
    gate1, gate2 = p6[0.10] <= p5[0.10] - 1 + 1e-9, p6[0.05] <= p5[0.05] + 1e-9
    # ---- 테스트 밖 달 4·5·7월 ----
    rr = []
    for m in ROLL:
        ev = fit_fold(m)
        dm, drop = dedup_days(by_day(ev), D)
        for s in S_GATE:
            R = compare(dm, fc_all, s, cap, [sel])
            for k, (mx, wk) in R.items():
                rr.append(dict(월=m, s=s, 정책=POL_P6 if isinstance(k, tuple) else k, 월최대=round(mx, 2), 평일일피크중앙=round(wk, 2),
                               평가일=len(dm), 평일=sum(g.index[0].dayofweek < 5 for g in dm), 복제제외일=drop))
        print(f"  롤링 {m}월 완료(평가 {len(dm)}일, 복제 제외 {drop}일)", flush=True)
    Rr = pd.DataFrame(rr)
    Rr["선택후보"] = f"{sel[0]}/{sel[1]}"
    Rr.to_csv(ROLL_CSV, index=False, encoding="utf-8-sig")
    print("\n[롤링 · 선택 후보 고정]"); print(Rr.to_string(index=False))
    w = Rr[Rr.s == 0.10].pivot(index="월", columns="정책", values="월최대")
    gate3 = bool((w[POL_P6] <= w["P5 전일 운전표"] + 1e-9).all())
    for k in ["P5 전일 운전표", POL_P6]:                       # 오라클 하한
        assert (Rr[Rr.정책 == k].set_index(["월", "s"])["월최대"] >= Rr[Rr.정책.str.startswith("P3")].set_index(["월", "s"])["월최대"] - 1e-6).all()
    print(f"\n[게이트] 선택 θ={sel[0]} · 취소량={sel[1]}")
    print(f"  1. 8월 s=10%: P6 {p6[0.10]:.2f} ≤ P5 {p5[0.10]:.2f} − 1 → {'통과' if gate1 else '실패'}")
    print(f"  2. 8월 s=5%:  P6 {p6[0.05]:.2f} ≤ P5 {p5[0.05]:.2f} → {'통과' if gate2 else '실패'}")
    print(f"  3. 롤링 s=10% P6 ≤ P5 세 달 모두 → {'통과' if gate3 else '실패'}  " + " · ".join(f"{m}월 {w.loc[m, POL_P6]:.2f}/{w.loc[m, 'P5 전일 운전표']:.2f}" for m in ROLL))
    print(f"  → {'성공' if gate1 and gate2 and gate3 else '실패'}")


if __name__ == "__main__":
    main()
