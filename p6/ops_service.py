# ops_service.py — 실무자 화면(viewer_ops.py)의 숫자·생성·대조 계층. 화면 코드 없음.
# PRD: KAMP_제6회_PRD_실무자앱_20261027.md §4-끝(숫자 출처 표 N1~N31)·§0-5(모드 B).
# 규칙: build/·report/trackB/ 는 읽기만 한다(쓰기 0). 네트워크 호출 0. LLM 호출 0.
#       화면에 나오는 모든 숫자는 SOURCES 를 거친다 — 여기 없는 숫자는 화면에 나올 수 없다.
import hashlib
import json
import pathlib
import re
import sys
import threading
import time
import warnings

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
B, TB = HERE / "build", HERE / "report" / "trackB"
for p in (HERE, TB):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import b4_staffing_constraint as B4

import f11_dayahead as F11
import f14_schedule_v2 as F14
import f18_breakeven as F18
import f21_decision_forecaster as F21
import f24_scenario_schedule as F24
import k7_tariff_cost as K7
import precheck as P
from closed_loop_core import by_day
from common import load
from opsheet import moves

PLAN_FREE = F24.plan_scen                  # 원본 LP(보고서 조건). B4 는 plan_scen_ban 으로 바꿔 끼운다.
TEST_DAYS = pd.date_range("2021-09-01", "2021-09-14", freq="D")
TOL_KW = 0.01                              # 저장본 대조 허용(저장값이 소수 3자리 반올림)
GEN_LOCK = threading.Lock()                # 생성 직렬화 — regenerate 는 F24.plan_scen·B4.BAN 모듈 전역을 바꿔 끼우므로 동시 실행이면 두 LP가 섞인다
LAST_GEN = HERE.parent / "_sched" / "_demo_last_gen.json"   # 터널 끊김 대비 마지막 생성 결과(build/ 아님)
DEMO_DAY = pd.Timestamp("2021-09-10")      # 시연 기준 날짜(S9 와 같은 날)
ENGINE_FILES = ["f24_scenario_schedule.py", "f14_schedule_v2.py", "f21_decision_forecaster.py", "f11_dayahead.py", "common.py",
                "report/trackB/b4_staffing_constraint.py"]
ENGINE_SHA = {                              # PRD §0-3 — 발표 직전 코드 변조가 없음을 확인하는 기대값(기능 동일의 증명은 S9)
    "f24_scenario_schedule.py": "0377420e2f97e4045d18d20489e68c5f0b14d07ff3209b76b56818d254c8f76a",
    "f14_schedule_v2.py": "df864ad98ea6ad16efb21bbfe2d0b6d168ed4d0b4c791668bde8e3694c5c9f6a",
    "f21_decision_forecaster.py": "192f4a89e016a1dbd4a59c773f792d12325a3c3af37cc7468cf1d43cfb017a1f",
    "f11_dayahead.py": "5151a24f19342a7a34de8366cb3fc4f50d77a79821224543fda98820365e77dd",
    "common.py": "3cd43f1aab3381df9173a3a98290fe616af198881e6f9b879d9d192642b43764",
    "report/trackB/b4_staffing_constraint.py": "c0893af5c2b0d1c4b2c217d92fac231326f6e7883722f0d4d5ff81972e7d425c",
}
MODE_WIN, MODE_FREE = "win", "free"
LABEL_REPORT, LABEL_ADDED, LABEL_CONST, LABEL_GEN, LABEL_DERIVED = "보", "추", "상", "생", "파"
BADGE_TEXT = {LABEL_REPORT: "보고서 {page}", LABEL_ADDED: "제출 후 추가 분석", LABEL_CONST: "코드 상수", LABEL_GEN: "지금 생성", LABEL_DERIVED: "두 값의 차"}
PAGES = {"N1": "79·80쪽", "N2": "80쪽", "N3c": "80쪽", "N4": "80쪽", "N6": "80·84쪽", "N7": "80·88쪽", "N9": "84쪽", "N10": "79·80·101쪽", "N12": "84쪽", "N14": "79·101쪽", "N26": "48쪽"}


# ---------- 파일 읽기(캐시) ----------
_CACHE = {}


def rd(path, **k):
    key = (str(path), json.dumps(k, sort_keys=True, default=str))
    if key not in _CACHE:
        _CACHE[key] = pd.read_csv(path, encoding="utf-8-sig", **k)
    return _CACHE[key].copy()


def js(path):
    key = ("json", str(path))
    if key not in _CACHE:
        with open(path, encoding="utf-8") as fh:
            _CACHE[key] = json.load(fh)
    return _CACHE[key]


def _num(s):
    return float(str(s).replace(",", ""))


# ---------- 숫자 출처 표 (PRD §4-끝 N1~N31, 생성값 N27~N30 제외) ----------
def _b4test():
    d = rd(TB / "_b4_staffing.csv")
    return d[d.구간 == "테스트 9/1~14"].set_index("제약")


def _b4month(m):
    d = rd(TB / "_b4_staffing.csv")
    return d[d.구간 == f"{m}월"].set_index("제약")


def _kpi():
    return rd(B / "table_f24_kpi_skr.csv").set_index("KPI")


def _tariff(cond):
    return js(TB / "_b4b_tariff.json")[cond]


