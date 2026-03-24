from typing import Optional
from venv import logger
import pandas as pd

def get_ema_values_for_realtime(exchange, symbol: str, limits: dict = {"1m": 200, "5m": 200}):
    """
    실시간 기준, 1분봉/5분봉의 EMA(5,20,60,120,200) 값을 가져온다.
    fetch_ohlcv_func: (symbol, timeframe, limit) -> ohlcv list 반환 함수 (exchange.fetch_ohlcv 등)
    symbol: 심볼명
    limits: 각 타임프레임별 데이터 개수(dict)
    return: { '1m': {5: float, ...}, '5m': {5: float, ...} }
    """
    ema_periods = [5, 20, 60, 120, 200]
    result = {}
    for tf in ["1m", "5m"]:
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=limits.get(tf, 200))
        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
        ema_dict = {}
        for period in ema_periods:
            ema_dict[period] = df["close"].ewm(span=period, adjust=False).mean().iloc[-1]
        result[tf] = ema_dict
    return result

def get_ema_values(df: pd.DataFrame, tf: str, periods=None):
    """
    1분봉/5분봉의 EMA 값을 가져온다.
    periods: EMA 기간 리스트 (예: [3, 7, 14, 28, 50])
    """
    if periods is None:
        periods = [5, 20, 60, 120, 200]
    ema_dict = {}
    for period in periods:
        ema_dict[period] = df["close"].ewm(span=period, adjust=False).mean().iloc[-1]
    return ema_dict

def parse_ema_periods(ema_dict):
    periods = []
    for k, v in ema_dict.items():
        if k.startswith('_comment'):
            continue
        try:
            val = int(v)
            periods.append(val)
        except (ValueError, TypeError):
            continue
    return periods

def get_ema_position(df: dict, fast=None, medium=None):
    """
    EMA 정렬 + 기울기 기반 포지션 판단 (config 기반 동적 키)
    fast, medium: 사용할 EMA 기간(정수)
    ema_vals: {period: float/Series, ...}
    return: "long", "short", or "neutral"
    """
    ema_fast = None
    ema_medium = None
    # config에서 fast/medium이 지정되면 해당 키 사용, 아니면 기존 fallback
    if fast is not None and medium is not None and fast in df and medium in df:
        ema_fast = df[fast]
        ema_medium = df[medium]
    elif 5 in df and 20 in df:
        ema_fast = df[5]
        ema_medium = df[20]
    elif 3 in df and 7 in df:
        ema_fast = df[3]
        ema_medium = df[7]
    else:
        raise KeyError("EMA dict에 fast/medium 키가 없습니다.")

    # Series(시계열)이면 마지막 값으로 비교, 아니면 float로 비교
    if hasattr(ema_fast, 'iloc') and hasattr(ema_medium, 'iloc'):
        val_fast = ema_fast.iloc[-1]
        val_medium = ema_medium.iloc[-1]
    else:
        val_fast = ema_fast
        val_medium = ema_medium

    if val_fast < val_medium:
        return 'downtrend'
    elif val_fast > val_medium:
        return 'uptrend'
    else:
        return 'sideways'

def get_bollinger_bands(df: pd.DataFrame, window=20, num_std=2):
    """볼린저 밴드 계산."""
    ma = df['close'].rolling(window=window).mean()
    std = df['close'].rolling(window=window).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    return upper, ma, lower

def get_rsi(df: pd.DataFrame, period=14):
    """RSI 계산."""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss

    return 100 - (100 / (1 + rs))

