"""
Multi-Timeframe Trend Following Strategy
다중 시간봉 추세 추종 전략
"""

import pandas as pd
import logging
from typing import Dict, Optional, Tuple
from aibot_v2.technical_indicators import (
    get_trend_from_ema,
    get_trend_from_bollinger,
    get_trend_from_rsi,
    combine_trend_signals,
    check_volume_spike,
    check_ema_support,
    detect_ema_crossover,
    check_time_volatility
)
from aibot_v2.market_structure import MarketStructure
from aibot_v2.divergence_detector import DivergenceDetector
from aibot_v2 import technical_indicators
from aibot_v2.color_utils import Colors


logger = logging.getLogger(__name__)

def generate_entry_order(strategy, lower_dfs, indicators, base_df, higher_trend=None, analysis_results=None, tf=None, current_price=None):
    """
    단순 진입 신호 자료 생성 (진입가, 손절가, 익절가)
    Args:
        direction: 'long' 또는 'short'
        df: 진입 신호가 발생한 타임프레임의 데이터프레임
        entry_trigger_df: 트리거용 데이터프레임 (예: 1m)
        config: 설정 dict
    Returns:
        entry_order dict 또는 None
    """
    direction = strategy  # 첫 파라미터만 direction으로 사용
    df = lower_dfs
    entry_trigger_df = indicators
    config = base_df
    entry_order = None
    if current_price is None:
        entry_price = entry_trigger_df['close'].iloc[-1]
    else:
        entry_price = current_price
    if direction == 'long':
        sl_price = df['low'].iloc[-20:].min()
        tp_price = entry_price + (entry_price - sl_price) * config['risk_management']['risk_reward_ratio']
        entry_order = {
            'type': 'LONG',
            'entry_price': float(entry_price),
            'sl_price': float(sl_price),
            'tp_price': float(tp_price),
            'has_signal': True
        }
    elif direction == 'short':
        sl_price = df['high'].iloc[-20:].max()
        tp_price = entry_price - (sl_price - entry_price) * config['risk_management']['risk_reward_ratio']
        entry_order = {
            'type': 'SHORT',
            'entry_price': float(entry_price),
            'sl_price': float(sl_price),
            'tp_price': float(tp_price),
            'has_signal': True
        }
    return entry_order


def fetch_ohlcv_data(exchange, symbol: str, timeframe: str, limit: int = 500, cache=None) -> Optional[pd.DataFrame]:
    """
    OHLCV 데이터 가져오기 (캐시 지원)
    
    Args:
        exchange: CCXT exchange 인스턴스
        symbol: 거래 심볼
        timeframe: 시간봉 (1m, 5m, 15m 등)
        limit: 캔들 개수
        cache: 캐시 객체
        
    Returns:
        OHLCV 데이터프레임 또는 None
    """
    cache_key = f"{symbol}_{timeframe}_{limit}"
    
    # 캐시 확인
    if cache:
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data
    
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        if not ohlcv:
            logger.warning(f"OHLCV 데이터 없음: {symbol} {timeframe}")
            return None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # 캐시에 저장
        if cache:
            cache.set(cache_key, df)
        
        return df
    except Exception as e:
        logger.error(f"OHLCV 데이터 수집 실패: {str(e)}")
        return None