WIN, FREE = "시간창 07~20시", "제약 없음(제출 W2 재현)"
SOURCES = {
    "N1":  {"label": LABEL_REPORT, "row": "8",  "how": lambda: float(rd(B / "f24_plan_testat.csv")["실측"].max())},
    "N2":  {"label": LABEL_REPORT, "row": "8",  "how": lambda: float(rd(B / "table_f24_testat.csv").set_index("후보").loc["W2", "월최대kW"])},
    "N3":  {"label": LABEL_ADDED,  "row": "8",  "how": lambda: float(_b4test().loc[WIN, "월최대"])},
    "N3b": {"label": LABEL_ADDED,  "row": "8",  "how": lambda: float(_b4test().loc[WIN, "감축kW"])},
    "N3c": {"label": LABEL_REPORT, "row": "8",  "how": lambda: float(_b4test().loc[FREE, "감축kW"])},
    "N4":  {"label": LABEL_REPORT, "row": "9",  "how": lambda: float(rd(B / "table_f24_testat.csv").set_index("후보").loc["C0", "월최대kW"])},
    "N5":  {"label": LABEL_ADDED,  "row": "—",  "how": lambda: float(_b4test().loc[WIN, "금지칸평균"])},
    "N6a": {"label": LABEL_REPORT, "row": "11", "how": lambda: _num(re.search(r"[\d.]+", _kpi().loc["요금적용전력 (7·8·9월 청구 기준 최대)", "후"]).group())},
    "N6b": {"label": LABEL_ADDED,  "row": "11", "how": lambda: float(_tariff(WIN)["요금적용전력kW"])},
    "N7a": {"label": LABEL_REPORT, "row": "19", "how": lambda: -_num(re.search(r"선택Ⅰ -([\d,]+)", _kpi().loc["기본요금 (선택Ⅰ)", "개선"]).group(1))},
    "N7b": {"label": LABEL_ADDED,  "row": "19", "how": lambda: float(_tariff(WIN)["기본요금_월"])},
    "N8a": {"label": LABEL_ADDED,  "row": "20", "how": lambda: float(_tariff(FREE)["기본요금_연"])},
    "N8b": {"label": LABEL_ADDED,  "row": "20", "how": lambda: float(_tariff(WIN)["기본요금_연"])},
    "N9a": {"label": LABEL_REPORT, "row": "21", "how": lambda: _num(re.search(r"전력량 (-[\d,]+)", _kpi().loc["에너지비용 (기본+전력량, 선택Ⅰ)", "개선"]).group(1))},
    "N9b": {"label": LABEL_ADDED,  "row": "21", "how": lambda: float(_tariff(WIN)["전력량_월_봄가을"])},
    "N10a": {"label": LABEL_REPORT, "row": "7", "how": lambda: _num(re.search(r"(-[\d,]+)원/월", _kpi().loc["에너지비용 (기본+전력량, 선택Ⅰ)", "개선"]).group(1))},
    "N10b": {"label": LABEL_ADDED,  "row": "7", "how": lambda: float(_tariff(WIN)["합계_월(보고서 방식)"])},
    "N11a": {"label": LABEL_ADDED,  "row": "22", "how": lambda: tuple(float(x) for x in _tariff(FREE)["연_범위"])},
    "N11b": {"label": LABEL_ADDED,  "row": "22", "how": lambda: tuple(float(x) for x in _tariff(WIN)["연_범위"])},
    "N12a": {"label": LABEL_REPORT, "row": "18", "how": lambda: float(_b4month(7).loc[FREE, "월최대"])},
    "N12b": {"label": LABEL_ADDED,  "row": "18", "how": lambda: float(_b4month(7).loc[WIN, "월최대"])},
    "N12c": {"label": LABEL_REPORT, "row": "18", "how": lambda: float(_b4month(7).loc[FREE, "기존"])},
    "N13": {"label": LABEL_ADDED,  "row": "23", "how": lambda: float(js(TB / "_e1_s_grid.json")["손익분기"]["07~20시"]["s*_B 7월 < 218kW"])},
    "N14a": {"label": LABEL_REPORT, "row": "—", "how": lambda: float(rd(B / "table_d0x.csv")["월환산_손실개수"].min())},
    "N14b": {"label": LABEL_REPORT, "row": "—", "how": lambda: float(rd(B / "table_d0x.csv")["월환산_손실개수"].max())},
    "N16a": {"label": LABEL_ADDED, "row": "§2", "how": lambda: float(_e1_row("2교대")["7월"])},
    "N16b": {"label": LABEL_ADDED, "row": "§2", "how": lambda: float(_e1_row("2교대")["기본요금_월"])},
    "N16c": {"label": LABEL_ADDED, "row": "§2", "how": lambda: float(js(TB / "_e2_dr.json")["07~20시 + DR 17~21시 금지"]["7월"])},
    "N16d": {"label": LABEL_ADDED, "row": "§2", "how": lambda: float(js(TB / "_e2_dr.json")["07~20시 + DR 17~21시 금지"]["기본요금_월"])},
    "N17a": {"label": LABEL_ADDED, "row": "16", "how": lambda: str(_b4test().loc[WIN, "평일하락일"])},
    "N17b": {"label": LABEL_ADDED, "row": "16", "how": lambda: float(_b4test().loc[WIN, "평일변화율중앙"])},
    "N17c": {"label": LABEL_ADDED, "row": "16", "how": lambda: float(_b4test().loc[FREE, "평일변화율중앙"])},
    "N21a": {"label": LABEL_ADDED, "row": "1", "how": lambda: float(js(TB / "_b3_gate.json")["W2_운전한달"])},
    "N21b": {"label": LABEL_ADDED, "row": "1", "how": lambda: float(js(TB / "_b3_gate.json")["W2_현행보다높은달"])},
    "N21c": {"label": LABEL_ADDED, "row": "1", "how": lambda: float(js(TB / "_b3_gate.json")["W2_적용후변화율_중앙"])},
    "N21d": {"label": LABEL_ADDED, "row": "1", "how": lambda: float(len(js(TB / "_b3_gate.json")["W2_게이트"]))},
    "N22a": {"label": LABEL_ADDED, "row": "—", "how": lambda: float(js(TB / "_b3_gate.json")["실패예시"]["악화율"])},
    "N22b": {"label": LABEL_ADDED, "row": "—", "how": lambda: float(js(TB / "_b3_gate.json")["실패예시"]["A사_산정월_증가kW"])},
    "N22c": {"label": LABEL_ADDED, "row": "—", "how": lambda: float(js(TB / "_b3_gate.json")["실패예시"]["기본요금_증가_월_선택Ⅰ"])},
    "N22d": {"label": LABEL_ADDED, "row": "—", "how": lambda: float(js(TB / "_b3_gate.json")["실패예시"]["산정월이면_최대12개월"])},
    "N23a": {"label": LABEL_CONST, "row": "15", "how": lambda: float(P.HIT_PASS)},
    "N23b": {"label": LABEL_CONST, "row": "15", "how": lambda: float(P.HIT_CHANCE)},
    "N25a": {"label": LABEL_ADDED, "row": "4", "how": lambda: float(_decomp_med()["A사"])},
    "N25b": {"label": LABEL_ADDED, "row": "4", "how": lambda: float(_decomp_med()["Forge_1"])},
    "N25c": {"label": LABEL_ADDED, "row": "4", "how": lambda: float(_decomp_med()["Forge_2"])},
    "N31":  {"label": LABEL_ADDED, "row": "4", "how": lambda: float(_decomp_med()["UCI 철강"])},
    "N26":  {"label": LABEL_REPORT, "row": "10", "how": lambda: float(F18.s_kr())},
    # 민감도 범위의 아래 끝(07~20시, s 3.5%) — 위 끝은 도입 기준 값(N6b·N7b·N8b·N12b). 정정표 행 11·18·19·20
    "N6c":  {"label": LABEL_ADDED, "row": "11", "how": lambda: float(_e1_s("07~20시", 0.035)["요금적용전력_7_8월"])},
    "N7c":  {"label": LABEL_ADDED, "row": "19", "how": lambda: float(_e1_s("07~20시", 0.035)["기본요금_월"])},
    "N8c":  {"label": LABEL_ADDED, "row": "20", "how": lambda: float(_e1_s("07~20시", 0.035)["기본요금_연"])},
    "N12d": {"label": LABEL_ADDED, "row": "18", "how": lambda: float(_e1_s("07~20시", 0.035)["7월"])},
    "N15a": {"label": LABEL_DERIVED, "row": "—", "how": lambda: SOURCES["N12c"]["how"]() - SOURCES["N6a"]["how"]()},   # 피크 여유 = 7월 현행 − 요금적용전력
    "N15b": {"label": LABEL_DERIVED, "row": "—", "how": lambda: SOURCES["N12c"]["how"]() - SOURCES["N6b"]["how"]()},
}


