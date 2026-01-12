"""
백테스트 엔진 (Backtesting Engine)

과거 데이터를 사용하여 거래 전략을 시뮬레이션하고
성능을 평가하는 모듈입니다.

주요 기능:
- 과거 OHLCV 데이터 수집
- 거래 신호 재현
- 포지션 시뮬레이션 (진입/손절/수익)
- 성능 지표 계산 (수익률, 승률, Sharpe Ratio 등)
- 결과 분석 및 리포트
"""

import logging
import math
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)


class BacktestTrade:
    """개별 거래 기록"""
    
    def __init__(self, trade_id: int, entry_time: datetime, entry_price: float, 
                 side: str, amount: float, sl_price: float, tp_price: float):
        self.trade_id = trade_id
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.side = side
        self.amount = amount
        self.sl_price = sl_price
        self.tp_price = tp_price
        
        self.exit_time = None
        self.exit_price = None
        self.exit_reason = None  # 'TP', 'SL', 'TIMEOUT'
        self.pnl = None
        self.pnl_percent = None
    
    def close_position(self, exit_time: datetime, exit_price: float, exit_reason: str):
        """포지션 종료"""
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        
        if self.side == 'long':
            self.pnl = (exit_price - self.entry_price) * self.amount
            self.pnl_percent = ((exit_price - self.entry_price) / self.entry_price) * 100
        else:  # short
            self.pnl = (self.entry_price - exit_price) * self.amount
            self.pnl_percent = ((self.entry_price - exit_price) / self.entry_price) * 100
    
    def to_dict(self) -> Dict:
        """거래를 딕셔너리로 변환"""
        return {
            'trade_id': self.trade_id,
            'entry_time': self.entry_time.strftime('%Y-%m-%d %H:%M:%S'),
            'entry_price': round(self.entry_price, 2),
            'side': self.side,
            'amount': round(self.amount, 2),
            'sl_price': round(self.sl_price, 2),
            'tp_price': round(self.tp_price, 2),
            'exit_time': self.exit_time.strftime('%Y-%m-%d %H:%M:%S') if self.exit_time else None,
            'exit_price': round(self.exit_price, 2) if self.exit_price else None,
            'exit_reason': self.exit_reason,
            'pnl': round(self.pnl, 2) if self.pnl else None,
            'pnl_percent': round(self.pnl_percent, 2) if self.pnl_percent else None
        }


