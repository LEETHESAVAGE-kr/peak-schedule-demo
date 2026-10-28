# 실무자 모바일 화면 — 「피크 운전표」를 휴대폰에서 네 단계(① 점검 → ② 운전표 → ③ 반장 확인 → ④ 어제 결과)로만 쓴다.
# 10/28 사용자 지시: "너무 많은 내용을 보여 주려 한다 — 모바일에서는 실무자 관점에서만 명확하게 재조립".
# 디자인 규칙은 hazop-copilot DESIGN.md(흰 캔버스·잉크 글자·포인트 색 하나·큰 숫자는 화면당 하나·세부는 접기)를 따른다.
# 계산은 전부 기존 함수(ops_service · ops_j9_view.compute · ops_g6_view 카드)를 부른다 — 이 파일에는 숫자 리터럴·새 계산이 없다(레이아웃 값 제외).
# 발표 노트북 시연(viewer_ops_j9.py)은 그대로 두고, 배포 앱(Streamlit Cloud)의 기본 화면으로만 쓴다(deploy_streamlit/streamlit_app.py · ?v=full 이면 전체 화면).
# 실행(로컬 확인): streamlit run viewer_mobile.py  → 주소 끝에 ?k=<접속 코드>
import hmac
import os
import pathlib

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import ops_autoscore as A
import ops_g6_view as G6
import ops_j9_view as J9
import ops_service as O

J9.patch_display(O)
st.set_page_config(page_title="피크 운전표 실무자 화면", layout="centered", initial_sidebar_state="collapsed")

KEY_FILE = pathlib.Path(os.environ.get("KAMP_DEMO_KEY_FILE", pathlib.Path(__file__).resolve().parent.parent / "_secrets" / "demo_key.txt"))
NAVY, AMBER = "#1E2761", "#D98E1F"
WD = "월화수목금토일"
STEPS = ["① 점검", "② 운전표", "③ 반장", "④ 결과"]
CONDS = O.CONDS


def key_ok():
    """viewer_ops 와 같은 잠금 — ?k= 가 접속 코드 파일과 같아야 연다. 파일이 없으면 닫힌다."""
    try:
        want = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(want) and hmac.compare_digest(str(st.query_params.get("k", "")), want)


if not key_ok():
    st.markdown("시연 전용 화면입니다.")
    st.stop()

st.markdown("""<style>
html, body, [class*="css"], .stApp {font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif}
[data-testid=stHeader],[data-testid=stToolbar],[data-testid=stDecoration],[data-testid=stSidebar],[data-testid=stSidebarCollapsedControl],footer{display:none!important}
.block-container{max-width:560px;padding:12px 16px 48px 16px}
.stApp p,.stApp li,.stApp label{font-size:16px;line-height:1.5}
.brand{font-size:24px;font-weight:700;color:#222;margin:4px 0 0 0;line-height:1.3}
.lede{font-size:15px;color:#6a6a6a;margin:2px 0 6px 0;line-height:1.45}
.when{font-size:13px;font-weight:600;color:#1E2761;letter-spacing:.02em;margin:10px 0 2px 0}
.q{font-size:20px;font-weight:700;color:#222;margin:0 0 4px 0;line-height:1.35}
.hint{font-size:15px;color:#6a6a6a;margin:0 0 10px 0;line-height:1.45}
.hero{border:1px solid #ddd;border-radius:14px;padding:14px 16px;margin:8px 0;background:#fff;box-shadow:rgba(0,0,0,.02) 0 0 0 1px,rgba(0,0,0,.04) 0 2px 6px}
.hero .l{font-size:14px;color:#6a6a6a} .hero .n{font-size:36px;font-weight:700;color:#222;line-height:1.15;margin:2px 0}
.hero .n .u{font-size:18px;font-weight:600} .hero .s{font-size:14px;color:#3f3f3f}
.hero.ok{border-left:6px solid #1E2761} .hero.warn{border-left:6px solid #b25e09} .hero.bad{border-left:6px solid #c13515}
.row{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #ebebeb;padding:9px 2px;font-size:15px}
.row .k{color:#6a6a6a;flex:0 0 auto} .row .v{color:#222;font-weight:600;text-align:right}
.mv{display:flex;align-items:center;gap:10px;border:1px solid #ebebeb;border-radius:10px;padding:8px 12px;margin:6px 0;font-size:15px}
.mv .t{font-weight:700;color:#222;min-width:108px} .mv .d{flex:1;color:#3f3f3f} .mv .w{font-weight:700;color:#222}
.mv.out{border-left:5px solid #1E2761} .mv.in{border-left:5px solid #D98E1F}
.say{background:#f7f7f7;border-radius:12px;padding:12px 14px;font-size:15px;line-height:1.55;color:#222;margin:8px 0}
.note{display:inline-block;background:#fff4e5;color:#b25e09;border-radius:9999px;padding:2px 10px;font-size:12px;font-weight:600;margin:2px 0}
.small{font-size:13px;color:#6a6a6a;line-height:1.4}
.chk{padding-left:20px;margin:6px 0 0 0} .chk li{margin:4px 0}
.ok1{font-size:14px;color:#3f3f3f;margin:4px 0 10px 0} .ok1 b{color:#1E2761}
div[data-testid=stSegmentedControl] button{flex:1}
</style>""", unsafe_allow_html=True)


