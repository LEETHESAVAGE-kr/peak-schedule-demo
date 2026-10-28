# 주 테이블 특징 정의 — b0.py(베이스라인)와 f3.py(예측구간)가 같은 정의를 쓰게 한 곳에 둔다.
import pandas as pd, numpy as np, pathlib

B = pathlib.Path(__file__).parent
GB = ["hour", "생산량", "기온", "풍속", "습도", "강수량", "전기요금(계절)", "day", "d", "m", "공장인원", "인건비"]
CAL = ["hour", "day", "d", "m", "전기요금(계절)", "인건비"]
W = ["기온", "풍속", "습도", "강수량"]
PROD = ["생산량", "공장인원"]
LAG = ["lag_h", "lag_h1h", "lag1d", "lag1w", "roll1d"]
# 채택 구성 = B3⁻. 기상군에서 **풍속만 뺀다** — 열린 결정 §11-13(F6에서 종결).
# 풍속==0은 학습의 0.66%뿐인 희소값인데 그 층의 오차가 4.6배고 최대오차 116kW를 혼자 만든다(§6-9-D).
# 선택 근거는 검증 8월(시드 5/5 승, 중앙 −0.441)이고 테스트는 확인으로만 읽었다(5/5, −0.257).
WIND = "풍속"
B3 = CAL + LAG + [c for c in W if c != WIND] + PROD
TR, VA, TE = slice(None, "2021-07-31"), slice("2021-08-01", "2021-08-31"), slice("2021-09-01", "2021-09-14")


def load():
    return pd.read_csv(B / "build/main_15min.csv", encoding="utf-8-sig",
                       index_col=0, parse_dates=True).dropna(subset=["kw"])


def frame(q0, h):
    """h슬롯(15분×h) 앞 예측용 테이블. 특징은 전부 예측 시점 이전 관측."""
    d = q0.copy()
    d["lag_h"] = d["kw"].shift(h)          # 예측 시점의 마지막 관측
    d["lag_h1h"] = d["kw"].shift(h + 3)    # 그 1시간 전
    d["lag1d"] = d["kw"].shift(96)
    d["lag1w"] = d["kw"].shift(672)
    d["roll1d"] = d["kw"].shift(h).rolling(96).mean()
    return d.dropna(subset=LAG + GB)


def mae(y, p):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))


if __name__ == "__main__":
    q0 = load()
    d = frame(q0, 4)
    assert d["lag_h"].equals(q0["kw"].shift(4).loc[d.index]), "horizon 위반: lag가 h슬롯보다 가깝다"
    assert len(d[TR]) and len(d[VA]) and len(d[TE]), "분할 구간이 비었다"
    print(f"frame(4) {d.shape} | 학습 {len(d[TR])} 보정 {len(d[VA])} 테스트 {len(d[TE])}")
