# F14 — 운전표 v2. F11의 전일 운전표(naive_med4 · cap 20 · ±2h · 2단 '이동량 최소')를
# 세 축에서 넓힌다: ① 이동 폭 ±2h → ±4h ② 2단 목적식을 '이동량 최소' → 'TOU 전력량요금 최소'(1단 min 월최대는 그대로)
# ③ 익일 이월(내일로 미루기 — 일요일로·월 밖으로는 금지, 익일 계획은 받은 부하를 고정값으로 안고 다시 짠다).
# s는 F13이 보조 데이터에서 추정한 값(0.337)을 대표 결과으로, 0.255(로봇 1대 몫)·0.10(기존 가정)을 비교 행으로 둔다.
# 예측기·cap은 F11이 8월에서 고른 그대로(재선택 없음). 변형 선택은 8월에서만, 테스트 밖 달 4·5·7월은 선택 후보 고정, 테스트는 1회(--test는 로그 있으면 거부).
# 실행: python -X utf8 f14_schedule_v2.py --select   → table_f14_select.csv
#       python -X utf8 f14_schedule_v2.py --roll     → table_f14_rolling.csv
#       python -X utf8 f14_schedule_v2.py --test     → table_f14.csv · f14_plan_test.csv (1회)
#       python -X utf8 f14_schedule_v2.py --select --mutate N   (결함 재삽입 N=1..6 — self-check가 깨져야 정상, 산출물은 쓰지 않는다)
# 기존 table_f11*·table_k7*는 읽기 전용. 새 파일에만 쓴다.
import sys, hashlib, datetime, pathlib
import numpy as np, pandas as pd, pulp
from common import B, VA, TE, load
from closed_loop_core import fit_predictions, by_day, calendar, oracle, POL_P0, POL_P1, POL_P3
import f11_dayahead as F11
from f11b_twolayer import dedup_days
import k7_tariff_cost as K7

SEL_CSV, ROLL_CSV, TEST_CSV, PLAN_CSV = (B / "build/table_f14_select.csv", B / "build/table_f14_rolling.csv",
                                         B / "build/table_f14.csv", B / "build/f14_plan_test.csv")
TEST_LOG = B / "build/f14_test_read.log"
ROLL = [4, 5, 7, 8]                                   # 8월은 선택 월 — 기본요금(F15)용 청구 기준 최대를 같은 경로로 다시 잰다(선택에는 쓰지 않는다)
S_OLD, S_ONE = 0.10, 0.255
POL_V1 = "P5 전일 운전표 v1(±2h·이동량)"            # F11 재현(대조) — 8월 s=10%에서 table_f11_select와 같아야 한다
VARIANTS = {"A ±2h·TOU": (8, True, False), "B ±4h·TOU": (16, True, False), "C ±4h·TOU·익일이월": (16, True, True)}
OPTS = ["선택Ⅰ", "선택Ⅱ", "선택Ⅲ"]
MUT = 0                                                 # 결함 재삽입 번호(0 = 없음)
QUICK = False                                           # --quick: 8월 앞 10일 · s 2개 — 재삽입 시험 전용(산출물을 쓰지 않는다). 무결함 축약판이 먼저 통과해야 한다


# ===== 0. 고정 입력 — F11 선택(예측기·cap)과 F13 s_est =====
def f11_choice():
    T = pd.read_csv(B / "build/table_f11_select.csv", encoding="utf-8-sig")
    r = T[T["선택"]].iloc[0]
    assert r["예측기"] == "naive_med4", "F11 선택이 naive가 아니면 RF 전일 예측기가 필요하다 — 이 스크립트는 naive만 다룬다"
    return r["예측기"], float(r["cap"])


def s_est():
    S = pd.read_csv(B / "build/table_f13_s.csv", encoding="utf-8-sig")
    r = S[(S.구간 == "겹침 21일") & (S.추정량.str.startswith("가산 모형"))].iloc[0]
    return round(float(r["s_est"]), 3)


# ===== 1. TOU 단가 — k7과 같은 시간대 판정·요금표 =====
_T = K7.tariff()


def price(idx, opt="선택Ⅰ"):
    u = _T[_T["선택"] == opt].set_index("계절")
    return np.array([u.loc[K7.season(ts.month), K7.band(ts)] for ts in idx], float)


def cost(load_by_day, days, opt):
    return float(sum((o * 0.25 * price(g.index, opt)).sum() for o, g in zip(load_by_day, days)))


