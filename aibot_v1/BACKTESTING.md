# 백테스트 가이드 (Backtesting Guide)

## 개요

백테스트 기능은 라이브 트레이딩 전에 과거 데이터를 사용하여 거래 전략의 성능을 검증할 수 있게 해줍니다.

## 사용 방법

### 기본 백테스트 (30일)
```bash
python main.py --backtest
```

### 커스텀 기간 백테스트
```bash
# 60일 테스트
python main.py --backtest --days 60

# 90일 테스트
python main.py --backtest --days 90
```

### 커스텀 파라미터로 백테스트
```bash
# SL 0.5%, TP 1.0%로 30일 테스트
python main.py --backtest --days 30 --sl 0.5 --tp 1.5

# BTCUSDT 심볼, SL 1.0%, TP 2.0%로 테스트
python main.py --backtest --symbol BTCUSDT --sl 1.0 --tp 2.0
```

## 백테스트 작동 원리

### 1. 과거 데이터 수집
- CCXT를 통해 Bybit에서 과거 1시간 봉 데이터 다운로드
- 지정된 기간(기본 30일)의 모든 캔들 로드

### 2. 기술 지표 계산
- **RSI (14일)**: 과매도/과매수 판단
- **볼린저 밴드 (20일)**: 지지/저항 레벨

### 3. 거래 신호 생성
거래 진입 조건 (포지션 없을 때):
- **Long**: RSI < 30 (과매도)
- **Short**: RSI > 70 (과매수)

거래 종료 조건:
- **Take Profit (TP)**: 수익률 = TP_RATIO (기본 0.4%)
- **Stop Loss (SL)**: 손실률 = SL_RATIO (기본 0.2%)
- **Timeout**: 24시간 이상 보유 시 강제 종료
- **End**: 데이터 마지막 날 강제 종료

### 4. 성능 지표 계산
거래마다 시뮬레이션되고 다음과 같은 지표들이 계산됩니다:
- 승률 (Win Rate)
- 평균 손익 (Average PnL)
- 최대 인출 (Max Drawdown)
- 손익비 (Profit Factor)
- Sharpe Ratio
- 기타 통계

## 출력 결과

### 콘솔 출력
```
══════════════════════════════════════════════════════════════
BACKTEST REPORT
══════════════════════════════════════════════════════════════

Symbol                        : ETHUSDT
Data Period                   : ETHUSDT
Timeframe                     : 1h
Starting Balance              : 10,000.00 USDT
Ending Balance                : 10,480.25 USDT
Peak Balance                  : 10,520.75 USDT

Total Return                  : +480.25 USDT (+4.80%)

Total Trades                  : 15
Winning Trades                : 9 (60.0%)
Losing Trades                 : 6 (40.0%)

Average PnL                   : +32.02 USDT
Average Win                   : +65.45 USDT
Average Loss                  : -45.30 USDT
Max Win                       : +120.50 USDT
Max Loss                      : -95.75 USDT

Max Drawdown                  : 3.25% (325.50 USDT)
Profit Factor                 : 1.45
Sharpe Ratio                  : 1.23

Exit Reasons:
  TP                            :   9 (60.0%)
  SL                            :   6 (40.0%)
  TIMEOUT                       :   0 ( 0.0%)
  END                           :   0 ( 0.0%)

══════════════════════════════════════════════════════════════
```

### CSV 파일 출력
`backtest_trades.csv` 파일이 자동 생성됩니다:

```csv
trade_id,entry_time,entry_price,side,amount,sl_price,tp_price,exit_time,exit_price,exit_reason,pnl,pnl_percent
1,2025-12-06 10:00:00,2500.45,long,5000.0,2497.53,2510.50,2025-12-06 11:30:00,2510.55,TP,101.25,0.40
2,2025-12-06 12:00:00,2510.20,short,5000.0,2513.25,2507.30,2025-12-06 14:45:00,2507.35,TP,144.25,0.57
...
```

## 성능 지표 설명

### 기본 지표
- **Total Trades**: 시뮬레이션 중 실행된 거래 총 개수
- **Win Rate**: 수익성 있는 거래의 비율
- **Total Return**: 초기 자본 대비 수익 (절대값 및 비율)

### 수익 분석
- **Average PnL**: 거래당 평균 손익
- **Average Win/Loss**: 승리/패배 거래의 평균 손익
- **Max Win/Loss**: 최대 수익/손실 거래
- **Profit Factor**: 총 수익 / 총 손실 (> 1.5 권장)

