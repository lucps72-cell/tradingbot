"""
기술적 지표 및 시장 데이터 유틸리티 모듈
볼린저 밴드, RSI, OHLCV 데이터 조회 기능 통합
"""

import ccxt
import pandas as pd
from typing import List, Dict, Any, Optional
import log_config
import logging
logger = log_config.setup_logging(
    log_dir="logs",
    log_level=logging.INFO
)


# ==================== 볼린저 밴드 (Bollinger Bands) ====================

def compute_bollinger(df: pd.DataFrame, length: int = 20, stddev: float = 2.0) -> pd.DataFrame:
    """
    볼린저 밴드 계산
    
    Args:
        df: OHLCV 데이터프레임
        length: 이동평균 기간
        stddev: 표준편차 배수
        
    Returns:
        볼린저 밴드가 추가된 데이터프레임
    """
    df = df.copy()
    df['ma'] = df['close'].rolling(window=length, min_periods=1).mean()
    df['std'] = df['close'].rolling(window=length, min_periods=1).std()
    df['upper'] = df['ma'] + stddev * df['std']
    df['lower'] = df['ma'] - stddev * df['std']
    return df


def get_bollinger_for_timeframes(symbol: str,
                                 timeframes: List[str] = None,
                                 length: int = 20,
                                 stddev: float = 2.0,
                                 limit: int = 200,
                                 exchange: ccxt.Exchange | None = None) -> Dict[str, Any]:
    """
    여러 타임프레임에 대한 볼린저 밴드 계산
    
    Args:
        symbol: 거래 심볼
        timeframes: 타임프레임 리스트 (예: ['1m', '5m', '15m'])
        length: 이동평균 기간
        stddev: 표준편차 배수
        limit: 조회할 캔들 개수
        exchange: CCXT 거래소 객체
        
    Returns:
        타임프레임별 볼린저 밴드 값 딕셔너리
    """
    if timeframes is None:
        timeframes = ['1m', '5m', '15m']

    if exchange is None:
        exchange = ccxt.bybit({'enableRateLimit': True})

    # ensure markets loaded
    try:
        exchange.load_markets()
    except Exception:
        pass

    results: Dict[str, Any] = {}
    for tf in timeframes:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = compute_bollinger(df, length=length, stddev=stddev)
        last = df.iloc[-1]
        results[tf] = {
            'ma': float(last['ma']) if pd.notna(last['ma']) else None,
            'upper': float(last['upper']) if pd.notna(last['upper']) else None,
            'lower': float(last['lower']) if pd.notna(last['lower']) else None,
            'close': float(last['close']),
            'sample': df.tail(3).to_dict(orient='records')
        }

    return results


def print_bollinger_results(results: Dict[str, Any], decimals: int = 6) -> None:
    """
    볼린저 밴드 결과 출력
    
    Args:
        results: get_bollinger_for_timeframes()의 결과
        decimals: 소수점 자릿수
    """
    fmt = f"{{tf}}: close={{close:.3f}}, ma={{ma:.3f}}, upper={{upper:.3f}}, lower={{lower:.3f}}"
    for tf, v in results.items():
        ma = v.get('ma') or 0.0
        upper = v.get('upper') or 0.0
        lower = v.get('lower') or 0.0
        close = v.get('close') or 0.0
        logger.info(fmt.format(tf=tf, close=close, ma=ma, upper=upper, lower=lower))


# ==================== RSI (Relative Strength Index) ====================

