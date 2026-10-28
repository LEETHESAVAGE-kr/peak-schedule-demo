# ops_autoscore.py — G6 자동 채점 + 월 누적 요약(Track G-C). PRD KAMP_제6회_PRD_대상권돌파_TrackG_20261028.md §1 G6 ②③.
# 다음 날 실측 CSV가 감시 폴더에 들어오면 사람 클릭 없이 채점하고 ops_log.csv 에 한 줄씩 적재한다.
#  - A사 테스트 기간(2021-09-01~14): 저장 결과만 읽는다(재계산 금지). 운전표 = trackB/_b4b_plan_test.csv(07~20시),
#    들어온 파일의 실측이 저장본 실측과 같을 때만 채점한다. 값은 ③ 탭 채점표(ops_service.daily_rows)와 같아야 한다.
#  - 자사 데이터(모드 B): ops_service.score_user(같은 이동 행렬을 그 날 실측에 적용) — 지금 계산.
# 월 요약은 ops_log.csv 만 읽는다. 규칙은 trackB/roadmap.md §4-3 그대로(산정월 패 1회 / 비산정월 3연속 / 월 게이트).
# 규칙: viewer_ops.py·ops_service.py 는 import 만. build/·trackB/ 쓰기 0. 네트워크 0. 쓰는 파일은 ops_log.csv 하나.
import pathlib
import time

import numpy as np
import pandas as pd

import ops_ingest as I
import ops_service as O

HERE = pathlib.Path(__file__).resolve().parent
LOG = HERE / "ops_log.csv"
COLS = ["날짜", "모드", "기존_일최대", "운전표_일최대", "변화kW", "판정", "원천", "실측파일", "파일SHA", "채점시각"]
BILLING_MONTHS = (12, 1, 2, 7, 8, 9)                     # 요금적용전력 산정월(ops_service 모드 B 양식 7번과 같음)
SRC_SAVED, SRC_NOW = "저장 결과 읽기(재계산 없음)", "지금 계산(자사 데이터)"
SCORE_AFTER = pd.Timedelta(days=1, hours=8, minutes=30)  # D+1 08:30 채점(도입패키지 §3-2)


def read_log(path=LOG):
    if not pathlib.Path(path).exists():
        return pd.DataFrame(columns=COLS)
    d = pd.read_csv(path, encoding="utf-8-sig", dtype={"파일SHA": str})
    d["날짜"] = pd.to_datetime(d["날짜"])
    return d


def append_log(rows, path=LOG):
    """(날짜, 모드)가 이미 있으면 덮지 않고 건너뛴다 — 같은 날을 두 번 채점하지 않는다. 새로 적은 행 수를 돌려준다."""
    old = read_log(path)
    have = {(pd.Timestamp(a), b) for a, b in zip(old["날짜"], old["모드"])}
    new = [r for r in rows if (pd.Timestamp(r["날짜"]), r["모드"]) not in have]
    if new:
        out = pd.concat([old, pd.DataFrame(new, columns=COLS)], ignore_index=True) if len(old) else pd.DataFrame(new, columns=COLS)
        out["날짜"] = pd.to_datetime(out["날짜"]).dt.strftime("%Y-%m-%d")
        out.to_csv(path, index=False, encoding="utf-8-sig")
    return len(new)


def _day_file(cfg, day, now):
    """그 날 96칸 — 한 파일에 다 들었으면 그 파일(가장 최근), 아니면 now 전까지의 파일을 이어 붙여서(로거가 하루를 여러 번 나눠 내보낼 때, H10에서 발견).
    반환 (그 날 마지막 칸이 든 파일, 96값). 없으면 (None, None)."""
    day = pd.Timestamp(day).normalize()
    files = I.files_as_of(cfg["folder"], cfg.get("pattern", "*.csv"), now, cfg)
    parts = []
    for p in reversed(files):
        try:
            kw, _i, _m = I.read_mapped(p, cfg, now)
        except ValueError:
            continue
        y = O.F11.day_matrix(kw).get(day)
        if y is not None:
            return p, y
        parts.append((p, kw))
    if not parts:
        return None, None
    kw = pd.concat([k for _p, k in parts]).sort_index()
    kw = kw[~kw.index.duplicated(keep="first")]                   # 최근 파일 우선(reversed 순서로 모았다)
    y = O.F11.day_matrix(kw).get(day)
    if y is None:
        return None, None
    last = day + pd.Timedelta(hours=23, minutes=45)
    return next(p for p, k in parts if last in k.index), y


