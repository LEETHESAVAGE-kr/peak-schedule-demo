# I3 — 고지서 월 지표 재집계 + 0단계 선별 규칙(I2 봉인) 대조. 판독 아님: 저장 자료의 월 집계와 저장 판정표 재집계만.
# 규칙·읽는 법은 trackI/I2_prescreen_rules.md (SHA256 d8948add…, read_ledger I-A행) — 실행 전에 SHA를 확인하고 다르면 멈춘다.
# 출력: build/table_i3_bill_metrics.csv(공장-월) · build/table_i3_prescreen_vs_verdict.csv(공장) · report/fig/I3_선별대조.png · trackI/_i3_run.log
import sys, ast, hashlib, json
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import fisher_exact

B = Path(__file__).resolve().parents[2]                    # p6/
sys.path.insert(0, str(B))
import precheck as P                                       # 읽기만(_series·_days·_dedup·KR_HOLIDAYS) — 파일 불변
import x2_korea_factory as X2                              # 1차 1분 원본 → 15분 평균(판독 때와 같은 함수)

RULES, RULES_SHA = B / "report/trackI/I2_prescreen_rules.md", "d8948add5a18e57e4cb4df11b1aa75c8f56122c69fa9218e4c67267cdaaa796d"
SEALED = {B / "precheck.py": "dccac94a71dfcebe", B / "build/table_x_holdout.csv": "3b97082b0314a4ff",
          B / "build/table_x_holdout3.csv": "2b4277e2e2df6da1", B / "build/table_x_precheck_diag.csv": "b95894c3dc66951e",
          B / "build/main_15min.csv": "ce242314984367c9"}
OUT_M, OUT_F = B / "build/table_i3_bill_metrics.csv", B / "build/table_i3_prescreen_vs_verdict.csv"
FIG, LOG = B / "report/fig/I3_선별대조.png", B / "report/trackI/_i3_run.log"
NEW = B / "data/ext/new"
RATCHET = {12, 1, 2, 7, 8, 9}
MIN_VALID_DAYS, EQUIP_MIN, TOL = 10, 2_208_730, 0.5
NPERM, SEED = 10000, 0
US12 = set(pd.to_datetime(["2012-01-02", "2012-01-16", "2012-02-20", "2012-05-28", "2012-07-04", "2012-09-03",
                           "2012-10-08", "2012-11-12", "2012-11-22", "2012-12-25"]).date)      # x11_holdout.US12 그대로
DE17 = set(pd.to_datetime(["2017-10-03", "2017-10-31", "2017-11-01", "2017-12-25", "2017-12-26"]).date)   # x11_holdout.DE17 그대로
KR = set(P.KR_HOLIDAYS)
lines = []


