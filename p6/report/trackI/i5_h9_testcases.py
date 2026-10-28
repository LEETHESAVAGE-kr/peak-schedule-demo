# I5 — G-C H9 '0단계(고지서)' 화면의 시험 케이스 6개와 기대 출력. 규칙은 I2 §1(봉인 d8948add…) 그대로, 단가는 2023-11-09판(I6와 같은 경로).
# 실제 공장 케이스(A사·EnerNOC 673·690·786)는 I3 월 지표(table_i3_bill_metrics.csv)에서 그대로 옮기고, 가상 케이스 2개는 '가상' 라벨.
# 출력: build/table_i5_h9_testcases.csv · trackI/_i5_run.log
import sys, json
from pathlib import Path
import numpy as np, pandas as pd

B = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(B)); sys.path.insert(0, str(Path(__file__).parent))
import i3_bill_metrics as I3
import i6_tariff_choice as I6

OUT, LOG = B / "build/table_i5_h9_testcases.csv", B / "report/trackI/_i5_run.log"
SUM = json.load(open(B / "report/trackI/_i3_summary.json", encoding="utf-8"))
F3 = pd.read_csv(B / "build/table_i3_prescreen_vs_verdict.csv", encoding="utf-8-sig")
R4_REF, R5_REF = F3.R4값.dropna().values, F3.R5값.dropna().values      # 31곳 기준 분포(I3)
lines = []


def log(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)


def h9(case):
    """입력 5칸 → 출력 4개 + 다음 행동. months: {월: (D_m, kWh경, kWh중, kWh최)} — 최대 12개."""
    C, plan_now, P_bill, M = case["계약전력"], case["요금제"], case["요금적용전력"], case["월"]
    if len(M) < 3:
        return dict(요금제="판정 불가(고지서 3장 미만)", 래칫여유kW=np.nan, 효과상한원=np.nan, 선별="판정 불가",
                    다음행동="고지서 12장(또는 파워플래너 '월별 청구요금' 화면)을 모은 뒤 다시 — 그동안 파워플래너 가입·15분 곡선 2개월 확보")
    ms = sorted(M); last = ms[-1]
    rat = [m for m in ms if m in I3.RATCHET]; non = [m for m in ms if m not in I3.RATCHET]
    P_sim = max([M[m][0] for m in rat] + [M[last][0]])
    Pw = P_bill if P_bill else P_sim
    price = 6490 if Pw < 300 else 7220
    # R1
    if C:
        slack = Pw - 0.3 * C; r1 = "효과 없음" if slack <= 0 else "통과"
    else:
        slack, r1 = np.nan, "입력 없음"
    # R2·R3
    if len(rat) >= 3 and len(non) >= 3:
        U = max(0.0, Pw - float(np.median([M[m][0] for m in non]))) * price * 12
        r2 = "효과 없음" if U < I3.EQUIP_MIN else "통과"
    else:
        U, r2 = np.nan, "판정 불가"
    if len(rat) >= 3:                                      # I2 §1: R3는 유효 산정월 ≥ 3이면 계산(R2와 별개)
        mg = [m for m in rat if M[m][0] >= 0.98 * Pw]; r3 = "통과" if len(mg) <= 2 else "주의"
    else:
        r3, mg = "판정 불가", []
    kwh = np.array([M[m][1:] for m in ms], float)
    r4 = kwh[:, 2].sum() / kwh.sum()
    r5 = float(np.std([M[m][0] for m in ms]) / np.mean([M[m][0] for m in ms])) if len(ms) >= 6 else np.nan
    p4 = float((R4_REF <= r4).mean()); p5 = float((R5_REF <= r5).mean()) if np.isfinite(r5) else np.nan
    caution = [n for n, v in [("R3", r3 == "주의"), ("R4", p4 <= 1 / 3), ("R5", np.isfinite(p5) and p5 >= 2 / 3)] if v]
    sel = "효과 없음" if "효과 없음" in (r1, r2) else (f"통과(주의 {','.join(caution)})" if caution else "통과")
    # 요금제 비교(I6 경로, 2023-11-09판) — 같은 종별 안에서
    T = I6.tariffs(); fam = "산업용(갑)Ⅱ" if plan_now.startswith("갑") else "산업용(을)"
    cost = {}
    for name, t in T.items():
        if not name.startswith(fam):
            continue
        run, tot = -np.inf, 0.0
        for m in ms:
            if m in I3.RATCHET:
                run = max(run, M[m][0])
            Pm = P_bill if P_bill else max(run, M[m][0])
            if C:
                Pm = max(Pm, 0.3 * C)                       # 제68조 ① 단서 — 계약전력이 있으면 30% 하한 적용
            tot += Pm * t["base"] + sum(M[m][1 + j] * t["e"][I6.season_of(m)][I6.BN[j]] for j in range(3))
        cost[name.split()[-1]] = round(tot)
    best = min(cost, key=cost.get); now = plan_now.split()[-1]
    tariff = f"{best} 최저" + ("" if best == now else f" — 지금({now})보다 {cost[now] - cost[best]:,}원 싸다({len(ms)}개월)")
    if sel == "효과 없음":
        nxt = "운전표 대신: 요금제 선택 비교" + (f"({best}로 변경 검토)" if best != now else "(지금 요금제 유지)") + " · 계약전력 검토(약관 제14조) · 파워플래너 목표 알림"
    else:
        nxt = "다음 단계: 파워플래너 시간대별 화면에서 15분 곡선 2개월 → 판정(precheck)" + (f" · 관리 대상 달 {','.join(map(str, mg))}월" if mg else "")
    return dict(요금제=tariff, 래칫여유kW=round(slack, 1) if np.isfinite(slack) else np.nan, 효과상한원=round(U) if np.isfinite(U) else np.nan,
                선별=sel, R1=r1, R2=r2, R3=r3, R4=round(r4, 4), R4백분위=round(p4, 3), R5=round(r5, 4) if np.isfinite(r5) else np.nan,
                요금제비교=json.dumps(cost, ensure_ascii=False), 다음행동=nxt)