def oracle_L(g, s, L):
    """closed_loop_core.oracle과 같되 이동 폭 L을 받는다 — ±4h 변형의 하한은 ±4h 오라클이어야 한다."""
    y = g["y"].values
    m = pulp.LpProblem("oracleL", pulp.LpMinimize)
    Pk = pulp.LpVariable("Pk", 0); m += Pk
    rng = lambda t: range(max(0, t - L), min(95, t + L) + 1)
    fl = {(t, w): pulp.LpVariable(f"f_{t}_{w}", 0) for t in range(96) for w in rng(t)}
    for t in range(96):
        m += pulp.lpSum(fl[t, w] for w in rng(t)) == s * y[t]
    for w in range(96):
        m += (1 - s) * y[w] + pulp.lpSum(fl[t, w] for t in rng(w)) <= Pk
    m.solve(pulp.PULP_CBC_CMD(msg=0)); assert pulp.LpStatus[m.status] == "Optimal"
    return np.array([(1 - s) * y[w] + sum(pulp.value(fl[t, w]) for t in rng(w)) for w in range(96)])


POL_P3B = "P3b 오라클 ±4h(실측, LP)"


# ===== 2. 하루(+익일) 계획 LP =====
def plan2(f, s, cap, L, tou, pr, inh, f_next=None, pr_next=None):
    """반환 (F, G): F[t,w] 같은 날 이동 비율, G[t,w'] 익일 이동 비율(이월 없으면 0). 행 합 F+G = 1.
    1단 min Pk (오늘 총부하 = (1−s)f + inh + 유입 ≤ Pk; 이월이면 익일 총부하 = f_next + 유입 ≤ Pk도 함께)
    2단 Pk ≤ Pk*로 묶고 TOU면 Σ 단가×유입 최소(+ε·이동량), 아니면 이동량 최소(F11과 동일)."""
    F, G = np.eye(96), np.zeros((96, 96))
    if s == 0:
        return F, G
    carry = f_next is not None
    rng = lambda t: range(max(0, t - L), min(95, t + L) + 1)
    m = pulp.LpProblem("v2", pulp.LpMinimize)
    Pk = pulp.LpVariable("Pk", 0)
    fl = {(t, w): pulp.LpVariable(f"f_{t}_{w}", 0) for t in range(96) for w in rng(t)}
    gl = {(t, w): pulp.LpVariable(f"g_{t}_{w}", 0) for t in range(96) for w in rng(t)} if carry else {}
    for t in range(96):
        m += pulp.lpSum(fl[t, w] for w in rng(t)) + (pulp.lpSum(gl[t, w] for w in rng(t)) if carry else 0) == s * f[t]
    for w in range(96):
        m += (1 - s) * f[w] + inh[w] + pulp.lpSum(fl[t, w] for t in rng(w)) <= Pk
        if np.isfinite(cap) and MUT != 3:
            m += pulp.lpSum(fl[t, w] for t in rng(w) if t != w) <= cap
        if carry:
            m += f_next[w] + pulp.lpSum(gl[t, w] for t in rng(w)) <= Pk
            if np.isfinite(cap):
                m += pulp.lpSum(gl[t, w] for t in rng(w)) <= cap
    m += Pk
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    assert pulp.LpStatus[m.status] == "Optimal"
    pk = pulp.value(Pk)
    if MUT != 5:                                           # 재삽입 5: 2단이 1단 피크에 묶이지 않는다
        m += Pk <= pk + 1e-6 * max(1.0, pk)
    mv = pulp.lpSum(v for (t, w), v in fl.items() if t != w) + pulp.lpSum(gl.values())
    if MUT == 6:                                           # 재삽입 6: 단가 부호가 뒤집힌다(비싼 시간대로 몰기)
        pr, pr_next = -pr, (-pr_next if pr_next is not None else None)
    if tou:
        m.setObjective(pulp.lpSum(pr[w] * v for (t, w), v in fl.items() if t != w)
                       + (pulp.lpSum(pr_next[w] * v for (t, w), v in gl.items()) if carry else 0) + 1e-3 * mv)
    else:
        m.setObjective(mv)
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    assert pulp.LpStatus[m.status] == "Optimal"
    if MUT != 5:
        assert pulp.value(Pk) <= pk + 1e-4 * max(1.0, pk), "2단이 1단 피크를 깼다"
    for t in range(96):
        if s * f[t] > 1e-9:
            F[t, t] = 0.0
            for w in rng(t):
                F[t, w] = max(pulp.value(fl[t, w]), 0.0) / (s * f[t])
                if carry:
                    G[t, w] = max(pulp.value(gl[t, w]), 0.0) / (s * f[t])
            tot = F[t].sum() + G[t].sum()
            F[t] /= tot; G[t] /= tot
    return F, G


