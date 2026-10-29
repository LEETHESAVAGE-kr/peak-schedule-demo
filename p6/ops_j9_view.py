# J9 — 0단계(고지서) 화면: 입력 5칸 + 12개월 붙여넣기 한 칸 → 출력 4개(요금제·래칫 여유·효과 상한·선별) + 다음 행동 한 줄
#       + 판정 결과 카드(①) + 다음 행동 카드(④). 계산은 trackI/i5_h9_testcases.h9() 를 import 만 한다(같은 식, 수정 0).
# 실행 사본 viewer_ops_j9.py 에서만 쓴다(make_run_copy_j9.py). 동결본·viewer_ops*.py·ops_service.py·ops_g6_view.py 는 고치지 않는다.
# 숫자는 h9()·ops_service·build 표에서 온다 — 이 파일의 숫자 리터럴은 레이아웃 값과 입력 칸 기본값뿐이다.
import io
import json
import pathlib
import sys

import numpy as np
import pandas as pd
import streamlit as st

P6 = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P6 / "report" / "trackI"))
import i5_h9_testcases as I5                                   # noqa: E402  h9() — I5 시험 케이스 6행과 같은 경로
import i3_bill_metrics as I3                                    # noqa: E402  장비비 하한(EQUIP_MIN)

TAB = "⓪ 고지서 점검"
PLANS = ["을 선택Ⅰ", "을 선택Ⅱ", "을 선택Ⅲ", "갑Ⅱ 선택Ⅰ", "갑Ⅱ 선택Ⅱ"]          # 갑에는 선택Ⅲ 없음(약관 제67조⑦)
COLS = ["월", "최대수요kW", "경부하kWh", "중간kWh", "최대kWh"]
CASES = P6 / "build" / "table_i5_h9_testcases.csv"
CASE_NAME = {"T1": "A사 고지서(2021년 6개월)", "T2": "외부 공장 690(점검 통과)", "T3": "외부 공장 673(절감액이 장비비보다 작음)",
             "T4": "외부 공장 786(주의 항목 있음)", "T5": "예시: 계약전력 1,000kW·월 최대 250kW", "T6": "예시: 고지서 2장뿐"}
FIXED_TOP = "고지서 12장 또는 파워플래너 '청구내역' 화면의 숫자를 옮겨 적는다(약 30분·비용 없음)."
FIXED_BOTTOM = "고지서 점검은 운전표가 맞지 않는 공장을 미리 거르는 단계다. 적합 여부는 15분 전력으로 따로 판정하고, 운전표는 고지서만으로 만들 수 없다."
NEXT_CARD = {   # I6_next_actions.md §1 표의 '다음 행동' 열(문구만, 숫자 없음)
    "통과": ["파워플래너 '시간대별' 화면에서 15분 전력 2개월을 받아 적합 여부를 판정한다",
             "권장이면 측정 3주 → 모의 운전 2~4주 → 적용 (권장 공장도 3분의 1은 효과가 없거나 악화했으므로 모의 운전을 건너뛰지 않는다)"],
    "효과 없음": ["요금제 선택 비교 — 고지서 12개월로 선택요금별 연 요금을 약관 단가로 다시 계산한다(변경은 1년에 한 번)",
                 "계약전력 검토 — 요금적용전력이 계약전력의 30% 하한에 걸리면 감소를 신청할 수 있다(약관 제14조), 다시 늘리면 부담이 생긴다(제16조)",
                 "디맨드 컨트롤러 — 공조·냉동·펌프 같은 비핵심 부하부터 끄고 생산설비는 끄지 않는다",
                 "파워플래너 최대수요 목표 알림 — 무료, 목표를 처음 넘을 때 한 번 알린다"],
    "판정 불가": ["고지서 점검만 하고 요금제 비교·계약전력 검토를 먼저 한다",
                 "파워플래너에 가입(고객번호 10자리)해 2개월 뒤 15분 전력으로 판정한다"],
}
SAY = [("판정(precheck)", "적합 여부 판정"), ("15분 곡선", "15분 전력"), ("(R3", "(기준 달 피크 집중"), ("R3", "기준 달 피크 집중"), ("R4", "최대부하 시간대 비중 낮음"),
       ("R5", "월 최대 변동 큼"), ("주의 ", "주의: "), ("효과 없음", "절감액이 장비비보다 작음"), ("판정 불가(고지서 3장 미만)", "판정할 수 없음(고지서 3장 미만)"),
       ("판정 불가", "판정할 수 없음"), ("관리 대상 달", "피크 관리가 필요한 달")]


def say(t):
    """h9() 출력 문구(시험 기대값이라 계산 쪽은 그대로)를 화면에 보일 때만 풀어 쓴다."""
    t = str(t)
    for a_, b_ in SAY:
        t = t.replace(a_, b_)
    return t


