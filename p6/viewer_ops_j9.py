# 실행 사본(J9) — viewer_ops_g6.py SHA256 947314922417eb42… 에 J9 0단계 화면만 바꿔 끼웠다(make_run_copy_j9.py).
# 10/30 손 교열(사용자 지시): 휴대폰 화면과 용어 통일 + 우리 공장 조건 양식 배치 수정 — make_run_copy_j9.py 로 다시 만들면 이 교열이 사라진다.
# 실행 사본(G6) — 원본 viewer_ops.py SHA256 d715dc59b6a433aa… 에 G6 카드 3줄만 끼웠다. 손으로 고치지 않는다(make_run_copy_g6.py 로 다시 만든다).
# 실무자 화면 — 「생산을 지키는 피크 운전표」 에너지 담당·교대 반장용. PRD KAMP_제6회_PRD_실무자앱_20261027.md §3·§4.
# 숫자는 전부 ops_service(load_sources/regenerate/plan_user …)에서 온다 — 이 파일에는 숫자 리터럴을 두지 않는다(레이아웃 값 제외).
# 모드 A「A사 재현」= 저장본과 자동 대조되는 재현 생성 · 모드 B「우리 공장」= 자사 15분 전력으로 지금 계산(발표 숫자 아님).
# 온라인 시연(10/27 12:05 지시): 앱은 노트북에서 돌고 터널(ngrok·cloudflared)로 공개 URL 만 연다. ?k=<접속 코드>가 맞아야 화면이 열린다.
# 실행: ..\_sched\run_demo.ps1  (로컬만: streamlit run viewer_ops.py --server.port 8601, 주소 끝에 ?k=<코드>)
import hashlib
import hmac
import importlib
import os
import pathlib
import time

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import ops_service as O
import ops_g6_view as G6           # G6 카드 3개(자동 입력·자동 채점·월 요약) — 실행 사본에만
import ops_j9_view as J9           # J9 0단계 화면(입력 5칸 + 붙여넣기 → 출력 4개 + 판정·다음 행동 카드) — J9 사본에만
if not hasattr(J9, "cond_say"):   # 재배포가 프로세스를 다시 띄우지 않으면 예전 ops_j9_view 가 메모리에 남는다(10/30 Cloud·노트북 둘 다 겪음)
    J9 = importlib.reload(J9)
J9.patch_display(O)                # 교열: 반장 종이 표시 문구만 풀어 씀(동결 파일 수정 0)

SHOW_MODE_B = False             # 킬 규칙(PRD §0-5): 10/28 12:00까지 모드 B 가 S11 을 못 넘으면 False — 코드는 남긴다
NAVY, AMBER, GRAY, BAD = "#1E2761", "#D98E1F", "#9AA0AA", "#B03A2E"
WD = "월화수목금토일"
USER_BADGE = "지금 계산 · 자사 데이터 · 발표 숫자 아님"
KW = "kW(가정)"
KEY_FILE = pathlib.Path(os.environ.get("KAMP_DEMO_KEY_FILE", pathlib.Path(__file__).resolve().parent.parent / "_secrets" / "demo_key.txt"))
TABS_A = ["① 익일 운전표", "② 교대 반장 확인", "③ 일일 성과 분석", "④ 이번 달 KPI", "⑤ 우리 공장 진단", "⑥ 안전 중단 규칙(네 층)", "⓪ 도입 사전 진단"]
TABS_B = [TABS_A[4], TABS_A[0], TABS_A[1], TABS_A[2], TABS_A[3], TABS_A[5]]
CONDS = O.CONDS   # H9 '0단계 고지서' 탭 — 맨 뒤(시연 탭 순서 유지)
DEMO_STEPS = [("⓪ 도입 사전 진단 — 고지서 숫자 5개", TABS_A[6]), ("① 익일 운전표 — 매일 18:00", TABS_A[0]), ("② 교대 반장 확인 — 매일 18:10", TABS_A[1]),
              ("③ 일일 성과 분석 — 매일 08:30", TABS_A[2]), ("④ 안전 중단 규칙(네 층) — 월말", TABS_A[5])]

st.set_page_config(page_title="전력 피크 관리 운전표", layout="wide")


def key_ok():
    """접속 코드(?k=)가 _secrets/demo_key.txt 와 같아야 연다. 파일이 없으면 닫힌다(실패 시 잠금)."""
    try:
        want = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(want) and hmac.compare_digest(str(st.query_params.get("k", "")), want)


if not key_ok():
    st.markdown("시연 전용 화면입니다.")
    st.stop()

st.markdown("""<style>
html{font-size:18px}
html, body, [class*="css"] {font-family:'Malgun Gothic','맑은 고딕',sans-serif}
.block-container{padding-top:0.6rem;padding-bottom:1rem;max-width:1560px}
[data-testid=stHeader]{display:none} footer{display:none}
[data-testid=stMain] [data-testid=stVerticalBlock]{gap:0.5rem}
[data-testid=stSidebar]{min-width:220px!important;max-width:220px!important}
[data-testid=stSidebarContent]{padding-top:0.4rem} [data-testid=stSidebarHeader]{display:none}
.stApp p, .stApp li, .stApp label, [data-baseweb=tab] p, [data-baseweb=select] div, [data-testid=stWidgetLabel] p{font-size:18px}
.ttl{font-size:20px;font-weight:700;color:#1F232B;margin:6px 0 2px 0;line-height:1.3}
table.k th{white-space:nowrap} table.n3 td:first-child{white-space:nowrap}
.sub{color:#3F3F3F;font-size:18px;margin:2px 0 6px 0}
.tt{font-size:22px;font-weight:600;color:#1F232B;margin:2px 0 6px 0}
.bd{display:inline-block;border-radius:9999px;padding:1px 9px;font-size:18px;font-weight:600;margin:2px 4px 2px 0;max-width:100%}
.bd.rep{background:#F2F2F2;color:#6A6A6A} .bd.add{background:#FFF4E5;color:#B25E09} .bd.usr{background:#FFF4E5;color:#B25E09}
.fld{display:inline-block;border-radius:4px;padding:1px 8px;background:#FFF4E5;color:#B25E09;font-weight:600;font-size:18px}
.card{border:1px solid #DDDDDD;border-radius:12px;padding:6px 12px;background:#FFFFFF;height:100%}
.card .l{font-size:18px;color:#6A6A6A;line-height:1.25} .card .n{font-size:32px;font-weight:700;color:#1F232B;margin:0;line-height:1.15;white-space:nowrap} .card .n .u{font-size:18px;font-weight:600}
.card.s .n{font-size:22px;white-space:normal} .card .n.w{white-space:normal;font-size:22px}
.cpt{font-size:18px;color:#6A6A6A;line-height:1.3}
.bad{color:#B03A2E;font-weight:700}
table.k{border-collapse:collapse;width:100%;font-size:18px;line-height:1.2} table.k th{background:#EEF1F7;text-align:left}
table.k td,table.k th{border:1px solid #DDDDDD;padding:2px 8px;vertical-align:top}
table.k tr.sel td{background:#EEF1F7;font-weight:700}
.foot{font-size:18px;color:#6A6A6A;border-top:1px solid #DDDDDD;margin-top:14px;padding-top:6px}
</style>""", unsafe_allow_html=True)


# ---------- 숫자·배지 ----------
@st.cache_data
def sources():
    return O.load_sources()


V = sources()


def v(n):
    return V[n]


def bdg(n, *more, extra=""):
    """출처 배지 하나. more = 같은 배지를 쓰는 다른 출처 키(배지 글자가 같아야 한다)."""
    assert all(O.badge_of(m) == O.badge_of(n) for m in more), (n, more)
    lab = O.SOURCES[n]["label"]
    cls = "add" if lab == O.LABEL_ADDED else "rep"
    return f"<span class='bd {cls}'>{O.badge_of(n)}{(' · ' + extra) if extra else ''}</span>"