def get_rsi_trend(df: pd.DataFrame, recent_n=10):
    """RSI 기반 추세 판단 (상승/하락 비율 기반)"""
    ratio_threshold = 0.6  # 상승/하락 비율 임계값 (n개 값이 연속 상승/하락 비율)
    rsi_series = get_rsi(df, 14).dropna()
    if len(rsi_series) < recent_n + 1:
        return "sideways", "neutral"

    recent_rsi = rsi_series.iloc[-recent_n:]
    # 상승/하락 판별
    rsi_diff = recent_rsi.diff().dropna()
    up_count = sum(rsi_diff > 0)
    down_count = sum(rsi_diff < 0)
    up_ratio = up_count / (recent_n - 1)
    down_ratio = down_count / (recent_n - 1)

    if up_ratio >= ratio_threshold and recent_rsi.iloc[-1] > 40:
        trend = "uptrend"
    elif down_ratio >= ratio_threshold and recent_rsi.iloc[-1] < 60:
        trend = "downtrend"
    else:
        trend = "sideways"

    # 추세 강도 판단
    mean_rsi = recent_rsi.mean()
    if mean_rsi >= 60 and recent_rsi.iloc[-1] > 70:
        trend_strength = "strong_up"
    elif mean_rsi <= 40 and recent_rsi.iloc[-1] < 30:
        trend_strength = "strong_down"
    else:
        trend_strength = "neutral"

    return trend, trend_strength

def get_bollinger_trend(df: pd.DataFrame, recent_n=15, band_break_count=1):
    """볼린저 밴드 기반 추세 판단 + 밴드폭 시계열 포함"""
    window = 20  # 볼린저 밴드 기간 단축(빠른 반응)
    num_std = 2
    band_squeeze_threshold = 0.03  # 밴드폭 수축 임계값
    # 추가 파라미터: 밴드폭 증가 판단 구간, upper proximity 비율
    bandwidth_increase_lookback = 2  # 최근 몇 개 구간에서 밴드폭 증가 판단
    upper_proximity_ratio = 0.7      # upper proximity 기준 강화
    lower_proximity_ratio = -0.7     # lower proximity 기준 강화

    bb_upper, bb_middle, bb_lower = get_bollinger_bands(df, window, num_std)
    close = df['close']

    # 최근 n개만 추출
    recent_close = close.iloc[-recent_n:]
    recent_upper = bb_upper.iloc[-recent_n:]
    recent_lower = bb_lower.iloc[-recent_n:]
    recent_middle = bb_middle.iloc[-recent_n:]
    # 밴드폭 시계열
    recent_bandwidth = (recent_upper - recent_lower) / recent_middle
    # 밴드 수축 여부 (마지막 값 기준)
    is_squeeze = recent_bandwidth.iloc[-1] < band_squeeze_threshold

    # 밴드폭 증가(확장) 여부: 최근 bandwidth_increase_lookback개 중 마지막 값이 이전들보다 크면 확장
    is_bandwidth_increasing = False
    if len(recent_bandwidth) >= bandwidth_increase_lookback:
        last_bandwidth = recent_bandwidth.iloc[-1]
        prev_bandwidths = recent_bandwidth.iloc[-bandwidth_increase_lookback:-1]
        is_bandwidth_increasing = all(last_bandwidth > bw for bw in prev_bandwidths)

    # 종가가 upper proximity 기준 이상에 위치하는지
    last_close = recent_close.iloc[-1]
    last_upper = recent_upper.iloc[-1]
    last_lower = recent_lower.iloc[-1]
    last_middle = recent_middle.iloc[-1]
    # upper proximity: (종가 - middle) / (upper - middle)
    if last_upper > last_middle:
        upper_proximity = (last_close - last_middle) / (last_upper - last_middle)
    else:
        upper_proximity = 0
    # lower proximity: (종가 - middle) / (lower - middle)
    if last_lower < last_middle:
        lower_proximity = (last_close - last_middle) / (last_lower - last_middle)
    else:
        lower_proximity = 0

    # 돌파 조건 제외, proximity와 밴드폭 확장만으로 추세 판단
    if is_bandwidth_increasing and upper_proximity >= upper_proximity_ratio:
        trend = "uptrend"
    elif is_bandwidth_increasing and lower_proximity <= lower_proximity_ratio:
        trend = "downtrend"
    else:
        trend = "sideways"

    return {
        "trend": trend,
        "bandwidth_series": recent_bandwidth,
        "is_squeeze": is_squeeze,
        "upper_proximity": upper_proximity,
        "lower_proximity": lower_proximity
    }