def can_carry(d, days_set):
    """익일 이월 허용: 다음 날이 평가 집합에 있고(완전한 날), 일요일이 아니고, 같은 달이다."""
    n = d + pd.Timedelta(days=1)
    if MUT == 2:
        return n in days_set
    return n in days_set and n.dayofweek != 6 and n.month == d.month


def pk_star(f, s, cap, L):
    """1단만 푸는 독립 LP — 검사 5의 기준값."""
    rng = lambda t: range(max(0, t - L), min(95, t + L) + 1)
    m = pulp.LpProblem("pk", pulp.LpMinimize)
    Pk = pulp.LpVariable("Pk", 0); m += Pk
    fl = {(t, w): pulp.LpVariable(f"q_{t}_{w}", 0) for t in range(96) for w in rng(t)}
    for t in range(96):
        m += pulp.lpSum(fl[t, w] for w in rng(t)) == s * f[t]
    for w in range(96):
        m += (1 - s) * f[w] + pulp.lpSum(fl[t, w] for t in rng(w)) <= Pk
        m += pulp.lpSum(fl[t, w] for t in rng(w) if t != w) <= cap
    m.solve(pulp.PULP_CBC_CMD(msg=0)); assert pulp.LpStatus[m.status] == "Optimal"
    return float(pulp.value(Pk))


# ===== 3. 한 달 실행 =====
def run_variant(days, fc, s, cap, L, tou, carry):
    """반환 (실현 부하 리스트, 이월 kWh, 무계획 일수, 이동 kWh). 실현: out_d = (1−s)y_d + (s·y_d)@F_d + 받은 이월(실측 기준)."""
    dset = {g.index[0].normalize() for g in days}
    outs, nop, carried, moved = [], 0, 0.0, 0.0
    inh_plan, inh_real = np.zeros(96), np.zeros(96)        # 어제 계획이 오늘로 보낸 양(예측 기준 / 실측 기준)
    for i, g in enumerate(days):
        d, y = g.index[0].normalize(), g["y"].values
        f = fc.get(d)
        pr = price(g.index)
        nxt = days[i + 1] if i + 1 < len(days) else None
        use_carry = carry and nxt is not None and can_carry(d, dset) and fc.get(nxt.index[0].normalize()) is not None
        if f is None:
            F, G = np.eye(96), np.zeros((96, 96)); nop += 1
        else:
            f = np.asarray(f, float)
            F, G = plan2(f, s, cap, L, tou, pr, inh_plan,
                         np.asarray(fc[nxt.index[0].normalize()], float) if use_carry else None,
                         price(nxt.index) if use_carry else None)
        out = (1 - s) * y + (s * y) @ F + inh_real
        outs.append(out)
        moved += float(((s * y)[:, None] * (F - np.diag(np.diag(F)))).sum() / 4)
        to_next_real, to_next_plan = (s * y) @ G, (s * (f if f is not None else y)) @ G
        carried += float(to_next_real.sum() / 4)
        if nxt is not None and (nxt.index[0].normalize() - d) == pd.Timedelta(days=1):
            inh_plan, inh_real = to_next_plan, to_next_real
        else:
            assert to_next_real.sum() < 1e-9, "다음 날이 평가 집합에 없는데 이월이 생겼다"
            inh_plan, inh_real = np.zeros(96), np.zeros(96)
    if MUT == 1:
        outs[0] = outs[0] * 0.9                             # 에너지 비보존 결함
    return outs, carried, nop, moved


def bill_max(days, outs):
    """청구 기준 월최대 — 요금적용전력은 중간·최대부하 시간대 최대수요전력만 대상(k7과 같은 판정, 경부하·일요일·공휴일 제외)."""
    v = [o[m].max() for o, g in zip(outs, days) if (m := np.array([K7.band(ts) != "경부하" for ts in g.index])).any()]   # 일요일·공휴일은 전부 경부하 — 건너뛴다
    return float(max(v))


def stats(days, outs):
    M = np.array(outs)
    wk = np.array([g.index[0].dayofweek < 5 for g in days])
    return float(M.max()), float(np.median(M.max(1)[wk]))