def tag(text, cls="add"):
    return f"<span class='bd {cls}'>{text}</span>"


def ub():
    return tag(USER_BADGE, "usr")


def fld(text="현장 확인 필요"):
    return f"<span class='fld'>{text}</span>"


def kw1(x):
    return f"{x:.1f}".replace("-", "−")


def won(x):
    return f"{x:,.0f}원".replace("-", "−")


def man(x):
    return "0" if x == 0 else f"{x / 10 ** 4:,.0f}만".replace("-", "−")


def pct(x, d=1):
    return f"{x:.{d}%}".replace("-", "−")


def fday(d):
    d = pd.Timestamp(d)
    return f"{d:%Y-%m-%d} ({WD[d.dayofweek]})"


def card(col, label, value, badges="", note="", small=False):
    col.markdown(f"<div class='card{' s' if small else ''}'><div class='l'>{label}</div><div class='n'>{value}</div>{badges}"
                 f"{('<div class=cpt>' + note + '</div>') if note else ''}</div>", unsafe_allow_html=True)


def spans(slots):
    """받음 금지 슬롯 집합 → 연속 구간 [(시작 칸, 끝 칸+1)]."""
    s, out = sorted(slots), []
    for t in s:
        if out and out[-1][1] == t:
            out[-1][1] = t + 1
        else:
            out.append([t, t + 1])
    return out


def chart(index, lines, styles, move, ban_slots=(), scen=None, height=175):
    """lines: {이름: 96값}, styles: {이름: (색, 점선)}. 작업 재배치 금지 구간은 옅은 회색 띠, 아래 이동량 막대(빼냄 NAVY / 받음 AMBER).
    두 차트를 따로 그려 화면 폭에 맞춘다(vconcat 은 컨테이너 폭을 따르지 않는다). x 범위는 둘 다 그 날 00:00~23:59."""
    idx = pd.DatetimeIndex(index)
    d0 = idx[0]
    dom = [alt.DateTime(year=d0.year, month=d0.month, date=d0.day, hours=0),
           alt.DateTime(year=d0.year, month=d0.month, date=d0.day, hours=23, minutes=59, seconds=59)]
    sc = alt.Scale(domain=dom)
    rec = pd.DataFrame({"시각": idx, **lines}).melt("시각", var_name="선", value_name="kW")
    names = list(lines)
    col = alt.Scale(domain=names, range=[styles[k][0] for k in names])
    dash = alt.Scale(domain=names, range=[styles[k][1] for k in names])
    x = alt.X("시각:T", title=None, scale=sc, axis=alt.Axis(format="%H:%M", labelFontSize=18, labelOverlap=True))
    x_top = alt.X("시각:T", title=None, scale=sc, axis=alt.Axis(format="%H:%M", labels=False, ticks=False))
    yax = {"labelFontSize": 18, "titleFontSize": 18, "minExtent": 64}
    layers = []
    step = pd.Timedelta(minutes=15)
    band = pd.DataFrame([{"a": idx[a], "b": idx[b - 1] + step} for a, b in spans(ban_slots)])
    if len(band):
        layers.append(alt.Chart(band).mark_rect(color="#F2F2F2").encode(x=alt.X("a:T", scale=sc), x2="b:T"))
    if scen is not None and len(scen):
        thin = pd.DataFrame([{"시각": t, "날": str(j), "kW": float(val)} for j, y in enumerate(scen) for t, val in zip(idx, y)])
        layers.append(alt.Chart(thin).mark_line(strokeWidth=0.8, opacity=0.3, color="#7F8FA6", interpolate="step-after").encode(x=x_top, y="kW:Q", detail="날:N"))
    layers.append(alt.Chart(rec).mark_line(strokeWidth=2.2, interpolate="step-after").encode(
        x=x_top, y=alt.Y("kW:Q", title=KW, axis=alt.Axis(**yax)),
        color=alt.Color("선:N", scale=col, legend=alt.Legend(orient="top", title=None, labelFontSize=18, symbolStrokeWidth=3, labelLimit=360)),
        strokeDash=alt.StrokeDash("선:N", scale=dash, legend=None)))
    mv = pd.DataFrame({"시각": idx, "이동량": move})
    bars = alt.Chart(mv).mark_bar(width=3).encode(
        x=x, y=alt.Y("이동량:Q", title="이동 kW", axis=alt.Axis(**yax, tickCount=3)),
        color=alt.condition("datum.이동량 < 0", alt.value(NAVY), alt.value(AMBER))).properties(height=110)
    st.altair_chart(alt.layer(*layers).properties(height=height).configure_view(strokeWidth=0), width="stretch")
    st.altair_chart(bars.configure_view(strokeWidth=0), width="stretch")


def move_html(mt):
    rows = "".join(f"<tr><td style='white-space:nowrap'>{r.시각}</td><td style='white-space:nowrap'>{J9.MOVE_SAY[r['이동 방향']][1]}</td><td style='text-align:right'>{J9.MOVE_SAY[r['이동 방향']][2]}{kw1(r['평균 이동전력(kW)'])}</td>"
                   f"<td>{J9.MOVE_SAY[r['이동 방향']][3]}</td></tr>" for _, r in mt.iterrows())
    return f"<table class='k'><tr><th>시각</th><th>조정</th><th>kW</th><th>현장 확인 항목</th></tr>{rows}</table>"


def show_status_log(log, total):
    with st.status(f"완료 · 합계 {total:.2f}초", state="complete", expanded=False):
        for line in log:
            st.write(line)


def three_numbers(day, y=None, o=None, title="현장 확인 필수 3요소"):
    """현장 확인 필수 3요소 — ①② 는 현장 값(숫자 없음), ③ 은 부하 합 보존. 화면 공유 첫 뷰포트에 들어가게 3행 표."""
    gap = f"차 {O.energy_gap(day):.3f} kWh"                     # PRD §3 ③ — table_x_test_daily.csv 에너지차(지금 생성 차는 저장본 대조 카드)
    st.markdown(f"<table class='k n3'><tr><th colspan=2>{title}</th></tr>"
                f"<tr><td>① 설비별 가동 구간 수가 계획과 같은가?</td><td>{fld()}</td></tr>"
                f"<tr><td>② 일일 생산량이 당일 생산계획 수량 이상인가?</td><td>{fld('현장 입력')}</td></tr>"
                f"<tr><td>③ 하루 총 전력 사용량에 변동이 없는가?</td><td><b>예</b> · {gap} {tag('제출 후 추가 분석')}</td></tr></table>", unsafe_allow_html=True)


# ---------- 준비(앱 시작 때 1회) ----------
@st.cache_resource(show_spinner="엔진 준비 중 — 시연 날짜를 두 조건으로 한 번 계산합니다")
def warm():
    """엔진 import·데이터 로드·시연 날짜 두 조건 생성을 미리 1회. 캐시일 뿐 — 발표 중 '운전표 생성'은 LP 를 다시 푼다."""
    t = time.perf_counter()
    r = O.regenerate(O.DEMO_DAY)
    return {"sec": time.perf_counter() - t, "diff": max(r["compare"][m]["maxdiff"] for m in (O.MODE_WIN, O.MODE_FREE)),
            "ok": all(r["compare"][m]["ok"] for m in (O.MODE_WIN, O.MODE_FREE))}


def go(tab):
    """시연 순서 버튼 — 모드 A · 해당 탭 · 시연 날짜 · 07~20시."""
    st.session_state.update(mode=O.MODE_A_LABEL, tab_a=tab, cond_a=CONDS[0], day_a=O.DEMO_DAY)


def load_last():
    g = O.load_last_gen()
    if g is not None:
        st.session_state.update(gen=g, gen_log=[f"불러온 결과 · {g['saved_at']} 생성"], day_a=g["day"])


W = warm()

