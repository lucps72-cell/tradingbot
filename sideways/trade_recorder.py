"""
거래 레코더 모듈
거래 정보를 데이터베이스에 기록
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sideways.database import TradeDatabase, create_database
from sideways.common import send_telegram

active_logger = logging.getLogger(__name__)

class TradeRecorder:
    """거래 기록 관리 클래스"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 설정 딕셔너리
        """
        self.config = config
        self.db: Optional[TradeDatabase] = None
        self.db_enabled = config.get('database', {}).get('save_trades', True)
        
        if self.db_enabled:
            try:
                self.db = create_database(config)
            except Exception as e:
                active_logger.error(f"거래 레코더 초기화: 데이터베이스 연결 중 오류 발생: {e}")
                send_telegram(f"⚠️ [DB 연결 오류] 거래 데이터베이스 연결 중 예외 발생: {e}\n(거래 기록은 저장되지 않습니다)")
                self.db = None
                return

            if self.db:
                active_logger.info("거래 레코더 초기화 완료 (DB 저장 활성화)")
            else:
                active_logger.warning("거래 레코더 초기화: 데이터베이스 연결 실패 (로그 파일에만 기록됨)")
                send_telegram("⚠️ [DB 연결 실패] 거래 데이터베이스 연결에 실패했습니다.\n(거래 기록은 저장되지 않고 로그 파일에만 남습니다)")
        else:
            active_logger.info("거래 레코더 초기화 완료 (DB 저장 비활성화)")


    def record_entry(self, 
                     symbol: str,
                     side: str,
                     entry_price: float,
                     quantity: float,
                     entry_usdt: float,
                     tp_price: Optional[float] = None,
                     sl_price: Optional[float] = None,
                     signal_reason: str = "",
                     leverage: int = 1,
                     entry_split_count: int = 1,
                     is_simulated: bool = False) -> bool:
        """
        거래 진입 기록

        Args:
            symbol: 거래 심볼
            side: 포지션 방향 (long/short)
            entry_price: 진입가
            quantity: 거래량
            entry_usdt: 진입 금액 (USDT)
            tp_price: 익절가
            sl_price: 손절가
            signal_reason: 신호 이유
            leverage: 레버리지
            entry_split_count: 진입 분할 횟수
            is_simulated: read_only_mode(시뮬레이션)로 생성된 기록이면 True.
                호출부(simple_strategy.py)에서 config['trading']['read_only_mode']를 그대로 전달.

        Returns:
            저장 성공 여부
        """
        if not self.db_enabled or not self.db:
            return False

        try:
            trade_data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'symbol': symbol,
                'side': side,
                'entry_price': entry_price,
                'quantity': quantity,
                'entry_usdt': entry_usdt,
                'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'tp_price': tp_price,
                'sl_price': sl_price,
                'status': 'open',
                'signal_reason': signal_reason,
                'order_type': 'market',
                'leverage': leverage,
                'entry_split_count': entry_split_count,
                'is_simulated': bool(is_simulated),
            }
            
            return self.db.save_trade(trade_data)
        except Exception as e:
            active_logger.error(f"거래 진입 기록 실패: {e}")
            return False
    
    def record_exit(self,
                    symbol: str,
                    side: str,
                    exit_price: float,
                    quantity: float,
                    entry_price: float,
                    entry_usdt: float,
                    pnl: Optional[float] = None,
                    pnl_pct: Optional[float] = None,
                    exit_reason: str = "") -> bool:
        """
        거래 청산 기록
        
        Args:
            symbol: 거래 심볼
            side: 포지션 방향 (long/short)
            exit_price: 청산가
            quantity: 거래량
            entry_price: 진입가
            entry_usdt: 진입 금액 (USDT)
            pnl: 손익 (USDT)
            pnl_pct: 손익률 (%)
            exit_reason: 청산 이유
            
        Returns:
            저장 성공 여부
        """
        if not self.db_enabled or not self.db:
            return False
        
        try:
            # PnL 계산 (미제공 시)
            if pnl is None:
                if side == 'long':
                    pnl = (exit_price - entry_price) * quantity
                else:  # short
                    pnl = (entry_price - exit_price) * quantity
            
            if pnl_pct is None:
                pnl_pct = (pnl / entry_usdt * 100) if entry_usdt > 0 else 0
            
            trade_data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'symbol': symbol,
                'side': side,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'quantity': quantity,
                'entry_usdt': entry_usdt,
                'exit_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'status': 'closed',
                'signal_reason': exit_reason,
            }
            
            return self.db.close_trade(symbol, side, trade_data)
        except Exception as e:
            active_logger.error(f"거래 청산 기록 실패: {e}")
            return False
    
    def record_transaction(self, trade_data: Dict[str, Any]) -> bool:
        """
        일반적인 거래 기록 저장
        
        Args:
            trade_data: 거래 데이터 딕셔너리
                - symbol: 거래 심볼
                - side: 포지션 방향 (long/short)
                - entry_price: 진입가
                - exit_price: 청산가 (선택)
                - quantity: 거래량
                - entry_usdt: 진입 금액
                - status: 거래 상태 (open/closed)
                - signal_reason: 신호 이유
                - 기타 필드들...
                
        Returns:
            저장 성공 여부
        """
        if not self.db_enabled or not self.db:
            return False
        
        try:
            return self.db.save_trade(trade_data)
        except Exception as e:
            active_logger.error(f"거래 기록 저장 실패: {e}")
            return False
    
    def get_trades(self, symbol: Optional[str] = None, limit: int = 100):
        """거래 기록 조회"""
        if not self.db:
            return []
        return self.db.get_trades(symbol, limit)
    
    def get_statistics(self, symbol: Optional[str] = None):
        """거래 통계 조회"""
        if not self.db:
            return {}
        return self.db.get_trade_statistics(symbol)
    
    def close(self):
        """데이터베이스 연결 종료"""
        if self.db:
            self.db.close()
