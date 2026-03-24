## 실행 방법 (Windows)
python -m sideways.main

# sideways/README.md
이 폴더는 평균 회귀(Mean Reversion) 및 박스권(횡보장) 전략을 위한 소스코드를 포함합니다.
- 구조는 aibot_v2를 참고하되, 일관성/가독성을 위해 파일명, 함수명, 변수명을 재구성합니다.
- 기존 v2의 검증, 로깅, 포지션/리스크 관리, 지표 계산 등 모듈을 적극 활용합니다.
- 전략별 주요 파일은 아래와 같습니다.

## 기본 파일 구조
- config_loader.py : 설정 파일 로딩
- technical_indicators.py : 기술적 지표 계산 (Bollinger Band, RSI 등)
- validation.py : 데이터 검증 및 유효성 체크
- log_config.py : 로깅 설정
- position_manager.py : 포지션 관리
- risk_manager.py : 리스크 관리
- sideways_strategy.py : 평균 회귀/박스권 전략 로직
- main.py : 실행 진입점
- requirements.txt : 의존성 명시


지지선 / 저항선 = 가격의 “의사결정 구역” : 가격 반응이 일어나는 곳
  1.이전 고점/저점
  2.횡보 구간
  3.거래량 집중 구간
      상승 + 거래량 증가 → 진짜 상승 (신뢰도 높음)
      상승 + 거래량 감소 → 가짜 상승 (되돌림 가능성)
      하락 + 거래량 증가 → 패닉/추세 하락


📌 ✅ ❌ ⚠️ 🌟 ⭐️ 📉 📈 💹 🎯 📊 ⏰ 💰
1️⃣
매도/매수 원칙 case 1.
    EMA 정배열 시 매도 금지
    EMA 역배열 시 매수 금지
예외사항
    RSI 과열지역(과매수)에서 연속봉(상승)이 아닐때 ===> 매도 허용
    RSI 과열지역(과매도)에서 연속봉(하락)이 아닐때 ===> 매수 허용

매도/매수 원칙 case 2.
    Bollinger Band 상한선/하한선 매매

추세가 상승이면 매수-청산 시점을 찾는다.
추세가 하락이면 매도-청산 시점을 찾는다.
추세가 횡보이면 매수/매도 시점을 찾는다.

🟢 1차 추세 판단 : 상승 ==> ⚪ 2차 추세 판단 : 횡보  상태 변경시
🔴 1차 추세 판단 : 하락 ==> ⚪ 2차 추세 판단 : 횡보
매수-청산 시점 : 밴드 상단 아래 + RSI (과매수 or 아래), 연속 하락봉 발생시
매도-청산 시점 : 밴드 하단 위  + RSI (과매도 or 위), 연속 상승봉 발생시

저항선 체크

# 급격한 가격 변동시 포지션 진입
#   진입(매도) : 거래량 급증 + 밴드 하단 돌파 + RSI 과매도 이후 반등 + 되돌림 확인 후 진입
#   진입(매수) : 거래량 급증 + 밴드 상단 돌파 + RSI 과매수 이후 하락 + 되돌림 확인 후 진입


config.json의 트레일링 스탑 관련 설정값 의미는 다음과 같습니다:

"use_trailing_stop": true
  → 트레일링 스탑 기능을 사용할지 여부 (true면 활성화)
"trailing_stop_activation": 0.01
  → 진입 후 1% 수익이 발생하면 트레일링 스탑이 활성화됨 (예: 진입가 대비 1% 상승/하락 시)
"trailing_stop_distance": 0.005
  → 트레일링 스탑의 거리(폭), 0.5% (예: 활성화 이후 최고가/최저가에서 0.5% 역행하면 청산)

"use_profit_trailing": true
  → 이익구간 트레일링(Profit Trailing) 기능 사용 여부
"profit_trailing_activation": 0.007
  → 이익 트레일링 발동 기준, 0.7% 수익 발생 시부터 적용
"profit_trailing_drawdown": 0.3
  → 이익 트레일링 드로우다운 비율, 최고 수익에서 30% 이상 수익이 줄어들면 청산

즉,
트레일링 스탑은 진입 후 일정 수익이 발생하면 활성화되고,
이후 가격이 최고점(또는 최저점)에서 일정 비율(거리)만큼 역행하면 포지션을 청산합니다.
이익 트레일링은 추가로, 최고 수익에서 일정 비율만큼 수익이 줄어들면 청산하는 기능입니다.

상세설명:
"use_trailing_stop", "trailing_stop_activation", "trailing_stop_distance"

트레일링 스탑(기본):
진입 후 일정 이익(activation) 이상이 되면, 손절가(SL)를 진입가보다 위로 올려서 이익을 보호합니다.
가격이 trailing_stop_distance만큼 반전하면 포지션을 청산합니다.
즉, 이익이 발생하면 SL을 따라 올리고, 가격이 일정 거리만큼 떨어지면 자동 청산.

"use_profit_trailing", "profit_trailing_activation", "profit_trailing_drawdown"
프로핏 트레일링(이익 추적):
최대 이익(peak profit)을 추적하며, activation 이상 이익이 발생하면 drawdown(이익에서 일정 비율 하락)만큼 반전 시 청산합니다.
SL을 단순히 올리는 것이 아니라, 이익이 최고점에서 얼마나 떨어졌는지(드로우다운)를 기준으로 청산.
요약:

트레일링 스탑: SL을 올리고, 가격이 일정 거리만큼 반전하면 청산.
프로핏 트레일링: 최고 이익에서 일정 비율 하락(drawdown) 시 청산.