# ---------- 작은 그림 도구(숫자는 받은 값을 그대로 쓴다) ----------
def kw1(x):
    return f"{x:.1f}".replace("-", "−")


def hero(label, value, sub="", tone="ok", size=None):
    sz = f" style='font-size:{size}px'" if size else ""
    st.markdown(f"<div class='hero {tone}'><div class='l'>{label}</div><div class='n'{sz}>{value}</div>{('<div class=s>' + sub + '</div>') if sub else ''}</div>",
                unsafe_allow_html=True)


def rows(pairs):
    st.markdown("".join(f"<div class='row'><span class='k'>{k}</span><span class='v'>{v}</span></div>" for k, v in pairs), unsafe_allow_html=True)


def head(when, q, hint=""):
    st.markdown(f"<div class='when'>{when}</div><div class='q'>{q}</div>" + (f"<div class='hint'>{hint}</div>" if hint else ""), unsafe_allow_html=True)


def mcard(col, label, value, badges="", note="", small=False):
    """G6 카드(자동 입력·자동 채점)를 모바일 모양으로 받는다 — 같은 값. 자동 입력은 확인 한 줄, 자동 채점은 결과 카드."""
    if label.startswith("자동 입력"):
        col.markdown(f"<div class='ok1'><b>✓ 전날 18:00 전력 자동 입력</b> · {value}</div>", unsafe_allow_html=True)
    else:
        col.markdown(f"<div class='hero ok'><div class='l'>{label}</div><div class='n' style='font-size:22px'>{value}</div>"
                     f"<div class='s'>다음 날 아침 실측 파일이 들어오면 자동 채점 · 사람 클릭 없음</div></div>", unsafe_allow_html=True)


def mtag(text, cls="add"):
    return f"<span class='note'>{text}</span>"


def goto(step):
    st.session_state["m_step"] = step


def next_btn(step, label):
    st.button(label, on_click=goto, args=(step,), width="stretch", key=f"next_{step}")


def day_and_mode():
    day = pd.Timestamp(st.session_state.get("m_day", O.DEMO_DAY))
    cond = st.session_state.get("m_cond", CONDS[0])
    return day, (O.MODE_WIN if cond == CONDS[0] else O.MODE_FREE)


def fday(d):
    d = pd.Timestamp(d)
    return f"{d:%Y-%m-%d}({WD[d.dayofweek]})"