# ---------- 사이드바: 시연 순서 · 모드 · 날짜 · 조건 · 준비 상태 ----------
with st.sidebar:
    st.markdown("**시연 순서 ①→④**")
    for lab, tab in DEMO_STEPS:
        st.button(lab, key=f"step_{tab}", on_click=go, args=(tab,), width="stretch")
    st.markdown("<div class='ttl'>전력 피크 관리 운전표 — 실무자 화면</div>", unsafe_allow_html=True)
    if SHOW_MODE_B:
        mode = st.radio("모드", [O.MODE_A_LABEL, O.MODE_B_LABEL], key="mode")
    else:
        mode = O.MODE_A_LABEL
    IS_A = mode == O.MODE_A_LABEL
    day_sel, cond_sel = O.DEMO_DAY, CONDS[0]
    if IS_A:
        day_sel = st.selectbox("날짜(테스트 기간만)", list(O.TEST_DAYS), index=list(O.TEST_DAYS).index(O.DEMO_DAY), format_func=fday, key="day_a")
        cond_sel = st.radio("기준 조건 선택", CONDS, key="cond_a", format_func=J9.cond_say)
        if st.session_state.get("gen") is None and O.LAST_GEN.exists():
            st.button("마지막 생성 결과 불러오기", on_click=load_last, width="stretch")
    g_now = st.session_state.get("gen")
    last_sec = g_now["total_sec"] if g_now is not None else W["sec"]
    last_diff = max(g_now["compare"][m]["maxdiff"] for m in (O.MODE_WIN, O.MODE_FREE)) if g_now is not None else W["diff"]
    st.markdown(f"<div class='cpt'>{'엔진 준비 완료' if W['ok'] else '<span class=bad>엔진 준비 — 저장본 불일치</span>'} · 마지막 생성 {last_sec:.1f}초 · "
                f"저장본 대조 차 {last_diff:.2f}kW</div>", unsafe_allow_html=True)


# ===================================================================================== 모드 A
def mode_a(day, cond):
    m = O.MODE_WIN if cond == CONDS[0] else O.MODE_FREE
    gen = st.session_state.get("gen")
    gen = gen if gen is not None and gen["day"] == pd.Timestamp(day) else None
    tabs = st.tabs(TABS_A, key="tab_a", on_change="rerun")
    if tabs[0].open:
        with tabs[0]:
            gen = tab_a1(day, m, gen)
    if tabs[1].open:
        with tabs[1]:
            tab_a2(day, m, gen)
    if tabs[2].open:
        with tabs[2]:
            tab_a3(day, m, gen)
    if tabs[3].open:
        with tabs[3]:
            tab_a4()
    if tabs[4].open:
        with tabs[4]:
            tab_a5()
    if tabs[5].open:
        with tabs[5]:
            tab_a6()
    if tabs[6].open:
        with tabs[6]:
            J9.stage0_tab(card, tag, O.precheck_rows())
    fp = O.code_fingerprint()
    short = {f.split("/")[-1].split("_")[0].replace(".py", ""): h[:8] for f, h in fp["sha"].items()}
    ok = "일치 ✓" if fp["prereg_ok"] and all(fp["match"].values()) else "<span class='bad'>불일치</span>"
    st.markdown("<div class='foot'>전날 18:00까지의 15분 전력만으로 내일의 작업 이동표를 만듭니다. 화면의 모든 값은 제출 산출물과 제출 후 추가 분석 저장 파일에서 읽습니다.<br>"
                f"엔진 지문 SHA256 f24 {short['f24']}… · f14 {short['f14']}… · f21 {short['f21']}… · f11 {short['f11']}… · common {short['common']}… · "
                f"b4 {short['b4']}… · 사전등록 {fp['prereg_sha'][:8]}… {ok} · 데이터는 2021년, 화면 날짜도 2021년</div>", unsafe_allow_html=True)


def tab_a1(day, m, gen):
    G6.ingest_card(st, day, card, tag)
    b1, b2, b3 = st.columns([1.1, 1.9, 2.2], vertical_alignment="center")
    clicked = b1.button("운전표 생성", type="primary", key="gen_a")
    b3.markdown("<div class='cpt'>두 조건을 계산해 저장본과 대조합니다.</div>", unsafe_allow_html=True)
    if clicked:
        log = []
        with b2.status("운전표 생성 중 — 실측 단계만 표시", expanded=True) as stt:
            if O.GEN_LOCK.locked():
                stt.write("다른 화면에서 생성 중입니다(약 3초) — 끝나면 바로 시작합니다")

            def say(step, sec, note):
                line = J9.say_app(f"{step}{(' — ' + note) if note else ''} ({sec:.2f}초)")
                log.append(line); stt.write(line)
            gen = O.regenerate(day, progress=say)
            stt.update(label=f"완료 · 합계 {gen['total_sec']:.2f}초", state="complete", expanded=False)
        st.session_state["gen"], st.session_state["gen_log"] = gen, log
        O.save_last_gen(gen)
    elif gen is not None:
        with b2:
            show_status_log(st.session_state.get("gen_log", []), gen["total_sec"])
    saved, measured, _sname = O.saved_plan(day, m)
    c = st.columns([1.3, 1.25, 0.95, 1.05])
    if gen is not None:
        y, o, cmp = gen["measured"], gen["plans"][m], gen["compare"][m]
        b = tag("지금 생성", "rep") + (tag("야간 작업 가능 시 상한 — 보고서 값") if m == O.MODE_FREE else "")
        card(c[0], "피크 전력 · 기존 → 운전표(사후 평가)", f"{y.max():.0f} → {kw1(o.max())}<span class=u> kW</span>", b, f"변화 {kw1(o.max() - y.max())} kW")
        val = "일치" if cmp["ok"] else "<span class='bad'>불일치</span>"
        card(c[2], "저장된 운전표와 데이터 대조", val, tag("지금 생성", "rep"), f"15분 구간별 최대 차이 {cmp['maxdiff']:.3f} kW")
        ban = gen["ban"][m]
    else:
        card(c[0], "피크 전력 · 기존 → 운전표(사후 평가)", "생성 전", "", "운전표 생성을 누르면 지금 계산합니다")
        card(c[2], "저장된 운전표와 데이터 대조", "생성 전")
        y, o, ban = measured, None, (v("N5") if m == O.MODE_WIN else 0.0)
    if m == O.MODE_WIN:
        card(c[1], "테스트 기간 최대 (저장본)", f"{v('N1'):.0f} → {kw1(v('N3'))}<span class=u> kW</span>", bdg("N1") + bdg("N3"))
    else:
        card(c[1], "테스트 기간 최대 (저장본)", f"{v('N1'):.0f} → {kw1(v('N2'))}<span class=u> kW</span>", bdg("N1") + bdg("N2") + tag("야간 작업 가능 시 상한"))
    card(c[3], "작업 재배치 금지 구간", f"{ban:.0f} / 96", bdg("N5") if m == O.MODE_WIN else "", "07:00~20:00 밖" if m == O.MODE_WIN else "금지 구간 없음")
    g1, g2 = st.columns([1.25, 1])
    with g1:
        idx = gen["index"] if gen is not None else pd.date_range(day, periods=96, freq="15min")
        lines = {"기존 운전(실측)": y}
        sty = {"기존 운전(실측)": (NAVY, [1, 0])}
        if o is not None:
            lines["운전표 적용(지금 생성)"] = o; sty["운전표 적용(지금 생성)"] = (AMBER, [6, 3])
        lines["저장본"] = saved; sty["저장본"] = (GRAY, [2, 3])
        chart(idx, lines, sty, (o if o is not None else saved) - y, (O.B4.ban_window(day, 7, 20) if m == O.MODE_WIN else ()))
    with g2:
        st.markdown("**시간대별 부하 조정** (5kWh 이상)" + (tag("지금 생성", "rep") if o is not None else tag("저장본", "rep")), unsafe_allow_html=True)
        st.markdown(move_html(O.move_table(idx, y, o if o is not None else saved)), unsafe_allow_html=True)
        three_numbers(day, y, o)
    st.markdown("<div class='cpt'>회색 점선 = 저장본(07~20시 → 10/26 저장본 trackB/_b4b_plan_test.csv · 보고서 조건 → 10/7 1회 확인 저장본 build/f24_plan_testat.csv) — "
                "지금 생성한 선과 겹쳐 보이지 않으면 정상. 옅은 회색 띠 = 작업 재배치 금지 구간. 테스트 기간 최대 저장본 = trackB/_b4_staffing.csv(작업 재배치 금지 구간만 둔 사후 민감도) · build/table_f24_testat.csv.<br>"
                "테스트 기간(2021-09-01~14) 안의 날만 생성합니다. 그 밖의 날을 생성해 채점하면 새 성능 숫자가 되므로 하지 않습니다.</div>", unsafe_allow_html=True)
    return gen