def _e1_row(prefix):
    return next(r for r in js(TB / "_e1_s_grid.json")["요약"] if r["제약"].startswith(prefix) and abs(r["s"] - 0.1295) < 1e-9)


def _e1_s(cons, sv):
    return next(r for r in js(TB / "_e1_s_grid.json")["요약"] if r["제약"] == cons and abs(r["s"] - sv) < 1e-9)


def _decomp_med():
    return rd(B / "table_x_decomp.csv").groupby("공장")["적중률_평일"].median()


def load_sources():
    return {k: v["how"]() for k, v in SOURCES.items()}


def badge_of(n):
    s = SOURCES[n]
    return BADGE_TEXT[s["label"]].format(page=PAGES.get(n, PAGES.get(n.rstrip("abcd"), "")))


def precheck_rows():
    """N24 — A사 설계 달 5행(precheck 판정 창 62일)."""
    d = rd(B / "table_x_precheck_diag.csv")
    return d[d.공장 == "A사"][["월", "판정", "적중률", "첨두성", "결과"]].reset_index(drop=True)


def daily_rows(mode):
    """N18 — 테스트 14일 채점표."""
    if mode == MODE_WIN:
        d = rd(TB / "_b4_staffing_daily.csv")
        d = d[d.제약 == WIN].copy()
        d["day"] = pd.to_datetime(d["day"])
        out = pd.DataFrame({"날짜": d.day.values, "기존": d.실측.values, "운전표": d.실현.values})
    else:
        d = rd(B / "table_x_test_daily.csv")
        out = pd.DataFrame({"날짜": pd.to_datetime(d.day).values, "기존": d.실측일최대.values, "운전표": d.실현일최대.values})
    out["변화kW"] = out.운전표 - out.기존
    out["변화율"] = out.변화kW / out.기존
    out["요일"] = ["월화수목금토일"[x.dayofweek] for x in out.날짜]
    out["판정"] = np.where(out.변화kW > 1e-9, "패", "승")
    return out


def energy_gap(day):
    d = rd(B / "table_x_test_daily.csv")
    return float(d.loc[d.day == pd.Timestamp(day).strftime("%Y-%m-%d"), "에너지차"].iloc[0])


def gate_rows():
    g = js(TB / "_b3_gate.json")["W2_게이트"]
    return pd.DataFrame(g)[["월", "현행", "W2", "적용", "적용후변화율"]]


# ---------- 코드 지문 ----------
def code_fingerprint():
    sha = {f: hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in ENGINE_FILES}
    prereg = hashlib.sha256(F24.PREREG.read_bytes()).hexdigest()
    return {"sha": sha, "match": {f: sha[f] == ENGINE_SHA[f] for f in ENGINE_FILES},
                "prereg_sha": prereg, "prereg_ok": (prereg == F24.PREREG_SHA), "prereg_expected": F24.PREREG_SHA}