def table(days, fc, s, cap, label_extra=""):
    """한 s에서 P0·P1·P3·v1·A·B·C 행."""
    y0 = [g["y"].values * 1.0 for g in days]
    p0 = float(np.array(y0).max())
    rows = []
    def row(name, outs, carried=np.nan, nop=np.nan, moved=np.nan, L=np.nan):
        mx, wk = stats(days, outs)
        c0 = {o: cost(y0, days, o) for o in OPTS}; c1 = {o: cost(outs, days, o) for o in OPTS}
        return dict(s=s, 정책=name, 이동폭=L, 월최대=round(mx, 2), P0대비kW=round(mx - p0, 2), 평일일피크중앙=round(wk, 2),
                    **{f"전력량요금Δ_{o}": round(c1[o] - c0[o]) for o in OPTS}, 이동량kWh=round(moved, 1) if moved == moved else np.nan,
                    이월kWh=round(carried, 1) if carried == carried else np.nan, 무계획일=nop, 생산손실kWh=0.0)
    rows.append(row(POL_P0, y0))
    rows.append(row(POL_P1, [calendar(g, s) for g in days]))
    rows.append(row(POL_P3, [oracle(g, s) for g in days]))
    rows.append(row(POL_P3B, [oracle_L(g, s, 16) for g in days]))
    o, c, n, mv = run_variant(days, fc, s, cap, 8, False, False)
    rows.append(row(POL_V1, o, c, n, mv, 8))
    for name, (L, tou, carry) in VARIANTS.items():
        o, c, n, mv = run_variant(days, fc, s, cap, L, tou, carry)
        rows.append(row("P5v2 " + name, o, c, n, mv, L))
    return pd.DataFrame(rows), p0


def pick(T, s_head):
    """§3-1: s_est에서 월최대 최소 → 전력량요금(선택Ⅰ) 최소 → 이동 폭 작은 쪽. 후보는 A·B·C."""
    c = T[(T.s == s_head) & T.정책.str.startswith("P5v2")].copy()
    c["_L"] = c.이동폭
    best = c.sort_values(["월최대", "전력량요금Δ_선택Ⅰ", "_L"]).iloc[0]
    return best["정책"]


# ===== 4. 모드 =====
def forecasts(kw, days, stat="med"):
    D = F11.day_matrix(kw)
    return {g.index[0].normalize(): F11.naive(D, g.index[0].normalize(), stat) for g in days}, D


def month_frame(kw, m):
    start = pd.Timestamp(2021, m, 1)
    k = kw[(kw.index >= start) & (kw.index < start + pd.offsets.MonthBegin(1))]
    return pd.DataFrame(dict(y=k.values), index=k.index)


def do_select():
    pred, cap = f11_choice(); sh = s_est()
    kw = load()["kw"][:"2021-08-31"]                       # 테스트 구간은 메모리에서 잘라 낸다
    VAL, TEST = fit_predictions(); del TEST
    days = by_day(VAL)
    if QUICK:
        days = days[:10]
    fc, D = forecasts(kw, days)
    Ts = []
    for s in ([S_OLD, sh] if QUICK else [S_OLD, S_ONE, sh]):
        T, _ = table(days, fc, s, cap)
        Ts.append(T); print(f"  8월 s={s} 완료", flush=True)
    T = pd.concat(Ts, ignore_index=True)
    sel = pick(T, sh)
    T["선택"] = (T.정책 == sel)
    T["s_est"] = sh; T["예측기"] = pred; T["cap"] = cap
    if not (MUT or QUICK):                                   # 검사에서 멈춰도 계산을 잃지 않게 — 검사 통과 전에는 정식 파일명이 아니다
        T.to_csv(B / "build/_f14_select_pending.csv", index=False, encoding="utf-8-sig")
        print(T.drop(columns=["s_est", "예측기", "cap"]).to_string(index=False), flush=True)
    check(VAL, kw, days, fc, D, T, cap, sh)
    if MUT or QUICK:
        print(f"[{'재삽입 ' + str(MUT) if MUT else '축약판 무결함'}] self-check 통과" + (" — 검사가 이 결함을 못 본다" if MUT else "")); return
    T.to_csv(SEL_CSV, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 260)
    print(f"\n[8월 선택 · s∈{{{S_OLD}, {S_ONE}, {sh}(s_est)}} · 예측기 {pred} · cap {cap:.0f}]")
    print(T.drop(columns=["s_est", "예측기", "cap"]).to_string(index=False))
    print(f"\n[선택] {sel} (s_est={sh}: 월최대 → 전력량요금Ⅰ → 이동 폭)")
    print(f"→ {SEL_CSV.relative_to(B)}")


