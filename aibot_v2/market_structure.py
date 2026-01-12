"""
Market Structure Analysis Module
가격 구조(고점/저점) 분석 및 추세 전환 감지
"""

import pandas as pd
import numpy as np
from typing import Tuple, List, Optional, Dict


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
        스윙 고점(Swing High) 찾기
        
        Args:
            df: OHLCV 데이터프레임
            
        Returns:
            스윙 고점의 인덱스 리스트
        """
        swing_highs = []
        highs = df['high'].values
        
        for i in range(self.lookback, len(highs) - self.lookback):
            # 좌우 lookback 캔들보다 높은지 확인
            is_high = True
            for j in range(1, self.lookback + 1):
                if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                    is_high = False
                    break
            
            if is_high:
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
    

    def check_structure_break(self, df: pd.DataFrame, current_trend: str, current_price: float = None) -> Tuple[bool, str]:
        """
        추세 구조 붕괴 확인
        
        Args:
            df: OHLCV 데이터프레임
            current_trend: 현재 추세 ('uptrend' or 'downtrend')
            current_price: 실시간 현재가 (기본값: None)
            
        Returns:
            (구조붕괴여부, 전환될추세)
        """
        swing_highs_idx = self.find_swing_highs(df)
        swing_lows_idx = self.find_swing_lows(df)
        
        if len(swing_highs_idx) < 2 or len(swing_lows_idx) < 2:
            return False, current_trend
        
        recent_high = df['high'].iloc[swing_highs_idx[-1]]
        prev_high = df['high'].iloc[swing_highs_idx[-2]]
        recent_low = df['low'].iloc[swing_lows_idx[-1]]
        prev_low = df['low'].iloc[swing_lows_idx[-2]]
                            
        if current_price is None:
            current_price = df['close'].iloc[-1]
        # 상승 추세에서 HL(Higher Low) 붕괴 확인 (실시간 현재가 기준)
        if current_trend == 'uptrend':
            if current_price < prev_low:
                return True, 'downtrend'
        # 하락 추세에서 LH(Lower High) 붕괴 확인 (실시간 현재가 기준)
        elif current_trend == 'downtrend':
            if current_price > prev_high:
                return True, 'uptrend'
        return False, current_trend
    
    
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
