# K7 — 한전 요금표(전 계절·시간대)로 주 데이터의 에너지비용을 원 단위로 계산한다.
#  (1) 청구 기준 월 최대: 요금적용전력은 중간·최대부하 시간대의 최대수요전력만 대상(한전 요금표 주석),
#      공휴일은 경부하로 계량 → 하루 전체 최대(보고서의 '월 최대')와 다를 수 있다.
#  (2) 요금제 진단: 1~9월 실측 부하에 산업용(을) 고압A 선택Ⅰ·Ⅱ·Ⅲ를 적용한 비용(가정 없음, 단 요금적용전력은 근사).
#  (3) 전일 운전표(P5)의 전력량요금 효과: 테스트 14일 계획(f11_plan_test.csv)의 실현 부하 vs 실측, s별 원 단위.
# 입력: build/main_15min.csv · build/f11_plan_test.csv · data/ext/kepco_tariff_industrial_eul_HVA_20231109.csv
# 출력: build/table_k7_billing_peak.csv · table_k7_option.csv · table_k7_p5_energy.csv
# 실행: python -X utf8 k7_tariff_cost.py
# 가정(보고서에 그대로 적는다): 요금표는 2023-11-09 시행분(데이터는 2021년) · 부가세·기금·기후환경/연료비조정요금 제외 ·
#   kW 단위 가정(가이드북 단위 미표기) · 15분 값 kW × 0.25h = kWh · 요금적용전력은 '당월과 직전 12개월 중 12·1·2·7·8·9월
#   최대' 근사(약관 제68조 원문 미확인, 데이터에 2020년 12월이 없어 관측 범위 안에서만) · 계약전력 하한 규정 미반영.
import pathlib
import pandas as pd

HERE = pathlib.Path(__file__).parent
B = HERE / "build"
TAR = HERE / "data" / "ext" / "kepco_tariff_industrial_eul_HVA_20231109.csv"
# 2021년 1~9월 관공서 공휴일(일요일 제외 평일·토요일분, 대체공휴일 포함) — 관공서의 공휴일에 관한 규정 기준, 임시공휴일 없음
HOLI = pd.to_datetime(["2021-01-01", "2021-02-11", "2021-02-12", "2021-03-01", "2021-05-05", "2021-05-19",
                       "2021-08-16", "2021-09-20", "2021-09-21", "2021-09-22"]).date


def season(m):
    return "여름" if m in (6, 7, 8) else ("겨울" if m in (11, 12, 1, 2) else "봄가을")


def band(ts):
    """한전 계절별 시간대(현행). 일요일·공휴일 → 경부하, 토요일 최대부하 → 중간부하."""
    h, m = ts.hour, ts.month
    if ts.weekday() == 6 or ts.date() in HOLI or h >= 22 or h < 8:
        return "경부하"
    if season(m) == "겨울":
        b = "최대부하" if (9 <= h < 12 or 16 <= h < 19) else "중간부하"
    else:
        b = "최대부하" if (h == 11 or 13 <= h < 18) else "중간부하"
    return "중간부하" if (b == "최대부하" and ts.weekday() == 5) else b


def tariff():
    t = pd.read_csv(TAR, encoding="utf-8")
    t["선택"] = t["요금제"].str.extract(r"(선택[ⅠⅡⅢ])")[0]
    t["계절"] = t["계절"].str.extract(r"^(여름|봄가을|겨울)")[0]
    return t


def energy_cost(df, col, t, opt):
    u = t[t["선택"] == opt].set_index("계절")
    price = [u.loc[season(ts.month), b] for ts, b in zip(df.ts, df.band)]
    v = df[col].to_numpy() * 0.25 * pd.Series(price).to_numpy()
    return float(pd.Series(v).sum(skipna=True))  # 손상 제거된 7/13·7/15(192슬롯 결측)는 합에서 빠진다