def get_ema_trend(ema_vals: dict) -> tuple:
    """
    EMA 간 차이 비율 기반 추세 판단
    ema_vals: {5: float, 20: float, 60: float, 120: float, 200: float}
    return: (trend_value, trend_msg)
    """
    return_value = None
    return_msg = ""

    ema_5 = ema_vals[5]
    ema_20 = ema_vals[20]
    ema_60 = ema_vals[60]
    ema_120 = ema_vals[120]
    ema_200 = ema_vals[200]
    def ratio_diff(a, b, threshold):
        return abs(a - b) / ((a + b) / threshold)
    threshold_1 = 1 # 1% 허용 오차
    pairs = [
        (ema_5, ema_20),
        (ema_5, ema_60),
        (ema_5, ema_120),
        (ema_5, ema_200),
        (ema_20, ema_60),
        (ema_20, ema_120),
        (ema_20, ema_200),
        # (ema_60, ema_120),
        # (ema_60, ema_200),
        # (ema_120, ema_200),
    ]
    ratios = [ratio_diff(a, b, threshold_1) for a, b in pairs]
    is_sideways = all(r <= threshold_1*0.001 for r in ratios)
    if not is_sideways:
        threshold_2 = 2 # 2% 허용 오차
        ratios = [
            ratio_diff(ema_5, ema_20, threshold_1),
            ratio_diff(ema_5, ema_60, threshold_1),
            ratio_diff(ema_5, ema_120, threshold_1),
            ratio_diff(ema_5, ema_200, threshold_1),
            ratio_diff(ema_20, ema_60, threshold_2),
            ratio_diff(ema_20, ema_120, threshold_2),
            ratio_diff(ema_20, ema_200, threshold_2),
            # ratio_diff(ema_60, ema_120, threshold_2),
            # ratio_diff(ema_60, ema_200, threshold_2),
            # ratio_diff(ema_120, ema_200, threshold_2),
        ]
        is_sideways = all(r <= threshold_2*0.001 for r in ratios)
        if is_sideways:
            return_value = "ranging"
            return_msg = "[횡보(박스권)] 모든 EMA 간 차이 비율이 2% 이하입니다."
        else:
            if ema_5 > ema_20: # > ema_60 > ema_120 > ema_200:
                return "uptrend", "[추세(상승) 구간] 모든 EMA 간 차이 비율이 2% 초과입니다."
            elif ema_5 < ema_20: # < ema_60 < ema_120 < ema_200:
                return "downtrend", "[추세(하락) 구간] 모든 EMA 간 차이 비율이 2% 초과입니다."
            else:
                return_value = "complex"
                return_msg = "[복합추세] 일부 EMA 간 차이 비율이 2% 초과입니다."
    else:
        return_value = "crossover"
        return_msg = "[추세변환(크로스) 직전] 모든 EMA 간 차이 비율이 1% 이하입니다."

    if return_value == "crossover":  # 골든/데드크로스 신호 체크 (순수 파이썬)
        closes = list(ema_vals['close']) if 'close' in ema_vals else []
        cross_signal = detect_cross(closes, short_period=9, long_period=21)
        if cross_signal == 'golden':
            return_value = "uptrend"
            return_msg = "[EMA크로스] 단기 EMA가 장기 EMA를 상향 돌파했습니다."
        elif cross_signal == 'death':
            return_value = "downtrend"
            return_msg = "[EMA크로스] 단기 EMA가 장기 EMA를 하향 돌파했습니다."
        else:
            return_msg = "[EMA크로스] 신호 없음"

    return return_value, return_msg
    
    
