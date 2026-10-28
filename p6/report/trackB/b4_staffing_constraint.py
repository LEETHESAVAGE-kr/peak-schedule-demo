# Track B §3 후속 — "근무 칸만 받음 허용" 제약을 넣은 최종 운전표(W2)의 감축량 재측정. 제출 후 추가 분석(사후 민감도).
# 제출 코드(f24_scenario_schedule.py 등)는 import만 하고 고치지 않는다. LP는 plan_scen을 이 파일에 복사해 받음 금지 칸만 더했다.
# 산출물은 이 폴더(trackB/_b4_*.csv·json)에만 쓴다 — build/ 에는 아무것도 쓰지 않는다.
# ⚠ 테스트 9/1~14를 다시 계산한다. 사전등록(F24)의 1회 판독과 별개인 사후 민감도이며, 보고서 숫자를 바꾸지 않는다.
# 실행: python -X utf8 p6/report/trackB/b4_staffing_constraint.py
import sys, json, pathlib, datetime
import numpy as np, pandas as pd, pulp

HERE = pathlib.Path(__file__).resolve().parent
P6 = HERE.parents[1]
sys.path.insert(0, str(P6))
import f24_scenario_schedule as F24
from common import load
from closed_loop_core import by_day
import f11_dayahead as F11
import f14_schedule_v2 as F14
import f18_breakeven as F18
import f21_decision_forecaster as F21
from f11b_twolayer import dedup_days

BAN = set()          # 현재 날의 받음 금지 슬롯(0..95). run_scen이 날마다 plan_scen을 부르기 전에 바뀐다.


def plan_scen_ban(Ys, s, cap, L, pr, risk):
    """F24.plan_scen과 같은 LP + (t≠w, w∈BAN)인 이동 변수를 만들지 않는다(받음 금지). 나머지는 한 글자도 바꾸지 않았다."""
    Ys = np.asarray(Ys, float); J = len(Ys); pi = np.full(J, 1.0 / J)
    X = np.eye(96)
    if s == 0:
        return X
    rng = lambda t: range(max(0, t - L), min(95, t + L) + 1)
    live = [t for t in range(96) if (s * Ys[:, t]).max() > 1e-9]
    m = pulp.LpProblem("f24b", pulp.LpMinimize)
    x = {(t, w): pulp.LpVariable(f"x_{t}_{w}", 0) for t in live for w in rng(t) if t == w or w not in BAN}
    for t in live:
        m += pulp.lpSum(x[t, w] for w in rng(t) if (t, w) in x) == 1
    inflow = lambda j, w: pulp.lpSum(s * Ys[j, t] * x[t, w] for t in rng(w) if (t, w) in x)
    stay = lambda j, w: (1 - s) * Ys[j, w] + (s * Ys[j, w] if w not in live else 0)
    if risk == "max":
        Pk = pulp.LpVariable("Pk", 0); P = [Pk] * J
    else:
        P = [pulp.LpVariable(f"P_{j}", 0) for j in range(J)]
    for j in range(J):
        for w in range(96):
            m += stay(j, w) + inflow(j, w) <= P[j]
            if np.isfinite(cap):
                m += pulp.lpSum(s * Ys[j, t] * x[t, w] for t in rng(w) if t != w and (t, w) in x) <= cap
    obj1 = P[0] if risk == "max" else pulp.lpSum(pi[j] * P[j] for j in range(J))
    m += obj1
    m.solve(pulp.PULP_CBC_CMD(msg=0)); assert pulp.LpStatus[m.status] == "Optimal"
    v = pulp.value(obj1)
    m += obj1 <= v + 1e-6 * max(1.0, v)
    ybar = pi @ Ys
    mv = pulp.lpSum(s * ybar[t] * x[t, w] for (t, w) in x if t != w)
    m.setObjective(pulp.lpSum(pr[w] * s * ybar[t] * x[t, w] for (t, w) in x if t != w) + 1e-3 * mv)
    m.solve(pulp.PULP_CBC_CMD(msg=0)); assert pulp.LpStatus[m.status] == "Optimal"
    for t in live:
        X[t, t] = 0.0
        for w in rng(t):
            if (t, w) in x:
                X[t, w] = max(pulp.value(x[t, w]) or 0.0, 0.0)
        X[t] /= X[t].sum()
    return X


# ---- 받음 금지 칸 정의 (모두 D−1에 알 수 있는 정보만) ----
STAFF = load()["공장인원"]


def ban_window(d, lo=7, hi=20):
    """고정 시간창: lo:00~hi:00 밖은 받음 금지(모든 요일)."""
    return {t for t in range(96) if not (lo * 4 <= t < hi * 4)}


def ban_staff(d, thr):
    """같은 요일 직전 4주, 슬롯별 공장인원 평균 < thr 이면 받음 금지(당일 값 미사용)."""
    prev = [d - pd.Timedelta(days=7 * k) for k in range(1, 5)]
    M = [STAFF.loc[p:p + pd.Timedelta(minutes=15 * 95)].values for p in prev]
    M = [v for v in M if len(v) == 96]
    if not M:
        return set(range(96))
    mu = np.mean(M, 0)
    return {t for t in range(96) if mu[t] < thr}


VARIANTS = {
    "제약 없음(제출 W2 재현)": lambda d: set(),
    "시간창 07~20시": lambda d: ban_window(d, 7, 20),
    "직전 4주 인원≥0.5 칸": lambda d: ban_staff(d, 0.5),
    "직전 4주 인원≥1.0 칸": lambda d: ban_staff(d, 1.0),
}


