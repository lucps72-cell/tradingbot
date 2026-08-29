# 거래 데이터베이스 구현 완료 요약

## 🎯 구현 목표
sideways 거래봇에 SQLite와 MySQL을 모두 지원하는 거래 데이터베이스 시스템을 구현하여, 거래 내역을 체계적으로 기록하고 분석할 수 있도록 함.

---

## ✅ 구현 완료 사항

### 1. 데이터베이스 코어 모듈
**파일**: `sideways/database.py`

#### 특징:
- ✅ 추상 베이스 클래스 `TradeDatabase` 정의
- ✅ SQLite 구현: `SQLiteDatabase` 클래스
- ✅ MySQL 구현: `MySQLDatabase` 클래스
- ✅ 데이터베이스 팩토리: `create_database()` 함수

#### 주요 기능:
```python
# 자동으로 적절한 데이터베이스 생성
db = create_database(config)

# 거래 기록 저장
db.save_trade(trade_data)

# 거래 기록 조회
trades = db.get_trades(symbol='BTC/USDT:USDT', limit=100)

# 통계 계산
stats = db.get_trade_statistics(symbol='BTC/USDT:USDT')
```

#### 테이블 스키마:
- **trades**: 거래 내역 저장
  - 기본 정보: symbol, side, entry_price, exit_price, quantity
  - 거래 정보: entry_time, exit_time, tp_price, sl_price
  - 손익 정보: pnl, pnl_pct, status
  - 메타 정보: signal_reason, order_type, leverage, entry_split_count

- **trade_details**: 향후 확장용 상세 정보 저장

### 2. 거래 레코더 모듈
**파일**: `sideways/trade_recorder.py`

#### 특징:
- ✅ 고수준 API 제공
- ✅ 거래 진입/청산 기록 자동화
- ✅ 거래 조회 및 통계 계산

#### 사용 방법:
```python
from sideways.trade_recorder import TradeRecorder
from sideways.config_loader import load_config

config = load_config('config.json')
recorder = TradeRecorder(config)

# 거래 진입 기록
recorder.record_entry(
    symbol='BTC/USDT:USDT',
    side='long',
    entry_price=45000.5,
    quantity=0.01,
    entry_usdt=450.0,
    tp_price=46000.0,
    sl_price=44000.0,
    signal_reason='EMA Crossover'
)

# 거래 조회
trades = recorder.get_trades(limit=100)
stats = recorder.get_statistics()

recorder.close()
```

### 3. 설정 시스템
**파일**: `sideways/config.json`

#### 추가된 설정:
```json
{
  "database": {
    "type": "sqlite",        // "sqlite" 또는 "mysql"
    "path": "sideways/trades.db",  // SQLite 파일 경로
    "host": "localhost",      // MySQL 호스트
    "port": 3306,             // MySQL 포트
    "user": "root",           // MySQL 사용자명
    "password": "",           // MySQL 비밀번호
    "database": "trading_bot", // MySQL 데이터베이스명
    "save_trades": true       // 거래 기록 저장 여부
  }
}
```

### 4. 메인 프로그램 통합
**파일**: `sideways/main.py`

#### 수정 사항:
- ✅ TradeRecorder import 추가
- ✅ main() 함수에서 TradeRecorder 초기화
- ✅ SidewaysStrategy에 trade_recorder 전달
- ✅ 프로그램 종료 시 데이터베이스 정상 종료

### 5. 전략 모듈 통합
**파일**: `sideways/sideways_strategy.py`

#### 수정 사항:
- ✅ TradeRecorder import 추가
- ✅ `__init__()` 메서드에 trade_recorder 파라미터 추가
- ✅ `execute_transaction()` 메서드에서 거래 진입 시 자동 기록

### 6. 의존성 관리
**파일**: `sideways/requirements.txt`

#### 추가 라이브러리:
```
pandas
ccxt
python-dotenv
mysql-connector-python  # MySQL 사용 시에만 필요
```

---

## 📚 문서 및 예시

