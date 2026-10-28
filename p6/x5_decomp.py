# X5 — 외부 이전 실패의 원인 분해 (외부이전 재조사 PRD §7-2, Phase 1). **비블라인드 진단 — 성능 주장 근거로 쓰지 않는다.**
# 이미 판독한 공장-월만 쓴다: A사 설계 달(2·4·5·7·8월, 9월 없음) · 한국 단조 2곳 4~9월 · UCI 철강 2~12월.
# korea_factory의 나머지 8곳과 HIPE는 보류 데이터라 읽지 않는다(재삽입 5가 이를 검사한다).
# 공장-월마다 같은 단위(현행 월 최대 대비 %)로:
#   엔진 상한 = P3b(실측을 아는 ±4h 사후 최적) − P0
#   설계 손실 = P5*(같은 v2 계획식에 실측 투입 · 같은 cap·TOU 2단) − P3b
#   예측 손실 = C0(직전 4주 중앙값 한 줄 → v2) − P5*          · 합 = C0 − P0 (항등식 검사)
#   W1(직전 4주 시나리오 평균 LP, 외부에서 돌 수 있는 최종 엔진 계열)도 같이 싣는다.
#   구조 지표(피크 시각 적중·주간 반복·첨두성·야간·주말 비중) · 이동 폭 ±2/±4/±6h 민감도 · 휴일표 유무(단조·철강).
# 실행: python -X utf8 x5_decomp.py            → build/table_x_decomp.csv · build/table_x_decomp_sens.csv · build/x5_run.log
#       python -X utf8 x5_decomp.py --quick    (Forge_1 8월 · A사 7월 · 철강 단위 검사만, 산출물 안 씀)
#       python -X utf8 x5_decomp.py --mutate N (결함 재삽입 1 누설 · 2 휴일 누락 · 3 단위 · 4 시간대 · 5 보류 데이터 접근 — 깨져야 정상)
import sys, datetime
import numpy as np, pandas as pd
from common import B, load
from closed_loop_core import by_day
import f11_dayahead as F11
import f14_schedule_v2 as F14
import f19_kr_blind as F19
import k7_tariff_cost as K7
import f24_scenario_schedule as F24
from f11b_twolayer import dedup_days

OUT, OUT_S, LOG = B / "build/table_x_decomp.csv", B / "build/table_x_decomp_sens.csv", B / "build/x5_run.log"
S = 0.1295                                     # 대표 비중(s_kr) — 모든 공장에 같은 값
LS = {8: "±2h", 16: "±4h", 24: "±6h"}
HOL18 = pd.to_datetime(["2018-01-01", "2018-02-15", "2018-02-16", "2018-02-17", "2018-03-01", "2018-05-05", "2018-05-07",
                        "2018-05-22", "2018-06-06", "2018-06-13", "2018-08-15", "2018-09-23", "2018-09-24", "2018-09-25",
                        "2018-09-26", "2018-10-03", "2018-10-09", "2018-12-25"]).date   # 2018 한국 공휴일(대체·지방선거 포함)
HOLDOUT = {"Cement_1", "Cement_2", "Metal_1", "Metal_2", "Metal_3", "Paper", "Steel_1", "Steel_2"}
MUT = 0


# ===== 1. 자료 =====
def forge(f):
    if MUT == 5:
        f = "Metal_1"                                                           # 재삽입 5: 보류 공장을 읽는다
    assert f not in HOLDOUT, f"{f}: 보류 데이터 — 사전등록 전 접근 금지"
    q = F19.series(f)
    if MUT == 4:
        q.index = q.index + pd.Timedelta(hours=9)                               # 재삽입 4: UTC로 착각해 KST로 9시간 민다
    return q


def steel():
    import f12_external_steel as F12
    kw, _ = F12.load_steel()
    if MUT == 3:
        kw = kw / 4.0                                                           # 재삽입 3: kWh/15분을 kW로 착각
    return kw


def main_kw():
    kw = load()["kw"]
    kw = kw[kw.index < "2021-09-01"]
    assert kw.index.max() < pd.Timestamp("2021-09-01"), "테스트 구간이 메모리에 있다"
    return kw


