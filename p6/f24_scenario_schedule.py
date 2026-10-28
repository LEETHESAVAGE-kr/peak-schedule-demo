# F24 — 시나리오 운전표. 사전등록 prereg_F24_운영예측기_20261007.md.
# 예측 한 줄 대신 과거 실제 하루들(직전 4주 A, 유사일 kNN B)을 시나리오로 두고 LP가 그 전부를 본다.
# 후보 C0(현행 한 줄) · R1(A, 최악) · R2(A∪B, 최악) · W2(A∪B, 기대) + 보고 전용 W1(A, 기대). 정책 조건은 v2 B와 같다.
# 실행: python -X utf8 f24_scenario_schedule.py                → build/table_f24_rolling.csv · table_f24_select.csv · table_f24_kr.csv
#       python -X utf8 f24_scenario_schedule.py --quick        (무결함 축약판: 7월·s_kr·0.337 — 재삽입 전에 먼저 통과해야 한다)
#       python -X utf8 f24_scenario_schedule.py --mutate N     (결함 재삽입 1..8, 축약판 — 깨져야 정상, 산출물 안 씀)
#       python -X utf8 f24_scenario_schedule.py --test --dry   (테스트 경로를 8월로 시운전) / --test --confirm (기준 통과 시 1회)
# 기존 스크립트·표는 읽기 전용(import만). run_all은 import하지 않는다(__main__ 가드 없음).
import sys, hashlib, datetime
import numpy as np, pandas as pd, pulp
from common import B, load
from closed_loop_core import by_day
import f11_dayahead as F11
import f14_schedule_v2 as F14
import f18_breakeven as F18
import f19_kr_blind as F19
import f21_decision_forecaster as F21
from f11b_twolayer import dedup_days

PREREG, PREREG_SHA = B / "prereg_F24_운영예측기_20261007.md", "20484e98663f16e231d8706e90b3e6222daf879565f2fb0bed8f4890da413d8f"
ROLL_CSV, SEL_CSV, KR_CSV = B / "build/table_f24_rolling.csv", B / "build/table_f24_select.csv", B / "build/table_f24_kr.csv"
TEST_CSV, TEST_LOG, DRY_LOG = B / "build/table_f24_testat.csv", B / "build/f24_test_read.log", B / "build/f24_test_dry.log"
MONTHS, SENS, SEL_M = [2, 4, 5, 7, 8], [3, 6], [4, 5, 7, 8]
CAP, LW = 20.0, 16
CANDS = ["C0", "R1", "W2", "R2"]                       # 선택 대상(동률 깨기 순서 C0 → R1 → W2 → R2)
ALL = CANDS + ["W1"]                                   # W1 = 보고 전용
SPEC = {"R1": ("A", "max"), "R2": ("AB", "max"), "W2": ("AB", "mean"), "W1": ("A", "mean")}
C0_TEST = 189.66
MUT = 0
LOG_SCN, LOG_PLAN = [], []                             # (대상일, 시나리오 날들) / (위험, v*, 계획 후 max, 계획 후 mean)


# ===== 1. 시나리오 =====
def uniq(days, D):
    out, seen = [], set()
    for x in sorted(days):
        k = D[x].tobytes()
        if k in seen and MUT != 2:                     # 재삽입 2: 복제군 중복 허용
            continue
        seen.add(k); out.append(x)
    return out


def scen_A(D, d):
    return [d - pd.Timedelta(days=7 * k) for k in range(1, 5) if d - pd.Timedelta(days=7 * k) in D]


def scen_B(D, Fx, sd, d):
    F21.PICKS.clear()
    if F21.knn(D, Fx, d, sd) is None:
        return []
    return list(F21.PICKS[-1][1])


def scen_sets(D, Fx, sd, d):
    a = scen_A(D, d)
    b = scen_B(D, Fx, sd, d) if Fx is not None else []
    if MUT == 1:
        a = a + [d]                                    # 재삽입 1: 당일 실측을 시나리오에 넣는다
    return {"A": uniq(a, D), "AB": uniq(sorted(set(a) | set(b)), D)}