def run_w2(days, D, Fx, sd, s, fc0, banf):
    """F24.run_scen(W2 = 'AB','mean')을 날마다 BAN을 바꿔 가며 호출한다."""
    global BAN
    outs, fb, nop, banned = [], 0, 0, []
    for g in days:
        BAN = banf(g.index[0].normalize())
        banned.append(len(BAN))
        o, n0, f0, _ = F24.run_scen([g], D, Fx, sd, "AB", "mean", s, F24.CAP, fc0)
        if BAN and f0 == 0:                               # 금지 칸에 들어온 부하가 없어야 한다(제약이 실제로 걸렸는지)
            inc = (o[0] - g["y"].values)[sorted(BAN)]
            assert inc.max() <= 1e-6, f"{g.index[0].date()}: 받음 금지 칸에 +{inc.max():.3f}kW"
        outs += o; fb += f0; nop += n0
    return outs, fb, nop, float(np.mean(banned))


def evaluate(days, outs):
    y = [g["y"].values for g in days]
    d = pd.DataFrame(dict(day=[g.index[0].normalize() for g in days],
                          실측=[v.max() for v in y], 실현=[o.max() for o in outs],
                          받음kWh=[np.clip(o - v, 0, None).sum() / 4 for o, v in zip(outs, y)]))
    d["변화율"] = d.실현 / d.실측 - 1
    return d


def main():
    F24.plan_scen = plan_scen_ban                     # run_scen이 모듈 전역 plan_scen을 부른다 — 복사본으로 바꿔 끼움(파일은 그대로)
    sk = F18.s_kr()
    q0 = load(); kw = q0["kw"]
    rows, daily = [], []
    # 테스트 9/1~14 (do_test의 비시운전 경로와 같은 입력 구성)
    days_t = [g for g in by_day(F14.month_frame(kw, 9)) if g.index[0] <= pd.Timestamp("2021-09-14")]
    D = F11.day_matrix(kw)
    Fx = F21.day_feats(q0, D); sd = F21.scale(Fx, pd.Timestamp(2021, 9, 1))
    fc0 = {g.index[0].normalize(): F11.naive(D, g.index[0].normalize(), "med") for g in days_t}
    for name, banf in VARIANTS.items():
        o, fb, nop, nb = run_w2(days_t, D, Fx, sd, sk, fc0, banf)
        e = evaluate(days_t, o); wd = e[e.day.dt.dayofweek < 5]
        rows.append(dict(구간="테스트 9/1~14", 제약=name, 월최대=round(float(e.실현.max()), 2), 기존=float(e.실측.max()),
                         감축kW=round(float(e.실측.max() - e.실현.max()), 2),
                         평일하락일=f"{int((wd.실현 < wd.실측 - 1e-9).sum())}/{len(wd)}", 평일변화율중앙=round(float(wd.변화율.median()), 4),
                         받음kWh=round(float(e.받음kWh.sum()), 1), 금지칸평균=round(nb, 1), C0대체일=fb, 무계획일=nop))
        daily.append(e.assign(제약=name))
        print(rows[-1], flush=True)
    # 테스트 밖 달(요금적용전력을 정한 7월 포함) — month_rows의 W2 경로와 같은 입력 구성(복제일 제외)
    q_tr = q0[q0.index < "2021-09-01"]; kw_tr = q_tr["kw"]; D2 = F11.day_matrix(kw_tr)
    base = {2: 195.0, 4: 199.0, 5: 192.0, 7: 222.0, 8: 218.0}           # table_w3_gate.csv 현행 월최대
    for m in [2, 4, 5, 7, 8]:
        days, _ = dedup_days(by_day(F14.month_frame(kw_tr, m)), D2)
        Fx2 = F21.day_feats(q_tr, D2); sd2 = F21.scale(Fx2, pd.Timestamp(2021, m, 1))
        fc02 = {g.index[0].normalize(): F11.naive(D2, g.index[0].normalize(), "med") for g in days}
        for name, banf in VARIANTS.items():
            o, fb, nop, nb = run_w2(days, D2, Fx2, sd2, sk, fc02, banf)
            mx = float(np.array(o).max())
            rows.append(dict(구간=f"{m}월", 제약=name, 월최대=round(mx, 2), 기존=base[m], 감축kW=round(base[m] - mx, 2),
                             금지칸평균=round(nb, 1), C0대체일=fb, 무계획일=nop))
            print(rows[-1], flush=True)
    R = pd.DataFrame(rows)
    # 재현 검사: 제약 없음 = 제출값(테스트 184.19, table_f24_rolling W2)
    ref = {"테스트 9/1~14": 184.19, "2월": 181.33, "4월": 181.95, "5월": 172.86, "7월": 201.45, "8월": 195.45}
    chk = {k: float(R[(R.구간 == k) & (R.제약 == "제약 없음(제출 W2 재현)")].월최대.iloc[0]) for k in ref}
    bad = {k: (chk[k], ref[k]) for k in ref if abs(chk[k] - ref[k]) > 0.01}
    R.to_csv(HERE / "_b4_staffing.csv", index=False, encoding="utf-8-sig")
    pd.concat(daily).to_csv(HERE / "_b4_staffing_daily.csv", index=False, encoding="utf-8-sig")
    json.dump({"생성": datetime.datetime.now().isoformat(timespec="seconds"), "s": sk, "재현검사_불일치": bad,
               "결과": R.to_dict("records")}, open(HERE / "_b4_staffing.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    pd.set_option("display.width", 250)
    print(R.to_string(index=False))
    print("재현 검사:", "통과" if not bad else f"불일치 {bad}")


if __name__ == "__main__":
    main()