def detect_ema_crossover(prev_ema_fast: float, prev_ema_medium: float, 
                        curr_ema_fast: float, curr_ema_medium: float) -> Optional[str]:
    """
    EMA 크로스오버 감지 (추세 전환 조기 신호)
    주의: 이 함수는 기본 크로스 감지만 수행. 3봉 확정은 strategy에서 처리
    
    Args:
        prev_ema_fast: 이전 빠른 EMA
        prev_ema_medium: 이전 중간 EMA
        curr_ema_fast: 현재 빠른 EMA
        curr_ema_medium: 현재 중간 EMA
        
    Returns:
        'golden_cross' (상승 전환), 'death_cross' (하락 전환), None (크로스 없음)
    """
    # 골든 크로스: 빠른 EMA가 중간 EMA를 상향 돌파
    if prev_ema_fast <= prev_ema_medium and curr_ema_fast > curr_ema_medium:
        return 'golden_cross'
    
    # 데드 크로스: 빠른 EMA가 중간 EMA를 하향 돌파
    if prev_ema_fast >= prev_ema_medium and curr_ema_fast < curr_ema_medium:
        return 'death_cross'
    
    return None

def check_time_volatility(current_time: pd.Timestamp, close: float, 
                        prev_close: float, threshold: float = 0.005) -> bool:
    """
    시간대별 변동성 필터
    07:00-09:30 구간에서 변동성이 낮으면 진입 회피
    
    Args:
        current_time: 현재 시간
        close: 현재 종가
        prev_close: 이전 종가
        threshold: 변동성 임계값 (0.5% 기본)
        
    Returns:
        진입 가능 여부 (False면 회피)
    """
    hour = current_time.hour
    minute = current_time.minute
    
    # 07:00-09:30 구간 (실패 구간)
    if (hour == 7) or (hour == 8) or (hour == 9 and minute <= 30):
        # 변동성 계산
        volatility = abs(close - prev_close) / prev_close
        
        # 변동성이 임계값 이하면 진입 회피
        if volatility < threshold:
            return False
    
    return True

# 순수 파이썬 EMA 계산 함수
def calculate_ema(closes, period):
    """
    주어진 종가 리스트(closes)와 기간(period)으로 EMA(지수이동평균) 시퀀스를 반환합니다.
    """
    ema = []
    multiplier = 2 / (period + 1)
    for i, price in enumerate(closes):
        if i == 0:
            ema.append(price)
        else:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema

# 골든크로스/데드크로스 판별 함수
def detect_cross(closes, short_period=9, long_period=21):
    """
    단기/장기 EMA 교차로 골든/데드크로스 신호를 반환합니다.
    return: "golden", "dead", or None
    """
    ema_short = calculate_ema(closes, short_period)
    ema_long = calculate_ema(closes, long_period)
    if len(ema_short) < 2 or len(ema_long) < 2:
        return None
    prev_short = ema_short[-2]
    prev_long = ema_long[-2]
    curr_short = ema_short[-1]
    curr_long = ema_long[-1]
    #print(f"이전 단기 EMA: {prev_short}, 이전 장기 EMA: {prev_long}")
    #print(f"현재 단기 EMA: {curr_short}, 현재 장기 EMA: {curr_long}")

    if prev_short <= prev_long and curr_short > curr_long:
        return "golden"
    if prev_short >= prev_long and curr_short < curr_long:
        return "dead"
    return None