class Backtester:
    """백테스트 엔진"""
    
    def __init__(self, config: Dict, exchange: ccxt.Exchange):
        """
        백테스터 초기화
        
        Args:
            config: 설정 딕셔너리
            exchange: CCXT 거래소 객체
        """
        self.config = config
        self.exchange = exchange
        self.symbol = config['trading']['symbol']
        # 설정에 백테스트 타임프레임이 지정되면 사용, 없으면 기본 15m
        self.timeframe = config.get('backtest_timeframe', '15m')
        
        # 거래 설정
        self.sl_ratio = config['trading']['sl_ratio']
        self.tp_ratio = config['trading']['tp_ratio']
        self.order_amount = config['trading']['order_amount']
        
        # RSI 임계값
        self.rsi_thresholds = config['rsi_thresholds']
        
        # 백테스트 상태
        self.trades: List[BacktestTrade] = []
        self.current_position: Optional[BacktestTrade] = None
        self.starting_balance = 0.0
        self.current_balance = 0.0
        self.peak_balance = 0.0
        
        logger.info("="*60)
        logger.info("BACKTESTER INITIALIZED")
        logger.info("="*60)
        logger.info(f"Symbol        : {self.symbol}")
        logger.info(f"SL/TP Ratio   : -{self.sl_ratio}% / +{self.tp_ratio}%")
        logger.info(f"Order Amount  : {self.order_amount} USDT")
        logger.info("="*60 + "\n")
    
    def fetch_historical_data(self, days: int = 30) -> pd.DataFrame:
        """
        과거 데이터 수집
        
        Args:
            days: 수집할 일수
            
        Returns:
            pd.DataFrame: OHLCV 데이터
        """
        logger.info(f"Fetching historical data for {self.symbol} ({days} days)...")
        
        try:
            # CCXT에서 과거 데이터 수집
            since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
            
            all_candles = []
            while since < int(datetime.now().timestamp() * 1000):
                candles = self.exchange.fetch_ohlcv(
                    self.symbol, 
                    self.timeframe, 
                    since=since,
                    limit=1000
                )
                
                if not candles:
                    break
                
                all_candles.extend(candles)
                since = int(candles[-1][0]) + 1
            
            # DataFrame으로 변환
            df = pd.DataFrame(
                all_candles,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            
            # 타임스탐프를 datetime으로 변환
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            logger.info(f"✓ Loaded {len(df)} candles from {df.index[0]} to {df.index[-1]}")
            
            return df
        
        except Exception as e:
            logger.error(f"Failed to fetch historical data: {type(e).__name__}: {str(e)}")
            return pd.DataFrame()
    
    def calculate_rsi(self, data: pd.Series, period: int = 14) -> pd.Series:
        """RSI 계산"""
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_bollinger_bands(self, data: pd.Series, period: int = 20, std_dev: float = 2.0):
        """볼린저 밴드 계산"""
        sma = data.rolling(window=period).mean()
        std = data.rolling(window=period).std()
        upper_band = sma + (std_dev * std)
        lower_band = sma - (std_dev * std)
        return upper_band, sma, lower_band
    
    def run_backtest(self, df: pd.DataFrame, max_position_hours: int = 24) -> bool:
        """
        백테스트 실행
        
        Args:
            df: OHLCV 데이터
            max_position_hours: 최대 포지션 유지 시간 (기본: 24시간 = 1일)
            
        Returns:
            bool: 성공 여부
        """
        if df.empty:
            logger.error("Cannot run backtest with empty data")
            return False
        
        # 초기 설정
        self.starting_balance = 10000.0  # 초기 자본
        self.current_balance = self.starting_balance
        self.peak_balance = self.starting_balance
        self.trades = []
        self.current_position = None
        trade_id = 1
        
        logger.info(f"Starting backtest with {self.starting_balance:.2f} USDT")
        logger.info(f"Data range: {df.index[0]} to {df.index[-1]}")
        logger.info(f"Max position holding time: {max_position_hours} hours ({max_position_hours/24:.1f} days)\n")
        
        # 기술 지표 계산 (실거래와 동일: 5개 타임프레임)
        # 1분봉 데이터로 다른 타임프레임 리샘플링
        df_1m = df.copy()
        df_5m = df.resample('5T').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        df_15m = df.resample('15T').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        df_1h = df.resample('1H').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        df_1d = df.resample('1D').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        
        # RSI 계산 (각 타임프레임)
        df_1m['rsi'] = self.calculate_rsi(df_1m['close'])
        df_5m['rsi'] = self.calculate_rsi(df_5m['close'])
        df_15m['rsi'] = self.calculate_rsi(df_15m['close'])
        df_1h['rsi'] = self.calculate_rsi(df_1h['close'])
        df_1d['rsi'] = self.calculate_rsi(df_1d['close'])
        
        # 볼린저밴드 계산 (각 타임프레임)
        for tf_df in [df_1m, df_5m, df_15m, df_1h, df_1d]:
            tf_df['bb_upper'], tf_df['bb_middle'], tf_df['bb_lower'] = self.calculate_bollinger_bands(tf_df['close'])
        
        # RSI 임계값 로드
        rsi_oversold_1m = self.rsi_thresholds['long']['1m']
        rsi_oversold_5m = self.rsi_thresholds['long']['5m']
        rsi_oversold_15m = self.rsi_thresholds['long']['15m']
        rsi_neutral_1h = self.rsi_thresholds['long']['1h']
        rsi_neutral_1d = self.rsi_thresholds['long']['1d']
        
        rsi_overbought_1m = self.rsi_thresholds['short']['1m']
        rsi_overbought_5m = self.rsi_thresholds['short']['5m']
        rsi_overbought_15m = self.rsi_thresholds['short']['15m']
        rsi_overbought_1h = self.rsi_thresholds['short']['1h']
        rsi_overbought_1d = self.rsi_thresholds['short']['1d']

        # 각 캔들에 대해 시뮬레이션 (현재 타임프레임 기준)
        base_df = df_5m if self.timeframe == '5m' else df_15m if self.timeframe == '15m' else df_1m
        for idx in range(1, len(base_df)):
            current_row = base_df.iloc[idx]
            current_time = current_row.name
            current_price = current_row['close']
            
            # 각 타임프레임의 현재 시점 데이터 가져오기
            rsi_1m = df_1m.loc[:current_time, 'rsi'].iloc[-1] if current_time in df_1m.index or any(df_1m.index <= current_time) else None
            rsi_5m = df_5m.loc[:current_time, 'rsi'].iloc[-1] if current_time in df_5m.index or any(df_5m.index <= current_time) else None
            rsi_15m = df_15m.loc[:current_time, 'rsi'].iloc[-1] if current_time in df_15m.index or any(df_15m.index <= current_time) else None
            rsi_1h = df_1h.loc[:current_time, 'rsi'].iloc[-1] if current_time in df_1h.index or any(df_1h.index <= current_time) else None
            rsi_1d = df_1d.loc[:current_time, 'rsi'].iloc[-1] if current_time in df_1d.index or any(df_1d.index <= current_time) else None
            
            # 볼린저밴드 위치 체크
            bb_1m_lower = df_1m.loc[:current_time, 'bb_lower'].iloc[-1] if any(df_1m.index <= current_time) else None
            bb_1m_upper = df_1m.loc[:current_time, 'bb_upper'].iloc[-1] if any(df_1m.index <= current_time) else None
            bb_5m_lower = df_5m.loc[:current_time, 'bb_lower'].iloc[-1] if any(df_5m.index <= current_time) else None
            bb_5m_upper = df_5m.loc[:current_time, 'bb_upper'].iloc[-1] if any(df_5m.index <= current_time) else None
            
            midpoint_15m = df_15m.loc[:current_time, 'bb_middle'].iloc[-1] if any(df_15m.index <= current_time) else None
            midpoint_1h = df_1h.loc[:current_time, 'bb_middle'].iloc[-1] if any(df_1h.index <= current_time) else None
            midpoint_1d = df_1d.loc[:current_time, 'bb_middle'].iloc[-1] if any(df_1d.index <= current_time) else None
            
            # 기존 포지션 모니터링
            if self.current_position:
                # TP 확인
                if self.current_position.side == 'long' and current_price >= self.current_position.tp_price:
                    self._close_trade(trade_id, current_time, self.current_position.tp_price, 'TP')
                elif self.current_position.side == 'short' and current_price <= self.current_position.tp_price:
                    self._close_trade(trade_id, current_time, self.current_position.tp_price, 'TP')
                
                # SL 확인
                elif self.current_position.side == 'long' and current_price <= self.current_position.sl_price:
                    self._close_trade(trade_id, current_time, self.current_position.sl_price, 'SL')
                elif self.current_position.side == 'short' and current_price >= self.current_position.sl_price:
                    self._close_trade(trade_id, current_time, self.current_position.sl_price, 'SL')
                
                # 동적 종료: RSI 기반 조기 종료
                
                # 타임아웃 확인 (max_position_hours 초과)
                if self.current_position and (current_time - self.current_position.entry_time).total_seconds() > max_position_hours * 3600:
                    self._close_trade(trade_id, current_time, current_price, 'TIMEOUT')
            
            # 신규 포지션 진입 (포지션이 없을 때) - 실거래와 동일한 조건
            if not self.current_position:
                # LONG 진입 조건 (실거래와 동일: 5개 타임프레임 모두 만족)
                cond_1m = (rsi_1m is not None and rsi_1m <= rsi_oversold_1m) or (bb_1m_lower and current_price < bb_1m_lower)
                cond_5m = ((rsi_5m is not None and rsi_5m <= rsi_oversold_5m and bb_5m_lower and current_price < bb_5m_lower)
                           or (cond_1m and rsi_5m is not None and rsi_5m <= rsi_oversold_1m and rsi_5m <= rsi_1m))
                cond_15m = (rsi_15m is not None and rsi_15m <= rsi_oversold_15m
                            and midpoint_15m is not None and current_price < midpoint_15m)
                cond_1h = (rsi_1h is not None and rsi_1h <= rsi_neutral_1h
                           and midpoint_1h is not None and current_price < midpoint_1h)
                cond_1d = (rsi_1d is not None and rsi_1d >= rsi_neutral_1d
                           and midpoint_1d is not None and current_price < midpoint_1d)
                
                if cond_1m and cond_5m and cond_15m and cond_1h and cond_1d:
                    sl_price = current_price * (1 - self.sl_ratio / 100)
                    tp_price = current_price * (1 + self.tp_ratio / 100)
                    self._open_trade(trade_id, current_time, current_price, 'long', sl_price, tp_price)
                    trade_id += 1
                
                # SHORT 진입 조건 (실거래와 동일: 5개 타임프레임 모두 만족)
                else:
                    scond_1m = (rsi_1m is not None and rsi_1m >= rsi_overbought_1m) or (bb_1m_upper and current_price > bb_1m_upper)
                    scond_5m = (rsi_5m is not None and rsi_5m >= rsi_overbought_5m and bb_5m_upper and current_price > bb_5m_upper)
                    scond_15m = (rsi_15m is not None and rsi_15m >= rsi_overbought_15m
                                 and midpoint_15m is not None and current_price > midpoint_15m)
                    scond_1h = (rsi_1h is not None and rsi_1h >= rsi_overbought_1h
                                and midpoint_1h is not None and current_price > midpoint_1h)
                    scond_1d = (rsi_1d is not None and rsi_1d <= rsi_overbought_1d
                                and midpoint_1d is not None and current_price > midpoint_1d)
                    
                    if scond_1m and scond_5m and scond_15m and scond_1h and scond_1d:
                        sl_price = current_price * (1 + self.sl_ratio / 100)
                        tp_price = current_price * (1 - self.tp_ratio / 100)
                        self._open_trade(trade_id, current_time, current_price, 'short', sl_price, tp_price)
                        trade_id += 1
        
        # 남은 포지션 종료
        if self.current_position:
            last_price = base_df.iloc[-1]['close']
            last_time = base_df.index[-1]
            self._close_trade(trade_id, last_time, last_price, 'END')
        
        logger.info(f"\n✓ Backtest completed: {len(self.trades)} trades\n")
        return True
    
    def _open_trade(self, trade_id: int, entry_time: datetime, entry_price: float, 
                   side: str, sl_price: float, tp_price: float):
        """거래 진입"""
        # 수량 계산: USDT 금액 / 진입가
        amount = self.order_amount / entry_price
        
        self.current_position = BacktestTrade(
            trade_id=trade_id,
            entry_time=entry_time,
            entry_price=entry_price,
            side=side,
            amount=amount,  # USDT 금액이 아닌 실제 수량
            sl_price=sl_price,
            tp_price=tp_price
        )
        logger.debug(f"[{entry_time}] {side.upper()} ENTRY @ {entry_price:.2f} (Amount: {amount:.4f}, SL: {sl_price:.2f}, TP: {tp_price:.2f})")
    
    def _close_trade(self, trade_id: int, exit_time: datetime, exit_price: float, exit_reason: str):
        """거래 종료"""
        if self.current_position:
            self.current_position.close_position(exit_time, exit_price, exit_reason)
            self.trades.append(self.current_position)
            
            # 잔고 업데이트
            self.current_balance += self.current_position.pnl
            self.peak_balance = max(self.peak_balance, self.current_balance)
            
            logger.debug(f"[{exit_time}] {exit_reason:7s} @ {exit_price:.2f} | PnL: {self.current_position.pnl:+.2f} USDT")
            
            self.current_position = None
    
    def get_performance_metrics(self) -> Dict:
        """성능 지표 계산"""
        if not self.trades:
            logger.warning("No trades to analyze")
            return {}
        
        # 기본 통계
        total_return = self.current_balance - self.starting_balance
        total_return_percent = (total_return / self.starting_balance) * 100
        
        # 승패
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl < 0]
        
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (win_count / len(self.trades) * 100) if self.trades else 0
        
        # PnL 통계
        pnl_list = [t.pnl for t in self.trades]
        pnl_percent_list = [t.pnl_percent for t in self.trades]
        
        avg_pnl = statistics.mean(pnl_list) if pnl_list else 0
        avg_win = statistics.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = statistics.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        max_win = max([t.pnl for t in winning_trades]) if winning_trades else 0
        max_loss = min([t.pnl for t in losing_trades]) if losing_trades else 0
        
        # 손익비 (Profit Factor)
        total_wins = sum([t.pnl for t in winning_trades])
        total_losses = abs(sum([t.pnl for t in losing_trades]))
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # 최대 인출 (Max Drawdown)
        cumulative_pnl = 0.0
        peak = 0.0
        max_drawdown = 0.0
        
        for trade in self.trades:
            cumulative_pnl += trade.pnl
            peak = max(peak, cumulative_pnl)
            drawdown = peak - cumulative_pnl
            max_drawdown = max(max_drawdown, drawdown)
        
        max_drawdown_percent = (max_drawdown / (self.starting_balance + peak)) * 100 if (self.starting_balance + peak) > 0 else 0
        
        # Sharpe Ratio (간단한 계산)
        if pnl_percent_list and len(pnl_percent_list) > 1:
            std_dev = statistics.stdev(pnl_percent_list)
            mean_return = statistics.mean(pnl_percent_list)
            sharpe_ratio = (mean_return / std_dev * math.sqrt(252)) if std_dev > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Exit reasons 분석
        exit_reasons = {}
        for trade in self.trades:
            reason = trade.exit_reason
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        
        return {
            'total_trades': len(self.trades),
            'winning_trades': win_count,
            'losing_trades': loss_count,
            'win_rate': win_rate,
            'total_return_usdt': total_return,
            'total_return_percent': total_return_percent,
            'avg_pnl': avg_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_win': max_win,
            'max_loss': max_loss,
            'profit_factor': profit_factor,
            'max_drawdown_usdt': max_drawdown,
            'max_drawdown_percent': max_drawdown_percent,
            'sharpe_ratio': sharpe_ratio,
            'starting_balance': self.starting_balance,
            'ending_balance': self.current_balance,
            'peak_balance': self.peak_balance,
            'exit_reasons': exit_reasons
        }
    
    def print_report(self):
        """백테스트 결과 리포트 출력"""
        metrics = self.get_performance_metrics()
        
        if not metrics:
            return
        
        from color_utils import Colors
        
        # 헤더
        print("\n" + "="*70)
        print("BACKTEST REPORT")
        print("="*70)
        
        # 기본 통계
        print(f"\n{'Symbol':<30}: {self.symbol}")
        print(f"{'Data Period':<30}: {self.symbol}")
        print(f"{'Timeframe':<30}: {self.timeframe}")
        print(f"{'Starting Balance':<30}: {metrics['starting_balance']:,.2f} USDT")
        print(f"{'Ending Balance':<30}: {metrics['ending_balance']:,.2f} USDT")
        print(f"{'Peak Balance':<30}: {metrics['peak_balance']:,.2f} USDT")
        
        # 수익/손실
        return_color = Colors.GREEN if metrics['total_return_usdt'] >= 0 else Colors.RED
        print(f"\n{'Total Return':<30}: {return_color}{metrics['total_return_usdt']:+,.2f} USDT ({metrics['total_return_percent']:+.2f}%){Colors.RESET}")
        
        # 거래 통계
        print(f"\n{'Total Trades':<30}: {metrics['total_trades']}")
        print(f"{'Winning Trades':<30}: {metrics['winning_trades']} ({metrics['win_rate']:.1f}%)")
        print(f"{'Losing Trades':<30}: {metrics['losing_trades']} ({100-metrics['win_rate']:.1f}%)")
        
        # PnL 분석
        win_color = Colors.GREEN if metrics['avg_win'] >= 0 else Colors.RED
        loss_color = Colors.RED if metrics['avg_loss'] <= 0 else Colors.GREEN
        
        print(f"\n{'Average PnL':<30}: {metrics['avg_pnl']:+,.2f} USDT")
        print(f"{'Average Win':<30}: {win_color}{metrics['avg_win']:+,.2f} USDT{Colors.RESET}")
        print(f"{'Average Loss':<30}: {loss_color}{metrics['avg_loss']:+,.2f} USDT{Colors.RESET}")
        print(f"{'Max Win':<30}: {Colors.GREEN}{metrics['max_win']:+,.2f} USDT{Colors.RESET}")
        print(f"{'Max Loss':<30}: {Colors.RED}{metrics['max_loss']:+,.2f} USDT{Colors.RESET}")
        
        # 위험 지표
        dd_color = Colors.GREEN if metrics['max_drawdown_percent'] < 10 else Colors.YELLOW if metrics['max_drawdown_percent'] < 20 else Colors.RED
        print(f"\n{'Max Drawdown':<30}: {dd_color}{metrics['max_drawdown_percent']:.2f}% ({metrics['max_drawdown_usdt']:,.2f} USDT){Colors.RESET}")
        print(f"{'Profit Factor':<30}: {metrics['profit_factor']:.2f}")
        print(f"{'Sharpe Ratio':<30}: {metrics['sharpe_ratio']:.2f}")
        
        # Exit Reasons
        print(f"\n{'Exit Reasons':<30}:")
        for reason, count in metrics['exit_reasons'].items():
            percentage = (count / metrics['total_trades'] * 100)
            print(f"  {reason:<28}: {count:3d} ({percentage:5.1f}%)")
        
        print("\n" + "="*70 + "\n")
    
    def export_trades_to_csv(self, filepath: str = "backtest_trades.csv"):
        """거래 결과를 CSV로 내보내기"""
        if not self.trades:
            logger.warning("No trades to export")
            return
        
        try:
            trade_dicts = [t.to_dict() for t in self.trades]
            df = pd.DataFrame(trade_dicts)
            df.to_csv(filepath, index=False)
            logger.info(f"✓ Exported {len(self.trades)} trades to {filepath}")
        except Exception as e:
            logger.error(f"Failed to export trades: {type(e).__name__}: {str(e)}")
