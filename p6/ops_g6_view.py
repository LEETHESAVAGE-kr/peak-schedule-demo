# ops_g6_view.py — G6 카드 3개(자동 입력 · 자동 채점 · 월 누적 요약)를 시연 실행 사본(viewer_ops_g6.py)에 그린다.
# 동결 파일(viewer_ops.py·ops_service.py)은 고치지 않는다. 실행 사본이 card·tag 함수를 넘겨 주면 그 모양 그대로 그린다.
# 숫자는 전부 ops_ingest·ops_autoscore 결과(저장 파일 읽기)에서 — 이 파일에 수치 리터럴 없음(시각 오프셋 제외).
import pandas as pd
import streamlit as st

import ops_autoscore as A
import ops_ingest as I
import ops_service as O

DEVICE_NOTE = "CSV 폴더 규격으로 시험 · 장치 연동 미시험"


def _cfg():
    """모드 A 시연 폴더 — 테스트 기간 로거 내보내기 모양 CSV. 없으면 만든다(build/ 값 복사, build/ 쓰기 0)."""
    if not I.DEMO_INBOX.is_dir() or not any(I.DEMO_INBOX.glob("*.csv")):
        I.make_demo_inbox()
    return {**I.default_config(), "folder": str(I.DEMO_INBOX)}


@st.cache_data(show_spinner=False)
def _ingest(day):
    r = I.ingest(_cfg(), now=pd.Timestamp(day) - pd.Timedelta(hours=6))      # 전날 18:00
    if r["status"] != "읽음":
        return r
    c = I.check_against_engine(r["kw"])
    return {k: r[k] for k in ("status", "file", "mapping", "rows", "start", "end", "folder")} | {"check": c}


def ingest_card(col, day, card, tag):
    r = _ingest(pd.Timestamp(day))
    if r["status"] != "읽음":
        card(col, "자동 입력 — 전날 18:00 (폴더 감시)", r["status"], tag(DEVICE_NOTE), small=True)
        return
    mp, c = r["mapping"], r["check"]
    ok = f"엔진 입력과 같은 값 · 차 {c['maxdiff']:.3f} kW" if c["ok"] else "<span class='bad'>엔진 입력과 다름</span>"
    card(col, "자동 입력 — 전날 18:00 (폴더 감시)", f"{r['file']} · {r['rows']}칸", tag(DEVICE_NOTE),
         f"열 매핑 {mp['time_col']}→시각 · {mp['kw_col']}→kW · {r['start'][5:16]}~{r['end'][11:16]} · {ok}", small=True)


def autoscore_card(col, day, card, tag):
    day = pd.Timestamp(day).normalize()
    a = A.autoscore_saved(_cfg(), now=day + A.SCORE_AFTER, log=A.LOG)
    log = A.read_log(A.LOG)
    row = log[(log["날짜"] == day) & (log["모드"] == "A사 재현")]
    if row.empty:
        why = next((w for d, w in a["skipped"] if d == day), "아직 실측 파일 없음")
        card(col, "자동 채점 — 다음 날 08:30 (폴더 감시)", "채점 안 함", tag(A.SRC_SAVED, "rep"), why, small=True)
        return
    r = row.iloc[0]
    card(col, "자동 채점 — 다음 날 08:30 (폴더 감시)",
         f"{day:%m/%d} {r['기존_일최대']:.0f} → {r['운전표_일최대']:.1f} kW · {r['판정']}", tag(A.SRC_SAVED, "rep"),
         f"{r['실측파일']} 감지 → 채점 → ops_log.csv 적재(이번에 {a['added']}행 · 누적 {len(log)}행) · 사람 클릭 없음", small=True)


def replay_card():
    """H10 — 30일 무인 운영 재현 결과(저장 JSON 읽기만, 화면에서 다시 돌리지 않음)."""
    import json
    p = A.HERE / "report" / "trackH" / "_h10_replay.json"
    if not p.exists():
        return
    r = json.loads(p.read_text(encoding="utf-8"))
    sc = r["selfcheck"]
    lose = ", ".join(r["패_날짜"])
    st.markdown(f"<div class='card'><b>30일 무인 운영 재현 — {r['월']}(비산정월)</b> <span class='bd rep'>{r['라벨']}</span><br>"
                f"폴더에 하루 두 번(08:30·18:00) 파일을 넣고 사람 없이 입력 → 운전표 → 다음 날 채점 → 월 카드: "
                f"<b>{r['달력일']}일 중 {r['자동처리_성공일']}일 자동 처리</b> · 승 {r['승']} / 패 {r['패']}({lose}) · "
                f"멈춤 규칙 발동 {'없음' if r['일스위치_멈춤'] is None else r['일스위치_멈춤']} · 다음 달 {r['다음달']}<br>"
                f"<span class='cpt'>self-check: 복제 제외 {sc['평가일(복제 제외)']}일 월최대 {sc['재현 월최대']:.2f} = 저장값 {sc['저장 W2 월최대']:.2f}kW(차 {sc['차']:+.3f}) · "
                f"생산계획·기온은 저장 데이터 · 실기기 미시험</span></div>", unsafe_allow_html=True)


BILL_TAB = "⓪ 0단계 고지서"
VOLTS = {"22,900V(고압A)": 22900, "154,000V(고압B)": 154000, "345,000V(을 고압C)": 345000, "380V(저압)": 380}