def resample_data(df: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
    """
    1분봉 데이터를 상위 시간봉으로 리샘플링
    
    Args:
        df: 1분봉 데이터프레임
        target_timeframe: 목표 시간봉 (5m, 15m, 1h 등)
        
    Returns:
        리샘플링된 데이터프레임
    """
    try:
        # 시간봉 변환 (5m -> 5min, 15m -> 15min, 1h -> 1H)
        timeframe_map = {
            '1m': '1min',
            '3m': '3min',
            '5m': '5min',
            '15m': '15min',
            '30m': '30min',
            '1h': '1H',
            '4h': '4H',
            '1d': '1D'
        }
        
        resample_rule = timeframe_map.get(target_timeframe, target_timeframe)
        
        resampled = df.resample(resample_rule).agg({
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
        logger.error(f"데이터 리샘플 실패: {str(e)}")
        return df


def _apply_trend_filter(config: Dict, indicators: Dict, higher_trend: str, entry_signal: Dict) -> Dict:
    """
    추세 필터 적용하여 역추세 거래 차단
    
    Args:
        config: 전략 설정
        indicators: 기술적 지표 딕셔너리 (5m 타임프레임)
        higher_trend: 상위 시간봉 추세 ('uptrend' 또는 'downtrend')
        entry_signal: 진입 신호 딕셔너리
        
    Returns:
        {'allowed': bool, 'reason': str}
    """
    trend_config = config['strategy'].get('trend_filter', {})
    
    if not trend_config.get('enable', False):
        return {'allowed': True, 'reason': ''}
    
    if not entry_signal.get('has_signal'):
        return {'allowed': True, 'reason': ''}
    
    # 5m EMA 값 가져오기 (상위 시간봉의 추세)
    ema_fast = indicators['ema_fast'].iloc[-1]
    ema_medium = indicators['ema_medium'].iloc[-1]
    ema_slow = indicators['ema_slow'].iloc[-1]
    
    # EMA 배열로 5m 추세 판단
    is_strong_uptrend = bool(ema_fast > ema_medium and ema_medium > ema_slow)
    is_strong_downtrend = bool(ema_fast < ema_medium and ema_medium < ema_slow)
    
    # 추세 강도 계산 (EMA 간격으로 측정)
    min_strength = trend_config.get('min_trend_strength', 0.002)  # 0.2%
    
    # higher_trend가 'uptrend'이면 LONG, 'downtrend'이면 SHORT
    
    if is_strong_downtrend:
        trend_strength = (ema_slow - ema_fast) / ema_slow
        logger.info(f"[추세 필터] 5m 하락 추세 감지 (EMA 9:{ema_fast:.4f} < 20:{ema_medium:.4f} < 30:{ema_slow:.4f}, 강도:{trend_strength:.2%})")
        if trend_strength >= min_strength:
            # 강한 하락 추세 → LONG 차단
            if trend_config.get('block_counter_trend', True):
                if higher_trend == 'uptrend':  # LONG 시도
                    return {
                        'allowed': False,
                        'reason': f'5m 강한 하락 추세에서 LONG 차단 (강도: {trend_strength:.2%})'
                    }
    
    elif is_strong_uptrend:
        trend_strength = (ema_fast - ema_slow) / ema_slow
        logger.info(f"[추세 필터] 5m 상승 추세 감지 (EMA 9:{ema_fast:.4f} > 20:{ema_medium:.4f} > 30:{ema_slow:.4f}, 강도:{trend_strength:.2%})")
        if trend_strength >= min_strength:
            # 강한 상승 추세 → SHORT 차단
            if trend_config.get('block_counter_trend', True):
                if higher_trend == 'downtrend':  # SHORT 시도
                    return {
                        'allowed': False,
                        'reason': f'5m 강한 상승 추세에서 SHORT 차단 (강도: {trend_strength:.2%})'
                    }
    
    return {'allowed': True, 'reason': ''}


class TrendFollowingStrategy:
    """다중 시간봉 추세 추종 전략 클래스"""
    
    def __init__(self, config: Dict):
        """
        Args:
            config: 설정 딕셔너리
        """
        self.config = config
        self.market_structure = MarketStructure(
            lookback=config['strategy']['price_structure']['lookback_candles'],
            min_swing_size=config['strategy']['price_structure']['min_swing_size']
        )
        self.divergence_detector = DivergenceDetector(
            lookback=config['strategy']['rsi']['divergence_lookback']
        )
    
    def analyze_higher_timeframe(self, higher_df: pd.DataFrame, indicators: Dict) -> Dict:
        """
        상위 시간봉 분석 (추세 판단)
        
        Args:
            higher_df: 상위 시간봉 데이터프레임
            indicators: 계산된 지표 딕셔너리
            
        Returns:
            상위 시간봉 분석 결과
        """
        if len(higher_df) < 20:
            return {'trend': 'neutral', 'confidence': 0, 'reason': 'insufficient_data'}
        
        close = higher_df['close'].iloc[-1]
        ema_fast = indicators['ema_fast'].iloc[-1]
        ema_medium = indicators['ema_medium'].iloc[-1]
        ema_slow = indicators['ema_slow'].iloc[-1]
        bb_upper = indicators['bb_upper'].iloc[-1]
        bb_middle = indicators['bb_middle'].iloc[-1]
        bb_lower = indicators['bb_lower'].iloc[-1]
        rsi = indicators['rsi'].iloc[-1]
        
        # 가격 구조 분석
        trend_structure, structure_details = self.market_structure.detect_trend(higher_df)
        
        # 각 지표별 추세 판단
        trend_ema = get_trend_from_ema(close, ema_fast, ema_medium, ema_slow)
        trend_bb = get_trend_from_bollinger(close, bb_upper, bb_middle, bb_lower)
        trend_rsi = get_trend_from_rsi(
            rsi,
            self.config['strategy']['rsi']['overbought'],
            self.config['strategy']['rsi']['oversold']
        )
        
        # 지표 조합
        combined_trend, agreement_count = combine_trend_signals(
            trend_ema, trend_bb, trend_rsi,
            min_agreement=self.config['strategy']['trend_indicators']['min_agreement']
        )
        
        # 신뢰도 계산
        confidence = agreement_count / 3.0  # 최대 3개 지표
        
        return {
            'trend': combined_trend,
            'confidence': confidence,
            'trend_ema': trend_ema,
            'trend_bb': trend_bb,
            'trend_rsi': trend_rsi,
            'trend_structure': trend_structure,
            'structure_details': structure_details,
            'rsi': float(rsi),
            'price': float(close),
            'ema_fast': float(ema_fast),
            'ema_medium': float(ema_medium),
            'ema_slow': float(ema_slow)
        }
    
    def check_entry_signal(self, lower_df: pd.DataFrame, indicators: Dict, higher_trend: str, higher_indicators: Dict = None) -> Dict:
        """
        하위 시간봉에서 진입 신호 확인
        
        Args:
            lower_df: 하위 시간봉 데이터프레임
            indicators: 계산된 지표 딕셔너리 (1분봉)
            higher_trend: 상위 시간봉 추세
            higher_indicators: 상위 시간봉 지표 딕셔너리 (5분봉, 볼린저 밴드용)
            
        Returns:
            진입 신호 정보
        """
        if len(lower_df) < 10:
            return {'has_signal': False, 'reason': 'insufficient_data'}

        # 진입 모드 분기: config['strategy']['entry_mode']
        entry_mode = self.config['strategy'].get('entry_mode', 'conservative')
        # 필요한 지표 미리 정의
        close = lower_df['close'].iloc[-1]
        ema_fast = indicators['ema_fast'].iloc[-1]
        ema_medium = indicators['ema_medium'].iloc[-1]
        ema_slow = indicators['ema_slow'].iloc[-1]

        if entry_mode == 'aggressive':
            # 추세 전환 즉시 진입 (EMA 정렬만 체크)
            if higher_trend == 'uptrend' and ema_fast > ema_medium > ema_slow:
                logger.info(f"★ [공격적모드] 추세전환 즉시 LONG 진입 신호 감지 (EMA정렬)")
                return {
                    'has_signal': True,
                    'type': 'LONG',
                    'entry_price': float(close),
                    'sl_price': float(close) * 0.98,  # 임시 SL
                    'tp_price': float(close) * 1.02   # 임시 TP
                }
            elif higher_trend == 'downtrend' and ema_fast < ema_medium < ema_slow:
                logger.info(f"★ [공격적모드] 추세전환 즉시 SHORT 진입 신호 감지 (EMA정렬)")
                return {
                    'has_signal': True,
                    'type': 'SHORT',
                    'entry_price': float(close),
                    'sl_price': float(close) * 1.02,  # 임시 SL
                    'tp_price': float(close) * 0.98   # 임시 TP
                }
            else:
                return {'has_signal': False, 'reason': 'no_trend_change'}
        
        # 추세 필터 적용 (역추세 거래 차단)
        trend_filter_result = _apply_trend_filter(self.config, indicators, higher_trend, {'has_signal': True})
        if not trend_filter_result['allowed']:
            logger.info(f"⊗ {trend_filter_result['reason']}")
            return {'has_signal': False, 'reason': 'trend_filter_blocked', 'filter_reason': trend_filter_result['reason']}
        
        close = lower_df['close'].iloc[-1]
        volume = lower_df['volume'].iloc[-1]
        rsi = indicators['rsi'].iloc[-1]
        ema_fast = indicators['ema_fast'].iloc[-1]
        ema_medium = indicators['ema_medium'].iloc[-1]
        volume_ma = indicators['volume_ma'].iloc[-1]
        
        # 볼린저 밴드는 5분봉 기준 사용 (더 안정적인 변동성 측정)
        if higher_indicators is not None:
            bb_upper = higher_indicators['bb_upper'].iloc[-1]
            bb_lower = higher_indicators['bb_lower'].iloc[-1]
        else:
            # fallback: 1분봉 사용
            bb_upper = indicators['bb_upper'].iloc[-1]
            bb_lower = indicators['bb_lower'].iloc[-1]
        
        # 1. 가격 구조 확인 (시장 구조 붕괴)
        structure_break, new_trend = self.market_structure.check_structure_break(
            lower_df, higher_trend
        )
        
        # 2. RSI 다이버전스 확인
        divergences = self.divergence_detector.detect_all_divergences(lower_df, indicators['rsi'])
        
        # 3. 거래량 확인
        volume_spike = check_volume_spike(
            lower_df['volume'],
            indicators['volume_ma'],
            self.config['strategy']['volume']['volume_spike_threshold']
        )
        
        # 4. EMA 지지/저항 확인
        ema_support = check_ema_support(close, ema_fast, ema_medium, tolerance=0.005)
        
        # 5. RSI 과매수/과매도 필터 (극단적 구간 진입 차단)
        rsi_config = self.config['strategy']['rsi']
        rsi_overbought = rsi_config['overbought']
        rsi_oversold = rsi_config['oversold']
        
        # 1분봉 RSI 필터
        if higher_trend == 'uptrend' and rsi > rsi_overbought:
            return {'has_signal': False, 'reason': 'rsi_overbought', 'rsi': float(rsi), 'timeframe': '1m'}
        if higher_trend == 'downtrend' and rsi < rsi_oversold:
            return {'has_signal': False, 'reason': 'rsi_oversold', 'rsi': float(rsi), 'timeframe': '1m'}

        # === RSI 반전 진입 신호 추가 (1분봉 기준) ===
        # 과매도(30 이하)에서 반등(직전봉보다 상승) → LONG 진입 신호
        # 과매수(70 이상)에서 하락(직전봉보다 하락) → SHORT 진입 신호
        if len(indicators['rsi']) > 1:
            prev_rsi = indicators['rsi'].iloc[-2]
            # LONG: 과매도에서 반등
            if higher_trend == 'uptrend' and prev_rsi <= rsi_oversold and rsi > prev_rsi:
                logger.info(f"★ [RSI반전] 과매도({prev_rsi:.2f})→상승({rsi:.2f}) LONG 진입 신호")
                return {
                    'has_signal': True,
                    'type': 'LONG',
                    'entry_price': float(close),
                    'sl_price': float(close) * 0.98,
                    'tp_price': float(close) * 1.02,
                    'reason': 'rsi_oversold_rebound',
                    'rsi': float(rsi)
                }
            # SHORT: 과매수에서 하락 반전
            if higher_trend == 'downtrend' and prev_rsi >= rsi_overbought and rsi < prev_rsi:
                logger.info(f"★ [RSI반전] 과매수({prev_rsi:.2f})→하락({rsi:.2f}) SHORT 진입 신호")
                return {
                    'has_signal': True,
                    'type': 'SHORT',
                    'entry_price': float(close),
                    'sl_price': float(close) * 1.02,
                    'tp_price': float(close) * 0.98,
                    'reason': 'rsi_overbought_reversal',
                    'rsi': float(rsi)
                }
        
        # 5분봉(상위 시간봉) RSI 필터 - 추세 소진 구간 진입 차단
        if higher_indicators is not None and 'rsi' in higher_indicators:
            higher_rsi = higher_indicators['rsi'].iloc[-1]
            
            # LONG 진입 시: 5분봉 RSI가 과매수(70 이상)면 상승 추세 소진 -> 진입 차단
            if higher_trend == 'uptrend' and higher_rsi > rsi_overbought:
                return {
                    'has_signal': False, 
                    'reason': 'higher_rsi_overbought', 
                    'rsi': float(higher_rsi),
                    'timeframe': '5m'
                }
            
            # SHORT 진입 시: 5분봉 RSI가 과매도(30 이하)면 하락 추세 소진 -> 진입 차단
            if higher_trend == 'downtrend' and higher_rsi < rsi_oversold:
                return {
                    'has_signal': False, 
                    'reason': 'higher_rsi_oversold', 
                    'rsi': float(higher_rsi),
                    'timeframe': '5m'
                }
        
        # 6. 볼린져 밴드 폭 필터 (변동성 확인) - 비활성화 (너무 많은 신호 차단)
        # bb_width = (bb_upper - bb_lower) / close  # 상대적 폭 (%)
        # tp_ratio = self.config['risk_management']['tp_ratio']
        # 
        # # 익절가와 동일한 폭 필요 (변동성 부족 시 진입 차단)
        # min_bb_width = tp_ratio
        # if bb_width < min_bb_width:
        #     return {
        #         'has_signal': False, 
        #         'reason': 'insufficient_volatility', 
        #         'bb_width': float(bb_width),
        #         'min_required': float(min_bb_width),
        #         'tp_ratio': float(tp_ratio)
        #     }
        
        # 7. ADX 필터 (추세 강도 확인) - Option 3 - 일시적으로 비활성화
        # adx = indicators['adx'].iloc[-1] if len(indicators['adx']) > 0 else 0
        # adx_threshold = self.config['risk_management'].get('adx_threshold', 25)
        # 
        # # ADX가 임계값 이하면 약한 추세/횡보로 판단하여 진입 차단
        # if adx < adx_threshold:
        #     return {'has_signal': False, 'reason': 'weak_trend_adx', 'adx': float(adx)}
        
        # 8. 시간대 변동성 필터 (07:00-09:30 실패 구간 대응) - 비활성화 (너무 많은 신호 차단)
        # current_time = signal_df.index[-1]
        # prev_close = signal_df['close'].iloc[-2] if len(signal_df) >= 2 else close
        # 
        # if not check_time_volatility(current_time, close, prev_close, threshold=0.005):
        #     return {'has_signal': False, 'reason': 'low_volatility_risky_time'}
        
        # 9. EMA 크로스오버 감지 (추세 전환 조기 포착)
        # 2봉 확인으로 크로스오버 검증 (3봉은 너무 엄격하여 일시적으로 2봉으로 복원)
        if len(indicators['ema_fast']) >= 2:
            ema_fast_prev = indicators['ema_fast'].iloc[-2]
            ema_medium_prev = indicators['ema_medium'].iloc[-2]
            crossover = detect_ema_crossover(ema_fast_prev, ema_medium_prev, ema_fast, ema_medium)
        else:
            ema_fast_prev = ema_fast
            ema_medium_prev = ema_medium
            crossover = None
        
        # 10. Pullback 진입 체크 (추세 중 되돌림)
        # 상승 추세: 가격이 EMA 9 근처까지 되돌아오면 좋은 진입점
        pullback_entry = False
        if higher_trend == 'uptrend':
            # 가격이 EMA 9~20 사이에 있으면 pullback (0.1% 버퍼)
            pullback_entry = ema_medium <= close <= ema_fast * 1.001
        elif higher_trend == 'downtrend':
            # 가격이 EMA 9~20 사이에 있으면 pullback (0.1% 버퍼)
            pullback_entry = ema_fast * 0.999 <= close <= ema_medium
        
        # 11. EMA 간격 확인 (추세 강도)
        ema_separation = abs(ema_fast - ema_medium) / ema_medium
        ema_expanding = abs(ema_fast - ema_medium) > abs(ema_fast_prev - ema_medium_prev)
        
        # 강한 추세: 0.01% 이상 벌어져 있고 확장 중 OR 크로스오버 발생
        strong_trend = (ema_separation > 0.0001 and ema_expanding) or (crossover is not None)
        
        # 1분봉 EMA 간격 로그 출력
        logger.info(f"[1m EMA 간격] EMA9:{ema_fast:.4f}, EMA20:{ema_medium:.4f}, 간격:{ema_separation*100:.3f}%, 확장:{'✓' if ema_expanding else '✗'}, 강한추세:{'✓' if strong_trend else '✗'}")
        
        signal_conditions = {
            'structure_break': structure_break,
            'divergence': divergences['any_divergence'],
            'volume_spike': volume_spike,
            'ema_support': ema_support,
            'strong_trend': strong_trend,
            'pullback_entry': pullback_entry,
            'ema_crossover': crossover is not None
        }
        
        # Config 기반 필수 조건 확인
        entry_config = self.config['strategy']['entry_confirmation']
        required_conditions = []
        
        if entry_config.get('require_volume_spike', True):
            required_conditions.append(signal_conditions['volume_spike'])
        if entry_config.get('require_ema_support', False):
            required_conditions.append(signal_conditions['ema_support'])
        if entry_config.get('require_higher_low', False):
            # structure_break는 higher_low 개념과 유사
            required_conditions.append(signal_conditions['structure_break'])
        
        # 필수 조건 확인 - 다이버전스/구조전환 우선순위 로직
        active_signals = sum(signal_conditions.values())
        
        # 다이버전스나 구조 전환이 있으면 강력한 신호로 간주
        has_priority_signal = signal_conditions['divergence'] or signal_conditions['structure_break']
        
        # 강한추세 + EMA지지 핵심 조합 확인
        has_core_combo = signal_conditions['strong_trend'] and signal_conditions['ema_support']
        
        if has_core_combo:
            # 핵심 조합(강한추세 + EMA지지)이 있으면 즉시 진입 허용
            has_signal = True
        elif has_priority_signal:
            # 우선순위 신호가 있으면: 2개 신호면 진입 가능
            has_signal = active_signals >= 2
        else:
            # 일반 경우: 2개 신호 필요 (완화됨)
            has_required = all(required_conditions) if required_conditions else True
            has_signal = has_required and active_signals >= 2
        
        return {
            'has_signal': has_signal,
            'active_signals': active_signals,
            'signal_conditions': signal_conditions,
            'divergences': divergences,
            'structure_break': structure_break,
            'price': float(close),
            'rsi': float(rsi),
            'volume_spike': volume_spike
        }
    
    def generate_long_entry(self, lower_df: pd.DataFrame, indicators: Dict, entry_trigger_df: pd.DataFrame) -> Optional[Dict]:
        """
        롱 진입 신호 생성
        
        Args:
            lower_df: 하위 시간봉 데이터프레임
            indicators: 계산된 지표 딕셔너리
            entry_trigger_df: 진입 트리거 시간봉 (1m)
            
        Returns:
            진입 정보 또는 None
        """
        if len(lower_df) < 5 or len(entry_trigger_df) < 5:
            return None
        
        # 진입 트리거 가격
        entry_price = entry_trigger_df['close'].iloc[-1]
        
        # 최근 저점 (손절매 기준)
        last_swing = self.market_structure.get_last_swing_points(lower_df)
        
        if last_swing['last_swing_low'] is None:
            # 스윙 저점이 없으면 최근 낮은 가격 사용
            sl_price = lower_df['low'].iloc[-20:].min()
        else:
            sl_price = last_swing['last_swing_low']
        
        # SL이 너무 가깝거나 멀면 조정
        sl_ratio = abs(entry_price - sl_price) / entry_price
        min_sl = self.config['risk_management']['sl_ratio'] * 0.3
        max_sl = self.config['risk_management']['sl_ratio'] * 2.5
        
        if sl_ratio < min_sl:
            # SL이 너무 가까우면 최소 SL 사용
            sl_price = entry_price * (1 - min_sl)
        elif sl_ratio > max_sl:
            # SL이 너무 멀면 최대 SL 사용
            sl_price = entry_price * (1 - max_sl)
        
        # TP 계산
        tp_mode = self.config['risk_management'].get('tp_mode', 'fixed')
        
        if tp_mode == 'hybrid':
            # Hybrid 모드: 고정 TP + 상위 추세 반전 시 조기청산
            tp_ratio = self.config['risk_management']['tp_ratio']
            tp_price = entry_price * (1 + tp_ratio)
            tp_distance = entry_price * tp_ratio
        else:
            # Fixed 또는 Trend Change 모드: SL 기반 RR 비율
            sl_distance = entry_price - sl_price
            tp_price = entry_price + (sl_distance * self.config['risk_management']['risk_reward_ratio'])
            tp_distance = tp_price - entry_price
        
        return {
            'type': 'LONG',
            'entry_price': float(entry_price),
            'sl_price': float(sl_price),
            'tp_price': float(tp_price),
            'sl_distance': float(entry_price - sl_price),
            'tp_distance': float(tp_distance),
            'risk_reward_ratio': self.config['risk_management']['risk_reward_ratio'],
            'tp_mode': tp_mode,
            # 표준 키도 함께 제공해 후속 로깅에서 혼동을 줄임
            'stop_loss': float(sl_price),
            'take_profit': float(tp_price),
            'tp_ratio': float(abs(tp_price - entry_price) / entry_price),
            'sl_ratio': float(abs(entry_price - sl_price) / entry_price)
        }
    
    def generate_short_entry(self, lower_df: pd.DataFrame, indicators: Dict, entry_trigger_df: pd.DataFrame) -> Optional[Dict]:
        """
        숏 진입 신호 생성
        
        Args:
            lower_df: 하위 시간봉 데이터프레임
            indicators: 계산된 지표 딕셔너리
            entry_trigger_df: 진입 트리거 시간봉 (1m)
            
        Returns:
            진입 정보 또는 None
        """
        if len(lower_df) < 5 or len(entry_trigger_df) < 5:
            return None
        
        # 진입 트리거 가격
        entry_price = entry_trigger_df['close'].iloc[-1]
        
        # 최근 고점 (손절매 기준)
        last_swing = self.market_structure.get_last_swing_points(lower_df)
        
        if last_swing['last_swing_high'] is None:
            # 스윙 고점이 없으면 최근 높은 가격 사용
            sl_price = lower_df['high'].iloc[-20:].max()
        else:
            sl_price = last_swing['last_swing_high']
        
        # SL이 너무 가깝거나 멀면 조정
        sl_ratio = abs(sl_price - entry_price) / entry_price
        min_sl = self.config['risk_management']['sl_ratio'] * 0.3
        max_sl = self.config['risk_management']['sl_ratio'] * 2.5
        
        if sl_ratio < min_sl:
            # SL이 너무 가까우면 최소 SL 사용
            sl_price = entry_price * (1 + min_sl)
        elif sl_ratio > max_sl:
            # SL이 너무 멀면 최대 SL 사용
            sl_price = entry_price * (1 + max_sl)
        
        # TP 계산
        tp_mode = self.config['risk_management'].get('tp_mode', 'fixed')
        
        if tp_mode == 'hybrid':
            # Hybrid 모드: 고정 TP + 상위 추세 반전 시 조기청산
            tp_ratio = self.config['risk_management']['tp_ratio']
            tp_price = entry_price * (1 - tp_ratio)
            tp_distance = entry_price * tp_ratio
        else:
            # Fixed 또는 Trend Change 모드: SL 기반 RR 비율
            sl_distance = sl_price - entry_price
            tp_price = entry_price - (sl_distance * self.config['risk_management']['risk_reward_ratio'])
            tp_distance = entry_price - tp_price
        
        return {
            'type': 'SHORT',
            'entry_price': float(entry_price),
            'sl_price': float(sl_price),
            'tp_price': float(tp_price),
            'sl_distance': float(sl_price - entry_price),
            'tp_distance': float(tp_distance),
            'risk_reward_ratio': self.config['risk_management']['risk_reward_ratio'],
            'tp_mode': tp_mode,
            # 표준 키도 함께 제공해 후속 로깅에서 혼동을 줄임
            'stop_loss': float(sl_price),
            'take_profit': float(tp_price),
            'tp_ratio': float(abs(entry_price - tp_price) / entry_price),
            'sl_ratio': float(abs(sl_price - entry_price) / entry_price)
        }
    
    def check_trailing_stop_conditions(self, current_price: float, entry_price: float, 
                                      highest_price: float, position_type: str) -> Tuple[bool, Optional[float]]:
        """
        트레일링 스탑 조건 확인
        
        Args:
            current_price: 현재 가격
            entry_price: 진입 가격
            highest_price: 진입 후 최고 도달 가격 (롱) 또는 최저 도달 가격 (숏)
            position_type: 포지션 타입 ('LONG' 또는 'SHORT')
            
        Returns:
            (트레일링스탑활성화여부, 트레일링스탑가격)
        """
        if not self.config['risk_management']['use_trailing_stop']:
            return False, None
        
        activation = self.config['risk_management']['trailing_stop_activation']
        distance = self.config['risk_management']['trailing_stop_distance']
        
        if position_type == 'LONG':
            # 롱: 진입 후 최고가 대비 activation만큼 상승했으면 트레일링 스탑 활성화
            profit_ratio = (highest_price - entry_price) / entry_price
            
            if profit_ratio >= activation:
                # 트레일링 스탑 가격: 최고가에서 distance만큼 아래
                trailing_stop_price = highest_price * (1 - distance)
                
                # 현재 가격이 트레일링 스탑보다 높으면 손절
                if current_price <= trailing_stop_price:
                    return True, trailing_stop_price
        
        elif position_type == 'SHORT':
            # 숏: 진입 후 최저가 대비 activation만큼 하락했으면 트레일링 스탑 활성화
            profit_ratio = (entry_price - highest_price) / entry_price
            
            if profit_ratio >= activation:
                # 트레일링 스탑 가격: 최저가에서 distance만큼 위
                trailing_stop_price = highest_price * (1 + distance)
                
                # 현재 가격이 트레일링 스탑보다 낮으면 손절
                if current_price >= trailing_stop_price:
                    return True, trailing_stop_price
        
        return False, None


def determine_trend(exchange, symbol: str, config: Dict, cache=None, current_trend=None) -> Optional[str]:
    """
    추세 결정 (추세 전환 반영 후 최종 판단) 및 진입여부 판단
    
    Args:
        exchange: CCXT exchange 인스턴스
        symbol: 거래 심볼
        config: 설정 딕셔너리
        cache: 캐시 객체
        current_trend: 현재 추세 상태 ('uptrend', 'downtrend', None)
        
    Returns:
        new_trend : 변경된 추세 ('uptrend', 'downtrend', None)
        entry_key : 진입여부 키
        close_key : 청산여부 키
    """
    try:
        # close 변수는 항상 할당되도록 기본값 지정 (최신 higher_df가 없을 경우 current_price 사용)
        close = None
        higher_timeframe = config['strategy']['timeframes']['higher_trend'][0] if isinstance(config['strategy']['timeframes']['higher_trend'], list) else config['strategy']['timeframes']['higher_trend']
        lower_timeframe = config['strategy']['timeframes']['lower_signal'][0] if isinstance(config['strategy']['timeframes']['lower_signal'], list) else config['strategy']['timeframes']['lower_signal']

        # 실시간 현재가 조회 (거래소 ticker 사용)
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
        except Exception as e:
            logger.warning(f"실시간 현재가 조회 실패: {e}")
            current_price = l_close_price.iloc[-1]  # fallback: 1분봉 종가

        logger.info(f"[추세 확인 시작] {higher_timeframe}봉/{lower_timeframe}봉... 현재가: {current_price}")

        # 데이터 준비
        higher_df = fetch_ohlcv_data(exchange, symbol, higher_timeframe, limit=100, cache=cache)
        lower_df = fetch_ohlcv_data(exchange, symbol, lower_timeframe, limit=100, cache=cache)
        if higher_df is None or len(higher_df) < 50 or lower_df is None or len(lower_df) < 50:
            logger.warning("데이터 부족으로 추세 결정 불가")
            return None, None, None
        # close 기본값 할당 (최신 higher_df가 있으면 사용, 없으면 current_price)
        try:
            close = higher_df['close'].iloc[-1]
        except Exception:
            close = current_price

        import copy  # 안전한 config 복사를 위해 필요
        # config 전체를 깊은 복사 후 trend_ema 파라미터만 덮어쓰기
        trend_config = copy.deepcopy(config)
        # 상위봉(추세)에는 trend_ema, 하위봉(신호)에는 signal_ema를 각각 할당
        trend_config['strategy']['ema'] = dict(config['strategy']['trend_ema'])
        trend_config['strategy']['ema']['ema_fast'] = trend_config['strategy']['ema']['fast']
        trend_config['strategy']['ema']['ema_medium'] = trend_config['strategy']['ema']['medium']
        trend_config['strategy']['ema']['ema_slow'] = trend_config['strategy']['ema']['slow']
        higher_ind = technical_indicators.calculate_all_indicators(higher_df, trend_config)

        trend_config['strategy']['ema'] = dict(config['strategy']['signal_ema'])
        trend_config['strategy']['ema']['ema_fast'] = trend_config['strategy']['ema']['fast']
        trend_config['strategy']['ema']['ema_medium'] = trend_config['strategy']['ema']['medium']
        trend_config['strategy']['ema']['ema_slow'] = trend_config['strategy']['ema']['slow']
        lower_ind = technical_indicators.calculate_all_indicators(lower_df, trend_config)

        #higher_volume = technical_indicators.calculate_volume_ma_series(higher_df, config)
        #logger.info(f"거래량[{higher_timeframe}] 지표 계산 완료: {higher_volume['volume_ma'].iloc[-3:]} > {higher_volume['volume_ma'].iloc[-2:]} > {higher_volume['volume'].iloc[-1]}")


        # 1. 구조 붕괴 체크
        from aibot_v2.market_structure import MarketStructure
        ms = MarketStructure()
        # uptrend/downtrend 가정으로 각각 체크
        structure_break_up, _ = ms.check_structure_break(higher_df, 'uptrend', current_price=current_price)
        structure_break_down, _ = ms.check_structure_break(higher_df, 'downtrend', current_price=current_price)
        logger.info(f"[구조붕괴] uptrend: {structure_break_up}, downtrend: {structure_break_down}")

        # 2. EMA 정렬 체크
        h_ema_fast = higher_ind['ema_fast'].iloc[-1]
        h_ema_medium = higher_ind['ema_medium'].iloc[-1]
        h_ema_slow = higher_ind['ema_slow'].iloc[-1]
        ema_up = bool(h_ema_fast > h_ema_medium and h_ema_medium > h_ema_slow)    # 상승 정렬
        ema_down = bool(h_ema_fast < h_ema_medium and h_ema_medium < h_ema_slow)  # 하락 정렬
        logger.info(f"[EMA정렬] uptrend: {ema_up}, downtrend: {ema_down}")

        # 3. 볼린저밴드 위치 (상위/하위 차트) - 실시간 현재가 기준
        h_close_price = higher_df['close']
        h_bb_upper, h_bb_middle, h_bb_lower = technical_indicators.calculate_bollinger_bands(h_close_price)
        l_close_price = lower_df['close']
        l_bb_upper, l_bb_middle, l_bb_lower = technical_indicators.calculate_bollinger_bands(l_close_price)

        h_bb_up = current_price > h_bb_middle.iloc[-1]
        h_bb_down = current_price < h_bb_middle.iloc[-1]
        logger.info(f"[BB-상위] uptrend: {h_bb_up}, downtrend: {h_bb_down} (현재가: {current_price:5f}, 중단선: {h_bb_middle.iloc[-1]:5f})")

        l_bb_up = current_price > l_bb_middle.iloc[-1]
        l_bb_down = current_price < l_bb_middle.iloc[-1]
        logger.info(f"[BB-하위] uptrend: {l_bb_up}, downtrend: {l_bb_down} (현재가: {current_price:5f}, 중단선: {l_bb_middle.iloc[-1]:5f})")
        
        # 4. RSI 신호 (추세 반전 신호 감지 전용)
        h_rsi_signal = technical_indicators.detect_rsi_trend_reversal(higher_ind['rsi'], h_close_price, timeframe=higher_timeframe)
        l_rsi_signal = technical_indicators.detect_rsi_trend_reversal(lower_ind['rsi'], lower_df['close'], timeframe=lower_timeframe)

        # 한글 매핑
        rsi_kor_map = {
            'RSI_ovrsold_brkout': '과매도 돌파',
            'RSI_bull_dvrgence' : '강세 다이버전스',
            'RSI_mid_brkout'    : '50선 상향돌파',
            'RSI_ovrbght_brkdn' : '과매수 이탈',
            'RSI_bear_dvrgence' : '약세 다이버전스',
            'RSI_mid_brkdn'     : '50선 하락이탈',
        }
        def rsi_signal_to_kor(signal_dict):
            return {rsi_kor_map.get(k, k): v for k, v in signal_dict.items()}

        logger.info(f"[RSI] {higher_timeframe}: {rsi_signal_to_kor(h_rsi_signal)}")
        logger.info(f"[RSI] {lower_timeframe}: {rsi_signal_to_kor(l_rsi_signal)}")

        # 5. 거래량 급증
        h_vol_ma = technical_indicators.calculate_volume_ma(higher_df['volume'])
        h_vol_spike = technical_indicators.check_volume_spike(higher_df['volume'], h_vol_ma)
        l_vol_ma = technical_indicators.calculate_volume_ma(lower_df['volume'])
        l_vol_spike = technical_indicators.check_volume_spike(lower_df['volume'], l_vol_ma)
        logger.info(f"[거래량 {higher_timeframe}] {h_vol_spike}")
        logger.info(f"[거래량 {lower_timeframe}] {l_vol_spike}")

        # 6. 다중 시간대 비교 (1m/5m EMA 정렬 일치)
        l_ema_fast = lower_ind['ema_fast'].iloc[-1]
        l_ema_medium = lower_ind['ema_medium'].iloc[-1]
        l_ema_slow = lower_ind['ema_slow'].iloc[-1]
        ema_1m_up = l_ema_fast > l_ema_medium > l_ema_slow
        ema_1m_down = l_ema_fast < l_ema_medium < l_ema_slow
        multi_tf_up = ema_up and ema_1m_up
        multi_tf_down = ema_down and ema_1m_down
        logger.info(f"[다중TF] uptrend: {multi_tf_up}, downtrend: {multi_tf_down}")

        # 7. 상위 추세 판단 시작
        logger.info(f"[현재추세] : {current_trend} ")

        # 7-1. 1차 상위 추세 지표 셋팅 : 상위 분봉 지표 기반(구조 정렬 + EMA 정렬 + 볼린저 밴드 위치 + 다중TF)
        # 1분봉 RSI 반전 신호도 1차 추세 판단에 포함
        up_conds = [not bool(structure_break_up), bool(ema_up), bool(h_bb_up), bool(multi_tf_up), bool(h_rsi_signal.get('RSI_ovrsold_brkout', False)), bool(l_rsi_signal.get('RSI_ovrsold_brkout', False))]
        down_conds = [not bool(structure_break_down), bool(ema_down), bool(h_bb_down), bool(multi_tf_down), bool(h_rsi_signal.get('RSI_ovrbght_brkdn', False)), bool(l_rsi_signal.get('RSI_ovrbght_brkdn', False))]

        up_count = sum(up_conds)
        down_count = sum(down_conds)

        logger.info(f"[1차 상승] 구조정렬 + EMA정렬 + 볼린저밴드 위치 + 다중TF + RSI반전 {up_conds} ({up_count})")
        logger.info(f"[1차 하락] 구조정렬 + EMA정렬 + 볼린저밴드 위치 + 다중TF + RSI반전 {down_conds} ({down_count})")

        # 7-2. 1차 상위 추세 판단
        return_trend = None 
        if up_count > down_count and up_count >= 3:
            logger.info(f"{Colors.GREEN}🟢 1차 추세 판단 : 상승{Colors.END}")   
            return_trend = "uptrend"
        elif down_count > up_count and down_count >= 3:
            logger.info(f"{Colors.RED}🔴 1차 추세 판단 : 하락{Colors.END}")
            return_trend = "downtrend"
        else:
            logger.info("⚪ 1차 추세 판단 : 미결정")

        # 7-3. 1차 상위 추세 보완 : (구조붕괴X + RSI과매수/과매도 돌파)
        if structure_break_up == False and h_rsi_signal.get('RSI_ovrsold_brkout', False):
            logger.info(f"{Colors.GREEN}🟢 1차 추세 보완 : 상승 (구조붕괴X + RSI과매도돌파){Colors.END}")   
            return_trend = "uptrend"
        elif structure_break_down == False and h_rsi_signal.get('RSI_ovrbght_brkdn', False):
            logger.info(f"{Colors.RED}🔴 1차 추세 보완 : 하락 (구조붕괴X + RSI과매수이탈){Colors.END}")
            return_trend = "downtrend"
        else:
            logger.info("⚪ 1차 추세 보완 : 해당없음 (구조붕괴X + RSI과매수/과매도 돌파)")
        
        # 7-4. 1차 상위 추세 보완 : RSI 상승 다이버전스 + 과매도 구간(상승)
        if h_rsi_signal.get('RSI_bull_dvrgence', False) and h_rsi_signal.get('RSI_ovrsold_brkout', False):
            logger.info(f"{Colors.GREEN}🟢 1차 추세 보완 : 상승 (RSI 상승 다이버전스 + 과매도 구간){Colors.END}")   
            return_trend = "uptrend"
        #  RSI 하락 다이버전스 + 과매수 구간(하락)
        elif h_rsi_signal.get('RSI_bear_dvrgence', False) and h_rsi_signal.get('RSI_ovrbght_brkdn', False):
            logger.info(f"{Colors.RED}🔴 1차 추세 보완 : 하락 (RSI 하락 다이버전스 + 과매수 구간){Colors.END}")
            return_trend = "downtrend"
        else:
            logger.info("⚪ 1차 추세 보완 : 해당없음 (RSI 상승 다이버전스 + 과매도 구간(상승))")

        # 7-5. 1차 상위 추세 보완 : 볼린저밴드 극단 터치 후 반등(반락) + 거래량 급증
        if (h_bb_lower is not None and
            higher_df['low'].iloc[-2] < h_bb_lower.iloc[-1] and  # 직전봉 저가가 밴드 하단보다 아래
            current_price > h_bb_lower.iloc[-1]              # 현재가가 밴드 하단 위로 반등
        ):
            logger.info(f"{Colors.GREEN}🟢 1차 추세 보완 : 상승 (BB하단 극단터치+반등+거래량급증){Colors.END}")
            return_trend = "uptrend"
        elif (h_bb_upper is not None and
            higher_df['high'].iloc[-2] > h_bb_upper.iloc[-1] and # 직전봉 고가가 밴드 상단보다 위
            current_price < h_bb_upper.iloc[-1]              # 현재가가 밴드 상단 아래로 반락
        ):
            logger.info(f"{Colors.RED}🔴 1차 추세 보완 : 하락 (BB상단 극단터치+반락+거래량급증){Colors.END}")
            return_trend = "downtrend"
        else:
            logger.info("⚪ 1차 추세 보완 : 해당없음 (볼린저밴드 극단 터치 후 반등(반락) + 거래량 급증)")

        # 7-6. 1차 상위 추세 보완 : 강한 추세 확인 (EMA 간격 + 거래량 + 다이버전스)
        crossover = check_ema_signal(higher_ind, h_bb_up, h_bb_down)  # EMA 신호 체크 로그 출력
        if crossover is not None:
            if crossover == 'bullish':
                logger.info(f"{Colors.GREEN}🟢 1차 추세 보완 : 상승 (EMA 골든크로스){Colors.END}")
                return_trend = "uptrend"
            elif crossover == 'bearish':
                logger.info(f"{Colors.RED}🔴 1차 추세 보완 : 하락 (EMA 데드크로스){Colors.END}")
                return_trend = "downtrend"
        else:
            logger.info("⚪ 1차 추세 보완 : 해당없음 (EMA 간격 + 거래량 + 다이버전스)")

        # 7-7. 1차 상위 추세 보완 : 추세 변경 안함
        #  8-2. Pullback 진입 체크 (추세 중 되돌림)
        if return_trend is not None and current_trend is not None and return_trend != current_trend:
            result_value = check_pullback_signal(higher_ind, h_bb_up, h_bb_down, current_price, config, current_trend)
            if result_value is not None and result_value == current_trend:
                if current_trend == 'uptrend':  # 추세 상승 => 하락으로 변경시 체크 
                    return_trend     = "uptrend"
                    logger.info(f"{Colors.GREEN}🔄 1차 추세 보완 : 상승 (추세 되돌림) : downtrend → uptrend {Colors.END}")
                elif current_trend == 'downtrend': # 추세 하락 => 상승으로 변경시 체크 
                    return_trend     = "downtrend"
                    logger.info(f"{Colors.RED}🔄 1차 추세 보완 : 하락 (추세 되돌림) : uptrend → downtrend {Colors.END}")
                else:
                    logger.info("⚪ 1차 추세 보완 : 해당없음 (추세 되돌림)")


        # 8. 2차 하위 추세 판단 시작: 구조 붕괴 + EMA 정렬 + 볼린저밴드 + 거래량 급증 + 다중TF + RSI지표(3개) 
        up_signals = [
            bool(structure_break_up),
            bool(ema_up),
            bool(h_bb_up),
            bool(h_vol_spike),
            bool(multi_tf_up),
            bool(l_rsi_signal.get('RSI_ovrsold_brkout', False)),
            bool(l_rsi_signal.get('RSI_bull_dvrgence', False)),
            bool(l_rsi_signal.get('RSI_mid_brkout', False))
        ]
        down_signals = [
            bool(structure_break_down),
            bool(ema_down),
            bool(h_bb_down),
            bool(l_vol_spike),
            bool(multi_tf_down),
            bool(l_rsi_signal.get('RSI_ovrbght_brkdn', False)),
            bool(l_rsi_signal.get('RSI_bear_dvrgence', False)),
            bool(l_rsi_signal.get('RSI_mid_brkdn', False))
        ]
        up_count = sum(up_signals)
        down_count = sum(down_signals)

        up_signal_names   = ['구조붕괴', 'EMA정렬', '볼린저밴드', '거래량급증',
                             '다중TF', 'RSI과매도돌파', 'RSI강세다이버전스', 'RSI50선상향돌파'     ]
        down_signal_names = ['구조붕괴', 'EMA정렬', '볼린저밴드', '거래량급증',
                             '다중TF', 'RSI과매수이탈', 'RSI약세다이버전스', 'RSI50선하락이탈'     ]
        true_up_signals = [name for name, val in zip(up_signal_names, up_signals) if val]
        true_down_signals = [name for name, val in zip(down_signal_names, down_signals) if val]
        logger.info(f"[2차 종합] Up:{up_count} {true_up_signals}, Down:{down_count} {true_down_signals}")

        if up_count > 3 and up_count > down_count:
            return_trend = "uptrend"
            logger.info(f"{Colors.GREEN}🟢 2차 추세 판단 : 상승 (Up: {up_count}개){Colors.END}")
        elif down_count > 3 and down_count > up_count:
            return_trend = "downtrend"
            logger.info(f"{Colors.RED}🔴 2차 추세 판단 : 하락 (Down: {down_count}개){Colors.END}")
        else:
            logger.info(f"⚪ 2차 추세 판단 : 미결정 (Up: {up_count}, Down: {down_count})")

        
        # 9. 3차 진입 판단  
        return_entry = None # 진입여부 초기값
        return_close = None # 청산여부 초기값 유지

        if current_trend is None and return_trend is not None: # 최초 프로그램 실행 시
            current_trend = return_trend

        # 9-1. 추세 변경 시 - 진입여부 설정
        if return_trend is not None and current_trend is not None and return_trend != current_trend:
            return_entry = return_trend  # 진입여부 변경 포지션 설정
            return_close = current_trend # 청산여부 반대 포지션 설정

            # 8. 예외 처리: 추세 변경 안함
            #  8-2. Pullback 진입 체크 (추세 중 되돌림)
            #  상승 추세: 가격이 EMA 9 근처까지 되돌아오면 좋은 진입점
            result_value = check_pullback_signal(lower_ind, l_bb_up, l_bb_down, current_price, config, current_trend)
            if result_value is not None and result_value == current_trend:
                if current_trend == 'uptrend':  # 추세 상승 => 하락으로 변경시 체크 
                    return_trend     = "uptrend"
                    return_entry = "uptrend"
                    return_close = None
                    logger.info("가격이 EMA 9~20 근처로 되돌아옴 → 상승 추세 재진입 허용")
                    logger.info(f"{Colors.GREEN}🔄 Pullback 진입 체크 (추세 되돌림) : downtrend → uptrend {Colors.END}")
                elif current_trend == 'downtrend': # 추세 하락 => 상승으로 변경시 체크 
                    return_trend     = "downtrend"
                    return_entry = "downtrend"
                    return_close = None
                    logger.info("가격이 EMA 9~20 근처로 되돌아옴 → 하락 추세 재진입 허용")
                    logger.info(f"{Colors.RED}🔄 Pullback 진입 체크 (추세 되돌림) : uptrend → downtrend {Colors.END}")

            if return_trend != current_trend:
                if return_trend == "uptrend": 
                    logger.info(f"{Colors.GREEN}🔄 추세 변경으로 진입 확정 : {current_trend} → {return_trend}{Colors.END}")
                else:
                    logger.info(f"{Colors.RED}🔄 추세 변경으로 진입 확정 : {current_trend} → {return_trend}{Colors.END}")


        # 9-2. 추세 미변경 시 - 진입여부 설정
        if return_trend and current_trend and return_trend == current_trend:
        
            # 상위 상태를 추가해서 보완해야 함 ★★★

            # # 상승 추세에서는 Long 청산여부만 고려
            # if return_trend == "uptrend": 
            #     if l_bb_upper.iloc[-1] < current_price and lower_ind['rsi'].iloc[-1] > 70:
            #         logger.info("현재가 밴드 상단값 상회 & RSI 70 이상 → 하락 반전 신호")
            #         return_entry = None         # 진입여부 설정
            #         return_close = "downtrend"  # 청산여부 설정

            #     if return_close is not None:
            #         logger.info(f"{Colors.GREEN}✅ 상승 반전 신호 확인 → Long 청산 허용{Colors.END}")

            # # 하락 추세에서는 Short 청산여부만 고려
            # elif return_trend == "downtrend": 
            #     if l_bb_lower.iloc[-1] > current_price and lower_ind['rsi'].iloc[-1] < 30:
            #         logger.info("현재가 밴드 하단값 하회 & RSI 30 미만 → 상승 반전 신호")
            #         return_entry = None       # 진입여부 설정
            #         return_close = "uptrend"  # 청산여부 설정
                
            #     if return_close is not None:
            #         logger.info(f"{Colors.RED}✅ 하락 반전 신호 확인 → Short 청산 허용{Colors.END}")


            # 예외 처리: 추세를 반대로 변경
            #  RSI 다이버젼스 처리 : 상승다이버젼스 + 과매도 돌파 / 하락다이버젼스 + 과매수 이탈 동시 발생 시 진입 허용
            # 상승 다이버전스 + 과매도 돌파
            if current_trend == 'downtrend' and l_rsi_signal.get('RSI_bull_dvrgence', False) and l_rsi_signal.get('RSI_ovrsold_brkout', False):
                return_trend = "uptrend"
                return_entry = "uptrend"
                return_close = "downtrend"
                logger.info("RSI 상승 다이버전스 + 과매도 돌파 동시 발생 → 진입 예외 허용")
                logger.info(f"{Colors.GREEN}🔄 추세 상승 및 진입 확정 : {current_trend} → {return_trend}{Colors.END}")
                #return return_trend, return_entry, return_close
            # 하락 다이버전스 + 과매수 이탈
            elif current_trend == 'uptrend' and l_rsi_signal.get('RSI_bear_dvrgence', False) and l_rsi_signal.get('RSI_ovrbght_brkdn', False):
                return_trend = "downtrend"
                return_entry = "downtrend"
                return_close = "uptrend"
                logger.info("RSI 하락 다이버전스 + 과매수 이탈 동시 발생 → 진입 예외 허용")
                logger.info(f"{Colors.RED}🔄 추세 하락 및 진입 확정 : {current_trend} → {return_trend}{Colors.END}")
                #return return_trend, return_entry, return_close
            else:
                logger.info(f"[3차 진입] : 현재 {current_trend}, 미변동 (RSI다이버전스 + 과매수/과매도 이탈)")

        # 9-3. 추세와 상관없이 - 진입여부 설정
        if current_trend is not None and return_trend is not None:

            # 강한 추세 확인 (EMA 간격 + 거래량 + 다이버전스)
            crossover = check_ema_signal(lower_ind, l_bb_up, l_bb_down)
            if crossover == 'bullish':
                logger.info(f"{Colors.GREEN}✅ EMA 골든크로스 → 상승 추세 / 진입 즉시 허용{Colors.END}")
                return_trend     = "uptrend"
                return_entry = "uptrend"
                return_close = "downtrend"
                #return return_trend, return_entry, return_close
            elif crossover == 'bearish':
                logger.info(f"{Colors.RED}✅ EMA 데드크로스 → 하락 추세 / 진입 즉시 허용{Colors.END}")
                return_trend    = "downtrend"
                return_entry = "downtrend"
                return_close = "uptrend"
                #return return_trend, return_entry, return_close
            else:
                logger.info(f"[3차 진입] : 현재 {current_trend}, 미변동 (EMA 간격 + 거래량 + 다이버전스)")

        # 9-4. 거래 제한 : 볼린저밴드 밴드폭 기반
        #  - 밴드폭이 평균보다 좁으면 매매 금지
        #  - 밴드폭이 평균보다 충분히 넓어지기 시작하면 진입 신호

        # 볼린저밴드 상단/하단
        bb_upper_1m = lower_ind['bb_upper'].iloc[-1]
        bb_lower_1m = lower_ind['bb_lower'].iloc[-1]

        # 현시점 밴드폭 계산
        band_width_1m = bb_upper_1m - bb_lower_1m
        # 최근 N봉 평균 밴드폭 계산 :  N = 20
        band_width_mean_1m = (lower_ind['bb_upper'] - lower_ind['bb_lower']).iloc[-20:].mean()
        # 밴드폭 확장 여부
        band_expanding_1m = band_width_1m > band_width_mean_1m * 1.15  # 15% 이상 확장
        logger.info(f"[밴드폭(1m)] 현재: {band_width_1m:.6f}, 평균20: {band_width_mean_1m:.6f}, 확장15%: {band_expanding_1m}")
        # 밴드폭이 좁은 구간에서는 매매 금지
        if band_width_1m < band_width_mean_1m * 0.8 and band_expanding_1m is False:
            return_trend = current_trend # 추세 유지
            return_entry = None # 진입여부 초기값 유지
            return_close = None # 청산여부 초기값 유지
            logger.info(f"{Colors.YELLOW}⚪️ 볼린저밴드 폭이 좁음 → 매매 제한{Colors.END}")
        else:   
            logger.info(f"✅️ 볼린저밴드 폭이 충분함 → 매매 허용")


        # 10. 최종결과 출력 및 반환      
        logger.info(f"[최종결과] 추세 : {return_trend}, 진입 : {return_entry}, 청산 : {return_close}")
        return return_trend, return_entry, return_close
    
    except Exception as e:
        logger.error(f"추세/진입 결정 오류: {str(e)}")
        return None, None, None
    

def check_ema_signal(ind, bb_up, bb_down):
    """
    EMA 추세 강도, 강화, 크로스오버 체크 함수
    Args:
        ind: EMA 관련 지표가 포함된 DataFrame (예: higher_ind, lower_ind)
        bb_up: bool (상단 밴드 돌파 여부)
        bb_down: bool (하단 밴드 돌파 여부)
    Returns:
        (return_value)
    """
    ema_fast = ind['ema_fast'].iloc[-1]
    ema_medium = ind['ema_medium'].iloc[-1]
    ema_fast_prev = ind['ema_fast'].iloc[-2] if len(ind['ema_fast']) > 1 else ema_fast
    ema_medium_prev = ind['ema_medium'].iloc[-2] if len(ind['ema_medium']) > 1 else ema_medium

    crossover = None
    if len(ind['ema_fast']) >= 2:
        crossover = detect_ema_crossover(ema_fast_prev, ema_medium_prev, ema_fast, ema_medium)
        if hasattr(crossover, 'iloc'):
            crossover = crossover.iloc[-1]
    else:
        ema_fast_prev = ema_fast
        ema_medium_prev = ema_medium
        crossover = None

    ema_separation = abs(ema_fast - ema_medium) / ema_medium if ema_medium != 0 else 0
    ema_expanding = abs(ema_fast - ema_medium) > abs(ema_fast_prev - ema_medium_prev)
    strong_trend = bool((ema_separation > 0.0001 and ema_expanding) or (crossover is not None))

    if bool(ema_fast > ema_medium) and bool(bb_down) and bool(strong_trend):
        return_value = "bullish"
        logger.info(f"[EMA추세강도] 분리:{ema_separation:.6f} 강화:{ema_expanding} 크로스오버:{crossover} → 강한추세:{strong_trend}, BB:({bb_up}, {bb_down}) 추세결정:{return_value}")
        return return_value
    elif bool(ema_fast < ema_medium) and bool(bb_up) and bool(strong_trend):
        return_value = "bearish"
        logger.info(f"[EMA추세강도] 분리:{ema_separation:.6f} 강화:{ema_expanding} 크로스오버:{crossover} → 강한추세:{strong_trend}, BB:({bb_up}, {bb_down}) 추세결정:{return_value}")
        return return_value
    else:
        return None


def check_trend_reversal(exchange, symbol: str, config: Dict, current_trend: str, cache=None) -> bool:
    """
    현재 추세가 반전되었는지 확인
    
    Args:
        exchange: CCXT exchange 인스턴스
        symbol: 거래 심볼
        config: 설정 딕셔너리
        current_trend: 현재 추세 ('uptrend' or 'downtrend')
        cache: 캐시 객체
        
    Returns:
        True: 추세 반전됨, False: 추세 유지
    """
    try:
        higher_df = fetch_ohlcv_data(exchange, symbol, '5m', limit=100, cache=cache)
        if higher_df is None or len(higher_df) < 50:
            return False
        
        # trend_ema만 복사해서 전달
        import copy
        trend_config = copy.deepcopy(config)
        trend_config['strategy']['ema'] = dict(config['strategy']['trend_ema'])
        trend_config['strategy']['ema']['ema_fast'] = trend_config['strategy']['ema']['fast']
        trend_config['strategy']['ema']['ema_medium'] = trend_config['strategy']['ema']['medium']
        trend_config['strategy']['ema']['ema_slow'] = trend_config['strategy']['ema']['slow']
        higher_indicators = {
            'ema_fast': technical_indicators.calculate_ema_fast(higher_df, trend_config),
            'ema_medium': technical_indicators.calculate_ema_medium(higher_df, trend_config),
            'ema_slow': technical_indicators.calculate_ema_slow(higher_df, trend_config),
            'bb_upper': technical_indicators.calculate_bb_upper(higher_df, trend_config),
            'bb_middle': technical_indicators.calculate_bb_middle(higher_df, trend_config),
            'bb_lower': technical_indicators.calculate_bb_lower(higher_df, trend_config),
            'rsi': technical_indicators.calculate_rsi_series(higher_df, trend_config),
            'atr': technical_indicators.calculate_atr_series(higher_df, trend_config),
            'adx': technical_indicators.calculate_adx_series(higher_df, trend_config),
            'volume_ma': technical_indicators.calculate_volume_ma_series(higher_df, trend_config)
        }

        if 'ema_fast' not in higher_indicators:
            return False

        h_ema_fast = higher_indicators['ema_fast'].iloc[-1]
        h_ema_medium = higher_indicators['ema_medium'].iloc[-1]
        h_ema_slow = higher_indicators['ema_slow'].iloc[-1]

        # 추세 반전 확인
        if current_trend == 'uptrend':
            # 상승 추세였는데 하락 전환
            if h_ema_fast < h_ema_medium < h_ema_slow:
                logger.warning(
                    f"🔄 [5m] 상승 → 하락 추세 전환 감지! (EMA {config['strategy']['trend_ema']['fast']}:{h_ema_fast:.4f}, "
                    f"{config['strategy']['trend_ema']['medium']}:{h_ema_medium:.4f}, {config['strategy']['trend_ema']['slow']}:{h_ema_slow:.4f})"
                )
                return True
        elif current_trend == 'downtrend':
            # 하락 추세였는데 상승 전환
            if h_ema_fast > h_ema_medium > h_ema_slow:
                logger.warning(
                    f"🔄 [5m] 하락 → 상승 추세 전환 감지! (EMA {config['strategy']['trend_ema']['fast']}:{h_ema_fast:.4f}, "
                    f"{config['strategy']['trend_ema']['medium']}:{h_ema_medium:.4f}, {config['strategy']['trend_ema']['slow']}:{h_ema_slow:.4f})"
                )
                return True

        return False
        
    except Exception as e:
        logger.error(f"추세 반전 확인 오류: {str(e)}")
        return False


def check_exit_signal(exchange, symbol: str, config: Dict, position_type: str, cache=None) -> bool:
    """
    청산 신호 감지 전용 (1분봉 빠른 감지)
    
    포지션 보유 중 1분봉 반전 신호를 빠르게 감지:
    - BB 중앙선 크로스
    - 1분봉 EMA 정렬 반전
    
    Args:
        exchange: CCXT exchange 인스턴스
        symbol: 거래 심볼
        config: 설정 딕셔너리
        position_type: 'long' 또는 'short' (보유 포지션 방향)
        cache: 캐시 객체
        
    Returns:
        True: 청산 필요, False: 유지
    """
    try:
        logger.info(f"[1분봉 청산 신호 체크] {position_type.upper()} 포지션 모니터링...")
        
        # === 1분봉 빠른 신호 체크 ===
        base_df = fetch_ohlcv_data(exchange, symbol, '1m', limit=100, cache=cache)
        if base_df is None or len(base_df) < 50:
            logger.warning("데이터 부족으로 청산 신호 감지 불가")
            return False
        
        # 1분봉 지표 계산
        # Use signal_ema for 1m exit signal detection
        import copy
        exit_config = copy.deepcopy(config)
        exit_config['strategy']['ema'] = dict(config['strategy']['signal_ema'])
        exit_config['strategy']['ema']['ema_fast'] = exit_config['strategy']['ema']['fast']
        exit_config['strategy']['ema']['ema_medium'] = exit_config['strategy']['ema']['medium']
        exit_config['strategy']['ema']['ema_slow'] = exit_config['strategy']['ema']['slow']
        lower_indicators = {
            'ema_fast': technical_indicators.calculate_ema_fast(base_df, exit_config),
            'ema_medium': technical_indicators.calculate_ema_medium(base_df, exit_config),
            'ema_slow': technical_indicators.calculate_ema_slow(base_df, exit_config),
            'bb_upper': technical_indicators.calculate_bb_upper(base_df, exit_config),
            'bb_middle': technical_indicators.calculate_bb_middle(base_df, exit_config),
            'bb_lower': technical_indicators.calculate_bb_lower(base_df, exit_config),
            'rsi': technical_indicators.calculate_rsi_series(base_df, exit_config),
            'atr': technical_indicators.calculate_atr_series(base_df, exit_config),
            'adx': technical_indicators.calculate_adx_series(base_df, exit_config),
            'volume_ma': technical_indicators.calculate_volume_ma_series(base_df, exit_config)
        }
        if 'ema_fast' not in lower_indicators:
            return False

        ema_fast = lower_indicators['ema_fast'].iloc[-1]
        ema_medium = lower_indicators['ema_medium'].iloc[-1]
        ema_slow = lower_indicators['ema_slow'].iloc[-1]

        rsi = lower_indicators['rsi'].iloc[-1]
        bb_middle = lower_indicators['bb_middle'].iloc[-1]
        bb_upper = lower_indicators['bb_upper'].iloc[-1]
        bb_lower = lower_indicators['bb_lower'].iloc[-1]
        current_price = base_df['close'].iloc[-1]
        volume = base_df['volume'].iloc[-1]
        volume_ma = lower_indicators['volume_ma'].iloc[-1]
        volume = base_df['volume'].iloc[-1]
        volume_ma = lower_indicators['volume_ma'].iloc[-1]

        # 1. 더 빠른 EMA 조합 (예: 3, 6, 9)
        ema3 = technical_indicators.calculate_ema(base_df['close'], 3).iloc[-1]
        ema6 = technical_indicators.calculate_ema(base_df['close'], 6).iloc[-1]
        ema9 = technical_indicators.calculate_ema(base_df['close'], 9).iloc[-1]

        # 2. RSI/볼린저 병행
        trend_ema = technical_indicators.get_trend_from_ema(current_price, ema_fast, ema_medium, ema_slow)
        trend_bb = technical_indicators.get_trend_from_bollinger(current_price, bb_upper, bb_middle, bb_lower)
        trend_rsi = technical_indicators.get_trend_from_rsi(rsi)
        combined_trend, agreement = technical_indicators.combine_trend_signals(trend_ema, trend_bb, trend_rsi)

        # 3. 거래량 급증
        volume_spike = technical_indicators.check_volume_spike(base_df['volume'], lower_indicators['volume_ma'])

        # 4. 크로스 직후만 인정 (EMA 크로스)
        ema_cross = None
        if len(base_df) >= 2:
            prev_ema_fast = lower_indicators['ema_fast'].iloc[-2]
            prev_ema_medium = lower_indicators['ema_medium'].iloc[-2]
            ema_cross = technical_indicators.detect_ema_crossover(prev_ema_fast, prev_ema_medium, ema_fast, ema_medium)

        # 볼린저 밴드 중앙선 크로스 감지 (2봉 비교)
        bb_cross = None
        if len(base_df) >= 2:
            prev_price = base_df['close'].iloc[-2]
            prev_bb_middle = lower_indicators['bb_middle'].iloc[-2]
            if prev_price < prev_bb_middle and current_price > bb_middle:
                bb_cross = "bullish"
            elif prev_price > prev_bb_middle and current_price < bb_middle:
                bb_cross = "bearish"

        # LONG 포지션: 하락 신호 감지 시 청산
        if position_type.lower() == 'long':
            # 1. 빠른 EMA 조합 (3,6,9) 하락 정렬
            if ema3 < ema6 < ema9:
                logger.warning(f"⚠ [1m] 빠른 EMA(3,6,9) 하락 정렬! → LONG 청산 신호 (EMA3:{ema3:.4f}, EMA6:{ema6:.4f}, EMA9:{ema9:.4f})")
                return True
            # 2. RSI/볼린저/EMA 병행: 2개 이상 하락 동의
            if combined_trend == 'downtrend' and agreement >= 2:
                logger.warning(f"⚠ [1m] RSI/볼린저/EMA 병행 하락 신호! → LONG 청산 신호 (동의:{agreement}, RSI:{rsi:.2f}, BB:{trend_bb}, EMA:{trend_ema})")
                return True
            # 3. 거래량 급증
            if volume_spike:
                logger.warning(f"⚠ [1m] 거래량 급증! → LONG 청산 신호 (현재:{volume:.2f}, 평균:{volume_ma:.2f})")
                return True
            # 4. EMA 데드크로스 직후
            if ema_cross == 'death_cross':
                logger.warning(f"⚠ [1m] EMA 데드크로스 발생! → LONG 청산 신호 (EMA_FAST:{ema_fast:.4f}, EMA_MEDIUM:{ema_medium:.4f})")
                return True
            # 5. 볼린저 밴드 중앙선 하향 돌파
            if bb_cross == "bearish":
                logger.warning(f"⚠ [1m] BB 중앙선 하향 돌파! → LONG 청산 신호")
                return True
            # 6. 기존 EMA 정렬 하락
            if ema_fast < ema_medium < ema_slow:
                logger.warning(f"⚠ [1m] 하락 추세 전환! → LONG 청산 신호 (EMA {config['strategy']['ema']['fast']}:{ema_fast:.4f}, {config['strategy']['ema']['medium']}:{ema_medium:.4f}, {config['strategy']['ema']['slow']}:{ema_slow:.4f})")
                return True

        # SHORT 포지션: 상승 신호 감지 시 청산
        elif position_type.lower() == 'short':
            # 1. 빠른 EMA 조합 (3,6,9) 상승 정렬
            if ema3 > ema6 > ema9:
                logger.warning(f"⚠ [1m] 빠른 EMA(3,6,9) 상승 정렬! → SHORT 청산 신호 (EMA3:{ema3:.4f}, EMA6:{ema6:.4f}, EMA9:{ema9:.4f})")
                return True
            # 2. RSI/볼린저/EMA 병행: 2개 이상 상승 동의
            if combined_trend == 'uptrend' and agreement >= 2:
                logger.warning(f"⚠ [1m] RSI/볼린저/EMA 병행 상승 신호! → SHORT 청산 신호 (동의:{agreement}, RSI:{rsi:.2f}, BB:{trend_bb}, EMA:{trend_ema})")
                return True
            # 3. 거래량 급증
            if volume_spike:
                logger.warning(f"⚠ [1m] 거래량 급증! → SHORT 청산 신호 (현재:{volume:.2f}, 평균:{volume_ma:.2f})")
                return True
            # 4. EMA 골든크로스 직후
            if ema_cross == 'golden_cross':
                logger.warning(f"⚠ [1m] EMA 골든크로스 발생! → SHORT 청산 신호 (EMA_FAST:{ema_fast:.4f}, EMA_MEDIUM:{ema_medium:.4f})")
                return True
            # 5. 볼린저 밴드 중앙선 상향 돌파
            if bb_cross == "bullish":
                logger.warning(f"⚠ [1m] BB 중앙선 상향 돌파! → SHORT 청산 신호")
                return True
            # 6. 기존 EMA 정렬 상승
            if ema_fast > ema_medium > ema_slow:
                logger.warning(f"⚠ [1m] 상승 추세 전환! → SHORT 청산 신호 (EMA {config['strategy']['ema']['fast']}:{ema_fast:.4f}, {config['strategy']['ema']['medium']}:{ema_medium:.4f}, {config['strategy']['ema']['slow']}:{ema_slow:.4f})")
                return True

        return False
        
    except Exception as e:
        logger.error(f"청산 신호 감지 오류: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def detect_trend_reversal(exchange, symbol: str, config: Dict, position_type: str, cache=None) -> bool:
    """
    상위 시간봉 추세 반전 감지 (Hybrid Mode용)
    
    포지션 진입 후 상위 시간봉 추세가 반전되었는지 확인
    진입 시점의 추세와 현재 추세가 다르면 반전으로 판단
    
    Args:
        exchange: CCXT exchange 인스턴스
        symbol: 거래 심볼
        config: 설정 딕셔너리
        position_type: 'long' 또는 'short' (포지션 방향)
        cache: 캐시 객체
        
    Returns:
        추세 반전 감지 여부 (True: 반전됨, False: 유지)
    """
    try:
        logger.info(f"[추세 반전 감지] {position_type.upper()} 포지션 모니터링...")
        strategy = TrendFollowingStrategy(config)
        
        # 1분봉 데이터 수집 (충분한 상위 시간봉 생성을 위해 1500개)
        base_df = fetch_ohlcv_data(exchange, symbol, '1m', limit=1500, cache=cache)
        if base_df is None or len(base_df) < 100:
            logger.warning("데이터 부족으로 추세 반전 감지 불가")
            return False
        
        # === 1단계: 1분봉(하위) 추세 반전 감지 (빠른 반응) ===
        # Use signal_ema for 1m trend reversal detection
        import copy
        lower_config = copy.deepcopy(config)
        lower_config['strategy']['ema'] = dict(config['strategy']['signal_ema'])
        lower_config['strategy']['ema']['ema_fast'] = lower_config['strategy']['ema']['fast']
        lower_config['strategy']['ema']['ema_medium'] = lower_config['strategy']['ema']['medium']
        lower_config['strategy']['ema']['ema_slow'] = lower_config['strategy']['ema']['slow']
        lower_indicators = {
            'ema_fast': technical_indicators.calculate_ema_fast(base_df, lower_config),
            'ema_medium': technical_indicators.calculate_ema_medium(base_df, lower_config),
            'ema_slow': technical_indicators.calculate_ema_slow(base_df, lower_config),
            'bb_upper': technical_indicators.calculate_bb_upper(base_df, lower_config),
            'bb_middle': technical_indicators.calculate_bb_middle(base_df, lower_config),
            'bb_lower': technical_indicators.calculate_bb_lower(base_df, lower_config),
            'rsi': technical_indicators.calculate_rsi_series(base_df, lower_config),
            'atr': technical_indicators.calculate_atr_series(base_df, lower_config),
            'adx': technical_indicators.calculate_adx_series(base_df, lower_config),
            'volume_ma': technical_indicators.calculate_volume_ma_series(base_df, lower_config)
        }
        
        if len(base_df) >= 50 and 'ema_fast' in lower_indicators:
            ema_fast = lower_indicators['ema_fast'].iloc[-1]
            ema_medium = lower_indicators['ema_medium'].iloc[-1]
            ema_slow = lower_indicators['ema_slow'].iloc[-1]
            rsi_1m = lower_indicators['rsi'].iloc[-1]
            
            # 볼린저 밴드 중앙선 (추세 반전 1차 신호)
            bb_middle = lower_indicators['bb_middle'].iloc[-1]
            current_price = base_df['close'].iloc[-1]
            
            # BB 중앙선 크로스 감지 (2봉 비교)
            bb_cross = None
            if len(base_df) >= 2 and 'bb_middle' in lower_indicators:
                prev_price = base_df['close'].iloc[-2]
                prev_bb_middle = lower_indicators['bb_middle'].iloc[-2]
                
                # 상향 돌파 (아래 → 위)
                if prev_price < prev_bb_middle and current_price > bb_middle:
                    bb_cross = "bullish"
                # 하향 돌파 (위 → 아래)
                elif prev_price > prev_bb_middle and current_price < bb_middle:
                    bb_cross = "bearish"
            
            # 1분봉 추세 판단 (EMA 정렬)
            lower_trend = "neutral"
            if ema_fast > ema_medium > ema_slow:
                lower_trend = "uptrend"
            elif ema_fast < ema_medium < ema_slow:
                lower_trend = "downtrend"
            
            # LONG 포지션: 하락 신호 감지
            if position_type.lower() == 'long':
                # BB 중앙선 하향 돌파 (강력한 하락 신호)
                if bb_cross == "bearish":
                    logger.warning(f"⚠ [1m] BB 중앙선 하향 돌파! (가격={current_price:.4f} < BB중앙={bb_middle:.4f})")
                    return True
                # 1분봉 하락 추세 전환
                if lower_trend == 'downtrend':
                    logger.warning(f"⚠ [1m] 하위 추세 하락 전환 감지! (EMA9 < EMA20 < EMA30)")
                    return True
            
            # SHORT 포지션: 상승 신호 감지
            if position_type.lower() == 'short':
                # BB 중앙선 상향 돌파 (강력한 상승 신호)
                if bb_cross == "bullish":
                    logger.warning(f"⚠ [1m] BB 중앙선 상향 돌파! (가격={current_price:.4f} > BB중앙={bb_middle:.4f})")
                    return True
                # 1분봉 상승 추세 전환
                if lower_trend == 'uptrend':
                    logger.warning(f"⚠ [1m] 하위 추세 상승 전환 감지! (EMA9 > EMA20 > EMA30)")
                    return True
        
        # === 2단계: 5분봉(상위) 추세 분석 ===
        higher_timeframes = config['strategy']['timeframes']['higher_trend']
        
        if not higher_timeframes:
            logger.warning("상위 시간봉 설정 없음")
            return False
        
        # 첫 번째 상위 시간봉 분석 (일반적으로 15m)
        primary_tf = higher_timeframes[0]
        higher_df = resample_data(base_df, primary_tf)
        
        if len(higher_df) < 50:
            logger.warning(f"{primary_tf}: 데이터 부족 (bars: {len(higher_df)})")
            return False
        
        # 현재 상위 추세 분석
        # Use trend_ema for higher timeframe trend reversal detection
        higher_config = copy.deepcopy(config)
        higher_config['strategy']['ema'] = dict(config['strategy']['trend_ema'])
        higher_config['strategy']['ema']['ema_fast'] = higher_config['strategy']['ema']['fast']
        higher_config['strategy']['ema']['ema_medium'] = higher_config['strategy']['ema']['medium']
        higher_config['strategy']['ema']['ema_slow'] = higher_config['strategy']['ema']['slow']
        indicators = {
            'ema_fast': technical_indicators.calculate_ema_fast(higher_df, higher_config),
            'ema_medium': technical_indicators.calculate_ema_medium(higher_df, higher_config),
            'ema_slow': technical_indicators.calculate_ema_slow(higher_df, higher_config),
            'bb_upper': technical_indicators.calculate_bb_upper(higher_df, higher_config),
            'bb_middle': technical_indicators.calculate_bb_middle(higher_df, higher_config),
            'bb_lower': technical_indicators.calculate_bb_lower(higher_df, higher_config),
            'rsi': technical_indicators.calculate_rsi_series(higher_df, higher_config),
            'atr': technical_indicators.calculate_atr_series(higher_df, higher_config),
            'adx': technical_indicators.calculate_adx_series(higher_df, higher_config),
            'volume_ma': technical_indicators.calculate_volume_ma_series(higher_df, higher_config)
        }
        higher_analysis = strategy.analyze_higher_timeframe(higher_df, indicators)
        
        current_trend = higher_analysis['trend']
        rsi = higher_analysis['rsi']
        
        logger.info(
            f"[{primary_tf}] 현재 추세: {current_trend.upper()} "
            f"(신뢰도: {higher_analysis['confidence']*100:.1f}%)"
        )
        
        # 조기 반전 신호 감지 (RSI + 볼린저 밴드)
        early_reversal = False
        reversal_reason = ""
        
        if position_type.lower() == 'long':
            # LONG 포지션: 하락 반전 조기 신호
            # 1. RSI가 과매수(70)에서 하락 시작
            # 2. 가격이 볼린저 밴드 상단에서 이탈
            rsi_declining = False
            if len(indicators['rsi']) >= 3:
                rsi_prev2 = indicators['rsi'].iloc[-3]
                rsi_prev1 = indicators['rsi'].iloc[-2]
                rsi_curr = indicators['rsi'].iloc[-1]
                # RSI가 70 이상에서 2봉 연속 하락
                if rsi_prev2 > 70 and rsi_prev1 < rsi_prev2 and rsi_curr < rsi_prev1:
                    rsi_declining = True
                    reversal_reason += "RSI 과매수 하락, "
            
            bb_breakdown = False
            if len(higher_df) >= 2:
                close_prev = higher_df['close'].iloc[-2]
                close_curr = higher_df['close'].iloc[-1]
                bb_upper_prev = indicators['bb_upper'].iloc[-2]
                bb_upper_curr = indicators['bb_upper'].iloc[-1]
                # 가격이 BB 상단 위에 있다가 아래로 이탈
                if close_prev > bb_upper_prev and close_curr < bb_upper_curr:
                    bb_breakdown = True
                    reversal_reason += "BB 상단 이탈, "
            
            # 조기 반전: RSI 하락 OR BB 이탈
            if rsi_declining or bb_breakdown:
                early_reversal = True
                
        elif position_type.lower() == 'short':
            # SHORT 포지션: 상승 반전 조기 신호
            # 1. RSI가 과매도(30)에서 상승 시작
            # 2. 가격이 볼린저 밴드 하단에서 이탈
            rsi_rising = False
            if len(indicators['rsi']) >= 3:
                rsi_prev2 = indicators['rsi'].iloc[-3]
                rsi_prev1 = indicators['rsi'].iloc[-2]
                rsi_curr = indicators['rsi'].iloc[-1]
                # RSI가 30 이하에서 2봉 연속 상승
                if rsi_prev2 < 30 and rsi_prev1 > rsi_prev2 and rsi_curr > rsi_prev1:
                    rsi_rising = True
                    reversal_reason += "RSI 과매도 반등, "
            
            bb_breakup = False
            if len(higher_df) >= 2:
                close_prev = higher_df['close'].iloc[-2]
                close_curr = higher_df['close'].iloc[-1]
                bb_lower_prev = indicators['bb_lower'].iloc[-2]
                bb_lower_curr = indicators['bb_lower'].iloc[-1]
                # 가격이 BB 하단 아래에 있다가 위로 이탈
                if close_prev < bb_lower_prev and close_curr > bb_lower_curr:
                    bb_breakup = True
                    reversal_reason += "BB 하단 이탈, "
            
            # 조기 반전: RSI 상승 OR BB 이탈
            if rsi_rising or bb_breakup:
                early_reversal = True
        
        # 조기 반전 신호 발생 시 즉시 청산
        if early_reversal:
            logger.warning(f"⚠ {position_type.upper()} 포지션 조기 반전 신호 감지! ({reversal_reason.rstrip(', ')})")
            return True
        
        # 포지션 방향과 반대 추세로 명확히 바뀌었을 때만 반전으로 판별
        if position_type.lower() == 'long':
            # LONG 포지션: DOWNTREND로 반전 시 청산
            if current_trend == 'downtrend':
                logger.warning(f"⚠ LONG 포지션 추세 반전 감지! ({primary_tf} DOWNTREND)")
                return True
            elif current_trend == 'neutral':
                logger.info(f"{Colors.YELLOW}⊙ LONG 포지션 NEUTRAL 추세 유지{Colors.RESET}")
                return False
            else:  # uptrend
                logger.info(f"{Colors.GREEN}✓ LONG 포지션 추세 유지{Colors.RESET}")
                return False
            
        elif position_type.lower() == 'short':
            # SHORT 포지션: UPTREND로 반전 시 청산
            if current_trend == 'uptrend':
                logger.warning(f"⚠ SHORT 포지션 추세 반전 감지! ({primary_tf} UPTREND)")
                return True
            elif current_trend == 'neutral':
                logger.info(f"{Colors.YELLOW}⊙ SHORT 포지션 NEUTRAL 추세 유지{Colors.RESET}")
                return False
            else:  # downtrend
                logger.info(f"{Colors.RED}✓ SHORT 포지션 추세 유지{Colors.RESET}")
                return False
        
        return False
        
    except Exception as e:
        logger.error(f"추세 반전 감지 오류: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def check_pullback_signal(ind, bb_up, bb_down, current_price, config, current_trend):
    """
    EMA/볼린저밴드 기반 Pullback(되돌림) 진입/복귀 신호 판단 함수
    Args:
        ind: EMA, 볼린저밴드, RSI 등 지표 dict (예: lower_ind 또는 higher_ind)
        bb_up: 볼린저밴드 상단 돌파 여부 (bool)
        bb_down: 볼린저밴드 하단 돌파 여부 (bool)
        current_price: 현재가 (float)
        config: 설정 dict
        current_trend: 현재 추세 ('uptrend' 또는 'downtrend')
    Returns:
        'uptrend', 'downtrend', 또는 None (추세 복귀/진입 신호)
    """
    ema_fast = ind['ema_fast'].iloc[-1]
    ema_medium = ind['ema_medium'].iloc[-1]
    rsi = ind['rsi'].iloc[-1]
    rsi_oversold = config['strategy']['rsi']['oversold']
    rsi_overbought = config['strategy']['rsi']['overbought']
    bb_lower = ind['bb_lower'] if 'bb_lower' in ind else None
    bb_upper = ind['bb_upper'] if 'bb_upper' in ind else None
    bb_middle = ind['bb_middle'] if 'bb_middle' in ind else None
    
    if current_trend == 'uptrend':
        pullback_entry = bool(ema_medium <= current_price <= ema_fast * 1.001)
        prev_rsi = ind['rsi'].iloc[-2] if len(ind['rsi']) > 1 else rsi
        volume_spike = bool(check_volume_spike(ind['volume'], ind['volume_ma']))
        rsi_rebound = bool(rsi > rsi_oversold and rsi > prev_rsi)
        bb_recover = bool(current_price > bb_lower.iloc[-1] and current_price < bb_middle.iloc[-1])
        if pullback_entry and bool(bb_down) and (volume_spike or rsi_rebound or bb_recover):
            return 'uptrend'
    elif current_trend == 'downtrend':
        pullback_entry = bool(ema_fast * 0.999 <= current_price <= ema_medium)
        prev_rsi = ind['rsi'].iloc[-2] if len(ind['rsi']) > 1 else rsi
        volume_spike = bool(check_volume_spike(ind['volume'], ind['volume_ma']))
        rsi_rebound = bool(rsi < rsi_overbought and rsi < prev_rsi)
        bb_recover = bool(current_price < bb_upper.iloc[-1] and current_price > bb_middle.iloc[-1])
        if pullback_entry and bool(bb_up) and (volume_spike or rsi_rebound or bb_recover):
            return 'downtrend'
    return None