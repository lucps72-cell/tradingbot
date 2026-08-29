# 거래 데이터베이스 (Trade Database) 가이드

sideways 거래봇에 SQLite와 MySQL을 모두 지원하는 거래 데이터베이스 시스템이 통합되었습니다.

## 📋 목차
1. [개요](#개요)
2. [설치](#설치)
3. [설정](#설정)
4. [사용 방법](#사용-방법)
5. [데이터베이스 스키마](#데이터베이스-스키마)
6. [조회 및 분석](#조회-및-분석)

---

## 개요

거래 기록을 구조화된 데이터베이스에 저장하여:
- ✅ 거래 내역 체계적 관리
- ✅ 거래량 통계 및 분석
- ✅ 손익률 추적
- ✅ 거래 신호 검증
- ✅ 멀티-인스턴스 환경 지원

### 지원 데이터베이스
- **SQLite**: 로컬 단일 인스턴스용 (기본값, 설정 없음)
- **MySQL**: 서버 기반 멀티 인스턴스용

---

## 설치

### 1. 필수 패키지 설치
```bash
pip install -r requirements.txt
```

### 2. MySQL 사용 시 추가 설치 (선택)
```bash
pip install mysql-connector-python
```

---

## 설정

### config.json 설정

#### SQLite (기본 설정)
```json
{
  "database": {
    "type": "sqlite",
    "path": "sideways/trades.db",
    "save_trades": true
  }
}
```

#### MySQL 설정
```json
{
  "database": {
    "type": "mysql",
    "host": "localhost",
    "port": 3306,
    "user": "trading_bot",
    "password": "your_password",
    "database": "trading_bot",
    "save_trades": true
  }
}
```

### 설정 옵션 설명

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `type` | 데이터베이스 타입 (`sqlite` 또는 `mysql`) | `sqlite` |
| `path` | SQLite 파일 경로 (SQLite만 해당) | `sideways/trades.db` |
| `host` | MySQL 서버 호스트 (MySQL만 해당) | `localhost` |
| `port` | MySQL 서버 포트 (MySQL만 해당) | `3306` |
| `user` | MySQL 사용자명 (MySQL만 해당) | `root` |
| `password` | MySQL 비밀번호 (MySQL만 해당) | `` (빈 문자열) |
| `database` | MySQL 데이터베이스명 (MySQL만 해당) | `trading_bot` |
| `save_trades` | 거래 기록 저장 여부 | `true` |

---

## 사용 방법

### 1. 자동 저장 (권장)
거래봇을 실행하면 자동으로 거래 내역이 데이터베이스에 저장됩니다.

```bash
python main.py
```

**저장되는 정보:**
- 거래 시간 (timestamp)
- 심볼 (symbol)
- 포지션 방향 (long/short)
- 진입가 (entry_price)
- 청산가 (exit_price)
- 거래량 (quantity)
- 진입 금액 (entry_usdt)
- 손익 (pnl)
- 손익률 (pnl_pct)
- 신호 이유 (signal_reason)
- 기타 메타데이터

### 2. 수동 기록 (프로그래밍)

```python
from sideways.trade_recorder import TradeRecorder
from sideways.config_loader import load_config

# 설정 로드
config = load_config('config.json')

# TradeRecorder 초기화
trade_recorder = TradeRecorder(config)

# 거래 진입 기록
trade_recorder.record_entry(
    symbol='BTC/USDT:USDT',
    side='long',
    entry_price=45000.5,
    quantity=0.01,
    entry_usdt=450.0,
    tp_price=46000.0,
    sl_price=44000.0,
    signal_reason='EMA 골든크로스',
    leverage=50,
    entry_split_count=1
)

# 거래 청산 기록
trade_recorder.record_exit(
    symbol='BTC/USDT:USDT',
    side='long',
    exit_price=45500.0,
    quantity=0.01,
    entry_price=45000.5,
    entry_usdt=450.0,
    pnl=5.0,
    pnl_pct=1.11,
    exit_reason='익절'
)

# 데이터베이스 연결 종료
trade_recorder.close()
```

### 3. 거래 내역 조회

```python
from sideways.trade_recorder import TradeRecorder
from sideways.config_loader import load_config

config = load_config('config.json')
trade_recorder = TradeRecorder(config)

# 최근 100개 거래 조회
trades = trade_recorder.get_trades(limit=100)
for trade in trades:
    print(trade)

# 특정 심볼 거래 조회
btc_trades = trade_recorder.get_trades(symbol='BTC/USDT:USDT', limit=50)

# 통계 조회
stats = trade_recorder.get_statistics(symbol='BTC/USDT:USDT')
print(f"총 거래: {stats.get('total_trades')}")
print(f"승률: {stats.get('win_rate'):.2f}%")
print(f"총 손익: ${stats.get('total_pnl'):.2f}")
print(f"최대 손익: ${stats.get('max_profit'):.2f}")
print(f"최대 손실: ${stats.get('max_loss'):.2f}")

trade_recorder.close()
```

---

## 데이터베이스 스키마

### trades 테이블

거래 내역을 저장하는 주요 테이블입니다.

```sql
-- SQLite
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL,
    exit_price REAL,
    quantity REAL,
    entry_usdt REAL,
    entry_time TEXT,
    exit_time TEXT,
    tp_price REAL,
    sl_price REAL,
    pnl REAL,
    pnl_pct REAL,
    status TEXT,
    signal_reason TEXT,
    order_type TEXT,
    leverage INTEGER,
    entry_split_count INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- MySQL
CREATE TABLE trades (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    entry_price DECIMAL(20, 8),
    exit_price DECIMAL(20, 8),
    quantity DECIMAL(20, 8),
    entry_usdt DECIMAL(20, 2),
    entry_time DATETIME,
    exit_time DATETIME,
    tp_price DECIMAL(20, 8),
    sl_price DECIMAL(20, 8),
    pnl DECIMAL(20, 2),
    pnl_pct DECIMAL(10, 6),
    status VARCHAR(20),
    signal_reason TEXT,
    order_type VARCHAR(20),
    leverage INT,
    entry_split_count INT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_symbol (symbol),
    INDEX idx_timestamp (timestamp),
    INDEX idx_side (side)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### trade_details 테이블 (향후 확장용)

거래 상세 정보를 저장하기 위한 테이블입니다.

```sql
-- SQLite
CREATE TABLE trade_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER,
    detail_type TEXT,
    detail_data TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(trade_id) REFERENCES trades(id)
);

-- MySQL
CREATE TABLE trade_details (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trade_id INT,
    detail_type VARCHAR(50),
    detail_data LONGTEXT,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(trade_id) REFERENCES trades(id),
    INDEX idx_trade_id (trade_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

## 조회 및 분석

### SQLite 직접 조회

#### 명령줄
```bash
# SQLite CLI 열기
sqlite3 sideways/trades.db

# 최근 거래 조회
SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;

# 심볼별 거래 통계
SELECT 
    symbol,
    COUNT(*) as total_trades,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(pnl) as total_pnl,
    AVG(pnl_pct) as avg_pnl_pct
FROM trades
WHERE status IN ('closed', 'completed')
GROUP BY symbol;

# 일일 거래 통계
SELECT 
    DATE(timestamp) as trade_date,
    COUNT(*) as trades_count,
    SUM(pnl) as daily_pnl,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades
FROM trades
WHERE status IN ('closed', 'completed')
GROUP BY DATE(timestamp)
ORDER BY trade_date DESC;
```

### Python 조회

```python
from sideways.trade_recorder import TradeRecorder
from sideways.config_loader import load_config

config = load_config('config.json')
recorder = TradeRecorder(config)

# 오늘의 거래 조회
import datetime
today = datetime.date.today()
trades = recorder.db.get_trades()
today_trades = [t for t in trades if t['timestamp'].startswith(str(today))]
print(f"오늘 거래: {len(today_trades)}건")

# 심볼별 승률
all_trades = recorder.db.get_trades()
symbols = {}
for trade in all_trades:
    symbol = trade['symbol']
    if symbol not in symbols:
        symbols[symbol] = {'total': 0, 'wins': 0}
    symbols[symbol]['total'] += 1
    if trade['pnl'] and trade['pnl'] > 0:
        symbols[symbol]['wins'] += 1

for symbol, data in symbols.items():
    win_rate = (data['wins'] / data['total'] * 100) if data['total'] > 0 else 0
    print(f"{symbol}: {data['total']}거래, {win_rate:.1f}% 승률")

recorder.close()
```

---

## 문제 해결

### 1. SQLite 파일 권한 문제
```bash
# 파일 권한 확인
ls -la sideways/trades.db

# 권한 변경 (필요시)
chmod 666 sideways/trades.db
```

### 2. MySQL 연결 실패
```bash
# MySQL 서버 상태 확인
mysql -u root -p -e "SELECT 1;"

# 데이터베이스 생성
CREATE DATABASE trading_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# 사용자 생성 (권장)
CREATE USER 'trading_bot'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON trading_bot.* TO 'trading_bot'@'localhost';
FLUSH PRIVILEGES;
```

### 3. 거래 기록이 저장되지 않음
1. `config.json`의 `save_trades` 값이 `true`인지 확인
2. 데이터베이스 타입 설정이 올바른지 확인
3. 로그에서 에러 메시지 확인

```bash
# 로그 확인
tail -f sideways/logs/tradingbot.log | grep -i "database\|trade"
```

---

## FAQ

**Q: SQLite와 MySQL 중 어떤 것을 사용해야 하나요?**
- A: 단일 PC에서 운영하면 SQLite를, 여러 인스턴스를 관리하거나 웹 대시보드를 만들 계획이면 MySQL을 추천합니다.

**Q: 기존 거래 기록을 데이터베이스로 마이그레이션할 수 있나요?**
- A: 별도의 마이그레이션 스크립트를 작성할 수 있습니다. 필요시 문의해주세요.

**Q: 데이터베이스 크기가 커지면 어떻게 하나요?**
- A: MySQL을 사용하면 쉽게 확장할 수 있으며, 정기적인 아카이브 정책을 수립할 수 있습니다.

**Q: 거래 기록 저장 비활성화 방법은?**
- A: `config.json`의 `save_trades`를 `false`로 설정하면 데이터베이스에 저장되지 않습니다.

---

## 라이선스

이 모듈은 sideways 거래봇의 일부입니다.
