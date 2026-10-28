# ops_ingest.py — G6 폴더 감시 자동 입력(Track G-C). PRD KAMP_제6회_PRD_대상권돌파_TrackG_20261028.md §1 G6 ①.
# 설정한 폴더(계량기 펄스 장치·CT 로거가 내보내는 CSV — F13 §1 경로 ②③)에서 최신 CSV를 18:00 기준으로 읽어 15분 kW로 바꾼다.
# 열 이름 매핑은 처음 한 번 추정·저장(ops_ingest_config.json)하고, 그 뒤로는 저장한 매핑만 쓴다.
# 규칙: viewer_ops.py·ops_service.py 는 import 만 한다(고치지 않는다). build/·trackB/ 쓰기 0. 네트워크 0.
#       쓰는 파일은 설정 파일 하나(save_config). 실제 장치 연동은 시험하지 않았다 — CSV 폴더 규격으로만 시험.
import hashlib
import json
import pathlib

import numpy as np
import pandas as pd

import ops_service as O

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = HERE / "ops_ingest_config.json"
DEMO_INBOX = HERE / "_inbox_demo"                       # 시연용 폴더(로거 내보내기 모양의 CSV — make_demo_inbox 가 만든다)
CUTOFF = "18:00"                                         # 전날 18:00 마감(보고서 69·102쪽)
TIME_NAMES = ("timestamp", "ts", "datetime", "date", "time", "시각", "일시", "측정일시", "측정 시각", "date/time", "기록시각", "저장일시")
# 장치 규격(H8, 매뉴얼 기준·실기기 미시험). stamp: 시각 열이 구간 시작(start)인지 끝(end)인지 · dup: 같은 시각 중복 행을 버림(drop)/합산(sum)
PROFILES = {
    "DIU-310-S(DIU-Manager 엑셀 저장)": {          # 서창전기통신 DIU-310-S 사용자 매뉴얼 20160112-0001 p.34·38(그림 24)·p.35(중복 저장 합산)
        "pattern": "*.xlsx", "time_col": "저장일시", "kw_col": "15분 전력사용량(kWh)", "unit": "kWh/15분", "stamp": "end", "dup": "sum"},
}
KW_NAMES = ("kw", "전력", "load", "power", "최대수요전력", "유효전력", "유효전력[kw]", "유효전력(kw)", "p[kw]", "p(kw)", "active power[kw]", "active power")
KWH_HINTS = ("kwh", "usage", "전력량", "적산")


def default_config():
    return {"folder": str(DEMO_INBOX), "pattern": "*.csv", "time_col": None, "kw_col": None, "unit": None, "cutoff": CUTOFF}


def load_config(path=CONFIG):
    if pathlib.Path(path).exists():
        with open(path, encoding="utf-8") as fh:
            return {**default_config(), **json.load(fh)}
    return default_config()


def save_config(cfg, path=CONFIG):
    """설정 파일 하나만 쓴다(폴더·패턴·열 매핑·마감 시각)."""
    pathlib.Path(path).write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def _norm(c):
    return str(c).strip().lower().replace(" ", "")


def guess_mapping(columns):
    """열 이름 → (시각 열, 전력 열, 단위). 처음 한 번만 쓰고 결과는 설정에 저장한다. 못 찾으면 ValueError."""
    cols = list(columns)
    n = {_norm(c): c for c in cols}
    tcol = next((n[k] for k in n if k in {_norm(x) for x in TIME_NAMES}), None)
    kcol = next((n[k] for k in n if k in {_norm(x) for x in KW_NAMES}), None)
    unit = "kW"
    if kcol is None:
        kcol = next((n[k] for k in n if any(h in k for h in KWH_HINTS)), None)
        unit = "kWh/15분" if kcol is not None else unit
    if kcol is None:
        kcol = next((n[k] for k in n if "kw" in k and "kwh" not in k), None)
    if tcol is None or kcol is None:
        raise ValueError(f"열 매핑을 정하지 못했습니다 — 시각 열·전력 열 이름을 설정에 적어 주십시오(열: {cols})")
    return {"time_col": str(tcol), "kw_col": str(kcol), "unit": unit}


def _csv(path):
    """CSV(utf-8/cp949) 또는 엑셀(.xlsx — 장치 관리 프로그램 '엑셀로 저장'). 셀 값은 글자 그대로 읽고 숫자 변환은 뒤에서."""
    if pathlib.Path(path).suffix.lower() in (".xlsx", ".xlsm"):
        return pd.read_excel(path, dtype=str)
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{pathlib.Path(path).name}: 인코딩을 읽지 못했습니다(utf-8·cp949)")


def _span(path, cfg=None):
    """파일의 첫·마지막 시각(설정의 시각 열, 없으면 매핑 추정). 읽지 못하면 None."""
    try:
        d = _csv(path)
        tc = (cfg or {}).get("time_col") or guess_mapping(d.columns)["time_col"]
        t = pd.to_datetime(d[tc], errors="coerce").dropna()
        return (t.min(), t.max()) if len(t) else None
    except (ValueError, KeyError):
        return None


def files_as_of(folder, pattern="*.csv", now=None, cfg=None):
    """폴더의 CSV 중 now 시각에 이미 있었을 파일(첫 시각 < now)을 마지막 시각 순으로. now=None 이면 전부."""
    out = []
    for p in sorted(pathlib.Path(folder).glob(pattern)):
        sp = _span(p, cfg)
        if sp is None:
            continue
        if now is None or sp[0] < pd.Timestamp(now):
            out.append((sp[1], p.stat().st_mtime, p))
    return [p for *_k, p in sorted(out)]