### 위험 지표
- **Max Drawdown**: 최고점에서 최저점까지의 낙폭
  - < 10%: 좋음
  - 10-20%: 보통
  - > 20%: 높음
  
- **Sharpe Ratio**: 위험 대비 수익률
  - > 1.0: 우수
  - 0.5-1.0: 양호
  - < 0.5: 미흡

### Exit Reasons
거래가 종료된 이유:
- **TP**: Take Profit 도달
- **SL**: Stop Loss 도달
- **TIMEOUT**: 24시간 초과 보유
- **END**: 데이터 종료

## 권장 사항

### 1. 다양한 파라미터 테스트
```bash
# SL/TP 비율 조정
python main.py --backtest --days 30 --sl 0.3 --tp 0.5
python main.py --backtest --days 30 --sl 0.5 --tp 1.0
python main.py --backtest --days 30 --sl 1.0 --tp 2.0

# 긴 기간 테스트
python main.py --backtest --days 90
python main.py --backtest --days 180
```

### 2. 결과 해석
- **Win Rate > 50%**: 기본 조건 만족
- **Profit Factor > 1.5**: 좋은 성능
- **Sharpe Ratio > 1.0**: 위험 조정 수익 우수
- **Max Drawdown < 10%**: 낮은 위험

### 3. 라이브 트레이딩 전 체크리스트
- [ ] 30일 이상 백테스트 수행
- [ ] Win Rate > 40% 확인
- [ ] Profit Factor > 1.2 확인
- [ ] Max Drawdown < 15% 확인
- [ ] 다양한 시장 조건에서 테스트
- [ ] SL/TP 비율 최적화

## 주의 사항

### 백테스트의 한계
1. **과거 데이터만 사용**: 과거 성능이 미래를 보장하지 않음
2. **슬리피지 미반영**: 실제 주문 가격과의 차이 미계산
3. **거래 수수료 미반영**: 거래 수수료 자동 차감되지 않음
4. **단순 신호**: 실제 거래는 더 복잡한 조건 포함
5. **스프레드 미반영**: 호가 스프레드 미계산
6. **유동성 미반영**: 대량 거래 시 가격 영향 미반영

### 권고사항
- 백테스트 결과 수익률의 50% 정도만 실현된다고 예상
- 작은 금액으로 라이브 거래 시작 후 점진적 확대
- 실제 거래 결과를 계속 모니터링 및 파라미터 조정

## 문제 해결

### "Failed to fetch historical data" 오류
- API 호출 제한 확인
- .env 파일의 API 키 유효성 확인
- 인터넷 연결 확인

### 백테스트가 느린 경우
- 테스트 기간 단축 (`--days 30`)
- 다른 작업 줄이기
- 네트워크 속도 확인

### 결과가 너무 좋아 보이는 경우
- 과적합(overfitting) 가능성 검토
- 더 긴 기간 테스트 수행
- 다양한 시장 조건에서 테스트

## API 사용법

```python
from backtester import Backtester
import config_loader
import ccxt

# 설정 로드
config = config_loader.load_config('config.json')
exchange = ccxt.bybit({...})

# 백테스터 생성
bt = Backtester(config, exchange)

# 데이터 수집
df = bt.fetch_historical_data(days=30)

# 백테스트 실행
bt.run_backtest(df)

# 결과 조회
metrics = bt.get_performance_metrics()
print(f"총 거래: {metrics['total_trades']}")
print(f"승률: {metrics['win_rate']:.1f}%")
print(f"총 수익: {metrics['total_return_usdt']:+.2f} USDT")

# 리포트 출력
bt.print_report()

# 결과 내보내기
bt.export_trades_to_csv('results.csv')
```

## 향후 개선 계획

- [ ] 거래 수수료 반영
- [ ] 슬리피지 시뮬레이션
- [ ] 보다 정교한 포지션 크기 조정
- [ ] 다중 타임프레임 분석
- [ ] 파라미터 최적화 자동화
- [ ] 시각화 (차트, 등락률 그래프)
- [ ] Monte Carlo 시뮬레이션

---

**마지막 팁**: 백테스트는 거래 전략 검증의 첫 단계일 뿐입니다. 실제 시장의 변수성과 심리적 요인까지 고려하여 항상 신중하게 접근하세요.