def move_list(mt):
    """작업 이동표 → 휴대폰 한 줄씩(시각 · 줄임/배치 · kW)."""
    out = []
    for _, r in mt.iterrows():
        d = J9.say_app(r["이동 방향"])
        cls = "out" if d.startswith("부하 줄임") else "in"
        out.append(f"<div class='mv {cls}'><span class='t'>{r['시각']}</span><span class='d'>{d}</span><span class='w'>{kw1(r['평균 이동전력(kW)'])} kW</span></div>")
    st.markdown("".join(out) or "<div class='small'>옮길 작업이 없습니다. 기존 계획대로 운전합니다.</div>", unsafe_allow_html=True)


def day_chart(index, base, plan):
    rec = pd.DataFrame({"시각": pd.DatetimeIndex(index), "기존 운전": base, "운전표": plan}).melt("시각", var_name="선", value_name="kW")
    c = alt.Chart(rec).mark_line(strokeWidth=2.2, interpolate="step-after").encode(
        x=alt.X("시각:T", title=None, axis=alt.Axis(format="%H시", labelFontSize=12, tickCount=6)),
        y=alt.Y("kW:Q", title="kW", axis=alt.Axis(labelFontSize=12, titleFontSize=12)),
        color=alt.Color("선:N", scale=alt.Scale(domain=["기존 운전", "운전표"], range=[NAVY, AMBER]),
                        legend=alt.Legend(orient="top", title=None, labelFontSize=13)),
        strokeDash=alt.StrokeDash("선:N", scale=alt.Scale(domain=["기존 운전", "운전표"], range=[[1, 0], [6, 3]]), legend=None))
    st.altair_chart(c.properties(height=200).configure_view(strokeWidth=0), width="stretch")


# ---------- 머리 ----------
st.markdown("<div class='brand'>피크 운전표</div><div class='lede'>생산량은 그대로 두고, 전기 기본요금을 정하는 피크 15분만 낮추도록 "
            "작업 시각을 옮기는 하루 운전표입니다.</div>", unsafe_allow_html=True)
st.markdown(f"<span class='note'>예시 공장 A사 · 2021년 저장 데이터로 다시 계산</span>", unsafe_allow_html=True)
st.session_state.setdefault("m_step", STEPS[0])
step = st.segmented_control("단계", STEPS, key="m_step", label_visibility="collapsed") or STEPS[0]


