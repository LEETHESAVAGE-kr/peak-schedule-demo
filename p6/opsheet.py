# 운전표 화면·브리핑 공통 계산 — viewer.py와 x4_briefing.py가 같은 정의를 쓰게 한 곳에 둔다(읽기 전용, 학습 없음).
import numpy as np, pandas as pd


def daily_profiles(kw):
    """날짜 → 96슬롯 실측(결측 없는 날만). f11_dayahead.naive와 같은 정의의 재계산용."""
    return {d: g.values for d, g in kw.groupby(kw.index.normalize()) if len(g) == 96 and g.notna().all()}


def naive_med4(D, d):
    """같은 요일 직전 4주 슬롯별 중앙값(f11_dayahead.naive 'med'와 같은 정의). 0일이면 None."""
    hs = [D[d - pd.Timedelta(days=7 * k)] for k in range(1, 5) if d - pd.Timedelta(days=7 * k) in D]
    return np.median(hs, 0) if hs else None


def moves(g, tol=0.5, min_kwh=1.0):
    """하루 운전표(실측·실현 열)의 실현−실측 연속 구간 → 작업 이동 지시표. min_kwh 미만 조각은 생략."""
    dd = (g["실현"] - g["실측"]).round(2)
    sgn = np.where(dd > tol, 1, np.where(dd < -tol, -1, 0))
    rows, i, n = [], 0, len(dd)
    while i < n:
        if sgn[i] == 0:
            i += 1; continue
        j = i
        while j + 1 < n and sgn[j + 1] == sgn[i]:
            j += 1
        seg = dd.iloc[i:j + 1]
        t0, t1 = dd.index[i], dd.index[j] + pd.Timedelta(minutes=15)
        rows.append({"시각": f"{t0:%H:%M}~{t1:%H:%M}", "옮기는 양(평균 kW)": round(abs(seg.mean()), 1),
                     "에너지(kWh)": round(abs(seg.sum()) / 4, 1), "방향": "빼냄(다른 시간으로)" if sgn[i] < 0 else "받음(여기서 작업)"})
        i = j + 1
    df = pd.DataFrame(rows, columns=["시각", "옮기는 양(평균 kW)", "에너지(kWh)", "방향"])
    return df[df["에너지(kWh)"] >= min_kwh].reset_index(drop=True)
