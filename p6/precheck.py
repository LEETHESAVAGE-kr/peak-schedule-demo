# precheck — 운전표 도입 전 판정(외부이전 재조사 PRD §7-3). 독립 모듈: 표준 라이브러리 + pandas/numpy만, f24 등 엔진 import 금지.
# 공개 API: precheck(df_or_path, **kw) -> dict  (시연 앱이 import한다 — 인자·반환 키를 바꾸면 명세 md도 바꿀 것)
# CLI:     python -X utf8 precheck.py <csv> [--month YYYY-MM] [--tz Asia/Seoul] [--json out.json] [--fig out.png]
#
# 지표 두 개(판정은 ①만)(비블라인드 진단 28개 공장-월에서 원인 분해로 고른 것, ext_phase1_decomp_20261026.md §3-2):
#   ① 피크 시각 적중률(평일) — D−1 18:00에 아는 같은 요일 직전 4주 중앙값 곡선의 최대 슬롯이 실측 최대 슬롯 ±1시간(±4슬롯) 안인 평일 비율.
#      복제일(전날까지 어느 날과 96슬롯이 같은 날) 제외, 공휴일 제외. 낮으면 운전표가 엉뚱한 슬롯에 부하를 얹는다(단조형 '악화').
#   ② 첨두성 = 창 안 최대 ÷ 평균 — 보고만 한다. 중앙값 운전표의 철강형 '무변화'를 설명했지만 현행 W2에서는 판정력이 없어 v1 판정에서 뺐다.
# 판정 창: month를 주면 그 달 1일 직전 lookback_days일(인과 — 그 달 자료를 쓰지 않는다), 안 주면 자료 전체.
import sys, json, argparse
import numpy as np, pandas as pd

# ---- 임계값(출처: ext_precheck_v1_20261027.md §2) — 바꾸면 사전등록 SHA가 깨진다 ----
HIT_CHANCE = 9 / 96                 # ±4슬롯 창이 무작위로 맞을 확률(하루 96슬롯 균등 가정) = 0.09375
HIT_PASS = 2 * HIT_CHANCE           # 권장선: 우연의 2배 = 0.1875
PEAK_MAX = 3.0                      # 첨두성 참고선(판정에 쓰지 않음 — v1 결정, ext_precheck_v1_20261027.md §2)
MIN_WEEKDAYS = 8                    # 적중률을 잴 평일 최소 수
MAX_MISSING = 0.20                  # 창 안 결측 슬롯 비율 상한
SHIFT_HOURS_DEFAULT = 4

KR_HOLIDAYS = pd.to_datetime([      # 한국 법정공휴일(대체·선거일 포함) 2018~2022 — 내장표
    "2018-01-01", "2018-02-15", "2018-02-16", "2018-02-17", "2018-03-01", "2018-05-05", "2018-05-07", "2018-05-22", "2018-06-06",
    "2018-06-13", "2018-08-15", "2018-09-23", "2018-09-24", "2018-09-25", "2018-09-26", "2018-10-03", "2018-10-09", "2018-12-25",
    "2019-01-01", "2019-02-04", "2019-02-05", "2019-02-06", "2019-03-01", "2019-05-05", "2019-05-06", "2019-05-12", "2019-06-06",
    "2019-08-15", "2019-09-12", "2019-09-13", "2019-09-14", "2019-10-03", "2019-10-09", "2019-12-25",
    "2020-01-01", "2020-01-24", "2020-01-25", "2020-01-26", "2020-01-27", "2020-03-01", "2020-04-15", "2020-04-30", "2020-05-05",
    "2020-06-06", "2020-08-15", "2020-08-17", "2020-09-30", "2020-10-01", "2020-10-02", "2020-10-03", "2020-10-09", "2020-12-25",
    "2021-01-01", "2021-02-11", "2021-02-12", "2021-02-13", "2021-03-01", "2021-05-05", "2021-05-19", "2021-06-06", "2021-08-15",
    "2021-08-16", "2021-09-20", "2021-09-21", "2021-09-22", "2021-10-03", "2021-10-04", "2021-10-09", "2021-10-11", "2021-12-25",
    "2022-01-01", "2022-01-31", "2022-02-01", "2022-02-02", "2022-03-01", "2022-03-09", "2022-05-05", "2022-05-08", "2022-06-01",
    "2022-06-06", "2022-08-15", "2022-09-09", "2022-09-10", "2022-09-11", "2022-09-12", "2022-10-03", "2022-10-09", "2022-10-10",
    "2022-12-25"]).date


