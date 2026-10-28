# F19 — 블라인드 검증: 전일 운전표 v2를 한국 단조공장 2곳(2019-04~09)에 재조정 없이 적용.
# 규칙은 prereg_F19_kr_blind_20261006.md에 실행 전에 고정했고, 그 파일의 SHA256이 아래 PREREG_SHA와 같을 때만 실행한다.
# 정책 함수는 f14_schedule_v2·closed_loop_core의 것을 그대로 부른다. 공장별로 달라지는 값은 cap 환산 규칙(20/204 × 직전 달 최대) 하나뿐.
# 단위가 불명확하므로 지표는 전부 비율. 실행: python -X utf8 f19_kr_blind.py [--mutate N] → build/table_f19_kr.csv · table_f19_kr_summary.csv
import sys, hashlib, pathlib, datetime
import numpy as np, pandas as pd
from common import B
from closed_loop_core import calendar
import f14_schedule_v2 as F14
import f11_dayahead as F11
import k7_tariff_cost as K7

PREREG = B / "prereg_F19_kr_blind_20261006.md"
PREREG_SHA = "95e7de0ee311fde7347c7d02c01d624ad409fdbf4716363134ec8623265189a3"
ZIP_SHA = "f8794dc10e8892ead63f431eb55c6a4d6c6411c09a3d58aa29a07c54a14b57fc"
KR = B / "data/ext/korea_factory"
FORGES = ["Forge_1", "Forge_2"]
MONTHS = [4, 5, 6, 7, 8, 9]
S_LIST = [0.10, 0.1295, 0.337]
S_HEAD = 0.1295
HOL19 = pd.to_datetime(["2019-03-01", "2019-05-06", "2019-06-06", "2019-08-15", "2019-09-12", "2019-09-13"]).date
OUT, OUT_S, LOG = B / "build/table_f19_kr.csv", B / "build/table_f19_kr_summary.csv", B / "build/f19_run.log"
V2 = "P5v2 B ±4h·TOU"
MUT = 0


def series(f):
    q = pd.read_csv(KR / f"{f}_15min.csv", encoding="utf-8-sig", index_col=0, parse_dates=True)["u15"]
    return q


def complete_days(q):
    return {d: g.values for d, g in q.groupby(q.index.normalize()) if len(g) == 96 and g.notna().all()}


def cap_for(q, m):
    prev = q[(q.index.month == m - 1)] if MUT != 2 else q[q.index.month == m]   # 재삽입 2: 같은 달 최대로 cap(평가 구간 누설)
    return 20.0 / 204.0 * float(prev.max())


def run_month(q, D, m, s):
    days = [pd.DataFrame(dict(y=v), index=pd.date_range(d, periods=96, freq="15min")) for d, v in D.items() if d.month == m]
    fc = {g.index[0].normalize(): F11.naive(D, g.index[0].normalize(), "med") for g in days}
    cap = cap_for(q, m)
    y0 = [g["y"].values * 1.0 for g in days]
    o2, _, nop, mv = F14.run_variant(days, fc, s, cap, 16, True, False)
    if MUT == 4:
        o2 = [x * 0.97 for x in o2]                                 # 재삽입 4: 에너지 비보존
    out = {"P0 현행": y0, "P1 달력 규칙": [calendar(g, s) for g in days], V2: o2,
           "P3b 오라클 ±4h(실측, LP)": [F14.oracle_L(g, s, 16) for g in days]}
    return days, out, cap, nop, mv


def main():
    global MUT
    if "--mutate" in sys.argv:
        MUT = int(sys.argv[sys.argv.index("--mutate") + 1])
    ph = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    if ph != (PREREG_SHA if MUT != 1 else "0" * 64):                # 재삽입 1: 등록값이 다르면 거부되어야 한다
        raise SystemExit(f"[거부] 사전등록 파일 SHA256 {ph[:16]}… ≠ 등록값 — 규칙이 바뀌었다")
    assert hashlib.sha256((KR / "Data_list.zip").read_bytes()).hexdigest() == ZIP_SHA, "원자료 SHA256 불일치"
    if MUT != 3:
        K7.HOLI = HOL19                                             # 2019 공휴일을 경부하로(재삽입 3: 빠뜨린다)
    rows, cache = [], {}
    for f in FORGES:
        q = series(f); D = complete_days(q)
        for m in MONTHS:
            for s in S_LIST:
                days, out, cap, nop, mv = run_month(q, D, m, s)
                cache[(f, m, s)] = (days, out, cap)
                y0 = out["P0 현행"]; p0 = float(np.array(y0).max()); c0 = F14.cost(y0, days, "선택Ⅰ"); e0 = sum(x.sum() for x in y0)
                for k, v in out.items():
                    rows.append(dict(공장=f, 월=m, s=s, 정책=k, 평가일=len(days), cap=round(cap, 3), 무계획일=nop if k == V2 else 0,
                                     월최대=round(float(np.array(v).max()), 3), 월최대_변화율=round(float(np.array(v).max()) / p0 - 1, 4),
                                     청구기준월최대=round(F14.bill_max(days, v), 3),
                                     전력량요금지수_변화율=round(F14.cost(v, days, "선택Ⅰ") / c0 - 1, 4),
                                     이동에너지비중=round(mv / (e0 / 4), 4) if k == V2 else np.nan))
            print(f"  {f} {m}월 완료 · 평가 {len(days)}일", flush=True)
    R = pd.DataFrame(rows)
    S = summarize(R)
    check(R, cache)
    if MUT:
        print(f"[재삽입 {MUT}] self-check 통과 — 검사가 이 결함을 못 본다"); return
    R.to_csv(OUT, index=False, encoding="utf-8-sig"); S.to_csv(OUT_S, index=False, encoding="utf-8-sig")
    n = len(LOG.read_text(encoding="utf-8").splitlines()) + 1 if LOG.exists() else 1   # 덮어쓰지 않고 덧붙인다 — 재실행도 기록에 남긴다
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} · prereg SHA256 {ph} · 원자료 {ZIP_SHA[:16]}… · 실행 {n}회차"
                 f"{' (재현 실행 — 설정 불변)' if n > 1 else ''}\n")
    pd.set_option("display.width", 250)
    pv = R[R.s == S_HEAD].pivot_table(index=["공장", "월"], columns="정책", values="월최대_변화율")
    print((pv * 100).round(1).to_string()); print(); print(S.to_string(index=False))
    print(f"→ {OUT.relative_to(B)} · {OUT_S.relative_to(B)} · {LOG.relative_to(B)}")