def from_i3(name):
    M3 = pd.read_csv(B / "build/table_i3_bill_metrics.csv", encoding="utf-8-sig")
    G = M3[(M3.공장 == name) & M3.유효달]
    return {int(r.월): (float(r.D_m), float(r.kWh_경부하), float(r.kWh_중간), float(r.kWh_최대)) for _, r in G.iterrows()}


def main():
    assert I3.sha(I3.RULES) == I3.RULES_SHA
    cases = [
        dict(케이스="T1 A사(실제, 2021 유효 6개월)", 출처="I3 월 지표", 계약전력=None, 요금제="을 선택Ⅰ", 요금적용전력=None, 월=from_i3("A사")),
        dict(케이스="T2 EnerNOC_690(실제, 통과)", 출처="I3 월 지표", 계약전력=None, 요금제="을 선택Ⅰ", 요금적용전력=None, 월=from_i3("EnerNOC_690")),
        dict(케이스="T3 EnerNOC_673(실제, R2 회수 불가)", 출처="I3 월 지표", 계약전력=None, 요금제="갑 선택Ⅰ", 요금적용전력=None, 월=from_i3("EnerNOC_673")),
        dict(케이스="T4 EnerNOC_786(실제, R3 주의)", 출처="I3 월 지표", 계약전력=None, 요금제="을 선택Ⅰ", 요금적용전력=None, 월=from_i3("EnerNOC_786")),
        dict(케이스="T5 가상: 계약전력 1,000kW·월최대 250kW(R1 래칫 하한)", 출처="가상", 계약전력=1000, 요금제="을 선택Ⅰ", 요금적용전력=None,
             월={m: (250.0 - (m % 3) * 5, 40000.0, 30000.0, 15000.0) for m in range(1, 13)}),
        dict(케이스="T6 가상: 고지서 2장(판정 불가)", 출처="가상", 계약전력=300, 요금제="갑 선택Ⅰ", 요금적용전력=None,
             월={7: (200.0, 30000.0, 25000.0, 15000.0), 8: (210.0, 31000.0, 26000.0, 15500.0)}),
    ]
    rows = []
    for c in cases:
        o = h9(c)
        rows.append(dict(케이스=c["케이스"], 출처=c["출처"], 입력_계약전력=c["계약전력"], 입력_요금제=c["요금제"], 입력_요금적용전력=c["요금적용전력"],
                         입력_월수=len(c["월"]), 입력_월=json.dumps({m: [round(x, 2) for x in v] for m, v in sorted(c["월"].items())}), **o))
        log(f"{c['케이스']}: 선별 {o['선별']} · 요금제 {o['요금제']} · 래칫여유 {o['래칫여유kW']} · 상한 {o['효과상한원']} · → {o['다음행동']}")
    T = pd.DataFrame(rows)
    # I3와 같은 공장은 I3 결과와 같아야 한다(R2·R3·R4)
    for name, case in [("A사", "T1"), ("EnerNOC_690", "T2"), ("EnerNOC_673", "T3"), ("EnerNOC_786", "T4")]:
        r = F3[F3.공장 == name].iloc[0]; t = T[T.케이스.str.startswith(case)].iloc[0]
        assert t.R2 == r.R2 and t.R3 == r.R3 and abs(t.R4 - r.R4값) < 1e-4, f"{case} I3 불일치"
        assert (np.isnan(t.효과상한원) and np.isnan(r.U_원)) or abs(t.효과상한원 - r.U_원) < 1, f"{case} U 불일치"
    log("self-check: 실제 4케이스의 R2·R3·R4·U = I3 공장 표와 일치")
    T.to_csv(OUT, index=False, encoding="utf-8-sig")
    log(f"행 수: {OUT.name} {len(T)}")
    LOG.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
