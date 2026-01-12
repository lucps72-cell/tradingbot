# Risk Management System

## 개요 (Overview)

Trading Bot에 통합된 위험 관리 시스템은 계좌 보호와 손실 제한을 위한 다층 안전 메커니즘을 제공합니다.

## 주요 기능 (Key Features)

### 1. 최대 인출 추적 (Max Drawdown Tracking)
- **목적**: 최고 잔고 대비 현재 손실률 추적
- **기본값**: 10% (설정 가능)
- **동작**: 최대 인출률 도달 시 모든 거래 차단

### 2. 일일 손실 한도 (Daily Loss Limit)
- **목적**: 하루 동안의 최대 손실 제한
- **설정 방법**: 
  - 퍼센트 기반: `daily_loss_limit_percent` (기본 5%)
  - 절대값 기반: `daily_loss_limit_usdt` (선택사항)
- **동작**: 일일 한도 도달 시 당일 거래 차단
- **리셋**: 매일 자정에 자동 리셋

### 3. 연속 손실 보호 (Consecutive Loss Protection)
- **목적**: 연속된 손실 거래 시 거래 일시 중단
- **기본값**: 5회 연속 손실 (설정 가능)
- **동작**: 제한 도달 시 거래 차단, 승리 시 카운터 리셋

### 4. 동적 포지션 크기 조정 (Dynamic Position Sizing)
- **목적**: 위험 수준에 따라 포지션 크기 자동 조정
- **기본 설정**:
  - 기본 크기: 5000 USDT
  - 최소 크기: 1000 USDT
  - 최대 크기: 10000 USDT
- **조정 메커니즘**:
  - 승리 시: 포지션 크기 증가 (최대 1.5배)
  - 손실 시: 포지션 크기 감소 (최소 0.5배)
  - 높은 인출률: 추가 감소 (30-50%)
  - 연속 손실: 매 손실마다 20% 감소

### 5. 위험 등급 시스템 (Risk Level System)
- **Safe** (0-3%): 정상 운영, 제한 없음
- **Low** (3-5%): 경미한 위험, 포지션 크기 15% 감소
- **Medium** (5-8%): 중간 위험, 포지션 크기 30% 감소
- **High** (8-10%): 높은 위험, 포지션 크기 50% 감소
- **Critical** (10%+): 거래 차단

## 설정 방법 (Configuration)

`config.json`의 `risk_management` 섹션에서 설정:

```json
{
  "risk_management": {
    "max_drawdown_percent": 10.0,          // 최대 인출률 (%)
    "daily_loss_limit_percent": 5.0,       // 일일 손실 한도 (%)
    "daily_loss_limit_usdt": null,         // 일일 손실 한도 (USDT) - 선택사항
    "max_consecutive_losses": 5,           // 최대 연속 손실 횟수
    "enable_dynamic_sizing": true,         // 동적 포지션 크기 조정 활성화
    "base_position_size": 5000,            // 기본 포지션 크기 (USDT)
    "min_position_size": 1000,             // 최소 포지션 크기 (USDT)
    "max_position_size": 10000,            // 최대 포지션 크기 (USDT)
    "risk_level_low": 3.0,                 // Low 위험 임계값 (%)
    "risk_level_medium": 5.0,              // Medium 위험 임계값 (%)
    "risk_level_high": 8.0                 // High 위험 임계값 (%)
  }
}
```

## 사용 예시 (Usage Examples)

### 보수적 설정 (Conservative Settings)
```json
{
  "risk_management": {
    "max_drawdown_percent": 5.0,
    "daily_loss_limit_percent": 2.0,
    "max_consecutive_losses": 3,
    "enable_dynamic_sizing": true,
    "base_position_size": 3000,
    "min_position_size": 500,
    "max_position_size": 5000
  }
}
```

### 공격적 설정 (Aggressive Settings)
```json
{
  "risk_management": {
    "max_drawdown_percent": 15.0,
    "daily_loss_limit_percent": 8.0,
    "max_consecutive_losses": 7,
    "enable_dynamic_sizing": true,
    "base_position_size": 8000,
    "min_position_size": 2000,
    "max_position_size": 15000
  }
}
```

### 고정 크기 모드 (Fixed Size Mode)
```json
{
  "risk_management": {
    "max_drawdown_percent": 10.0,
    "daily_loss_limit_percent": 5.0,
    "max_consecutive_losses": 5,
    "enable_dynamic_sizing": false,        // 동적 조정 비활성화
    "base_position_size": 5000
  }
}
```

## 로그 출력 (Log Output)

Risk Manager는 주기적으로 상태를 로그에 출력합니다:

