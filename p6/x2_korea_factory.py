# -*- coding: utf-8 -*-
"""x2: 외부 근거 — 한국 제조공장 전력·DR 공개자료 (Lee, Baek, Kim 2022, Sci Data 9:227)

출처: doi:10.1038/s41597-022-01357-8 / figshare doi:10.6084/m9.figshare.14822256.v9 (CC BY 4.0, 로그인 불필요)
  Data_list.zip  https://ndownloader.figshare.com/files/34134648
     SHA256 f8794dc10e8892ead63f431eb55c6a4d6c6411c09a3d58aa29a07c54a14b57fc (MD5 cc3911b3f9e1125468e864a24540cfe0 = figshare 공시값 일치)
  Code_list.zip  https://ndownloader.figshare.com/files/34196997
     SHA256 bbe3f9ac892052548bd443af26a3ada4f78eda50f016ead8f395146acc018ff2 (MD5 398ed0baae9c9a33466e811860f4c3b3 일치)
압축 해제본: data/ext/korea_factory/raw/Data_list/Factories/*.csv (1분 간격, 2019-03-01~09-30)

단위 주의: 논문은 값을 kW라 적지만, 논문 Table(DR 실적)의 "responded capacity"는
 데이터값으로 계산한 (CBL-실측) 1시간 평균의 약 60배와 맞는다(Metal_1 8796 vs 8777 등).
 즉 데이터가 kWh/분(=kW/60)이거나, 논문 응동용량이 kW·분 합계이다. 둘 중 무엇인지 판정 불가.
 → 비율 지표(MAE/평균, 감축 %, 피크 저감 %)만 단위 무관. 절대값은 "데이터 단위(u)"로 표기.

실행: python -X utf8 x2_korea_factory.py
"""
import numpy as np, pandas as pd
from pathlib import Path
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

ROOT = Path(__file__).parent / "data/ext/korea_factory"
FAC = ROOT / "raw/Data_list/Factories"
OUT = ROOT
FORGES = ["Forge_1", "Forge_2"]
ALL = ["Forge_1", "Forge_2", "Metal_1", "Metal_2", "Metal_3", "Steel_1", "Steel_2", "Cement_1", "Cement_2", "Paper"]
# 2019 법정공휴일(기간 내): 삼일절, 어린이날 대체, 현충일, 광복절, 추석 연휴(9/14 토 제외)
HOL = pd.to_datetime(["2019-03-01", "2019-05-06", "2019-06-06", "2019-08-15", "2019-09-12", "2019-09-13"]).date


def load(f):
    d = pd.read_csv(FAC / f"{f}.csv")
    d.columns = ["t", "u"]
    d["t"] = pd.to_datetime(d.t, format="%Y-%m-%d %H:%M")
    s = d.set_index("t").u.astype(float)
    full = pd.date_range("2019-03-01", "2019-09-30 23:59", freq="1min")
    return s.reindex(full)


def to15(s):
    g = s.resample("15min")
    m, n = g.mean(), g.count()
    return m.where(n >= 12)  # 15분 중 12분 이상 있어야 값 인정


def tou_band(ts):
    """한전 현행 시간대(여름·봄가을). 자료가 3~9월이라 겨울 구분은 쓰이지 않음."""
    h = ts.hour
    if h >= 22 or h < 8:
        return "경부하"
    if h in (11, 13, 14, 15, 16, 17):
        return "최대"
    return "중간"  # 8~11, 12~13, 18~22


def daytype(d):
    if d in HOL or pd.Timestamp(d).weekday() == 6:
        return "일·공휴일"
    if pd.Timestamp(d).weekday() == 5:
        return "토"
    return "평일"


def an1(f, s1, q):
    rows = []
    for mth, x in q.groupby(q.index.month):
        t = x.idxmax()
        rows.append(dict(factory=f, month=mth, max15_u=round(x.max(), 2), at=t.strftime("%m-%d %H:%M"),
                         weekday=["월", "화", "수", "목", "금", "토", "일"][t.weekday()], band=tou_band(t),
                         mean15_u=round(x.mean(), 2), max_over_mean=round(x.max() / x.mean(), 2)))
    m = pd.DataFrame(rows)
    dd = q.groupby(q.index.date).agg(["mean", "max"])
    dd["type"] = [daytype(d) for d in dd.index]
    dt = dd.groupby("type").agg(n_days=("mean", "size"), mean_u=("mean", "mean"), dailymax_u=("max", "mean")).round(2)
    dt.insert(0, "factory", f)
    # 15분 피크 슬롯의 시간대 분포(평일 일최대 슬롯 기준)
    wk = q[[daytype(d) == "평일" for d in q.index.date]].dropna()
    dmax_t = wk.groupby(wk.index.date).idxmax()
    bands = pd.Series([tou_band(t) for t in dmax_t]).value_counts(normalize=True).round(3).to_dict()
    hours = pd.Series([t.hour for t in dmax_t]).value_counts().head(3).to_dict()
    meta = dict(factory=f, minutes_present=int(s1.notna().sum()), minutes_missing=int(s1.isna().sum()),
                zero_minute_share=round(float((s1 == 0).mean()), 4), slots15_valid=int(q.notna().sum()),
                slots15_total=len(q), weekday_dailypeak_band=bands, weekday_dailypeak_top_hours=hours)
    return m, dt, meta


