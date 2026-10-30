# 실무자 모바일 화면 — 「피크 운전표」를 휴대폰 한 페이지(위→아래: 운전표 자동 생성 → 반장 확인 → 접힘: 어제 채점·월말·멈춤 규칙 → 믿어도 되나 → 더 보기)로 쓴다.
# 10/29 Track M: 단계 선택기·생성 버튼을 없애고 열자마자 운전표가 보이는 "써 보는 앱"으로(계산·숫자 변경 없음, 호출 위치만 옮김).
# 10/28 사용자 지시: "너무 많은 내용을 보여 주려 한다 — 모바일에서는 실무자 관점에서만 명확하게 재조립".
# 10/28 추가 지시: 직접 넣은 고지서는 운전표에 쓰이지 않는다는 안내(1) + 우리 공장 15분 전력으로 운전표·반장·채점(2, 전체 화면 모드 B와 같은 함수).
# 디자인 규칙은 hazop-copilot DESIGN.md(흰 캔버스·잉크 글자·포인트 색 하나·큰 숫자는 화면당 하나·세부는 접기)를 따른다.
# 계산은 전부 기존 함수(ops_service · ops_j9_view.compute · ops_g6_view 카드)를 부른다 — 이 파일에는 숫자 리터럴·새 계산이 없다(레이아웃 값 제외).
# 발표 노트북 시연(viewer_ops_j9.py)은 그대로 두고, 배포 앱(Streamlit Cloud)의 기본 화면으로만 쓴다(deploy_streamlit/streamlit_app.py · ?v=full 이면 전체 화면).
# 실행(로컬 확인): streamlit run viewer_mobile.py  → 주소 끝에 ?k=<접속 코드>
import hashlib
import hmac
import html
import os
import pathlib

import altair as alt
import pandas as pd
import streamlit as st

import ops_g6_view as G6
import ops_j9_view as J9
import ops_service as O

J9.patch_display(O)
st.set_page_config(page_title="피크 운전표 실무자 화면", layout="centered", initial_sidebar_state="collapsed")

KEY_FILE = pathlib.Path(os.environ.get("KAMP_DEMO_KEY_FILE", pathlib.Path(__file__).resolve().parent.parent / "_secrets" / "demo_key.txt"))
NAVY, AMBER = "#1E2761", "#D98E1F"
WD = "월화수목금토일"
CONDS = O.CONDS
COUNT = pathlib.Path(__file__).parent / "tests" / "_count.txt"


def want_key():
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def key_ok(want):
    """viewer_ops 와 같은 잠금 — ?k= 또는 잠금 화면 입력칸의 코드가 접속 코드 파일과 같아야 연다. 파일이 없으면 닫힌다.
    한 번 맞으면 그 세션은 열린 채로 둔다(입력칸이 사라져도 다시 잠기지 않게 위젯 밖 키에 적는다)."""
    if not want:
        return False
    if st.session_state.get("m_auth"):
        return True
    typed = str(st.session_state.get("m_code", "")).strip()
    if "k=" in typed:                                        # "?k=코드"·"k=코드"·QR 주소 전체를 붙여 넣어도 코드만 쓴다
        typed = typed.rsplit("k=", 1)[1].split("&")[0].split("#")[0].strip()
    for got in (st.query_params.get("k", ""), typed):
        if got and hmac.compare_digest(str(got).strip().encode("utf-8"), want.encode("utf-8")):
            st.session_state["m_auth"] = True
            return True
    return False