# ===== 2. 시나리오 LP =====
def plan_scen(Ys, s, cap, L, pr, risk):
    """Ys: (J,96) 시나리오. 반환 이동 비율 x(96×96). 1단 R=min max_j P_j / W=min mean_j P_j, 2단 v* 묶고 평균 TOU+1e-3 이동량."""
    Ys = np.asarray(Ys, float); J = len(Ys); pi = np.full(J, 1.0 / J)
    X = np.eye(96)
    if s == 0:
        return X
    rng = lambda t: range(max(0, t - L), min(95, t + L) + 1)
    live = [t for t in range(96) if (s * Ys[:, t]).max() > 1e-9]
    m = pulp.LpProblem("f24", pulp.LpMinimize)
    x = {(t, w): pulp.LpVariable(f"x_{t}_{w}", 0) for t in live for w in rng(t)}
    for t in live:
        m += pulp.lpSum(x[t, w] for w in rng(t)) == 1
    inflow = lambda j, w: pulp.lpSum(s * Ys[j, t] * x[t, w] for t in rng(w) if (t, w) in x)
    stay = lambda j, w: (1 - s) * Ys[j, w] + (s * Ys[j, w] if w not in live else 0)
    use = "mean" if (MUT == 4 and risk == "max") else risk          # 재삽입 4: 최악형을 평균으로 푼다
    if use == "max":
        Pk = pulp.LpVariable("Pk", 0); P = [Pk] * J
    else:
        P = [pulp.LpVariable(f"P_{j}", 0) for j in range(J)]
    for j in range(J):
        for w in range(96):
            m += stay(j, w) + inflow(j, w) <= P[j]
            if np.isfinite(cap):
                m += pulp.lpSum(s * Ys[j, t] * x[t, w] for t in rng(w) if t != w and (t, w) in x) <= cap
    obj1 = P[0] if use == "max" else pulp.lpSum(pi[j] * P[j] for j in range(J))
    m += obj1
    m.solve(pulp.PULP_CBC_CMD(msg=0)); assert pulp.LpStatus[m.status] == "Optimal"
    v = pulp.value(obj1)
    if MUT != 5:                                                     # 재삽입 5: 2단이 1단 값에 묶이지 않는다
        m += obj1 <= v + 1e-6 * max(1.0, v)
    ybar = pi @ Ys
    mv = pulp.lpSum(s * ybar[t] * x[t, w] for (t, w) in x if t != w)
    m.setObjective(pulp.lpSum(pr[w] * s * ybar[t] * x[t, w] for (t, w) in x if t != w) + 1e-3 * mv)
    m.solve(pulp.PULP_CBC_CMD(msg=0)); assert pulp.LpStatus[m.status] == "Optimal"
    for t in live:
        X[t, t] = 0.0
        for w in rng(t):
            X[t, w] = max(pulp.value(x[t, w]) or 0.0, 0.0)
        X[t] /= X[t].sum()
    pk = np.array([((1 - s) * Ys[j] + (s * Ys[j]) @ X).max() for j in range(J)])
    LOG_PLAN.append((risk, v, float(pk.max()), float(pi @ pk)))
    return X


def run_scen(days, D, Fx, sd, key, risk, s, cap, fc0):
    """반환 (실현 부하, 무계획 일수, C0 대체 일수, 시나리오 수 합). carry 없음 → 날마다 독립."""
    outs, nop, fb, ns = [], 0, 0, 0
    for g in days:
        d, y = g.index[0].normalize(), g["y"].values
        S = scen_sets(D, Fx, sd, d)[key]
        LOG_SCN.append((d, S))
        pr = F14.price(g.index)
        if len(S) >= 2:
            X = plan_scen([D[x] for x in S], s, cap, LW, pr, risk); ns += len(S)
        elif fc0.get(d) is not None:
            X, _ = F14.plan2(np.asarray(fc0[d], float), s, cap, LW, True, pr, np.zeros(96)); fb += 1
        else:
            X = np.eye(96); nop += 1
        out = (1 - s) * y + (s * y) @ X
        if MUT == 6:
            out = out * 0.97                                         # 재삽입 6: 에너지 비보존
        assert abs(out.sum() - y.sum()) < 1e-6, f"{d.date()}: 일 에너지 불보존"
        outs.append(out)
    return outs, nop, fb, ns


