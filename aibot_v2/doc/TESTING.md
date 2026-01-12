# Aibot v2 테스트 및 백테스트 가이드

## 개요

**aibot_v2**는 다음 두 가지 모드로 운영됩니다:

1. **라이브 트레이딩 (main.py)**: 실시간 바이비트 거래
2. **백테스트 (backtester.py)**: 과거 데이터로 전략 검증 (독립 스크립트)

---

## 1. 라이브 트레이딩 (main.py)

### 실행 방법

```bash
# 기본 설정으로 실행
python main.py

# 커스텀 주문 금액
python main.py --amount 150

# 특정 설정 파일 사용
python main.py --config custom_config.json
```

### 파라미터

| 파라미터 | 기본값 | 설명 |
|---------|-------|------|
| `--config` | `config.json` | 설정 파일 경로 |
| `--amount` | `100` | 한 번의 거래 금액 (USDT) |

### 실행 결과

- **심볼**: config.json에서 지정한 심볼 (기본: XRPUSDT)
- **레버리지**: config.json에서 지정한 레버리지 (기본: 50x)
- **로그**: `logs/tradingbot.log` 에 저장 (일일 롤링)
- **신호 감지 시**: 자동으로 롱/숏 포지션 진입
- **종료**: Ctrl+C 누르면 우아하게 종료

### 주요 기능

✅ 다중 시간봉 추세 분석 (15m → 5m → 1m)  
✅ RSI 다이버전스 감지  
✅ EMA 지지선 확인  
✅ 거래량 증가 신호  
✅ 시장 구조 이탈 신호  
✅ ATR 기반 동적 손절/익절 (선택적, config에서 `use_atr_sl: true`로 활성화)  
✅ 틱(tick) 크기 정렬  
✅ 헤지 모드 포지션 관리 (Long/Short 동시)  
✅ 한글 로그 출력

---

## 2. 백테스트 (backtester.py)

### 특징

- **독립 실행**: 메인 스크립트와 분리
- **커맨드라인 파라미터**: 유연한 설정
- **상세한 통계**: 승률, 손익, 드로우다운 등

### 실행 방법

```bash
# 기본 설정 (30일, XRPUSDT, 100 USDT)
python backtester.py

# 커스텀: 60일 XRPUSDT 백테스트
python backtester.py --days 60 --symbol XRPUSDT

# 커스텀: 90일 BTCUSDT 백테스트 (주문당 200 USDT)
python backtester.py --days 90 --symbol BTCUSDT --amount 200

# 특정 설정 파일 사용
python backtester.py --config custom_config.json --days 30
```

### 파라미터

| 파라미터 | 기본값 | 설명 |
|---------|-------|------|
| `--config` | `config.json` | 설정 파일 경로 |
| `--symbol` | `XRPUSDT` | 거래 심볼 |
| `--days` | `30` | 백테스트 기간 (일) |
| `--amount` | `100` | 한 거래당 금액 (USDT) |

### 실행 결과

```
============================================================
[BACKTEST MODE]
============================================================

[수행 중...]

============================================================
[BACKTEST RESULTS]
============================================================
기간: 30일
심볼: XRPUSDT
총 거래: 15
승리: 10
패배: 5
승률: 66.67%
수익: 12.50%
평균 거래: 83.33 USDT
Profit Factor: 2.50
최대 드로우다운: -8.50%

백테스트가 완료되었습니다.
```

### 결과 해석

| 지표 | 의미 |
|------|------|
| 총 거래 | 백테스트 기간 동안의 총 거래 수 |
| 승리/패배 | 수익거래 / 손실거래 |
| 승률 | 수익거래 비율 |
| 수익 | 초기 잔액 대비 총 손익률 (%) |
| 평균 거래 | 한 거래당 평균 손익 (USDT) |
| Profit Factor | 총 수익 / 총 손실 (> 1.5 이상이 양호) |
| 최대 드로우다운 | 최대 낙폭 (%) |

---

## 3. 설정 파일 (config.json)

### 전략 설정

```json
{
  "strategy": {
    "timeframes": {
      "higher_trend": ["15m"],
      "lower_signal": ["5m"],
      "entry_trigger": "1m"
    },
    "ema": {
      "fast": 9,
      "medium": 20,
      "slow": 60
    },
    "rsi": {
      "period": 14,
      "overbought": 65,
      "oversold": 35,
      "use_divergence": true
    }
  }
}
```

### 리스크 관리 설정

```json
{
  "risk_management": {
    "use_atr_sl": false,        // ATR 기반 동적 손절 활성화 (true로 변경 시 적용)
    "atr_period": 14,            // ATR 계산 기간
    "sl_ratio": 0.01,            // 기본 손절 비율 (1%)
    "tp_ratio": 0.02             // 기본 익절 비율 (2%)
  }
}
```

### 거래 설정

```json
{
  "trading": {
    "symbol": "XRPUSDT",
    "order_amount_usdt": 100,
    "leverage": 50,
    "exchange": "bybit"
  }
}
```

---

## 4. 워크플로우 예시

### 시나리오: 새로운 전략 검증