def case_inputs(row):
    """build/table_i5_h9_testcases.csv 한 행 → h9() 입력."""
    c = None if pd.isna(row["입력_계약전력"]) else float(row["입력_계약전력"])
    p = None if pd.isna(row["입력_요금적용전력"]) else float(row["입력_요금적용전력"])
    m = {int(k): tuple(float(x) for x in v) for k, v in json.loads(row["입력_월"]).items()}
    if str(row["출처"]).startswith("I3"):                       # 실제 공장: I5가 쓴 전정밀 월 지표(표의 JSON은 소수 둘째 자리 반올림)
        m = I5.from_i3(str(row["케이스"]).split()[1].split("(")[0])
    return {"계약전력": c, "요금제": str(row["입력_요금제"]), "요금적용전력": p, "월": m}


def months_to_text(m, nd=None):
    """{월: (D, 경, 중, 최)} → 붙여넣기 칸 문자열(탭 구분, 머리 1줄). nd = 표시 반올림 자리(None이면 전정밀)."""
    f = repr if nd is None else (lambda v: f"{v:.{nd}f}")
    lines = ["\t".join(COLS)] + ["\t".join([str(k)] + [f(v) for v in m[k]]) for k in sorted(m)]
    return "\n".join(lines)


def parse_paste(text):
    """엑셀/CSV 붙여넣기(탭·쉼표 구분, 머리 있음/없음) → {월: (최대수요, 경, 중, 최)}. 칸이 모자라면 ValueError."""
    text = (text or "").strip()
    if not text:
        return {}
    sep = "\t" if "\t" in text else ","
    df = pd.read_csv(io.StringIO(text), sep=sep, header=None, dtype=str)
    if not str(df.iloc[0, 0]).strip().rstrip("월").isdigit():
        df = df.iloc[1:]
    if df.shape[1] < 5:
        raise ValueError("한 줄에 월·최대수요·경부하·중간·최대 kWh 다섯 칸이 있어야 합니다.")
    out = {}
    for r in df.itertuples(index=False):
        k = int(str(r[0]).strip().rstrip("월"))
        if not 1 <= k <= 12:
            raise ValueError(f"월 {k}은 1~12가 아닙니다.")
        out[k] = tuple(float(str(x).replace(",", "").strip()) for x in r[1:5])
    return out


def compute(case):
    """h9() 그대로(계산 함수 — 반환 키 이름은 I5 시험과 같게 둔다)."""
    return I5.h9(case)


def _key(sel):
    return "효과 없음" if sel == "효과 없음" else ("판정 불가" if sel == "판정 불가" else "통과")