def made_peaks(days, outs):
    return int(sum(o.max() > g["y"].values.max() + 1.0 for g, o in zip(days, outs)))


# ===== 3. 테스트 밖 달 평가 =====
def month_rows(q0, kw, m, dedup, slist):
    start = pd.Timestamp(2021, m, 1)
    days = by_day(F14.month_frame(kw, m))
    D = F11.day_matrix(kw)
    drop = 0
    if dedup:
        days, drop = dedup_days(days, D)
    if not days:
        return []
    Fx = F21.day_feats(q0, D); sd = F21.scale(Fx, start)
    fc0 = {g.index[0].normalize(): F11.naive(D, g.index[0].normalize(), "med") for g in days}
    cap = CAP if MUT != 3 else 10.0                                  # 재삽입 3: cap 변경
    rows = []
    for s in slist:
        p3b = float(np.array([F14.oracle_L(g, s, LW) for g in days]).max())
        res = {}
        o, _, nop, _ = F14.run_variant(days, fc0, s, CAP, LW, True, False)
        res["C0"] = (o, nop, 0, 0)
        for c, (key, risk) in SPEC.items():
            res[c] = run_scen(days, D, Fx, sd, key, risk, s, cap, fc0)
        c0 = float(np.array(res["C0"][0]).max())
        for c in ALL:
            o, nop, fb, ns = res[c]
            mx = float(np.array(o).max())
            rows.append(dict(월=m, 구분="선택 오염(F11 선택 월)" if m == 8 else "롤링", 복제처리="제외" if dedup else "포함(민감도)",
                             s=s, 후보=c, 선택대상=c in CANDS, 월최대=round(mx, 2), C0대비kW=round(mx - c0, 2), 사후최적P3b=round(p3b, 2),
                             격차감소=round((c0 - mx) / (c0 - p3b), 3) if c0 - p3b > 1e-9 else np.nan,
                             계획이만든피크일=made_peaks(days, o), 시나리오수평균=round(ns / max(1, len(days) - nop - fb), 2) if c != "C0" else np.nan,
                             C0대체일=fb, 무계획일=nop, 평가일=len(days), 복제제외일=drop))
    return rows


# ===== 4. 단조 2곳 (gate 단조 조건) =====
def kr_rows(sk):
    import k7_tariff_cost as K7
    holi, K7.HOLI = K7.HOLI, F19.HOL19                               # f19와 같은 설정: 2019 공휴일을 경부하로(재실행 1 수정)
    try:
        return _kr_rows(sk)
    finally:
        K7.HOLI = holi


def _kr_rows(sk):
    rows = []
    for f in F19.FORGES:
        q = F19.series(f); D = F19.complete_days(q)
        for m in F19.MONTHS:
            days = [pd.DataFrame(dict(y=v), index=pd.date_range(d, periods=96, freq="15min")) for d, v in D.items() if d.month == m]
            fc0 = {g.index[0].normalize(): F11.naive(D, g.index[0].normalize(), "med") for g in days}
            cap = F19.cap_for(q, m)
            base = max(g["y"].values.max() for g in days)
            o, _, _, _ = F14.run_variant(days, fc0, sk, cap, LW, True, False)
            res = {"C0": o}
            for c in ["R1", "W1"]:
                key, risk = SPEC[c]
                res[c] = run_scen(days, D, None, None, key, risk, sk, cap, fc0)[0]
            for c, o in res.items():
                mx = float(np.array(o).max())
                rows.append(dict(공장=f, 월=m, s=sk, 후보=c, 현행월최대=round(base, 3), 월최대=round(mx, 3), 현행보다높음=bool(mx > base + 0.005)))
    return pd.DataFrame(rows)