# ---------- 모드 A: 재현 생성(테스트 기간 안 날짜 1개, 두 조건) ----------
_ASA = {}


def _asa_inputs():
    if not _ASA:
        q0 = load(); kw = q0["kw"]
        D = F11.day_matrix(kw)
        Fx = F21.day_feats(q0, D); sd = F21.scale(Fx, pd.Timestamp(2021, 9, 1))
        _ASA.update(q0=q0, kw=kw, D=D, Fx=Fx, sd=sd, sk=F18.s_kr())
    return _ASA


def regenerate(day, progress=None):
    """생성 1회 — GEN_LOCK 으로 직렬화(다른 화면이 생성 중이면 끝날 때까지 기다린다)."""
    with GEN_LOCK:
        return _regenerate(day, progress)


def _regenerate(day, progress=None):
    """A사 2021-09-01~14 중 하루를 두 조건(07~20시 받음 / 보고서 조건)으로 지금 생성한다. 테스트 밖 날짜는 거부."""
    day = pd.Timestamp(day).normalize()
    if day not in TEST_DAYS:
        raise ValueError("테스트 기간(2021-09-01~14) 안의 날만 생성한다 — 밖은 새 성능 숫자가 된다")
    say = progress or (lambda *a: None)
    t0 = time.perf_counter(); A = _asa_inputs()
    days = [g for g in by_day(F14.month_frame(A["kw"], 9)) if g.index[0].normalize() == day]
    fc0 = {day: F11.naive(A["D"], day, "med")}
    secs = {}
    t = time.perf_counter(); S = F24.scen_sets(A["D"], A["Fx"], A["sd"], day)["AB"]; secs["유사일 검색"] = time.perf_counter() - t
    say("1/4 유사일 검색", secs["유사일 검색"], f"시나리오 {len(S)}일 확정")
    t = time.perf_counter(); scen = [A["D"][x] for x in S]; secs["시나리오 구성"] = time.perf_counter() - t
    say("2/4 시나리오 부하 구성", secs["시나리오 구성"], f"{len(scen)}×96 슬롯")
    out = {}
    try:
        F24.plan_scen = B4.plan_scen_ban
        t = time.perf_counter()
        o, fb, _nop, nb = B4.run_w2(days, A["D"], A["Fx"], A["sd"], A["sk"], fc0, lambda d: B4.ban_window(d, 7, 20))
        secs["최적화 07~20시"] = time.perf_counter() - t
        out[MODE_WIN] = {"plan": o[0], "ban": nb, "fallback": fb}
        say("3/4 작업 일정 최적화 — 07~20시만 받음", secs["최적화 07~20시"], f"받음 금지 {int(nb)}/96칸")
        F24.plan_scen = PLAN_FREE
        t = time.perf_counter()
        o, _nop, fb, _ns = F24.run_scen(days, A["D"], A["Fx"], A["sd"], "AB", "mean", A["sk"], F24.CAP, fc0)
        secs["최적화 보고서 조건"] = time.perf_counter() - t
        out[MODE_FREE] = {"plan": o[0], "ban": 0.0, "fallback": fb}
        say("4/4 작업 일정 최적화 — 보고서 조건(새벽에도 받음)", secs["최적화 보고서 조건"], "")
    finally:
        F24.plan_scen = PLAN_FREE
    g = days[0]
    res = {"day": day, "index": g.index, "measured": g["y"].values, "scen_days": list(S), "scen": np.array(scen),
               "plans": {m: out[m]["plan"] for m in out}, "ban": {m: out[m]["ban"] for m in out},
               "secs": secs, "total_sec": time.perf_counter() - t0, "s": A["sk"]}
    res["compare"] = compare(res)
    return res


