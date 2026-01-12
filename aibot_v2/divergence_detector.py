"""
Divergence Detector Module
RSI 다이버전스 감지 모듈
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional, List, Dict


class DivergenceDetector:
    """RSI 다이버전스 감지 클래스"""
    
    def __init__(self, lookback: int = 5, min_rsi_diff: float = 5.0):
        """
        Args:
            lookback: 다이버전스 확인을 위한 과거 캔들 수
            min_rsi_diff: 유효한 다이버전스로 인정할 최소 RSI 차이
        """
        self.lookback = lookback
        self.min_rsi_diff = min_rsi_diff
    
    def find_price_pivots(self, df: pd.DataFrame, pivot_type: str = 'high') -> List[int]:
        """
        가격의 피봇 포인트(고점/저점) 찾기
        
        Args:
            df: OHLCV 데이터프레임
            pivot_type: 'high' 또는 'low'
            
        Returns:
            피봇 인덱스 리스트
        """
        pivots = []
        
        if pivot_type == 'high':
            values = df['high'].values
            compare_func = lambda i, j: values[i] > values[j]
        else:
            values = df['low'].values
            compare_func = lambda i, j: values[i] < values[j]
        
        for i in range(2, len(values) - 2):
            is_pivot = True
            for j in range(1, 3):
                if not compare_func(i, i - j) or not compare_func(i, i + j):
                    is_pivot = False
                    break
            
            if is_pivot:
                pivots.append(i)
        
        return pivots
    
    def find_rsi_pivots(self, rsi_values: np.ndarray, pivot_type: str = 'high') -> List[int]:
        """
        RSI의 피봇 포인트 찾기
        
        Args:
            rsi_values: RSI 값 배열
            pivot_type: 'high' 또는 'low'
            
        Returns:
            피봇 인덱스 리스트
        """
        pivots = []
        
        if pivot_type == 'high':
            compare_func = lambda i, j: rsi_values[i] > rsi_values[j]
        else:
            compare_func = lambda i, j: rsi_values[i] < rsi_values[j]
        
        for i in range(2, len(rsi_values) - 2):
            is_pivot = True
            for j in range(1, 3):
                if not compare_func(i, i - j) or not compare_func(i, i + j):
                    is_pivot = False
                    break
            
            if is_pivot:
                pivots.append(i)
        
        return pivots
    
    def detect_bullish_divergence(self, df: pd.DataFrame, rsi: pd.Series) -> Tuple[bool, Optional[Dict]]:
        """
        강세 다이버전스 감지 (가격 ↓, RSI ↑)
        
        Args:
            df: OHLCV 데이터프레임
            rsi: RSI 시리즈
            
        Returns:
            (다이버전스여부, 상세정보)
        """
        if len(df) < self.lookback + 5:
            return False, None
        
        # 최근 구간만 확인
        recent_df = df.iloc[-self.lookback - 5:].copy()
        recent_rsi = rsi.iloc[-self.lookback - 5:].values
        
        # 가격 저점과 RSI 저점 찾기
        price_lows_idx = self.find_price_pivots(recent_df, 'low')
        rsi_lows_idx = self.find_rsi_pivots(recent_rsi, 'low')
        
        if len(price_lows_idx) < 2 or len(rsi_lows_idx) < 2:
            return False, None
        
        # 최근 2개의 저점 비교
        price_low_1_idx = price_lows_idx[-2]
        price_low_2_idx = price_lows_idx[-1]
        
        # RSI 저점 찾기 (가격 저점과 가까운 시점)
        rsi_low_1_idx = self._find_closest_pivot(rsi_lows_idx, price_low_1_idx)
        rsi_low_2_idx = self._find_closest_pivot(rsi_lows_idx, price_low_2_idx)
        
        if rsi_low_1_idx is None or rsi_low_2_idx is None:
            return False, None
        
        price_low_1 = recent_df['low'].iloc[price_low_1_idx]
        price_low_2 = recent_df['low'].iloc[price_low_2_idx]
        rsi_low_1 = recent_rsi[rsi_low_1_idx]
        rsi_low_2 = recent_rsi[rsi_low_2_idx]
        
        # 강세 다이버전스: 가격은 낮아지고, RSI는 높아짐
        price_lower = price_low_2 < price_low_1
        rsi_higher = rsi_low_2 > rsi_low_1
        rsi_diff = abs(rsi_low_2 - rsi_low_1)
        
        if price_lower and rsi_higher and rsi_diff >= self.min_rsi_diff:
            details = {
                'type': 'bullish',
                'price_low_1': float(price_low_1),
                'price_low_2': float(price_low_2),
                'rsi_low_1': float(rsi_low_1),
                'rsi_low_2': float(rsi_low_2),
                'rsi_diff': float(rsi_diff),
                'strength': 'strong' if rsi_diff > 10 else 'weak'
            }
            return True, details
        
        return False, None
    
    def detect_bearish_divergence(self, df: pd.DataFrame, rsi: pd.Series) -> Tuple[bool, Optional[Dict]]:
        """
        약세 다이버전스 감지 (가격 ↑, RSI ↓)
        
        Args:
            df: OHLCV 데이터프레임
            rsi: RSI 시리즈
            
        Returns:
            (다이버전스여부, 상세정보)
        """
        if len(df) < self.lookback + 5:
            return False, None
        
        # 최근 구간만 확인
        recent_df = df.iloc[-self.lookback - 5:].copy()
        recent_rsi = rsi.iloc[-self.lookback - 5:].values
        
        # 가격 고점과 RSI 고점 찾기
        price_highs_idx = self.find_price_pivots(recent_df, 'high')
        rsi_highs_idx = self.find_rsi_pivots(recent_rsi, 'high')
        
        if len(price_highs_idx) < 2 or len(rsi_highs_idx) < 2:
            return False, None
        
        # 최근 2개의 고점 비교
        price_high_1_idx = price_highs_idx[-2]
        price_high_2_idx = price_highs_idx[-1]
        
        # RSI 고점 찾기 (가격 고점과 가까운 시점)
        rsi_high_1_idx = self._find_closest_pivot(rsi_highs_idx, price_high_1_idx)
        rsi_high_2_idx = self._find_closest_pivot(rsi_highs_idx, price_high_2_idx)
        
        if rsi_high_1_idx is None or rsi_high_2_idx is None:
            return False, None
        
        price_high_1 = recent_df['high'].iloc[price_high_1_idx]
        price_high_2 = recent_df['high'].iloc[price_high_2_idx]
        rsi_high_1 = recent_rsi[rsi_high_1_idx]
        rsi_high_2 = recent_rsi[rsi_high_2_idx]
        
        # 약세 다이버전스: 가격은 높아지고, RSI는 낮아짐
        price_higher = price_high_2 > price_high_1
        rsi_lower = rsi_high_2 < rsi_high_1
        rsi_diff = abs(rsi_high_2 - rsi_high_1)
        
        if price_higher and rsi_lower and rsi_diff >= self.min_rsi_diff:
            details = {
                'type': 'bearish',
                'price_high_1': float(price_high_1),
                'price_high_2': float(price_high_2),
                'rsi_high_1': float(rsi_high_1),
                'rsi_high_2': float(rsi_high_2),
                'rsi_diff': float(rsi_diff),
                'strength': 'strong' if rsi_diff > 10 else 'weak'
            }
            return True, details
        
        return False, None
    
    def _find_closest_pivot(self, pivot_indices: List[int], target_idx: int, max_distance: int = 3) -> Optional[int]:
        """
        목표 인덱스에 가장 가까운 피봇 찾기
        
        Args:
            pivot_indices: 피봇 인덱스 리스트
            target_idx: 목표 인덱스
            max_distance: 최대 허용 거리
            
        Returns:
            가장 가까운 피봇 인덱스 또는 None
        """
        closest = None
        min_dist = float('inf')
        
        for pivot_idx in pivot_indices:
            dist = abs(pivot_idx - target_idx)
            if dist < min_dist and dist <= max_distance:
                min_dist = dist
                closest = pivot_idx
        
        return closest
    
    def detect_all_divergences(self, df: pd.DataFrame, rsi: pd.Series) -> Dict:
        """
        모든 다이버전스 감지
        
        Args:
            df: OHLCV 데이터프레임
            rsi: RSI 시리즈
            
        Returns:
            다이버전스 정보 딕셔너리
        """
        bullish, bullish_details = self.detect_bullish_divergence(df, rsi)
        bearish, bearish_details = self.detect_bearish_divergence(df, rsi)
        
        return {
            'bullish_divergence': bullish,
            'bullish_details': bullish_details,
            'bearish_divergence': bearish,
            'bearish_details': bearish_details,
            'any_divergence': bullish or bearish
        }