```bash
# 1단계: 백테스트로 전략 성과 확인 (30일)
python backtester.py --days 30 --symbol XRPUSDT

# 2단계: 더 긴 기간으로 검증 (90일)
python backtester.py --days 90 --symbol XRPUSDT

# 3단계: 결과가 만족스러우면 라이브 거래
python main.py

# 4단계: 운영 중 실시간 로그 모니터링
tail -f logs/tradingbot.log
```

### 시나리오: 설정 조정 후 재검증

```bash
# 1. config.json 수정 (예: ATR 활성화)
# {
#   "risk_management": {
#     "use_atr_sl": true   <-- 변경
#   }
# }

# 2. 백테스트로 영향도 확인
python backtester.py --config config.json --days 30

# 3. 결과 비교
# (이전 결과와 비교하여 개선 여부 판단)

# 4. 라이브 거래 적용
python main.py --config config.json
```

---

## 5. 로그 위치

- **라이브 거래**: `logs/tradingbot.log`
- **일일 롤링**: `logs/tradingbot.log.2026-01-06` (YYYY-MM-DD 형식)
- **로그 레벨**: DEBUG (모든 신호, 가격, 지표값 포함)

### 로그 확인

```bash
# 실시간 로그 추적 (Windows PowerShell)
Get-Content logs\tradingbot.log -Wait -Tail 50

# 또는 (cmd)
type logs\tradingbot.log
```

---

## 6. 주의사항

### 라이브 거래 시

⚠️ **실제 자금이 움직입니다**. 다음 점을 확인하세요:

1. `.env` 파일에 올바른 Bybit API 키/시크릿이 있는지 확인
2. `config.json`에서 `order_amount_usdt`가 원하는 금액인지 확인
3. 레버리지가 적절한지 확인 (기본 50x)
4. 필요시 먼저 백테스트로 전략 검증
5. 처음에는 작은 금액으로 시작 권장

### 백테스트 시

- 과거 데이터 기반이므로 실제 거래와 완전히 일치하지 않을 수 있음
- 슬리페이지(slippage) 미적용
- 거래량 미적용
- ATR 기반 정제는 라이브 거래에만 적용 (백테스트는 기본 전략 기반)

---

## 7. 트러블슈팅

### 백테스트 실행 안 됨

```bash
# 문제: "config.json not found"
# 해결: backtester.py가 있는 디렉토리에서 실행
cd C:\tradingbot\aibot_v2
python backtester.py

# 또는 경로 지정
python backtester.py --config C:\tradingbot\aibot_v2\config.json
```

### 라이브 거래 API 에러

```
# 문제: "Bybit API error: ... "
# 확인사항:
# 1. .env 파일 존재 및 API 키/시크릿 확인
# 2. 인터넷 연결 확인
# 3. Bybit 계정의 거래 권한 확인
# 4. API 속도 제한(Rate Limit) 확인
```

### 손절/익절이 설정 안 됨

```json
// config.json 확인
{
  "risk_management": {
    "use_atr_sl": false  // true로 변경하면 ATR 기반 손절/익절 적용
  }
}
```

---

## 8. 파일 구조

```
aibot_v2/
├── main.py                    # 라이브 거래 (순수 실행)
├── backtester.py              # 백테스트 (독립 스크립트)
├── config.json                # 설정 파일
├── trend_strategy.py          # 추세 분석
├── position_manager.py        # 거래 실행 및 관리
├── technical_indicators.py    # 지표 계산
├── risk_manager.py            # 리스크 관리
├── config_loader.py           # 설정 로드
├── log_config.py              # 로깅 설정
├── color_utils.py             # 색상 출력
├── validation.py              # 유효성 검증
├── TESTING.md                 # 이 파일
├── logs/
│   ├── tradingbot.log         # 현재 로그
│   └── tradingbot.log.2026-01-06  # 이전 로그
└── __pycache__/
```

---

## 9. FAQ

**Q: 백테스트와 라이브 거래의 차이는?**  
A: 백테스트는 과거 데이터로 전략을 검증합니다. 라이브 거래는 실제 시장에서 돈을 벌거나 잃습니다.

**Q: ATR 기반 손절/익절을 사용하려면?**  
A: `config.json`에서 `use_atr_sl: true`로 변경 후 라이브 거래를 시작하세요. (백테스트에는 미적용)

**Q: 여러 심볼을 동시에 거래할 수 있나?**  
A: 현재 버전은 한 심볼씩만 지원합니다. 다른 심볼은 다른 instance로 실행하세요. (프로세스 잠금 권장)

**Q: 거래 기록은 어디에 저장되나?**  
A: 백테스트 결과는 콘솔 출력 및 `logs/tradingbot.log`에 기록됩니다. 라이브 거래도 로그에 모두 기록됩니다.

---

## 10. 연락처 및 지원

- 문제 발생 시 로그(`logs/tradingbot.log`) 확인
- 설정 오류 시 `config.json` 문법 확인
- API 오류 시 `.env` 파일 및 Bybit 계정 확인

---

**마지막 업데이트**: 2026-01-07  
**버전**: aibot_v2