def stage0_tab(card, tag, precheck_rows=None):
    st.markdown("<div class='tt'>고지서 점검 — 숫자 다섯 개로 요금제·기본요금 하한까지 여유·최대 절감액·점검 결과 확인</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='cpt'><b>{FIXED_TOP}</b></div>", unsafe_allow_html=True)
    cases = pd.read_csv(CASES, encoding="utf-8-sig")
    names = {c: CASE_NAME.get(str(c).split()[0], c) for c in cases["케이스"]}
    pick = st.selectbox("예시 고지서 불러오기(선택)", ["직접 입력"] + list(cases["케이스"]), key="j9_case", format_func=lambda c: names.get(c, c))
    if pick != "직접 입력" and st.session_state.get("j9_loaded") != pick:
        ci = case_inputs(cases[cases["케이스"] == pick].iloc[0])
        st.session_state.update(j9_c=ci["계약전력"], j9_p=ci["요금적용전력"], j9_txt=months_to_text(ci["월"], 1), j9_exact=ci["월"], j9_loaded=pick,
                                j9_plan=next((p for p in PLANS if p.split()[-1] == ci["요금제"].split()[-1] and p[0] == ci["요금제"][0]), PLANS[0]))
    a, b, c = st.columns(3)
    ck = a.number_input("① 계약전력(kW) — 모르면 비워 둠", min_value=0.0, value=None, step=10.0, key="j9_c")
    plan = b.selectbox("② 계약종별·선택요금", PLANS, key="j9_plan")
    pb = c.number_input("③ 요금적용전력(kW, 기본요금을 매기는 기준 전력) — 비우면 ④로 계산", min_value=0.0, value=None, step=1.0, key="j9_p")
    txt = st.text_area("④ 월 최대수요 12개 + ⑤ 월 시간대별 사용량 12×3 — 엑셀·CSV에서 한 번에 붙여넣기 (월, 최대수요kW, 경부하kWh, 중간kWh, 최대kWh)",
                       key="j9_txt", height=200)
    try:
        months = parse_paste(txt)
    except ValueError as e:
        st.error(str(e)); return
    ex = st.session_state.get("j9_exact")
    if ex and pick != "직접 입력" and txt == months_to_text(ex, 1):
        months = ex                                              # 불러온 예시를 고치지 않았으면 전정밀 값(표시는 소수 첫째 자리)
    if not months:
        st.info("④⑤ 칸에 월별 다섯 칸을 붙여넣으면 계산합니다."); return
    plan_h9 = ("갑 " if plan.startswith("갑") else "을 ") + plan.split()[-1]
    r = compute({"계약전력": ck, "요금제": plan_h9, "요금적용전력": pb, "월": months})
    k = st.columns(4)
    card(k[0], "가장 싼 선택요금", r["요금제"], tag("약관 단가 2023-11-09판"), "2026년 시간대 개편 전 기준", small=True)
    rs = r.get("래칫여유kW")
    card(k[1], "기본요금 하한까지 여유", "계약전력 미입력" if rs is None or not np.isfinite(rs) else f"{rs:,.1f} kW", tag("약관 제68조①"),
         "0 이하면 계약전력 30% 하한에 걸려 피크를 내려도 기본요금이 그대로" if rs is not None and np.isfinite(rs) and rs <= 0 else "요금적용전력 − 계약전력의 30%", small=True)
    u = r.get("효과상한원")
    card(k[2], "최대 절감 가능액(연)", "판정할 수 없음" if u is None or not np.isfinite(u) else f"{u:,.0f}원", tag("약관 산식"),
         f"장비비 하한 {I3.EQUIP_MIN:,.0f}원과 비교", small=True)
    card(k[3], "점검 결과", say(r["선별"]), tag("외부 공장 분석으로 만든 기준"), "주의 항목은 외부 31곳 분포 대비 위치(고정 기준 아님)", small=True)
    st.markdown(f"<div class='card'><b>다음 행동</b> — {say(r['다음행동'])}</div>", unsafe_allow_html=True)
    key = _key(r["선별"])
    left, right = st.columns(2)
    with left:
        if key == "통과" and precheck_rows is not None and str(st.session_state.get("j9_loaded", "")).startswith("T1"):
            d = precheck_rows.rename(columns={"첨두성": "피크 뾰족한 정도(참고)", "결과": "그 달 결과"})
            st.markdown("<div class='card'><b>① 적합성 판정 결과(A사 2·4·5·7·8월)</b></div>", unsafe_allow_html=True)
            st.dataframe(d, hide_index=True)
        elif key == "통과":
            st.markdown("<div class='card'><b>① 적합성 판정</b> — 15분 전력 2개월을 넣으면 '권장·조건부·비권장'으로 판정합니다.</div>", unsafe_allow_html=True)
    with right:
        items = "".join(f"<li>{x}</li>" for x in NEXT_CARD[key])
        st.markdown(f"<div class='card'><b>④ {'운전표 대신 할 일' if key != '통과' else '다음 단계'}</b><ul>{items}</ul></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='cpt'>{FIXED_BOTTOM} 고지서 사진 자동 읽기는 넣지 않았다(손으로 옮겨 적기, 약 30분).</div>", unsafe_allow_html=True)


# ===== 10/28 교열: 동결 파일(ops_service)이 만드는 반장 종이·브리핑 문구를 J9 실행 사본에서만 화면 표시 단계에서 풀어 쓴다(파일 수정 0) =====
APP_SAY = [("받음 금지 칸", "부하 배치 금지 구간"), ("받음 금지", "부하 배치 금지"), ("07~20시만 받음", "07~20시에만 부하 배치"),
           ("새벽에도 받음", "새벽에도 부하 배치"), ("작업을 받습니다", "작업을 배치합니다"), ("A사(재현)", "A사(저장 데이터로 다시 계산)"),
           ("규칙 기반 브리핑 · 숫자는 운전표에서", "정해진 문장 틀 · 숫자는 운전표에서"), ("부하 합", "전력량 합"), ("브리핑", "작업 지시"), ("빼냄", "부하 줄임"), ("받음", "부하 배치")]


def say_app(t):
    t = str(t)
    for a_, b_ in APP_SAY:
        t = t.replace(a_, b_)
    return t


def patch_display(O):
    """O.paper_html 의 반환 HTML 문자열만 바꾼다(브리핑 문장도 그 안에 들어 있다. briefing 은 튜플을 반환하므로 감싸지 않는다)."""
    if getattr(O, "_j9_patched", False):
        return
    for name in ("paper_html",):
        f = getattr(O, name)
        setattr(O, name, (lambda f_: (lambda *a, **k: say_app(f_(*a, **k))))(f))
    O._j9_patched = True


# ===== 10/29 Track K C5(K4): 작업 이동표 '현장 행동' 열 문구 — 전체 화면(viewer_ops_j9)·휴대폰 화면(viewer_mobile)이 같은 사전을 쓴다(표시만) =====
# 발표 v6 8장 카드 ①과 같은 말. A사 설비별 계측이 없으므로 화면에서는 '확인 항목'으로 단다.
FIELD_ACT = {"빼냄": "순서 밖 설비(압축기·집진 등) 잠시 멈춤 · 작업 묶음 끝 15분 뒤로", "받음": "미룬 설비·묶음 끝 작업을 여기서 돌림"}