def month_days(kw, y, m, dedup=False, D=None):
    st = pd.Timestamp(y, m, 1)
    k = kw[(kw.index >= st) & (kw.index < st + pd.offsets.MonthBegin(1))]
    days = by_day(pd.DataFrame(dict(y=k.values), index=k.index))
    days = [g for g in days if g["y"].notna().all()]
    if dedup:
        days, _ = dedup_days(days, D)
    return days


# ===== 2. 구조 지표 (이 달 평가일만, 예측은 D−1 18:00에 아는 같은 요일 직전 4주 중앙값) =====
def metrics(days, D, fc, holi):
    hit, hit_wd, auto_wd, err = [], [], [], []
    for g in days:
        d, y = g.index[0].normalize(), g["y"].values
        wd = d.weekday() < 5 and d.date() not in holi
        f = fc.get(d)
        if f is not None:
            h = abs(int(np.argmax(f)) - int(np.argmax(y))) <= 4
            hit.append(h); err.append(np.abs(f - y).mean() / max(y.mean(), 1e-9))
            if wd:
                hit_wd.append(h)
        p = d - pd.Timedelta(days=7)
        if wd and p in D:
            auto_wd.append(abs(int(np.argmax(D[p])) - int(np.argmax(y))) <= 4)
    Y = np.concatenate([g["y"].values for g in days]); idx = pd.DatetimeIndex(np.concatenate([g.index.values for g in days]))
    top = Y >= np.quantile(Y, 0.99)
    night = (idx.hour >= 22) | (idx.hour < 8); wkend = idx.weekday >= 5
    return dict(적중률_전체일=np.mean(hit) if hit else np.nan, 적중률_평일=np.mean(hit_wd) if hit_wd else np.nan,
                주간반복_평일=np.mean(auto_wd) if auto_wd else np.nan, 예측오차_평균대비=np.mean(err) if err else np.nan,
                첨두성_최대대평균=Y.max() / Y.mean(), 상위1pct_분산일비=len(set(idx[top].normalize())) / len(days),
                야간비중=Y[night].sum() / Y.sum(), 주말비중=Y[wkend].sum() / Y.sum(), 평가일=len(days))


# ===== 3. 한 공장-월 =====
def run_fm(name, days, D, cap, holi, Ls=(8, 16, 24), hol_off=None):
    fc = {g.index[0].normalize(): F11.naive(D, g.index[0].normalize(), "med") for g in days}
    fy = {g.index[0].normalize(): g["y"].values for g in days}
    p0 = max(g["y"].max() for g in days)
    K7.HOLI = holi
    r = dict(P0=p0)
    for L in Ls:
        r[f"P3b_{L}"] = float(np.array([F14.oracle_L(g, S, L) for g in days]).max())
        r[f"C0_{L}"] = float(np.array(F14.run_variant(days, fc, S, cap, L, True, False)[0]).max())
    r["P5s"] = float(np.array(F14.run_variant(days, fy, S, cap, 16, True, False)[0]).max())
    r["W1"] = float(np.array(F24.run_scen(days, D, None, None, "A", "mean", S, cap, fc)[0]).max())
    if hol_off is not None:
        K7.HOLI = hol_off
        r["C0_휴일표없음"] = float(np.array(F14.run_variant(days, fc, S, cap, 16, True, False)[0]).max())
    m = metrics(days, D, fc, holi)
    return r, m