# ================= RSI 다이버전스 감지 함수 =================
def detect_rsi_bull_divergence(rsi_series: pd.Series, price_series: pd.Series, lookback: int = 16, price_min_diff: float = 0.001, rsi_min_diff: float = 0.05) -> bool:
    """
    RSI 강세 다이버전스: 가격 저점 하락, RSI 저점 상승 (임계값 적용)
    lookback: 체크 구간 (default 25)
    price_min_diff: 가격 저점 차이 임계값 (default 0.1)
    rsi_min_diff: RSI 저점 차이 임계값 (default 1.0)
    """
    if len(rsi_series) < lookback or len(price_series) < lookback:
        return False
    recent_prices = price_series.iloc[-lookback:]
    recent_rsi = rsi_series.iloc[-lookback:]
    price_min_now = recent_prices.min()
    price_min_prev = recent_prices[:-1].min()
    rsi_min_now = recent_rsi.min()
    rsi_min_prev = recent_rsi[:-1].min()
    price_diff = price_min_prev - price_min_now
    rsi_diff = rsi_min_now - rsi_min_prev
    result = (price_min_now < price_min_prev - price_min_diff) and (rsi_min_now > rsi_min_prev + rsi_min_diff)
    #print(f"[DEBUG][bull_div] price_min_now={price_min_now}, price_min_prev={price_min_prev}, price_diff={price_diff}, rsi_min_now={rsi_min_now}, rsi_min_prev={rsi_min_prev}, rsi_diff={rsi_diff}, result={result}")
    return result

def detect_rsi_bear_divergence(rsi_series: pd.Series, price_series: pd.Series, lookback: int = 16, price_max_diff: float = 0.001, rsi_max_diff: float = 0.05) -> bool:
    """
    RSI 약세 다이버전스: 가격 고점 상승, RSI 고점 하락 (임계값 적용)
    lookback: 체크 구간 (default 25)
    price_max_diff: 가격 고점 차이 임계값 (default 0.1)
    rsi_max_diff: RSI 고점 차이 임계값 (default 1.0)
    """
    if len(rsi_series) < lookback or len(price_series) < lookback:
        return False
    recent_prices = price_series.iloc[-lookback:]
    recent_rsi = rsi_series.iloc[-lookback:]
    price_max_now = recent_prices.max()
    price_max_prev = recent_prices[:-1].max()
    rsi_max_now = recent_rsi.max()
    rsi_max_prev = recent_rsi[:-1].max()
    price_diff = price_max_now - price_max_prev
    rsi_diff = rsi_max_prev - rsi_max_now
    result = (price_max_now > price_max_prev + price_max_diff) and (rsi_max_now < rsi_max_prev - rsi_max_diff)
    #print(f"[DEBUG][bear_div] price_max_now={price_max_now}, price_max_prev={price_max_prev}, price_diff={price_diff}, rsi_max_now={rsi_max_now}, rsi_max_prev={rsi_max_prev}, rsi_diff={rsi_diff}, result={result}")
    return result

# ================= 커스텀 로컬 저점/고점 기반 RSI 다이버전스 감지 함수 =================
import numpy as np

def find_local_minima(series: pd.Series, order: int = 3):
    """
    주어진 시계열에서 로컬 미니멈(저점) 인덱스 반환
    order: 좌우 몇 개씩 비교할지(3이면 3개)
    """
    from scipy.signal import argrelextrema
    return argrelextrema(series.values, np.less, order=order)[0]

def find_local_maxima(series: pd.Series, order: int = 3):
    """
    주어진 시계열에서 로컬 맥시멈(고점) 인덱스 반환
    """
    from scipy.signal import argrelextrema
    return argrelextrema(series.values, np.greater, order=order)[0]

def detect_rsi_bull_divergence_local(rsi_series: pd.Series, price_series: pd.Series, order: int = 2, lookback: int = 16, price_min_diff: float = 0.001, rsi_min_diff: float = 0.05) -> bool:
    """
    최근 두 개의 로컬 저점에서 가격은 하락, RSI는 상승하면 True(강세 다이버전스)
    lookback: 최근 구간에서만 로컬 저점 비교
    price_min_diff: 가격 저점 차이 임계값 (default 0.02)
    rsi_min_diff: RSI 저점 차이 임계값 (default 1.0)
    """
    idxs = find_local_minima(price_series, order=order)
    # lookback 구간 내의 로컬 저점만 사용
    idxs = [i for i in idxs if i >= len(price_series) - lookback]
    if len(idxs) < 2:
        return False
    idx1, idx2 = idxs[-2], idxs[-1]
    price1, price2 = price_series.iloc[idx1], price_series.iloc[idx2]
    rsi1, rsi2 = rsi_series.iloc[idx1], rsi_series.iloc[idx2]
    price_diff = price1 - price2
    rsi_diff = rsi2 - rsi1
    result = (price2 < price1 - price_min_diff) and (rsi2 > rsi1 + rsi_min_diff)
    #print(f"[DEBUG][bull_div_local] idx1={idx1}, idx2={idx2}, price1={price1}, price2={price2}, price_diff={price_diff}, rsi1={rsi1}, rsi2={rsi2}, rsi_diff={rsi_diff}, result={result}")
    return result

