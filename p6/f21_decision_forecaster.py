# F21 — 결정 기준 예측기 선택. 사전등록 prereg_F21_F22_20261006.md.
# 운전표 v2 B(±4h·TOU·cap 20)는 그대로 두고 예측 dict fc만 바꿔 끼운다. 후보 C0 naive_med4 · C1 유사일 kNN(k=4) ·
# C2 C0·C1 평균 · C3 RF 테스트 밖 달 재학습. MAE가 아니라 실현 월 최대로, 테스트 밖 4·5·7·8월 × s 3개 = 12칸에서 고른다.
# 실행: python -X utf8 f21_decision_forecaster.py                → build/table_f21_rolling.csv · table_f21_select.csv
#       python -X utf8 f21_decision_forecaster.py --mutate N     (결함 재삽입 1..7, 7월·s_kr 축약판 — 깨져야 정상, 산출물 안 씀)
#       python -X utf8 f21_decision_forecaster.py --quick        (무결함 축약판 — 재삽입 전에 먼저 통과해야 한다)
#       python -X utf8 f21_decision_forecaster.py --test --dry   (테스트 경로를 8월로 시운전) / --test (기준 통과 시 1회)
# 기존 table_f1*·table_k*·table_w*는 읽기 전용. 새 파일에만 쓴다.
import sys, hashlib, datetime, pathlib, re
import numpy as np, pandas as pd
from sklearn.ensemble import RandomForestRegressor
from common import B, load
from closed_loop_core import by_day
import f11_dayahead as F11
import f14_schedule_v2 as F14
import f18_breakeven as F18
from f11b_twolayer import dedup_days
import k7_tariff_cost as K7

PREREG, PREREG_SHA = B / "prereg_F21_F22_20261006.md", "1fcfc84fb0bcecbbb8a7d6f97b7bd2b4f8d29f5c14bde0f1b662e6c615ba1bff"
GATE_DOC = B.parent / "KAMP_제6회_PRD_AI운영경로_20261006.md"
ROLL_CSV, SEL_CSV = B / "build/table_f21_rolling.csv", B / "build/table_f21_select.csv"
TEST_CSV, TEST_LOG, DRY_LOG = B / "build/table_f21_testat.csv", B / "build/f21_test_read.log", B / "build/f21_test_dry.log"
MONTHS, SENS, SEL_M = [2, 4, 5, 7, 8], [3, 6], [4, 5, 7, 8]
CAP, LW, K = 20.0, 16, 4
CANDS = ["C0 naive_med4", "C1 유사일 kNN", "C2 C0·C1 평균", "C3 RF 롤링"]
C0_TEST = 189.66                                       # build/f14_testat_read.log 평가분(s_kr) — prereg §3-4
MUT = 0
PICKS = []                                             # (대상일, 고른 날들) — 검사 1·2가 읽는다


# ===== 1. 날 단위 재료 =====
def dtype(d):
    return "일휴" if (d.dayofweek == 6 or d.date() in K7.HOLI) else ("토" if d.dayofweek == 5 else "평일")


def day_feats(q0, D):
    """{날짜: (생산 합, 4구간 합 ×4, 기온 평균, 직전 같은 요일 최대 시각)} — 완전한 날만."""
    out = {}
    for d in D:
        g = q0.loc[d:d + pd.Timedelta(hours=23, minutes=45)]
        p = g["생산량"].values
        prev = D.get(d - pd.Timedelta(days=7))
        prev = prev if prev is not None else D.get(d - pd.Timedelta(days=14))
        out[d] = np.array([p.sum(), p[:24].sum(), p[24:48].sum(), p[48:72].sum(), p[72:].sum(), g["기온"].mean(),
                           float(np.argmax(prev)) if prev is not None else np.nan])
    return out


def scale(Fx, start):
    X = np.array([v for d, v in Fx.items() if d < start])
    sd = np.nanstd(X, 0)
    return np.where((sd > 0) & np.isfinite(sd), sd, 1.0)