def log(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def src_dict(path, name):
    """판독 스크립트 소스에서 SHA 표를 그대로 읽는다(모듈 import 없이 — 엔진 부작용 방지)."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == name for t in n.targets):
            return ast.literal_eval(n.value)
    raise KeyError(name)


# ---------------- 자료 ----------------
def grid(q, a, b):
    q = q[~q.index.duplicated()].sort_index()
    return q.reindex(pd.date_range(a, b, freq="15min"))


def load_all():
    S = {}
    hold1 = src_dict(B / "x11_holdout.py", "HOLD")
    for f, h in hold1.items():                                           # 1차 한국 8곳, 2019
        assert sha(X2.FAC / f"{f}.csv") == h, f"{f} SHA"
        S[f] = ("1차", X2.to15(X2.load(f)), KR, 2019)
    sh2 = {690: "76a8a2da2bb75566", 716: "7036b54385ded6a0", 761: "849a6e44268819a6", 832: "9fce849f0e6d9e06"}
    p = NEW / "hipe_kit/HIPE_MainTerminal_15min.csv"
    assert sha(p).startswith("652886703be18e45"), "HIPE SHA"
    d = pd.read_csv(p); S["HIPE_Main"] = ("2차", grid(pd.Series(d.kw.values, pd.to_datetime(d.timestamp)), "2017-10-01", "2017-12-31 23:45"), DE17, 2017)
    for i, h in sh2.items():
        p = NEW / f"enernoc_mfg/EnerNOC_{i}_15min.csv"; assert sha(p).startswith(h), f"{i} SHA"
        d = pd.read_csv(p); S[f"EnerNOC_{i}"] = ("2차", grid(pd.Series(d.kw.values, pd.to_datetime(d.timestamp)), "2012-01-01", "2012-12-31 23:45"), US12, 2012)
    hold3 = src_dict(B / "x13_holdout3.py", "HOLD3")
    for i, h in hold3.items():
        p = NEW / f"enernoc_food/EnerNOC_{i}_15min.csv"; assert sha(p) == h, f"{i} SHA"
        d = pd.read_csv(p); S[f"EnerNOC_{i}"] = ("3차", grid(pd.Series(d.kw.values, pd.to_datetime(d.timestamp)), "2012-01-01", "2012-12-31 23:45"), US12, 2012)
    m = pd.read_csv(B / "build/main_15min.csv")
    t = pd.to_datetime(m.ts); q = pd.Series(m.kw.values, t)
    S["A사"] = ("A사", grid(q[((t >= "2021-01-01") & (t < "2021-09-01")).values], "2021-01-01", "2021-08-31 23:45"), KR, 2021)
    return S


# ---------------- 시간대(별표3, 가정 라벨) ----------------
def band_vec(day, hol):
    """하루 96칸의 시간대 라벨(요금 대상 판단용 dm, kWh 집계용 kwh). 0 경부하 · 1 중간 · 2 최대."""
    h = np.arange(96) // 4
    winter = day.month in (11, 12, 1, 2)
    peak = np.isin(h, [9, 10, 11, 16, 17, 18]) if winter else np.isin(h, [11, 13, 14, 15, 16, 17])
    light = (h >= 22) | (h < 8)
    b = np.where(light, 0, np.where(peak, 2, 1))
    if day.weekday() == 6 or day.date() in hol:            # 공휴일(일요일 포함) — 전부 경부하
        return np.zeros(96, int), np.zeros(96, int)
    kwh_b = np.where((b == 2) & (day.weekday() == 5), 1, b)  # 공휴일 아닌 토요일 최대부하 kWh → 중간
    return b, kwh_b


def month_table(name, part, q, hol, year):
    D = P._dedup(P._days(q))                              # 완전한 날, 복제일 제외(precheck 정의 그대로)
    rows, chk = [], 0.0
    for (y, mth), days in pd.Series(list(D.keys()), index=list(D.keys())).groupby(lambda d: (d.year, d.month)):
        dm, kw = -np.inf, np.zeros(3)
        for d in days:
            v = D[d]; b_dm, b_kwh = band_vec(d, hol)
            if (b_dm > 0).any():
                dm = max(dm, float(v[b_dm > 0].max()))
            for k in range(3):
                kw[k] += float(v[b_kwh == k].sum()) * 0.25
        rows.append(dict(공장=name, 구분=part, 연=y, 월=mth, 유효일=len(days), 유효달=len(days) >= MIN_VALID_DAYS,
                         D_m=round(dm, 4) if np.isfinite(dm) else np.nan, kWh_경부하=kw[0], kWh_중간=kw[1], kWh_최대=kw[2],
                         kWh_총=kw.sum(), R4_m=kw[2] / kw.sum() if kw.sum() > 0 else np.nan, 산정월=mth in RATCHET))
    T = pd.DataFrame(rows)
    # self-check: 월 집계 합 = 원본 15분 값(같은 유효 일)의 직접 합
    direct = sum(float(v.sum()) for v in D.values()) * 0.25
    raw = float(q[q.index.normalize().isin(list(D.keys()))].sum()) * 0.25
    assert abs(T.kWh_총.sum() - direct) < 1e-6 * max(1, direct) and abs(direct - raw) < 1e-6 * max(1, raw), f"{name} kWh 합 불일치"
    assert np.allclose(T[["kWh_경부하", "kWh_중간", "kWh_최대"]].sum(1), T.kWh_총)
    return T, raw


# ---------------- 규칙(I2 §1 그대로) ----------------
def factory_rules(T):
    V = T[T.유효달].sort_values(["연", "월"])
    out = dict(유효달수=len(V))
    if V.empty:
        return out
    last = (V.연.iloc[-1], V.월.iloc[-1])
    cand = V[V.산정월 | ((V.연 == last[0]) & (V.월 == last[1]))]
    Pw = float(cand.D_m.max())
    price = 6490 if Pw < 300 else 7220
    rat, non = V[V.산정월], V[~V.산정월]
    out.update(P_모사=Pw, 단가_가정=price, C_star=Pw / 0.3, R1="입력 없음")
    if len(rat) >= 3 and len(non) >= 3:
        U = max(0.0, Pw - float(non.D_m.median())) * price * 12
        out.update(U_원=U, R2="효과 없음" if U < EQUIP_MIN else "통과")
    else:
        out.update(U_원=np.nan, R2="판정 불가")
    if len(rat) >= 3:                                      # I2 §1: R3 판정 불가는 유효 산정월 < 3일 때만(R2 조건과 별개)
        mg = rat[rat.D_m >= 0.98 * Pw].월.tolist()
        out.update(R3="통과" if len(mg) <= 2 else "주의", 관리대상달=",".join(map(str, mg)))
    else:
        out.update(R3="판정 불가", 관리대상달="")
    out["R4값"] = float(V.kWh_최대.sum() / V.kWh_총.sum())
    out["R5값"] = float(V.D_m.std(ddof=0) / V.D_m.mean()) if len(V) >= 6 else np.nan
    return out


def auc(score, y):
    s, y = np.asarray(score, float), np.asarray(y, bool)
    pos, neg = s[y], s[~y]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


def perm_p(score, y):
    a0 = auc(score, y); rng = np.random.default_rng(SEED); y = np.asarray(y, bool)
    k = sum(abs(auc(score, rng.permutation(y)) - 0.5) >= abs(a0 - 0.5) - 1e-12 for _ in range(NPERM))
    return a0, (k + 1) / (NPERM + 1)


def main():
    assert sha(RULES) == RULES_SHA, "[거부] I2 규칙 파일이 봉인 뒤 바뀌었다"
    for p, h in SEALED.items():
        assert sha(p).startswith(h), f"[거부] {p.name} SHA 불일치"
    log(f"I2 SHA {RULES_SHA[:16]}… 일치 · 봉인 입력 {len(SEALED)}개 일치")
    S = load_all()
    log("공장", len(S), "(A사 + 외부", len(S) - 1, ")")
    assert len(S) == 31
    MT, F = [], []
    for name, (part, q, hol, year) in S.items():
        T, raw = month_table(name, part, q, hol, year)
        MT.append(T)
        r = factory_rules(T); r.update(공장=name, 구분=part, 원본kWh_유효일=raw); F.append(r)
        log(f"{name:14s} {part} 유효달 {r['유효달수']:2d} P {r.get('P_모사', np.nan):9.2f} R2 {r.get('R2', '-'):6s} U {r.get('U_원', np.nan):14,.0f} R3 {r.get('R3', '-')} R4 {r.get('R4값', np.nan):.4f} R5 {r.get('R5값', np.nan):.4f}  (월합 self-check 통과)")
    MT = pd.concat(MT, ignore_index=True); F = pd.DataFrame(F)
    # R4·R5 분포 3분위(기준 집합 31곳, 값 있는 곳만)
    q4 = F.R4값.dropna().quantile(1 / 3); q5 = F.R5값.dropna().quantile(2 / 3)
    F["R4"] = np.where(F.R4값.isna(), "판정 불가", np.where(F.R4값 <= q4, "주의", "통과"))
    F["R5"] = np.where(F.R5값.isna(), "판정 불가", np.where(F.R5값 >= q5, "주의", "통과"))
    F["선별"] = np.where(F.R2 == "효과 없음", "효과 없음", "통과")
    F["주의수"] = (F[["R3", "R4", "R5"]] == "주의").sum(1)
    log(f"R4 하위 3분의 1 경계 {q4:.4f} · R5 상위 3분의 1 경계 {q5:.4f} (31곳 분포)")

    # 판정·결과(저장값)
    H = pd.read_csv(B / "build/table_x_holdout.csv", encoding="utf-8-sig"); H = H[H.구분.isin(["1차", "2차"])]
    H3 = pd.read_csv(B / "build/table_x_holdout3.csv", encoding="utf-8-sig")
    E = pd.concat([H, H3[H.columns]], ignore_index=True)
    E = E[(E.평가 == "평가") & E.판정.isin(["권장", "조건부", "비권장"])].copy()
    assert len(E) == 270, len(E)                           # G5 self-check와 같은 값
    E["결과"] = np.where(E.W2외부판_pct > TOL, "악화", np.where(E.W2외부판_pct < -TOL, "하락", "무변화"))
    fac = E.groupby("공장").agg(평가달=("판정", "size"), 권장비율=("판정", lambda s: (s == "권장").mean()),
                              결과중앙=("W2외부판_pct", "median"))
    fac["권장다수"] = fac.권장비율 >= 0.5; fac["악화공장"] = fac.결과중앙 > TOL
    F = F.merge(fac, left_on="공장", right_index=True, how="left")
    A = pd.read_csv(B / "build/table_x_precheck_diag.csv", encoding="utf-8-sig"); A = A[A.공장 == "A사"]
    ia = F.공장 == "A사"
    F.loc[ia, ["평가달", "권장비율", "결과중앙"]] = [len(A), (A.판정 == "권장").mean(), A.W2외부판_pct.median()]
    X = F[~ia & F.평가달.notna()].copy()
    assert len(X) == 30, len(X)

    # 1. 거름의 비용
    EE = E.merge(F[["공장", "선별", "R2"]], on="공장")
    res = {}
    for g, G in EE.groupby("선별"):
        res[g] = dict(공장=G.공장.nunique(), 공장월=len(G), 하락=int((G.결과 == "하락").sum()), 악화=int((G.결과 == "악화").sum()),
                      권장=int((G.판정 == "권장").sum()), 권장악화=int(((G.판정 == "권장") & (G.결과 == "악화")).sum()),
                      권장하락=int(((G.판정 == "권장") & (G.결과 == "하락")).sum()))
        log(f"[거름] {g}: {res[g]}")
    log("[R2 판정 불가 공장]", EE[EE.R2 == "판정 불가"].공장.unique().tolist())

    # 2. 공장 단위 AUC·순열·Fisher
    stat = []
    for rv in ["R4값", "R5값"]:
        for lab in ["권장다수", "악화공장"]:
            Z = X[X[rv].notna()]
            sc = -Z[rv] if rv == "R4값" else Z[rv]           # 방향은 I2 정의대로: R4 낮을수록·R5 높을수록 '주의'
            y = Z[lab].astype(bool) if lab == "악화공장" else ~Z[lab].astype(bool)   # '주의' 쪽이 맞히려는 사건: 권장 다수 아님 / 악화 공장
            a, p = perm_p(sc.values, y.values)
            rr = rv[:2]; ct = pd.crosstab(Z[rr] == "주의", y)
            fp = fisher_exact(ct.values)[1] if ct.shape == (2, 2) else np.nan
            stat.append(dict(규칙=rr, 사건="권장 다수 아님" if lab == "권장다수" else "악화 공장", n=len(Z), 사건수=int(y.sum()),
                             AUC=round(a, 4), 순열p=round(p, 4), 주의중사건=int(((Z[rr] == "주의") & y).sum()), 주의=int((Z[rr] == "주의").sum()),
                             통과중사건=int(((Z[rr] == "통과") & y).sum()), 통과=int((Z[rr] == "통과").sum()), Fisher_p=round(fp, 4)))
            log(f"[공장] {stat[-1]}")
    ST = pd.DataFrame(stat)
    hit = ((ST.AUC >= 0.70) & (ST.순열p < 0.05)).any()
    verdict = "고지서만으로 1차 선별 가능(사후 설계 후보)" if hit else "고지서는 선별 못 함, 요금 확정용 — 선별은 피크 시각이 필요"
    log("[읽는 법 적용]", verdict)

    # 3. 공장-월 보조: 직전 달 R4
    Mv = MT[MT.유효달 & (MT.공장 != "A사")][["공장", "월", "R4_m"]]
    EM = E.merge(Mv.assign(월=Mv.월 + 1).rename(columns={"R4_m": "R4_직전달"}), on=["공장", "월"], how="inner")
    fm = []
    for lab, y in [("권장 아님", EM.판정 != "권장"), ("악화", EM.결과 == "악화")]:
        a = auc(-EM.R4_직전달.values, y.values)
        fm.append(dict(사건=lab, n=len(EM), 사건수=int(y.sum()), AUC=round(a, 4))); log(f"[공장-월 보조] {fm[-1]}")

    # 저장
    MT.to_csv(OUT_M, index=False, encoding="utf-8-sig")
    cols = ["공장", "구분", "유효달수", "P_모사", "단가_가정", "C_star", "R1", "U_원", "R2", "관리대상달", "R3", "R4값", "R4", "R5값", "R5",
            "선별", "주의수", "평가달", "권장비율", "결과중앙", "권장다수", "악화공장", "원본kWh_유효일"]
    F[cols].to_csv(OUT_F, index=False, encoding="utf-8-sig")
    ST.to_csv(B / "build/table_i3_rule_stats.csv", index=False, encoding="utf-8-sig")
    json.dump(dict(거름=res, 공장=stat, 공장월=fm, 판정=verdict, R4경계=q4, R5경계=q5), open(B / "report/trackI/_i3_summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=float)
    fig(F, X)
    log(f"행 수: {OUT_M.name} {len(MT)} · {OUT_F.name} {len(F)} · table_i3_rule_stats.csv {len(ST)}")
    LOG.write_text("\n".join(lines), encoding="utf-8")


def fig(F, X):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 13})
    fig, ax = plt.subplots(1, 2, figsize=(13, 5.5), dpi=110)
    for k, (lab, ttl) in enumerate([("악화공장", "결과: 권장 달 포함 평가 달 중앙 > +0.5% = 악화 공장"), ("권장다수", "판정: 평가 달 절반 이상 권장")]):
        a = ax[k]; Z = X[X.R4값.notna()]
        r5 = Z.R5값.fillna(Z.R5값.max() * 1.15)
        c = np.where(Z[lab].astype(bool), "#c0392b" if lab == "악화공장" else "#2a78d6", "#9a9893")
        ok = Z.R5값.notna().values
        a.scatter(Z.R4값[ok], r5[ok], c=c[ok], s=60, zorder=3)
        a.scatter(Z.R4값[~ok], r5[~ok], facecolors="none", edgecolors=c[~ok], s=60, zorder=3)
        for x_, y_ in zip(Z.R4값[~ok], r5[~ok]):
            a.annotate("R5 판정 불가(3개월)", (x_, y_), xytext=(-60, -14), textcoords="offset points", fontsize=10)
        ra = F[F.공장 == "A사"].iloc[0]; a.scatter([ra.R4값], [ra.R5값], marker="*", s=260, c="#222", zorder=4); a.annotate("A사", (ra.R4값, ra.R5값), xytext=(6, 6), textcoords="offset points")
        a.axvline(F.R4값.dropna().quantile(1 / 3), ls="--", c="#52514e", lw=1); a.axhline(F.R5값.dropna().quantile(2 / 3), ls="--", c="#52514e", lw=1)
        a.set_xlabel("R4 최대부하 시간대 kWh 비중(한국 표 가정)"); a.set_ylabel("R5 월 최대수요 변동계수")
        a.set_title(ttl, loc="left", fontsize=12)
    ax[0].text(0.01, -0.2, "빨강 = 악화 공장, 회색 = 그 외", transform=ax[0].transAxes, fontsize=11)
    ax[1].text(0.01, -0.2, "파랑 = 권장 다수, 회색 = 그 외 · 점선 = 31곳 분포 3분위(고정 기준 아님)", transform=ax[1].transAxes, fontsize=11)
    fig.suptitle("I3 고지서 월 지표 vs 판정·결과 (외부 30곳, 재집계·사후 설계 후보)", x=0.01, ha="left", fontsize=14, weight="bold")
    fig.tight_layout(); fig.savefig(FIG)


if __name__ == "__main__":
    main()
