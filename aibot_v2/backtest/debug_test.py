"""
Debug Backtest - 간단한 버전으로 신호 생성 테스트
"""

import pandas as pd
import logging
from datetime import datetime, timedelta
import ccxt
from technical_indicators import calculate_all_indicators
from trend_strategy import TrendFollowingStrategy
from config_loader import load_config


def test_signal_generation():
    """신호 생성 테스트"""
    
    # 설정 로드
    config = load_config('config.json')
    
    # 로거 설정
    logger = logging.getLogger('test')
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    logger.addHandler(handler)
    
    strategy = TrendFollowingStrategy(config)
    
    # 데이터 수집
    print("[*] Fetching XRPUSDT 1m data...")
    exchange = ccxt.bybit()
    ohlcv = exchange.fetch_ohlcv('XRPUSDT', '1m', limit=1000)
    df = pd.DataFrame(
        ohlcv,
        columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df.set_index('timestamp')
    
    print(f"[+] Collected {len(df)} bars ({df.index[0]} ~ {df.index[-1]})")
    
    # 리샘플
    print("[*] Resampling data...")
    
    # timeframe 변환 함수
    def resample_with_conversion(df, timeframe):
        if timeframe.endswith('m'):
            minutes = timeframe[:-1]
            tf_str = f"{minutes}min"
        else:
            tf_str = timeframe
        
        return df.resample(tf_str).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
    
    df_1h = resample_with_conversion(df, '1h')
    df_4h = resample_with_conversion(df, '4h')
    df_15m = resample_with_conversion(df, '15m')
    df_5m = resample_with_conversion(df, '5m')
    
    print(f"[+] Resampled to: 1h ({len(df_1h)}), 4h ({len(df_4h)}), 15m ({len(df_15m)}), 5m ({len(df_5m)})")
    
    # 지표 계산
    print("[*] Calculating indicators...")
    
    # 최소 데이터 길이 체크
    if len(df_1h) >= 15:
        ind_1h = calculate_all_indicators(df_1h, config)
        print("[*] Analyzing latest bar...")
        
        # 상위 시간봉 (1h) 분석
        higher_analysis_1h = strategy.analyze_higher_timeframe(df_1h, ind_1h)
        print(f"\n[1h] Trend: {higher_analysis_1h['trend']} (confidence: {higher_analysis_1h['confidence']:.2f})")
        
        if 'rsi' in higher_analysis_1h:
            print(f"      RSI: {higher_analysis_1h['rsi']:.2f}, Price: {higher_analysis_1h['price']:.6f}")
            print(f"      EMA Fast: {higher_analysis_1h['ema_fast']:.6f}")
            print(f"      Structure Trend: {higher_analysis_1h['trend_structure']}")
        else:
            print(f"      주의: RSI 미계산 (데이터 부족)")
            print(f"      이유: {higher_analysis_1h.get('reason', '알 수 없음')}")
        
        # 하위 시간봉 (15m) 신호
        if len(df_15m) >= 20:
            ind_15m = calculate_all_indicators(df_15m, config)
            signal_15m = strategy.check_entry_signal(df_15m, ind_15m, higher_analysis_1h['trend'])
            print(f"\n[15m] Signal conditions: {signal_15m['signal_conditions']}")
            print(f"      Active signals: {signal_15m['active_signals']}")
            print(f"      Has signal: {signal_15m['has_signal']}")
        else:
            print(f"\n[15m] Insufficient data ({len(df_15m)} bars)")
    else:
        print("[ERROR] Insufficient 1h data for analysis")
        print(f"        Available: {len(df_1h)} bars, Required: 20 bars")
    
    print("\n[*] Test completed")


if __name__ == '__main__':
    test_signal_generation()