def tab_a3(day, m, gen):
    st.markdown("<div class='tt'>일일 성과 분석 — 매일 08:30 자동 채점, 계획 대 실측</div>", unsafe_allow_html=True)
    if m == O.MODE_WIN:
        G6.autoscore_card(st, day, card, tag)
    if gen is not None:
        three_numbers(day, gen["measured"], gen["plans"][m], title="현장 확인 필수 3요소(반장 기록)")
    else:
        three_numbers(day, title="현장 확인 필수 3요소(반장 기록)")
    d = O.daily_rows(m)
    lose = d[d.변화kW > 0]
    c = st.columns(3)
    if m == O.MODE_WIN:
        card(c[0], "최근 2주 평일 피크 감소", v("N17a"), bdg("N17a"))
        card(c[1], "평일 피크 변화율(중앙값)", pct(v("N17b")), bdg("N17b"), "07~20시에만 작업 재배치")
    else:
        card(c[0], "최근 2주 평일 피크 감소", f"{(d[d.날짜.dt.dayofweek < 5].변화kW < 0).sum()}/{(d.날짜.dt.dayofweek < 5).sum()}", tag("제출 후 추가 분석"))
        card(c[1], "평일 피크 변화율(중앙값)", pct(v("N17c")), bdg("N17c"), "보고서 조건")
    low = ", ".join(f"+{x:.2f}" if m == O.MODE_WIN else f"+{x:.1f}" for x in lose.변화kW)
    card(c[2], "피크가 오른 날", f"{len(lose)}일", tag("제출 후 추가 분석"), f"주말 저부하일 {lose.기존.max():.0f}kW, {low} kW" if len(lose) else "")
    sel = pd.Timestamp(day)
    rows = "".join(f"<tr{' class=sel' if r.날짜 == sel else ''}><td>{r.날짜:%Y-%m-%d}</td><td>{r.요일}</td><td style='text-align:right'>{r.기존:.1f}</td>"
                   f"<td style='text-align:right'>{r.운전표:.2f}</td><td style='text-align:right'>{f'{r.변화kW:+.2f}'.replace('-', '−')}</td>"
                   f"<td style='text-align:right'>{pct(r.변화율)}</td><td>{'<span class=bad>패</span>' if r.판정 == '패' else '승'}</td></tr>" for r in d.itertuples())
    st.markdown("<table class='k'><tr><th>날짜</th><th>요일</th><th>기존 운전 일최대(kW)</th><th>운전표 적용 일최대(kW)</th><th>변화 kW</th><th>변화율</th><th>승/패</th></tr>"
                + rows + "</table>", unsafe_allow_html=True)
    src = "trackB/_b4_staffing_daily.csv" if m == O.MODE_WIN else "build/table_x_test_daily.csv"
    st.markdown(f"<div class='cpt'>주말 등 전력 사용이 적은 날(저부하일)의 피크 상승은 월 최대 전력과 기본요금에 영향을 주지 않습니다.</div>", unsafe_allow_html=True)


def tab_a2(day, m, gen):
    st.markdown("<div class='tt'>교대 반장 — 현장 확인 및 확정 · 운전원 배포용 일정표</div>", unsafe_allow_html=True)
    if gen is None:
        st.info("① 익일 운전표에서 운전표 생성을 누르면 일정표가 만들어집니다.")
        return
    # D10(Track F): 반장이 옮길 수 없는 작업 행을 체크 → 그 작업은 원 시각으로 → 그 자리에서 피크 재계산(LP 재실행 아님)
    y0, o0 = O.base_of(gen), gen["plans"][m]
    mt = O.move_table(gen["index"], y0, o0)
    st.markdown("**이동 불가 작업 체크** — 금형 교체·예열 등 현장 사정상 시간 이동이 불가능한 작업", unsafe_allow_html=True)
    cols = st.columns(4)
    locked = [r.시각 for k, r in enumerate(mt.itertuples())
              if cols[k % 4].checkbox(f"{r.시각} · {J9.MOVE_SAY[r._3][1]} ({J9.MOVE_SAY[r._3][2]}{kw1(r._2)} kW)", key=f"lock_{pd.Timestamp(day):%m%d}_{m}_{r.시각}")]
    lk = O.lock_rows(gen["index"], y0, o0, locked)
    c = st.columns([1.5, 1, 1])
    if locked:
        card(c[0], "반장 수정 반영 후 예상 피크", f"{kw1(lk['peak'])}<span class=u> kW</span>",
             tag("화면에서 다시 계산 · 최적화 계산은 다시 하지 않음", "rep"), f"수정 전 {kw1(o0.max())} kW · 기존 {y0.max():.0f} kW")
        card(c[1], "지운 작업", f"{len(locked)}행", "", f"남은 반대 방향 이동 {pct(lk['kept_ratio'], 0)} 유지")
        card(c[2], "하루 총 전력 사용량", "변동 없음" if lk["gap_kwh"] < 0.01 else f"차 {lk['gap_kwh']:.2f} kWh", "", "지운 만큼 반대 방향도 줄임")
        gen = {**gen, "plans": {**gen["plans"], m: lk["plan"]}}
    else:
        card(c[0], "반장 수정 반영 후 예상 피크", "수정 없음", "", f"현재 운전표 {kw1(o0.max())} kW · 기존 {y0.max():.0f} kW")
    html = O.paper_html(gen, m, extra_bans=[f"이동 불가(반장 삭제) — {t}" for t in locked])
    st.markdown(tag("정해진 문장 틀 · 숫자는 운전표에서"), unsafe_allow_html=True)
    components.html(O.paper_html(gen, m, screen=True, extra_bans=[f"이동 불가(반장 삭제) — {t}" for t in locked]), height=900, scrolling=True)
    st.download_button("현장 운전원 배포용 일정표 다운로드(인쇄용)", data=html.encode("utf-8"), file_name=f"운전표_{pd.Timestamp(day):%Y%m%d}.html", mime="text/html")
    st.markdown("<div class='cpt'>운전원은 이 종이만 받습니다. 새 화면은 보지 않습니다.</div>", unsafe_allow_html=True)


