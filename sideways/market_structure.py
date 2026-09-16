"""
Market Structure Analysis Module
가격 구조(고점/저점) 분석 및 추세 전환 감지
"""
import logging
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
    
    # (정리 2026-09-17: find_swing_highs/find_swing_lows/detect_trend/
    #  check_structure_break/get_last_swing_points를 여기서 제거했다.
    #  이 다섯 메서드는 서로만 호출하는 닫힌 군집이었고, simple_strategy.py 등
    #  실제 전략 코드에서는 전혀 쓰이지 않는 죽은 코드였다(아래 find_swing_points
    #  기반의 check_trend_by_swing_points/get_previous_high_low만 실제로 쓰임).
    #  두 가지 서로 다른 스윙 탐지 구현이 공존하던 중복도 이걸로 해소됨.

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

        return (
            prev_high['price'] if prev_high else None,
            prev_low['price'] if prev_low else None,
        )
    
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