def score_saved_day(day, actual, path_name="", sha=""):
    """A사 테스트 하루 — 저장 운전표(07~20시)와 들어온 실측. 실측이 저장본과 다르면 ValueError(채점하지 않는다)."""
    plan, saved_meas, _name = O.saved_plan(day, O.MODE_WIN)
    gap = float(np.abs(np.asarray(actual, float) - saved_meas).max())
    if gap > 1e-6:
        raise ValueError(f"{pd.Timestamp(day):%Y-%m-%d}: 들어온 실측이 저장본 실측과 다릅니다(최대 차 {gap:.3f}kW) — 채점하지 않습니다")
    y0, y1 = float(np.max(actual)), float(np.max(plan))
    return {"날짜": pd.Timestamp(day).normalize(), "모드": "A사 재현", "기존_일최대": y0, "운전표_일최대": y1, "변화kW": y1 - y0,
            "판정": "패" if y1 - y0 > 1e-9 else "승", "원천": SRC_SAVED, "실측파일": path_name, "파일SHA": sha[:16],
            "채점시각": time.strftime("%Y-%m-%d %H:%M:%S")}


def autoscore_saved(cfg=None, now=None, log=LOG, days=None):
    """폴더 감시 1회(A사 재현) — now 시각에 채점할 수 있는 테스트 날(D+1 08:30 지남, 아직 로그에 없음)을 채점해 적재.
    반환 {scored: [행], skipped: [(날, 이유)], added: 새 행 수}."""
    cfg = cfg or I.load_config()
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    done = set(read_log(log).query("모드 == 'A사 재현'")["날짜"]) if pathlib.Path(log).exists() else set()
    scored, skipped = [], []
    for d in (days if days is not None else O.TEST_DAYS):
        d = pd.Timestamp(d).normalize()
        if d + SCORE_AFTER > now or d in done:
            continue
        p, y = _day_file(cfg, d, now)
        if p is None:
            skipped.append((d, "그 날 96칸 실측 파일 없음")); continue
        try:
            scored.append(score_saved_day(d, y, p.name, I.hashlib.sha256(p.read_bytes()).hexdigest()))
        except ValueError as e:
            skipped.append((d, str(e)))
    return {"scored": scored, "skipped": skipped, "added": append_log(scored, log) if scored else 0}


def autoscore_user(res, cfg=None, now=None, log=LOG):
    """모드 B — 계획(plan_user 결과)의 날 실측이 폴더에 들어왔으면 채점·적재. 아직 없으면 None."""
    cfg = cfg or I.load_config()
    p, y = _day_file(cfg, res["day"], now)
    if p is None:
        return None
    kw = pd.Series(y, index=pd.date_range(res["day"], periods=96, freq="15min"))
    if O.reject_if_asa(kw):
        raise ValueError("A사 데이터는 재현 모드에서만 채점합니다")
    sc = O.score_user(res, kw)
    y0, y1 = float(sc["measured"].max()), float(sc["realized"].max())
    row = {"날짜": res["day"], "모드": "자사 데이터", "기존_일최대": y0, "운전표_일최대": y1, "변화kW": y1 - y0, "판정": "패" if y1 - y0 > 1e-9 else "승",
           "원천": SRC_NOW, "실측파일": p.name, "파일SHA": I.hashlib.sha256(p.read_bytes()).hexdigest()[:16], "채점시각": time.strftime("%Y-%m-%d %H:%M:%S")}
    append_log([row], log)
    return row