def save_last_gen(res):
    """마지막 생성 결과를 _sched/_demo_last_gen.json 에 남긴다(재접속용). 이 모듈에서 파일을 쓰는 곳은 여기 하나다."""
    keep = {"day": str(res["day"].date()), "index": [str(t) for t in res["index"]], "measured": list(map(float, res["measured"])),
            "plans": {m: list(map(float, v)) for m, v in res["plans"].items()}, "ban": {m: float(b) for m, b in res["ban"].items()},
            "scen_days": [str(pd.Timestamp(x).date()) for x in res["scen_days"]], "scen": np.asarray(res["scen"], float).tolist(),
            "secs": {k: float(v) for k, v in res["secs"].items()}, "total_sec": float(res["total_sec"]), "s": float(res["s"]),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    LAST_GEN.parent.mkdir(parents=True, exist_ok=True)
    LAST_GEN.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")


def load_last_gen():
    """저장한 마지막 생성 결과를 되살리고 저장본 대조를 다시 계산한다. 없거나 테스트 밖 날짜면 None."""
    if not LAST_GEN.exists():
        return None
    with open(LAST_GEN, encoding="utf-8") as fh:
        k = json.load(fh)
    day = pd.Timestamp(k["day"])
    if day not in TEST_DAYS:
        return None
    res = {"day": day, "index": pd.DatetimeIndex(pd.to_datetime(k["index"])), "measured": np.array(k["measured"]),
           "plans": {m: np.array(v) for m, v in k["plans"].items()}, "ban": k["ban"], "scen_days": [pd.Timestamp(x) for x in k["scen_days"]],
           "scen": np.array(k["scen"]), "secs": k["secs"], "total_sec": k["total_sec"], "s": k["s"], "saved_at": k["saved_at"]}
    res["compare"] = compare(res)
    return res


def saved_plan(day, mode):
    """저장본: 07~20시 → trackB/_b4b_plan_test.csv(10/26 사후 민감도) · 보고서 조건 → build/f24_plan_testat.csv(10/7 1회 확인)."""
    ds = pd.Timestamp(day).strftime("%Y-%m-%d")
    if mode == MODE_WIN:
        d = rd(TB / "_b4b_plan_test.csv", parse_dates=["ts"]).set_index("ts").loc[ds]
        return d[WIN].values, d["실측"].values, "10/26 저장본(제출 후 추가 분석 · trackB/_b4b_plan_test.csv)"
    d = rd(B / "f24_plan_testat.csv", parse_dates=["ts"])
    d = d[d.s == F18.s_kr()].set_index("ts").loc[ds]
    return d["실현"].values, d["실측"].values, "10/7 1회 확인 저장본(build/f24_plan_testat.csv)"


def compare(res):
    out = {}
    for m in (MODE_WIN, MODE_FREE):
        sp, sm, name = saved_plan(res["day"], m)
        diff = float(np.abs(res["plans"][m] - sp).max())
        out[m] = {"saved": sp, "maxdiff": diff, "ok": diff <= TOL_KW, "name": name, "measured_ok": bool(np.abs(sm - res["measured"]).max() < 1e-6)}
    sc = rd(B / "f24_scen_testat.csv", parse_dates=["대상일", "시나리오일"])
    saved_days = set(sc[sc.대상일 == res["day"]].시나리오일)
    out["scen_ok"] = saved_days == set(res["scen_days"])
    return out


def move_table(index, measured, plan, min_kwh=5.0):
    g = pd.DataFrame({"실측": measured, "실현": plan}, index=index)
    mt = moves(g, min_kwh=min_kwh)
    return mt.assign(방향=mt["방향"].str[:2]).rename(columns={"옮기는 양(평균 kW)": "평균 이동전력(kW)", "방향": "이동 방향"})[["시각", "평균 이동전력(kW)", "이동 방향"]]


def lock_rows(index, base, plan, locked, tol=0.5, min_kwh=5.0):
    """반장이 '이동 불가'로 지운 작업 행(move_table 의 시각 문자열)을 원 시각으로 되돌린 화면 계산(Track F D10).
    고정-재계산 — LP 를 다시 풀지 않는다: 지운 행의 이동량을 0으로 두고, 하루 에너지가 맞도록 반대 방향 이동(남은 행)을 같은 비율로 줄인다.
    move_table 과 같은 구간 정의(moves: tol 0.5kW, 5kWh 이상). 반환 {plan, peak, gap_kwh, kept_ratio}. 저장본·build/ 는 건드리지 않는다."""
    idx = pd.DatetimeIndex(index)
    base = np.asarray(base, float)
    d = np.asarray(plan, float) - base
    dd = np.round(d, 2)
    sgn = np.where(dd > tol, 1, np.where(dd < -tol, -1, 0))
    i, n = 0, len(dd)
    while i < n:
        if sgn[i] == 0:
            i += 1; continue
        j = i
        while j + 1 < n and sgn[j + 1] == sgn[i]:
            j += 1
        t0, t1 = idx[i], idx[j] + pd.Timedelta(minutes=15)
        if f"{t0:%H:%M}~{t1:%H:%M}" in set(locked) and abs(dd[i:j + 1].sum()) / 4 >= min_kwh:
            d[i:j + 1] = 0.0
        i = j + 1
    s = d.sum()
    side = d > 0 if s > 0 else d < 0                      # 남은 받음(빼냄 행을 지웠을 때) 또는 남은 빼냄을 줄인다
    tot = d[side].sum()
    ratio = 1.0 if s == 0 or tot == 0 else min(1.0, max(0.0, (tot - s) / tot))
    d[side] *= ratio
    new = base + d
    return {"plan": new, "peak": float(new.max()), "gap_kwh": float(abs(new.sum() - base.sum()) / 4), "kept_ratio": ratio}


# ---------- 브리핑(규칙 기반) · 반장 종이 ----------
SITE_ASA, SITE_USER = "A사(재현)", "우리 공장(자사 데이터)"


def base_of(res):
    """운전표를 비교할 기준선 — 모드 A는 그 날 실측(사후 평가), 모드 B는 시나리오 평균(예상, 실측 없음)."""
    return res["base"] if "base" in res else res["measured"]


def briefing(res, mode, site=SITE_ASA, window=(7, 20)):
    """규칙 기반 문장 — 숫자는 전부 res(지금 생성)에서 넣는다. LLM 없음.
    A사 전용 문장(프레스 1·2호·평일 경보 시간대)은 모드 A에만. 모드 B는 '고정 설비는 손대지 않습니다'만, 경보 문장 없음."""
    idx, y, o = res["index"], base_of(res), res["plans"][mode]
    sm = res["scen"].mean(0)
    pk = idx[int(sm.argmax())]
    mt = moves(pd.DataFrame({"실측": y, "실현": o}, index=idx))
    outs, ins = mt[mt.방향.str.startswith("빼냄")], mt[mt.방향.str.startswith("받음")]
    kwh = round(float(outs["에너지(kWh)"].sum()), 1)
    if mode == MODE_FREE:
        cond = "하루 중 어느 시각에도 작업을 받을 수 있다는 조건입니다(야간 작업 가능 시 상한)"
    elif site == SITE_ASA:
        cond = f"사람이 있는 {window[0]:02d}:00~{window[1]:02d}:00에만 작업을 받습니다"
    else:
        cond = "양식에 적은 근무시간과 받음 금지 칸을 지킵니다"
    s1 = f"{idx[0]:%Y-%m-%d} 운전 지시입니다. 비슷한 과거 날 {len(res['scen_days'])}일의 평균 기준으로 예상 일 최대는 {pk:%H:%M} 무렵 {round(sm.max())}kW입니다."
    s2 = (f"{', '.join(outs.시각)} 시간대의 이동 가능 작업(구간 평균 최대 {outs['옮기는 양(평균 kW)'].max():.1f}kW)을 "
          f"{', '.join(ins.시각)} 시간대로 옮겨 주십시오.") if len(outs) and len(ins) else "옮길 작업이 없습니다. 기존 계획대로 운전합니다."
    s3 = f"옮기는 에너지는 모두 {kwh}kWh이며, 하루 생산량과 부하 합은 그대로입니다. {cond}."
    if site != SITE_ASA:
        s4 = "고정 설비는 손대지 않습니다."
    elif idx[0].dayofweek < 5:
        s4 = "프레스 1·2호는 손대지 않습니다. 경보는 평일 08~17시 고정 시간대에 켜 둡니다."
    else:
        s4 = "프레스 1·2호는 손대지 않습니다."
    facts = set(np.round([sm.max(), kwh] + list(outs["옮기는 양(평균 kW)"]) + list(ins["옮기는 양(평균 kW)"]), 1))
    return f"{s1} {s2} {s3} {s4}", facts


def paper_html(res, mode, extra_bans=None, window=(7, 20), site=SITE_ASA, screen=False):
    """반장 종이 HTML. screen=True 는 화면 공유용 미리보기(글자 18px 이상) — 내려받는 인쇄본은 기본 크기."""
    text, _ = briefing(res, mode, site=site, window=window)
    big = ("body{max-width:none!important;margin:8px auto!important;font-size:18px!important} h1{font-size:24px!important} "
           ".m,.badge,td,th{font-size:18px!important}") if screen else ""
    mt = move_table(res["index"], base_of(res), res["plans"][mode])
    rows = "".join(f"<tr><td>{r.시각}</td><td style='text-align:right'>{r['평균 이동전력(kW)']:.1f}</td><td>{r['이동 방향']}</td></tr>" for _, r in mt.iterrows())
    if site == SITE_ASA:
        bans = [f"근무시간 밖({window[1]:02d}:00~{window[0]:02d}:00) — 자동" if mode == MODE_WIN else "근무시간 제약 없음(보고서 조건)",
                "금형 교체 — 현장 입력 ______", "예열 — 현장 입력 ______", "DR 발령 — 참여 시 현장 입력 ______"]
    else:
        bans = [f"근무시간 밖({window[1]:02d}:00~{window[0]:02d}:00) — 양식대로 자동"]
    ban_li = "".join(f"<li>{b}</li>" for b in bans + list(extra_bans or []))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>운전표 {res['day']:%Y-%m-%d}</title>
<style>body{{font-family:'Malgun Gothic','맑은 고딕',sans-serif;color:#1F232B;max-width:760px;margin:24px auto;padding:0 16px;font-size:14px;line-height:1.5}}
h1{{font-size:20px;margin:0 0 4px}} .m{{color:#6A6A6A;font-size:12px}} table{{border-collapse:collapse;width:100%;margin:8px 0}} td,th{{border:1px solid #DDDDDD;padding:4px 8px;text-align:left}}
th{{background:#EEF1F7}} .box{{border:1px solid #DDDDDD;border-radius:4px;padding:10px 14px;margin:10px 0}} .sig{{display:flex;gap:24px;margin-top:16px}} .sig div{{flex:1;border-top:1px solid #1F232B;padding-top:4px}}
.badge{{display:inline-block;background:#FFF4E5;color:#B25E09;border-radius:999px;padding:1px 9px;font-size:11px;font-weight:600}} {big}</style></head><body>
<h1>{res['day']:%Y-%m-%d} ({'월화수목금토일'[res['day'].dayofweek]}) 운전표 — 반장 확인·서명</h1>
<div class="m">작성 전날 18:00 · 조건 {('07~20시만 받음(도입 기준)' if mode == MODE_WIN else '보고서 조건(새벽에도 받음)') if site == SITE_ASA else f'{window[0]:02d}~{window[1]:02d}시 받음(양식)'} · 현장 {site} · <span class="badge">규칙 기반 브리핑 · 숫자는 운전표에서</span></div>
<div class="box"><b>브리핑</b><br>{text}</div>
<b>작업 이동표</b> (이동 에너지 5kWh 이상 구간)
<table><tr><th>시각</th><th>평균 이동전력(kW)</th><th>이동 방향</th></tr>{rows}</table>
<b>받음 금지 칸</b><ul>{ban_li}</ul>
<div class="box"><b>반장이 보는 세 숫자</b> — 하나라도 틀리면 그날은 원래 계획으로<br>
☐ ① 설비별 오늘 가동 칸 수 = 계획 칸 수 &nbsp;&nbsp; ☐ ② 일 생산 수량 ≥ 생산계획 수량 &nbsp;&nbsp; ☐ ③ 브리핑에 "부하 합은 그대로" 문구</div>
<div class="sig"><div>반장 서명 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 18:__</div><div>퇴근 전 기록 — 옮긴 구간 ☐ · 생산 수량 ______ · 이상 사항 ______</div></div>
<p class="m">운전원은 이 종이만 받습니다. 새 화면은 보지 않습니다.</p></body></html>"""


# ---------- 모드 B: 우리 공장(자사 데이터) ----------
def read_user_csv(file_or_df):
    """timestamp·kw 열 탐지 → 15분 kW Series. kWh/15분이면 ×4. 반환 (kw, info)."""
    d = file_or_df if isinstance(file_or_df, pd.DataFrame) else pd.read_csv(file_or_df)
    cols = {c.lower().strip(): c for c in d.columns}
    tcol = next((cols[c] for c in cols if c in ("timestamp", "ts", "datetime", "date", "시각", "일시", "time")), d.columns[0])
    unit = "kW"
    kcol = next((cols[c] for c in cols if c in ("kw", "전력", "load", "power", "최대수요전력")), None)
    if kcol is None:
        kcol = next((cols[c] for c in cols if "kwh" in c or "usage" in c), None)
        unit = "kWh/15분" if kcol else "kW"
    if kcol is None:
        num = [c for c in d.columns if c != tcol and pd.api.types.is_numeric_dtype(d[c])]
        if not num:
            raise ValueError("kW 열을 찾지 못했습니다 — 열 이름을 timestamp, kw 로 해 주십시오")
        kcol = num[0]
    s = pd.Series(pd.to_numeric(d[kcol], errors="coerce").values, index=pd.to_datetime(d[tcol], errors="coerce"), name="kw").dropna().sort_index()
    s = s[~s.index.duplicated()]
    if unit == "kWh/15분":
        s = s * 4.0
    step = s.index.to_series().diff().median()
    if step < pd.Timedelta(minutes=15):
        s = s.resample("15min").mean().dropna()
    D = F11.day_matrix(s)
    seen, dup = set(), 0
    for dday in sorted(D):
        k = D[dday].tobytes(); dup += k in seen; seen.add(k)
    full_idx = pd.date_range(s.index.min().floor("D"), s.index.max().ceil("D"), freq="15min", inclusive="left")
    info = {"start": str(s.index.min()), "end": str(s.index.max()), "days": len(D), "weekdays": sum(1 for x in D if x.dayofweek < 5),
                "missing": round(1 - len(s) / max(1, len(full_idx)), 4), "dup_days": int(dup), "unit": unit, "col": str(kcol)}
    return s, info


def reject_if_asa(kw):
    """A사 데이터 차단(S12): build/main_15min.csv 와 겹치는 시각에서 95% 이상 같으면 True."""
    a = load()["kw"]
    j = pd.concat([a.rename("a"), kw.rename("b")], axis=1, join="inner").dropna()
    if len(j) < 96 * 7:
        return False
    return bool((np.abs(j.a - j.b) < 1e-6).mean() >= 0.95)


def precheck_user(kw, month=None):
    df = pd.DataFrame({"timestamp": kw.index, "kw": kw.values})
    return P.precheck(df, month=month)


MODE_A_LABEL, MODE_B_LABEL = "A사 재현 — 발표 시연", "우리 공장 — 자사 데이터"
TABS_A = ["① 내일의 운전표", "② 반장 확인·서명", "③ 어제 채점", "④ 이번 달 KPI", "⑤ 우리 공장 진단", "⑥ 멈춤 스위치(네 층)"]
TABS_B = ["⑤ 우리 공장 진단", "① 내일의 운전표", "② 반장 확인·서명", "③ 어제 채점", "④ 이번 달 KPI", "⑥ 멈춤 스위치(네 층)"]
CONDS = ["07~20시만 받음(도입 기준)", "보고서 조건(새벽에도 받음)"]


def gate_of(verdict):
    """판정이 운전표를 잠근다(S14): 권장 → 생성 · 조건부 → 모의 운전만(적용 금지) · 비권장/판정불가 → 생성 안 함."""
    return {"can_generate": verdict in ("권장", "조건부"), "mock_only": verdict == "조건부", "verdict": verdict}


def form_default():
    return {"win_lo": 7, "win_hi": 20, "night": False, "night_lo": 22, "night_hi": 6, "s_known": False, "s": F18.s_kr(), "L_hours": 4,
                "ban_extra": [], "dr": False, "tariff": "산업용(을) 고압A 선택Ⅰ", "billing_month": False, "cap_scale": True}


def ban_from_form(form):
    """양식 → 받음 금지 슬롯(0..95) 집합. 시간창 밖 + 야간 허용 창 복원 + 추가 금지 구간 + DR 17~21시."""
    allow = {t for t in range(96) if form["win_lo"] * 4 <= t < form["win_hi"] * 4}
    if form.get("night"):
        lo, hi = form["night_lo"] * 4, form["night_hi"] * 4
        allow |= {t for t in range(96) if (t >= lo or t < hi)} if lo > hi else {t for t in range(96) if lo <= t < hi}
    ban = set(range(96)) - allow
    for (h0, m0, h1, m1) in form.get("ban_extra", []):
        a, b = h0 * 4 + m0 // 15, h1 * 4 + m1 // 15
        ban |= {t for t in range(96) if a <= t < b}
    if form.get("dr"):
        ban |= {t for t in range(96) if 17 * 4 <= t < 21 * 4}
    return ban


def plan_user(kw, day, form, progress=None):
    """모드 B 생성 — 같은 GEN_LOCK(B4.BAN 전역을 쓴다)."""
    with GEN_LOCK:
        return _plan_user(kw, day, form, progress)


def _plan_user(kw, day, form, progress=None):
    """자사 데이터로 하루 운전표(계획). 엔진 = W2-외부판(x7_w2ext.feats_power_only) + 받음 금지 LP(b4.plan_scen_ban).
    계획은 전날까지의 자료만으로 만든다 — 그 날 실측은 쓰지 않는다. 화면·이동표·브리핑·종이는 '예상'(시나리오 평균 기준) 두 선.
    그 날 실측 96칸이 자료에 있을 때만 realized(사후 채점용)를 함께 돌려준다. day 는 자료 마지막 날 다음 날이어도 된다."""
    import x7_w2ext as X7
    say = progress or (lambda *a: None)
    day = pd.Timestamp(day).normalize(); t0 = time.perf_counter()
    D = F11.day_matrix(kw[kw.index < day])                    # 전날까지(완전한 날만) — 시나리오·특징·중앙값 모두 과거 날만
    if not D:
        raise ValueError("전날까지의 완전한 날(96칸)이 없습니다")
    Fx = X7.feats_power_only(D)
    prev = D.get(day - pd.Timedelta(days=7))
    prev = prev if prev is not None else D.get(day - pd.Timedelta(days=14))
    Fx[day] = np.array([np.nan] * 6 + [float(np.argmax(prev)) if prev is not None else np.nan])   # feats_power_only 와 같은 규칙(그 날 자료 불필요)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)          # 없는 특징(NaN 열)의 표준편차 경고 — F21.scale 이 1.0 으로 바꾼다
        sd = F21.scale(Fx, day)
    idx = pd.date_range(day, periods=96, freq="15min")
    s, L = float(form["s"]), int(form["L_hours"]) * 4
    cap = F24.CAP * (max(float(np.max(v)) for v in D.values()) / SOURCES["N1"]["how"]()) if form.get("cap_scale", True) else F24.CAP   # 받음 상한을 공장 규모에 비례
    opt = re.search(r"선택[ⅠⅡⅢ]", form.get("tariff") or "")
    pr = F14.price(idx, opt.group() if opt else "선택Ⅰ")
    ban = ban_from_form(form)
    t = time.perf_counter(); S = F24.scen_sets(D, Fx, sd, day)["AB"]; sec1 = time.perf_counter() - t
    say("1/3 유사일 검색", sec1, f"시나리오 {len(S)}일")
    fallback = 0
    if len(S) >= 2:
        Ys = np.array([D[x] for x in S], float)
    else:
        f0 = F11.naive(D, day, "med")
        if f0 is None:
            raise ValueError("같은 요일 직전 4주 자료가 없어 시나리오를 만들 수 없습니다")
        Ys, fallback = np.array([f0], float), 1                # 시나리오 1일 이하 → 직전 4주 중앙값 한 줄(받음 금지는 그대로 지킨다)
    try:
        B4.BAN = ban
        t = time.perf_counter()
        X = B4.plan_scen_ban(Ys, s, cap, L, pr, "mean")
        sec2 = time.perf_counter() - t
    finally:
        B4.BAN = set()
    say("2/3 작업 일정 최적화(받음 금지 칸 적용)", sec2, f"금지 {len(ban)}/96칸")
    shift = lambda y: (1 - s) * y + (s * y) @ X

    def check(y, out, what):
        if ban:
            inc = (out - y)[sorted(ban)]
            assert inc.max() <= 1e-6, f"{what}: 받음 금지 칸에 부하가 들어왔다(+{inc.max():.3f}kW)"
        assert abs(out.sum() - y.sum()) < 1e-6 * max(1.0, y.sum()), f"{what}: 일 에너지 불보존"
        return out
    ybar = Ys.mean(0)
    expected = check(ybar, shift(ybar), "예상")
    full = F11.day_matrix(kw[(kw.index >= day) & (kw.index < day + pd.Timedelta(days=1))])
    y = full.get(day)
    realized = check(y, shift(y), "실현") if y is not None else None
    say("3/3 운전표", 0.0, "예상 = 시나리오 평균 기준")
    return {"day": day, "index": idx, "base": ybar, "plans": {MODE_WIN: expected}, "X": X, "measured": y, "realized": realized,
                "scen_days": list(S), "scen": Ys, "ban": {MODE_WIN: float(len(ban))}, "ban_slots": sorted(ban), "fallback": fallback,
                "s": s, "cap": cap, "secs": {"유사일 검색": sec1, "최적화": sec2}, "total_sec": time.perf_counter() - t0}


def score_user(res, actual_kw):
    """채점(다음 날 실측을 넣었을 때만): 같은 이동 행렬 X 를 그 날 실측에 적용한 사후 평가."""
    y = F11.day_matrix(actual_kw).get(res["day"])
    if y is None:
        raise ValueError(f"{res['day']:%Y-%m-%d} 의 15분 실측 96칸이 없습니다")
    s = res["s"]; out = (1 - s) * y + (s * y) @ res["X"]
    if res["ban_slots"]:
        assert (out - y)[res["ban_slots"]].max() <= 1e-6, "실현: 받음 금지 칸에 부하가 들어왔다"
    assert abs(out.sum() - y.sum()) < 1e-6 * max(1.0, y.sum()), "실현: 일 에너지 불보존"
    return {"measured": y, "realized": out}


def tariff_user(form, before_peak, after_peak, index, measured, plan):
    """산식만(연 환산 없음): 기본요금 Δ = (전 − 후) × 단가 · 전력량 Δ = Σ(후−전)/4 × 시간대 단가(그 날 계절)."""
    if form.get("tariff", "").startswith("모른다") or not form.get("tariff"):
        return None
    t = K7.tariff(); opt = re.search(r"선택[ⅠⅡⅢ]", form["tariff"]).group()
    u = t[t["선택"] == opt].set_index("계절")
    base_rate = float(t[t["선택"] == opt]["기본요금_원per_kW"].iloc[0])
    pr = np.array([u.loc[K7.season(ts.month), K7.band(ts)] for ts in index], float)
    return {"요금제": form["tariff"], "기본요금_단가": base_rate, "기본요금_월_차": round((after_peak - before_peak) * base_rate),
                "전력량_일_차": round(float(((plan - measured) / 4 * pr).sum())), "주의": "산식값 — 요금적용전력은 산정월 6개월 최대로 정해지므로 이 달 피크만으로 확정되지 않는다"}


def steel_example():
    import f12_external_steel as F12
    kw, _ = F12.load_steel()
    return kw.rename("kw")