def do_roll():
    pred, cap = f11_choice(); sh = s_est()
    S = pd.read_csv(SEL_CSV, encoding="utf-8-sig"); sel = S[S.선택].iloc[0]["정책"]
    L, tou, carry = VARIANTS[sel.replace("P5v2 ", "")]
    kw = load()["kw"][:"2021-08-31"]
    rows = []
    for m in ROLL:
        df = month_frame(kw, m)
        days = by_day(df)
        fc, D = forecasts(kw, days)
        dm, drop = dedup_days(days, D)
        for s in [S_OLD, S_ONE, sh]:
            y0 = [g["y"].values * 1.0 for g in dm]; p0 = float(np.array(y0).max())
            out = {POL_P0: y0, POL_P1: [calendar(g, s) for g in dm], POL_P3: [oracle(g, s) for g in dm], POL_P3B: [oracle_L(g, s, 16) for g in dm]}
            o, c, n, mv = run_variant(dm, fc, s, cap, 8, False, False); out[POL_V1] = o
            o2, c2, n2, mv2 = run_variant(dm, fc, s, cap, L, tou, carry); out["P5v2 " + sel.replace("P5v2 ", "")] = o2
            for k, v in out.items():
                mx, wk = stats(dm, v)
                rows.append(dict(월=m, s=s, 정책=k, 월최대=round(mx, 2), P0대비kW=round(mx - p0, 2), 평일일피크중앙=round(wk, 2),
                                 청구기준월최대=round(bill_max(dm, v), 2),
                                 **{"전력량요금Δ_선택Ⅰ": round(cost(v, dm, "선택Ⅰ") - cost(y0, dm, "선택Ⅰ"))},
                                 이월kWh=round(c2, 1) if k.startswith("P5v2") else np.nan, 평가일=len(dm), 복제제외일=drop))
            assert np.array(out[POL_V1]).max() >= np.array(out[POL_P3]).max() - 1e-6, "v1 오라클 하한 위반"
            if not carry:
                assert np.array(o2).max() >= np.array(out[POL_P3B if L == 16 else POL_P3]).max() - 1e-6, "v2 오라클 하한 위반"
            tot_y = sum(g["y"].sum() for g in dm)
            assert abs(sum(x.sum() for x in o2) - tot_y) < 1e-6 and abs(sum(x.sum() for x in o) - tot_y) < 1e-6, "월 에너지 불보존"
        print(f"  롤링 {m}월 완료(평가 {len(dm)}일, 복제 제외 {drop}일)", flush=True)
    R = pd.DataFrame(rows); R["선택변형"] = sel
    R.to_csv(ROLL_CSV, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 260)
    print(R.to_string(index=False)); print(f"→ {ROLL_CSV.relative_to(B)}")


def refuse_test(sel_csv=SEL_CSV, log=TEST_LOG):
    if not pathlib.Path(sel_csv).exists():
        raise SystemExit(f"[거부] {sel_csv} 없음 — 먼저 --select")
    if pathlib.Path(log).exists() and MUT != 4:
        raise SystemExit(f"[거부] {log} 가 이미 있다 — 테스트는 1회만 읽는다. 재실행하려면 사람이 로그를 지우고 6장 검증 이력에 기록할 것")
    S = pd.read_csv(sel_csv, encoding="utf-8-sig")
    return S[S.선택].iloc[0], hashlib.sha256(pathlib.Path(sel_csv).read_bytes()).hexdigest()


S_TEST = None                                           # --test-at s: 설계 문서 — s_kr 한 값만, 별도 기록 파일로 1회


