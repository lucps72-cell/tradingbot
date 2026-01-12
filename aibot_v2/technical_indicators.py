# === 단일 지표 반환 함수 ===
def calculate_ema_fast(df: pd.DataFrame, config: dict) -> pd.Series:
    return calculate_ema(df['close'], config['strategy']['ema']['fast'])

def calculate_ema_medium(df: pd.DataFrame, config: dict) -> pd.Series:
    return calculate_ema(df['close'], config['strategy']['ema']['medium'])

def calculate_ema_slow(df: pd.DataFrame, config: dict) -> pd.Series:
    return calculate_ema(df['close'], config['strategy']['ema']['slow'])

def calculate_rsi_series(df: pd.DataFrame, config: dict) -> pd.Series:
    return calculate_rsi(df['close'], config['strategy']['rsi']['period'])

def calculate_bb_upper(df: pd.DataFrame, config: dict) -> pd.Series:
    upper, _, _ = calculate_bollinger_bands(
        df['close'],
        config['strategy']['bollinger_bands']['period'],
        config['strategy']['bollinger_bands']['std_dev']
    )
    return upper

def calculate_bb_middle(df: pd.DataFrame, config: dict) -> pd.Series:
    _, middle, _ = calculate_bollinger_bands(
        df['close'],
        config['strategy']['bollinger_bands']['period'],
        config['strategy']['bollinger_bands']['std_dev']
    )
    return middle

def calculate_bb_lower(df: pd.DataFrame, config: dict) -> pd.Series:
    _, _, lower = calculate_bollinger_bands(
        df['close'],
        config['strategy']['bollinger_bands']['period'],
        config['strategy']['bollinger_bands']['std_dev']
    )
    return lower

def calculate_atr_series(df: pd.DataFrame, config: dict) -> pd.Series:
    return calculate_atr(df, config['risk_management']['atr_period'])

def calculate_adx_series(df: pd.DataFrame, config: dict) -> pd.Series:
    adx, _, _ = calculate_adx(df, config['risk_management'].get('adx_period', 14))
    return adx

def calculate_volume_ma_series(df: pd.DataFrame, config: dict) -> pd.Series:
    return calculate_volume_ma(df['volume'], config['strategy']['volume']['volume_ma_period'])
"""
Technical Indicators Module
기술적 지표 계산 모듈 (EMA, Bollinger Bands, RSI, Volume)
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional, Dict


def calculate_ema(data: pd.Series, period: int) -> pd.Series:
    """
    지수이동평균(EMA) 계산
    
    Args:
        data: 가격 데이터 (Series)
        period: EMA 기간
        
    Returns:
        EMA 값 Series
    """
    return data.ewm(span=period, adjust=False).mean()


def calculate_bollinger_bands(data: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    볼린저 밴드 계산
    
    Args:
        data: 가격 데이터 (Series)
        period: 이동평균 기간
        std_dev: 표준편차 배수
        
    Returns:
        (상단밴드, 중간밴드, 하단밴드)
    """
    middle = data.rolling(window=period).mean()
    std = data.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    return upper, middle, lower