_want = want_key()
if not key_ok(_want):
    st.markdown("시연 전용 화면입니다.")
    if _want:                                                # QR 없이 노트북에서 열 때 — 코드를 넣으면 같은 화면이 열린다
        st.text_input("접속 코드", type="password", key="m_code", placeholder="접속 코드(또는 QR 주소 전체)를 붙여 넣고 Enter")
        if st.session_state.get("m_code"):
            st.error("접속 코드가 맞지 않습니다.")
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
.mv{flex-wrap:wrap} .mv .a{flex-basis:100%;font-size:13px;color:#6a6a6a;margin-top:2px}
.say{background:#f7f7f7;border-radius:12px;padding:12px 14px;font-size:15px;line-height:1.55;color:#222;margin:8px 0}
.warnbox{background:#fff4e5;border-radius:12px;padding:10px 14px;font-size:14px;line-height:1.5;color:#7a4100;margin:8px 0}
.note{display:inline-block;background:#fff4e5;color:#b25e09;border-radius:9999px;padding:2px 10px;font-size:12px;font-weight:600;margin:2px 0}
.small{font-size:13px;color:#6a6a6a;line-height:1.4}
.chk{padding-left:20px;margin:6px 0 0 0} .chk li{margin:4px 0}
.ok1{font-size:14px;color:#3f3f3f;margin:4px 0 10px 0} .ok1 b{color:#1E2761}
.card{border:1px solid #ddd;border-radius:12px;padding:12px 14px;margin:8px 0;font-size:15px;line-height:1.5}
.bd{display:inline-block;background:#f2f2f2;color:#6a6a6a;border-radius:9999px;padding:2px 10px;font-size:12px;font-weight:600} .bd.rep{background:#f2f2f2}
.cpt{font-size:13px;color:#6a6a6a} .bad{color:#c13515;font-weight:600}
.hero .s.only{font-size:15px;color:#222}
</style>""", unsafe_allow_html=True)


# ---------- 작은 그림 도구(숫자는 받은 값을 그대로 쓴다) ----------
def kw1(x):
    return f"{x:.1f}".replace("-", "−")


def pct(x, d=1):
    return f"{x:.{d}%}".replace("-", "−")


def hero(label, value, sub="", tone="ok", size=None):
    sz = f" style='font-size:{size}px'" if size else ""
    st.markdown(f"<div class='hero {tone}'><div class='l'>{label}</div><div class='n'{sz}>{value}</div>{('<div class=s>' + sub + '</div>') if sub else ''}</div>",
                unsafe_allow_html=True)


def rows(pairs):
    st.markdown("".join(f"<div class='row'><span class='k'>{k}</span><span class='v'>{v}</span></div>" for k, v in pairs), unsafe_allow_html=True)


def head(when, q, hint=""):
    st.markdown(f"<div class='when'>{when}</div><div class='q'>{q}</div>" + (f"<div class='hint'>{hint}</div>" if hint else ""), unsafe_allow_html=True)


INGEST_SAY = {   # 자동 입력 상태별 다음 행동(PRD Track L §6-2 표 그대로) — (톤, 문장, 운전표를 만드는가)
    "폴더 없음": ("warn", "자동 입력 폴더가 없습니다 — 설정에서 로거 내보내기 폴더를 가리키십시오. 오늘은 운전표를 만들지 않습니다.", False),
    "대기": ("ok", "18:00 마감 전입니다 — 마감 뒤 최신 파일을 읽습니다.", True),
    "파일 없음": ("warn", "오늘 파일이 없습니다 — 로거 내보내기를 확인하십시오. 어제 파일로는 만들지 않습니다.", False),
    "다름": ("bad", "자동 입력값이 엔진 입력과 다릅니다 — 운전표를 만들지 않고 담당자가 확인합니다.", False),
    "예외": ("bad", "파일을 읽지 못했습니다 — 시각·kW 열 이름을 설정에서 고릅니다.", False),
}


def say_box(tone, text, sub=""):
    if tone == "ok":
        st.markdown(f"<div class='ok1'>{text}</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='hero {tone}'><div class='s only'>{text}</div>" + (f"<div class='small'>{sub}</div>" if sub else "") + "</div>",
                    unsafe_allow_html=True)


def mcard(col, label, value, badges="", note="", small=False):
    """G6 카드(자동 입력·자동 채점)를 모바일 모양으로 받는다 — 같은 값. 자동 입력은 상태별 한 줄, 자동 채점은 결과 카드."""
    if label.startswith("자동 입력"):
        state = value if value in INGEST_SAY else ("다름" if "엔진 입력과 다름" in note else None)
        if state is None:
            col.markdown(f"<div class='ok1'><b>✓ 전날 18:00 전력 자동 입력</b> · {value}</div>", unsafe_allow_html=True)
            return
        tone, text, make = INGEST_SAY[state]
        st.session_state["m_ingest_bad"] = not make
        say_box(tone, text)
    else:
        col.markdown(f"<div class='hero ok'><div class='l'>{label}</div><div class='n' style='font-size:22px'>{value}</div>"
                     f"<div class='s'>다음 날 아침 실측 파일이 들어오면 자동 채점 · 사람 클릭 없음</div></div>", unsafe_allow_html=True)


def mtag(text, cls="add"):
    return f"<span class='note'>{text}</span>"


def keep(name, value):
    """위젯 값을 따로 들고 있는다(접힘 안 위젯을 다음에 그 값으로 다시 그린다)."""
    st.session_state[name] = value
    return value


def day_and_mode():
    """설정 위젯(맨 아래 '날짜·조건 바꾸기')의 값 — 위젯보다 위에서 읽으므로 위젯 키를 직접 본다."""
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
        out.append(f"<div class='mv {cls}'><span class='t'>{r['시각']}</span><span class='d'>{d}</span><span class='w'>{kw1(r['평균 이동전력(kW)'])} kW</span><span class='a'>현장 행동(확인 항목): {J9.FIELD_ACT.get(r['이동 방향'], '')}</span></div>")
    st.markdown("".join(out) or "<div class='small'>옮길 작업이 없습니다. 기존 계획대로 운전합니다.</div>", unsafe_allow_html=True)


def day_chart(index, base, plan, names=("기존 운전", "운전표")):
    rec = pd.DataFrame({"시각": pd.DatetimeIndex(index), names[0]: base, names[1]: plan}).melt("시각", var_name="선", value_name="kW")
    c = alt.Chart(rec).mark_line(strokeWidth=2.2, interpolate="step-after").encode(
        x=alt.X("시각:T", title=None, axis=alt.Axis(format="%H시", labelFontSize=12, tickCount=6)),
        y=alt.Y("kW:Q", title="kW", axis=alt.Axis(labelFontSize=12, titleFontSize=12)),
        color=alt.Color("선:N", scale=alt.Scale(domain=list(names), range=[NAVY, AMBER]), legend=alt.Legend(orient="top", title=None, labelFontSize=13)),
        strokeDash=alt.StrokeDash("선:N", scale=alt.Scale(domain=list(names), range=[[1, 0], [6, 3]]), legend=None))
    st.altair_chart(c.properties(height=200).configure_view(strokeWidth=0), width="stretch")


def a_notice():
    """안내(사용자 지시 1): 위 운전표는 예시 공장 A사 화면이고, 고지서 숫자는 운전표에 쓰이지 않는다."""
    own = st.session_state.get("m_own_bill")
    st.markdown("<div class='small'>" + ("직접 넣은 고지서 숫자는 운전표에 쓰이지 않습니다" if own else "고지서 숫자는 운전표에 쓰이지 않습니다")
                + " — 고지서에는 15분 전력이 없기 때문입니다. 위 운전표는 예시 공장 A사(2021년)의 15분 전력으로 만들었습니다. "
                  "우리 공장은 <b>우리 공장 15분 전력</b>(한전 파워플래너 '시간대별' 화면에서 받은 CSV)을 올리면 만들 수 있습니다.</div>",
                unsafe_allow_html=True)


# ===================================================================== 고지서 점검(도입 전 한 번)
def step1():
    head("도입 전 한 번 · 약 30분", "우리 공장에 운전표가 맞을까?",
         "전기요금 고지서 숫자 다섯 개로 먼저 거릅니다. 맞지 않는 공장은 여기서 대신 할 일을 받습니다.")
    cases = pd.read_csv(J9.CASES, encoding="utf-8-sig")
    names = {c: J9.CASE_NAME.get(str(c).split()[0], c) for c in cases["케이스"]}
    opts = list(cases["케이스"]) + ["직접 입력"]
    pick = st.selectbox("고지서", opts, key="m_case", index=opts.index(st.session_state.get("m_case_v", opts[0])), format_func=lambda c: names.get(c, c))
    keep("m_case_v", pick); keep("m_own_bill", pick == "직접 입력")
    if pick != "직접 입력" and (st.session_state.get("m_loaded") != pick or "m_txt" not in st.session_state):
        ci = J9.case_inputs(cases[cases["케이스"] == pick].iloc[0])
        st.session_state.update(m_c=ci["계약전력"], m_p=ci["요금적용전력"], m_txt=J9.months_to_text(ci["월"], 1), m_exact=ci["월"], m_loaded=pick,
                                m_plan=next((p for p in J9.PLANS if p.split()[-1] == ci["요금제"].split()[-1] and p[0] == ci["요금제"][0]), J9.PLANS[0]))
    with st.expander("고지서 숫자 보기·고치기", expanded=pick == "직접 입력"):
        st.number_input("계약전력(kW) — 모르면 비워 둠", min_value=0.0, value=None, step=10.0, key="m_c")
        st.selectbox("계약종별·선택요금", J9.PLANS, key="m_plan")
        st.number_input("요금적용전력(kW) — 비우면 아래 표로 계산", min_value=0.0, value=None, step=1.0, key="m_p")
        st.text_area("월별 다섯 칸 붙여넣기(월, 최대수요kW, 경부하kWh, 중간kWh, 최대kWh)", key="m_txt", height=180)
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
    fin = lambda x: x is not None and pd.notna(x) and abs(x) != float("inf")
    rows([("가장 싼 선택요금", r["요금제"]),
          ("최대 절감 가능액(연)", f"{u:,.0f}원" if fin(u) else "판정할 수 없음"),
          ("기본요금 하한까지 여유", f"{rs:,.1f} kW" if fin(rs) else "계약전력 미입력")])
    st.markdown(f"<div class='say'><b>{'다음 할 일' if key == '통과' else '운전표 대신 할 일'}</b><ul class='chk'>"
                + "".join(f"<li>{x}</li>" for x in J9.NEXT_CARD[key]) + "</ul></div>", unsafe_allow_html=True)
    if key == "통과" and str(st.session_state.get("m_loaded", "")).startswith("T1") and pick != "직접 입력":
        with st.expander("15분 전력으로 한 적합성 판정(A사 5개월)"):
            st.dataframe(O.precheck_rows()[["월", "판정", "적중률"]], hide_index=True, width="stretch")
            st.markdown("<div class='small'>권장이면 측정 3주 → 모의 운전 2~4주 → 적용 순서로 갑니다.</div>", unsafe_allow_html=True)
    with st.expander("이 결과를 믿어도 되나"):
        st.markdown(f"<div class='small'>요금 계산은 한전 기본공급약관 단가(2023-11-09판), 점검 기준은 외부 공장 31곳 고지서 분석에서 만들었습니다. "
                    f"{J9.FIXED_BOTTOM}</div>", unsafe_allow_html=True)
    if key == "통과":
        st.markdown("<div class='small'>운전표는 고지서가 아니라 15분 전력으로 만듭니다. 위 운전표는 예시 공장 A사, 우리 공장은 아래 '우리 공장 15분 전력으로 운전표 만들기'에서 만듭니다.</div>",
                    unsafe_allow_html=True)


# ---------- 우리 공장(전체 화면 모드 B와 같은 함수: read_user_csv · reject_if_asa · precheck_user · gate_of · plan_user) ----------
@st.cache_data(show_spinner=False)
def cached_precheck(kw, month):
    return O.precheck_user(kw, month=month)


def user_data():
    up = st.file_uploader("15분 전력 CSV 올리기(열: timestamp, kw)", type=["csv"], key="m_up")
    if st.button("예시 자료로 해 보기 — 공개 철강공장 2018(UCI, CC BY 4.0)", width="stretch", key="m_ex"):
        kw = O.steel_example()
        st.session_state.update(m_kw=kw, m_kw_src="예시 — 공개 철강공장 2018", m_kw_sig="steel", m_reject=False)
    if up is not None:
        sig = hashlib.sha256(up.getvalue()).hexdigest()
        if st.session_state.get("m_kw_sig") != sig:
            try:
                kw, _ = O.read_user_csv(up)
            except (ValueError, KeyError, TypeError) as e:
                st.error(f"파일을 읽지 못했습니다 — {e}"); return None
            if O.reject_if_asa(kw):
                st.session_state.update(m_kw=None, m_reject=True, m_kw_sig=sig)
            else:
                st.session_state.update(m_kw=kw, m_kw_src=up.name, m_kw_sig=sig, m_reject=False)
    if st.session_state.get("m_reject"):
        st.error("A사 자료는 '예시 공장 A사'에서만 봅니다. 우리 공장 자료를 올려 주십시오."); return None
    kw = st.session_state.get("m_kw")
    if kw is None:
        st.markdown("<div class='small'>한전 파워플래너 '시간대별' 화면에서 15분 전력 2개월 이상을 내려받아 올립니다. kWh 열이면 kW로 바꿔 계산합니다.</div>",
                    unsafe_allow_html=True)
        return None
    i = O.read_user_csv(pd.DataFrame({"timestamp": kw.index, "kw": kw.values}))[1]
    rows([("자료", st.session_state.get("m_kw_src", "올린 파일")), ("기간", f"{i['start'][:10]} ~ {i['end'][:10]}"),
          ("평일 · 결측", f"{i['weekdays']}일 · {pct(i['missing'])}")])
    return kw


def user_form(kw):
    f = O.form_default()
    D = O.F11.day_matrix(kw)
    last = max(D)
    cand = [last + pd.Timedelta(days=1)] + sorted([d for d in D if d > last - pd.Timedelta(days=14)], reverse=True)
    hours = list(range(25))
    with st.expander("우리 공장 조건 — 날짜·근무 시간·이동 폭"):
        dv = st.session_state.get("m_bday_v")
        day = keep("m_bday_v", st.selectbox("운전표 날짜", cand, index=cand.index(dv) if dv in cand else 0, key="m_bday",
                                            format_func=lambda d: fday(d) + (" — 자료 다음 날(계획만)" if d not in D else " — 실측 있음(아래에서 채점)")))
        c1, c2 = st.columns(2)
        lo = keep("m_lo_v", c1.selectbox("사람이 있는 시작 시각", hours, index=st.session_state.get("m_lo_v", f["win_lo"]), key="m_lo"))
        hi = keep("m_hi_v", c2.selectbox("끝 시각", hours, index=st.session_state.get("m_hi_v", f["win_hi"]), key="m_hi"))
        Ls = [2, 3, 4]
        L = keep("m_L_v", st.selectbox("작업을 옮기는 폭(±시간)", Ls, index=Ls.index(st.session_state.get("m_L_v", f["L_hours"])), key="m_L"))
        st.markdown(f"<div class='small'>옮길 수 있는 부하 비중은 추정값 {pct(f['s'], 2)}(단조공장 2곳 전력 패턴)을 씁니다 — 로거로 3주 재면 바꿉니다. "
                    "금형 교체·예열처럼 못 옮기는 작업은 아래 반장 확인에서 지웁니다.</div>", unsafe_allow_html=True)
    return pd.Timestamp(day), dict(f, win_lo=int(lo), win_hi=int(hi), L_hours=int(L))


def step2_user():
    kw = user_data()
    if kw is None:
        return
    day, form = user_form(kw)
    pc = cached_precheck(kw[kw.index < day], f"{day:%Y-%m}")
    gate = O.gate_of(pc["verdict"])
    V = O.load_sources()
    h = pc["metrics"]["peak_hour_hit_rate"]
    hp, hc = pct(V["N23a"], 2), pct(V["N23b"], 1)
    msg = {"권장": (f"피크 시각이 반복됩니다(적중률 {pct(h, 0)} ≥ {hp}). 운전표를 만들 수 있습니다.", "ok"),
           "조건부": ("1개월 모의 운전만 합니다. 실제 적용은 하지 않습니다.", "warn"),
           "비권장": (f"피크 시각이 반복되지 않습니다(적중률 {'—' if pd.isna(h) else pct(h, 0)} < {hc}). 운전표를 만들지 않습니다.", "bad"),
           "판정불가": ("판정 기간의 평일이 모자라거나 빈 칸이 많습니다. 운전표를 만들지 않습니다.", "bad")}[pc["verdict"]]
    hero("우리 공장 적합성 판정(직전 62일)", pc["verdict"], msg[0], msg[1], size=26)
    key = (st.session_state.get("m_kw_sig"), str(day), repr(sorted(form.items())))
    gen = st.session_state.get("gen_b")
    gen = gen if gen is not None and gen.get("_key") == key else None
    if st.button("우리 공장 내일 운전표 만들기", type="primary", width="stretch", key="m_gen_b", disabled=not gate["can_generate"]):
        with st.spinner("비슷한 과거 날 찾기 → 작업 일정 최적화 — 몇 초 걸립니다"):
            gen = O.plan_user(kw, day, form)
        gen.update(_key=key, _form=form, _mock=gate["mock_only"])
        st.session_state["gen_b"] = gen
    if gen is None:
        return
    base, exp = gen["base"], gen["plans"][O.MODE_WIN]
    hero(f"{fday(day)} 예상 최대 전력", f"{kw1(base.max())} → {kw1(exp.max())}<span class=u> kW</span>",
         f"비슷한 과거 날 {len(gen['scen_days'])}일 평균 기준 예상(참고) · 실제 결과는 아래에서 채점" + (" · <b>모의 운전만(적용 금지)</b>" if gen["_mock"] else ""),
         "warn" if gen["_mock"] else "ok")
    st.markdown("**옮길 작업** — 남색 줄은 부하 줄임, 주황 줄은 그 부하를 배치하는 시간", unsafe_allow_html=True)
    move_list(O.move_table(gen["index"], base, exp))
    text, _ = O.briefing(gen, O.MODE_WIN, site=O.SITE_USER, window=(form["win_lo"], form["win_hi"]))
    with st.expander("작업 지시 문장(종이에 그대로 들어감)"):
        st.markdown(f"<div class='say'>{J9.say_app(text)}</div>", unsafe_allow_html=True)
    with st.expander("하루 전력 그래프(예상)"):
        day_chart(gen["index"], base, exp, names=("운전표 없음(예상)", "운전표 적용(예상)"))


# ===================================================================== 반장 확인(A사·우리 공장 공용)
def foreman(gen, m, site, window, base_name):
    """이동 불가 체크 → 피크 다시 계산(lock_rows) → 세 숫자 → 종이. 체크 키 규칙은 현행 ③ 그대로."""
    day = gen["day"]
    y0, o0 = O.base_of(gen), gen["plans"][m]
    mt = O.move_table(gen["index"], y0, o0)
    st.markdown("**이동 불가 체크**", unsafe_allow_html=True)
    tag = "u" if site == O.SITE_USER else "a"
    locked = [r.시각 for r in mt.itertuples()
              if st.checkbox(f"{r.시각} · {J9.say_app(r._3)} {kw1(r._2)} kW", key=f"m_lock_{tag}_{day:%m%d}_{m}_{r.시각}")]
    lk = O.lock_rows(gen["index"], y0, o0, locked)
    if locked:
        gap = "그대로" if lk["gap_kwh"] < 0.01 else f"차 {lk['gap_kwh']:.2f} kWh"
        hero("반장 수정 후 예상 피크", f"{kw1(lk['peak'])}<span class=u> kW</span>",
             f"수정 전 {kw1(o0.max())} kW · {base_name} {kw1(y0.max())} kW · 하루 전력량 합 {gap}", "warn" if lk["peak"] > o0.max() else "ok")
        gen = {**gen, "plans": {**gen["plans"], m: lk["plan"]}}
    st.markdown("<div class='say'><b>반장이 보는 세 숫자</b> — 하나라도 틀리면 그날은 원래 계획으로<ul class='chk'>"
                "<li>설비별 오늘 가동 구간 수 = 계획</li><li>일 생산 수량 ≥ 생산계획 수량</li><li>하루 전력량 합은 그대로</li></ul></div>", unsafe_allow_html=True)
    extra = [f"이동 불가(반장 삭제) — {t}" for t in locked]
    st.download_button("운전원에게 줄 종이 내려받기(인쇄용)", data=O.paper_html(gen, m, extra_bans=extra, window=window, site=site).encode("utf-8"),
                       file_name=f"운전표_{day:%Y%m%d}.html", mime="text/html", width="stretch", key=f"m_paper_{tag}")


# ===================================================================== 어제 결과·멈춤 규칙
def stop_rules():
    with st.expander("언제 멈추나 — 멈춤 규칙 네 가지"):
        st.markdown("<ul class='chk'><li><b>당일</b> 반장 세 숫자 중 하나라도 이상 → 즉시 원래 계획</li>"
                    "<li><b>다음 날</b> 채점에서 지면 → 비산정월 3연속 · 산정월 1회면 그 달은 기존 운전</li>"
                    "<li><b>월</b> 직전 달 모의 운전이 현행보다 높으면 그 달은 측정만</li>"
                    "<li><b>단계</b> 준수율 70% 미만 2주 → 모의 운전으로 되돌림</li></ul>"
                    "<div class='small'>멈춤 규칙은 손실을 막을 뿐 절감을 지켜 주지는 않습니다.</div>", unsafe_allow_html=True)


def yesterday(day, m):
    """어제 채점 — 현행 ④ 모드 A 그대로(다음 날 아침 실측 파일이 들어오면 자동 채점, 사람 클릭 없음)."""
    if m == O.MODE_WIN:
        G6.autoscore_card(st, day, mcard, mtag)
    d = O.daily_rows(m)
    lose = d[d.변화kW > 0]
    V = O.load_sources()                                     # 전체 화면 ③ 탭과 같은 값(N17a·N17b·N17c)
    down = V["N17a"] if m == O.MODE_WIN else f"{(d[d.날짜.dt.dayofweek < 5].변화kW < 0).sum()}/{(d.날짜.dt.dayofweek < 5).sum()}"
    rows([("테스트 2주 평일 하락", f"{down}일"),
          ("평일 변화율 중앙", pct(V["N17b" if m == O.MODE_WIN else "N17c"])),
          ("올라간 날", f"{len(lose)}일" + (" · 모두 주말 저부하일" if len(lose) and (lose.날짜.dt.dayofweek >= 5).all() else ""))])
    with st.expander("날짜별 결과"):
        st.dataframe(pd.DataFrame({"날짜": d.날짜.dt.strftime("%m/%d") + "(" + d.요일 + ")", "기존 kW": d.기존.round(1), "운전표 kW": d.운전표.round(1),
                                   "결과": d.판정}), hide_index=True, width="stretch")
        st.markdown("<div class='small'>주말 저부하일의 상승은 월 최대·요금에 영향이 없다.</div>", unsafe_allow_html=True)


def step4_user():
    gen = st.session_state.get("gen_b")
    if gen is None:
        return
    sc = None
    if gen["realized"] is not None:
        sc = {"measured": gen["measured"], "realized": gen["realized"]}
    else:
        st.markdown(f"<div class='small'>{fday(gen['day'])} 하루의 15분 실측 CSV를 올리면 채점합니다(같은 이동표를 실측에 적용한 사후 평가).</div>",
                    unsafe_allow_html=True)
        f = st.file_uploader("그 날 15분 실측 CSV", type=["csv"], key="m_up_score")
        if f is not None:
            try:
                kw2, _ = O.read_user_csv(f)
                if O.reject_if_asa(kw2):
                    st.error("A사 자료는 '예시 공장 A사'에서만 봅니다."); return
                sc = O.score_user(gen, kw2)
            except (ValueError, KeyError, TypeError) as e:
                st.error(str(e)); return
    if sc is None:
        return
    y, o = sc["measured"], sc["realized"]
    win = o.max() <= y.max() + 1e-9
    hero(f"{fday(gen['day'])} 실측 일최대 → 운전표 적용", f"{kw1(y.max())} → {kw1(o.max())}<span class=u> kW</span>",
         f"{'승' if win else '패'} · 변화 {kw1(o.max() - y.max())} kW({pct(o.max() / y.max() - 1)}) · 사후 평가", "ok" if win else "bad")
    with st.expander("하루 전력 그래프(실측)"):
        day_chart(gen["index"], y, o, names=("실측", "운전표 적용"))


# ===================================================================== 한 페이지(위 → 아래)
st.markdown("<div class='brand'>피크 운전표</div><div class='lede'>생산량은 그대로 두고, 전기 기본요금을 정하는 피크 15분만 낮추도록 "
            "작업 시각을 옮기는 하루 운전표입니다.</div>", unsafe_allow_html=True)
st.markdown("<span class='note'>예시 공장 A사 · 2021년 저장 데이터로 다시 계산</span>", unsafe_allow_html=True)
day, m = day_and_mode()

# [A] 운전표 — 열리면 바로 만든다(버튼 없음). 자동 입력이 "만들지 않는다"고 말한 상태면 건너뛴다.
head("매일 전날 18:00 · 에너지 담당", "내일 어떤 작업을 몇 시로 옮길까?",
     "전날 18시까지의 15분 전력으로 내일 운전표를 만듭니다. 사람이 있는 시간 안에서만 옮깁니다.")
st.session_state["m_ingest_bad"] = False
try:
    G6.ingest_card(st, day, mcard, mtag)
except Exception as e:  # noqa: BLE001 — 열 매핑 실패 등 — 계산 함수는 그대로, 화면만 다음 행동을 말한다
    st.session_state["m_ingest_bad"] = True
    tone, text, _ = INGEST_SAY["예외"]
    say_box(tone, text, html.escape((str(e).splitlines() or [type(e).__name__])[0], quote=False))
gen = st.session_state.get("gen")
gen = gen if gen is not None and gen["day"] == day else None
if st.session_state["m_ingest_bad"]:
    gen = None
elif gen is None:
    with st.spinner("운전표 계산 중 — 몇 초"):
        gen = O.regenerate(day)
    st.session_state["gen"] = gen
    O.save_last_gen(gen)
if gen is not None:
    y, o = gen["measured"], gen["plans"][m]
    hero(f"{fday(day)} 하루 최대 전력", f"{y.max():.0f} → {kw1(o.max())}<span class=u> kW</span>",
         f"운전표대로 옮겼을 때 {kw1(o.max() - y.max())} kW · 실제 그날 전력으로 사후 평가")
    st.markdown("**옮길 작업** — 남색 줄은 부하 줄임, 주황 줄은 그 부하를 배치하는 시간", unsafe_allow_html=True)
    move_list(O.move_table(gen["index"], O.base_of(gen), o))

    # [B] 반장 확인 — 접지 않는다
    head("매일 18:10 · 교대 반장", "못 옮기는 작업이 있나?", "체크하면 피크를 바로 다시 계산합니다.")
    foreman(gen, m, O.SITE_ASA, (7, 20), "기존")

# [C] 접힘 3개
with st.expander("어제 채점 — 다음 날 08:30, 자동"):
    yesterday(day, m)
if m == O.MODE_WIN:
    with st.expander("이번 달 누적 — 월말 판단"):
        G6.month_card(day)                                   # 노트북 ④와 같은 함수·같은 문장
stop_rules()

# [D] 이 계산을 믿어도 되나
with st.expander("이 계산을 믿어도 되나"):
    fp = O.code_fingerprint()
    n = COUNT.read_text(encoding="utf-8").strip() if COUNT.exists() else ""
    pairs = []
    if gen is not None:
        cmp = gen["compare"][m]
        pairs += [("저장해 둔 운전표와 대조", "일치" if cmp["ok"] else "불일치"),
                  ("15분 구간별 최대 차이", f"{cmp['maxdiff']:.3f} kW"),
                  ("계산 시간", f"{gen['total_sec']:.1f}초")]
    pairs.append(("엔진 지문", "사전등록 일치 ✓" if all(fp["match"].values()) and fp["prereg_ok"] else "<span class='bad'>불일치</span>"))
    if n:
        pairs.append(("자동 시험", f"{n}건 통과"))
    rows(pairs)
    st.markdown("<div class='small'>계산은 오프라인 · 언어 모델 없음 · 숫자는 저장 파일에서 읽거나 같은 계산으로 다시 만든 값</div>", unsafe_allow_html=True)
    with st.expander("날짜·조건 바꾸기"):
        days = list(O.TEST_DAYS)
        st.selectbox("날짜(2021-09 테스트 기간)", days, key="m_day", index=days.index(pd.Timestamp(O.DEMO_DAY)), format_func=fday)
        st.radio("조건", CONDS, key="m_cond", format_func=J9.say_app)

# [E] 더 보기
st.divider()
st.markdown("**더 보기**")
with st.expander("우리 공장에 맞을까 — 고지서 다섯 숫자로 점검(도입 전 한 번)"):
    step1()
with st.expander("우리 공장 15분 전력으로 운전표 만들기(자사 데이터)"):
    a_notice()
    step2_user()
    gen_b = st.session_state.get("gen_b")
    if gen_b is not None:
        st.markdown("**반장 확인**")
        foreman(gen_b, O.MODE_WIN, O.SITE_USER, (gen_b["_form"]["win_lo"], gen_b["_form"]["win_hi"]), "운전표 없음 예상")
        st.markdown("**다음 날 채점**")
        step4_user()

st.markdown("<div class='small' style='margin-top:28px'>화면의 숫자는 제출 산출물과 저장 파일에서 읽거나 같은 계산으로 다시 만든 값입니다. "
            "PC에서 전체 화면(KPI·진단 포함)은 주소에 <b>v=full</b>을 붙입니다.</div>", unsafe_allow_html=True)
