import logging
import pandas as pd
from sideways.color_utils import Colors
from sideways import technical_indicators
from sideways.common import play_voice_alert, play_voice_alert_signal, send_telegram
from sideways.market_structure import MarketStructure
from sideways.validation import validate_data
from sideways.position_manager import PositionManager
from sideways.risk_manager import RiskManager
from datetime import datetime, time

active_logger = logging.getLogger(__name__)
active_logger.setLevel(logging.DEBUG)
trade_logger = logging.getLogger("trade")

class SidewaysStrategy:

    """평균 회귀/박스권 전략 로직."""
    def __init__(self, exchange, symbol, config, window_size=180+1, bb_window=20, bb_std=2, rsi_period=14, rsi_overbought=70, rsi_oversold=30):
        self.exchange = exchange
        self.symbol = symbol
        self.config = config
        self.window_size = window_size
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.position_manager = PositionManager(exchange, symbol)
        self.risk_manager = RiskManager()
        self.current_price = None

    def execute_trading(self, current_trend, verbose: bool = False):
        """
         1.기초 자료 생성
           차트(1분봉, 5분봉) 기반 볼린저 밴드, RSI 계산...
         2.추세 확인 : 상위 캔틀(5m, 15m) 기반 확인
         3.신호 생성 : 거래량 중심, 
         4.포지션 관리
        """
        return_trend = None
        return_position = None
        return_position_msg = None

        # 1분봉/5분봉 OHLCV list 조회
        ohlcv_low = self.exchange.fetch_ohlcv(self.symbol, timeframe='1m', limit=self.window_size)
        ohlcv_hgh = self.exchange.fetch_ohlcv(self.symbol, timeframe='5m', limit=self.window_size)
        #print(f"[DEBUG] ohlcv_low: {repr(ohlcv_low)[:100]}")
        #print(f"[DEBUG] ohlcv_hgh: {repr(ohlcv_hgh)[:400]}")
        
        # 1분봉/5분봉, 볼린저 밴드, RSI df생성
        df_low = pd.DataFrame(ohlcv_low, columns=['timestamp','open','high','low','close','volume'])
        df_hgh = pd.DataFrame(ohlcv_hgh, columns=['timestamp','open','high','low','close','volume'])
        validate_data(df_low, ['close', 'volume'])
        validate_data(df_hgh, ['close', 'volume'])
        bb_low_top, bb_low_mid, bb_low_down = technical_indicators.get_bollinger_bands(df_low, self.bb_window, self.bb_std)
        rsi_low = technical_indicators.get_rsi(df_low, self.rsi_period)
        bb_hgh_top, bb_hgh_mid, bb_hgh_down = technical_indicators.get_bollinger_bands(df_hgh, self.bb_window, self.bb_std)
        rsi_hgh = technical_indicators.get_rsi(df_hgh, self.rsi_period)

        # 분봉에 따라 config에서 EMA 파라미터 선택
        strategy_cfg = self.config.get("strategy", {})
        tf_hgh_fast = strategy_cfg.get("trend_ema", {}).get("first", 5)
        tf_hgh_medium = strategy_cfg.get("trend_ema", {}).get("second", 14)
        tf_low_fast = strategy_cfg.get("signal_ema", {}).get("first", 3)
        tf_low_medium = strategy_cfg.get("signal_ema", {}).get("second", 7)
        trend_ema_periods = technical_indicators.parse_ema_periods(strategy_cfg.get("trend_ema", {}))
        signal_ema_periods = technical_indicators.parse_ema_periods(strategy_cfg.get("signal_ema", {}))
        ema_low_series = {p: df_low["close"].ewm(span=p, adjust=False).mean() for p in signal_ema_periods}
        ema_hgh_series = {p: df_hgh["close"].ewm(span=p, adjust=False).mean() for p in trend_ema_periods}
        ema_low = technical_indicators.get_ema_values(df_low, "1m", periods=signal_ema_periods)
        ema_hgh = technical_indicators.get_ema_values(df_hgh, "5m", periods=trend_ema_periods)
        #active_logger.info(f"[signal_ema_periods] {signal_ema_periods} [ema_low_series] {ema_low_series}")
        #active_logger.info(f"[EMA 1m] {' '.join([f'EMA{p}={v:.4f}' for p,v in ema_low.items()])}")
        #active_logger.info(f"[EMA 5m] {' '.join([f'EMA{p}={v:.4f}' for p,v in ema_hgh.items()])}")

        # 실시간 현재가 조회
        current_price = self.position_manager.get_current_price(self.exchange, self.symbol)
        self.current_price = current_price
        # 현재가의 EMA/볼린저밴드 상대 위치 정보 출력
        price_pos_info = self.get_price_position(current_price, ema_low, bb_low_top.iloc[-1], bb_low_mid.iloc[-1], bb_low_down.iloc[-1])
        active_logger.info(f"⚪ 직전추세: {current_trend}, 현재가: {current_price}, EMA: {price_pos_info['closest_ema']}, BB: {price_pos_info['closest_bb']}, BB구간: {price_pos_info['bb_zone']}")

        # 1차 추세 판단(5분봉)
        trend_result_first = self.determine_trend_signal(
            ohlcv_hgh, df_hgh, ema_hgh_series, ema_hgh, bb_hgh_top, bb_hgh_mid, bb_hgh_down, rsi_hgh, current_price, tf_hgh_fast, tf_hgh_medium)
        self.result_first_trend = trend_result_first["trend"]
        bull_divergence_first = trend_result_first["bull_divergence"]
        bear_divergence_first = trend_result_first["bear_divergence"]
        if self.result_first_trend == "uptrend":
            active_logger.info(f"{Colors.GREEN}🟢 1차 추세 : 상승{Colors.END}")   
        elif self.result_first_trend == "downtrend":
            active_logger.info(f"{Colors.RED}🔴 1차 추세 : 하락{Colors.END}")
        else:
            active_logger.info(f"{Colors.YELLOW}⚪ 1차 추세 : 횡보{Colors.END}")

        # 2차 추세 판단(1분봉)
        trend_result_second = self.determine_trend_signal(
            ohlcv_low, df_low, ema_low_series, ema_low, bb_low_top, bb_low_mid, bb_low_down, rsi_low, current_price, tf_low_fast, tf_low_medium)
        self.result_second_trend = trend_result_second["trend"]
        bull_divergence_second = trend_result_second["bull_divergence"]
        bear_divergence_second = trend_result_second["bear_divergence"]
        if self.result_second_trend == "uptrend":
            active_logger.info(f"{Colors.GREEN}🟢 2차 추세 : 상승{Colors.END}")   
        elif self.result_second_trend == "downtrend":
            active_logger.info(f"{Colors.RED}🔴 2차 추세 : 하락{Colors.END}")
        else:
            active_logger.info(f"{Colors.YELLOW}⚪ 2차 추세 : 횡보{Colors.END}")
        
        # 음성 알림 (추세 변화 시)
        # if current_trend != self.result_first_trend and self.result_first_trend in ["uptrend", "downtrend"]:
        #     play_voice_alert_signal("일차", self.result_first_trend)
        # else:
        #     if self.result_second_trend in ["uptrend", "downtrend"]:
        #         play_voice_alert_signal("이차", self.result_second_trend)
        
        # 진입/청산 신호 판단(상위 추세 기반)
        return_position_hgh, return_msg_hgh = self.determine_trade_signal(ohlcv_hgh, df_hgh, ema_hgh_series, ema_hgh, bb_hgh_top, bb_hgh_mid, bb_hgh_down, rsi_hgh, current_price, tf_hgh_fast, tf_hgh_medium)
        active_logger.info(f"⚠️ 상위신호: {return_position_hgh} | {return_msg_hgh}")
        # 진입/청산 신호 판단(하위 추세 기반)
        return_position_low, return_msg_low = self.determine_trade_signal(ohlcv_low, df_low, ema_low_series, ema_low, bb_low_top, bb_low_mid, bb_low_down, rsi_low, current_price, tf_low_fast, tf_low_medium)     
        active_logger.info(f"⚠️ 하위신호: {return_position_low} | {return_msg_low}")
        return_position_msg = f"1차:{return_msg_hgh} , 2차:{return_msg_low}"
        return_close = None # 청산신호 초기화

        # EMA 정렬 추세 체크 (slope 기반)
        ema_position_hgh = technical_indicators.get_ema_position(ema_hgh_series, fast=tf_hgh_fast, medium=tf_hgh_medium)
        ema_hgh_up   = bool(ema_position_hgh == 'uptrend')    
        ema_hgh_down = bool(ema_position_hgh == 'downtrend')
        ema_position_low = technical_indicators.get_ema_position(ema_low_series, fast=tf_low_fast, medium=tf_low_medium)
        ema_low_up   = bool(ema_position_low == 'uptrend')    
        ema_low_down = bool(ema_position_low == 'downtrend')
        active_logger.info(f"[EMA정렬] 5m 상승: {ema_hgh_up}, 1m 상승: {ema_low_up} | 5m 하락: {ema_hgh_down}, 1m 하락: {ema_low_down}")

        # 추세전환 골든크로스/데드크로스 신호
        ema_cross_high = self.detect_ema_cross(ema_hgh_series, fast=tf_hgh_fast, medium=tf_hgh_medium)
        ema_cross_low = self.detect_ema_cross(ema_low_series, fast=tf_low_fast, medium=tf_low_medium)
        active_logger.info(f"[EMA골든크로스/데드크로스] 5m: {ema_cross_high}, 1m: {ema_cross_low}")

        if ema_cross_high == 'long':
            return_position_low = "long"
            return_position_msg = f"매수 전환(5m상승시작 골든크로스 감지) | {return_position_msg}"
        elif ema_cross_low == 'long' and ema_low_up and self.result_second_trend != "downtrend":
            return_position_low = "long"
            return_position_msg = f"매수 전환(1m상승시작 골든크로스 감지) | {return_position_msg}"
        elif ema_cross_high == 'short':
            return_position_low = "short"
            return_position_msg = f"매도 전환(5m하락시작 데드크로스 감지) | {return_position_msg}"
        elif ema_cross_low == 'short' and ema_low_down and self.result_second_trend != "uptrend":
            return_position_low = "short"
            return_position_msg = f"매도 전환(1m하락시작 데드크로스 감지) | {return_position_msg}"

        # 추세전환 - 매도 진입 (상승 후 하락 시작 시점)
        if bear_divergence_first:
            # 1차(5분봉) : 직전 종가가 밴드 고점 위, 직전 RSI > 70, 현재가 < 직전 종가, RSI < 이전 RSI
            prev_close2 = df_hgh['high'].iloc[-2]
            prev_close1 = df_hgh['high'].iloc[-1]
            prev_rsi2   = rsi_hgh.iloc[-2]
            prev_rsi1   = rsi_hgh.iloc[-1]
            prev_bb_up2 = bb_hgh_top.iloc[-2]
            prev_bb_up1 = bb_hgh_top.iloc[-1]
            if prev_close2 > prev_bb_up2 and prev_rsi2 > 70 and prev_close1 < prev_bb_up1 and prev_rsi1 < 70:
                return_position_hgh = "short"
                return_position_msg = f"매도(5m): 직전고가({prev_close2:.4f} → {prev_close1:.4f}), 직전RSI({prev_rsi2:.2f} → {prev_rsi1:.2f}), 밴드고점({prev_bb_up2:.4f} → {prev_bb_up1:.4f}) | {return_position_msg}"
            # 2차(1분봉) : 직전 종가가 밴드 고점 위, 직전 RSI > 70, 현재가 < 직전 종가, RSI < 이전 RSI
            prev_close2 = df_low['high'].iloc[-2]
            prev_close1 = df_low['high'].iloc[-1]
            prev_rsi2   = rsi_low.iloc[-2]
            prev_rsi1   = rsi_low.iloc[-1]
            prev_bb_up2 = bb_low_top.iloc[-2]
            prev_bb_up1 = bb_low_top.iloc[-1]
            if prev_close2 > prev_bb_up2 and prev_rsi2 > prev_rsi1 and prev_rsi2 > 70 and prev_close1 < prev_close2 and current_price < prev_close1 and current_price < prev_bb_up1:
                return_position_low = "short"
                return_position_msg = f"매도(1m): 직전고가({prev_close2:.4f} → {prev_close1:.4f}), 직전RSI({prev_rsi2:.2f} → {prev_rsi1:.2f}), 밴드고점({prev_bb_up2:.4f} → {prev_bb_up1:.4f}) | {return_position_msg}"
            elif prev_close1 > prev_bb_up1 and prev_rsi2 > prev_rsi1 and prev_rsi1 > 65 and current_price < prev_close1 and current_price < prev_bb_up1:
                return_position_low = "short"
                return_position_msg = f"매도(1m): 직전고가({prev_close2:.4f} → {prev_close1:.4f}), 직전RSI({prev_rsi2:.2f} → {prev_rsi1:.2f}), 밴드고점({prev_bb_up2:.4f} → {prev_bb_up1:.4f}) | {return_position_msg}"

            if bear_divergence_second:
                return_position_low = "short"
                return_position_msg = f"매도(1m) RSI하락다이버젼스: 직전고가({prev_close2:.4f} → {prev_close1:.4f}), 직전RSI({prev_rsi2:.2f} → {prev_rsi1:.2f}), 밴드고점({prev_bb_up2:.4f} → {prev_bb_up1:.4f}) | {return_position_msg}"

        # 추세전환 - 매수 진입 (하락 후 반등 시작 시점)
        elif bull_divergence_first:
            # 1차(5분봉) : 직전 저가 < 밴드 하단, 직전 종가 밴드 저점 위, 직전 RSI < 35, 현재가 > 직전 시가, RSI > 이전 RSI
            prev_close2 = df_hgh['low'].iloc[-2]
            prev_close1 = df_hgh['low'].iloc[-1]
            prev_rsi2   = rsi_hgh.iloc[-2]
            prev_rsi1   = rsi_hgh.iloc[-1]
            prev_bb_dn2 = bb_hgh_down.iloc[-2]
            prev_bb_dn1 = bb_hgh_down.iloc[-1]
            if prev_close2 < prev_bb_dn2 and prev_rsi2 < 30 and prev_close1 < prev_bb_dn1 and prev_rsi1 > 30:
                return_position_hgh = "long"
                return_position_msg = f"매수(5m): 직전고가({prev_close2:.4f} → {prev_close1:.4f}), 직전RSI({prev_rsi2:.2f} → {prev_rsi1:.2f}), 밴드고점({prev_bb_up2:.4f} → {prev_bb_up1:.4f}) | {return_position_msg}"
            # 2차(1분봉) : 직전 종가가 밴드 저점 위, 직전 RSI < 30, 현재가 > 직전 시가, RSI > 이전 RSI
            prev_close2 = df_low['low'].iloc[-2]
            prev_close1 = df_low['low'].iloc[-1]
            prev_rsi2   = rsi_low.iloc[-2]
            prev_rsi1   = rsi_low.iloc[-1]
            prev_bb_dn2 = bb_low_down.iloc[-2]
            prev_bb_dn1 = bb_low_down.iloc[-1]
            if prev_close2 < prev_bb_dn2 and prev_rsi2 < 30  and prev_close1 > prev_close2 and current_price > prev_close1 and current_price > prev_bb_dn1:
                return_position_low = "long"
                return_position_msg = f"매수(1m): 직전고가({prev_close2:.4f} → {prev_close1:.4f}), 직전RSI({prev_rsi2:.2f} → {prev_rsi1:.2f}), 밴드고점({prev_bb_up2:.4f} → {prev_bb_up1:.4f}) | {return_position_msg}"
            elif prev_close1 < prev_bb_dn1 and prev_rsi2 < prev_rsi1 and prev_rsi1 < 35 and current_price > prev_close1 and current_price > prev_bb_dn1:
                return_position_low = "long"
                return_position_msg = f"매수(1m): 직전고가({prev_close2:.4f} → {prev_close1:.4f}), 직전RSI({prev_rsi2:.2f} → {prev_rsi1:.2f}), 밴드고점({prev_bb_up2:.4f} → {prev_bb_up1:.4f}) | {return_position_msg}"

            if bull_divergence_second:
                return_position_low = "long"
                return_position_msg = f"매수(1m) RSI상승다이버젼스: 직전고가({prev_close2:.4f} → {prev_close1:.4f}), 직전RSI({prev_rsi2:.2f} → {prev_rsi1:.2f}), 밴드고점({prev_bb_up2:.4f} → {prev_bb_up1:.4f}) | {return_position_msg}"

        else:
            # 연속 양봉/음봉 제한
            is_upper_riding = technical_indicators.detect_consecutive_candles(df_hgh, direction='up', lookback=2)
            is_lower_riding = technical_indicators.detect_consecutive_candles(df_hgh, direction='down', lookback=2)
            if is_upper_riding and return_position_low == "short":
                return_position_msg = f"매도 제한(연속양봉) | {return_position_msg}"
                return_position_low = None
            elif is_lower_riding and return_position_low == "long":
                return_position_msg = f"매수 제한(연속음봉) | {return_position_msg}"
                return_position_low = None
                
            # EMA 정렬 제한
            if ema_hgh_up and ema_hgh_down and return_position_low == "short":
                return_position_msg = f"매도 제한(상승추세) | {return_position_msg}"
                return_position_low = None
            elif ema_hgh_down and ema_low_down and return_position_low == "long":
                return_position_msg = f"매수 제한(하락추세) | {return_position_msg}"
                return_position_low = None

            if ema_hgh_up and return_position_hgh == "short":
                return_position_msg = f"매도 제한(상승추세) | {return_position_msg}"
                return_position_hgh = None
            elif ema_hgh_down and return_position_hgh == "long":
                return_position_msg = f"매수 제한(하락추세) | {return_position_msg}"
                return_position_hgh = None

        # if return_position_hgh is None and return_position_low is None:
        #     if ema_hgh_up and ema_low_up:
        #         return_position_msg = f"매수(상승추세) | {return_position_msg}"
        #         return_position_low = "long"
        #     elif ema_hgh_down and ema_low_down:
        #         return_position_msg = f"매도(하락추세) | {return_position_msg}"
        #         return_position_low = "short"

        # 최종 진입/청산 확인
        if return_position_hgh == "long" or return_position_low == "long":
            active_logger.info(f"{Colors.GREEN}🟢 진입 : 매수 ({current_price}){Colors.END} | {return_position_msg}")
            trade_logger.info(f"🟢 진입 : 매수 | {current_price:.4f} | {return_position_msg}")
            return_position = "long"
            play_voice_alert("매수 신호 발생")
            #send_telegram(f"매수 신호 발생: {current_price} " + return_position_msg)
        elif return_position_hgh == "short" or return_position_low == "short": 
            active_logger.info(f"{Colors.RED}🔴 진입 : 매도 ({current_price}){Colors.END} | {return_position_msg}")
            trade_logger.info(f"🔴 진입 : 매도 | {current_price:.4f} | {return_position_msg}")
            return_position = "short"
            play_voice_alert("매도 신호 발생")
            #send_telegram(f"매도 신호 발생: {current_price} " + return_position_msg)
        else:
            if return_close == "long":
                active_logger.info(f"{Colors.GREEN}🟢 청산 : 매수 ({current_price}){Colors.END} | {return_position_msg}")
                trade_logger.info(f"🟢 청산 : 매수 | {current_price:.4f} | {return_position_msg}")
            elif return_close == "short":
                active_logger.info(f"{Colors.RED}🔴 청산 : 매도 ({current_price}){Colors.END} | {return_position_msg}")
                trade_logger.info(f"🔴 청산 : 매도 | {current_price:.4f} | {return_position_msg}")
            else:
                return_position = None
                active_logger.info(f"⚪ 진입/청산 : 없음 | {return_position_msg}")

        # 최종 추세/진입/청산 신호 반환
        if self.result_first_trend and self.result_first_trend in ["uptrend", "downtrend"]:
            return_trend = self.result_first_trend
        if 'return_close' not in locals():
            return_close = None

        return return_trend, return_position, return_close, current_price
        

    def execute_transaction(self, action: str, close_position: str) -> tuple:
        """
        실제 거래 실행
        action: 'long'/'short'
        """
        success_count = 0
        skipped_count = 0

        if action != "long" and action != "short":
            active_logger.info(f"[거래실행] 실행할 거래가 없습니다. action={action}")
            return success_count, skipped_count
        
        # === 3. 포지션 상태 확인 ===
        positions = self.position_manager.get_all_positions(self.exchange, self.symbol)
        if not positions or not isinstance(positions, tuple) or len(positions) != 2:
            active_logger.error("⚪ 진입/청산 : 없음 | 포지션 데이터 없음")
            return success_count, skipped_count
        (has_long, long_amount, long_price), (has_short, short_amount, short_price) = positions
        #active_logger.info(f"[DEBUG] has_long={has_long}, long_amount={long_amount}, long_price={long_price}, has_short={has_short}, short_amount={short_amount}, short_price={short_price}")
        long_amount = float(long_amount) if has_long else 0.0
        long_price = float(long_price) if has_long else 0.0
        short_amount = float(short_amount) if has_short else 0.0
        short_price = float(short_price) if has_short else 0.0
        #active_logger.info(f"[DEBUG] long_amount(float)={long_amount}, long_price(float)={long_price}, short_amount(float)={short_amount}, short_price(float)={short_price}")

        # === 4. 청산신호 확인 및 실행 ===
        if close_position is not None: # 청산신호만 있을 경우
            if close_position == 'long' and has_long:
                success = self.position_manager.close_position(self.exchange, self.symbol, 'long', long_amount)
                if success:
                    active_logger.info(f"{Colors.GREEN}✓ LONG 포지션 청산 완료!{Colors.END}")
            elif close_position == 'short' and has_short:
                success = self.position_manager.close_position(self.exchange, self.symbol, 'short', short_amount)
                if success:
                    active_logger.info(f"{Colors.RED}✓ SHORT 포지션 청산 완료!{Colors.END}")
        else:
            # 반대 포지션 존재 시 청산 정책 (True: 자동청산, False: 청산안함)
            auto_close_opposite = self.config['trading'].get('auto_close_opposite', False)
            if auto_close_opposite:
                if action == 'long' and has_short:
                    active_logger.info(f"🔄 LONG 진입 → SHORT 포지션 청산 시도, 진입가: {short_price}, 수량: {short_amount}")
                    try:
                        close_result = self.position_manager.close_position(self.exchange, self.symbol, 'short', short_amount)
                        if close_result:
                            active_logger.info(f"{Colors.GREEN}✓ SHORT 포지션 청산 성공!{Colors.END}")
                        else:
                            active_logger.error(f"{Colors.RED}✗ SHORT 포지션 청산 실패!{Colors.END}")
                    except Exception as e:
                        active_logger.error(f"{Colors.RED}✗ SHORT 포지션 청산 예외 발생: {e}{Colors.END}")
                elif action == 'short' and has_long:
                    active_logger.info(f"🔄 SHORT 진입 → LONG 포지션 청산 시도, 진입가: {long_price}, 수량: {long_amount}")
                    try:
                        close_result = self.position_manager.close_position(self.exchange, self.symbol, 'long', long_amount)
                        if close_result:
                            active_logger.info(f"{Colors.GREEN}✓ LONG 포지션 청산 성공!{Colors.END}")
                        else:
                            active_logger.error(f"{Colors.RED}✗ LONG 포지션 청산 실패!{Colors.END}")
                    except Exception as e:
                        active_logger.error(f"{Colors.RED}✗ LONG 포지션 청산 예외 발생: {e}{Colors.END}")

            # 진입 시도 (분할 진입 로직 개선)
            analysis = self.position_manager.get_entry_signal(self.exchange, self.symbol, action, config=self.config)
            if not analysis or not analysis.get('has_signal'):
                active_logger.error(f"{Colors.RED}⚪ 진입가, 익절가, 손절가 생성 실패 (신호 없음 또는 분석 실패){Colors.END}")
                return success_count, skipped_count

            action = 'long' if analysis['type'].upper() == 'LONG' else 'short'
            split_count = int(float(self.config['trading']['entry_split_count']))
            leverage    = float(self.config['trading'].get('leverage', 1))
            amount_mode = self.config['trading'].get('amount_mode', 'margin')
            order_amount_usdt = float(self.config['trading']['order_amount_usdt'])

            # 분할 진입 금액 계산 (레버리지 반영)
            if amount_mode == 'margin':
                split_amount = (order_amount_usdt * leverage) / split_count
            else:
                split_amount = order_amount_usdt / split_count

            # 누적 진입 금액 계산
            total_entry_amount = 0.0
            if action == 'long':
                total_entry_amount = long_amount
            elif action == 'short':
                total_entry_amount = short_amount
            entry_count = int(total_entry_amount // split_amount)
            #active_logger.info(f"[DEBUG] split_amount={split_amount}, total_entry_amount={total_entry_amount}, entry_count={entry_count}")

            # 현재 진입 수량 및 금액 계산 (이번 진입)
            current_entry_price = float(analysis['entry_price'])
            current_sl_price = float(analysis['sl_price']) if 'sl_price' in analysis else 0.0
            current_tp_price = float(analysis['tp_price']) if 'tp_price' in analysis else 0.0
            #active_logger.info(f"[DEBUG] current_entry_price={current_entry_price}, current_sl_price={current_sl_price}, current_tp_price={current_tp_price}")
            current_entry_qty = split_amount / current_entry_price
            #active_logger.info(f"[DEBUG] current_entry_qty={current_entry_qty}")
            total_amount = total_entry_amount

            # 진입 제한 체크 개선
            entry_limit_flag = False
            # 1. 분할 진입 최대 횟수 초과 체크
            if entry_count >= split_count:
                active_logger.info(f"{Colors.YELLOW}⚠️ 분할 진입 최대 횟수({split_count}) 초과 → 진입 거절{Colors.END}")
                entry_limit_flag = True
            # 2. 분할 진입 총액 초과 체크
            max_entry_amount = (order_amount_usdt * leverage) if amount_mode == 'margin' else order_amount_usdt
            #active_logger.info(f"[DEBUG] max_entry_amount={max_entry_amount}")
            if total_amount + split_amount > max_entry_amount:
                active_logger.info(f"{Colors.YELLOW}⚠️ 분할 진입 총액 초과: {(total_amount + split_amount):.2f} > {max_entry_amount:.2f} USDT → 진입 거절{Colors.END}")
                entry_limit_flag = True

            if not entry_limit_flag:
                if not analysis or 'entry_price' not in analysis or 'sl_price' not in analysis:
                    active_logger.error(f"{Colors.RED}✗ 진입 정보(analysis) None 또는 필수값 누락!{Colors.END}")
                    skipped_count += 1
                else:
                    active_logger.info(f"{Colors.BLUE}✓ {action.upper()} 포지션 진입 {entry_count+1}/{split_count}회 시도! (총액: {total_amount+split_amount:.2f} USDT) " \
                                        f"| 진입가: {current_entry_price}, 진입수량: {current_entry_qty:.4f}, 손절가: {analysis['sl_price']}, 익절가: {analysis.get('tp_price'):.4f}{Colors.END}")
                    success = self.position_manager.execute_trade(
                        self.exchange,
                        self.config['trading']['symbol'],
                        action,
                        current_entry_qty,
                        current_entry_price,
                        current_sl_price,
                        current_tp_price,
                        amount_mode=amount_mode,
                        leverage=leverage
                    )
                    if not success:
                        skipped_count += 1
                        active_logger.info(f"{Colors.RED}✗ {action.upper()} 포지션 진입 실패! (execute_trade 실패){Colors.END}")
                    else:
                        success_count += 1
                        active_logger.info(f"{Colors.BLUE}✓ {action.upper()} 포지션 진입 {entry_count+1}/{split_count}회 완료!! (총액: {total_amount+split_amount:.2f} USDT) " \
                                           f"| 진입가: {current_entry_price}, 진입수량: {current_entry_qty:.4f}, 손절가: {analysis['sl_price']:.4f}, 익절가: {analysis.get('tp_price'):.4f}{Colors.END}")
                        #time.sleep(2)  # 진입 간 짧은 대기 시간 (API 과부하 방지)

        return success_count, skipped_count
    
    def determine_trend_signal(self, ohlcv, df: pd.DataFrame, ema_series: dict, ema_vals: dict, df_bb_up: pd.DataFrame, df_bb_ma: pd.DataFrame, df_bb_dn: pd.DataFrame, df_rsi:pd.DataFrame,  current_price: float, tf_fast, tf_medium) -> dict[str, any]:
        """
        상승/하락/횡보 추세인지 판단한다. (방향만 감지)
            # 가격구조(정렬/붕괴) 체크
            # EMA 정렬/추세 체크
            # 볼린저 밴드/RSI 체크
            # 골든크로스/데드크로스 체크
            # 거래량 추세 체크
            # 추세 반전 체크
        df: 캔들 데이터(DataFrame)
        ema_series: EMA 시계열 딕셔너리 {5: Series, ...}
        ema_vals: EMA 마지막값 딕셔너리 {5: float, ...}
        current_price: 실시간 현재가(float)

        return: 추세값(uptrend/downtrend/sideways/complex/crossover), 메시지(str)
        """
        try:
            from sideways.market_structure import MarketStructure
            ms = MarketStructure()

            # 1. 가격구조 체크
            swing_highs, swing_lows, swing_msg = ms.check_trend_by_swing_points(ohlcv)
            structure_up = (swing_highs == 'uptrend')
            structure_down = (swing_lows == 'downtrend')
            #active_logger.info(f"[가격구조] 스윙하이: {structure_up}, 스윙로우: {structure_down} | 고점: {swing_msg['high']} | 저점: {swing_msg['low']}")

            # 1.거래량 중심 체크
            # volume_trend = ms.volume_trend_with_ratio(df, swing_lookback=3, trend_lookback=3, ratio_threshold=0.6)
            # active_logger.info(f"[거래량추세] {volume_trend}")

            # 2.EMA 정렬 체크 (slope 기반)
            ema_position = technical_indicators.get_ema_position(ema_series, fast=tf_fast, medium=tf_medium)
            ema_up = bool(ema_position == 'uptrend')    
            ema_down = bool(ema_position == 'downtrend') 
            #active_logger.info(f"[EMA정렬] 상승: {ema_up}, 하락: {ema_down}")

            # 3.EMA 추세 비율 체크 (float 기반)
            #ema_trend, ema_trend_msg = technical_indicators.get_ema_trend(ema_vals)
            #active_logger.info(f"[EMA비율] {ema_trend}, {ema_trend_msg}")

            # 4.볼린저 밴드 체크
            bb_trend_info = technical_indicators.get_bollinger_trend(df, recent_n=15, band_break_count=1)
            #active_logger.info(f"[BB추세] trend={bb_trend_info['trend']} squeeze={bb_trend_info['is_squeeze']}")
            
            # 밴드타기(상단/하단) 감지 (일반적 셋팅: lookback=10, min_count=7, proximity=0.98)
            #is_upper_riding = technical_indicators.detect_band_riding(df, direction='upper', lookback=3, proximity=0.97)
            #is_lower_riding = technical_indicators.detect_band_riding(df, direction='lower', lookback=3, proximity=0.97)
            #active_logger.info(f"[밴드타기] 상단: {is_upper_riding}, 하단: {is_lower_riding}")

            # 5.연속 양봉/음봉 감지 (일반적 셋팅: lookback=5)
            is_upper_riding = technical_indicators.detect_consecutive_candles(df, direction='up', lookback=3)
            is_lower_riding = technical_indicators.detect_consecutive_candles(df, direction='down', lookback=3)
            #active_logger.info(f"[연속양봉] {is_upper_riding}, [연속음봉] {is_lower_riding}")

            # 6.RSI 추세 체크
            rsi_trend, rsi_strength = technical_indicators.get_rsi_trend(df, recent_n=14)
            #active_logger.info(f"[RSI추세] trend={rsi_trend} strength={rsi_strength}")
            
            # 7.EMA 골든크로스/데드크로스 체크
            ema_cross = self.detect_ema_cross(ema_series, fast=tf_fast, medium=tf_medium)
            #active_logger.info(f"[EMA크로스] : {ema_cross}")

            # 8.RSI 추세 반전 체크
            bull_divergence = False
            bear_divergence = False
            bull_divergence_pre = technical_indicators.detect_rsi_bull_divergence(df_rsi, df['close'], lookback=15) #RSI 강세 다이버전스(최근)
            bull_divergence_low = technical_indicators.detect_rsi_bull_divergence_local(df_rsi, df['close'], lookback=15)        #RSI 강세 다이버전스(전저점)    
            #active_logger.info(f"[다이버전스 DEBUG] bull_divergence_pre={bull_divergence_pre}, bull_divergence_low={bull_divergence_low}, rsi={df_rsi.tail(15).values}, close={df['close'].tail(15).values}")
            if bull_divergence_low or bull_divergence_pre:
                bull_divergence = True
            bear_divergence_pre = technical_indicators.detect_rsi_bear_divergence(df_rsi, df['close'], lookback=15) #RSI 약세 다이버전스(최근)
            bear_divergence_low = technical_indicators.detect_rsi_bear_divergence_local(df_rsi, df['close'], lookback=15)       #RSI 약세 다이버전스(전고점)
            #active_logger.info(f"[다이버전스 DEBUG] bear_divergence_pre={bear_divergence_pre}, bear_divergence_low={bear_divergence_low}, rsi={df_rsi.tail(15).values}, close={df['close'].tail(15).values}")
            if bear_divergence_low or bear_divergence_pre:
                bear_divergence = True
            
            # 9. 스파이크 반전 체크
            spike_result = technical_indicators.detect_spike_reversal(df)
            #active_logger.info(f"[추세반전] spike상승: { spike_result.get('down_reversal')}, spike하락: {spike_result.get('up_reversal')}")

            # 종합 추세 판단
            up_conds = [
                structure_up and not structure_down,
                ema_up and not ema_down,
                (bb_trend_info['trend'] == "uptrend") and not (bb_trend_info['trend'] == "downtrend"),
                (rsi_trend == "uptrend") and not (rsi_trend == "downtrend"),
                (rsi_strength == "strong_up") and not (rsi_strength == "strong_down"),
                is_upper_riding and not is_lower_riding,
                spike_result.get('down_reversal', False) and not spike_result.get('up_reversal', False),
                (ema_cross == 'long'),
                bull_divergence
            ]
            dn_conds = [
                structure_down and not structure_up,
                ema_down and not ema_up,
                (bb_trend_info['trend'] == "downtrend") and not (bb_trend_info['trend'] == "uptrend"),
                (rsi_trend == "downtrend") and not (rsi_trend == "uptrend"),
                (rsi_strength == "strong_down") and not (rsi_strength == "strong_up"),
                is_lower_riding and not is_upper_riding,
                spike_result.get('up_reversal', False) and not spike_result.get('down_reversal', False),
                (ema_cross == 'short'),
                bear_divergence
            ]
            up_count = sum(up_conds)
            down_count = sum(dn_conds)

            def to_text(val, up_text="O", down_text="X"):
                return up_text if val else down_text
            active_logger.info(
                f"[상승조건] 스윙하이= {to_text(structure_up and not structure_down)}, EMA정렬= {to_text(ema_up and not ema_down)}, BB추세= {to_text((bb_trend_info['trend'] == 'uptrend') and not (bb_trend_info['trend'] == 'downtrend'))}," \
                f" RSI추세= {to_text((rsi_trend == 'uptrend') and not (rsi_trend == 'downtrend'))}, RSI강도= {to_text((rsi_strength == 'strong_up') and not (rsi_strength == 'strong_down'))}," \
                f" 연속봉= {to_text(is_upper_riding and not is_lower_riding)}, 스파이크= {to_text(spike_result.get('down_reversal', False) and not spike_result.get('up_reversal', False))}, EMA크로스= {to_text((ema_cross == 'long'))}, RSI강세다이버전스= {to_text(bull_divergence)}"
            )
            active_logger.info(
                f"[하락조건] 스윙로우= {to_text(structure_down and not structure_up)}, EMA정렬= {to_text(ema_down and not ema_up)}, BB추세= {to_text((bb_trend_info['trend'] == 'downtrend') and not (bb_trend_info['trend'] == 'uptrend'))}," \
                f" RSI추세= {to_text((rsi_trend == 'downtrend') and not (rsi_trend == 'uptrend'))}, RSI강도= {to_text((rsi_strength == 'strong_down') and not (rsi_strength == 'strong_up'))}," \
                f" 연속봉= {to_text(is_lower_riding and not is_upper_riding)}, 스파이크= {to_text(spike_result.get('up_reversal', False) and not spike_result.get('down_reversal', False))}, EMA크로스= {to_text((ema_cross == 'short'))}, RSI약세다이버전스= {to_text(bear_divergence)}"
            )
            active_logger.info(f"[종합조건] 상승조건 = {up_count} 하락조건 = {down_count}")

            if up_count > down_count and up_count >= 2:
                #active_logger.info(f"{Colors.GREEN}🟢 추세 : 상승{Colors.END}")   
                return_trend = "uptrend"
            elif down_count > up_count and down_count >= 2:
                #active_logger.info(f"{Colors.RED}🔴 추세 : 하락{Colors.END}")
                return_trend = "downtrend"
            else:
                #active_logger.info(f"{Colors.YELLOW}⚪ 추세 : 횡보{Colors.END}")
                return_trend = "sideways"
           
            return {
                "trend": return_trend,
                "bull_divergence": bull_divergence,
                "bear_divergence": bear_divergence
            }

        except Exception as e:
            active_logger.error(f"[에러]추세 실패: {e}")
            return {
                "trend": "",
                "bull_divergence": False,
                "bear_divergence": False,
                "error": f"[에러]추세 실패: {e}"
            }


    def determine_trade_signal(self, ohlcv, df: pd.DataFrame, ema_series: dict, ema_vals: dict, df_bb_up: pd.DataFrame, df_bb_ma: pd.DataFrame, df_bb_dn: pd.DataFrame, df_rsi:pd.DataFrame,  current_price: float, tf_fast, tf_medium) -> str:
        # 1. 지지선/저항선 체크 2. 전저점/전고점 체크 3. 거래량 중심 체크 4. 현재가 위치 체크 6. 밴드폭 통계 조회
        return_position = None
        return_msg = ""

        band_position_lower = False # 볼린저밴드 하단 위치 
        band_position_upper = False # 볼린저밴드 상단 위치 
        band_position_belowlow   = False # 볼린저밴드 하단 아래 위치
        band_position_aboveupper = False # 볼린저밴드 상단 위 위치
        resistance_breakup  = False # 저항선 돌파 신호(상승)
        support_breakdown   = False # 지지선 파괴 신호(하락)
        volume_breakup      = False # 거래량 중심 돌파 신호(상승)
        volume_breakdown    = False # 거래량 중심 파괴 신호(하락)
        prev_volume_up      = False # 이전 거래량 상승 여부 초기화
        prev_high_price = None # 이전 고점 초기화
        prev_low_price  = None # 이전 저점 초기화

        # 현재가 위치 체크
        price_position = self.get_price_position(current_price, ema_vals, df_bb_up.iloc[-1], df_bb_ma.iloc[-1], df_bb_dn.iloc[-1])
        band_position_belowlow   = True if price_position['bb_zone'] == "below_lower" else False
        band_position_aboveupper = True if price_position['bb_zone'] == "above_upper" else False
        band_position_lower      = True if price_position['closest_bb'] == "lower" else False
        band_position_upper      = True if price_position['closest_bb'] == "upper" else False

        # 동적 지지선/저항선 체크
        dynamic_support, dynamic_resistance = self.get_dynamic_support_resistance(current_price, ema_vals, df_bb_up.iloc[-1], df_bb_ma.iloc[-1], df_bb_dn.iloc[-1])
        dyn_sup_val = f"{dynamic_support[0]:.4f}" if dynamic_support[0] is not None else "-"
        dyn_res_val = f"{dynamic_resistance[0]:.4f}" if dynamic_resistance[0] is not None else "-"
        active_logger.info(f"[동적 지지/저항] 지지선: {dynamic_support[1]}, {dyn_sup_val}, 저항선: {dynamic_resistance[1]}, {dyn_res_val}")
        support_price = dynamic_support[0]
        resistance_price = dynamic_resistance[0]
        support_breakdown, resistance_breakup = self.get_position_signal(
            support_price, resistance_price, current_price
        )

        # 이전 고점/저점 조회 (swing point 기반)
        prev_high_price, prev_low_price = MarketStructure().get_previous_high_low(ohlcv)
        #active_logger.info(f"[전저점/전고점]  현재가: {current_price}, 전저점: {prev_high_price}, 전고점: {prev_low_price}")
        support_breakdown, resistance_breakup = self.get_position_signal(prev_high_price, prev_low_price, current_price)

        # 주요 거래량 체크
        volume_trend, prev_volume_up = self.get_price_volume(df, current_price, df_bb_up, df_bb_dn, df_rsi, ratio_threshold=2.8)
        if volume_trend == "breakup":     # 거래량 돌파 신호, 가격상승
            volume_breakup = True
        elif volume_trend == "breakdown": # 거래량 파괴 신호, 가격하락
            volume_breakdown = True

        # 밴드폭 통계 조회 (변화율은 직전 대비)
        band_bandwidth = False
        bandwidth_stats = self.get_bandwidth_stats(df_bb_up, df_bb_dn, df_bb_ma, window=20)
        # 밴드 하단 매수~상단 청산 시 예상 수익률 계산
        band_upper = float(df_bb_up.iloc[-1])
        band_lower = float(df_bb_dn.iloc[-1])
        if band_lower > 0:
            expected_return = (band_upper - band_lower) / band_lower * 100
        active_logger.info(f"[밴드폭] 현재:{bandwidth_stats['current_bandwidth']:.4f}, 평균:{bandwidth_stats['mean_bandwidth']:.4f}, " \
                           f"비율:{bandwidth_stats['bandwidth_ratio']:.2f}, 변화율:{bandwidth_stats['bandwidth_change']:.2%}, " \
                           f"밴드값:{df_bb_up.iloc[-1]:.4f}, {df_bb_ma.iloc[-1]:.4f}, {df_bb_dn.iloc[-1]:.4f}, RSI: {df_rsi.iloc[-1]:.4f}, " \
                           f"밴드폭 수익률 {expected_return:.2f}%")
        if bandwidth_stats['bandwidth_ratio'] is not None:
            if bandwidth_stats['bandwidth_ratio'] >= 1.0 and bandwidth_stats['bandwidth_change'] > 15:
                band_bandwidth = True # 진입신호 허용
        
        # 1.밴드폭 확대, 거래량 폭증 신호 결정
        if band_bandwidth:
            # 지지선/저항선 및 거래량 신호 처리
            if (resistance_breakup or volume_breakup):
                return "long", "⭐️ 밴드폭 확대 및 저항선 신호로 매수"
            elif (support_breakdown or volume_breakdown):
                return "short", "⭐️ 밴드폭 확대 및 지지선 신호로 매도"
            # 동적 지지선/저항선 미존재 신호 결정
            if dyn_res_val == "-":
                return "long", "⭐️ 밴드폭 확대 및 저항선 미존재 신호로 매수"                
            elif dyn_sup_val == "-":
                return "short", "⭐️ 밴드폭 확대 및 지지선 미존재 신호로 매도"
            
        # 2.볼린저밴드 위치 기반(예외 신호) 결정
        rsi_trend, rsi_strength = technical_indicators.get_rsi_trend(df, recent_n=14) # RSI 추세 체크
        
        if band_position_lower: # 볼린저밴드 하단 위치 신호(상승)
            # RSI 강세 다이버전스 감지
            bull_divergence = technical_indicators.detect_rsi_bull_divergence(df_rsi, df['close'], lookback=15)
            if bull_divergence and (rsi_trend == "uptrend" or rsi_strength == 'strong_up'):
                 return "long", f"⭐️ RSI 추세상승 및 강세 다이버전스(최근)"

            # 직전거래량 급증 확인
            if prev_volume_up:
                spike_result = technical_indicators.detect_spike_reversal(df)
                if spike_result.get('down_reversal'):
                    return "long", "⭐️ 스파이크 반전 패턴 감지로 매수"
                elif spike_result.get('up_reversal') :
                    return "short", "⭐️ 스파이크 반전 패턴 감지로 매도"
            
        elif band_position_upper: # 볼린저밴드 상단 위 위치 신호(하락)
            # RSI 약세 다이버전스 감지
            bear_divergence = technical_indicators.detect_rsi_bear_divergence(df_rsi, df['close'], lookback=15)
            if bear_divergence and (rsi_trend == "downtrend" or rsi_strength == 'strong_down'):
                return "short", f"⭐️ RSI 추세하락 및 약세 다이버전스(최근)"

            # 직전거래량 급증 확인
            if prev_volume_up:
                spike_result = technical_indicators.detect_spike_reversal(df)
                if spike_result.get('down_reversal'):
                    return "long", "⭐️ 스파이크 반전 패턴 감지로 매수"
                elif spike_result.get('up_reversal') :
                    return "short", "⭐️ 스파이크 반전 패턴 감지로 매도"
            
        # 연속 양봉/음봉 감지
        is_upper_riding = technical_indicators.detect_consecutive_candles(df, direction='up', lookback=2)
        is_lower_riding = technical_indicators.detect_consecutive_candles(df, direction='down', lookback=2)
        rsi_last = df_rsi.iloc[-1] if hasattr(df_rsi, 'iloc') else df_rsi[-1]
        rsi_last2 = df_rsi.iloc[-2] if hasattr(df_rsi, 'iloc') else df_rsi[-2]
          
        # 3.볼린저밴드 상단/하단 근접 여부 (예: 1% 이내)
        upper_band = float(df_bb_up.iloc[-1])
        lower_band = float(df_bb_dn.iloc[-1])
        is_near_upper_band = abs(current_price - upper_band) / upper_band < 0.01
        is_near_lower_band = abs(current_price - lower_band) / lower_band < 0.01

        # 저항선/지지선 및 거래량 신호 처리 (상단/하단 모두 대응)
        if resistance_breakup and volume_breakup:
            if rsi_last >= 65 and rsi_last < rsi_last2 and is_near_upper_band and current_price < df['close'].iloc[-1]:
                # 과매수+고점 돌파 후 매도 (반전 또는 익절)
                return "short", f"과매수+고점 돌파 후 매도 (저항선반전: {resistance_breakup}, 거래량반전: {volume_breakup})"
            elif rsi_last < 65 and is_upper_riding and current_price > df['close'].iloc[-1]:
                # 정상적인 돌파 매수
                return "long", f"연속 양봉 매수(저항선돌파: {resistance_breakup}, 거래량돌파: {volume_breakup})"
        elif support_breakdown and volume_breakdown:
            if rsi_last <= 35 and rsi_last > rsi_last2 and is_near_lower_band and current_price > df['close'].iloc[-1]:
                # 과매도+저점 돌파 후 매수 (반전 또는 저점 매수)
                return "long", f"과매도+저점 돌파 후 매수 (지지선반전: {support_breakdown}, 거래량반전: {volume_breakdown})"
            elif rsi_last > 35 and rsi_last <= rsi_last2 and is_lower_riding and current_price < df['close'].iloc[-1]:
                # 정상적인 돌파 매도
                return "short", f"연속 음봉 매도(지지선반전: {support_breakdown}, 거래량반전: {volume_breakdown})"

        # 4.신호 결정 (일반조건: 밴드값, RSI, 거래량 기반)
        if return_position is None:
            if volume_breakup and rsi_last < 60 and is_upper_riding:                # 거래량 돌파 신호(상승)
                return_position = "long"
                return_msg = "거래량 돌파 신호로 매수"
            elif volume_breakdown and rsi_last > 40 and is_lower_riding:             # 거래량 파괴 신호(하락)
                return_position = "short"
                return_msg = "거래량 파괴 신호로 매도"                                

        return return_position, return_msg
    

    def get_price_volume(self, df, current_price, bb_up, bb_dn, rsi, ratio_threshold=2.8) -> tuple:
        """
        주요 가격대 및 거래량 분석 (전저점/전고점, 최대 거래량, 진입 조건 등)
        결과: 돌파/파괴 신호 반환
             breakup, breakdown
        """
        return_value = None # 현재가와 직전거래량, 최근 최대거래량 캔들과 가격대 비교 결과(돌파/파괴 신호)

        # 전저점/전고점 체크 (window_size 기준)
        fetch_size = self.window_size - 1
        df['prev_low'] = df['low'].shift(1).rolling(window=fetch_size).min()
        df['prev_high'] = df['high'].shift(1).rolling(window=fetch_size).max()
        prev_low_price = df['prev_low'].iloc[-1]
        prev_high_price = df['prev_high'].iloc[-1]
        #active_logger.info(f"[전저점/전고점] 현재가={current_price}, 저점={prev_low_price}, 고점={prev_high_price}, size={fetch_size}")

        # 거래량이 가장 큰 캔들 인덱스
        vol_idx = df['volume'].idxmax()
        max_vol_price = df.loc[vol_idx, 'close']  # 종가
        max_vol_high = df.loc[vol_idx, 'high']    # 고가
        max_vol_low = df.loc[vol_idx, 'low']      # 저가
        #active_logger.info(f"[거래량 최대] 종가={max_vol_price}, 고가={max_vol_high}, 저가={max_vol_low}")

        # 최근 3시간(180개) 중 최대 거래량 캔들의 거래량이 평균 거래량의 2배 이상인지
        avg_volume = df['volume'].iloc[-fetch_size:].mean()
        max_volume = df['volume'].iloc[-fetch_size:].max()
        #active_logger.info(f"[최대거래량] 거래량={max_volume}, 평균거래량={avg_volume:.2f}, 종가={max_vol_price}, 배율2체크={max_volume >= (avg_volume * 2)}")

        # 직전 캔들과 현재가의 거래량 밴드/RSI 값 출력 및 진입 조건 체크
        last_vol_price = df.iloc[-1]['close']  # 종가
        last_vol_high_price = df.iloc[-1]['high']  
        last_vol_low_price = df.iloc[-1]['low']     
        last_volume = df.iloc[-1]['volume']
        last_volume_up = last_volume >= (avg_volume * ratio_threshold)
        active_logger.info(f"[직전거래량] 거래량={last_volume}, 평균={avg_volume:.2f}, 배율*{ratio_threshold}={(avg_volume * ratio_threshold):.2f}, 종가:{last_vol_price}, 현재가:{current_price}")

        if last_volume >= (avg_volume * ratio_threshold) and current_price > last_vol_price:
            if current_price < prev_low_price:
                return_value = "breakdown"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 거래량 급증 돌파가 전저점 아래에서 발생. 추가 하락 신호 생성.")   
            if current_price > prev_high_price:
                return_value = "breakup"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 거래량 급증 돌파가 전고점 위에서 발생. 추가 상승 신호 생성.")
            if current_price > max_vol_price:
                return_value = "breakup"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 거래량 급증 돌파가 최대거래량 캔들 종가 위에서 발생. 추가 상승 신호 생성.")
            if current_price < max_vol_price:
                return_value = "breakdown"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 거래량 급증 돌파가 최대거래량 캔들 종가 아래에서 발생. 추가 하락 신호 생성.") 
            if last_vol_price > max_vol_price:
                return_value = "breakup"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 종가가 최대거래량 캔들 종가 위에서 발생. 추가 상승 신호 생성.")   
        if last_volume >= (avg_volume * ratio_threshold) and current_price < last_vol_price:
            if current_price < prev_low_price:
                return_value = "breakdown"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 거래량 급증 파괴가 전저점 아래에서 발생. 추가 하락 신호 생성.")   
            if current_price > prev_high_price:
                return_value = "breakup"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 거래량 급증 파괴가 전고점 위에서 발생. 추가 상승 신호 생성.")
            if current_price > max_vol_price:
                return_value = "breakup"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 거래량 급증 파괴가 최대거래량 캔들 종가 위에서 발생. 추가 상승 신호 생성.")
            if current_price < max_vol_price:
                return_value = "breakdown"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 거래량 급증 파괴가 최대거래량 캔들 종가 아래에서 발생. 추가 하락 신호 생성.") 
            if last_vol_price > max_vol_price:
                return_value = "breakup"
                active_logger.info(f"[신호 발생] 최근 직전 캔들 종가가 최대거래량 캔들 종가 위에서 발생. 추가 상승 신호 생성.")   
            
        return return_value, last_volume_up


    def get_price_position(self, price, ema_dict, bb_upper, bb_middle, bb_lower):
        """
        현재가가 EMA(5,20,60,120,200)와 볼린저밴드(상단, 중간, 하단) 중 어디에 가까운지,
        그리고 어느 구간(upper~middle, middle~lower)에 위치하는지 반환
        """
        try:
            # EMA와의 거리 계산
            ema_distances = {period: abs(price - ema_dict[period]) for period in ema_dict}
            closest_ema = min(ema_distances, key=ema_distances.get)
        except Exception as e:
            active_logger.error(f"[에러][get_price_position] EMA dict 접근 오류: {e}, ema_dict keys: {list(ema_dict.keys())}")
            return None

        # 볼린저밴드 구간 판별
        if price >= bb_upper:
            bb_zone = "above_upper"
        elif price >= bb_middle:
            bb_zone = "upper_to_middle"
        elif price >= bb_lower:
            bb_zone = "middle_to_lower"
        else:
            bb_zone = "below_lower"

        # 볼린저밴드와의 거리
        bb_distances = {
            "upper": abs(price - bb_upper),
            "middle": abs(price - bb_middle),
            "lower": abs(price - bb_lower)
        }
        closest_bb = min(bb_distances, key=bb_distances.get)

        return {
            "closest_ema": closest_ema,
            "closest_bb": closest_bb,
            "bb_zone": bb_zone
        }
        
    def get_dynamic_support_resistance(self, price, ema_dict, bb_upper, bb_middle, bb_lower):
        """
        현재가 기준 가장 가까운 동적 지지선/저항선(EMA, 볼린저밴드) 반환
        (값, 이름) 튜플로 반환
        """
        candidates = []
        for period, val in ema_dict.items():
            candidates.append((val, str(period)))
        candidates.extend([
            (bb_upper, "upper"),
            (bb_middle, "middle"),
            (bb_lower, "lower")
        ])
        resistances = [(v, n) for v, n in candidates if v > price]
        supports = [(v, n) for v, n in candidates if v < price]
        resistance = min(resistances, key=lambda x: x[0]) if resistances else (None, None)
        support = max(supports, key=lambda x: x[0]) if supports else (None, None)
        return support, resistance

    def get_bandwidth_stats(self, bb_upper, bb_lower, bb_middle, window=20):
        """
        볼린저밴드 밴드폭의 시계열 평균 대비 현재 밴드폭 비율,
        최근 밴드폭의 증가/감소폭(변화율) 반환
        - bb_upper, bb_lower, bb_middle: Series (밴드)
        - window: 평균 계산 구간
        밴드폭 비율 해석 가이드:
            1.0 이하: 평소 수준(평균 밴드폭과 비슷)
            1.5 이상: 변동성 확대 시작(주의)
            2.0 이상: 강한 변동성 확장(추세 돌파, 급등락 가능성 높음)
            3.0 이상: 매우 이례적, 과매수/과매도 및 변동성 피크 구간 가능
        변화율 해석 가이드:
            직전 캔들 대비 밴드폭이 3.28% 증가했다는 의미입니다.
             (0보다 크면 밴드가 넓어지는 중, 0보다 작으면 좁아지는 중)
        return: dict { 'current_bandwidth': float, 'mean_bandwidth': float, 'bandwidth_ratio': float, 'bandwidth_change': float }
          예시: stats = self.get_bandwidth_stats(bb_low_top, bb_low_down, bb_low_mid, window=20)
                active_logger.info(f"[밴드폭] 현재:{stats['current_bandwidth']:.4f}, 평균:{stats['mean_bandwidth']:.4f}, 비율:{stats['bandwidth_ratio']:.2f}, 변화율:{stats['bandwidth_change']:.2%}")
        """
        # 밴드폭 시계열
        bandwidth_series = (bb_upper - bb_lower) / bb_middle
        # 최근 window개 평균
        mean_bandwidth = bandwidth_series.iloc[-window:].mean()
        # 현재 밴드폭
        current_bandwidth = bandwidth_series.iloc[-1]
        # 현재 밴드폭/평균 비율
        bandwidth_ratio = current_bandwidth / mean_bandwidth if mean_bandwidth != 0 else None
        # 최근 밴드폭 변화율 (직전 대비)
        if len(bandwidth_series) >= 2:
            prev_bandwidth = bandwidth_series.iloc[-2]
            bandwidth_change = (current_bandwidth - prev_bandwidth) / prev_bandwidth if prev_bandwidth != 0 else None
        else:
            bandwidth_change = None

        # if bandwidth_ratio >= 3.0 and bandwidth_change > 10:
        #     active_logger.info(f"[밴드폭 신호] 밴드폭 비율이 3.0 이상으로 매우 이례적인 변동성 피크 구간 ==> ⭐️ 청산 신호 발생.")
        # elif bandwidth_ratio >= 2.0:
        #     active_logger.info(f"[밴드폭 신호] 밴드폭 비율이 2.0 이상으로 강한 변동성 확장 구간 ==> ⭐️ 추세 돌파 및 급등락 가능성 높음.")
        # elif bandwidth_ratio >= 1.0:
        #     active_logger.info(f"[밴드폭 신호] 밴드폭 비율이 1.0 이상으로 변동성 확대 시작 구간 ==> ⭐️ 주의 필요.")            

        return {
            'current_bandwidth': current_bandwidth,
            'mean_bandwidth': mean_bandwidth,
            'bandwidth_ratio': bandwidth_ratio,
            'bandwidth_change': bandwidth_change
        }

    def get_position_signal(self, support_price, resistance_price, current_price):
        """
        지지선/저항선 기반 포지션 전환 신호 함수
        입력: support_price, resistance_price, current_price
        출력: (support_breakdown, resistance_breakup) (tuple of bool)
        """
        support_breakdown = False  # 지지선 파괴 신호
        resistance_breakup = False # 저항선 돌파 신호

        # None 처리 안전하게 비교
        if support_price is None and resistance_price is not None:  # 지지선이 없을 때(강한 상승시)
            if resistance_price is not None and current_price > resistance_price:
                resistance_breakup = True
        elif resistance_price is None and support_price is not None: # 저항선이 없을 때(강한 하락시)
            if support_price is not None and current_price < support_price:
                support_breakdown = True
        elif support_price is not None and resistance_price is not None: # 둘 다 있을 때
            if current_price > resistance_price:
                resistance_breakup = True
            elif current_price < support_price:
                support_breakdown = True
            else:
                diff_support = current_price - support_price
                diff_resistance = resistance_price - current_price
                # 지지선에 더 가까움
                if diff_resistance > diff_support > 0:
                    if current_price < support_price:
                        support_breakdown = True
                    elif current_price > resistance_price:
                        resistance_breakup = True
                else: # 저항선에 더 가까움
                    if current_price > resistance_price:
                        resistance_breakup = True
                    elif current_price < support_price:
                        support_breakdown = True
        # 모두 None이거나 둘 다 None이면 신호 없음

        return support_breakdown, resistance_breakup

    def get_pullback_signal(self, ind: dict, bb_up: bool, bb_down: bool, current_price: float, current_trend: str, fast=None, medium=None):
        """
        Wrapper for pullback/cross entry signal detection. Returns 'long', 'short', or None.
        """
        # EMA 골든/데드크로스 우선
        cross_signal = self.detect_ema_cross(ind, fast, medium)
        if cross_signal:
            return cross_signal
        
        # Pullback(되돌림) 진입 신호
        pullback_signal = self.detect_pullback_entry(ind, bb_up, bb_down, current_price, current_trend, fast, medium)
        if pullback_signal:
            return pullback_signal
        return None
        

    # --- Entry Signal Logic: Module-level functions for cross and pullback detection ---
    def detect_ema_cross(self, ind: dict, fast=None, medium=None) -> str:
        """
        EMA 골든/데드크로스 진입 신호 감지
        Returns: 'long' (골든크로스), 'short' (데드크로스), or None
        """
        if fast is None or medium is None:
            strategy_cfg = self.config.get("strategy", {})
            fast = strategy_cfg.get("signal_ema", {}).get("first", 3)
            medium = strategy_cfg.get("signal_ema", {}).get("second", 7)

        ema_fast = ind.get(fast)
        ema_medium = ind.get(medium)
        if ema_fast is None or ema_medium is None:
            logging.info(f"[detect_ema_cross] EMA dict에 키 없음: fast={fast}, medium={medium}, 사용가능키={list(ind.keys())}")
            return None

        ema_fast_prev = ema_fast.iloc[-2] if hasattr(ema_fast, 'iloc') and len(ema_fast) > 1 else ema_fast
        ema_medium_prev = ema_medium.iloc[-2] if hasattr(ema_medium, 'iloc') and len(ema_medium) > 1 else ema_medium
        ema_fast_now = ema_fast.iloc[-1] if hasattr(ema_fast, 'iloc') else ema_fast
        ema_medium_now = ema_medium.iloc[-1] if hasattr(ema_medium, 'iloc') else ema_medium
        #logging.info(f"[EMA 크로스] 이전값: EMA{fast}={ema_fast_prev:.4f}, EMA{medium}={ema_medium_prev:.4f} | 현재값: EMA{fast}={ema_fast_now:.4f}, EMA{medium}={ema_medium_now:.4f}")
        if ema_fast_prev <= ema_medium_prev and ema_fast_now > ema_medium_now:
            return 'long'
        if ema_fast_prev >= ema_medium_prev and ema_fast_now < ema_medium_now:
            return 'short'
        return None

    def detect_pullback_entry(self, ind: dict, bb_up: bool, bb_down: bool, current_price: float, current_trend: str, fast=None, medium=None) -> str:
        """
        EMA/볼린저밴드/RSI/거래량 기반 Pullback(되돌림) 진입 신호 감지 (안전 접근)
        Returns: 'long', 'short', or None
        """
        try:
            strategy_cfg = self.config.get("strategy", {})
            rsi_oversold = strategy_cfg.get("rsi", {}).get("oversold", 30)
            rsi_overbought = strategy_cfg.get("rsi", {}).get("overbought", 70)

            # EMA 값
            ema_fast = ind.get(fast)
            ema_medium = ind.get(medium)
            if ema_fast is None or ema_medium is None:
                return None
            ema_fast = ema_fast.iloc[-1] if hasattr(ema_fast, 'iloc') else ema_fast
            ema_medium = ema_medium.iloc[-1] if hasattr(ema_medium, 'iloc') else ema_medium
            # RSI
            rsi_series = ind.get('rsi')
            if rsi_series is None:
                return None
            rsi = rsi_series.iloc[-1] if hasattr(rsi_series, 'iloc') else rsi_series
            prev_rsi = rsi_series.iloc[-2] if hasattr(rsi_series, 'iloc') and len(rsi_series) > 1 else rsi
            # 볼린저밴드
            bb_lower = ind.get('bb_lower')
            bb_upper = ind.get('bb_upper')
            bb_middle = ind.get('bb_middle')
            bb_lower = bb_lower.iloc[-1] if hasattr(bb_lower, 'iloc') else bb_lower
            bb_upper = bb_upper.iloc[-1] if hasattr(bb_upper, 'iloc') else bb_upper
            bb_middle = bb_middle.iloc[-1] if hasattr(bb_middle, 'iloc') else bb_middle
            # 거래량
            volume = ind.get('volume')
            volume_ma = ind.get('volume_ma')
            vol_val = volume.iloc[-1] if hasattr(volume, 'iloc') else volume if volume is not None else None
            vol_ma_val = volume_ma.iloc[-1] if hasattr(volume_ma, 'iloc') else volume_ma if volume_ma is not None else None
            # volume_spike
            volume_spike = False
            if volume is not None and volume_ma is not None and 'check_volume_spike' in globals():
                try:
                    volume_spike = bool(technical_indicators.check_volume_spike(volume, volume_ma))
                except Exception:
                    volume_spike = False

            # uptrend: 되돌림 매수 진입
            if current_trend == 'uptrend':
                pullback_entry = bool(ema_medium <= current_price <= ema_fast * 1.001)
                rsi_rebound = bool(rsi > rsi_oversold and rsi > prev_rsi)
                bb_recover = False
                if bb_lower is not None and bb_middle is not None:
                    bb_recover = bool(current_price > bb_lower and current_price < bb_middle)
                if pullback_entry and bb_down and (volume_spike or rsi_rebound or bb_recover):
                    return 'long'
            # downtrend: 되돌림 매도 진입
            elif current_trend == 'downtrend':
                pullback_entry = bool(ema_fast * 0.999 <= current_price <= ema_medium)
                rsi_rebound = bool(rsi < rsi_overbought and rsi < prev_rsi)
                bb_recover = False
                if bb_upper is not None and bb_middle is not None:
                    bb_recover = bool(current_price < bb_upper and current_price > bb_middle)
                if pullback_entry and bb_up and (volume_spike or rsi_rebound or bb_recover):
                    return 'short'
            return None
        except Exception as e:
            active_logger.error(f"풀백 진입 신호 오류: {str(e)}")
            return None