### 1. 사용 설명서
**파일**: `sideways/DATABASE.md`

내용:
- ✅ 개요 및 설치 방법
- ✅ SQLite vs MySQL 설정 가이드
- ✅ 사용 방법 및 API 문서
- ✅ 데이터베이스 스키마 설명
- ✅ 직접 SQL 쿼리 예시
- ✅ 문제 해결 및 FAQ

### 2. 테스트 스크립트
**파일**: `sideways/test_database.py`

테스트 항목:
- ✅ SQLite 데이터베이스 생성 및 기본 동작
- ✅ TradeRecorder 통합 기능
- ✅ MySQL 연결 테스트 (선택)

실행 방법:
```bash
python sideways/test_database.py
```

### 3. 사용 예시
**파일**: `sideways/example_database_usage.py`

예시:
- ✅ 기본 조회 방법
- ✅ 심볼별 조회
- ✅ 통계 분석
- ✅ 일일 성과 분석
- ✅ 신호별 성과 분석
- ✅ DB 타입 선택 가이드

실행 방법:
```bash
python sideways/example_database_usage.py
```

---

## 🚀 사용 방법

### 빠른 시작 (SQLite)

1. **기본 설정 (이미 config.json에 포함됨)**
   ```json
   {
     "database": {
       "type": "sqlite",
       "path": "sideways/trades.db",
       "save_trades": true
     }
   }
   ```

2. **거래봇 실행**
   ```bash
   python sideways/main.py
   ```

3. **거래 내역 조회**
   ```bash
   # SQLite 명령줄에서
   sqlite3 sideways/trades.db
   SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;
   ```

### MySQL 설정

1. **MySQL 서버 준비**
   ```bash
   # 데이터베이스 생성
   mysql -u root -p
   CREATE DATABASE trading_bot CHARACTER SET utf8mb4;
   CREATE USER 'trading_bot'@'localhost' IDENTIFIED BY 'password';
   GRANT ALL PRIVILEGES ON trading_bot.* TO 'trading_bot'@'localhost';
   FLUSH PRIVILEGES;
   ```

2. **config.json 수정**
   ```json
   {
     "database": {
       "type": "mysql",
       "host": "localhost",
       "user": "trading_bot",
       "password": "password",
       "database": "trading_bot",
       "save_trades": true
     }
   }
   ```

3. **거래봇 실행**
   ```bash
   python sideways/main.py
   ```

---

## 📊 데이터베이스 구조

### 테이블: trades
```
id                INTEGER  거래 ID (자동 증가)
timestamp         TEXT     거래 기록 시간
symbol            TEXT     거래 심볼 (BTC/USDT:USDT 등)
side              TEXT     포지션 방향 (long/short)
entry_price       REAL     진입가
exit_price        REAL     청산가 (선택)
quantity          REAL     거래량
entry_usdt        REAL     진입 금액
entry_time        TEXT     진입 시간
exit_time         TEXT     청산 시간
tp_price          REAL     익절가
sl_price          REAL     손절가
pnl               REAL     손익 (USDT)
pnl_pct           REAL     손익률 (%)
status            TEXT     거래 상태 (open/closed/completed)
signal_reason     TEXT     신호 이유
order_type        TEXT     주문 유형 (market/limit)
leverage          INTEGER  레버리지
entry_split_count INTEGER  분할 진입 횟수
created_at        TEXT     생성 시간
updated_at        TEXT     수정 시간

인덱스:
- idx_symbol: symbol 필드 인덱싱
- idx_timestamp: timestamp 필드 인덱싱
- idx_side: side 필드 인덱싱
```

### 테이블: trade_details (향후 확장용)
```
id                INTEGER  세부 정보 ID
trade_id          INTEGER  거래 ID (외래키)
detail_type       TEXT     정보 유형
detail_data       TEXT     상세 데이터 (JSON 등)
created_at        TEXT     생성 시간
```

---

## 🔄 자동 거래 기록 흐름