def an2(f, q):
    """하루 전 예측: 같은 요일·같은 슬롯, 직전 4주(D-7..D-28) 중앙값. 비교로 D-7 단순 반복."""
    df = pd.DataFrame({"y": q})
    for k in (7, 14, 21, 28):
        df[f"l{k}"] = q.shift(96 * k)
    df["med4"] = df[["l7", "l14", "l21", "l28"]].median(axis=1, skipna=False)
    df = df.dropna(subset=["y", "med4"])
    df["hol"] = [d in HOL for d in df.index.date]
    out = []
    for name, sub in [("전체", df), ("공휴일 제외", df[~df.hol])]:
        for mth, g in [("all", sub)] + list(sub.groupby(sub.index.month)):
            e = (g.y - g.med4).abs()
            out.append(dict(factory=f, subset=name, month=mth, n_slots=len(g), mean_u=round(g.y.mean(), 2),
                            MAE_med4_u=round(e.mean(), 2), MAE_over_mean=round(e.mean() / g.y.mean(), 3),
                            MAE_D7_over_mean=round((g.y - g.l7).abs().mean() / g.y.mean(), 3)))
    return pd.DataFrame(out)


def an3(f, s1, day="2019-06-13", st=18, et=19):
    """CBL = Max 4 of 5 (논문 표 기준: 직전 평일 5일(공휴일 제외) 중 상위 4일 평균), 같은 시간대 1분값 평균."""
    h = s1[(s1.index.hour >= st) & (s1.index.hour < et)]
    daily = h.groupby(h.index.date).mean()
    D = pd.Timestamp(day).date()
    prev = [x for x in daily.index if x < D and pd.Timestamp(x).weekday() < 5 and x not in HOL][-5:]
    pv = daily[prev].dropna()
    cbl = pv.sort_values(ascending=False).iloc[:4].mean()
    act = daily[D]
    return dict(factory=f, day=day, window=f"{st}-{et}", prev_days=[str(p) for p in prev], CBL_u=round(cbl, 2),
                actual_u=round(act, 2), reduction_u=round(cbl - act, 2), reduction_pct_of_CBL=round((cbl - act) / cbl * 100, 1))


def shift_lp(L, s, w=8):
    """하루 96슬롯. x_ij>=0 : 슬롯 i→j 이동(|i-j|<=w). sum_j x_ij <= s*L_i. 새부하 N_j <= P, min P."""
    n = len(L)
    pairs = [(i, j) for i in range(n) for j in range(max(0, i - w), min(n, i + w + 1)) if i != j]
    nv = len(pairs) + 1
    c = np.zeros(nv); c[-1] = 1
    A = lil_matrix((2 * n, nv)); b = np.zeros(2 * n)
    for k, (i, j) in enumerate(pairs):
        A[i, k] += 1          # 유출 한도
        A[n + i, k] += -1     # N_i = L_i - out + in <= P
        A[n + j, k] += 1
    for i in range(n):
        b[i] = s * L[i]
        A[n + i, nv - 1] = -1
        b[n + i] = -L[i]
    r = linprog(c, A_ub=A.tocsr(), b_ub=b, bounds=[(0, None)] * nv, method="highs")
    assert r.status == 0, r.message
    return r.x[-1]


def an4(f, q):
    days = q.groupby(q.index.date)
    rows, skipped = [], 0
    res = {}
    for d, x in days:
        if x.isna().any() or len(x) != 96:
            skipped += 1
            continue
        L = x.values
        res[d] = {"orig": L.max(), **{s: shift_lp(L, s) for s in (0.05, 0.10, 0.255)}}
    r = pd.DataFrame(res).T
    r.index = pd.to_datetime(r.index)
    for mth, g in r.groupby(r.index.month):
        o = g.orig.max()
        row = dict(factory=f, month=mth, days_used=len(g), orig_max_u=round(o, 2))
        for s in (0.05, 0.10, 0.255):
            row[f"cut_pct_s{s*100:g}"] = round((o - g[s].max()) / o * 100, 2)
        rows.append(row)
    return pd.DataFrame(rows), skipped


if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    M, DT, META, F2, F4, DR = [], [], [], [], [], []
    for f in ALL:
        s1 = load(f)
        q = to15(s1)
        DR.append(an3(f, s1, st=16, et=17) if f == "Metal_2" else an3(f, s1))  # 논문 표: Metal 2만 6/13 16~17시
        if f == "Metal_2": DR.append(an3(f, s1, day="2019-05-15", st=17, et=20))
        if f not in FORGES:
            F2.append(an2(f, q).query("month=='all'"))
            continue
        m, dt, meta = an1(f, s1, q)
        M.append(m); DT.append(dt); META.append(meta)
        F2.append(an2(f, q))
        t4, sk = an4(f, q); t4["days_skipped_missing"] = sk; F4.append(t4)
        q.rename("u15").to_csv(OUT / f"{f}_15min.csv", encoding="utf-8-sig")
    M, DT, F2, F4, DR = (pd.concat(M), pd.concat(DT), pd.concat(F2), pd.concat(F4), pd.DataFrame(DR))
    for name, t in [("an1_monthly", M), ("an1_daytype", DT), ("an2_forecast", F2), ("an4_shift", F4), ("an3_dr", DR)]:
        t.to_csv(OUT / f"x2_{name}.csv", encoding="utf-8-sig", index=(name == "an1_daytype"))
        print(f"\n== {name}"); print(t.to_string())
    print("\n== meta")
    for m in META: print(m)