def knn(D, Fx, d, sd):
    lim = d - pd.Timedelta(days=2) if MUT != 1 else d + pd.Timedelta(days=31)        # 재삽입 1: 미래 날 허용
    cand, seen = [], set()
    for x in sorted(D):
        if x > lim or x == d or dtype(x) != dtype(d):
            continue
        key = D[x].tobytes()
        if key in seen and MUT != 2:                                                  # 재삽입 2: 복제군 중복 허용
            continue
        seen.add(key); cand.append(x)
    if not cand:
        return None
    fd = Fx[d]
    dist = []
    for x in cand:
        fx = Fx[x]
        z = (fx[:6] - fd[:6]) / sd[:6]
        c = abs(fx[6] - fd[6]); c = min(c, 96 - c) / sd[6] if np.isfinite(c) else 0.0
        dist.append(float(np.sqrt(np.nansum(z ** 2) + c ** 2)))
    pick = [cand[i] for i in np.argsort(dist, kind="stable")[:K]]
    PICKS.append((d, pick))
    return np.median([D[x] for x in pick], 0)


def rf_rolling(q0, kw, start):
    """2021-01-15 ~ start 전 완전한 날로 학습(F11 RFDayAhead와 같은 특징·하이퍼파라미터, 학습 기간만 롤링)."""
    cut = start if MUT != 7 else start + pd.offsets.MonthBegin(1)                    # 재삽입 7: 대상 월을 학습에 섞는다
    days = [d for d in F11.day_matrix(kw) if pd.Timestamp("2021-01-15") <= d < cut]
    X = F11.rf_features(q0, kw, days)
    ok = X[["lag1w", "lag2w"]].notna().all(1)
    X, y = X[ok], kw.reindex(X.index)[ok]
    m = RandomForestRegressor(max_depth=20, random_state=42, n_jobs=1).fit(X, y)
    m.train_max_ = X.index.max()
    return m


def rf_point(m, q0, kw, d):
    X = F11.rf_features(q0, kw, [d])
    return None if X[["lag1w", "lag2w"]].isna().any().any() else m.predict(X)


def forecasts(q0, kw, days, start):
    D = F11.day_matrix(kw)
    Fx = day_feats(q0, D)
    sd = scale(Fx, start)
    rf = rf_rolling(q0, kw, start)
    fc = {c: {} for c in CANDS}
    for g in days:
        d = g.index[0].normalize()
        a, b = F11.naive(D, d, "med"), knn(D, Fx, d, sd)
        fc[CANDS[0]][d], fc[CANDS[1]][d] = a, b
        fc[CANDS[2]][d] = (a + b) / 2 if (a is not None and b is not None) else (a if a is not None else b)
        fc[CANDS[3]][d] = rf_point(rf, q0, kw, d)
    return fc, D, rf


# ===== 2. 지표 =====
def hit(fc, days):
    h = [abs(int(np.argmax(f)) - int(np.argmax(g["y"].values))) <= 4 for g in days
         if g.index[0].dayofweek < 5 and (f := fc.get(g.index[0].normalize())) is not None]
    return float(np.mean(h)) if h else np.nan


def month_rows(q0, kw, m, dedup, slist):
    start = pd.Timestamp(2021, m, 1)
    days = by_day(F14.month_frame(kw, m))
    D0 = F11.day_matrix(kw)
    drop = 0
    if dedup:
        days, drop = dedup_days(days, D0)
    if not days:
        return []
    fc, _, rf = forecasts(q0, kw, days, start)
    assert rf.train_max_ < start, f"{m}월 C3 학습이 대상 월에 닿았다"
    rows = []
    for s in slist:
        p3b = float(np.array([F14.oracle_L(g, s, LW) for g in days]).max())
        res = {}
        for c in CANDS:
            o, _, nop, _ = F14.run_variant(days, fc[c], s, CAP if MUT != 3 else 10.0, LW, True, False)   # 재삽입 3: cap 변경
            if MUT == 4 and c == CANDS[1]:
                o = [x * 0.97 for x in o]                                                   # 재삽입 4: 에너지 비보존
            assert np.allclose([x.sum() for x in o], [g["y"].sum() for g in days], atol=1e-6), f"{m}월 s={s} {c}: 일 에너지 불보존"
            res[c] = (float(np.array(o).max()), nop)
        c0 = res[CANDS[0]][0]
        for c in CANDS:
            mx, nop = res[c]
            rows.append(dict(월=m, 구분="선택 오염(F11 선택 월)" if m == 8 else "롤링", 복제처리="제외" if dedup else "포함(민감도)",
                             s=s, 후보=c, 월최대=round(mx, 2), C0대비kW=round(mx - c0, 2), 사후최적P3b=round(p3b, 2),
                             격차감소=round((c0 - mx) / (c0 - p3b), 3) if c0 - p3b > 1e-9 else np.nan,
                             적중률_평일1h=round(hit(fc[c], days), 3), 예측MAE=round(F11.fc_mae(fc[c], days), 2),
                             무계획일=nop, 평가일=len(days), 복제제외일=drop))
    return rows