```
SidewaysStrategy.execute_transaction()
  ↓
  거래 실행 성공
  ↓
  TradeRecorder.record_entry()
  ↓
  TradeDatabase.save_trade()
  ↓
  SQLite/MySQL에 저장
```

---

## 📈 성과 분석 예시

### 통계 조회
```python
stats = recorder.get_statistics()
# {
#   'total_trades': 100,
#   'winning_trades': 65,
#   'losing_trades': 35,
#   'total_pnl': 1500.50,
#   'avg_pnl_pct': 1.23,
#   'win_rate': 65.0,
#   'max_profit': 150.00,
#   'max_loss': -50.00
# }
```

### SQL 쿼리 분석
```sql
-- 일일 손익
SELECT 
    DATE(timestamp) as trade_date,
    SUM(pnl) as daily_pnl,
    COUNT(*) as trade_count,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades
FROM trades
WHERE status IN ('closed', 'completed')
GROUP BY DATE(timestamp)
ORDER BY trade_date DESC;

-- 심볼별 성과
SELECT 
    symbol,
    COUNT(*) as total_trades,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as win_rate,
    SUM(pnl) as total_pnl
FROM trades
WHERE status IN ('closed', 'completed')
GROUP BY symbol
ORDER BY total_pnl DESC;
```

---

## ⚙️ 설정 옵션

### save_trades (거래 저장 활성화)
```json
{
  "database": {
    "save_trades": true   // true: 저장, false: 로그만 기록
  }
}
```

### 데이터베이스 타입 선택
| 타입 | 용도 | 장점 | 단점 |
|------|------|------|------|
| sqlite | 로컬 단일 인스턴스 | 설정 간단, 별도 서버 불필요 | 멀티 인스턴스 미지원 |
| mysql | 서버 기반 멀티 인스턴스 | 확장성, 원격 접속 | 서버 설치 필요 |

---

## 🐛 문제 해결

### 1. "SQLite 데이터베이스 초기화 실패"
- 파일 권한 확인
- 디렉토리 존재 여부 확인

### 2. "MySQL 연결 실패"
- MySQL 서버 상태 확인
- 사용자명/비밀번호 확인
- 데이터베이스 존재 여부 확인

### 3. "거래가 저장되지 않음"
- config.json의 `save_trades` 값이 true인지 확인
- 로그에서 오류 메시지 확인

---

## 📝 파일 목록

### 새로 생성된 파일
1. `sideways/database.py` - 데이터베이스 코어 모듈
2. `sideways/trade_recorder.py` - 거래 레코더
3. `sideways/test_database.py` - 테스트 스크립트
4. `sideways/example_database_usage.py` - 사용 예시
5. `sideways/DATABASE.md` - 사용 설명서

### 수정된 파일
1. `sideways/config.json` - 데이터베이스 설정 추가
2. `sideways/main.py` - TradeRecorder 통합
3. `sideways/sideways_strategy.py` - 거래 기록 저장 로직 추가
4. `sideways/requirements.txt` - 의존성 추가

---

## 🎓 다음 단계

### 선택 사항:
1. **웹 대시보드**: 거래 현황을 시각화하는 대시보드 개발
2. **거래 분석**: 머신러닝을 활용한 성과 분석
3. **알림 시스템**: 손익 임계값 도달 시 알림
4. **데이터 아카이빙**: 오래된 거래 데이터 자동 아카이빙

---

## ✨ 결론

SQLite와 MySQL을 모두 지원하는 거래 데이터베이스 시스템이 완성되었습니다.

**핵심 특징:**
- ✅ 자동 거래 기록
- ✅ 유연한 데이터베이스 선택 (SQLite/MySQL)
- ✅ 구조화된 데이터 관리
- ✅ 쉬운 통계 및 분석
- ✅ 완벽한 문서 및 예시

**바로 사용 가능합니다!**
```bash
python sideways/main.py
```

거래 내역은 자동으로 데이터베이스에 저장됩니다.

---

*2026년 8월 29일 완료*