# ===================================================================== ① 점검
def step1():
    head("1 / 4 · 도입 전 한 번 · 약 30분", "우리 공장에 운전표가 맞을까?",
         "전기요금 고지서 숫자 다섯 개로 먼저 거릅니다. 맞지 않는 공장은 여기서 대신 할 일을 받습니다.")
    cases = pd.read_csv(J9.CASES, encoding="utf-8-sig")
    names = {c: J9.CASE_NAME.get(str(c).split()[0], c) for c in cases["케이스"]}
    opts = list(cases["케이스"]) + ["직접 입력"]
    pick = st.selectbox("고지서", opts, key="m_case", format_func=lambda c: names.get(c, c))
    if pick != "직접 입력" and (st.session_state.get("m_loaded") != pick or "m_txt" not in st.session_state):   # 다른 단계에 다녀오면 입력칸 상태가 지워진다
        ci = J9.case_inputs(cases[cases["케이스"] == pick].iloc[0])
        st.session_state.update(m_c=ci["계약전력"], m_p=ci["요금적용전력"], m_txt=J9.months_to_text(ci["월"], 1), m_exact=ci["월"], m_loaded=pick,
                                m_plan=next((p for p in J9.PLANS if p.split()[-1] == ci["요금제"].split()[-1] and p[0] == ci["요금제"][0]), J9.PLANS[0]))
    with st.expander("고지서 숫자 보기·고치기", expanded=pick == "직접 입력"):
        ck = st.number_input("계약전력(kW) — 모르면 비워 둠", min_value=0.0, value=None, step=10.0, key="m_c")
        plan = st.selectbox("계약종별·선택요금", J9.PLANS, key="m_plan")
        pb = st.number_input("요금적용전력(kW) — 비우면 아래 표로 계산", min_value=0.0, value=None, step=1.0, key="m_p")
        txt = st.text_area("월별 다섯 칸 붙여넣기(월, 최대수요kW, 경부하kWh, 중간kWh, 최대kWh)", key="m_txt", height=180)
        st.markdown("<div class='small'>고지서 12장 또는 한전 파워플래너 '청구내역' 화면에서 옮겨 적습니다.</div>", unsafe_allow_html=True)
    ck, plan, pb, txt = st.session_state.get("m_c"), st.session_state.get("m_plan", J9.PLANS[0]), st.session_state.get("m_p"), st.session_state.get("m_txt", "")
    try:
        months = J9.parse_paste(txt)
    except ValueError as e:
        st.error(str(e)); return
    ex = st.session_state.get("m_exact")
    if ex and pick != "직접 입력" and txt == J9.months_to_text(ex, 1):
        months = ex                                          # 불러온 예시를 고치지 않았으면 전정밀 값(J9 화면과 같은 처리)
    if not months:
        st.info("위 칸에 월별 숫자를 붙여넣으면 바로 결과가 나옵니다."); return
    plan_h9 = ("갑 " if plan.startswith("갑") else "을 ") + plan.split()[-1]
    r = J9.compute({"계약전력": ck, "요금제": plan_h9, "요금적용전력": pb, "월": months})
    key = J9._key(r["선별"])
    tone = {"통과": "ok", "효과 없음": "warn", "판정 불가": "warn"}[key]
    hero("점검 결과", J9.say(r["선별"]), {"통과": "운전표를 써 볼 만한 공장입니다", "효과 없음": "운전표 대신 아래 할 일을 하십시오",
                                         "판정 불가": "고지서가 더 필요합니다"}[key], tone, size=24)
    rs, u = r.get("래칫여유kW"), r.get("효과상한원")
    rows([("가장 싼 선택요금", r["요금제"]),
          ("최대 절감 가능액(연)", "판정할 수 없음" if u is None or not np.isfinite(u) else f"{u:,.0f}원"),
          ("기본요금 하한까지 여유", "계약전력 미입력" if rs is None or not np.isfinite(rs) else f"{rs:,.1f} kW")])
    st.markdown(f"<div class='say'><b>{'다음 할 일' if key == '통과' else '운전표 대신 할 일'}</b><ul class='chk'>"
                + "".join(f"<li>{x}</li>" for x in J9.NEXT_CARD[key]) + "</ul></div>", unsafe_allow_html=True)
    if key == "통과" and str(st.session_state.get("m_loaded", "")).startswith("T1"):
        with st.expander("15분 전력으로 한 적합성 판정(A사 5개월)"):
            d = O.precheck_rows()[["월", "판정", "적중률"]]
            st.dataframe(d, hide_index=True, width="stretch")
            st.markdown("<div class='small'>권장이면 측정 3주 → 모의 운전 2~4주 → 적용 순서로 갑니다.</div>", unsafe_allow_html=True)
    with st.expander("이 결과를 믿어도 되나"):
        st.markdown(f"<div class='small'>요금 계산은 한전 기본공급약관 단가(2023-11-09판), 점검 기준은 외부 공장 31곳 고지서 분석에서 만들었습니다. "
                    f"{J9.FIXED_BOTTOM}</div>", unsafe_allow_html=True)
    if key == "통과":
        next_btn(STEPS[1], "다음: ② 내일 운전표 만들기 →")