# ===== 5. 선택·통과 기준 =====
def select(R, sk, K):
    E = R[(R.복제처리 == "제외") & R.월.isin(SEL_M) & R.후보.isin(CANDS)].copy()
    E["순위"] = E.groupby(["월", "s"])["월최대"].rank(method="average")
    A = E.groupby("후보")["순위"].mean().reindex(CANDS)
    best = min(CANDS, key=lambda c: (round(A[c], 9), CANDS.index(c)))
    F = R[(R.복제처리 == "제외") & R.월.isin(SEL_M)]
    w = lambda c, s: F[(F.후보 == c) & np.isclose(F.s, s)].set_index("월")["월최대"]
    sel_k, c0_k = w(best, sk), w("C0", sk)
    worse = int(sum((E[E.후보 == best].set_index(["월", "s"])["월최대"] - E[E.후보 == "C0"].set_index(["월", "s"])["월최대"]) > 0.005))
    kr_c = {"R1": "R1", "R2": "R1", "W2": "W1"}.get(best)
    kr_n = lambda c: int(K[K.후보 == c]["현행보다높음"].sum())
    cond = dict(선택_아님_C0=best != "C0", 평균_1kW_이상_개선=bool(sel_k.mean() <= c0_k.mean() - 1.0),
                어느달도_1kW_넘게_악화없음=bool(((sel_k - c0_k) <= 1.0).all()), 악화칸_3이하=worse <= 3,
                단조_현행초과_C0이하=bool(kr_c is not None and kr_n(kr_c) <= kr_n("C0")))
    verdict = "실패" if best == "C0" else ("통과" if all(cond.values()) else "부분")
    ml = ""
    if best in ("R2", "W2"):
        base = "R1" if best == "R2" else "W1"
        dlt = w(best, sk).mean() - w(base, sk).mean()
        ml = f"{best}−{base} s_kr 4개월 평균 {dlt:+.2f}kW → " + ("유사일 증분 있음" if dlt <= -0.5 else "유사일 증분 확인 안 됨")
    S = pd.DataFrame([dict(후보=c, 선택대상=c in CANDS, 평균순위=round(A[c], 3) if c in CANDS else np.nan,
                           s_kr_4개월평균월최대=round(w(c, sk).mean(), 2), s_kr_C0대비=round(w(c, sk).mean() - c0_k.mean(), 2),
                           선택=(c == best)) for c in ALL])
    S["판정"] = verdict
    S["조건"] = " · ".join(f"{k}={v}" for k, v in cond.items()) + f" · 악화칸={worse}/12 · 단조 현행초과 {kr_c}={kr_n(kr_c) if kr_c else '-'} vs C0={kr_n('C0')}/12"
    S["ML증분"] = ml
    return S, verdict