def compute_rsi(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    """
    RSI 계산 (Wilder's smoothing 방식)
    
    Args:
        df: OHLCV 데이터프레임
        length: RSI 기간
        
    Returns:
        RSI가 추가된 데이터프레임
    """
    df = df.copy()
    delta = df['close'].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder's smoothing (EWMA with alpha=1/length)
    avg_gain = gain.ewm(alpha=1/length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/length, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi_value = 100 - (100 / (1 + rs))
    df['rsi'] = rsi_value.fillna(0)
    return df


def get_rsi_for_timeframes(symbol: str,
                           timeframes: List[str] = None,
                           length: int = 14,
                           limit: int = 200,
                           exchange: ccxt.Exchange | None = None) -> Dict[str, Any]:
    """
    여러 타임프레임에 대한 RSI 계산
    
    Args:
        symbol: 거래 심볼
        timeframes: 타임프레임 리스트
        length: RSI 기간
        limit: 조회할 캔들 개수
        exchange: CCXT 거래소 객체
        
    Returns:
        타임프레임별 RSI 값 딕셔너리
    """
    if timeframes is None:
        timeframes = ['1m', '5m', '15m']

    if exchange is None:
        exchange = ccxt.bybit({'enableRateLimit': True})

    try:
        exchange.load_markets()
    except Exception:
        pass

    results: Dict[str, Any] = {}
    for tf in timeframes:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = compute_rsi(df, length=length)
        last = df.iloc[-1]
        results[tf] = {
            'rsi': float(last['rsi']) if pd.notna(last['rsi']) else None,
            'close': float(last['close']),
            'sample': df.tail(3).to_dict(orient='records')
        }

    return results


def print_rsi_results(results: Dict[str, Any], decimals: int = 2) -> None:
    """
    RSI 결과 출력
    
    Args:
        results: get_rsi_for_timeframes()의 결과
        decimals: 소수점 자릿수
    """
    fmt = f"{{tf}}: close={{close:.{decimals}f}}, rsi={{rsi:.{decimals}f}}"
    for tf, v in results.items():
        rsi = v.get('rsi') or 0.0
        close = v.get('close') or 0.0
        logger.info(fmt.format(tf=tf, close=close, rsi=rsi))


# ==================== 시장 데이터 유틸리티 ====================

def fetch_ohlcv_from_bybit(exchange, symbol: str, tf_name: str, limit: int = 3) -> Optional[list]:
    """
    OHLCV 데이터 조회 (마지막 캔들 반환)
    
    Args:
        exchange: CCXT 거래소 객체
        symbol: 거래 심볼
        tf_name: 타임프레임 (예: '15m', '1h', '1d')
        limit: 조회할 캔들 개수
        
    Returns:
        마지막 캔들 데이터 [timestamp, open, high, low, close, volume] 또는 None
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf_name, limit=limit)
        if not ohlcv:
            return None
        return ohlcv[-1]
    except Exception:
        return None


def fetch_ohlcv_field(exchange, symbol: str, tf_name: str, field: str = 'mid', limit: int = 3) -> Optional[float]:
    """
    OHLCV 필드 값 조회 (편의 함수)
    
    Args:
        exchange: CCXT 거래소 객체
        symbol: 거래 심볼
        tf_name: 타임프레임
        field: 조회할 필드 ('open', 'high', 'low', 'close', 'volume', 'mid')
        limit: 조회할 캔들 개수
        
    Returns:
        필드 값 (float) 또는 None
    """
    last = fetch_ohlcv_from_bybit(exchange, symbol, tf_name, limit=limit)
    if last:
        try:
            if field == 'mid':
                return (float(last[2]) + float(last[3])) / 2.0
            mapping = {'open': 1, 'high': 2, 'low': 3, 'close': 4, 'volume': 5}
            if field in mapping:
                return float(last[mapping[field]])
        except Exception:
            return 0.0

    return None


def get_band_values(bands: Dict[str, Any], tf_name: str, field: str = 'ma') -> Any:
    """
    볼린저 밴드 값 조회
    
    Args:
        bands: get_bollinger_for_timeframes()의 결과
        tf_name: 타임프레임
        field: 조회할 필드 ('ma', 'upper', 'lower', 'close')
        
    Returns:
        필드 값 또는 None
    """
    if not bands:
        return None
    return bands.get(tf_name, {}).get(field)


# ==================== 메인 실행 (테스트용) ====================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='기술적 지표 계산 도구')
    parser.add_argument('--indicator', '-i', choices=['bollinger', 'rsi'], default='bollinger',
                       help='계산할 지표 (bollinger 또는 rsi)')
    parser.add_argument('--symbol', '-s', default='ETH/USDT', help='거래 심볼 (예: ETH/USDT)')
    parser.add_argument('--timeframes', '-t', default='1m,5m,15m', help='타임프레임 (쉼표로 구분)')
    parser.add_argument('--length', '-l', type=int, default=20, help='이동평균/RSI 기간')
    parser.add_argument('--stddev', type=float, default=2.0, help='볼린저 밴드 표준편차 배수')
    args = parser.parse_args()

    tfs = [x.strip() for x in args.timeframes.split(',') if x.strip()]
    ex = ccxt.bybit({'enableRateLimit': True})
    
    if args.indicator == 'bollinger':
        res = get_bollinger_for_timeframes(
            args.symbol, 
            timeframes=tfs, 
            length=args.length, 
            stddev=args.stddev, 
            exchange=ex
        )
        print_bollinger_results(res, decimals=6)
    elif args.indicator == 'rsi':
        res = get_rsi_for_timeframes(
            args.symbol, 
            timeframes=tfs, 
            length=args.length, 
            exchange=ex
        )
        print_rsi_results(res, decimals=2)