def bill_tab(card, tag):
    """H9 — 고지서 세 칸 → 요금제(제59조)·요금적용전력·래칫 여유(제68조)·초과(제67조의3). 수동 입력이 1순위(OCR 없음)."""
    import ops_bill as Bl
    st.markdown("<div class='tt'>0단계 고지서 — 세 칸으로 요금제와 기준 피크를 정합니다</div>", unsafe_allow_html=True)
    a, b, c = st.columns(3)
    ck = a.number_input("① 계약전력(kW)", min_value=0.0, value=None, step=10.0, placeholder="고지서의 계약전력", key="bill_c")
    vv = b.selectbox("② 수전전압", list(VOLTS), key="bill_v")
    mode = c.radio("③ 직전 기록", ["고지서 요금적용전력 1칸", "직전 11개월 최대수요"], key="bill_m", horizontal=True)
    m1, m2, m3 = st.columns(3)
    month = m1.text_input("검침 월(YYYY-MM)", value=pd.Timestamp.now().strftime("%Y-%m"), key="bill_month")
    cur = m2.number_input("이번 달 지금까지 최대수요(kW, 선택)", min_value=0.0, value=None, step=1.0, key="bill_cur")
    opt = m3.selectbox("선택요금", ["선택Ⅰ", "선택Ⅱ", "선택Ⅲ"], key="bill_opt")
    hist, applied = None, None
    if mode.startswith("고지서"):
        applied = st.number_input("요금적용전력(kW)", min_value=0.0, value=None, step=1.0, key="bill_ap")
    else:
        try:
            months = [str(p) for p in pd.period_range(pd.Period(month, "M") - 11, pd.Period(month, "M") - 1, freq="M")]
        except ValueError:
            st.error("검침 월은 YYYY-MM 으로 적어 주십시오."); return
        ed = st.data_editor(pd.DataFrame({"월": months, "최대수요kW": [None] * len(months)}), key="bill_hist", hide_index=True, disabled=["월"])
        hist = {r.월: r.최대수요kW for r in ed.itertuples() if pd.notna(r.최대수요kW)}
    if ck is None or (applied is None and not hist):
        st.info("① 계약전력과 ③ 직전 기록을 넣으면 계산합니다.")
        return
    try:
        r = Bl.bill_check(ck, VOLTS[vv], month, cur, hist if hist else None, applied, opt)
    except ValueError as e:
        st.error(str(e)); return
    k = st.columns(4)
    card(k[0], "요금제(제59조)", f"{r['요금제']} {r['전압']}", tag("약관 원문 식"), r["근거"], small=True)
    card(k[1], f"기본요금 단가({opt})", "고지서 단가 입력" if r["기본요금단가"] is None else f"{r['기본요금단가']:,}원/kW", tag("F7 표(별표1)"),
         r["단가없음"] or "", small=True)
    card(k[2], "이번 달 요금적용전력(제68조)", f"{r['래칫_요금적용전력']:.1f} kW", tag("약관 원문 식"),
         f"기준 {r['래칫_기준']:.1f}kW · {r['래칫_근거']}" + (" · 계약전력 30% 하한 적용" if r["래칫_하한적용"] else ""), small=True)
    gap = r["래칫_래칫여유kW"]
    card(k[3], "래칫 여유", "당월 최대 미입력" if gap is None else f"{gap:.1f} kW", tag("산정월" if r["래칫_산정월"] else "비산정월"), r["래칫_주의"], small=True)
    if r["초과"]:
        x = r["초과"]
        st.markdown(f"<div class='card'><span class='bad'>계약전력 초과 {x['초과kW']:.1f}kW({x['초과비율']:.0%})</span> — 부가 배율 {x['배율']:.0%} · {x['근거']}</div>",
                    unsafe_allow_html=True)
    st.markdown("<div class='cpt'>식: 한전 기본공급약관(2024.10.24판) 제59조·제67조의3·제68조 원문 그대로. 고지서 사진 자동 읽기는 넣지 않았습니다 — 세 칸을 손으로 넣는 것이 1순위입니다. "
                "요금적용전력은 중간·최대부하 시간대 최대수요로 정해집니다(별표 3).</div>", unsafe_allow_html=True)


def month_card(day):
    """월말 — 그 달 테스트 기간 끝(다음 날 08:30)까지 자동 채점한 ops_log 로 한 줄 요약."""
    last = max(d for d in O.TEST_DAYS if d.to_period("M") == pd.Timestamp(day).to_period("M"))
    A.autoscore_saved(_cfg(), now=last + A.SCORE_AFTER, log=A.LOG)
    s = A.month_summary(A.read_log(A.LOG), pd.Timestamp(day).to_period("M"))
    if s is None:
        return
    head, gate, sw = A.summary_line(s)
    lose = " · ".join(f"{t:%m/%d} 기존 일최대 {k:.0f}kW" for t, k in zip(s["패_날짜"], s["패_기존최대"]))
    st.markdown(f"<div class='card'><b>이번 달 누적 — 월말 판단</b> <span class='bd rep'>ops_log.csv 집계 · {A.SRC_SAVED}</span><br>"
                f"{head}<br><b>{gate}</b><br>{sw}{(' — 패 날: ' + lose) if lose else ''}<br>"
                f"<span class='cpt'>{s['규칙']} · 월 게이트는 직전 달 모의 월최대 &lt; 현행 월최대일 때 다음 달 적용(보고서 75쪽)</span></div>",
                unsafe_allow_html=True)