# ===== 6. self-check — 결함을 되살리면 깨진다 =====
def check(R, kw, sk, quick, q0=None):
    assert kw.index.max() < pd.Timestamp("2021-09-01"), "테스트 구간이 메모리에 있다"            # 재삽입 8
    D = F11.day_matrix(kw)
    for d, S in LOG_SCN:                                                                     # 재삽입 1
        assert all(x <= d - pd.Timedelta(days=2) for x in S), f"{d.date()}: 시나리오에 D−1 18:00 이후 날 {S}"
        assert len({D[x].tobytes() for x in S if x in D}) == len(S), f"{d.date()}: 복제군 중복 시나리오"   # 재삽입 2
    for risk, v, mx, mean in LOG_PLAN:                                                       # 재삽입 4·5
        got = mx if risk == "max" else mean
        assert got <= v + 1e-4 * max(1.0, v), f"계획 후 {risk} {got:.4f} > 1단 값 {v:.4f} (위험 척도 또는 2단 묶음 결함)"
    # 시나리오 1개 = C0 한 줄이면 C0와 같다 (7월, s_kr·0.337) — cap 결함(재삽입 3)을 본다
    days, _ = dedup_days(by_day(F14.month_frame(kw, 7)), D)
    fc0 = {g.index[0].normalize(): F11.naive(D, g.index[0].normalize(), "med") for g in days}
    for s in [sk, 0.337]:
        ref = float(np.array(F14.run_variant(days, fc0, s, CAP, LW, True, False)[0]).max())
        cap = CAP if MUT != 3 else 10.0
        o = [(1 - s) * g["y"].values + (s * g["y"].values) @ plan_scen([fc0[g.index[0].normalize()]], s, cap, LW, F14.price(g.index), "max")
             for g in days]
        got = float(np.array(o).max())
        assert abs(got - ref) < 0.01, f"7월 s={s}: 시나리오 1개 LP {got:.2f} ≠ C0 {ref:.2f}"
    if not quick:
        T = pd.read_csv(B / "build/table_f21_rolling.csv", encoding="utf-8-sig")
        n = 0
        for _, r in R[R.후보 == "C0"].iterrows():
            t = T[(T.월 == r.월) & np.isclose(T.s, r.s) & (T.후보 == "C0 naive_med4") & (T.복제처리 == r.복제처리)]
            assert len(t) == 1 and abs(t["월최대"].iloc[0] - r.월최대) < 0.01, f"{r.월}월 s={r.s} C0 {r.월최대} ≠ f21"
            n += 1
        print(f"  C0 = table_f21_rolling {n}행 일치")
    assert (R.월 != 9).all()
    print(f"self-check OK (시나리오 인과·중복 0 {len(LOG_SCN)}건 · 계획 {len(LOG_PLAN)}건 위험척도·2단 · 1시나리오=C0 · 에너지 보존 · 9월 없음)")


def check_kr(K, sk):
    T = pd.read_csv(B / "build/table_f19_kr.csv", encoding="utf-8-sig")
    for _, r in K[K.후보 == "C0"].iterrows():
        t = T[(T.공장 == r.공장) & (T.월 == r.월) & np.isclose(T.s, sk) & (T.정책 == F19.V2)]
        assert len(t) == 1 and abs(t["월최대"].iloc[0] - r.월최대) < 0.01, f"단조 {r.공장} {r.월}월 C0 {r.월최대} ≠ f19 {t['월최대'].tolist()}"
    print(f"  단조 C0 = table_f19_kr {int((K.후보 == 'C0').sum())}행 일치")


def prereg_ok():
    h = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    if h != (PREREG_SHA if MUT != 7 else "0" * 64):                                          # 재삽입 7
        raise SystemExit(f"[거부] 사전등록 SHA {h[:16]}… ≠ 등록값")