```
────────────────────────────────────────────────────────────
RISK MANAGEMENT STATUS
────────────────────────────────────────────────────────────
Balance             : 10500.00 USDT (Peak: 11000.00)
Drawdown            : 4.55% / 10.0%
Daily Loss          : 250.00 USDT (2.38% / 5.0%)
Consecutive Losses  : 2 / 5
Position Multiplier : 0.80x
Recommended Size    : 3400.00 USDT
Risk Level          : MEDIUM
Trading Status      : ✓ ALLOWED
────────────────────────────────────────────────────────────
```

## 거래 차단 메시지 (Trade Blocking Messages)

시스템이 거래를 차단할 때 표시되는 메시지들:

1. **최대 인출 도달**:
   ```
   🚫 TRADING BLOCKED: Max drawdown limit reached: 10.05% (Limit: 10.0%)
   ```

2. **일일 손실 한도 도달**:
   ```
   🚫 TRADING BLOCKED: Daily loss limit reached: 5.12% (Limit: 5.0%)
   ```

3. **연속 손실 한도 도달**:
   ```
   🚫 TRADING BLOCKED: Too many consecutive losses: 5 (Limit: 5)
   ```

## 모니터링 및 알림 (Monitoring & Alerts)

### 실시간 모니터링
- 매 거래 루프마다 잔고 업데이트
- 설정된 간격(기본 10회 루프)마다 위험 상태 로그 출력
- 포지션 종료 시 자동으로 거래 결과 기록

### 알림 시점
- 위험 등급 변경 시 (Safe → Low → Medium → High → Critical)
- 거래 차단 발생 시
- 신규 최고 잔고 도달 시

## 권장 사항 (Best Practices)

1. **초기 설정**: 보수적인 설정으로 시작 (5% 인출, 2% 일일 손실)
2. **모니터링**: 정기적으로 로그 확인 및 설정 조정
3. **백테스팅**: 새 설정 적용 전 백테스트 실행 권장
4. **잔고 비율**: 포지션 크기는 전체 잔고의 10-20% 이내 권장
5. **한도 설정**: daily_loss_limit_usdt를 설정하여 절대 손실 제한 추가 고려

## API 참조 (API Reference)

### RiskManager 클래스

#### 초기화
```python
risk_mgr = RiskManager(config['risk_management'])
```

#### 주요 메서드
- `update_balance(balance: float)` - 잔고 업데이트 및 인출률 계산
- `can_trade() -> Tuple[bool, Optional[str]]` - 거래 가능 여부 확인
- `calculate_position_size() -> float` - 권장 포지션 크기 계산
- `record_trade_result(pnl: float, is_win: bool)` - 거래 결과 기록
- `get_status() -> Dict` - 현재 위험 관리 상태 반환
- `log_status()` - 상태를 로그에 출력

## 문제 해결 (Troubleshooting)

### 거래가 차단됩니다
1. 로그에서 차단 이유 확인
2. 위험 한도 설정 조정 고려
3. 수동으로 손실 포지션 정리 후 재시작

### 포지션 크기가 너무 작습니다
1. `min_position_size` 설정 확인
2. 연속 손실 카운터 확인 (승리 시 리셋됨)
3. 인출률 확인 및 필요 시 입금

### 일일 한도가 너무 빨리 도달합니다
1. `daily_loss_limit_percent` 증가 고려
2. 거래 전략 검토 (SL/TP 비율 조정)
3. 시장 변동성이 높은 시간대 거래 피하기

## 제한 사항 (Limitations)

1. **수동 거래**: 봇 외부에서 수동으로 한 거래는 추적되지 않음
2. **슬리피지**: 실제 거래 가격과 예상 가격 차이는 고려되지 않음
3. **수수료**: 거래 수수료는 PnL 계산에 자동 포함되지 않음
4. **다중 심볼**: 현재는 단일 심볼만 추적 (다중 심볼 거래 시 전체 잔고 추적)

## 향후 개선 계획 (Future Enhancements)

- [ ] Kelly Criterion 기반 포지션 크기 계산
- [ ] 변동성 기반 동적 SL/TP 조정
- [ ] 시간대별 위험 프로파일
- [ ] 텔레그램/이메일 알림 통합
- [ ] 다중 심볼 위험 관리
- [ ] 포트폴리오 수준 위험 관리

---

**주의**: 위험 관리 시스템은 손실을 완전히 방지할 수 없으며, 보조 도구로만 사용해야 합니다. 암호화폐 거래는 높은 위험을 수반하므로 투자 전 충분한 학습과 이해가 필요합니다.
