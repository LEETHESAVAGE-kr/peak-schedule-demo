# 폐루프 코어 — f9_closed_loop.py에서 분리. f9·f10이 같은 예측·정책 정의를 쓰게 한 곳에 둔다.
# 이 모듈은 import 시 아무것도 실행하지 않는다. 예측 적합은 fit_predictions()를 불러야 돈다.
# 분리 수용 기준: 분리 전후 build/table_f9.csv·table_f9_select.csv·f9_loads.csv 바이트 동일 + f9 check() 통과.
import pandas as pd, numpy as np, pulp
from sklearn.ensemble import RandomForestRegressor
from common import B3, TR, VA, TE, load, frame

H, T0, ALPHA = 4, 190, 0.975                        # +60분 · 운영 임계 190kW · 채택 α(F8 §11-9) — 여기서 다시 고르지 않는다
L = 8                                               # 이동 폭 ±8창 = ±2h (f5.py와 동일)
S_ROWS = [0.05, 0.10, 0.255]                        # 가정 시나리오: 낮음 · 중간(대표 결과 후보) · 보조 라인 상한
S_SEL = 0.10                                        # 8월 규칙 선택에 쓰는 s
DANGA = {"선택I": 7220, "선택II": 8320, "선택III": 9810}   # 산업용(을) 고압A 기본요금 원/kW·월 (2023-11-09, 4장 부록 출처)
R6_NOTE = " · 원 단위는 정상상태 가정 — 같은 정책을 연중 운영해 요금적용전력 산정 월이 전부 같은 폭으로 내려갈 때만 성립. 이 데이터의 9월(204kW)은 7·8월(222·218kW) 아래라 9월 한 달의 감소는 실제 청구서에서 0원"   # 래칫(요금적용전력 = 직전 12개월 해당 월 최대 중 최대)
S_NOTE = "8월 상단은 2겹 교차 보정(반월 교차) · 테스트 상단은 8월 전체로 보정(f8과 동일)"


# ===== 1. 예측 — f8.py와 같은 적합. 8월 상단은 2겹 교차 보정(8월 안에서 보정·평가가 같은 표본이 되지 않게) =====
def qtl(r, a):
    n = len(r)
    return np.sort(r)[min(int(np.ceil((n + 1) * a)), n) - 1]


def fit_predictions():
    """(VAL, TEST) — 열 y·pred·up. TEST를 반환한다는 것은 테스트를 읽는다는 뜻이다(호출 쪽이 봉인을 책임진다)."""
    q0 = load()
    d = frame(q0, H)
    tr, va, te = d[TR], d[VA], d[TE]
    m = RandomForestRegressor(max_depth=20, random_state=42, n_jobs=-1).fit(tr[B3], tr["kw"])
    pv, pt = m.predict(va[B3]), m.predict(te[B3])
    half = len(tr) // 2
    ma = RandomForestRegressor(max_depth=20, random_state=42, n_jobs=1).fit(tr[B3][:half], tr["kw"][:half])
    ms = RandomForestRegressor(max_depth=10, random_state=42, n_jobs=1).fit(tr[B3][half:], np.abs(tr["kw"].values[half:] - ma.predict(tr[B3][half:])))
    sv, st = np.maximum(ms.predict(va[B3]), 1e-3), np.maximum(ms.predict(te[B3]), 1e-3)
    z = (va["kw"].values - pv) / sv
    up_te = pt + qtl(z, ALPHA) * st                                     # 테스트 상단 = f8의 up975와 같아야 한다
    fold = (va.index.day > 15).astype(int)                              # 8/1~15 ↔ 8/16~31
    up_va = np.where(fold == 0, pv + qtl(z[fold == 1], ALPHA) * sv, pv + qtl(z[fold == 0], ALPHA) * sv)
    VAL = pd.DataFrame(dict(y=va["kw"].values, pred=pv, up=up_va), index=va.index)
    TEST = pd.DataFrame(dict(y=te["kw"].values, pred=pt, up=up_te), index=te.index)
    return VAL, TEST


# ===== 2. 정책 =====
def by_day(df):
    return [g for _, g in df.groupby(df.index.normalize()) if len(g) == 96]