def summarize(R):
    rows = []
    for s in S_LIST:
        E = R[np.isclose(R.s, s)]
        w = lambda f, m, k: float(E[(E.공장 == f) & (E.월 == m) & (E.정책 == k)]["월최대"].iloc[0])
        below_p0 = sum(w(f, m, V2) < w(f, m, "P0 현행") for f in FORGES for m in MONTHS)
        below_p1 = sum(w(f, m, V2) < w(f, m, "P1 달력 규칙") for f in FORGES for m in MONTHS)
        rat = {}
        for f in FORGES:
            bm = lambda k: max(float(E[(E.공장 == f) & (E.월 == m) & (E.정책 == k)]["청구기준월최대"].iloc[0]) for m in (7, 8, 9))
            rat[f] = (bm(V2) / bm("P0 현행") - 1, bm("P1 달력 규칙") / bm("P0 현행") - 1, bm("P3b 오라클 ±4h(실측, LP)") / bm("P0 현행") - 1)
        both = all(rat[f][0] < 0 for f in FORGES)
        per_f = {f: sum(w(f, m, V2) < w(f, m, "P0 현행") for m in MONTHS) for f in FORGES}
        verdict = ("성공" if (below_p0 >= 9 and both) else
                   "실패" if all(per_f[f] < 3 for f in FORGES) else "부분 성공")
        med = float(np.median([w(f, m, V2) / w(f, m, "P0 현행") - 1 for f in FORGES for m in MONTHS]))
        rows.append(dict(s=s, v2가_현행보다_낮은_공장월=f"{below_p0}/12", v2가_고정시간대규칙보다_낮은_공장월=f"{below_p1}/12",
                         월최대_변화율_중앙=round(med, 4),
                         **{f"{f}_요금적용전력근사_변화율(v2·P1·사후최적)": " · ".join(f"{x * 100:+.1f}%" for x in rat[f]) for f in FORGES},
                         판정=verdict if np.isclose(s, S_HEAD) else "(보조)"))
    return pd.DataFrame(rows)


def check(R, cache):
    # 1. 에너지 보존(이월 없음 → 일 합) · 2. 오라클 하한 · 3. cap = 20/204 × 직전 달 최대 · 4. 2019 공휴일이 경부하
    for (f, m, s), (days, out, cap) in cache.items():
        for k, v in out.items():
            assert np.allclose([x.sum() for x in v], [g["y"].sum() for g in days], atol=1e-6), f"{f} {m}월 s={s} {k}: 일 에너지 불보존"
        assert np.array(out[V2]).max() >= np.array(out["P3b 오라클 ±4h(실측, LP)"]).max() - 1e-6, f"{f} {m}월: 오라클 하한 위반"
        q = series(f)
        assert abs(cap - 20.0 / 204.0 * float(q[q.index.month == m - 1].max())) < 1e-9, f"{f} {m}월: cap이 직전 달 최대로 환산되지 않았다"
    assert K7.band(pd.Timestamp("2019-06-06 14:00")) == "경부하" and K7.band(pd.Timestamp("2019-06-05 14:00")) == "최대부하", "2019 공휴일 계량 누락"
    # 5. 정책 함수가 주 데이터의 것과 같은 객체(여기서 다시 정의하지 않았다)
    assert F14.run_variant.__module__ == "f14_schedule_v2" and calendar.__module__ == "closed_loop_core"
    # 6. 평가 달은 4~9월, s 집합은 사전등록 그대로
    assert set(R.월) == set(MONTHS) and sorted(set(R.s)) == sorted(S_LIST)
    print("self-check OK (1 에너지 보존 · 2 오라클 하한 · 3 cap = 직전 달 · 4 2019 공휴일 · 5 정책 함수 동일 · 6 등록 범위)")


if __name__ == "__main__":
    main()