def _series(df_or_path, tz=None, kw_col=None):
    """15분 kW 시계열(벽시계 시각, tz 없음). kWh/15분이면 ×4. 15분보다 촘촘하면 15분 평균(구간의 80% 이상 있을 때)."""
    d = pd.read_csv(df_or_path) if isinstance(df_or_path, (str, bytes)) or hasattr(df_or_path, "__fspath__") else df_or_path.copy()
    if not isinstance(d, pd.DataFrame):
        d = d.to_frame()
    if "timestamp" in d.columns:
        t = pd.to_datetime(d["timestamp"], utc=False)
    else:
        t = pd.to_datetime(d.index)
    t = pd.DatetimeIndex(t)
    if t.tz is not None:                                     # 오프셋이 붙은 시각은 현지 시각으로 바꾼 뒤 tz를 뗀다
        t = t.tz_convert(tz or "Asia/Seoul").tz_localize(None)
    col = kw_col or ("kw" if "kw" in d.columns else "kwh" if "kwh" in d.columns else None)
    if col is None:
        raise ValueError("열 'kw' 또는 'kwh'가 필요하다")
    v = pd.to_numeric(d[col], errors="coerce").values * (4.0 if col == "kwh" else 1.0)
    s = pd.Series(v, index=t).sort_index()
    s = s[~s.index.duplicated()]
    step = s.index.to_series().diff().median()
    if step > pd.Timedelta(minutes=15):
        raise ValueError(f"해상도 {step}는 15분보다 거칠다 — 판정 불가")
    if step < pd.Timedelta(minutes=15):
        need = 0.8 * (pd.Timedelta(minutes=15) / step)
        g = s.resample("15min")
        s = g.mean().where(g.count() >= need)
    mv = None
    if "movable_kw" in d.columns:
        mv = pd.Series(pd.to_numeric(d["movable_kw"], errors="coerce").values, index=t).sort_index()
    return s, mv


def _days(s):
    """완전한 날(96슬롯, 결측 없음)만 {날짜: 96벡터}. 서머타임 전환일(92·100슬롯)은 자동으로 빠진다."""
    out = {}
    for d, g in s.groupby(s.index.normalize()):
        if len(g) == 96 and g.notna().all() and (g.index == pd.date_range(d, periods=96, freq="15min")).all():
            out[d] = g.values.astype(float)
    return out


def _dedup(D):
    keep, seen = {}, set()
    for d in sorted(D):
        k = D[d].tobytes()
        if k in seen:
            continue
        seen.add(k); keep[d] = D[d]
    return keep


def _median4(D, d):
    hs = [D[d - pd.Timedelta(days=7 * k)] for k in range(1, 5) if d - pd.Timedelta(days=7 * k) in D]
    return np.median(hs, 0) if hs else None