def prep_demo_log(day=O.DEMO_DAY, log=LOG, cfg=None):
    """시연 준비 — 로그의 A사 재현 행을 비우고 시연 날 전날까지만 채점해 둔다(③에서 시연 날 1행이 새로 들어가게). 자사 데이터 행은 그대로."""
    old = read_log(log)
    keep = old[old["모드"] != "A사 재현"]
    if pathlib.Path(log).exists():
        if len(keep):
            keep.assign(날짜=keep["날짜"].dt.strftime("%Y-%m-%d")).to_csv(log, index=False, encoding="utf-8-sig")
        else:
            pathlib.Path(log).unlink()
    return autoscore_saved(cfg, now=pd.Timestamp(day) - pd.Timedelta(days=1) + SCORE_AFTER, log=log)


def month_summary(log_df, month, mode="A사 재현"):
    """월 누적 요약 — ops_log 만 읽는다. 일 스위치(산정월 패 1회 / 비산정월 3연속 패)와 월 게이트(운전표 월최대 < 기존 월최대)를 따로 적는다.
    월 게이트는 '운전표를 적용했다면'의 모의값이다(일 스위치로 멈춘 날도 같은 운전표로 채점)."""
    m = pd.Period(month, "M")
    d = log_df[(log_df["모드"] == mode) & (pd.to_datetime(log_df["날짜"]).dt.to_period("M") == m)].sort_values("날짜")
    if d.empty:
        return None
    billing = m.month in BILLING_MONTHS
    loses = list(pd.to_datetime(d.loc[d["판정"] == "패", "날짜"]))
    run, stop = 0, None
    for r in d.itertuples():
        run = run + 1 if r.판정 == "패" else 0
        if stop is None and ((billing and run >= 1) or (not billing and run >= 3)):
            stop = pd.Timestamp(r.날짜)
    b0, b1 = float(d["기존_일최대"].max()), float(d["운전표_일최대"].max())
    gate = "적용" if b1 < b0 else "측정만"
    return {"월": str(m), "산정월": billing, "일수": int(len(d)), "처음": pd.Timestamp(d["날짜"].min()), "끝": pd.Timestamp(d["날짜"].max()),
            "승": int((d["판정"] == "승").sum()), "패": int(len(loses)), "패_날짜": loses,
            "패_요일": ["월화수목금토일"[x.dayofweek] for x in loses], "패_기존최대": [float(x) for x in d.loc[d["판정"] == "패", "기존_일최대"]],
            "기존_월최대": b0, "운전표_월최대": b1, "다음달": gate, "일스위치_멈춤": stop,
            "규칙": "산정월 — 채점 패 1회면 그 달 나머지 기존 운전" if billing else "비산정월 — 채점 패 3연속이면 그 달 기존 운전"}


def summary_line(s):
    """카드 한 줄 — 숫자는 전부 s(ops_log 집계)에서."""
    f = lambda x: f"{x:.1f}"
    wk = ", ".join(f"{t:%m/%d}({w})" for t, w in zip(s["패_날짜"], s["패_요일"]))
    head = (f"{s['월']} {'산정월' if s['산정월'] else '비산정월'} · {s['처음']:%m/%d}~{s['끝']:%m/%d} {s['일수']}일 채점 · 승 {s['승']} / 패 {s['패']}"
            + (f"({wk})" if wk else ""))
    gate = f"모의 월최대 {f(s['운전표_월최대'])} {'<' if s['다음달'] == '적용' else '≥'} 기존 {f(s['기존_월최대'])} kW → 다음 달 {s['다음달']}"
    sw = (f"일 스위치: {s['일스위치_멈춤']:%m/%d} 패로 규칙상 그 달 나머지는 기존 운전" if s["일스위치_멈춤"] is not None else "일 스위치: 걸리지 않음")
    return head, gate, sw