# ===== 3. 선택·통과 기준 =====
def select(R, sk):
    E = R[(R.복제처리 == "제외") & R.월.isin(SEL_M)].copy()
    E["순위"] = E.groupby(["월", "s"])["월최대"].rank(method="average")
    A = E.groupby("후보")["순위"].mean().reindex(CANDS)
    best = min(CANDS, key=lambda c: (round(A[c], 9), CANDS.index(c)))
    w = lambda c, s: E[(E.후보 == c) & np.isclose(E.s, s)].set_index("월")["월최대"]
    sel_k, c0_k = w(best, sk), w(CANDS[0], sk)
    worse = int(sum((E[E.후보 == best].set_index(["월", "s"])["월최대"] - E[E.후보 == CANDS[0]].set_index(["월", "s"])["월최대"]) > 0.005))
    cond = dict(선택_아님_C0=best != CANDS[0], 평균_1kW_이상_개선=bool(sel_k.mean() <= c0_k.mean() - 1.0),
                어느달도_1kW_넘게_악화없음=bool(((sel_k - c0_k) <= 1.0).all()), 악화칸_3이하=worse <= 3)
    verdict = "실패" if best == CANDS[0] else ("통과" if all(cond.values()) else "부분")
    S = pd.DataFrame([dict(후보=c, 평균순위=round(A[c], 3), s_kr_4개월평균월최대=round(w(c, sk).mean(), 2),
                           s_kr_C0대비=round(w(c, sk).mean() - c0_k.mean(), 2), 선택=(c == best)) for c in CANDS])
    S["판정"] = verdict
    S["조건"] = " · ".join(f"{k}={v}" for k, v in cond.items()) + f" · 악화칸={worse}/12"
    return S, verdict


# ===== 4. self-check — 결함을 되살리면 깨진다 =====
def check(R, kw, sk):
    assert kw.index.max() < pd.Timestamp("2021-09-01"), "테스트 구간이 메모리에 있다"                 # 재삽입 6
    for d, pick in PICKS:                                                                   # 재삽입 1
        assert all(x <= d - pd.Timedelta(days=2) for x in pick), f"{d.date()}: kNN이 D−1 18:00 이후의 날을 골랐다 {pick}"
    D = F11.day_matrix(kw)
    for d, pick in PICKS:                                                                   # 재삽입 2
        assert len({D[x].tobytes() for x in pick}) == len(pick), f"{d.date()}: kNN이 복제군에서 같은 부하를 두 번 골랐다"
    F = pd.read_csv(B / "build/table_f18_breakeven.csv", encoding="utf-8-sig")              # 재삽입 3
    n = 0
    for _, r in R[R.후보 == CANDS[0]].iterrows():
        f = F[(F.월 == r.월) & np.isclose(F.s, r.s) & (F.정책 == "P5v2 B ±4h·TOU") & (F.복제처리 == r.복제처리)]
        if len(f):
            assert abs(f["월최대"].iloc[0] - r.월최대) < 0.01, f"{r.월}월 s={r.s} C0 {r.월최대} ≠ f18 {f['월최대'].iloc[0]}"
            n += 1
    assert n >= 1, "C0 대조 행이 하나도 없다"
    assert (R.월 != 9).all()
    print(f"self-check OK (테스트 미사용 · kNN 인과 {len(PICKS)}건 · 복제 중복 0 · C0=f18 {n}행 · 에너지 보존 · C3 학습 컷)")


def prereg_ok():
    h = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    if h != (PREREG_SHA if MUT != 5 else "0" * 64):                                       # 재삽입 5
        raise SystemExit(f"[거부] 사전등록 SHA {h[:16]}… ≠ 등록값")