def tab_a4():
    st.markdown("<div class='tt'>이번 달 KPI — 보고서 값 / 도입 기준 / 민감도 범위</div>", unsafe_allow_html=True)
    no_calc = fld("계산 안 함")
    na = "<span class='cpt'>해당 없음</span>"
    rows = [
        ("테스트 최대", f"{v('N1'):.0f} → {kw1(v('N2'))} kW {bdg('N2')}", f"{kw1(v('N3'))} kW {bdg('N3')}", f"{no_calc} <span class='cpt'>테스트는 다시 계산하지 않음</span>"),
        ("요금적용전력(7·8·9월 최대)", f"{v('N6a'):.2f} kW {bdg('N6a')}", f"{v('N6b'):.2f} kW {bdg('N6b')}",
         f"{v('N6b'):.2f} ~ {v('N6c'):.1f} kW {bdg('N6c', extra='7·8월만, 비중 3.5%~')}"),
        ("기본요금 월(선택Ⅰ)", f"{won(v('N7a'))} {bdg('N7a')}", f"{won(v('N7b'))} {bdg('N7b')}", f"{won(v('N7c'))} ~ {won(v('N7b'))} {bdg('N7c')}"),
        ("기본요금 연", f"{man(v('N8a'))} 원 {bdg('N8a', extra='보고서에 없음')}", f"{man(v('N8b'))} 원 {bdg('N8b')}", f"{man(v('N8c'))} ~ {man(v('N8b'))} 원 {bdg('N8c')}"),
        ("전력량요금 월(9월 단가)", f"{won(v('N9a'))} {bdg('N9a')}", f"{won(v('N9b'))} {bdg('N9b')}", no_calc),
        ("합계 월", f"{won(v('N10a'))} {bdg('N10a')}", f"{won(v('N10b'))} {bdg('N10b')}", no_calc),
        ("합계 연", f"{man(-v('N11a')[1])}~{man(-v('N11a')[0])} 원 절감 {bdg('N11a')}", f"{man(-v('N11b')[1])}~{man(-v('N11b')[0])} 원 절감 {bdg('N11b')}", no_calc),
        (f"7월 월최대(현행 {v('N12c'):.0f}kW)", f"{v('N12a'):.2f} kW {bdg('N12a', 'N12c')}", f"{v('N12b'):.2f} kW {bdg('N12b')}", f"{v('N12b'):.2f} ~ {v('N12d'):.1f} kW {bdg('N12d')}"),
        ("7월 월 최대를 낮추는 최소 이동 가능 부하 비중", "<span class='cpt'>보고서 84쪽 값은 중앙값 기반 운전표 기준</span>", f"{pct(v('N13'), 0)} {bdg('N13')}", na),
        ("생산 손실 회피(차단 방식 대비)", f"월 {v('N14a'):,.0f}~{v('N14b'):,.0f}개 {bdg('N14a', 'N14b')}", "<span class='cpt'>같은 정의 — 작업을 옮기기만 한다</span>", na),
        ("피크 여유(7월 현행 − 요금적용전력)", f"{v('N15a'):.2f} kW {bdg('N15a')}", f"{v('N15b'):.2f} kW {bdg('N15b')}", na),
    ]
    blank = ["계약전력", "변압기 정격·부하율", "로거 가격·회수 기간", "국민DR 자격"]
    body = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td><td>{c}</td><td>{d}</td></tr>" for a, b, c, d in rows)
    body += "".join(f"<tr><td><b>{a}</b></td><td colspan=3>{fld()}</td></tr>" for a in blank)
    st.markdown(f"<table class='k'><tr><th>항목</th><th>보고서 값(새벽 시간대 포함 작업 재배치)</th><th>도입 기준(07~20시에만 작업 재배치)</th><th>민감도 범위(07~20시, 비중 3.5~{pct(v('N26'), 2)})</th></tr>{body}</table>",
                unsafe_allow_html=True)
    st.markdown("**부속 — 도입 기준 옆에 두는 변형(더하지 않음)**", unsafe_allow_html=True)
    st.markdown("<table class='k'><tr><th>변형</th><th>7월 월최대</th><th>기본요금 월</th></tr>"
                f"<tr><td>2교대(07~20 ∪ 그날 계획 야간 슬롯) — 야간조 가능 여부 {fld()}</td><td>{kw1(v('N16a'))} kW {bdg('N16a')}</td><td>{won(v('N16b'))} {bdg('N16b')}</td></tr>"
                f"<tr><td>07~20시 + DR 17~21시 작업 재배치 금지</td><td>{kw1(v('N16c'))} kW {bdg('N16c')}</td><td>{won(v('N16d'))} {bdg('N16d')}</td></tr></table>", unsafe_allow_html=True)
    st.markdown(f"<div class='cpt'>세 열은 산출 조건이 달라 서로 더하지 않습니다. 7·8월은 운전표 선택에 쓴 달입니다. {pct(v('N26'), 2)}는 단조공장 2곳에서 추정한 값이며 A사 실측이 아닙니다. {bdg('N26')}</div>",
                unsafe_allow_html=True)


def rule_card(pct_style=False):
    hp, hc = v("N23a"), v("N23b")
    hp_s, hc_s = (pct(hp, 2), pct(hc, 1)) if pct_style else (f"{hp:.4f}", f"{hc:.3f}")
    st.markdown(f"<div class='card'><b>판정은 하나</b> — 평일 하루 최대 전력 시각을 같은 요일 직전 4주 중앙값이 1시간 안에 맞히는 비율(적중률)<br>"
                f"· 권장 ≥ {hp_s} (우연 {hc_s}의 2배) {bdg('N23a')}{bdg('N23b')}<br>· 조건부 {hc_s} ~ {hp_s} — 1개월 모의 운전 후<br>· 비권장 &lt; {hc_s}<br>"
                "· 첨두성(최대/평균)은 참고만</div>", unsafe_allow_html=True)


def tab_a5():
    st.markdown("<div class='tt'>우리 공장 진단 — 도입 전, 15분 전력 두 달로</div>", unsafe_allow_html=True)
    a, b = st.columns([1, 1])
    with a:
        rule_card()
        st.markdown("**A사 설계 달 5개 판정**(판정 기간 = 그 달 직전 62일) " + tag("제출 후 추가 분석"), unsafe_allow_html=True)
        pr = O.precheck_rows()
        st.markdown("<table class='k'><tr><th>월</th><th>판정</th><th>적중률</th><th>첨두성(참고)</th><th>그 달 결과</th></tr>" + "".join(
            f"<tr><td>{r.월}월</td><td>{r.판정}</td><td>{r.적중률:.2f}</td><td>{r.첨두성:.2f}</td><td>{r.결과}</td></tr>" for r in pr.itertuples()) + "</table>",
            unsafe_allow_html=True)
        st.markdown("<div class='cpt'>출처: 제출 후 추가 분석 저장값</div>", unsafe_allow_html=True)
    with b:
        st.markdown("**비교 — 같은 정의로 잰 월 안 평일 적중률(중앙)** " + bdg("N25a", extra="월 안 적중률(진단)"), unsafe_allow_html=True)
        st.markdown("<table class='k'><tr><th>공장</th><th>적중률</th></tr>"
                    f"<tr><td>A사</td><td>{pct(v('N25a'), 0)} {bdg('N25a')}</td></tr><tr><td>단조 1</td><td>{pct(v('N25b'))} {bdg('N25b')}</td></tr>"
                    f"<tr><td>단조 2</td><td>{pct(v('N25c'))} {bdg('N25c')}</td></tr><tr><td>철강</td><td>{pct(v('N31'), 0)} {bdg('N31')}</td></tr></table>",
                    unsafe_allow_html=True)
        med = O.precheck_rows().적중률.median()
        st.markdown(f"<div class='cpt'>보고서 적중률 값은 정의가 다릅니다(복제일 포함 / 주말 포함). 판정 기간(직전 62일)으로 재면 A사 중앙 {pct(med, 0)}입니다. build/table_x_decomp.csv</div>",
                    unsafe_allow_html=True)
        with st.expander("우리 공장 15분 전력 CSV(timestamp, kw)", expanded=False):
            f = st.file_uploader("CSV 올리기", type=["csv"], key="up_a5")
            if f is not None:
                kw, _info = O.read_user_csv(f)
                if O.reject_if_asa(kw):
                    st.error("A사 데이터는 재현 모드에서만. 테스트 기간은 다시 계산하지 않습니다.")
                else:
                    r = O.precheck_user(kw)
                    hr = r["metrics"]["peak_hour_hit_rate"]
                    st.markdown(f"판정 **{r['verdict']}** · 적중률 {hr:.2f} · 첨두성(참고) {r['metrics']['peakiness']:.2f} " + tag("지금 계산 · 참고"), unsafe_allow_html=True)


