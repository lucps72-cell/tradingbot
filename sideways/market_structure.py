"""
Market Structure Analysis Module
가격 구조(고점/저점) 분석 및 추세 전환 감지
"""
import logging
from venv import logger
import pandas as pd
import numpy as np
from typing import Tuple, List, Optional, Dict

active_logger = logging.getLogger(__name__)
active_logger.setLevel(logging.DEBUG)

class MarketStructure:
    """시장 구조 분석 클래스"""
    
    def __init__(self, lookback: int = 5, min_swing_size: float = 0.002):
        """
        Args:
            lookback: 고점/저점 확인을 위한 좌우 캔들 수
            min_swing_size: 유효한 스윙으로 인정할 최소 변동 비율
        """
        self.lookback = lookback
        self.min_swing_size = min_swing_size
    
    def find_swing_highs(self, df: pd.DataFrame) -> List[int]:
        """
        스윙 고점(Swing High) 찾기 - 구간 최고가 조건 추가
        Args:
            df: OHLCV 데이터프레임
        Returns:
            스윙 고점의 인덱스 리스트
        """
        swing_highs = []
        highs = df['high'].values
        for i in range(self.lookback, len(highs) - self.lookback):
            window_high = highs[i - self.lookback : i + self.lookback + 1]
            window_low = df['low'].values[i - self.lookback : i + self.lookback + 1]
            # i번째 봉의 high가 구간 최고가이면서, low가 구간 최저가가 아닐 때만 인정
            # 저점 봉의 high가 고점으로 잡히는 현상 원천 차단
            # 저점 봉의 high가 고점으로 잡히는 현상 원천 차단 (실수 오차까지 고려)
            low_val = df['low'].values[i]
            open_val = df['open'].values[i]
            close_val = df['close'].values[i]
            is_not_bottom = abs(low_val - np.min(window_low)) > 1e-6
            candle_length = highs[i] - low_val
            lower_shadow = min(open_val, close_val) - low_val
            lower_shadow_ratio = lower_shadow / candle_length if candle_length > 0 else 0
            open_close_near_low = abs(open_val - low_val) < 1e-6 or abs(close_val - low_val) < 1e-6
            # 저점 봉 구조적 특성 복합적으로 제외
            if (
                highs[i] == np.max(window_high)
                and is_not_bottom
                and lower_shadow_ratio < 0.6
                and not open_close_near_low
            ):
                # 최소 변동 크기 확인
                if i > 0:
                    swing_size = abs(highs[i] - highs[i - 1]) / highs[i - 1]
                    if swing_size >= self.min_swing_size:
                        swing_highs.append(i)
        return swing_highs
    
    def find_swing_lows(self, df: pd.DataFrame) -> List[int]:
        """
        스윙 저점(Swing Low) 찾기
        
        Args:
            df: OHLCV 데이터프레임
            
        Returns:
            스윙 저점의 인덱스 리스트
        """
        swing_lows = []
        lows = df['low'].values
        
        for i in range(self.lookback, len(lows) - self.lookback):
            # 좌우 lookback 캔들보다 낮은지 확인
            is_low = True
            for j in range(1, self.lookback + 1):
                if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                    is_low = False
                    break
            
            if is_low:
                # 최소 변동 크기 확인
                if i > 0:
                    swing_size = abs(lows[i] - lows[i - 1]) / lows[i - 1]
                    if swing_size >= self.min_swing_size:
                        swing_lows.append(i)
        
        return swing_lows
    
    def detect_trend(self, df: pd.DataFrame) -> Tuple[str, Dict]:
        """
        HH/HL/LL/LH 패턴으로 추세 감지
        
        Args:
            df: OHLCV 데이터프레임
            
        Returns:
            (추세, 상세정보)
            추세: 'uptrend', 'downtrend', 'ranging'
        """
        swing_highs_idx = self.find_swing_highs(df)
        swing_lows_idx = self.find_swing_lows(df)
        
        if len(swing_highs_idx) < 2 or len(swing_lows_idx) < 2:
            return 'ranging', {'reason': 'insufficient_swings'}
        
        # 최근 2개의 고점과 저점 가져오기
        recent_highs = [df['high'].iloc[i] for i in swing_highs_idx[-2:]]
        recent_lows = [df['low'].iloc[i] for i in swing_lows_idx[-2:]]
        
        # Higher High & Higher Low 체크
        higher_high = recent_highs[-1] > recent_highs[-2]
        higher_low = recent_lows[-1] > recent_lows[-2]
        
        # Lower Low & Lower High 체크
        lower_low = recent_lows[-1] < recent_lows[-2]
        lower_high = recent_highs[-1] < recent_highs[-2]
        
        details = {
            'recent_highs': recent_highs,
            'recent_lows': recent_lows,
            'higher_high': higher_high,
            'higher_low': higher_low,
            'lower_low': lower_low,
            'lower_high': lower_high,
            'swing_highs_count': len(swing_highs_idx),
            'swing_lows_count': len(swing_lows_idx)
        }
        
        # 상승 추세: HH & HL
        if higher_high and higher_low:
            return 'uptrend', details
        
        # 하락 추세: LL & LH
        if lower_low and lower_high:
            return 'downtrend', details
        
        # 그 외는 횡보
        return 'ranging', details
    

    def check_structure_break(self, df: pd.DataFrame, current_price: float = None) -> Tuple[Tuple[bool, str, str], Tuple[bool, str, str]]:
        """
        추세 구조 붕괴 확인
        
        Args:
            df: OHLCV 데이터프레임
            current_price: 실시간 현재가 (기본값: None)
            
        Returns:
            (구조붕괴여부, 전환될추세, 상세메시지)
            (True, 'downtrend', return_msg), (False, 'uptrend', return_msg)

        """
        swing_highs_idx = self.find_swing_highs(df)
        swing_lows_idx = self.find_swing_lows(df)
        recent_high = None
        recent_low = None
        if len(swing_highs_idx) < 2 or len(swing_lows_idx) < 2:
            if len(swing_highs_idx) == 1:
                idx_high = swing_highs_idx[-1]
                recent_high = df['high'].iloc[idx_high]
            else:
                idx_high = None
            if len(swing_lows_idx) == 1:
                idx_low = swing_lows_idx[-1]
                recent_low = df['low'].iloc[idx_low]
            else:
                idx_low = None
            active_logger.info(f"recent_high: {recent_high} (idx: {idx_high}), recent_low: {recent_low} (idx: {idx_low})")
            return False, "", False, "", f"Not enough swing points: highs={len(swing_highs_idx)} lows={len(swing_lows_idx)} | recent_high: {recent_high} (idx: {idx_high}), recent_low: {recent_low} (idx: {idx_low})"
        recent_high = df['high'].iloc[swing_highs_idx[-1]]
        prev_high = df['high'].iloc[swing_highs_idx[-2]]
        recent_low = df['low'].iloc[swing_lows_idx[-1]]
        prev_low = df['low'].iloc[swing_lows_idx[-2]]

        if current_price is None:
            current_price = df['close'].iloc[-1]
        return_msg = f"current_price: {current_price}, recent_high: {recent_high}, prev_high: {prev_high}, recent_low: {recent_low}, prev_low: {prev_low}"

        return_yn = return_yn2 = False
        return_trend = return_trend2 = ''
        # 상승 추세에서 HL(Higher Low) 붕괴 확인 (실시간 현재가 기준)
        if current_price < prev_low:
            return_yn = True
            return_trend = 'downtrend'
        # 하락 추세에서 LH(Lower High) 붕괴 확인 (실시간 현재가 기준)
        if current_price > prev_high:
            return_yn2 = True
            return_trend2 = 'uptrend'
            
        return return_yn, return_trend, return_yn2, return_trend2, return_msg

    
    def get_last_swing_points(self, df: pd.DataFrame) -> Dict:
        """
        최근 스윙 포인트 정보 반환
        
        Args:
            df: OHLCV 데이터프레임
            
        Returns:
            최근 스윙 고점/저점 정보
        """
        swing_highs_idx = self.find_swing_highs(df)
        swing_lows_idx = self.find_swing_lows(df)
        
        result = {
            'last_swing_high': None,
            'last_swing_high_idx': None,
            'last_swing_low': None,
            'last_swing_low_idx': None
        }
        
        if len(swing_highs_idx) > 0:
            idx = swing_highs_idx[-1]
            result['last_swing_high'] = df['high'].iloc[idx]
            result['last_swing_high_idx'] = idx
        
        if len(swing_lows_idx) > 0:
            idx = swing_lows_idx[-1]
            result['last_swing_low'] = df['low'].iloc[idx]
            result['last_swing_low_idx'] = idx
        
        return result

    def find_swing_points(self, ohlcv, left=3, right=3):
        """
        ohlcv : list of [timestamp, open, high, low, close, volume]
        left  : 기준 봉 왼쪽 봉 개수
        right : 기준 봉 오른쪽 봉 개수

        return:
            swing_highs : list of dict
            swing_lows  : list of dict
        """

        swing_highs = []
        swing_lows = []

        for i in range(left, len(ohlcv) - right):
            high = ohlcv[i][2]
            low = ohlcv[i][3]

            is_swing_high = True
            is_swing_low = True

            # 왼쪽 검사
            for j in range(i - left, i):
                if ohlcv[j][2] >= high:
                    is_swing_high = False
                if ohlcv[j][3] <= low:
                    is_swing_low = False

            # 오른쪽 검사
            for j in range(i + 1, i + right + 1):
                if ohlcv[j][2] > high:
                    is_swing_high = False
                if ohlcv[j][3] < low:
                    is_swing_low = False

            if is_swing_high:
                swing_highs.append({
                    "index": i,
                    "timestamp": ohlcv[i][0],
                    "price": high
                })

            if is_swing_low:
                swing_lows.append({
                    "index": i,
                    "timestamp": ohlcv[i][0],
                    "price": low
                })
            
        return swing_highs, swing_lows

    def check_trend_by_swing_points(self, ohlcv):
        """
        ohlcv : list of [timestamp, open, high, low, close, volume]
        left  : 기준 봉 왼쪽 봉 개수
        right : 기준 봉 오른쪽 봉 개수

        return:
            swing_highs : list of dict
            swing_lows  : list of dict
        """
        return_high, return_low = None, None
        msg_high, msg_low = "", ""

        swing_highs, swing_lows = self.find_swing_points(ohlcv, left=2, right=2)

        if len(swing_highs) >= 2:
            if swing_highs[-1]['price'] > swing_highs[-2]['price']:
                msg_high = "스윙 고점이 상승 중입니다."
                return_high = 'uptrend'
            elif swing_highs[-1]['price'] < swing_highs[-2]['price']:
                msg_high = "스윙 고점이 하락 중입니다."
                return_high = 'downtrend'
            else:
                msg_high = "스윙 고점 변화 없음."
        else:
            msg_high = "스윙 고점이 없습니다."

        if len(swing_lows) >= 2:
            if swing_lows[-1]['price'] > swing_lows[-2]['price']:
                msg_low = "스윙 저점이 상승 중입니다."
                return_low = 'uptrend'
            elif swing_lows[-1]['price'] < swing_lows[-2]['price']:
                msg_low = "스윙 저점이 하락 중입니다."
                return_low = 'downtrend'
            else:
                msg_low = "스윙 저점 변화 없음."
        else:
            msg_low = "스윙 저점이 없습니다."

        return return_high, return_low, {"high": msg_high, "low": msg_low}


    def get_previous_high_low(self, ohlcv):
        """
        current_index : 기준 봉 index
        return:
            previous_high (dict or None)
            previous_low  (dict or None)
        """
        current_index = len(ohlcv) - 1
        swing_highs, swing_lows = self.find_swing_points(ohlcv, left=2, right=2) # 단기용(left=3, right=3)

        prev_high = None
        prev_low = None

        for h in reversed(swing_highs):
            if h["index"] < current_index:
                prev_high = h
                break

        for l in reversed(swing_lows):
            if l["index"] < current_index:
                prev_low = l
                break

        return prev_high['price'], prev_low['price']
    
    def get_sorted_by_price(self, swing_list, reverse=True):
        """
        스윙 리스트(dict 리스트)를 price 기준으로 정렬
        swing_list: [{'index': int, 'timestamp': ..., 'price': float}, ...]
        reverse=True면 내림차순(최고가 우선), False면 오름차순
        return: 정렬된 리스트
        """
        return sorted(swing_list, key=lambda x: x["price"], reverse=reverse)

    # 전고점(rolling max) 반환 함수
    def get_prev_high(self, df: pd.DataFrame, window: int = 200, shift: int = 1) -> pd.Series:
        """
        df: OHLCV 데이터프레임
        window: rolling window 크기
        shift: 몇 칸 이전까지 볼지(보통 1)
        return: 전고점 시계열(pd.Series)
        """
        return df['high'].shift(shift).rolling(window=window).max()

    # 전저점(rolling min) 반환 함수
    def get_prev_low(self, df: pd.DataFrame, window: int = 200, shift: int = 1) -> pd.Series:
        """
        df: OHLCV 데이터프레임
        window: rolling window 크기
        shift: 몇 칸 이전까지 볼지(보통 1)
        return: 전저점 시계열(pd.Series)
        """
        return df['low'].shift(shift).rolling(window=window).min()
    

    import pandas as pd
    import numpy as np

    def volume_swing_points(self, df, lookback=3):
        """
        df: DataFrame with 'volume'
        lookback: 좌우 비교 봉 수
        """
        volumes = df['volume'].values
        swing_high = np.zeros(len(df))
        swing_low = np.zeros(len(df))

        for i in range(lookback, len(df) - lookback):
            left = volumes[i-lookback:i]
            right = volumes[i+1:i+1+lookback]

            if volumes[i] > left.max() and volumes[i] > right.max():
                swing_high[i] = volumes[i]

            if volumes[i] < left.min() and volumes[i] < right.min():
                swing_low[i] = volumes[i]

        df['vol_swing_high'] = swing_high
        df['vol_swing_low'] = swing_low
        return df
    
    def volume_trend(self, df):
        """
        거래량 추세 판단
        df: DataFrame with 'vol_swing_high' and 'vol_swing_low'
        """
        df = self.volume_swing_points(df, lookback=3)

        highs = df[df['vol_swing_high'] > 0]['vol_swing_high']
        lows = df[df['vol_swing_low'] > 0]['vol_swing_low']

        if len(highs) < 2 or len(lows) < 2:
            return ""

        hh = highs.iloc[-1] > highs.iloc[-2]
        hl = lows.iloc[-1] > lows.iloc[-2]

        lh = highs.iloc[-1] < highs.iloc[-2]
        ll = lows.iloc[-1] < lows.iloc[-2]

        if hh and hl:
            return "uptrend"

        if lh and ll:
            return "downtrend"

        return "sideways"

    def volume_trend_with_ratio(self, df, swing_lookback=3, trend_lookback=3, ratio_threshold=0.6):
        """
        거래량 스윙포인트 기반 추세 + 비율 기반 조기 신호
        """
        df = self.volume_swing_points(df, lookback=swing_lookback)
        highs = df[df['vol_swing_high'] > 0]['vol_swing_high']
        lows = df[df['vol_swing_low'] > 0]['vol_swing_low']

        # 최근 trend_lookback개만 추출
        recent_highs = highs.iloc[-trend_lookback:]
        recent_lows = lows.iloc[-trend_lookback:]

        # 변화 방향 비율 계산
        high_up = sum(recent_highs.diff().dropna() > 0)
        high_down = sum(recent_highs.diff().dropna() < 0)
        low_up = sum(recent_lows.diff().dropna() > 0)
        low_down = sum(recent_lows.diff().dropna() < 0)

        up_ratio = (high_up + low_up) / (2 * (trend_lookback - 1))
        down_ratio = (high_down + low_down) / (2 * (trend_lookback - 1))

        if up_ratio >= ratio_threshold:
            return "uptrend"
        elif down_ratio >= ratio_threshold:
            return "downtrend"
        else:
            return "sideways"