# ===================================================================== ② 운전표
def step2():
    day, m = day_and_mode()
    head("2 / 4 · 매일 전날 18:00", "내일 어떤 작업을 몇 시로 옮길까?",
         "오늘 18시까지의 15분 전력으로 내일 운전표를 만듭니다. 사람이 있는 07~20시 안에서만 옮깁니다.")
    G6.ingest_card(st, day, mcard, mtag)
    gen = st.session_state.get("gen")
    gen = gen if gen is not None and gen["day"] == day else None
    if st.button("내일 운전표 만들기", type="primary", width="stretch", key="m_gen"):
        with st.spinner("운전표 계산 중 — 몇 초 걸립니다"):
            gen = O.regenerate(day)
        st.session_state["gen"] = gen
        O.save_last_gen(gen)
    if gen is None:
        st.markdown(f"<div class='small'>대상 날짜 {fday(day)} · 조건 {J9.say_app(CONDS[0] if m == O.MODE_WIN else CONDS[1])}</div>", unsafe_allow_html=True)
        return
    y, o, cmp = gen["measured"], gen["plans"][m], gen["compare"][m]
    hero(f"{fday(day)} 하루 최대 전력", f"{y.max():.0f} → {kw1(o.max())}<span class=u> kW</span>",
         f"운전표대로 옮겼을 때 {kw1(o.max() - y.max())} kW · 실제 그날 전력으로 사후 평가")
    st.markdown("**옮길 작업** — 남색 줄은 부하 줄임, 주황 줄은 그 부하를 배치하는 시간", unsafe_allow_html=True)
    move_list(O.move_table(gen["index"], O.base_of(gen), o))
    text, _ = O.briefing(gen, m)
    with st.expander("작업 지시 문장(종이에 그대로 들어감)"):
        st.markdown(f"<div class='say'>{J9.say_app(text)}</div>", unsafe_allow_html=True)
    with st.expander("하루 전력 그래프"):
        day_chart(gen["index"], y, o)
    with st.expander("계산이 맞는지 확인"):
        rows([("저장해 둔 운전표와 대조", "일치" if cmp["ok"] else "불일치"),
              ("15분 구간별 최대 차이", f"{cmp['maxdiff']:.3f} kW"),
              ("계산 시간", f"{gen['total_sec']:.1f}초")])
    next_btn(STEPS[2], "다음: ③ 반장 확인 →")


# ===================================================================== ③ 반장
def step3():
    day, m = day_and_mode()
    head("3 / 4 · 매일 18:10 · 교대 반장", "못 옮기는 작업이 있나?",
         "금형 교체·예열처럼 옮길 수 없는 작업을 체크하면 피크를 바로 다시 계산합니다. 확인이 끝나면 종이 한 장으로 운전원에게 넘깁니다.")
    gen = st.session_state.get("gen")
    if gen is None or gen["day"] != day:
        st.info("먼저 ② 에서 내일 운전표를 만드십시오.")
        next_btn(STEPS[1], "② 운전표로 가기")
        return
    y0, o0 = O.base_of(gen), gen["plans"][m]
    mt = O.move_table(gen["index"], y0, o0)
    st.markdown("**이동 불가 체크**", unsafe_allow_html=True)
    locked = [r.시각 for r in mt.itertuples()
              if st.checkbox(f"{r.시각} · {J9.say_app(r._3)} {kw1(r._2)} kW", key=f"m_lock_{day:%m%d}_{m}_{r.시각}")]
    lk = O.lock_rows(gen["index"], y0, o0, locked)
    if locked:
        gap = "그대로" if lk["gap_kwh"] < 0.01 else f"차 {lk['gap_kwh']:.2f} kWh"
        hero("반장 수정 후 예상 피크", f"{kw1(lk['peak'])}<span class=u> kW</span>",
             f"수정 전 {kw1(o0.max())} kW · 기존 {y0.max():.0f} kW · 하루 전력량 합 {gap}", "warn" if lk["peak"] > o0.max() else "ok")
        gen = {**gen, "plans": {**gen["plans"], m: lk["plan"]}}
    else:
        hero("예상 피크(수정 없음)", f"{kw1(o0.max())}<span class=u> kW</span>", f"기존 {y0.max():.0f} kW")
    st.markdown("<div class='say'><b>반장이 보는 세 숫자</b> — 하나라도 틀리면 그날은 원래 계획으로<ul class='chk'>"
                "<li>설비별 오늘 가동 구간 수 = 계획</li><li>일 생산 수량 ≥ 생산계획 수량</li><li>하루 전력량 합은 그대로</li></ul></div>", unsafe_allow_html=True)
    extra = [f"이동 불가(반장 삭제) — {t}" for t in locked]
    st.download_button("운전원에게 줄 종이 내려받기(인쇄용)", data=O.paper_html(gen, m, extra_bans=extra).encode("utf-8"),
                       file_name=f"운전표_{day:%Y%m%d}.html", mime="text/html", width="stretch")
    next_btn(STEPS[3], "다음: ④ 다음 날 결과 →")