def do_test(dry=False):
    """dry=True: 같은 코드 경로를 8월(검증)로 시운전한다 — 로그·정식 산출물을 쓰지 않고 v1 대조는 F11 8월 값으로 한다."""
    global TEST_CSV, PLAN_CSV, TEST_LOG
    if S_TEST is not None:
        TEST_CSV, PLAN_CSV, TEST_LOG = B / "build/table_f14_testat.csv", B / "build/f14_plan_testat.csv", B / "build/f14_testat_read.log"
    if dry:
        S = pd.read_csv(SEL_CSV, encoding="utf-8-sig"); r = S[S.선택].iloc[0]
        TEST_CSV, PLAN_CSV = B / "build/_f14_dry.csv", B / "build/_f14_dry_plan.csv"
    else:
        r, sha = refuse_test(log=TEST_LOG)
    pred, cap = f11_choice(); sh = s_est()
    if not dry:
      TEST_LOG.write_text(f"{datetime.datetime.now().isoformat(timespec='seconds')} · 변형={r['정책']} · s_est={sh} · s={S_TEST or '기본 3행'} · 예측기={pred} · cap={cap} · "
                        f"table_f14_select.csv SHA256 {sha}\n", encoding="utf-8")
      print(f"[로그 먼저 기록] {TEST_LOG.name}: {TEST_LOG.read_text(encoding='utf-8').strip()}")
    kw = load()["kw"] if not dry else load()["kw"][:"2021-08-31"]
    VALd, TEST = fit_predictions()
    if dry:
        TEST = VALd
    days = by_day(TEST)
    fc, D = forecasts(kw, days)
    sel = r["정책"]; L, tou, carry = VARIANTS[sel.replace("P5v2 ", "")]
    rows, plans = [], []
    f11 = pd.read_csv(B / "build/table_f11.csv", encoding="utf-8-sig")
    for s in (S_TEST or [S_OLD, S_ONE, sh]):
        y0 = [g["y"].values * 1.0 for g in days]; p0 = float(np.array(y0).max())
        p3 = [oracle(g, s) for g in days]; p3b = [oracle_L(g, s, 16) for g in days]
        o1, c1, n1, mv1 = run_variant(days, fc, s, cap, 8, False, False)
        o2, c2, n2, mv2 = run_variant(days, fc, s, cap, L, tou, carry)
        for k, v, c, n, mv in [(POL_P0, y0, 0, 0, 0), (POL_P1, [calendar(g, s) for g in days], np.nan, 0, np.nan), (POL_P3, p3, np.nan, 0, np.nan),
                               (POL_P3B, p3b, np.nan, 0, np.nan), (POL_V1, o1, c1, n1, mv1), (sel, o2, c2, n2, mv2)]:
            pref = np.array(p3b if (k == sel and L == 16) else p3).max()
            mx, wk = stats(days, v)
            rows.append(dict(s=s, 정책=k, 월최대kW=round(mx, 2), P0대비kW=round(mx - p0, 2), 청구기준월최대=round(bill_max(days, v), 2),
                             P1대비kW=round(mx - stats(days, [calendar(g, s) for g in days])[0], 2),
                             예측의가치=round((p0 - mx) / (p0 - pref), 3) if k.startswith("P5") and p0 > pref else np.nan,
                             **{f"전력량요금Δ_{o}": round(cost(v, days, o) - cost(y0, days, o)) for o in OPTS},
                             이동량kWh=round(mv, 1) if mv == mv else np.nan, 이월kWh=round(c, 1) if c == c else np.nan, 무계획일=n, 생산손실kWh=0.0))
        if not carry:
            assert np.array(o2).max() >= np.array(p3b if L == 16 else p3).max() - 1e-6
        assert abs(sum(x.sum() for x in o2) - sum(x.sum() for x in y0)) < 1e-6, "테스트 에너지 불보존"
        if np.isclose(s, S_OLD):                            # v1 대조 — F11 테스트 값과 같아야 한다(같은 정의)
            if dry:
                f11s = pd.read_csv(B / "build/table_f11_select.csv", encoding="utf-8-sig")
                ref = f11s[(f11s.s == s) & (f11s.정책 == "P5 전일 운전표") & (f11s.예측기 == pred) & (f11s.cap == cap)]["월최대"].iloc[0]
            else:
                ref = f11[np.isclose(f11.s, s) & (f11.정책 == "P5 전일 운전표")]["월최대kW"].iloc[0]
            assert abs(stats(days, o1)[0] - ref) < 0.01, f"v1 테스트 {stats(days, o1)[0]:.2f} ≠ F11 {ref}"
        for g, o in zip(days, o2):
            plans.append(pd.DataFrame({"s": s, "실측": g["y"].values, "실현": o.round(3)}, index=g.index))
    E = pd.DataFrame(rows); E["s_est"] = sh; E["변형"] = sel; E["예측기"] = pred; E["cap"] = cap
    E["라벨"] = (f"s={S_TEST[0]} = 한국 단조공장 실측 s_kr(약점극복 PRD §3-4 추가 판독 1회) · " if S_TEST else "") + ("s=0.10 가정 · s=0.255 추정(보조 라인 로봇 1대 몫) · s=s_est 추정(보조 라인 가산 모형, 겹침 21일) · "
               "예측기·cap은 F11이 8월에서 고정 · 변형은 8월에서 선택 · 테스트 1회 · 에너지·생산 보존(차단 없음) · 전력량요금은 k7 요금표(2023-11-09)")
    E.to_csv(TEST_CSV, index=False, encoding="utf-8-sig")
    pd.concat(plans).to_csv(PLAN_CSV, encoding="utf-8-sig")
    pd.set_option("display.width", 260)
    print(f"[테스트 1회 · 9/1~14 · {sel}]"); print(E.drop(columns=["라벨", "s_est", "예측기", "cap", "변형"]).to_string(index=False))
    print(f"→ {TEST_CSV.relative_to(B)} · {PLAN_CSV.relative_to(B)}")