def detect_rsi_bear_divergence_local(rsi_series: pd.Series, price_series: pd.Series, order: int = 2, lookback: int = 16, price_max_diff: float = 0.001, rsi_max_diff: float = 0.05) -> bool:
    """
    최근 두 개의 로컬 고점에서 가격은 상승, RSI는 하락하면 True(약세 다이버전스)
    lookback: 최근 구간에서만 로컬 고점 비교
    price_max_diff: 가격 고점 차이 임계값 (default 0.01)
    rsi_max_diff: RSI 고점 차이 임계값 (default 1.0)
    """
    idxs = find_local_maxima(price_series, order=order)
    # lookback 구간 내의 로컬 고점만 사용
    idxs = [i for i in idxs if i >= len(price_series) - lookback]
    if len(idxs) < 2:
        return False
    idx1, idx2 = idxs[-2], idxs[-1]
    price1, price2 = price_series.iloc[idx1], price_series.iloc[idx2]
    rsi1, rsi2 = rsi_series.iloc[idx1], rsi_series.iloc[idx2]
    price_diff = price2 - price1
    rsi_diff = rsi1 - rsi2
    result = (price2 > price1 + price_max_diff) and (rsi2 < rsi1 - rsi_max_diff)
    #print(f"[DEBUG][bear_div_local] idx1={idx1}, idx2={idx2}, price1={price1}, price2={price2}, price_diff={price_diff}, rsi1={rsi1}, rsi2={rsi2}, rsi_diff={rsi_diff}, result={result}")
    return result

# --- Spike Reversal Pattern Detection (그림의 원안) ---
def detect_spike_reversal(
    df: pd.DataFrame,
    wick_ratio: float = 2.0,
    min_rsi: float = 30.0,
    max_rsi: float = 70.0,
    band_break: bool = True,
    volume_multiplier: float = 1.5,
    lookback: int = 3
) -> dict:
    """
    Detects both bullish (down_reversal) and bearish (up_reversal) spike reversal patterns.
    Args:
        df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
        wick_ratio: How much longer the wick should be compared to the body
        min_rsi: RSI threshold for bullish reversal
        max_rsi: RSI threshold for bearish reversal
        band_break: Require Bollinger Band break
        volume_multiplier: Volume spike threshold (x times recent mean)
        lookback: How many recent bars to check
    Returns:
        dict: {'down_reversal': bool, 'up_reversal': bool}
    """
    if len(df) < lookback + 20:
        return {'down_reversal': False, 'up_reversal': False}

    result = {'down_reversal': False, 'up_reversal': False}
    bb_upper, bb_middle, bb_lower = get_bollinger_bands(df, window=20, num_std=2)
    rsi = get_rsi(df, period=14)
    recent = df.iloc[-lookback:]
    recent_rsi = rsi.iloc[-lookback:]
    recent_upper = bb_upper.iloc[-lookback:]
    recent_lower = bb_lower.iloc[-lookback:]
    recent_vol = df['volume'].iloc[-lookback:]
    mean_vol = df['volume'].iloc[-(lookback+20):-lookback].mean() if len(df) > (lookback+20) else df['volume'].mean()

    for i in range(lookback):
        o = recent['open'].iloc[i]
        h = recent['high'].iloc[i]
        l = recent['low'].iloc[i]
        c = recent['close'].iloc[i]
        wick_top = h - max(o, c)
        wick_bot = min(o, c) - l
        body = abs(o - c)
        rsi_val = recent_rsi.iloc[i]
        vol = recent_vol.iloc[i]
        upper = recent_upper.iloc[i]
        lower = recent_lower.iloc[i]

        # Bullish reversal (down_reversal): long lower wick, RSI low, band break, volume spike
        if (
            wick_bot > wick_ratio * body and
            c > o and
            rsi_val < min_rsi and
            (l < lower if band_break else True) and
            vol > volume_multiplier * mean_vol
        ):
            result['down_reversal'] = True

        # Bearish reversal (up_reversal): long upper wick, RSI high, band break, volume spike
        if (
            wick_top > wick_ratio * body and
            c < o and
            rsi_val > max_rsi and
            (h > upper if band_break else True) and
            vol > volume_multiplier * mean_vol
        ):
            result['up_reversal'] = True

    return result