def latest_csv(folder, pattern="*.csv", now=None, cfg=None):
    f = files_as_of(folder, pattern, now, cfg)
    return f[-1] if f else None


def read_mapped(path, cfg, now=None):
    """매핑대로 읽어 15분 kW Series. now 가 있으면 그 시각 전 칸만(장치가 그때까지 내보냈을 칸). kWh/15분이면 ×4."""
    d = _csv(path)
    mp = cfg if cfg.get("time_col") and cfg.get("kw_col") else {**cfg, **guess_mapping(d.columns)}
    missing = [c for c in (mp["time_col"], mp["kw_col"]) if c not in d.columns]
    if missing:
        raise ValueError(f"{pathlib.Path(path).name}: 설정한 열 {missing} 이 파일에 없습니다(열: {list(d.columns)})")
    vcol = "kWh" if mp.get("unit") == "kWh/15분" else "kw"
    df = pd.DataFrame({"timestamp": pd.to_datetime(d[mp["time_col"]], errors="coerce"),
                       vcol: pd.to_numeric(d[mp["kw_col"]].astype(str).str.strip().str.lstrip("'").str.replace(",", ""), errors="coerce")}).dropna()
    if mp.get("stamp") == "end":                         # 구간 끝 시각(EOI) → 구간 시작 시각(앱·엔진 규칙)
        df["timestamp"] = df["timestamp"] - pd.Timedelta(minutes=15)
    if mp.get("dup") == "sum":                           # 시간 동기화 중복 저장은 합산(장치 매뉴얼). 그 밖은 read_user_csv 가 첫 행만 남긴다
        df = df.groupby("timestamp", as_index=False)[vcol].sum()
    if now is not None:
        df = df[df.timestamp < pd.Timestamp(now)]
    if df.empty:
        raise ValueError(f"{pathlib.Path(path).name}: {now} 전 칸이 없습니다")
    kw, info = O.read_user_csv(df)                       # 같은 규칙(단위 변환·15분 재표본·복제일)으로
    return kw, info, mp


def ingest(cfg=None, now=None, history=False):
    """폴더 감시 1회 — 설정 폴더의 최신 CSV를 읽는다. 반환 dict(file, sha, mapping, kw, rows, start, end, cutoff_ok).
    history=True 면 now 전까지 있었을 파일을 모두 이어 붙인다(모드 B 계획에 필요한 과거 날).
    now 가 마감 시각(18:00) 전이면 상태 '대기'만 돌려준다(파일을 읽지 않는다)."""
    cfg = cfg or load_config()
    folder = pathlib.Path(cfg["folder"])
    if not folder.is_dir():
        return {"status": "폴더 없음", "folder": str(folder)}
    if now is not None:
        hh, mm = map(int, cfg.get("cutoff", CUTOFF).split(":"))
        if pd.Timestamp(now).time() < pd.Timestamp(now).replace(hour=hh, minute=mm).time():
            return {"status": "대기", "folder": str(folder), "note": f"마감 {cfg.get('cutoff', CUTOFF)} 전"}
    files = files_as_of(folder, cfg.get("pattern", "*.csv"), now, cfg)
    if not files:
        return {"status": "파일 없음", "folder": str(folder)}
    use = files if history else files[-1:]
    parts, mp = [], cfg
    for p in use:
        kw, _i, mp = read_mapped(p, mp, now)
        parts.append(kw)
    kw = pd.concat(parts).sort_index()
    kw = kw[~kw.index.duplicated(keep="last")]
    last = files[-1]
    return {"status": "읽음", "folder": str(folder), "file": last.name, "files": [p.name for p in use],
            "sha": hashlib.sha256(last.read_bytes()).hexdigest(), "mapping": {k: mp[k] for k in ("time_col", "kw_col", "unit")},
            "kw": kw, "rows": int(len(parts[-1])), "start": str(parts[-1].index.min()), "end": str(parts[-1].index.max())}


def check_against_engine(kw):
    """모드 A 대조 — 자동 입력값이 엔진 입력(build/main_15min.csv, common.load)과 같은 시각에서 같은지. 저장본 읽기만."""
    a = O.load()["kw"]
    j = pd.concat([a.rename("a"), kw.rename("b")], axis=1, join="inner").dropna()
    diff = float(np.abs(j.a - j.b).max()) if len(j) else float("nan")
    return {"n": int(len(j)), "of": int(len(kw)), "maxdiff": diff, "ok": bool(len(j) == len(kw) and len(j) and diff < 1e-6)}


def make_demo_inbox(folder=DEMO_INBOX, days=None):
    """시연용 폴더 — A사 테스트 기간의 하루 하나씩을 로거 내보내기 모양(열 이름 '측정일시','유효전력[kW]')으로.
    값은 build/main_15min.csv 그대로(복사). build/ 는 읽기만 한다."""
    folder = pathlib.Path(folder); folder.mkdir(parents=True, exist_ok=True)
    kw = O.load()["kw"]
    days = list(days if days is not None else O.TEST_DAYS)
    for d in days:
        s = kw[(kw.index >= d) & (kw.index < d + pd.Timedelta(days=1))]
        out = pd.DataFrame({"측정일시": s.index.strftime("%Y-%m-%d %H:%M"), "유효전력[kW]": s.values})
        out.to_csv(folder / f"meter_{pd.Timestamp(d):%Y%m%d}.csv", index=False, encoding="utf-8-sig")
    return folder
