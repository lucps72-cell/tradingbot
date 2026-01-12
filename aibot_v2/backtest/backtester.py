"""
Backtester for Multi-Timeframe Trend Following Strategy
다중 시간봉 추세 추종 전략 백테스트 모듈
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple
import ccxt

from aibot_v2.technical_indicators import calculate_all_indicators
from aibot_v2.trend_strategy import TrendFollowingStrategy
from aibot_v2 import config_loader


class BacktestEngine:
    """백테스트 엔진 클래스"""
    
    def __init__(self, config: Dict, logger: logging.Logger):
        """
        Args:
            config: 설정 딕셔너리
            logger: 로거 객체
        """
        self.config = config
        self.logger = logger
        self.strategy = TrendFollowingStrategy(config)
        
        # 백테스트 통계
        self.trades = []
        self.positions = {
            'LONG': [],
            'SHORT': []
        }
        self.balance_history = []
        self.equity_history = []
        self.initial_balance = config['backtest']['initial_balance']
        self.current_balance = self.initial_balance
        self.commission_rate = config['backtest']['commission_rate']
        # TP 모드: 'fixed', 'trend_change', 'hybrid'
        self.tp_mode = (
            config.get('risk_management', {}).get('take_profit_mode', 'fixed')
        )
        # 수수료/슬리피지 (백테스트 설정에서 읽음)
        self.fee_ratio = config.get('backtest', {}).get('fee_ratio', 0.0)
        self.slippage = config.get('backtest', {}).get('slippage', 0.0)
        # 최대 포지션 유지 바 수
        self.max_bars = config.get('backtest', {}).get('max_bars', 500)
    
    def fetch_historical_data(self, symbol: str, timeframe: str, days: int) -> Optional[pd.DataFrame]:
        """
        역사 데이터 수집
        
        Args:
            symbol: 거래 심볼
            timeframe: 시간봉
            days: 기간 (일)
            
        Returns:
            OHLCV 데이터프레임
        """
        try:
            # Bybit 거래소 인스턴스 (공개 정보만 사용)
            exchange = ccxt.bybit()
            
            limit = int((days * 24 * 60) / self._timeframe_to_minutes(timeframe)) + 100
            limit = min(limit, 1000)  # CCXT 제한
            
            self.logger.info(f"역사 데이터 수집: {symbol} {timeframe} (최근 {days}일, {limit}개 캔들)")
            
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.set_index('timestamp')
            
            # 기간 필터링
            cutoff_date = datetime.now() - timedelta(days=days)
            df = df[df.index >= cutoff_date]
            
            self.logger.info(f"수집 완료: {len(df)}개 캔들 ({df.index[0]} ~ {df.index[-1]})")
            
            return df
        
        except Exception as e:
            self.logger.error(f"역사 데이터 수집 실패: {str(e)}")
            return None
    
    def resample_data(self, df: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
        """
        데이터프레임 리샘플
        
        Args:
            df: 기본 시간봉 데이터
            target_timeframe: 목표 시간봉
            
        Returns:
            리샘플된 데이터프레임
        """
        try:
            # timeframe 변환 ('m' -> 'min')
            if target_timeframe.endswith('m'):
                minutes = target_timeframe[:-1]
                resampled_tf = f"{minutes}min"
            else:
                resampled_tf = target_timeframe
            
            resampled = df.resample(resampled_tf).agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            # 시간 순서대로 정렬 (오래된 것부터 최신 순)
            resampled = resampled.sort_index(ascending=True)
            
            return resampled
        except Exception as e:
            self.logger.error(f"데이터 리샘플 실패: {str(e)}")
            return df
    
    def check_entry_conditions(self, higher_dfs: Dict, lower_dfs: Dict, 
                               base_df: pd.DataFrame, bar_idx: int) -> Optional[Dict]:
        """
        진입 조건 확인
        
        Args:
            higher_dfs: 상위 시간봉 데이터 딕셔너리
            lower_dfs: 하위 시간봉 데이터 딕셔너리
            base_df: 기본 시간봉 데이터
            bar_idx: 현재 바 인덱스
            
        Returns:
            진입 신호 또는 None
        """
        try:
            # 상위 시간봉 분석
            higher_trend = None
            
            for tf, df in higher_dfs.items():
                # 현재 인덱스에 맞는 데이터 추출
                # 1분봉 바 인덱스를 상위 시간봉으로 맞춰야 함
                higher_idx = bar_idx // (self._timeframe_to_minutes(tf) // self._timeframe_to_minutes('1m'))
                
                if higher_idx >= len(df) or higher_idx < 50:
                    continue
                
                higher_df_slice = df.iloc[:higher_idx+1]
                if len(higher_df_slice) < 20:
                    continue
                
                indicators = calculate_all_indicators(higher_df_slice, self.config)
                analysis = self.strategy.analyze_higher_timeframe(higher_df_slice, indicators)
                
                if analysis['trend'] != 'neutral':
                    higher_trend = analysis['trend']
                    break
            
            if higher_trend is None:
                return None
            
            # 하위 시간봉 신호 확인
            for tf, df in lower_dfs.items():
                lower_idx = bar_idx // (self._timeframe_to_minutes(tf) // self._timeframe_to_minutes('1m'))
                
                if lower_idx >= len(df) or lower_idx < 20:
                    continue
                
                lower_df_slice = df.iloc[:lower_idx+1]
                
                indicators = calculate_all_indicators(lower_df_slice, self.config)
                signal = self.strategy.check_entry_signal(lower_df_slice, indicators, higher_trend)
                
                if signal.get('has_signal'):
                    # 진입 신호 생성
                    base_df_slice = base_df.iloc[:bar_idx+1]
                    
                    if higher_trend == 'uptrend':
                        entry_order = self.strategy.generate_long_entry(lower_df_slice, indicators, base_df_slice)
                        if entry_order:
                            return entry_order
                    else:
                        entry_order = self.strategy.generate_short_entry(lower_df_slice, indicators, base_df_slice)
                        if entry_order:
                            return entry_order
            
            return None
        
        except Exception as e:
            self.logger.debug(f"진입 조건 확인 중 오류: {str(e)}")
            return None
    
    def simulate_trade(self, symbol: str, entry_signal: Dict, base_df: pd.DataFrame,
                       start_idx: int, higher_dfs: Optional[Dict] = None,
                       max_bars: int = 1440) -> Optional[Dict]:
        """
        거래 시뮬레이션
        
        Args:
            symbol: 거래 심볼
            entry_signal: 진입 신호
            base_df: 기본 시간봉 데이터
            start_idx: 시작 인덱스
            max_bars: 최대 포지션 유지 바 수
            
        Returns:
            거래 결과 또는 None
        """
        try:
            entry_price = entry_signal['entry_price']
            sl_price = entry_signal['sl_price']
            tp_price = entry_signal['tp_price']
            position_type = entry_signal['type']
            
            # 거래 실행 타임스탬프
            entry_time = base_df.index[start_idx]
            
            # 상위TF 추세 평가 최적화: 상위TF 경계가 바뀔 때만 재계산
            last_idx_by_tf: Dict[str, int] = {}
            
            # 포지션 유지 기간 동안 SL/TP 확인
            for i in range(start_idx + 1, min(start_idx + max_bars, len(base_df))):
                candle = base_df.iloc[i]
                # 디버깅: SL/TP 가격과 캔들 high/low 기록
                self.logger.debug(
                    f"{position_type} | idx:{i} | entry:{entry_price} | sl:{sl_price} | tp:{tp_price} | "
                    f"candle_low:{candle['low']} | candle_high:{candle['high']} | time:{base_df.index[i]}"
                )
                
                # SL 체크
                if position_type == 'LONG':
                    if candle['low'] <= sl_price:
                        return self._close_trade(position_type, entry_price, sl_price, 
                                                entry_time, base_df.index[i], 'stop_loss')
                    # TP 체크 (fixed, hybrid 모드에서)
                    if self.tp_mode in ['fixed', 'hybrid'] and candle['high'] >= tp_price:
                        return self._close_trade(position_type, entry_price, tp_price,
                                                entry_time, base_df.index[i], 'take_profit')
                else:  # SHORT
                    if candle['high'] >= sl_price:
                        return self._close_trade(position_type, entry_price, sl_price, 
                                                entry_time, base_df.index[i], 'stop_loss')
                    # TP 체크 (fixed, hybrid 모드에서)
                    if self.tp_mode in ['fixed', 'hybrid'] and candle['low'] <= tp_price:
                        return self._close_trade(position_type, entry_price, tp_price,
                                                entry_time, base_df.index[i], 'take_profit')
                
                # 추세 변경 시 청산 (trend_change, hybrid 모드)
                if self.tp_mode in ['trend_change', 'hybrid'] and higher_dfs is not None:
                    try:
                        current_trend = None
                        # 상위 시간봉들 중 첫 번째로 비중립 추세를 사용하는 기존 로직과 동일하게 처리
                        for tf, hdf in higher_dfs.items():
                            # 1분 기준 인덱스를 상위 시간봉 인덱스로 변환
                            factor = self._timeframe_to_minutes(tf) // self._timeframe_to_minutes('1m')
                            if factor <= 0:
                                continue
                            higher_idx = i // factor
                            if higher_idx >= len(hdf) or higher_idx < 50:
                                continue
                            if last_idx_by_tf.get(tf) != higher_idx:
                                last_idx_by_tf[tf] = higher_idx
                                hslice = hdf.iloc[:higher_idx+1]
                                if len(hslice) < 20:
                                    continue
                                hind = calculate_all_indicators(hslice, self.config)
                                hanalysis = self.strategy.analyze_higher_timeframe(hslice, hind)
                                if hanalysis['trend'] != 'neutral':
                                    current_trend = hanalysis['trend']
                                    break
                        if current_trend is not None:
                            if position_type == 'LONG' and current_trend == 'downtrend':
                                return self._close_trade(position_type, entry_price, candle['close'],
                                                         entry_time, base_df.index[i], 'trend_change')
                            if position_type == 'SHORT' and current_trend == 'uptrend':
                                return self._close_trade(position_type, entry_price, candle['close'],
                                                         entry_time, base_df.index[i], 'trend_change')
                    except Exception as _:
                        # 추세 평가 실패 시에는 그냥 진행
                        pass
            
            # 최대 바 초과 (강제 종료)
            timeout_index = min(start_idx + max_bars - 1, len(base_df) - 1)
            close_price = base_df.iloc[timeout_index]['close']
            return self._close_trade(position_type, entry_price, close_price,
                                    entry_time, base_df.index[timeout_index], 'timeout')
        
        except Exception as e:
            self.logger.error(f"거래 시뮬레이션 실패: {str(e)}")
            return None
    
    def _close_trade(self, position_type: str, entry_price: float, exit_price: float,
                     entry_time, exit_time, exit_reason: str) -> Dict:
        """
        거래 종료 및 결과 계산
        """
        # Slippage 적용 (진입: 불리, 청산: 불리)
        actual_entry = entry_price * (1 + self.slippage if position_type == 'LONG' else 1 - self.slippage)
        actual_exit = exit_price * (1 - self.slippage if position_type == 'LONG' else 1 + self.slippage)
        
        if position_type == 'LONG':
            pnl_ratio = (actual_exit - actual_entry) / actual_entry
        else:  # SHORT
            pnl_ratio = (actual_entry - actual_exit) / actual_entry
        
        # 수수료 적용: 진입과 청산 모두 차감
        total_fee = self.fee_ratio * 2  # 진입 + 청산
        pnl_ratio -= total_fee
        
        # 포지션 크기 계산
        position_size = self.config['trading']['order_amount_usdt']
        pnl_usdt = position_size * pnl_ratio
        
        # 잔액 업데이트
        self.current_balance += pnl_usdt
        
        trade_result = {
            'type': position_type,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl_ratio': pnl_ratio,
            'pnl_usdt': pnl_usdt,
            'balance_after': self.current_balance,
            'duration': exit_time - entry_time
        }
        
        self.trades.append(trade_result)
        return trade_result
    
    def run_backtest(self, symbol: str, days: int) -> Dict:
        """
        백테스트 실행
        
        Args:
            symbol: 거래 심볼
            days: 백테스트 기간 (일)
            
        Returns:
            백테스트 결과
        """
        self.logger.info("=" * 60)
        self.logger.info(f"백테스트 시작: {symbol} ({days}일)")
        self.logger.info("=" * 60)
        
        # 데이터 수집
        base_df = self.fetch_historical_data(symbol, '1m', days)
        if base_df is None or len(base_df) == 0:
              raise ValueError('Failed to fetch historical data')
        
        # 상위 시간봉 데이터 준비
        higher_timeframes = self.config['strategy']['timeframes']['higher_trend']
        higher_dfs = {}
        for tf in higher_timeframes:
            higher_dfs[tf] = self.resample_data(base_df, tf)
        
        # 하위 시간봉 데이터 준비
        lower_timeframes = self.config['strategy']['timeframes']['lower_signal']
        lower_dfs = {}
        for tf in lower_timeframes:
            lower_dfs[tf] = self.resample_data(base_df, tf)
        
        # 백테스트 루프
        bar_processed = 0
        for i in range(100, len(base_df)):
            bar_processed += 1
            
            if bar_processed % 1000 == 0:
                self.logger.info(f"처리 중... {bar_processed}/{len(base_df) - 100} 바")
            
            # 진입 신호 확인
            entry_signal = self.check_entry_conditions(higher_dfs, lower_dfs, base_df, i)
            
            if entry_signal:
                # 거래 시뮬레이션
                trade_result = self.simulate_trade(symbol, entry_signal, base_df, i, higher_dfs)
                
                if trade_result:
                    self.logger.info(
                        f"거래 종료: {trade_result['type']} | "
                        f"PnL: {trade_result['pnl_ratio']*100:.2f}% | "
                        f"이유: {trade_result['exit_reason']}"
                    )
        
        # 결과 계산
        return self.calculate_statistics()
    
    def calculate_statistics(self) -> Dict:
        """백테스트 통계 계산"""
        
        if len(self.trades) == 0:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_return': 0,
                'total_pnl': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'average_trade': 0,
                'max_drawdown': 0
            }
        
        trades_df = pd.DataFrame(self.trades)
        
        winning_trades = trades_df[trades_df['pnl_usdt'] > 0]
        losing_trades = trades_df[trades_df['pnl_usdt'] <= 0]
        
        total_pnl = trades_df['pnl_usdt'].sum()
        total_return = total_pnl / self.initial_balance
        win_rate = len(winning_trades) / len(trades_df)
        
        gross_profit = winning_trades['pnl_usdt'].sum() if len(winning_trades) > 0 else 0
        gross_loss = abs(losing_trades['pnl_usdt'].sum()) if len(losing_trades) > 0 else 1e-10
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # 최대 드로우다운
        balance_series = trades_df['balance_after'].values
        running_max = np.maximum.accumulate(balance_series)
        drawdown = (balance_series - running_max) / running_max
        max_drawdown = np.min(drawdown)
        
        return {
            'total_trades': len(trades_df),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'average_trade': trades_df['pnl_usdt'].mean(),
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'largest_win': trades_df['pnl_usdt'].max(),
            'largest_loss': trades_df['pnl_usdt'].min(),
            'trades': self.trades,
            'tp_mode': self.tp_mode
        }
    
    def _timeframe_to_minutes(self, timeframe: str) -> int:
        """시간봉을 분으로 변환"""
        if timeframe.endswith('m'):
            return int(timeframe[:-1])
        elif timeframe.endswith('h'):
            return int(timeframe[:-1]) * 60
        elif timeframe.endswith('d'):
            return int(timeframe[:-1]) * 24 * 60
        else:
            return 1


def run_backtest(config: Dict, symbol: str, days: int, logger: logging.Logger) -> Dict:
    """
    백테스트 실행 함수
    
    Args:
        config: 설정 딕셔너리
        symbol: 거래 심볼
        days: 백테스트 기간
        logger: 로거 객체
        
    Returns:
        백테스트 결과
    """
    backtester = BacktestEngine(config, logger)
    return backtester.run_backtest(symbol, days)


if __name__ == '__main__':
    import argparse
    import sys
    import os
    from aibot_v2.log_config import setup_logging
    from aibot_v2.color_utils import print_success, print_info, print_warning, print_error
    
    # UTF-8 인코딩 설정 (Windows 한글 깨짐 방지)
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr.reconfigure(encoding='utf-8')
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    
    # 파라미터 파싱
    parser = argparse.ArgumentParser(description='Bybit Trading Bot v2 - Backtester')
    parser.add_argument('--config', type=str, default='config.json',
                        help='설정 파일 경로 (기본값: config.json)')
    parser.add_argument('--symbol', type=str, default='XRPUSDT',
                        help='거래 심볼 (기본값: XRPUSDT)')
    parser.add_argument('--days', type=int, default=30,
                        help='백테스트 기간 (일, 기본값: 30)')
    parser.add_argument('--amount', type=float, default=100,
                        help='주문 금액 (기본값: 100 USDT)')
    parser.add_argument('--tp-mode', type=str, choices=['fixed', 'trend_change', 'hybrid'], default='fixed',
                        help="TP mode: fixed, trend_change, or hybrid")
    parser.add_argument('--fee-ratio', type=float, default=0.0,
                        help='Fee ratio (default: 0.0)')
    parser.add_argument('--slippage', type=float, default=0.0,
                        help='Slippage ratio (default: 0.0)')
    parser.add_argument('--max-bars', type=int, default=500,
                        help='Max bars to hold position (default: 500)')
    
    args = parser.parse_args()
    
    try:
        config = config_loader.load_config(args.config)
        config['trading']['symbol'] = args.symbol
        config['trading']['order_amount_usdt'] = args.amount
        # 위험 관리 설정에 TP 모드 적용
        if 'risk_management' not in config:
            config['risk_management'] = {}
        config['risk_management']['take_profit_mode'] = args.tp_mode
        # 백테스트 설정에 수수료, 슬리피지, max-bars 적용
        if 'backtest' not in config:
            config['backtest'] = {}
        config['backtest']['fee_ratio'] = args.fee_ratio
        config['backtest']['slippage'] = args.slippage
        config['backtest']['max_bars'] = args.max_bars
    except (FileNotFoundError, KeyError) as e:
        print_error(f"설정 로드 실패: {str(e)}")
        sys.exit(1)
    
    # 로깅 설정
    logger = setup_logging(
        log_dir='logs',
        log_level=logging.INFO
    )
    
    print_success("\n" + "=" * 60)
    print_success("[BACKTEST MODE]")
    print_success("=" * 60)
    
    result = run_backtest(config, args.symbol, args.days, logger)
    
    print("\n" + "=" * 60)
    print_success("[BACKTEST RESULTS]")
    print("=" * 60)
    # 디버깅용: result 전체를 사람이 읽기 쉬운 형태로 출력
    import json
    def convert_for_json(obj):
        try:
            import numpy as np
            import pandas as pd
            if isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            if isinstance(obj, (np.ndarray,)):
                return obj.tolist()
            if isinstance(obj, (pd.Timestamp, pd.Timedelta)):
                return str(obj)
        except ImportError:
            pass
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return str(obj)

    print(json.dumps(result, default=convert_for_json, ensure_ascii=False, indent=2))
    
    # 기본 정보
    print_info(f"기간: {args.days}일")
    print_info(f"심볼: {args.symbol}")
    print_info(f"초기 자본: {config['backtest']['initial_balance']:,.0f} USDT")
    print_info(f"주문 금액: {config['trading']['order_amount_usdt']:,.0f} USDT")
    print_info(f"레버리지: {config['trading']['leverage']}x")
    
    # 시간봉 설정
    higher_tf = ', '.join(config['strategy']['timeframes']['higher_trend'])
    lower_tf = ', '.join(config['strategy']['timeframes']['lower_signal'])
    entry_tf = config['strategy']['timeframes']['entry_trigger']
    print_info(f"추세확인: {higher_tf}봉 | 신호감지: {lower_tf}봉 | 진입: {entry_tf}봉")
    
    # 손절/익절
    sl_pct = config['risk_management']['sl_ratio'] * 100
    tp_pct = config['risk_management']['tp_ratio'] * 100
    rr_ratio = config['risk_management']['risk_reward_ratio']
    tp_mode = config['risk_management'].get('take_profit_mode', 'fixed')
    fee_ratio = config['backtest'].get('fee_ratio', 0.0) * 100
    slippage = config['backtest'].get('slippage', 0.0) * 100
    max_bars = config['backtest'].get('max_bars', 500)
    
    if tp_mode == 'trend_change':
        print_info(f"손절: -{sl_pct:.1f}% | 익절: 추세변화 시 청산")
        print_info("익절 모드: trend_change")
    elif tp_mode == 'hybrid':
        print_info(f"손절: -{sl_pct:.1f}% | 익절: +{tp_pct:.1f}% 또는 추세변화 시 조기청산")
        print_info("익절 모드: hybrid (2% + 추세반전)")
    else:
        print_info(f"손절/익절: -{sl_pct:.1f}% / +{tp_pct:.1f}% (손익비 1:{rr_ratio:.1f})")
        print_info("익절 모드: fixed")
    
    if fee_ratio > 0 or slippage > 0:
        print_info(f"수수료: {fee_ratio:.3f}% | 슬리피지: {slippage:.3f}% | Max Bars: {max_bars}")
    
    print("\n" + "-" * 60)
    print_info(f"총 거래: {result.get('total_trades', 0)}")
    print_info(f"승리: {result.get('winning_trades', 0)}")
    print_info(f"패배: {result.get('losing_trades', 0)}")
    
    if result.get('total_trades', 0) > 0:
        print_info(f"승률: {result.get('win_rate', 0)*100:.2f}%")
        
        # 수익률 및 실손익 금액
        total_pnl = result.get('total_pnl', 0)
        return_pct = result.get('total_return_pct', 0)
        print_success(f"수익: {return_pct:.2f}% ({total_pnl:+.2f} USDT)")
        
        # 평균 거래 및 최대 손익
        avg_trade = result.get('average_trade', 0)
        largest_win = result.get('largest_win', 0)
        largest_loss = result.get('largest_loss', 0)
        print_info(f"평균 거래: {avg_trade:+.2f} USDT")
        print_success(f"최대 수익: {largest_win:.2f} USDT")
        print_warning(f"최대 손실: {largest_loss:.2f} USDT")
        
        print_info(f"Profit Factor: {result.get('profit_factor', 0):.2f}")
        print_warning(f"최대 드로우다운: {result.get('max_drawdown', 0)*100:.2f}%")
    
    logger.info("백테스트 완료")
    logger.info(f"결과: {result}")
    

    # --- 반드시 출력: result 요약 통계 ---
    import json
    def convert_for_json(obj):
        try:
            import numpy as np
            import pandas as pd
            if isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            if isinstance(obj, (np.ndarray,)):
                return obj.tolist()
            if isinstance(obj, (pd.Timestamp, pd.Timedelta)):
                return str(obj)
        except ImportError:
            pass
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return str(obj)


    # --- CSV 저장 및 안내 ---
    import pandas as pd
    try:
        trades = result.get('trades', [])
        if trades:
            # 판다스 DataFrame으로 변환 및 타입 변환
            df = pd.DataFrame(trades)
            for col in df.columns:
                df[col] = df[col].apply(lambda x: str(x))
            csv_path = 'backtest_trades.csv'
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')
            print(f"[CSV 저장 완료] {csv_path} (총 {len(df)}건)")
        else:
            print("[CSV 저장] 거래 내역이 없습니다.")
    except Exception as e:
        print(f"[CSV 저장 오류] {e}")

    try:
        print("\n[RESULT SUMMARY]")
        print(json.dumps(result, default=convert_for_json, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[RESULT PRINT ERROR] {e}")

    print_success("\n백테스트가 완료되었습니다.")
    sys.exit(0)

# --- 무조건 출력 보장: result 요약 통계 마지막에 한 번 더 출력 ---
import json
def convert_for_json(obj):
    try:
        import numpy as np
        import pandas as pd
        if isinstance(obj, (np.integer, np.floating)):
            return float(obj)
        if isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        if isinstance(obj, (pd.Timestamp, pd.Timedelta)):
            return str(obj)
    except ImportError:
        pass
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    return str(obj)

try:
    print("\n[RESULT SUMMARY]")
    print(json.dumps(result, default=convert_for_json, ensure_ascii=False, indent=2))
except Exception as e:
    print(f"[RESULT PRINT ERROR] {e}")