def rows_for(fac, y, m, r, met, s_meas, engine_note):
    p0 = r["P0"]; pc = lambda v: (v / p0 - 1) * 100
    up, des, pred = pc(r["P3b_16"]), pc(r["P5s"]) - pc(r["P3b_16"]), pc(r["C0_16"]) - pc(r["P5s"])
    assert abs(up + des + pred - pc(r["C0_16"])) < 1e-9, "분해 항등식 깨짐"
    row = dict(공장=fac, 연=y, 월=m, s=S, 현행월최대=round(p0, 3),
               엔진상한_pct=round(up, 3), 엔진상한_대비s=round(-up / (S * 100), 3),
               설계손실_pct=round(des, 3), 예측손실_C0_pct=round(pred, 3), C0_pct=round(pc(r["C0_16"]), 3),
               W1_pct=round(pc(r["W1"]), 3), 예측손실_W1_pct=round(pc(r["W1"]) - pc(r["P5s"]), 3),
               C0_현행초과=bool(r["C0_16"] > p0 + 0.005), W1_현행초과=bool(r["W1"] > p0 + 0.005),
               이동가능분_측정=s_meas, 엔진=engine_note)
    row.update({k: (round(v, 4) if isinstance(v, float) else v) for k, v in met.items()})
    sens = dict(공장=fac, 연=y, 월=m, **{f"P3b_{LS[L]}_pct": round(pc(r[f"P3b_{L}"]), 3) for L in LS if f"P3b_{L}" in r},
                **{f"C0_{LS[L]}_pct": round(pc(r[f"C0_{L}"]), 3) for L in LS if f"C0_{L}" in r})
    if "C0_휴일표없음" in r:
        sens["C0_±4h_휴일표없음_pct"] = round(pc(r["C0_휴일표없음"]), 3)
    return row, sens, r


# ===== 4. self-check =====
def check(raw):
    K = pd.read_csv(B / "build/table_f19_kr.csv", encoding="utf-8-sig"); K = K[np.isclose(K.s, S)]
    G = pd.read_csv(B / "build/table_f19b_kr_diag.csv", encoding="utf-8-sig")
    W = pd.read_csv(B / "build/table_f24_kr.csv", encoding="utf-8-sig")
    R = pd.read_csv(B / "build/table_f24_rolling.csv", encoding="utf-8-sig"); R = R[(R.복제처리 == "제외") & np.isclose(R.s, S)]
    n = 0
    for (fac, m), r in raw.items():
        if fac.startswith("Forge"):
            k = lambda p: float(K[(K.공장 == fac) & (K.월 == m) & (K.정책 == p)]["월최대"].iloc[0])
            assert abs(r["C0_16"] - k(F19.V2)) < 0.01, f"{fac} {m}월 C0 {r['C0_16']:.3f} ≠ f19 {k(F19.V2):.3f}"
            assert abs(r["P3b_16"] - k(F14.POL_P3B)) < 0.01, f"{fac} {m}월 P3b ≠ f19"
            g = G[(G.공장 == fac) & (G.월 == m)].iloc[0]
            assert abs(r["P5s"] - g.v2_실측입력) < 0.006, f"{fac} {m}월 P5* {r['P5s']:.3f} ≠ f19b {g.v2_실측입력}"
            w = float(W[(W.공장 == fac) & (W.월 == m) & (W.후보 == "W1")]["월최대"].iloc[0])
            assert abs(r["W1"] - w) < 0.01, f"{fac} {m}월 W1 {r['W1']:.3f} ≠ f24 {w:.3f}"
            n += 1
        elif fac == "A사":
            t = lambda c: R[(R.월 == m) & (R.후보 == c)].iloc[0]
            assert abs(r["C0_16"] - t("C0").월최대) < 0.01, f"A사 {m}월 C0 {r['C0_16']:.2f} ≠ f24 {t('C0').월최대}"
            assert abs(r["W1"] - t("W1").월최대) < 0.01, f"A사 {m}월 W1 ≠ f24"
            assert abs(r["P3b_16"] - t("C0").사후최적P3b) < 0.01, f"A사 {m}월 P3b ≠ f24"
            n += 1
        elif fac == "UCI 철강":
            assert r["P0"] <= 628.72 + 1e-6
    return n