# ===== 5. self-check — 결함을 되살리면 깨진다 (--mutate N으로 재삽입 시험) =====
def check(VAL, kw, days, fc, D, T, cap, sh):
    rng = np.random.default_rng(0)
    # 1. 에너지 보존 — 전 변형 × 전 s, 월 합(이월 포함)과 이월 없는 변형의 일 합
    for name, (L, tou, carry) in list(VARIANTS.items()) + [("v1", (8, False, False))]:
        for s in ([S_OLD, sh] if QUICK else [S_OLD, S_ONE, sh]):
            o, c, n, mv = run_variant(days, fc, s, cap, L, tou, carry)
            assert abs(sum(x.sum() for x in o) - sum(g["y"].sum() for g in days)) < 1e-6, f"{name} s={s}: 월 에너지 불보존"
            if not carry:
                assert np.allclose([x.sum() for x in o], [g["y"].sum() for g in days], atol=1e-6), f"{name} s={s}: 일 에너지 불보존"
            else:
                if c == 0:
                    print(f"  [대조] {name} s={s}: 이월이 한 번도 선택되지 않았다(LP가 이월을 유리하다고 보지 않음)")
    # 2. 이월 금지 규칙 — 일요일로·월 밖으로 이월이 없다
    dset = {g.index[0].normalize() for g in days}
    for d in dset:
        n = d + pd.Timedelta(days=1)
        if n.dayofweek == 6 or n.month != d.month:
            assert not can_carry(d, dset), f"{d.date()} → {n.date()} 이월 허용"
    # 3. 받는 슬롯 증가량 ≤ cap (예측 f 기준)
    g = days[5]; f = np.asarray(fc[g.index[0].normalize()], float)
    F, G = plan2(f, sh, cap, 16, True, price(g.index), np.zeros(96))
    inflow = (sh * f) @ (F - np.diag(np.diag(F)))
    assert inflow.max() <= cap + 1e-6, f"받는 슬롯 증가량 {inflow.max():.3f} > cap {cap}"
    # 4. s=0 → 실현 = 실측
    o, _, _, _ = run_variant(days, fc, 0.0, cap, 16, True, True)
    assert np.allclose(np.array(o), np.array([g["y"].values for g in days]))
    # 5. 2단(TOU)이 1단 피크를 안 깬다 — **예측 f 기준**으로 본다. 1단 단독 LP(독립 구현)의 최적 피크와 TOU 계획의 예측 피크가 같아야 한다.
    #    (첫 실행은 이 검사를 실측 y로 실현한 월최대로 걸었다가 27분 뒤 거짓 실패했다 — 1단은 f 위의 피크만 보장한다.
    #     2단 목적식이 다르면 같은 f 피크에서도 흐름이 달라 실현 피크는 달라질 수 있고, 그것은 결과다.)
    for i in (2, 6, 9):
        g = days[i]; f = fc.get(g.index[0].normalize())
        if f is None:
            continue
        f = np.asarray(f, float)
        pk = pk_star(f, sh, cap, 16)
        F, _ = plan2(f, sh, cap, 16, True, price(g.index), np.zeros(96))
        got = float(((1 - sh) * f + (sh * f) @ F).max())
        assert abs(got - pk) < 1e-3 * max(1.0, pk), f"{g.index[0].date()}: TOU 계획 예측 피크 {got:.3f} ≠ 1단 최적 {pk:.3f}"
        # 5b. TOU 2단은 예측 f 위에서 이동량 2단보다 비싸면 안 된다(같은 피크 묶음 아래 비용 최소화)
        Fm, _ = plan2(f, sh, cap, 16, False, price(g.index), np.zeros(96))
        pr = price(g.index)
        c_tou, c_mv = float((pr * ((1 - sh) * f + (sh * f) @ F)).sum()), float((pr * ((1 - sh) * f + (sh * f) @ Fm)).sum())
        assert c_tou <= c_mv + 1e-6 * c_mv, f"{g.index[0].date()}: TOU 계획 예측 비용 {c_tou:,.1f} > 이동량 계획 {c_mv:,.1f}"
    o_mv, *_ = run_variant(days, fc, sh, cap, 16, False, False); o_tou, *_ = run_variant(days, fc, sh, cap, 16, True, False)
    print(f"  [정보] ±4h 실현 — 이동량 목적 월최대 {stats(days, o_mv)[0]:.2f} · 전력량요금Ⅰ {cost(o_mv, days, '선택Ⅰ'):,.0f} / "
          f"TOU 목적 {stats(days, o_tou)[0]:.2f} · {cost(o_tou, days, '선택Ⅰ'):,.0f}")
    # 6. v1 대조 — 8월 s=10% P5 v1 = table_f11_select의 naive_med4·cap20 P5 (축약판은 달 전체가 아니라 건너뛴다)
    f11 = pd.read_csv(B / "build/table_f11_select.csv", encoding="utf-8-sig")
    ref = f11[(f11.s == S_OLD) & (f11.정책 == "P5 전일 운전표") & (f11.예측기 == "naive_med4") & (f11.cap == cap)]["월최대"].iloc[0]
    got = T[(T.s == S_OLD) & (T.정책 == POL_V1)]["월최대"].iloc[0]
    assert QUICK or abs(got - ref) < 0.01, f"v1 8월 {got} ≠ F11 {ref}"
    for k in ([] if QUICK else [POL_P0, POL_P1, POL_P3]):
        assert abs(T[(T.s == S_OLD) & (T.정책 == k)]["월최대"].iloc[0] - f11[(f11.s == S_OLD) & (f11.정책 == k)]["월최대"].iloc[0]) < 0.01, k
    # 7. 오라클 하한 — 이동 폭이 같은 오라클과 비교한다(±4h 변형을 ±2h 오라클과 비교하면 거짓 위반). 이월 변형은 하루 오라클보다 낮을 수 있어 단언하지 않는다
    for s in T.s.unique():
        p3, p3b = T[(T.s == s) & (T.정책 == POL_P3)]["월최대"].iloc[0], T[(T.s == s) & (T.정책 == POL_P3B)]["월최대"].iloc[0]
        assert p3b <= p3 + 1e-6, "±4h 오라클이 ±2h 오라클보다 높다"
        for _, r in T[(T.s == s) & T.정책.str.startswith("P5")].iterrows():
            if "이월" in r.정책:
                continue
            assert r.월최대 >= (p3 if r.이동폭 == 8 else p3b) - 1e-6, f"s={s} {r.정책}: 오라클 하한 위반"
    # 8. 인과성 — 예측이 D−1 18:00 이후 kw에 의존하지 않는다(naive는 ≥7일 전만 본다)
    for d in [days[i].index[0].normalize() for i in (0, 5, 9)]:
        kw2 = kw.copy(); late = kw2.index >= d - F11.CUT
        kw2[late] = kw2[late].values[rng.permutation(late.sum())] * rng.uniform(0.3, 2.0, late.sum())
        a, b = F11.naive(D, d, "med"), F11.naive(F11.day_matrix(kw2), d, "med")
        assert (a is None and b is None) or np.allclose(a, b), f"{d.date()}: 예측이 미래 kw에 의존"
    # 9. 테스트 1회 강제
    tmp, tsel = B / "build/_f14_dummy.log", B / "build/_f14_dummy.csv"
    tmp.write_text("x", encoding="utf-8"); T.to_csv(tsel, index=False, encoding="utf-8-sig")
    try:
        try:
            refuse_test(tsel, tmp); raise AssertionError("로그가 있는데 --test가 거부되지 않는다")
        except SystemExit:
            pass
    finally:
        tmp.unlink(); tsel.unlink()
    # 10. 시간대 단가 — k7과 같은 판정
    assert K7.band(pd.Timestamp("2021-08-05 14:00")) == "최대부하" and K7.band(pd.Timestamp("2021-08-08 14:00")) == "경부하"
    print("self-check OK (1 에너지 보존 · 2 이월 금지 · 3 cap · 4 s=0 · 5 TOU 대조 · 6 v1=F11 · 7 오라클 · 8 인과 · 9 테스트 1회 · 10 단가)")


def main():
    global MUT, QUICK
    args = sys.argv[1:]
    if "--quick" in args:
        QUICK = True; args.remove("--quick")
    if "--mutate" in args:
        MUT = int(args[args.index("--mutate") + 1]); args = [a for a in args if a not in ("--mutate", str(MUT))]
    global S_TEST
    if "--test-at" in args:
        i = args.index("--test-at"); S_TEST = [float(args[i + 1])]; args = args[:i] + ["--test"] + args[i + 2:]
    mode = [a for a in args if a in ("--select", "--roll", "--test")]
    args = [a for a in args if a != "--dry"] + (["--dry"] if "--dry" in args else [])
    assert len(mode) == 1, "실행 인자: --select | --roll | --test [--mutate N]"
    assert (MUT == 0 and not QUICK) or mode[0] == "--select", "--mutate·--quick은 --select에서만(산출물을 쓰지 않는다)"
    if mode[0] == "--test" and "--dry" in args:
        do_test(dry=True); print("[시운전] 테스트 경로 8월로 통과 — 산출물은 build/_f14_dry*.csv"); return
    {"--select": do_select, "--roll": do_roll, "--test": do_test}[mode[0]]()


if __name__ == "__main__":
    main()