def causal(g, s, sig, est, rule, guard="T0", return_hat=False):
    """롤링 재배치 — 인과적으로 아는 것만 쓴다. 시각 k(슬롯 k 시작)에는 슬롯 ≤ k+H의 예측만 있다.
    · 앞당김(V1만): 시각 k에 새로 드러난 슬롯 r=k+H가 경보면, 아직 오지 않은 k+1..r−1(−45분까지) 중 들어갈 자리로 옮긴다.
    · 이월(V1·V2): 앞당기지 못한 경보 슬롯 k는 시각 k에 k+1..k+H(+60분까지, 예측이 있는 범위) 중 들어갈 자리로 미룬다.
    · 들어갈 자리 = 후보 중 예측 총부하가 가장 낮은 곳(설계 규칙). guard가 그 자리를 거른다 — **못 거르면 옮기지 않는다**(제자리 가동):
        T0      = 받은 뒤 예측 총부하 < 임계(190kW)여야 옮긴다(보수적)
        improve = 받은 뒤 예측 총부하 < 원 슬롯의 예측 총부하여야 옮긴다(예측상 개선되는 이동만)
      강제 배치는 없다 — 기한에 몰아넣는 1차 구현이 한 슬롯에 블록 둘을 쌓아 185→230.9kW를 만들었다(수용 기준 2 위반).
      ±2h 상한 안이지만 실제 쓸 수 있는 폭은 예측 지평(+60분)이 묶는다(−45분~+60분).
    sig: 경보·후보 채점 신호(up=상단, pred=점 예측) · est: 옮길 양의 추정 · 실현 부하는 실측 s·y로 채점한다(같은 날 안, 일 합 보존).
    return_hat=True면 (out, hat) — hat[k]는 시각 k까지 확정된 이동만 반영한다(슬롯 w로의 이동은 시각 < w에만 일어난다)."""
    y, f, e = g["y"].values, g[sig].values, g[est].values
    out, hat = y * 1.0, f * 1.0                                    # 실현 부하 · 예측 총부하(예정 이동 반영)
    pending = set()

    def move(t0, cands):
        mh, mr = s * e[t0], s * y[t0]
        cands = [w for w in cands if 0 <= w <= 95]
        if not cands:
            return False
        w = min(cands, key=lambda w: hat[w])
        if not (hat[w] + mh < (T0 if guard == "T0" else hat[t0])):
            return False
        hat[t0] -= mh; out[t0] -= mr; hat[w] += mh; out[w] += mr
        return True

    for k in range(-H, 96):
        r = k + H                                                   # 시각 k에 새로 드러나는 슬롯
        if 0 <= r <= 95 and hat[r] >= T0:
            if not (rule == "V1" and s > 0 and move(r, range(max(k + 1, 0), r))):
                pending.add(r)
        if k >= 0 and k in pending:                                 # 슬롯 k 시작 — 앞당기지 못했으면 이월을 시도
            if s > 0:
                move(k, range(k + 1, min(k + H, 95) + 1))
            pending.discard(k)
    return (out, hat) if return_hat else out


def shed(g, s, sig):
    """보조 데이터 없음 — s·블록·이동 폭을 모르면 가능한 조치는 차단뿐. 경보 슬롯의 s·y를 끊는다(생산 손실)."""
    y, f = g["y"].values, g[sig].values
    cut = f >= T0
    return np.where(cut, (1 - s) * y, y), float((s * y * cut).sum())


def calendar(g, s):
    """평일 08~17시가 위험하다는 것만 안다. 08:00~09:45 → −2h, 16:00~17:45 → +2h, 가운데는 못 빠져나간다."""
    y = g["y"].values
    if g.index[0].dayofweek >= 5:
        return y * 1.0
    out = y * 1.0
    for w in range(32, 40):
        out[w] -= s * y[w]; out[w - L] += s * y[w]
    for w in range(64, 72):
        out[w] -= s * y[w]; out[w + L] += s * y[w]
    return out


def oracle(g, s):
    """실측을 알고 하루를 통째로 푸는 LP — 달성 가능한 하한. 이동 가능 부하 s·y_t를 ±L창 안에서 연속량으로 배분한다."""
    y = g["y"].values
    m = pulp.LpProblem("oracle", pulp.LpMinimize)
    Pk = pulp.LpVariable("Pk", 0)
    m += Pk
    rng = lambda t: range(max(0, t - L), min(95, t + L) + 1)
    fl = {(t, w): pulp.LpVariable(f"f_{t}_{w}", 0) for t in range(96) for w in rng(t)}
    for t in range(96):
        m += pulp.lpSum(fl[t, w] for w in rng(t)) == s * y[t]
    for w in range(96):
        m += (1 - s) * y[w] + pulp.lpSum(fl[t, w] for t in rng(w)) <= Pk
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    assert pulp.LpStatus[m.status] == "Optimal"
    return np.array([(1 - s) * y[w] + sum(pulp.value(fl[t, w]) for t in rng(w)) for w in range(96)])


POL_P0 = "P0 현행"
POL_P1 = "P1 달력 규칙"
POL_P2 = "P2 예측 상단 기반(본선)"
POL_P3 = "P3 오라클(실측, LP)"
POL_SHED = "P2′ 차단(보조 없음)"
POL_P3B = "P3b 완전정보·같은 인과 창"   # 진단: P2의 창(−45~+60분)에 실측을 넣는다 → 격차를 '예측 오차'와 '예측 지평'으로 가른다


def run(df, s, rule, est, guard):
    days = by_day(df)
    out = {POL_P0: [g["y"].values * 1.0 for g in days],
           POL_P1: [calendar(g, s) for g in days],
           "P2a 점 예측 기반": [causal(g, s, "pred", "pred", rule, guard) for g in days],
           POL_P2: [causal(g, s, "up", est, rule, guard) for g in days],
           POL_P3B: [causal(g, s, "y", "y", rule, guard) for g in days],
           POL_P3: [oracle(g, s) for g in days]}
    sh = [shed(g, s, "up") for g in days]
    out[POL_SHED] = [v for v, _ in sh]
    lost = sum(e for _, e in sh) / 4                                # kW·15min → kWh
    return days, out, lost


def summarize(days, out):
    wk = np.array([g.index[0].dayofweek < 5 for g in days])
    R = {}
    for k, v in out.items():
        M = np.array(v)
        R[k] = dict(기간최대=M.max(), 일피크중앙=np.median(M.max(1)), 평일일피크중앙=np.median(M.max(1)[wk]))
    return R