def main():
    global MUT
    a = sys.argv[1:]
    if "--mutate" in a:
        MUT = int(a[a.index("--mutate") + 1]); F24.MUT = 1 if MUT == 1 else 0   # 재삽입 1: 시나리오에 당일 실측(누설)
    quick = bool(MUT) or "--quick" in a
    t0 = datetime.datetime.now()
    rows, sens, raw = [], [], {}
    hol21 = K7.HOLI
    # 철강 단위 검사(연최대 = f12 P0 628.72)
    ks = steel()
    assert abs(ks.max() - 628.72) < 0.01, f"철강 연최대 {ks.max():.2f} ≠ 628.72kW — 단위(kWh/15분 ×4) 오류"
    # 단조 2곳
    for f in (["Forge_1"] if quick else F19.FORGES):
        q = forge(f); D = F19.complete_days(q)
        for m in ([8] if quick else F19.MONTHS):
            days = [pd.DataFrame(dict(y=v), index=pd.date_range(d, periods=96, freq="15min")) for d, v in D.items() if d.month == m]
            r, met = run_fm(f, days, D, F19.cap_for(q, m), F19.HOL19 if MUT != 2 else hol21, hol_off=hol21)
            raw[(f, m)] = r
            sm = float(pd.read_csv(B / "build/table_f17_kr_flex.csv", encoding="utf-8-sig").set_index("공장").loc[f, "간헐부하비중"])
            a1, b1, _ = rows_for(f, 2019, m, r, met, sm, "F14 v2(C0)·F24 W1 — 블라인드 판독 끝난 공장")
            rows.append(a1); sens.append(b1); print(f"  {f} {m}월 {datetime.datetime.now():%H:%M:%S}", flush=True)
    # A사 설계 달(복제 제외, 9월 없음)
    kw = main_kw(); DA = F11.day_matrix(kw)
    for m in ([7] if quick else F24.MONTHS):
        days = month_days(kw, 2021, m, True, DA)
        r, met = run_fm("A사", days, DA, F24.CAP, hol21)
        raw[("A사", m)] = r
        a1, b1, _ = rows_for("A사", 2021, m, r, met, np.nan, "설계·선택에 쓴 달(비블라인드)")
        rows.append(a1); sens.append(b1); print(f"  A사 {m}월 {datetime.datetime.now():%H:%M:%S}", flush=True)
    # UCI 철강 2~12월 (1월은 직전 4주 이력·직전 달 cap이 없어 제외)
    if not quick:
        DS = F11.day_matrix(ks)
        for m in range(2, 13):
            days = month_days(ks, 2018, m)
            prev = ks[ks.index.month == m - 1]
            r, met = run_fm("UCI 철강", days, DS, 20.0 / 204.0 * float(prev.max()), HOL18, hol_off=hol21)
            raw[("UCI 철강", m)] = r
            a1, b1, _ = rows_for("UCI 철강", 2018, m, r, met, np.nan, "구 엔진(F11)으로 판독한 공장 — v2·W1 첫 적용(비블라인드)")
            rows.append(a1); sens.append(b1); print(f"  철강 {m}월 {datetime.datetime.now():%H:%M:%S}", flush=True)
    K7.HOLI = hol21
    n = check(raw)
    print(f"self-check OK (기존 표 대조 {n}개 공장-월 · 분해 항등식 · 철강 단위 · 보류 공장 미접근 · 테스트 구간 미적재)")
    T, U = pd.DataFrame(rows), pd.DataFrame(sens)
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
    if quick:
        print(f"[{'재삽입 ' + str(MUT) if MUT else '축약판 무결함'}] self-check 통과" + (" — 검사가 이 결함을 못 본다" if MUT else ""))
        print(T.to_string(index=False)); return
    T.to_csv(OUT, index=False, encoding="utf-8-sig"); U.to_csv(OUT_S, index=False, encoding="utf-8-sig")
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{t0.isoformat(timespec='seconds')} → {datetime.datetime.now().isoformat(timespec='seconds')} · 비블라인드 진단 · "
                 f"{len(T)}공장-월 · s={S} · 보류 8곳·HIPE 미접근\n")
    print(T.to_string(index=False)); print(U.to_string(index=False)); print(f"→ {OUT.relative_to(B)} · {OUT_S.relative_to(B)}")


if __name__ == "__main__":
    main()