def tab_a6():
    st.markdown("<div class='tt'>안전 중단 규칙 — 네 층, 기존보다 나빠지는 것을 막는다</div>", unsafe_allow_html=True)
    G6.month_card(O.DEMO_DAY)
    G6.replay_card()
    d = O.daily_rows(O.MODE_WIN)
    lose = d[d.변화kW > 0]
    c = st.columns(4)
    card(c[0], "당일", "현장 확인 필수 3요소 중 하나라도 어긋나면 → 즉시 기존 계획", "", "상태: 현장", small=True)
    card(c[1], "다음 날", "채점 패 → 비산정월 3연속 / 산정월 1회면 그 달 기존 운전", tag("제출 후 추가 분석"),
         f"상태: 테스트 패 {len(lose)}일, 모두 {'주말' if (lose.날짜.dt.dayofweek >= 5).all() else '평일 포함'}", small=True)
    card(c[2], "월", "직전 달 모의 운전이 현행보다 높으면 그 달은 측정만", bdg("N21a", "N21c", "N21d"),
         f"상태: 설계 달 {v('N21d'):.0f}개월 중 {v('N21a'):.0f}개월 운전 · 현행보다 높아진 달 {v('N21b'):.0f} {bdg('N21b')} · 중앙 {pct(v('N21c'))}", small=True)
    card(c[3], "단계", "준수율 70% 미만 2주 → 모의 운전으로 강등", "", "상태: " + fld("도입 후 측정"), small=True)
    st.markdown("")
    st.markdown(f"<div class='card'><b>실패 예시</b> — 단조공장 1의 7월 +{pct(v('N22a'))}가 A사 산정월에 나면 +{kw1(v('N22b'))}kW → 기본요금 월 +{v('N22c'):,.0f}원 → "
                f"산정월이면 최대 12개월 약 {man(v('N22d'))} 원(연 기본요금 절감 {man(-v('N8b'))} 원보다 큼) {bdg('N22a', 'N22b', 'N22c', 'N22d', 'N8b')}</div>", unsafe_allow_html=True)
    st.markdown("<div class='cpt'>중단 규칙은 손실을 막을 뿐 절감을 지켜 주지는 않습니다. 산정월에 멈추면 기존 피크가 돌아옵니다. trackB/_b3_gate.json</div>", unsafe_allow_html=True)


# ===================================================================================== 모드 B
TIMES = ["__:__"] + [f"{h:02d}:{mm:02d}" for h in range(24) for mm in (0, 30)]


@st.cache_data(show_spinner=False)
def cached_precheck(kw, month):
    return O.precheck_user(kw, month=month)


def sentence(parts, key):
    """문장 사이 빈칸 — parts: 글자(str) 또는 (위젯 함수, 인자 dict). 폭은 글자 길이 비례."""
    w = [max(0.5, len(p) / 4.6) if isinstance(p, str) else p[2] for p in parts]
    cols = st.columns(w + [max(0.3, 22 - sum(w))], vertical_alignment="center")          # 줄마다 전체 폭을 같게 — 빈칸이 글자 옆에 붙는다
    out = []
    for i, (c, p) in enumerate(zip(cols, parts)):
        if isinstance(p, str):
            c.markdown(p)
        else:
            out.append(p[0](c, **p[1], key=f"{key}_{i}", label_visibility="collapsed"))
    return out


def sel(c, options, index=0, **k):
    return c.selectbox("빈칸", options, index=index, **k)


def num(c, **k):
    return c.number_input("빈칸", **k)


def form_ui():
    """우리 공장 조건 — 항목마다 라벨이 붙은 입력칸(10/30: 문장 사이 빈칸 배치는 좁은 칸에서 글자가 세로로 깨져 바꿈). 돌려주는 값은 그대로."""
    st.markdown("<div class='tt'>우리 공장 조건 — 아래 칸을 채우면 그 조건으로 운전표를 만듭니다</div>", unsafe_allow_html=True)
    f = O.form_default()
    hours = list(range(25))
    st.markdown("**1. 근무 시간** — 사람이 있는 시간에만 작업을 재배치합니다")
    a, b, _ = st.columns([1, 1, 3])
    lo = a.selectbox("시작 시각(시)", hours, index=hours.index(f["win_lo"]), key="s1_1")
    hi = b.selectbox("끝 시각(시)", hours, index=hours.index(f["win_hi"]), key="s1_3")
    st.markdown("**2. 야간조**")
    a, b, c, _ = st.columns([1, 1, 1, 2])
    night = a.selectbox("야간조", ["없다", "있다"], key="s2_1") == "있다"
    nlo, nhi = f["night_lo"], f["night_hi"]
    if night:
        nlo = b.selectbox("야간 재배치 시작(시)", hours[:24], index=f["night_lo"], key="s2b_1")
        nhi = c.selectbox("야간 재배치 끝(시)", hours[:24], index=f["night_hi"], key="s2b_3")
    st.markdown("**3. 이동 가능한 부하 비중**")
    sopt = [f"모른다 → {pct(f['s'], 2)} 추정값(단조 2곳 전력 패턴)", "로거로 재어 안다 → 직접 입력(%)"]
    a, b, _ = st.columns([2.5, 1, 1.5], vertical_alignment="bottom")
    sk = a.selectbox("부하 비중", sopt, key="s3_1")
    s_val = f["s"]
    if sk == sopt[1]:
        x = b.number_input("로거로 잰 비중(%)", min_value=0.5, max_value=50.0, value=None, step=0.5, placeholder="__", key="s3b_1")
        s_val = None if x is None else x / 100
    else:
        b.markdown(tag("추정값 · 로거 3주 측정 권고"), unsafe_allow_html=True)
    st.markdown("**4. 이동 폭**")
    a, _ = st.columns([1, 4])
    L = a.selectbox("원래 시각에서 ±(시간)", [2, 3, 4], index=2, key="s4_1")
    st.markdown("**5. 작업 재배치 금지 시각**")
    k = st.columns(5)
    m0 = k[0].selectbox("금형 교체 시작", TIMES, key="s5_1")
    m1 = k[1].selectbox("금형 교체 끝", TIMES, key="s5_3")
    p0 = k[2].selectbox("예열 시작", TIMES, key="s5_5")
    p1 = k[3].selectbox("예열 끝", TIMES, key="s5_7")
    dr = k[4].selectbox("DR 발령", ["없음", "17~21시"], key="s5_9")
    st.markdown("**6. 요금**")
    a, b, _ = st.columns([2, 1.5, 1.5])
    tar = a.selectbox("전기 요금제", ["산업용(을) 고압A 선택Ⅰ", "산업용(을) 고압A 선택Ⅱ", "산업용(을) 고압A 선택Ⅲ", "모른다"], key="s6_1")
    bill = b.selectbox("이번 달이 산정월(12·1·2·7·8·9월)인가", ["이다", "아니다"], index=1, key="s7_1") == "이다"
    extra, extra_txt = [], []
    for name, a, b in (("금형 교체", m0, m1), ("예열", p0, p1)):
        if a != "__:__" and b != "__:__" and a < b:
            extra.append((int(a[:2]), int(a[3:]), int(b[:2]), int(b[3:]))); extra_txt.append(f"{name} {a}~{b} — 양식")
    if dr != "없음":
        extra_txt.append("DR 발령 17:00~21:00 — 양식")
    st.markdown("<div class='cpt'>이 조건은 운전표를 만드는 규칙에 그대로 들어갑니다(작업 재배치 금지 구간·이동 폭·비중). 자유 문장 입력은 두지 않았습니다 — 오프라인에서 해석할 수 없고, "
                "잘못 해석된 조건이 운전표에 들어가면 안 되기 때문입니다.</div>", unsafe_allow_html=True)
    form = dict(f, win_lo=int(lo), win_hi=int(hi), night=night, night_lo=int(nlo), night_hi=int(nhi), s=s_val, s_known=sk == sopt[1], L_hours=int(L),
                ban_extra=extra, dr=dr != "없음", tariff=tar, billing_month=bill)
    return form, extra_txt