# ===== 7. 테스트 (기준 통과 시 1회) =====
def do_test(dry, confirm):
    S = pd.read_csv(SEL_CSV, encoding="utf-8-sig")
    best, verdict = S[S.선택].iloc[0]["후보"], S["판정"].iloc[0]
    sk = F18.s_kr()
    if not dry:
        if verdict != "통과":
            raise SystemExit("[거부] F24 게이트가 통과가 아니다")
        if not DRY_LOG.exists():
            raise SystemExit("[거부] --test --dry 시운전 로그가 없다")
        if TEST_LOG.exists():
            raise SystemExit("[거부] 테스트는 1회만 읽는다 — f24_test_read.log가 이미 있다")
        if not confirm:
            raise SystemExit("[거부] --confirm 없음(사용자 확인 후 1회)")
    q0 = load()
    q0 = q0 if not dry else q0[q0.index < "2021-09-01"]
    kw = q0["kw"]
    m = 8 if dry else 9
    days = by_day(F14.month_frame(kw, m))
    D = F11.day_matrix(kw)
    if not dry:
        days = [g for g in days if g.index[0] <= pd.Timestamp("2021-09-14")]
    else:
        days, _ = dedup_days(days, D)
    start = pd.Timestamp(2021, m, 1)
    Fx = F21.day_feats(q0, D); sd = F21.scale(Fx, start)
    fc0 = {g.index[0].normalize(): F11.naive(D, g.index[0].normalize(), "med") for g in days}
    rows = []
    for c in dict.fromkeys(["C0", best]):
        if c == "C0":
            o = F14.run_variant(days, fc0, sk, CAP, LW, True, False)[0]
        else:
            o = run_scen(days, D, Fx, sd, *SPEC[c], sk, CAP, fc0)[0]
        rows.append(dict(s=sk, 후보=c, 월최대kW=round(float(np.array(o).max()), 2), 계획이만든피크일=made_peaks(days, o),
                         구간="8월 시운전" if dry else "테스트 9/1~14"))
    E = pd.DataFrame(rows)
    ref = 200.59 if dry else C0_TEST
    assert abs(E[E.후보 == "C0"]["월최대kW"].iloc[0] - ref) < 0.01, f"C0 ≠ 기준 {ref}"
    if dry:
        DRY_LOG.write_text(f"{datetime.datetime.now().isoformat(timespec='seconds')} · 8월 시운전 통과 · {E.to_dict('records')}\n", encoding="utf-8")
        print(E.to_string(index=False)); print(f"[시운전] → {DRY_LOG.name}"); return
    E.to_csv(TEST_CSV, index=False, encoding="utf-8-sig")
    TEST_LOG.write_text(f"{datetime.datetime.now().isoformat(timespec='seconds')} · 선택={best} · s={sk} · "
                        f"table_f24_testat.csv SHA256 {hashlib.sha256(TEST_CSV.read_bytes()).hexdigest()}\n", encoding="utf-8")
    print(E.to_string(index=False)); print(f"→ {TEST_CSV.relative_to(B)} · {TEST_LOG.name}")


def main():
    global MUT
    args = sys.argv[1:]
    if "--mutate" in args:
        MUT = int(args[args.index("--mutate") + 1])
        if MUT == 2:
            F21.MUT = 2                                                                 # 재삽입 2는 kNN 쪽 복제 제외도 끈다
    prereg_ok()
    if "--test" in args:
        do_test("--dry" in args, "--confirm" in args); return
    quick = bool(MUT) or "--quick" in args
    sk = F18.s_kr()
    q0 = load()
    q0 = q0[q0.index < "2021-09-01"] if MUT != 8 else q0                                    # 재삽입 8: 테스트 구간을 메모리에 둔다
    kw = q0["kw"]
    slist = [sk, 0.337] if quick else [0.10, sk, 0.337]
    rows = []
    for m, dd in ([(7, True)] if quick else [(m, True) for m in MONTHS] + [(m, False) for m in SENS]):
        rows += month_rows(q0, kw, m, dd, slist)
        print(f"  {m}월 완료 {datetime.datetime.now():%H:%M:%S}", flush=True)
    R = pd.DataFrame(rows)
    check(R, kw, sk, quick)
    if quick:
        print(f"[{'재삽입 ' + str(MUT) if MUT else '축약판 무결함'}] self-check 통과" + (" — 검사가 이 결함을 못 본다" if MUT else ""))
        print(R[["s", "후보", "월최대", "C0대비kW", "계획이만든피크일", "시나리오수평균", "C0대체일"]].to_string(index=False)); return
    K = kr_rows(sk); check_kr(K, sk)
    S, verdict = select(R, sk, K)
    R.to_csv(ROLL_CSV, index=False, encoding="utf-8-sig"); S.to_csv(SEL_CSV, index=False, encoding="utf-8-sig")
    K.to_csv(KR_CSV, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(R.pivot_table(index=["복제처리", "월", "s"], columns="후보", values="월최대").round(2).to_string())
    print(R[R.복제처리 == "제외"].pivot_table(index=["월", "s"], columns="후보", values="계획이만든피크일").to_string())
    print(K.pivot_table(index=["공장", "월"], columns="후보", values="월최대").round(2).to_string())
    print(S.to_string(index=False))
    print(f"[게이트] {verdict} → {ROLL_CSV.relative_to(B)} · {SEL_CSV.relative_to(B)} · {KR_CSV.relative_to(B)}")


if __name__ == "__main__":
    main()