def calculate_rsi(data: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI (Relative Strength Index) 계산
    
    Args:
        data: 가격 데이터 (Series)
        period: RSI 기간
        
    Returns:
        RSI 값 Series
    """
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ATR (Average True Range) 계산
    
    Args:
        df: OHLCV 데이터프레임
        period: ATR 기간
        
    Returns:
        ATR 값 Series
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    return atr


def calculate_adx(df: pd.DataFrame, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    ADX (Average Directional Index) 계산
    추세 강도를 측정하는 지표 (0-100)
    ADX > 25: 강한 추세
    ADX < 20: 약한 추세/횡보
    
    Args:
        df: OHLCV 데이터프레임
        period: ADX 기간
        
    Returns:
        (ADX, +DI, -DI) Series
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # +DM, -DM 계산
    plus_dm = high.diff()
    minus_dm = -low.diff()
    
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    
    # +DM과 -DM 중 큰 쪽만 유지
    plus_dm[(plus_dm < minus_dm)] = 0
    minus_dm[(minus_dm < plus_dm)] = 0
    
    # ATR 계산
    tr = pd.concat([
        high - low,
        abs(high - close.shift()),
        abs(low - close.shift())
    ], axis=1).max(axis=1)
    
    # 평활화 (Smoothed Moving Average)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    
    # DX 계산
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    
    # ADX 계산 (DX의 평활 이동평균)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    
    return adx, plus_di, minus_di


def calculate_volume_ma(volume: pd.Series, period: int = 20) -> pd.Series:
    """
    거래량 이동평균 계산
    
    Args:
        volume: 거래량 데이터 (Series)
        period: 이동평균 기간
        
    Returns:
        거래량 이동평균 Series
    """
    return volume.rolling(window=period).mean()


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


def check_ema_support(price: float, ema_fast: float, ema_medium: float, tolerance: float = 0.002) -> bool:
    """
    EMA 지지 확인 (가격이 EMA 근처에 있는지)
    
    Args:
        price: 현재 가격
        ema_fast: 빠른 EMA
        ema_medium: 중간 EMA
        tolerance: 허용 오차 비율
        
    Returns:
        EMA 지지 여부
    """
    # 빠른 EMA나 중간 EMA 중 하나에서 지지 받는지 확인
    fast_support = abs(price - ema_fast) / price <= tolerance
    medium_support = abs(price - ema_medium) / price <= tolerance
    
    # 가격이 EMA 위에 있는지 확인
    above_ema = price >= min(ema_fast, ema_medium)
    
    return (fast_support or medium_support) and above_ema


def check_ema_resistance(price: float, ema_fast: float, ema_medium: float, tolerance: float = 0.002) -> bool:
    """
    EMA 저항 확인 (가격이 EMA 근처에서 저항받는지)
    
    Args:
        price: 현재 가격
        ema_fast: 빠른 EMA
        ema_medium: 중간 EMA
        tolerance: 허용 오차 비율
        
    Returns:
        EMA 저항 여부
    """
    # 빠른 EMA나 중간 EMA 중 하나에서 저항 받는지 확인
    fast_resistance = abs(price - ema_fast) / price <= tolerance
    medium_resistance = abs(price - ema_medium) / price <= tolerance
    
    # 가격이 EMA 아래에 있는지 확인
    below_ema = price <= max(ema_fast, ema_medium)
    
    return (fast_resistance or medium_resistance) and below_ema


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


def get_trend_from_ema(price: float, ema_fast: float, ema_medium: float, ema_slow: float) -> str:
    """
    EMA로 추세 판단 (완화된 2단계 조건)
    
    Args:
        price: 현재 가격
        ema_fast: 빠른 EMA (9)
        ema_medium: 중간 EMA (20)
        ema_slow: 느린 EMA (30) - 참고용
        
    Returns:
        추세 ('uptrend', 'downtrend', 'ranging')
    """
    # 상승 추세: 가격이 EMA 9 위 + EMA 9이 20 위 (2단계)
    if price > ema_fast and ema_fast > ema_medium:
        return 'uptrend'
    
    # 하락 추세: 가격이 EMA 9 아래 + EMA 9이 20 아래 (2단계)
    if price < ema_fast and ema_fast < ema_medium:
        return 'downtrend'
    
    return 'ranging'


def get_trend_from_bollinger(price: float, bb_upper: float, bb_middle: float, bb_lower: float) -> str:
    """
    볼린저 밴드로 추세 판단
    
    Args:
        price: 현재 가격
        bb_upper: 상단 밴드
        bb_middle: 중간 밴드
        bb_lower: 하단 밴드
        
    Returns:
        추세 ('uptrend', 'downtrend', 'ranging')
    """
    band_width = (bb_upper - bb_lower) / bb_middle
    
    # 밴드 폭이 좁으면 횡보
    if band_width < 0.02:
        return 'ranging'
    
    # 가격이 상단 밴드 근처면 상승 추세
    if price >= bb_middle + (bb_upper - bb_middle) * 0.5:
        return 'uptrend'
    
    # 가격이 하단 밴드 근처면 하락 추세
    if price <= bb_middle - (bb_middle - bb_lower) * 0.5:
        return 'downtrend'
    
    return 'ranging'


def get_trend_from_rsi(rsi: float, overbought: float = 70.0, oversold: float = 30.0, midline: float = 50.0) -> str:
    """
    RSI로 추세 판단 (과매수/과매도 영역만 고려)
    
    Args:
        rsi: RSI 값
        overbought: 과매수 임계값 (기본: 70)
        oversold: 과매도 임계값 (기본: 30)
        midline: 중간선 기준값 (기본: 50)
        
    Returns:
        추세 ('uptrend', 'downtrend', 'neutral')
        
    Note:
        - RSI가 과매수/과매도 영역에만 도달했을 때만 신호 반환
        - 중간값 사이 범위는 'neutral'로 반환 (다른 지표와의 조합 필요)
    """
    if rsi >= overbought:
        return 'uptrend'
    elif rsi <= oversold:
        return 'downtrend'
    else:
        return 'neutral'


def combine_trend_signals(
    trend_ema: str,
    trend_bb: str,
    trend_rsi: str,
    min_agreement: int = 2
) -> Tuple[str, int]:
    """
    여러 지표의 추세를 조합해서 최종 추세 판단
    
    Args:
        trend_ema: EMA로 판단한 추세
        trend_bb: Bollinger Bands로 판단한 추세
        trend_rsi: RSI로 판단한 추세
        min_agreement: 최소 동의 개수 (기본: 2개 이상)
        
    Returns:
        (최종추세, 동의신호개수)
        최종추세: 'uptrend', 'downtrend', 'neutral'
        동의신호개수: 같은 방향으로 신호한 지표 개수
    """
    uptrend_signals = sum([
        1 for signal in [trend_ema, trend_bb, trend_rsi]
        if signal == 'uptrend'
    ])
    
    downtrend_signals = sum([
        1 for signal in [trend_ema, trend_bb, trend_rsi]
        if signal == 'downtrend'
    ])
    
    if uptrend_signals >= min_agreement:
        return 'uptrend', uptrend_signals
    elif downtrend_signals >= min_agreement:
        return 'downtrend', downtrend_signals
    else:
        return 'neutral', max(uptrend_signals, downtrend_signals)


def calculate_all_indicators(df: pd.DataFrame, config: dict) -> dict:
    """
    모든 주요 지표를 한번에 계산 (calculate_selected_indicators 기반)
    Args:
        df: OHLCV 데이터프레임
        config: 설정 딕셔너리
    Returns:
        계산된 지표 딕셔너리
    """
    indicator_list = [
        'ema_fast', 'ema_medium', 'ema_slow',
        'bb_upper', 'bb_middle', 'bb_lower',
        'rsi', 'atr', 'adx', 'plus_di', 'minus_di', 'volume_ma'
    ]
    return calculate_selected_indicators(df, config, indicator_list)

# ================= RSI 기반 추세 전환 감지 함수 =================
# 이 함수는 RSI 시계열, 가격 시계열, 분봉(timeframe) 문자열을 받아 
# 분봉 기준으로 과매도 돌파, 강세 다이버전스, 50선 돌파 등 RSI 기반 추세 전환 신호를 감지할 수 있습니다.
def detect_rsi_trend_reversal(
    rsi_series: pd.Series,
    price_series: pd.Series,
    timeframe: str = "1m",
    oversold: float = 30,
    overbought: float = 70,
    midline: float = 50,
    lookback: int = 5,
    logger=None
) -> str:
    """
    분봉 기준 RSI로 추세 전환(상승/하락) 신호 감지 (로그 포함)
    Args:
        rsi_series: RSI 값 시계열 (pd.Series)
        price_series: 가격 시계열 (pd.Series)
        timeframe: 분봉(예: '1m', '5m' 등) 문자열 (로깅/디버깅용)
        oversold: 과매도 기준값 (기본 30)
        overbought: 과매수 기준값 (기본 70)
        midline: RSI 중립선 기준값 (기본 50)
        lookback: 다이버전스 체크 구간 (기본 5)
        logger: 로그 함수 (print 또는 logging.info 등)
    Returns:
        신호별 결과 dict (True/False)
    """
    def log(msg):
        if logger:
            logger(msg)
        else:
            print(msg)


    # 신호별 의미:
    # 'RSI_ovsold_brkout': 과매도 구간(30 이하) 돌파 시 상승 전환
    # 'RSI_bull_dvrgence': 가격 저점 하락, RSI 저점 상승(강세 다이버전스)
    # 'RSI_mid_brkout': RSI 50선 상향 돌파(상승 모멘텀)
    # 'RSI_overbght_brkdn': 과매수 구간(70 이상) 이탈 시 하락 전환
    # 'RSI_bear_dvrgence': 가격 고점 상승, RSI 고점 하락(약세 다이버전스)
    # 'RSI_mid_brkdn': RSI 50선 하락 이탈(하락 모멘텀)
    result = {
        'RSI_ovrsold_brkout': False,
        'RSI_bull_dvrgence': False,
        'RSI_mid_brkout': False,
        'RSI_ovrbght_brkdn': False,
        'RSI_bear_dvrgence': False,
        'RSI_mid_brkdn': False
    }

    if len(rsi_series) < 2:
        #log(f"[{timeframe}] RSI 데이터 부족: len={len(rsi_series)}")
        return result

    # 상승 전환 신호
    if rsi_series.iloc[-2] < oversold and rsi_series.iloc[-1] >= oversold:
        #log(f"[{timeframe}] RSI 과매도 돌파: {rsi_series.iloc[-2]:.2f} -> {rsi_series.iloc[-1]:.2f}")
        result['RSI_ovrsold_brkout'] = True

    if len(rsi_series) >= lookback and len(price_series) >= lookback:
        recent_prices = price_series.iloc[-lookback:]
        recent_rsi = rsi_series.iloc[-lookback:]
        if recent_prices.min() < recent_prices[:-1].min() and recent_rsi.min() > recent_rsi[:-1].min():
            #log(f"[{timeframe}] RSI 강세 다이버전스: 가격저점 {recent_prices.min():.4f} < {recent_prices[:-1].min():.4f}, RSI저점 {recent_rsi.min():.2f} > {recent_rsi[:-1].min():.2f}")
            result['RSI_bull_dvrgence'] = True

    if rsi_series.iloc[-2] < midline and rsi_series.iloc[-1] >= midline:
        #log(f"[{timeframe}] RSI 50선 상향돌파: {rsi_series.iloc[-2]:.2f} -> {rsi_series.iloc[-1]:.2f}")
        result['RSI_mid_brkout'] = True

    # 하락 전환 신호
    if rsi_series.iloc[-2] > overbought and rsi_series.iloc[-1] <= overbought:
        #log(f"[{timeframe}] RSI 과매수 이탈: {rsi_series.iloc[-2]:.2f} -> {rsi_series.iloc[-1]:.2f}")
        result['RSI_ovrbght_brkdn'] = True

    if len(rsi_series) >= lookback and len(price_series) >= lookback:
        recent_prices = price_series.iloc[-lookback:]
        recent_rsi = rsi_series.iloc[-lookback:]
        if recent_prices.max() > recent_prices[:-1].max() and recent_rsi.max() < recent_rsi[:-1].max():
            #log(f"[{timeframe}] RSI 약세 다이버전스: 가격고점 {recent_prices.max():.4f} > {recent_prices[:-1].max():.4f}, RSI고점 {recent_rsi.max():.2f} < {recent_rsi[:-1].max():.2f}")
            result['RSI_bear_dvrgence'] = True

    if rsi_series.iloc[-2] > midline and rsi_series.iloc[-1] <= midline:
        #log(f"[{timeframe}] RSI 50선 하락이탈: {rsi_series.iloc[-2]:.2f} -> {rsi_series.iloc[-1]:.2f}")
        result['RSI_mid_brkdn'] = True


    #log(f"[{timeframe}] RSI 추세전환 신호 결과: {result}")
    return result


# ================= 선택된 지표만 계산하는 함수 =================
def calculate_selected_indicators(df: pd.DataFrame, config: dict, indicators: list) -> dict:
    """
    선택된 지표만 계산하는 함수
    
    Args:
        df (pd.DataFrame): OHLCV 데이터프레임. 반드시 다음 컬럼을 포함해야 함:
            - 'open': 시가
            - 'high': 고가
            - 'low': 저가
            - 'close': 종가
            - 'volume': 거래량
        config (dict): 설정 딕셔너리. 반드시 다음 구조와 키를 포함해야 함:
            config['strategy']['ema']['fast']: EMA 빠른 기간 (int)
            config['strategy']['ema']['medium']: EMA 중간 기간 (int)
            config['strategy']['ema']['slow']: EMA 느린 기간 (int)
            config['strategy']['bollinger_bands']['period']: 볼린저밴드 기간 (int)
            config['strategy']['bollinger_bands']['std_dev']: 볼린저밴드 표준편차 배수 (float)
            config['strategy']['rsi']['period']: RSI 기간 (int)
            config['strategy']['volume']['volume_ma_period']: 거래량 이동평균 기간 (int)
            config['risk_management']['atr_period']: ATR 기간 (int)
            config['risk_management']['adx_period']: ADX 기간 (int, optional)
        indicators (list of str): 계산할 지표명 리스트. 사용 가능한 값:
            'ema_fast', 'ema_medium', 'ema_slow',
            'bb_upper', 'bb_middle', 'bb_lower',
            'rsi', 'atr', 'adx', 'plus_di', 'minus_di', 'volume_ma'
    Returns:
        dict: 계산된 지표명(str)을 키로, pd.Series를 값으로 하는 딕셔너리
    """
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    result = {}
    for ind in indicators:
        if ind == 'ema_fast':
            result['ema_fast'] = calculate_ema(close, config['strategy']['ema']['fast'])
        elif ind == 'ema_medium':
            result['ema_medium'] = calculate_ema(close, config['strategy']['ema']['medium'])
        elif ind == 'ema_slow':
            result['ema_slow'] = calculate_ema(close, config['strategy']['ema']['slow'])
        elif ind == 'bb_upper' or ind == 'bb_middle' or ind == 'bb_lower':
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(
                close,
                config['strategy']['bollinger_bands']['period'],
                config['strategy']['bollinger_bands']['std_dev']
            )
            if ind == 'bb_upper':
                result['bb_upper'] = bb_upper
            if ind == 'bb_middle':
                result['bb_middle'] = bb_middle
            if ind == 'bb_lower':
                result['bb_lower'] = bb_lower
        elif ind == 'rsi':
            result['rsi'] = calculate_rsi(close, config['strategy']['rsi']['period'])
        elif ind == 'atr':
            result['atr'] = calculate_atr(df, config['risk_management']['atr_period'])
        elif ind == 'adx' or ind == 'plus_di' or ind == 'minus_di':
            adx, plus_di, minus_di = calculate_adx(df, config['risk_management'].get('adx_period', 14))
            if ind == 'adx':
                result['adx'] = adx
            if ind == 'plus_di':
                result['plus_di'] = plus_di
            if ind == 'minus_di':
                result['minus_di'] = minus_di
        elif ind == 'volume_ma':
            result['volume_ma'] = calculate_volume_ma(volume, config['strategy']['volume']['volume_ma_period'])
    return result