# --- Bollinger Band Riding Detection ---
def detect_band_riding(df: pd.DataFrame, window: int = 20, num_std: int = 2, lookback: int = 8, proximity: float = 0.98, direction: str = 'upper', min_count: int = 7) -> bool:
    """
    볼린저밴드 밴드타기(상단/하단) 패턴 감지
    Args:
        df: OHLCV 데이터프레임
        window: 볼린저밴드 기간
        num_std: 표준편차
        lookback: 최근 체크할 캔들 수
        proximity: 밴드 근접 기준 (예: 0.98이면 upper*0.98 이상)
        direction: 'upper' 또는 'lower'
        min_count: 밴드 근처에 위치한 최소 캔들 수
    Returns:
        bool: 밴드타기 패턴 감지 여부
    로그 예시: [밴드타기] 상단: True, 하단: False
    활용: is_upper_riding, is_lower_riding 값을 진입/청산 필터, 추세 지속 신호 등으로 사용할 수 있습니다.
    """
    # 최근 recent_n개가 연속으로 조건을 만족하면 True
    recent_n = lookback if lookback else 3
    if len(df) < recent_n + window:
        return False
    upper, middle, lower = get_bollinger_bands(df, window, num_std)
    closes = df['close'].iloc[-recent_n:]
    uppers = upper.iloc[-recent_n:]
    lowers = lower.iloc[-recent_n:]
    for i in range(recent_n):
        if direction == 'upper':
            if closes.iloc[i] < uppers.iloc[i] * proximity:
                return False
        elif direction == 'lower':
            if closes.iloc[i] > lowers.iloc[i] * proximity:
                return False
    return True

def detect_consecutive_candles(df, direction='up', lookback=3):
    """
    연속 양봉/음봉 감지
    direction: 'up' (양봉), 'down' (음봉)
    lookback: 연속 개수
    return: True/False
    """
    closes = df['close']
    opens = df['open']
    if direction == 'up':
        return all(closes.iloc[-lookback:] > opens.iloc[-lookback:])
    else:
        return all(closes.iloc[-lookback:] < opens.iloc[-lookback:])
    

def check_volume_spike(volume: pd.Series, volume_ma: pd.Series, threshold: float = 1.5) -> bool:
    """
    거래량 급증 확인
    
    Args:
        volume: 현재 거래량 Series
        volume_ma: 거래량 이동평균 Series
        threshold: 급증 판단 임계값 (평균의 n배)
        
    Returns:
        거래량 급증 여부
    """
    if len(volume) == 0 or len(volume_ma) == 0:
        return False
    
    current_volume = volume.iloc[-1]
    avg_volume = volume_ma.iloc[-1]
    
    if pd.isna(avg_volume) or avg_volume == 0:
        return False
    
    return current_volume >= (avg_volume * threshold)