def precheck(df_or_path, holidays=None, shift_hours=SHIFT_HOURS_DEFAULT, month=None, lookback_days=62, tz=None, kw_col=None):
    """반환: {metrics, verdict ∈ {권장, 조건부, 비권장, 판정불가}, reasons, thresholds, window}."""
    hol = set(KR_HOLIDAYS if holidays is None else pd.to_datetime(list(holidays)).date)
    s, mv = _series(df_or_path, tz, kw_col)
    if month is not None:
        st = pd.Timestamp(str(month) + ("-01" if len(str(month)) == 7 else ""))
        lo = max(st - pd.Timedelta(days=lookback_days), s.index.min().normalize())   # 자료 시작 전은 창에서 뺀다
        hist = s[s.index < st]                               # 이력(직전 4주 중앙값용)은 창 이전도 쓴다 — 판정 달 자료는 쓰지 않는다
        win_lo, win_hi = lo, st
    else:
        hist = s; win_lo, win_hi = s.index.min().normalize(), s.index.max() + pd.Timedelta(minutes=15)
    D_all = _days(hist)
    D = _dedup(D_all)                                         # 복제일 제외(먼저 나온 날만 남김)
    W = {d: v for d, v in D.items() if win_lo <= d < win_hi}
    slots_win = hist[(hist.index >= win_lo) & (hist.index < win_hi)]
    n_exp = max(1, int((win_hi - win_lo) / pd.Timedelta(minutes=15)))
    missing = 1.0 - float(slots_win.notna().sum()) / n_exp
    hits = []
    for d, y in W.items():
        if d.weekday() >= 5 or d.date() in hol:
            continue
        f = _median4(D_all, d)                                # 이력은 복제 포함 전체(운영 때와 같다), 평가 대상만 복제 제외
        if f is not None:
            hits.append(abs(int(np.argmax(f)) - int(np.argmax(y))) <= 4)
    Y = np.concatenate(list(W.values())) if W else np.array([np.nan])
    idx = pd.DatetimeIndex(np.concatenate([pd.date_range(d, periods=96, freq="15min").values for d in W])) if W else pd.DatetimeIndex([])
    mean = float(np.nanmean(Y)) if W else np.nan
    m = dict(peak_hour_hit_rate=float(np.mean(hits)) if hits else np.nan, hit_weekdays=len(hits),
             peakiness=float(np.nanmax(Y) / mean) if W and mean > 0 else np.nan,
             weekly_peak_hour_autocorr=_wk_auto(W, hol), night_share=_share(Y, idx, (idx.hour >= 22) | (idx.hour < 8)),
             weekend_share=_share(Y, idx, idx.weekday >= 5), days=len(W), dup_days_removed=len([d for d in D_all if win_lo <= d < win_hi]) - len(W),
             missing_rate=round(missing, 4), movable_share=_movable(mv, s, win_lo, win_hi))
    reasons = []
    if len(hits) < MIN_WEEKDAYS or missing > MAX_MISSING:
        verdict = "판정불가"
        reasons.append(f"평일 {len(hits)}일(최소 {MIN_WEEKDAYS}) · 결측 {missing:.1%}(상한 {MAX_MISSING:.0%})")
    else:
        h, p = m["peak_hour_hit_rate"], m["peakiness"]
        rh = "통과" if h >= HIT_PASS else ("우연 수준" if h < HIT_CHANCE + 1e-12 else "미달")
        reasons.append(f"① 피크 시각 적중률 {h:.3f} — {rh} (권장선 {HIT_PASS:.4f} = 우연 {HIT_CHANCE:.4f}의 2배)")
        reasons.append(f"② 첨두성 {p:.2f} — 참고(판정에 쓰지 않음: 시나리오 운전표 W2에서는 스파이크형 공장도 11개월 중 7개월 하락)")
        if rh == "통과":
            verdict = "권장"
        elif rh == "우연 수준":
            verdict = "비권장"
            reasons.append("피크 시각이 우연 수준으로만 맞는다 — 운전표가 엉뚱한 슬롯에 부하를 얹어 피크를 키울 수 있다")
        else:
            verdict = "조건부"
            reasons.append("우연보다 낫지만 권장선 미만 — 1개월 그림자 운전(운전표를 만들되 실행 안 함)으로 확인 후 적용")
    if m["movable_share"] is None:
        reasons.append("이동 가능 부하는 입력되지 않았다 — 효과 크기는 설비 계측(전류 로거 3주)으로 따로 잰다")
    return dict(metrics={k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}, verdict=verdict, reasons=reasons,
                thresholds=dict(hit_pass=HIT_PASS, hit_chance=HIT_CHANCE, peakiness_max=PEAK_MAX, min_weekdays=MIN_WEEKDAYS,
                                max_missing=MAX_MISSING, source="ext_precheck_v1_20261027.md §2 (진단 28개 공장-월)"),
                window=dict(start=str(win_lo.date()), end_exclusive=str(pd.Timestamp(win_hi).date()), month=str(month) if month else None,
                            shift_hours=shift_hours))


def _wk_auto(W, hol):
    r = [abs(int(np.argmax(W[d - pd.Timedelta(days=7)])) - int(np.argmax(y))) <= 4
         for d, y in W.items() if d.weekday() < 5 and d.date() not in hol and d - pd.Timedelta(days=7) in W]
    return float(np.mean(r)) if r else np.nan


def _share(Y, idx, mask):
    return float(np.nansum(Y[np.asarray(mask)]) / np.nansum(Y)) if len(idx) else np.nan


def _movable(mv, s, lo, hi):
    if mv is None:
        return None
    a, b = mv[(mv.index >= lo) & (mv.index < hi)], s[(s.index >= lo) & (s.index < hi)]
    return float(a.sum() / b.sum()) if b.sum() > 0 else None


def _fig(res, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 18})
    m = res["metrics"]
    fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
    ax.axvspan(0, HIT_PASS, color="#f0efec"); ax.axhline(PEAK_MAX, color="#52514e", lw=1.5, ls="--")
    ax.axvline(HIT_PASS, color="#52514e", lw=1.5, ls="--")
    ax.scatter([m["peak_hour_hit_rate"]], [m["peakiness"]], s=160, color="#2a78d6", zorder=3)
    ax.set_xlim(0, 0.7); ax.set_ylim(1, max(8, (m["peakiness"] or 0) + 1))
    ax.set_xlabel("① 피크 시각 적중률(평일)"); ax.set_ylabel("② 첨두성(최대/평균)")
    ax.set_title(f"도입 전 판정: {res['verdict']}", loc="left", weight="bold")
    fig.tight_layout(); fig.savefig(path)


def main():
    ap = argparse.ArgumentParser(description="운전표 도입 전 판정")
    ap.add_argument("csv"); ap.add_argument("--month"); ap.add_argument("--tz"); ap.add_argument("--json"); ap.add_argument("--fig")
    ap.add_argument("--lookback", type=int, default=62)
    a = ap.parse_args()
    r = precheck(a.csv, month=a.month, tz=a.tz, lookback_days=a.lookback)
    txt = json.dumps(r, ensure_ascii=False, indent=2, default=str)
    if a.json:
        open(a.json, "w", encoding="utf-8").write(txt)
    if a.fig:
        _fig(r, a.fig)
    print(txt)


if __name__ == "__main__":
    main()