# ===================================================================== ④ 결과
def step4():
    day, m = day_and_mode()
    head("4 / 4 · 다음 날 08:30 · 자동", "어제 운전표가 피크를 낮췄나?",
         "다음 날 아침 실측 파일이 들어오면 자동으로 채점합니다. 사람이 누를 것은 없습니다.")
    if m == O.MODE_WIN:
        G6.autoscore_card(st, day, mcard, mtag)
    d = O.daily_rows(m)
    lose = d[d.변화kW > 0]
    V = O.load_sources()                                     # 전체 화면 ③ 탭과 같은 값(N17a·N17b·N17c)
    down = V["N17a"] if m == O.MODE_WIN else f"{(d[d.날짜.dt.dayofweek < 5].변화kW < 0).sum()}/{(d.날짜.dt.dayofweek < 5).sum()}"
    rows([("테스트 2주 평일 하락", f"{down}일"),
          ("평일 변화율 중앙", f"{V['N17b' if m == O.MODE_WIN else 'N17c']:.1%}".replace("-", "−")),
          ("올라간 날", f"{len(lose)}일" + (" · 모두 주말 저부하일" if len(lose) and (lose.날짜.dt.dayofweek >= 5).all() else ""))])
    with st.expander("날짜별 결과"):
        st.dataframe(pd.DataFrame({"날짜": d.날짜.dt.strftime("%m/%d") + "(" + d.요일 + ")", "기존 kW": d.기존.round(1), "운전표 kW": d.운전표.round(1),
                                   "결과": d.판정}), hide_index=True, width="stretch")
        st.markdown("<div class='small'>주말 저부하일의 상승은 월 최대·요금에 영향이 없다.</div>", unsafe_allow_html=True)
    with st.expander("언제 멈추나 — 멈춤 규칙 네 가지"):
        st.markdown("<ul class='chk'><li><b>당일</b> 반장 세 숫자 중 하나라도 이상 → 즉시 원래 계획</li>"
                    "<li><b>다음 날</b> 채점에서 지면 → 비산정월 3연속 · 산정월 1회면 그 달은 기존 운전</li>"
                    "<li><b>월</b> 직전 달 모의 운전이 현행보다 높으면 그 달은 측정만</li>"
                    "<li><b>단계</b> 준수율 70% 미만 2주 → 모의 운전으로 되돌림</li></ul>"
                    "<div class='small'>멈춤 규칙은 손실을 막을 뿐 절감을 지켜 주지는 않습니다.</div>", unsafe_allow_html=True)


{STEPS[0]: step1, STEPS[1]: step2, STEPS[2]: step3, STEPS[3]: step4}[step]()
if step != STEPS[0]:
    with st.expander("설정 — 날짜·조건", expanded=False):
        st.session_state.setdefault("m_day", O.DEMO_DAY)
        st.selectbox("날짜(2021-09 테스트 기간)", list(O.TEST_DAYS), key="m_day", format_func=fday)
        st.radio("조건", CONDS, key="m_cond", format_func=J9.say_app)
st.markdown("<div class='small' style='margin-top:28px'>화면의 숫자는 제출 산출물과 저장 파일에서 읽거나 같은 계산으로 다시 만든 값입니다. "
            "PC에서 전체 화면(KPI·진단 포함)은 주소에 <b>v=full</b>을 붙입니다.</div>", unsafe_allow_html=True)