def main():
    d = pd.read_csv(B / "main_15min.csv", encoding="utf-8-sig", parse_dates=["ts"])
    d["band"] = [band(x) for x in d.ts]
    d["M"] = d.ts.dt.month
    t = tariff()

    # (1) 청구 기준 월 최대
    bill = d[d.band != "경부하"].groupby("M").kw.max()
    rows = []
    for m, g in d.groupby("M"):
        i = g.kw.idxmax()
        rows.append({"월": m, "하루전체_최대kW": g.kw.max(), "그_시각": d.ts[i].strftime("%m-%d %H:%M"),
                     "그_시간대": d.band[i], "청구기준_최대kW(중간·최대부하)": bill.get(m)})
    bp = pd.DataFrame(rows)
    # 요금적용전력 근사: 당월과 관측된 12·1·2·7·8·9월 중 당월 이전 값의 최대
    win = {1, 2, 7, 8, 9, 12}
    bp["요금적용전력_근사kW"] = [max([bill[m]] + [bill[k] for k in bill.index if k < m and k in win]) for m in bp["월"]]
    bp.to_csv(B / "table_k7_billing_peak.csv", index=False, encoding="utf-8-sig")

    # (2) 요금제 진단(1~9월)
    opt_rows = []
    for opt in ["선택Ⅰ", "선택Ⅱ", "선택Ⅲ"]:
        base = int(t[t["선택"] == opt]["기본요금_원per_kW"].iloc[0])
        basic = sum(bp["요금적용전력_근사kW"] * base)
        en = energy_cost(d, "kw", t, opt)
        opt_rows.append({"요금제": f"산업용(을) 고압A {opt}", "기본요금_원per_kW": base, "기본요금합_원": round(basic),
                         "전력량요금합_원": round(en), "합계_원(1~9월)": round(basic + en)})
    op = pd.DataFrame(opt_rows)
    op["최저안_대비_원"] = op["합계_원(1~9월)"] - op["합계_원(1~9월)"].min()
    kwh = d.kw.sum(skipna=True) * 0.25
    op["사용시간(h,1~9월)"] = round(kwh / bp["요금적용전력_근사kW"].max(), 1)
    op.to_csv(B / "table_k7_option.csv", index=False, encoding="utf-8-sig")

    # (3) 전일 운전표의 전력량요금 효과(테스트 14일)
    p = pd.read_csv(B / "f11_plan_test.csv", encoding="utf-8-sig", parse_dates=["ts"])
    p["band"] = [band(x) for x in p.ts]
    er = []
    for s, g in p.groupby("s"):
        for opt in ["선택Ⅰ", "선택Ⅱ", "선택Ⅲ"]:
            before, after = energy_cost(g, "실측", t, opt), energy_cost(g, "실현", t, opt)
            mv = ((g.실현 - g.실측) * 0.25).groupby(g.band).sum()
            er.append({"s": s, "요금제": opt, "전력량요금_전_원": round(before), "후_원": round(after),
                       "차이_원(14일)": round(after - before), "월환산_원(×30/14)": round((after - before) * 30 / 14),
                       "최대부하_kWh변화": round(mv.get("최대부하", 0), 1), "중간부하_kWh변화": round(mv.get("중간부하", 0), 1),
                       "경부하_kWh변화": round(mv.get("경부하", 0), 1),
                       "청구기준_최대_전kW": g[g.band != "경부하"].실측.max(), "청구기준_최대_후kW": g[g.band != "경부하"].실현.max()})
    pe = pd.DataFrame(er)
    pe.to_csv(B / "table_k7_p5_energy.csv", index=False, encoding="utf-8-sig")
    print(bp.to_string(index=False)); print(op.to_string(index=False)); print(pe.to_string(index=False))
    check(d, p, pe)


def check(d, p, pe):
    # 일 에너지 보존(운전표는 옮길 뿐) — 위반이면 전력량요금 차이가 '절감'이 아니라 '사용량 감소'가 된다
    day = p.assign(dt=p.ts.dt.date).groupby(["s", "dt"])[["실측", "실현"]].sum()
    assert (day.실측 - day.실현).abs().max() < 0.01, "일 에너지 불보존"  # CSV 소수 3자리 반올림 허용
    assert set(d.band.unique()) == {"경부하", "중간부하", "최대부하"}
    assert band(pd.Timestamp("2021-07-17 14:00")) == "중간부하"   # 토요일 최대부하 → 중간
    assert band(pd.Timestamp("2021-09-21 10:00")) == "경부하"     # 추석 공휴일
    assert band(pd.Timestamp("2021-01-04 10:00")) == "최대부하"   # 겨울 평일 10시
    assert band(pd.Timestamp("2021-07-05 10:00")) == "중간부하"   # 여름 평일 10시
    print("check OK — 일 에너지 보존 · 시간대 판정 4건")


if __name__ == "__main__":
    main()