def data_ui():
    a, b = st.columns([3, 2], vertical_alignment="bottom")
    up = a.file_uploader("15분 전력 CSV 올리기(timestamp, kw)", type=["csv"], key="up_b")
    if b.button("예시 데이터로 보기(UCI 철강 2018, 공개 데이터 · 이미 진단한 공장)", key="ex_b"):
        kw = O.steel_example()
        st.session_state["user_kw"] = kw
        st.session_state["user_info"] = O.read_user_csv(pd.DataFrame({"timestamp": kw.index, "kw": kw.values}))[1]
        st.session_state["user_src"] = "예시 — UCI 철강 2018"
    if up is not None:
        sig = hashlib.sha256(up.getvalue()).hexdigest()
        if st.session_state.get("user_sig") != sig:
            kw, info = O.read_user_csv(up)
            st.session_state["user_sig"] = sig
            if O.reject_if_asa(kw):
                st.session_state["user_kw"] = None
                st.session_state["user_reject"] = True
            else:
                st.session_state.update(user_kw=kw, user_info=info, user_src=up.name, user_reject=False)
    if st.session_state.get("user_reject"):
        st.error("거부 — A사 데이터는 재현 모드에서만. 테스트 기간은 다시 계산하지 않습니다.")
        return None
    kw = st.session_state.get("user_kw")
    if kw is None:
        st.info("15분 전력 CSV를 올리거나 예시 데이터로 보기를 누르십시오.")
        return None
    i = st.session_state.get("user_info") or O.read_user_csv(pd.DataFrame({"timestamp": kw.index, "kw": kw.values}))[1]
    st.markdown(f"<div class='card'>데이터 · {st.session_state.get('user_src', '올린 파일')} · 기간 {i['start'][:10]} ~ {i['end'][:10]} · 평일 {i['weekdays']}일 · "
                f"결측 {pct(i['missing'])} · 복제일 {i['dup_days']}일 · 단위 {i['unit']}{' (×4로 kW 변환)' if i['unit'] != 'kW' else ''} {ub()}</div>", unsafe_allow_html=True)
    return kw


def mode_b():
    st.markdown("<div class='sub'>자사 15분 전력과 공장 조건으로 지금 계산합니다. 이 모드의 숫자는 그 공장의 계산이며 발표 숫자가 아닙니다.</div>", unsafe_allow_html=True)
    kw = data_ui()
    form, extra_txt = form_ui()
    if kw is None:
        return
    D = O.F11.day_matrix(kw)
    last = max(D)
    cand = [last + pd.Timedelta(days=1)] + sorted([d for d in D if d > last - pd.Timedelta(days=14)], reverse=True)
    day = st.selectbox("운전표 날짜", cand, format_func=lambda d: fday(d) + (" — 자료 다음 날(계획만, 실측 없음)" if d not in D else " — 실측 있음(채점 가능)"), key="day_b")
    pc = cached_precheck(kw[kw.index < day], f"{pd.Timestamp(day):%Y-%m}")
    gate = O.gate_of(pc["verdict"])
    key = (st.session_state.get("user_sig") or st.session_state.get("user_src"), str(day), repr(sorted(form.items())))
    gen = st.session_state.get("gen_b")
    gen = gen if gen is not None and gen.get("_key") == key else None
    tabs = st.tabs(TABS_B, key="tab_b", on_change="rerun")
    if tabs[0].open:
        with tabs[0]:
            tab_b5(pc, gate)
    if tabs[1].open:
        with tabs[1]:
            gen = tab_b1(kw, day, form, gate, gen, key)
    if tabs[2].open:
        with tabs[2]:
            if gen is None:
                st.info("① 익일 운전표에서 운전표를 만들면 일정표가 나옵니다.")
            else:
                st.markdown("<div class='tt'>교대 반장 — 현장 확인 및 확정 · 운전원 배포용 일정표</div>" + tag("정해진 문장 틀 · 숫자는 운전표에서") + ub()
                            + (tag("모의 운전만(적용 금지)") if gate["mock_only"] else ""), unsafe_allow_html=True)
                html = O.paper_html(gen, O.MODE_WIN, extra_bans=extra_txt, window=(form["win_lo"], form["win_hi"]), site=O.SITE_USER)
                components.html(O.paper_html(gen, O.MODE_WIN, extra_bans=extra_txt, window=(form["win_lo"], form["win_hi"]), site=O.SITE_USER, screen=True),
                                height=900, scrolling=True)
                st.download_button("현장 운전원 배포용 일정표 다운로드(인쇄용)", data=html.encode("utf-8"), file_name=f"운전표_{pd.Timestamp(day):%Y%m%d}.html", mime="text/html", key="dl_b")
    if tabs[3].open:
        with tabs[3]:
            tab_b3(gen)
    if tabs[4].open:
        with tabs[4]:
            tab_b4(gen, form)
    if tabs[5].open:
        with tabs[5]:
            st.markdown("<div class='tt'>안전 중단 규칙 — 네 층, 기존보다 나빠지는 것을 막는다</div>", unsafe_allow_html=True)
            c = st.columns(4)
            card(c[0], "당일", "현장 확인 필수 3요소 중 하나라도 어긋나면 → 즉시 기존 계획", "", "상태: " + fld("도입 후 측정"), small=True)
            rule = "산정월 — 채점 패 1회면 그 달 기존 운전" if form["billing_month"] else "비산정월 — 채점 패 3연속이면 그 달 기존 운전"
            card(c[1], "다음 날", rule, "", "상태: " + fld("도입 후 측정"), small=True)
            card(c[2], "월", "직전 달 모의 운전이 현행보다 높으면 그 달은 측정만", "", "상태: " + fld("도입 후 측정"), small=True)
            card(c[3], "단계", "준수율 70% 미만 2주 → 모의 운전으로 강등", "", "상태: " + fld("도입 후 측정"), small=True)


def tab_b5(pc, gate):
    st.markdown("<div class='tt'>우리 공장 진단 — 도입 전, 15분 전력 두 달로</div>", unsafe_allow_html=True)
    a, b = st.columns([1, 1])
    with a:
        rule_card(pct_style=True)
    with b:
        m = pc["metrics"]
        h = m["peak_hour_hit_rate"]
        hp, hc = pct(v("N23a"), 2), pct(v("N23b"), 1)
        txt = {"권장": f"권장 — 적중률 {pct(h, 0)} ≥ {hp}. 운전표를 만들 수 있습니다.",
               "조건부": "조건부 — 1개월 모의 운전만. 적용하지 않습니다.",
               "비권장": f"비권장 — 피크 시각이 반복되지 않습니다(적중률 {pct(h, 0)} &lt; {hc}). 운전표를 만들지 않습니다.",
               "판정불가": "판정불가 — 판정 창의 평일이 모자라거나 결측이 많습니다. 운전표를 만들지 않습니다."}[pc["verdict"]]
        st.markdown(f"<div class='card'><div class='n w'>{txt}</div>적중률 {('—' if pd.isna(h) else pct(h, 0))} · 잰 평일 {m['hit_weekdays']}일 · 첨두성(참고) {m['peakiness']:.2f} · "
                    f"판정 창 {pc['window']['start']} ~ {pc['window']['end_exclusive']}(그 날 달의 직전 62일) {ub()}</div>", unsafe_allow_html=True)
        st.markdown("<div class='cpt'>판정 기준은 적중률 하나다. 피크의 뾰족한 정도는 참고로만 표시한다.</div>", unsafe_allow_html=True)