# ===== 5. 테스트 (기준 통과 시 1회) =====
def do_test(dry):
    S = pd.read_csv(SEL_CSV, encoding="utf-8-sig")
    best, verdict = S[S.선택].iloc[0]["후보"], S["판정"].iloc[0]
    sk = F18.s_kr()
    if not dry:
        prd = GATE_DOC.read_text(encoding="utf-8")
        if verdict != "통과" or not re.search(r"F21 롤링 판정: \*\*통과", prd):
            raise SystemExit("[거부] F21 통과 기준 통과 기록이 실행 기록 문서에 없다")
        if not DRY_LOG.exists():
            raise SystemExit("[거부] --test --dry 시운전 로그가 없다")
        if TEST_LOG.exists():
            raise SystemExit("[거부] 테스트는 1회만 읽는다 — f21_test_read.log가 이미 있다")
    q0 = load()
    kw = q0["kw"] if not dry else q0["kw"][:"2021-08-31"]
    m = 8 if dry else 9
    days = by_day(F14.month_frame(kw, m))
    if not dry:
        days = [g for g in days if g.index[0] <= pd.Timestamp("2021-09-14")]
    else:
        days, _ = dedup_days(days, F11.day_matrix(kw))
    fc, _, _ = forecasts(q0, kw, days, pd.Timestamp(2021, m, 1))
    rows = []
    for c in dict.fromkeys([CANDS[0], best]):
        o, _, nop, _ = F14.run_variant(days, fc[c], sk, CAP, LW, True, False)
        rows.append(dict(s=sk, 후보=c, 월최대kW=round(float(np.array(o).max()), 2), 적중률_평일1h=round(hit(fc[c], days), 3),
                         예측MAE=round(F11.fc_mae(fc[c], days), 2), 무계획일=nop, 구간="8월 시운전" if dry else "테스트 9/1~14"))
    E = pd.DataFrame(rows)
    ref = 200.59 if dry else C0_TEST
    assert abs(E[E.후보 == CANDS[0]]["월최대kW"].iloc[0] - ref) < 0.01, f"C0 {E['월최대kW'].iloc[0]} ≠ 기준 {ref}"
    if dry:
        DRY_LOG.write_text(f"{datetime.datetime.now().isoformat(timespec='seconds')} · 8월 시운전 통과 · {E.to_dict('records')}\n", encoding="utf-8")
        print(E.to_string(index=False)); print(f"[시운전] → {DRY_LOG.name}"); return
    E.to_csv(TEST_CSV, index=False, encoding="utf-8-sig")                                    # 먼저 저장, 그 뒤 출력
    TEST_LOG.write_text(f"{datetime.datetime.now().isoformat(timespec='seconds')} · 선택={best} · s={sk} · "
                        f"table_f21_testat.csv SHA256 {hashlib.sha256(TEST_CSV.read_bytes()).hexdigest()}\n", encoding="utf-8")
    print(E.to_string(index=False)); print(f"→ {TEST_CSV.relative_to(B)} · {TEST_LOG.name}")


def main():
    global MUT
    args = sys.argv[1:]
    if "--mutate" in args:
        MUT = int(args[args.index("--mutate") + 1])
    prereg_ok()
    if "--test" in args:
        do_test("--dry" in args); return
    quick = MUT or "--quick" in args
    sk = F18.s_kr()
    q0 = load()
    q0 = q0[q0.index < "2021-09-01"] if MUT != 6 else q0                                     # 재삽입 6: 테스트 구간을 메모리에 둔다
    kw = q0["kw"]
    slist = [sk, 0.337] if quick else [0.10, sk, 0.337]                                      # 축약판도 0.337 — 7월 s_kr에선 cap이 안 묶여 재삽입 3이 안 보였다(1차)
    rows = []
    for m, dd in ([(7, True)] if quick else [(m, True) for m in MONTHS] + [(m, False) for m in SENS]):
        rows += month_rows(q0, kw, m, dd, slist)
        print(f"  {m}월 완료", flush=True)
    R = pd.DataFrame(rows)
    check(R, kw, sk)
    if quick:
        print(f"[{'재삽입 ' + str(MUT) if MUT else '축약판 무결함'}] self-check 통과" + (" — 검사가 이 결함을 못 본다" if MUT else ""))
        print(R[["후보", "월최대", "적중률_평일1h", "예측MAE"]].to_string(index=False)); return
    S, verdict = select(R, sk)
    R.to_csv(ROLL_CSV, index=False, encoding="utf-8-sig"); S.to_csv(SEL_CSV, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(R.pivot_table(index=["복제처리", "월", "s"], columns="후보", values="월최대").round(2).to_string())
    print(R[R.복제처리 == "제외"].pivot_table(index="월", columns="후보", values=["적중률_평일1h", "예측MAE"]).round(3).to_string())
    print(S.to_string(index=False))
    print(f"[게이트] {verdict} → {ROLL_CSV.relative_to(B)} · {SEL_CSV.relative_to(B)}")


if __name__ == "__main__":
    main()
