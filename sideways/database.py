"""
거래 데이터베이스 관리 모듈
SQLite와 MySQL 모두 지원하는 추상화 레이어
"""
import sqlite3
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, List, Any
import json

active_logger = logging.getLogger(__name__)

# =============================================================================
# 추상 베이스 클래스
# =============================================================================
class TradeDatabase(ABC):
    """거래 데이터베이스 추상 클래스"""
    
    @abstractmethod
    def initialize(self) -> bool:
        """데이터베이스 초기화"""
        pass
    
    @abstractmethod
    def save_trade(self, trade_data: Dict[str, Any]) -> bool:
        """거래 기록 저장"""
        pass

    @abstractmethod
    def close_trade(self, symbol: str, side: str, trade_data: Dict[str, Any]) -> bool:
        """열린 거래를 청산 정보로 갱신"""
        pass
    
    @abstractmethod
    def get_trades(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """거래 기록 조회"""
        pass
    
    @abstractmethod
    def get_trade_statistics(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """거래 통계 계산"""
        pass
    
    @abstractmethod
    def close(self):
        """데이터베이스 연결 종료"""
        pass


# =============================================================================
# SQLite 구현
# =============================================================================
class SQLiteDatabase(TradeDatabase):
    """SQLite 기반 거래 데이터베이스"""
    
    def __init__(self, db_path: str = "sideways/trades.db"):
        """
        Args:
            db_path: SQLite 데이터베이스 파일 경로
        """
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.initialize()
    
    def initialize(self) -> bool:
        """SQLite 데이터베이스 초기화"""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.cursor = self.conn.cursor()
            
            # trades 테이블 생성
            self.cursor.execute("SHOW TABLES LIKE 'trades'")
            if not self.cursor.fetchone():
                self.cursor.execute('''
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
                )
            ''')
            
            # trade_details 테이블 (세부 거래 기록)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS trade_details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER,
                    detail_type TEXT,
                    detail_data TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trade_id) REFERENCES trades(id)
                )
            ''')
            
            # 인덱스 생성
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_side ON trades(side)')
            
            self.conn.commit()
            active_logger.info(f"SQLite 데이터베이스 초기화 완료: {self.db_path}")
            return True
        except Exception as e:
            active_logger.error(f"SQLite 데이터베이스 초기화 실패: {e}")
            return False
    
    def save_trade(self, trade_data: Dict[str, Any]) -> bool:
        """거래 기록 저장"""
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # trade_data 검증 및 기본값 설정
            required_fields = {
                'symbol': trade_data.get('symbol', 'UNKNOWN'),
                'side': trade_data.get('side', ''),
                'entry_price': trade_data.get('entry_price'),
                'exit_price': trade_data.get('exit_price'),
                'quantity': trade_data.get('quantity', 0),
                'entry_usdt': trade_data.get('entry_usdt', 0),
                'tp_price': trade_data.get('tp_price'),
                'sl_price': trade_data.get('sl_price'),
                'pnl': trade_data.get('pnl'),
                'pnl_pct': trade_data.get('pnl_pct'),
                'status': trade_data.get('status', 'open'),
                'signal_reason': trade_data.get('signal_reason', ''),
                'order_type': trade_data.get('order_type', 'market'),
                'leverage': trade_data.get('leverage', 1),
                'entry_split_count': trade_data.get('entry_split_count', 1),
            }
            
            # timestamp 설정
            timestamp = trade_data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            entry_time = trade_data.get('entry_time')
            exit_time = trade_data.get('exit_time')
            
            self.cursor.execute('''
                INSERT INTO trades (
                    timestamp, symbol, side, entry_price, exit_price, quantity,
                    entry_usdt, entry_time, exit_time, tp_price, sl_price,
                    pnl, pnl_pct, status, signal_reason, order_type, leverage,
                    entry_split_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                timestamp, required_fields['symbol'], required_fields['side'],
                required_fields['entry_price'], required_fields['exit_price'],
                required_fields['quantity'], required_fields['entry_usdt'],
                entry_time, exit_time, required_fields['tp_price'],
                required_fields['sl_price'], required_fields['pnl'],
                required_fields['pnl_pct'], required_fields['status'],
                required_fields['signal_reason'], required_fields['order_type'],
                required_fields['leverage'], required_fields['entry_split_count'],
                now, now
            ))
            
            self.conn.commit()
            trade_id = self.cursor.lastrowid
            active_logger.debug(f"SQLite 거래 저장 완료 (ID: {trade_id}): {required_fields['symbol']} {required_fields['side']}")
            return True
        except Exception as e:
            active_logger.error(f"SQLite 거래 저장 실패: {e}")
            return False

    def close_trade(self, symbol: str, side: str, trade_data: Dict[str, Any]) -> bool:
        """가장 최근의 열린 거래를 청산 정보로 갱신"""
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.cursor.execute('''
                SELECT id FROM trades
                WHERE symbol = ? AND side = ? AND status = 'open'
                ORDER BY id DESC LIMIT 1
            ''', (symbol, side))
            row = self.cursor.fetchone()
            if not row:
                active_logger.warning(f"SQLite 열린 거래를 찾을 수 없음: {symbol} {side}")
                return False

            self.cursor.execute('''
                UPDATE trades
                SET exit_price = ?, exit_time = ?, pnl = ?, pnl_pct = ?,
                    status = 'closed', signal_reason = ?, updated_at = ?
                WHERE id = ?
            ''', (
                trade_data.get('exit_price'), trade_data.get('exit_time'),
                trade_data.get('pnl'), trade_data.get('pnl_pct'),
                trade_data.get('signal_reason', ''), now, row[0]
            ))
            self.conn.commit()
            active_logger.debug(f"SQLite 거래 청산 갱신 완료 (ID: {row[0]}): {symbol} {side}")
            return self.cursor.rowcount == 1
        except Exception as e:
            active_logger.error(f"SQLite 거래 청산 갱신 실패: {e}")
            return False
    
    def get_trades(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """거래 기록 조회"""
        try:
            if symbol:
                self.cursor.execute(
                    'SELECT * FROM trades WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?',
                    (symbol, limit)
                )
            else:
                self.cursor.execute(
                    'SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?',
                    (limit,)
                )
            
            columns = [description[0] for description in self.cursor.description]
            trades = [dict(zip(columns, row)) for row in self.cursor.fetchall()]
            return trades
        except Exception as e:
            active_logger.error(f"SQLite 거래 조회 실패: {e}")
            return []
    
    def get_trade_statistics(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """거래 통계 계산"""
        try:
            if symbol:
                self.cursor.execute('''
                    SELECT
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                        SUM(pnl) as total_pnl,
                        AVG(pnl_pct) as avg_pnl_pct,
                        MAX(pnl) as max_profit,
                        MIN(pnl) as max_loss,
                        SUM(entry_usdt) as total_usdt
                    FROM trades
                    WHERE symbol = ? AND status IN ('closed', 'completed')
                ''', (symbol,))
            else:
                self.cursor.execute('''
                    SELECT
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                        SUM(pnl) as total_pnl,
                        AVG(pnl_pct) as avg_pnl_pct,
                        MAX(pnl) as max_profit,
                        MIN(pnl) as max_loss,
                        SUM(entry_usdt) as total_usdt
                    FROM trades
                    WHERE status IN ('closed', 'completed')
                ''')
            
            row = self.cursor.fetchone()
            if row:
                columns = [description[0] for description in self.cursor.description]
                stats = dict(zip(columns, row))
                
                # Win rate 계산
                total = stats['total_trades'] or 0
                winning = stats['winning_trades'] or 0
                stats['win_rate'] = (winning / total * 100) if total > 0 else 0
                
                return stats
            return {}
        except Exception as e:
            active_logger.error(f"SQLite 통계 조회 실패: {e}")
            return {}
    
    def close(self):
        """데이터베이스 연결 종료"""
        try:
            if self.conn:
                self.conn.close()
                active_logger.info("SQLite 데이터베이스 연결 종료")
        except Exception as e:
            active_logger.error(f"SQLite 연결 종료 실패: {e}")


# =============================================================================
# MySQL 구현
# =============================================================================
class MySQLDatabase(TradeDatabase):
    """MySQL 기반 거래 데이터베이스"""
    
    def __init__(self, host: str, user: str, password: str, database: str, port: int = 3306):
        """
        Args:
            host: MySQL 서버 호스트
            user: 사용자명
            password: 비밀번호
            database: 데이터베이스명
            port: MySQL 포트 (기본값: 3306)
        """
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.port = port
        self.conn = None
        self.cursor = None
        self.initialized = self.initialize()
    
    def initialize(self) -> bool:
        """MySQL 데이터베이스 초기화"""
        try:
            import mysql.connector
            
            # 1단계: 데이터베이스 없이 MySQL에 먼저 연결
            temp_conn = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                port=self.port,
                connection_timeout=5,
                use_pure=True
            )
            temp_cursor = temp_conn.cursor()
            
            # 데이터베이스 생성 (없으면)
            temp_cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{self.database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            temp_conn.commit()
            temp_cursor.close()
            temp_conn.close()
            
            # 2단계: 생성된 데이터베이스에 연결
            self.conn = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database,
                port=self.port,
                connection_timeout=5,
                use_pure=True
            )
            self.cursor = self.conn.cursor(dictionary=True)
            
            # trades 테이블 생성
            self.cursor.execute("SHOW TABLES LIKE 'trades'")
            if not self.cursor.fetchone():
                self.cursor.execute('''
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
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
            
            # trade_details 테이블 생성
            self.cursor.execute("SHOW TABLES LIKE 'trade_details'")
            if not self.cursor.fetchone():
                self.cursor.execute('''
                CREATE TABLE trade_details (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    trade_id INT,
                    detail_type VARCHAR(50),
                    detail_data LONGTEXT,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(trade_id) REFERENCES trades(id),
                    INDEX idx_trade_id (trade_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
            
            self.conn.commit()
            print(f"[MySQL] 데이터베이스 초기화 완료: {self.host}/{self.database}")
            return True
        except Exception as e:
            print(f"[MySQL] 데이터베이스 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def save_trade(self, trade_data: Dict[str, Any]) -> bool:
        """거래 기록 저장"""
        try:
            if not self.initialized or not self.conn or not self.cursor:
                active_logger.error("MySQL 거래 저장 실패: 데이터베이스 연결이 초기화되지 않았습니다.")
                return False
            
            now = datetime.now()
            
            # trade_data 검증 및 기본값 설정
            required_fields = {
                'symbol': trade_data.get('symbol', 'UNKNOWN'),
                'side': trade_data.get('side', ''),
                'entry_price': trade_data.get('entry_price'),
                'exit_price': trade_data.get('exit_price'),
                'quantity': trade_data.get('quantity', 0),
                'entry_usdt': trade_data.get('entry_usdt', 0),
                'tp_price': trade_data.get('tp_price'),
                'sl_price': trade_data.get('sl_price'),
                'pnl': trade_data.get('pnl'),
                'pnl_pct': trade_data.get('pnl_pct'),
                'status': trade_data.get('status', 'open'),
                'signal_reason': trade_data.get('signal_reason', ''),
                'order_type': trade_data.get('order_type', 'market'),
                'leverage': trade_data.get('leverage', 1),
                'entry_split_count': trade_data.get('entry_split_count', 1),
            }
            
            # timestamp 설정
            timestamp = trade_data.get('timestamp', now)
            if isinstance(timestamp, str):
                timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            
            entry_time = trade_data.get('entry_time')
            if isinstance(entry_time, str):
                entry_time = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S') if entry_time else None
            
            exit_time = trade_data.get('exit_time')
            if isinstance(exit_time, str):
                exit_time = datetime.strptime(exit_time, '%Y-%m-%d %H:%M:%S') if exit_time else None
            
            self.cursor.execute('''
                INSERT INTO trades (
                    timestamp, symbol, side, entry_price, exit_price, quantity,
                    entry_usdt, entry_time, exit_time, tp_price, sl_price,
                    pnl, pnl_pct, status, signal_reason, order_type, leverage,
                    entry_split_count, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                timestamp, required_fields['symbol'], required_fields['side'],
                required_fields['entry_price'], required_fields['exit_price'],
                required_fields['quantity'], required_fields['entry_usdt'],
                entry_time, exit_time, required_fields['tp_price'],
                required_fields['sl_price'], required_fields['pnl'],
                required_fields['pnl_pct'], required_fields['status'],
                required_fields['signal_reason'], required_fields['order_type'],
                required_fields['leverage'], required_fields['entry_split_count'],
                now, now
            ))
            
            self.conn.commit()
            active_logger.debug(f"MySQL 거래 저장 완료: {required_fields['symbol']} {required_fields['side']}")
            return True
        except Exception as e:
            active_logger.error(f"MySQL 거래 저장 실패: {e}")
            return False

    def close_trade(self, symbol: str, side: str, trade_data: Dict[str, Any]) -> bool:
        """가장 최근의 열린 거래를 청산 정보로 갱신"""
        try:
            if not self.initialized or not self.conn or not self.cursor:
                active_logger.error("MySQL 거래 청산 실패: 데이터베이스 연결이 초기화되지 않았습니다.")
                return False
            now = datetime.now()
            self.cursor.execute('''
                SELECT id FROM trades
                WHERE symbol = %s AND side = %s AND status = 'open'
                ORDER BY id DESC LIMIT 1
            ''', (symbol, side))
            row = self.cursor.fetchone()
            if not row:
                active_logger.warning(f"MySQL 열린 거래를 찾을 수 없음: {symbol} {side}")
                return False

            trade_id = row['id']
            self.cursor.execute('''
                UPDATE trades
                SET exit_price = %s, exit_time = %s, pnl = %s, pnl_pct = %s,
                    status = 'closed', signal_reason = %s, updated_at = %s
                WHERE id = %s
            ''', (
                trade_data.get('exit_price'), trade_data.get('exit_time'),
                trade_data.get('pnl'), trade_data.get('pnl_pct'),
                trade_data.get('signal_reason', ''), now, trade_id
            ))
            self.conn.commit()
            active_logger.debug(f"MySQL 거래 청산 갱신 완료 (ID: {trade_id}): {symbol} {side}")
            return self.cursor.rowcount == 1
        except Exception as e:
            active_logger.error(f"MySQL 거래 청산 갱신 실패: {e}")
            return False
    
    def get_trades(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """거래 기록 조회"""
        try:
            if symbol:
                self.cursor.execute(
                    'SELECT * FROM trades WHERE symbol = %s ORDER BY timestamp DESC LIMIT %s',
                    (symbol, limit)
                )
            else:
                self.cursor.execute(
                    'SELECT * FROM trades ORDER BY timestamp DESC LIMIT %s',
                    (limit,)
                )
            
            trades = self.cursor.fetchall()
            return trades if trades else []
        except Exception as e:
            active_logger.error(f"MySQL 거래 조회 실패: {e}")
            return []
    
    def get_trade_statistics(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """거래 통계 계산"""
        try:
            if symbol:
                self.cursor.execute('''
                    SELECT
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                        SUM(pnl) as total_pnl,
                        AVG(pnl_pct) as avg_pnl_pct,
                        MAX(pnl) as max_profit,
                        MIN(pnl) as max_loss,
                        SUM(entry_usdt) as total_usdt
                    FROM trades
                    WHERE symbol = %s AND status IN ('closed', 'completed')
                ''', (symbol,))
            else:
                self.cursor.execute('''
                    SELECT
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                        SUM(pnl) as total_pnl,
                        AVG(pnl_pct) as avg_pnl_pct,
                        MAX(pnl) as max_profit,
                        MIN(pnl) as max_loss,
                        SUM(entry_usdt) as total_usdt
                    FROM trades
                    WHERE status IN ('closed', 'completed')
                ''')
            
            row = self.cursor.fetchone()
            if row:
                stats = dict(row)
                
                # Win rate 계산
                total = stats['total_trades'] or 0
                winning = stats['winning_trades'] or 0
                stats['win_rate'] = (winning / total * 100) if total > 0 else 0
                
                return stats
            return {}
        except Exception as e:
            active_logger.error(f"MySQL 통계 조회 실패: {e}")
            return {}
    
    def close(self):
        """데이터베이스 연결 종료"""
        try:
            if self.conn:
                self.conn.close()
                active_logger.info("MySQL 데이터베이스 연결 종료")
        except Exception as e:
            active_logger.error(f"MySQL 연결 종료 실패: {e}")


# =============================================================================
# 데이터베이스 팩토리
# =============================================================================
def create_database(config: Dict[str, Any]) -> Optional[TradeDatabase]:
    """
    설정에 따라 적절한 데이터베이스 인스턴스 생성
    
    Args:
        config: 데이터베이스 설정 딕셔너리
        
    Returns:
        TradeDatabase 인스턴스 또는 None
    """
    try:
        db_config = config.get('database', {})
        db_type = db_config.get('type', 'sqlite').lower()
        
        if db_type == 'sqlite':
            db_path = db_config.get('path', 'sideways/trades.db')
            db = SQLiteDatabase(db_path)
            active_logger.info(f"SQLite 데이터베이스 생성: {db_path}")
            return db
        
        elif db_type == 'mysql':
            db = MySQLDatabase(
                host=db_config.get('host', 'localhost'),
                user=db_config.get('user', 'root'),
                password=db_config.get('password', ''),
                database=db_config.get('database', 'trading_bot'),
                port=db_config.get('port', 3306)
            )
            if not db.initialized:
                active_logger.error("MySQL 데이터베이스 연결 실패")
                return None
            active_logger.info(f"MySQL 데이터베이스 생성: {db_config.get('host')}/{db_config.get('database')}")
            return db
        
        else:
            active_logger.error(f"지원하지 않는 데이터베이스 타입: {db_type}")
            return None
    
    except Exception as e:
        active_logger.error(f"데이터베이스 생성 실패: {e}")
        return None