def tab_b1(kw, day, form, gate, gen, key):
    st.markdown("<div class='tt'>익일 운전표 — 전날까지 자료로 만든 계획(시나리오 평균 기준, 참고)</div>", unsafe_allow_html=True)
    b1, b2 = st.columns([1, 5], vertical_alignment="center")
    ready = gate["can_generate"] and form["s"] is not None
    clicked = b1.button("운전표 생성", type="primary", disabled=not ready, key="gen_b_btn")
    if not gate["can_generate"]:
        b2.markdown("<span class='bad'>도입하지 않음 — 피크 시각이 반복되지 않습니다</span> (⑤ 판정)" if gate["verdict"] == "비권장" else
                    "<span class='bad'>판정불가 — 운전표를 만들지 않습니다</span>", unsafe_allow_html=True)
    elif form["s"] is None:
        b2.markdown("<span class='bad'>3번 문장의 비중을 적어 주십시오.</span>", unsafe_allow_html=True)
    else:
        b2.markdown((tag("모의 운전만(적용 금지)") if gate["mock_only"] else "") +
                    "<span class='cpt'>유사일 검색 → 작업 일정 최적화(작업 재배치 금지 구간 적용) → 운전표. 그 날 실측은 쓰지 않습니다.</span>", unsafe_allow_html=True)
    if clicked:
        log = []
        with st.status("운전표 생성 중 — 실측 단계만 표시", expanded=True) as stt:
            def say(step, sec, note):
                line = J9.say_app(f"{step}{(' — ' + note) if note else ''} ({sec:.2f}초)")
                log.append(line); stt.write(line)
            t = time.perf_counter()
            gen = O.plan_user(kw, day, form, progress=say)
            stt.update(label=f"완료 · 합계 {time.perf_counter() - t:.2f}초", state="complete", expanded=False)
        gen["_key"], gen["_log"] = key, log
        st.session_state["gen_b"] = gen
    elif gen is not None:
        show_status_log(gen["_log"], gen["total_sec"])
    if gen is None:
        return None
    base, exp = gen["base"], gen["plans"][O.MODE_WIN]
    mock = tag("모의 운전만(적용 금지)") if gate["mock_only"] else ""
    c = st.columns(4)
    card(c[0], "예상 최대 (운전표 없음 → 적용, 시나리오 평균 기준·참고)", f"{kw1(base.max())} → {kw1(exp.max())} kW", ub() + mock, f"변화 {kw1(exp.max() - base.max())} kW")
    card(c[1], "시나리오", f"{len(gen['scen_days'])}일" if not gen["fallback"] else "직전 4주 중앙값 1줄", ub(),
         " · ".join(f"{pd.Timestamp(x):%m-%d}" for x in gen["scen_days"][:10]))
    card(c[2], "작업 재배치 금지 구간", f"{gen['ban'][O.MODE_WIN]:.0f} / 96", ub(), f"근무 {form['win_lo']:02d}~{form['win_hi']:02d}시 밖 + 양식 금지 칸")
    card(c[3], "작업 이동 폭 · 비중", f"±{form['L_hours']}시간 · {pct(gen['s'], 2)}", ub(), "추정값" if not form["s_known"] else "로거 측정값")
    g1, g2 = st.columns([3, 2])
    with g1:
        chart(gen["index"], {"예상 부하(운전표 없음)": base, "운전표 적용 예상": exp}, {"예상 부하(운전표 없음)": (NAVY, [1, 0]), "운전표 적용 예상": (AMBER, [6, 3])},
              exp - base, gen["ban_slots"], gen["scen"])
        st.markdown("<div class='cpt'>가는 회색선 = 시나리오 과거 날, 두 선은 그 평균 기준의 예상(참고). 옅은 회색 띠 = 작업 재배치 금지 구간. " + USER_BADGE + "</div>", unsafe_allow_html=True)
    with g2:
        st.markdown("**시간대별 부하 조정** (이동 에너지 5kWh 이상)" + ub(), unsafe_allow_html=True)
        st.markdown(move_html(O.move_table(gen["index"], base, exp)), unsafe_allow_html=True)
        st.markdown("**현장 확인 필수 3요소**", unsafe_allow_html=True)
        k = st.columns(3)
        card(k[0], "① 설비별 가동 구간 수가 계획과 같은가?", fld(), "", "")
        card(k[1], "② 일일 생산량이 당일 생산계획 수량 이상인가?", fld("현장 입력"), "", "")
        card(k[2], "③ 하루 총 전력 사용량에 변동이 없는가?", "예", ub(), f"예상 차 {abs(exp.sum() - base.sum()) / 4:.3f} kWh")
    return gen


def tab_b3(gen):
    st.markdown("<div class='tt'>일일 성과 분석 — 다음 날, 계획 대 실측</div>", unsafe_allow_html=True)
    if gen is None:
        st.info("다음 날 실측 CSV를 넣으면 채점합니다.")
        return
    sc = None
    if gen["realized"] is not None:
        sc = {"measured": gen["measured"], "realized": gen["realized"]}
    else:
        st.markdown("<div class='cpt'>다음 날 실측 CSV를 넣으면 채점합니다.</div>", unsafe_allow_html=True)
        f = st.file_uploader("그 날 15분 실측 CSV(timestamp, kw)", type=["csv"], key="up_b3")
        if f is not None:
            kw2, _ = O.read_user_csv(f)
            if O.reject_if_asa(kw2):
                st.error("거부 — A사 데이터는 재현 모드에서만. 테스트 기간은 다시 계산하지 않습니다.")
                return
            try:
                sc = O.score_user(gen, kw2)
            except ValueError as e:
                st.error(str(e)); return
    if sc is None:
        return
    y, o = sc["measured"], sc["realized"]
    c = st.columns(3)
    card(c[0], "실측 일최대 → 운전표 적용 일최대(사후 평가)", f"{kw1(y.max())} → {kw1(o.max())} kW", ub())
    card(c[1], "변화", f"{kw1(o.max() - y.max())} kW · {pct(o.max() / y.max() - 1)}", ub())
    card(c[2], "승/패", "패" if o.max() > y.max() + 1e-9 else "승", ub(), "패 = 운전표 적용 일최대가 실측보다 높음")
    chart(gen["index"], {"실측": y, "운전표 적용(실측에 같은 이동표)": o}, {"실측": (NAVY, [1, 0]), "운전표 적용(실측에 같은 이동표)": (AMBER, [6, 3])}, o - y, gen["ban_slots"])


def tab_b4(gen, form):
    st.markdown("<div class='tt'>이번 달 KPI — 산식만(연 환산 없음)</div>", unsafe_allow_html=True)
    if gen is None:
        st.info("① 익일 운전표를 만든 뒤 산식값을 계산합니다.")
        return
    base, exp = gen["base"], gen["plans"][O.MODE_WIN]
    tf = O.tariff_user(form, base.max(), exp.max(), gen["index"], base, exp)
    dk = exp.max() - base.max()
    rows = [("예상 최대 변화(시나리오 평균 기준)", f"{kw1(dk)} kW {ub()}")]
    if tf is None:
        rows.append(("요금", "요금제를 모른다 — kW만 표시, 원화 없음"))
    else:
        rows += [(f"기본요금 산식({tf['요금제']}, 단가 {tf['기본요금_단가']:,.0f}원/kW)", f"{won(tf['기본요금_월_차'])} {ub()}<br><span class='cpt'>{tf['주의']}</span>"),
                 ("전력량요금 산식(이 날 시간대 단가 × 이동 kWh)", f"{won(tf['전력량_일_차'])} {ub()}")]
    rows.append(("생산 손실", f"0개 (모형 — 작업을 옮기기만 한다) {ub()}"))
    for a in ("계약전력", "변압기 정격·부하율", "로거 가격·회수 기간"):
        rows.append((a, fld()))
    st.markdown("<table class='k'><tr><th>항목</th><th>이번 달 운전표 적용 시 산식값</th></tr>" + "".join(f"<tr><td><b>{a}</b></td><td>{b}</td></tr>" for a, b in rows) + "</table>",
                unsafe_allow_html=True)
    st.markdown("<div class='cpt'>예상 최대는 시나리오 평균 기준이며 실제 피크는 채점에서 확인합니다. 조건이 다른 금액은 더하지 않습니다.</div>", unsafe_allow_html=True)


if IS_A:
    mode_a(day_sel, cond_sel)
else:
    mode_b()
