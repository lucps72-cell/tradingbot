import datetime
import time
import ccxt
import pandas as pd

from ast import Dict
from typing import Optional, Tuple
from sideways.color_utils import Colors
from sideways.config_loader import load_config
import logging
active_logger = logging.getLogger(__name__)
active_logger.setLevel(logging.DEBUG)
trade_logger = logging.getLogger("trade")

class PositionManager:
    """포지션 관리 클래스."""
    def __init__(self, exchange=None, symbol=None, config=None):
        self.position = {'long': None, 'short': None}
        self.config = config
        if exchange is not None and symbol is not None:
            self.fetch_and_set_position(exchange, symbol)
            
    def get_current_price(self, exchange, symbol: str) -> float:
        """
        거래소에서 실시간 현재가를 조회한다.
        """        
        try:
            ticker = exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            print(f"[에러]실시간 현재가 조회 실패: {e}")
        return None

    def fetch_and_set_position(self, exchange, symbol):
        """
        거래소에서 롱/숏 포지션을 모두 조회해서 self.position에 저장합니다.
        Bybit/CCXT/v2 방식 참고.
        """
        try:
            pos_result = self.get_all_positions(exchange, symbol)
            if not pos_result or not isinstance(pos_result, tuple) or len(pos_result) != 2:
                active_logger.info("[get_all_positions] 포지션 없음")
                self.position = ((None, 0.0, None), (None, 0.0, None))
                return self.position

            (current_long, long_amount, long_entry), (current_short, short_amount, short_entry) = pos_result
            sl_price = None
            tp_price = None

            # 롱 포지션 tp/sl 동기화
            if current_long == 'long' and long_amount > 0:
                # TP/SL 정보 읽기
                try:
                    orders = exchange.fetch_open_orders(symbol, params={"recv_window": 30000})
                    for order in orders:
                        #active_logger.info(f"주문 정보: {order}")
                        # 익절가/손절가 추출
                        tp_candidate = order.get('takeProfitPrice')
                        sl_candidate = order.get('stopLossPrice')
                        #active_logger.info(f"order.get('side') : {order.get('side')}, order['type'] : {order['type']}, tp_candidate 정보: {tp_candidate}, sl_candidate 정보: {sl_candidate}")
                        if order['type'] in ['market', 'limit'] and order.get('side') == 'sell':
                            if tp_candidate is not None and tp_price is None:
                                try:
                                    tp_price = float(tp_candidate)
                                except Exception:
                                    pass
                            if sl_candidate is not None and sl_price is None:
                                try:
                                    sl_price = float(sl_candidate)
                                except Exception:
                                    pass
                except Exception as e:
                    active_logger.error(f"[fetch_open_orders] tp/sl 조회 오류: {e}")
                    pass
                self.position['long'] = {'side': 'long', 'entry_price': long_entry, 'size': abs(long_amount), 'sl_price': sl_price, 'tp_price': tp_price}
                #active_logger.info(f"'side': 'long', 'entry_price': {long_entry}, 'size': {abs(long_amount)}, 'sl_price': {sl_price}, 'tp_price': {tp_price}")
            
            # 숏 포지션 tp/sl 동기화
            if current_short == 'short' and short_amount > 0:
                try:
                    orders = exchange.fetch_open_orders(symbol, params={"recv_window": 30000})
                    for order in orders:
                        #active_logger.info(f"주문 정보: {order}")
                        # 익절가/손절가 추출
                        tp_candidate = order.get('takeProfitPrice')
                        sl_candidate = order.get('stopLossPrice')
                        #active_logger.info(f"order.get('side') : {order.get('side')}, order['type'] : {order['type']}, tp_candidate 정보: {tp_candidate}, sl_candidate 정보: {sl_candidate}")
                        if order['type'] in ['market', 'limit'] and order.get('side') == 'buy':
                            if tp_candidate is not None and tp_price is None:
                                try:
                                    tp_price = float(tp_candidate)
                                except Exception:
                                    pass
                            if sl_candidate is not None and sl_price is None:
                                try:
                                    sl_price = float(sl_candidate)
                                except Exception:
                                    pass
                except Exception as e:
                    active_logger.error(f"[fetch_open_orders] tp/sl 조회 오류: {e}")
                    pass
                self.position['short'] = {'side': 'short', 'entry_price': short_entry, 'size': abs(short_amount), 'sl_price': sl_price, 'tp_price': tp_price}
                #active_logger.info(f"'side': 'short', 'entry_price': {short_entry}, 'size': {abs(short_amount)}, 'sl_price': {sl_price}, 'tp_price': {tp_price}")

        except Exception as e:
            active_logger.error(f"[fetch_and_set_position] 포지션 조회 오류: {e}")
            self.position = {'long': None, 'short': None}
        return self.position

    # def open_position(self, side, price, size):
    #     """
    #     지정한 방향(side: 'long'/'short')에 포지션을 연다.
    #     """
    #     if side not in ['long', 'short']:
    #         raise ValueError("side must be 'long' or 'short'")
    #     self.position[side] = {'side': side, 'entry_price': price, 'size': size}
    #     active_logger.info(f"Open {side} position: {self.position[side]}")

    def close_position(self, exchange, symbol, side=None, amount=None):
        """
        지정한 방향(side: 'long'/'short')만 청산. side=None이면 모두 청산.
        실제 거래소에 시장가 청산 주문을 실행합니다.
        Args:
            exchange: CCXT 거래소 객체
            symbol: 거래 심볼
            side: 'long', 'short', 또는 None(전체)
            amount: 청산 수량 (None이면 전체)
        Returns:
            True(성공), False(실패)
        """
        success = True
        sides = ['long', 'short'] if side is None else [side]
        for s in sides:
            pos = self.position.get(s)
            if pos and pos.get('size', 0) > 0:
                close_side = 'sell' if s == 'long' else 'buy'
                close_amount = abs(amount) if amount is not None else abs(pos['size'])
                #active_logger.info(f"[청산시도] {s.upper()} 시장가 청산 시도: {close_amount} {symbol}")

                try:
                    config = load_config('config.json')
                    position_mode = config['trading'].get('position_mode', 'hedge')
                    params = {}
                    if position_mode == 'hedge':
                        params['positionIdx'] = 1 if s == 'long' else 2
                    order = exchange.create_market_order(symbol, close_side, close_amount, params=params)
                    active_logger.info(f"[청산성공] {s.upper()} 시장가 청산 완료: {close_amount} {symbol}, 주문 ID: {order.get('id')}")
                    self.position[s] = None
                except Exception as e:
                    active_logger.error(f"[청산실패] {s.upper()} 시장가 청산 실패: {e}")
                    success = False
            else:
                active_logger.info(f"[청산없음] close_position({s}) 포지션 없음 또는 수량 0: {pos}")
        active_logger.info(f"[청산결과] close_position 최종 결과: {success}")
        return success

    def has_position(self, side=None):
        """
        side=None: 롱/숏 둘 중 하나라도 있으면 True
        side='long'/'short': 해당 방향만 체크
        """
        if side is None:
            return self.position['long'] is not None or self.position['short'] is not None
        if side not in ['long', 'short']:
            raise ValueError("side must be 'long' or 'short'")
        return self.position[side] is not None

    """
    현재 포지션 확인
    Args:
        exchange: CCXT 거래소 객체
        symbol: 거래 심볼 (예: 'BTCUSDT' 또는 'BTC/USDT:USDT') 
        action: 거래 액션 ('long' 또는 'short')
    Returns:
        (current_side, amount) - current_side는 'long', 'short', None
    """
    def get_current_position(self, exchange: ccxt.Exchange, v_symbol: str, action: str) -> Tuple[Optional[str], float]:
        return_side = None
        amount = 0.0
        try:
            positions = exchange.fetch_positions([v_symbol], params={"recv_window": 30000})
            if not positions:
                return None, 0.0
            long_pos = None
            short_pos = None
            for pos in positions:
                side = pos.get('side')
                contracts = float(pos.get('contracts', 0))
                if side == 'long' and contracts > 0:
                    long_pos = pos
                elif side == 'short' and contracts > 0:
                    short_pos = pos
            if long_pos:
                active_logger.info(f"[{v_symbol}] Long 포지션: {long_pos.get('contracts')}개 보유 (평균단가: {long_pos.get('entryPrice')})")
                if action == 'long':
                    return 'long', float(long_pos.get('contracts', 0))
            if short_pos:
                active_logger.info(f"[{v_symbol}] Short 포지션: {short_pos.get('contracts')}개 보유 (평균단가: {short_pos.get('entryPrice')})")
                if action == 'short':
                    return 'short', float(short_pos.get('contracts', 0))
            active_logger.info(f"[{v_symbol}] 현재 보유 중인 포지션이 없습니다.")
            return None, 0.0
        except Exception as e:
            active_logger.info(f"포지션 조회 중 오류 발생: {e}")
            return None, 0.0

    def get_all_positions(self, exchange, symbol) -> Tuple[Tuple[Optional[str], float, Optional[float]], Tuple[Optional[str], float, Optional[float]]]:
        """
        LONG/SHORT 포지션 동시 조회
        
        Args:
            exchange: CCXT exchange 인스턴스
            symbol: 거래 심볼
            
        Returns:
            ((long_side, long_amount, long_entry_price), 
             (short_side, short_amount, short_entry_price))
        """
        try:
            positions = exchange.fetch_positions([symbol], params={"recv_window": 30000})

            if not positions:
                return (None, 0.0, None), (None, 0.0, None)
            long_side, long_amount, long_entry = None, 0.0, None
            short_side, short_amount, short_entry = None, 0.0, None
            for pos in positions:
                side = pos.get('side')
                contracts = float(pos.get('contracts', 0))
                entry_price = None
                try:
                    if pos.get('entryPrice'):
                        entry_price = float(pos['entryPrice'])
                    elif pos.get('avgPrice'):
                        entry_price = float(pos['avgPrice'])
                    elif isinstance(pos.get('info'), dict):
                        ep = pos['info'].get('avgPrice') or pos['info'].get('entryPrice')
                        if ep:
                            entry_price = float(ep)
                except Exception:
                    entry_price = None
                if side == 'long' and contracts > 0:
                    long_side = 'long'
                    long_amount = contracts
                    long_entry = entry_price
                elif side == 'short' and contracts > 0:
                    short_side = 'short'
                    short_amount = contracts
                    short_entry = entry_price
            return (long_side, long_amount, long_entry), (short_side, short_amount, short_entry)
        except Exception as e:
            active_logger.error(f"포지션 조회 오류: {e}")
            return (None, 0.0, None), (None, 0.0, None)

    # 진입 신호 자료를 한 번에 생성하는 함수
    def get_entry_signal(self, exchange, symbol, direction, config) -> Optional[dict]:
        """
        진입 신호 자료를 한 번에 생성 (main에서 한 줄로 사용)
        Args:
            exchange: CCXT 거래소 인스턴스
            symbol: 거래 심볼
            config: 설정 딕셔너리
            analysis dict (진입가, 손절가, 익절가 등)
        """
        # 데이터 준비
        base_df = fetch_ohlcv_data(exchange, symbol, '1m', limit=500)
        lower_df = resample_data(base_df, '5m')
        
        # 실시간 현재가 조회
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
        except Exception as e:
            active_logger.warning(f"실시간 현재가 조회 실패: {e}")
            current_price = base_df['close'].iloc[-1] 
        return generate_entry_order(direction, lower_df, base_df, config=config, current_price=current_price)

    def update_trailing_stop(self, position, current_price, config):
        """
        트레일링 스탑 로직: 진입 후 일정 이익 이상에서 손절가를 진입가 위로 올리고, 반전 시 청산
        position: {'side': 'long'/'short', 'entry_price': float, 'sl_price': float, ...}
        current_price: 현재가
        config: 설정값 (profit_trailing_activation, profit_trailing_drawdown 등)
        return: (업데이트된 손절가, 청산여부)
        """
        if not position:
            return None, None, False

        side = position.get('side')
        entry_price = float(position.get('entry_price', 0.0)) if position.get('entry_price') is not None else 0.0
        sl_price    = float(position.get('sl_price', 0)) if position.get('sl_price') is not None else None
        tp_price    = float(position.get('tp_price', 0)) if position.get('tp_price') is not None else None
        current_price = float(current_price) if current_price is not None else 0.0

        sl_ratio = config['risk_management'].get('sl_ratio', 0.01)
        tp_ratio = config['risk_management'].get('tp_ratio', 0.02)
        use_trailing_stop = config['risk_management'].get('use_trailing_stop', True)
        ts_activation = config['risk_management'].get('trailing_stop_activation', 0.012)
        ts_distance = config['risk_management'].get('trailing_stop_distance', 0.004)
        use_profit_trailing = config['risk_management'].get('use_profit_trailing', True)
        pt_activation = config['risk_management'].get('profit_trailing_activation', 0.018)
        pt_drawdown = config['risk_management'].get('profit_trailing_drawdown', 0.002)

        ts_activation_price = 0.0
        ts_distance_price = 0.0
        pt_activation_price = 0.0
        pt_distance_price = 0.0
        current_profit = 0.0
        max_profit = 0.0
        cmp_sl_price = 0.0

        # 롱 포지션
        if side == 'long':
            if sl_price is None:
                sl_price = entry_price - sl_ratio * entry_price
            if tp_price is None:
                tp_price = entry_price + tp_ratio * entry_price

            if use_trailing_stop:
                ts_activation_price = entry_price + ts_activation * entry_price
                ts_distance_price = ts_activation_price - ts_distance * ts_activation_price
            if use_profit_trailing:
                pt_activation_price = entry_price + pt_activation * entry_price
                pt_distance_price = pt_activation_price - pt_drawdown * pt_activation_price

            if current_price >= pt_activation_price:
                max_profit = pt_activation_price - entry_price
                cmp_sl_price = current_price - pt_drawdown * entry_price
            elif current_price >= ts_activation_price:
                max_profit = ts_activation_price - entry_price
                cmp_sl_price = current_price - ts_distance * entry_price
            else:
                max_profit = current_price - entry_price
                cmp_sl_price = sl_price

            active_logger.info(f"[트레일링] {side.upper()}  | 현재가:{current_price}, 진입가:{entry_price:.4f}, 손절가:{sl_price:.4f}, 익절가:{tp_price:.4f}, 수정SL:{cmp_sl_price:.4f} | " \
                               f"ts조정가: {ts_activation_price:.4f}, {ts_distance_price:.4f} | pt조정가: {pt_activation_price:.4f}, {pt_distance_price:.4f}")

            current_profit = current_price - entry_price
            if current_profit > max_profit:
                new_sl = max(sl_price, cmp_sl_price)
                if current_price <= new_sl: # 가격이 new_sl 아래로 내려가면 청산
                    return new_sl, tp_price, True
                return new_sl, tp_price, False
            else:
                return sl_price, tp_price, False
        # 숏 포지션
        elif side == 'short':
            if sl_price is None:
                sl_price = entry_price + sl_ratio * entry_price
            if tp_price is None:
                tp_price = entry_price - tp_ratio * entry_price

            # Ensure: sl_price > entry_price, tp_price < entry_price
            if sl_price <= entry_price:
                sl_price = entry_price + abs(sl_ratio) * entry_price
            if tp_price >= entry_price:
                tp_price = entry_price - abs(tp_ratio) * entry_price

            if use_trailing_stop:
                ts_activation_price = entry_price - ts_activation * entry_price
                ts_distance_price = ts_activation_price + ts_distance * ts_activation_price
            if use_profit_trailing:
                pt_activation_price = entry_price - pt_activation * entry_price
                pt_distance_price = pt_activation_price + pt_drawdown * pt_activation_price

            if current_price <= pt_activation_price:
                max_profit = entry_price - pt_activation_price
                cmp_sl_price = current_price + pt_drawdown * entry_price
            elif current_price <= ts_activation_price:
                max_profit = entry_price - ts_activation_price
                cmp_sl_price = current_price + ts_distance * entry_price
            else:
                max_profit = entry_price - current_price
                cmp_sl_price = sl_price

            active_logger.info(f"[트레일링] {side.upper()} | 현재가:{current_price}, 진입가:{entry_price:.4f}, 손절가:{sl_price:.4f}, 익절가:{tp_price:.4f}, 수정SL:{cmp_sl_price:.4f} | " \
                               f"ts조정가: {ts_activation_price:.4f}, {ts_distance_price:.4f} | pt조정가: {pt_activation_price:.4f}, {pt_distance_price:.4f}")

            current_profit = entry_price - current_price
            if current_profit > max_profit:
                new_sl = min(sl_price, cmp_sl_price)
                if current_price >= new_sl:
                    return new_sl, tp_price, True
                return new_sl, tp_price, False
            else:
                return sl_price, tp_price, False

        return sl_price, tp_price, False

    def trailing_stop_monitor(self, exchange, symbol, config):
        """
        포지션이 있을 때마다 트레일링 스탑을 갱신하고, 청산 조건이 되면 포지션을 정리합니다.
        이 메서드를 메인 루프나 주기적 타이머에서 호출하세요.
        호출: self.position_manager.trailing_stop_monitor(exchange, symbol, config)
        """
        
        # 거래소에서 최신 포지션 동기화
        self.fetch_and_set_position(exchange, symbol)

        for side in ['long', 'short']:
            pos = self.position.get(side)
            if pos:
                current_price = self.get_current_price(exchange, symbol)
                new_sl, tp_price, should_close = self.update_trailing_stop(pos, current_price, config)

                # 거래소 TP/SL 주문 갱신
                if new_sl != pos.get('sl_price'):
                    active_logger.info(f"[트레일링] {side} 포지션 손절가 갱신: {pos.get('sl_price')} → {new_sl}")

                    # TP/SL 주문 갱신 전 숏 포지션 익절가 체크
                    if side == 'short' and tp_price is not None:
                        try:
                            tp_price = float(tp_price)
                        except Exception:
                            tp_price = None
                        if tp_price is not None and tp_price >= current_price:
                            tp_ratio = config['risk_management'].get('tp_ratio', 0.02)
                            tp_price = current_price - abs(tp_ratio) * current_price

                    self.set_tp_sl_orders(exchange, symbol, side, pos['size'], new_sl, tp_price)
                    #time.sleep(1)  # 주문 갱신 대기 (시장 상황에 따라 조절 가능)

                # 청산 조건이면 포지션 정리
                if should_close:
                    active_logger.info(f"{Colors.YELLOW}⚪ 트레일링 스탑 : 청산 | 포지션: {side} | 현재가: {current_price} | 청산가: {new_sl}{Colors.RESET}")
                    trade_logger.info(f"{Colors.YELLOW}⚪ 트레일링 스탑 : 청산 | 포지션: {side} | 현재가: {current_price} | 청산가: {new_sl}{Colors.RESET}")
                    self.close_position(current_price, side=side)
                    #time.sleep(1)  # 주문 갱신 대기 (시장 상황에 따라 조절 가능)

    # 포지션별 최고 수익률 추적 (Profit Trailing Stop용)
    # 구조: {symbol_side: {'peak_pnl': float, 'entry_price': float}}
    position_peak_tracker = {}

    def execute_trade(self,
        exchange: ccxt.Exchange,
        symbol: str,
        action: str,  # 'long' or 'short'
        usdt_amount: float,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        amount_mode: str = 'notional',  # 'notional' or 'margin'
        leverage: float = 1
    ) -> bool:
        """
        거래 실행 (포지션 확인 → 수량 계산 → 주문 → TP/SL 설정)
        Args:
            exchange: CCXT 거래소 객체
            symbol: 거래 심볼
            action: 'long' 또는 'short'
            usdt_amount: 수량
            entry_price: 진입가
            sl_price: 손절가
            tp_price: 익절가
            amount_mode: 'notional' 또는 'margin'
            leverage: 레버리지
            
        Returns:
            성공 여부
        """
        return_success = False
        allow_same_position = True

        try:
            # 포지션 진입시 동일 포지션 존재할 때 진입여부와 청산여부를 config설정으로 확인하는 로직 추가
            # 진입여부가 True이면 동일포지션 존재시 진입, false이면 진입안함
            # 청산여부가 True이면 반대포지션 존재시 자동청산 후 진입, false이면 청산하지 않고 진입 함
            # config에서 포지션 정책 읽기 (기본값: 동일포지션 진입허용, 자동청산 금지)
            config = load_config()
            allow_same_position = config['trading'].get('allow_same_position', True)

            # 1. 반대/동일 포지션 확인 및 config 기반 진입/청산 정책 적용
            positions = self.get_all_positions(exchange, symbol)
            if not positions or not isinstance(positions, tuple) or len(positions) != 2:
                active_logger.error("⚪ execute_trade : 포지션 데이터 없음")
                return False
            (current_long, long_amount, long_entry), (current_short, short_amount, short_entry) = positions
            # 동일 포지션 존재 시 진입 정책 (True: 진입허용, False: 진입안함)
            if allow_same_position is False:
                if action == 'long' and current_long == 'long':
                    active_logger.info("동일 LONG 포지션이 이미 존재하여 진입을 스킵합니다.")
                    return False
                if action == 'short' and current_short == 'short':
                    active_logger.info("동일 SHORT 포지션이 이미 존재하여 진입을 스킵합니다.")
                    return False

            if not entry_price or entry_price <= 0:
                active_logger.info("진입가가 유효하지 않음")
                return False

            qty = usdt_amount     
            if qty <= 0:
                active_logger.info(f"주문수량 유효하지 않음")
                return False
            
            # 3-3. 잔고 기반 최대 주문 비중 조절 (예: 10%로 제한)
            effective_notional = self.get_adjusted_trade_amount(exchange, float(usdt_amount), leverage, max_position_pct=0.1)
            if effective_notional <= 0:
                active_logger.info("잔고 기반 최대 주문 비중으로 인해 주문 금액이 0 이하로 조정되어 진입을 스킵합니다.")
                return False
            
            # 4. 주문 실행
            order = self.place_order(exchange, symbol, 'limit', action, qty, entry_price) # 지정가 주문
            if not order:
                active_logger.info("주문 실패: place_order 결과 None")
                return False
            active_logger.info(f"주문 완료: {symbol} {action.upper()} price={entry_price}, qty={qty:.4f} | amount_mode={amount_mode} notional={effective_notional:.2f}USDT leverage={leverage}x")

            time.sleep(4)  # 주문 체결 대기 (시장 상황에 따라 조절 가능)

            # 5. 미체결 주문 처리 (양방향 모두 취소)
            #self.cancel_all_open_orders(exchange, symbol)
            self.cancel_all_side_orders(exchange, symbol, side=action)

            cur_pos = self.get_current_position(exchange, symbol, action)
            if not cur_pos or not isinstance(cur_pos, tuple) or len(cur_pos) != 2:
                active_logger.info("주문 미체결: TP/SL 스킵")
                return True
            
            # 6. TP/SL 설정
            current_side, current_qty = cur_pos
            if current_qty > 0:
                refined_sl, refined_tp = sl_price, tp_price
                # 6-1. TP/SL 가격 정교화 (틱 사이즈 정렬 + 최소 간격 확보 + ATR 기반 최소 거리)
                if sl_price is None or tp_price is None:
                    refined_sl, refined_tp = self.refine_sl_tp_prices(exchange, symbol, action, entry_price, sl_price, tp_price)   

                tp_sl_success = self.set_tp_sl_orders(exchange, symbol, action, current_qty, refined_sl, refined_tp)
                if tp_sl_success:
                    active_logger.info(f"TP/SL 설정 완료: TP={refined_tp:.4f}, SL={refined_sl:.4f}")
                    return_success = True
                    time.sleep(1)  # 설정 대기 (시장 상황에 따라 조절 가능)
                else:
                    active_logger.warning(f"TP/SL 설정 실패했지만 주문은 완료됨.")
                    return_success = True
            else:
                active_logger.warning("포지션이 아직 열리지 않아 TP/SL 주문을 스킵.")
                return_success = False

            return return_success
            
        except Exception as e:
            active_logger.error(f"거래 실행 실패: {str(e)}")
            return False

    def get_adjusted_trade_amount(self, exchange, requested_amount: float, leverage: float, max_position_pct: float = 1.0) -> float:
        """
        잔고를 조회하여 최대 주문 비중에 맞게 주문 금액을 조절합니다.
        Args:
            exchange: CCXT 거래소 객체
            requested_amount: 요청한 주문 금액(USDT)
            max_position_pct: 최대 주문 비중(0~1)
        Returns:
            조정된 주문 금액(USDT)
        """
        try:
            balance = exchange.fetch_balance()
            usdt_available = balance.get('USDT', {}).get('free', None)
            if usdt_available is not None:
                usdt_available = balance.get('total', {}).get('USDT', None)
            else:
                active_logger.warning("USDT 잔고 조회 실패, 입력값 그대로 사용")
                return float(requested_amount)
            
            max_trade_amount = float(usdt_available) * float(max_position_pct) * float(leverage)
            if max_trade_amount <= 0:
                active_logger.info(f"사용 가능한 USDT 잔고가 부족합니다: {usdt_available}")
                return 0.0
            if float(requested_amount) > max_trade_amount:
                active_logger.info(f"주문 금액이 최대 비중({max_position_pct*100:.1f}%)을 초과하여 조정: {requested_amount} → {max_trade_amount}")
            return min(float(requested_amount), max_trade_amount)
        except Exception as e:
            active_logger.warning(f"잔고 조회 중 오류: {e}, 입력값 그대로 사용")
            return float(requested_amount)

    def refine_sl_tp_prices(self,
        exchange: ccxt.Exchange,
        symbol: str,
        action: str,
        entry_price: float,
        sl_price: float,
        tp_price: float
    ) -> Tuple[float, float]:
        """
        SL/TP 가격을 거래소 틱 사이즈에 맞게 보정하고, 엔트리와 최소 1틱 이상 간격을 확보한다.
        
        Rules:
        - LONG: SL은 아래쪽으로 내림, TP는 위쪽으로 올림
        - SHORT: SL은 위쪽으로 올림, TP는 아래쪽으로 내림
        - 보정 후에도 방향이 뒤바뀌지 않도록 최소 1틱 간격 보장
        """
        # config.json에서 설정 로드
        config = load_config('config.json')
        
        tick = get_price_tick_size(symbol)
        sl, tp = sl_price, tp_price

        # ATR 기반 최소 거리 설정 (config에서 읽어오기)
        atr_settings = {
            'enabled': config['risk_management'].get('use_atr_sl', False),
            'timeframe': config['strategy']['timeframes']['entry_trigger'],
            'period': config['risk_management'].get('atr_period', 14),
            'sl_mult': 0.3,  # SL ATR 배수
            'tp_mult': 0.5   # TP ATR 배수
        }

        # ATR 기반 최소 거리 적용 (옵션)
        atr_info = None
        if atr_settings.get('enabled', False):
            tf = atr_settings.get('timeframe', '1m')
            period = atr_settings.get('period', 14)
            sl_mult = atr_settings.get('sl_mult', 0.3)
            tp_mult = atr_settings.get('tp_mult', 0.5)

            atr_value = get_recent_atr(exchange, symbol, tf, period)
            if atr_value and atr_value > 0:
                atr_info = {'atr': atr_value, 'tf': tf, 'period': period, 'sl_mult': sl_mult, 'tp_mult': tp_mult}
                min_sl_dist = sl_mult * atr_value
                min_tp_dist = tp_mult * atr_value

                if action == 'long':
                    # SL는 엔트리 아래로 최소 거리 확보
                    target_sl = entry_price - min_sl_dist
                    if sl > target_sl:
                        sl = target_sl
                    # TP는 엔트리 위로 최소 거리 확보
                    target_tp = entry_price + min_tp_dist
                    if tp < target_tp:
                        tp = target_tp
                else:
                    # short: SL는 엔트리 위로 최소 거리 확보
                    target_sl = entry_price + min_sl_dist
                    if sl < target_sl:
                        sl = target_sl
                    # TP는 엔트리 아래로 최소 거리 확보
                    target_tp = entry_price - min_tp_dist
                    if tp > target_tp:
                        tp = target_tp

        if action == 'long':
            sl = round_to_tick(sl_price, tick, 'down')
            tp = round_to_tick(tp_price, tick, 'up')
            # 최소 1틱 간격 확보
            if sl >= entry_price:
                sl = round_to_tick(entry_price - (tick or 0), tick or 1e-8, 'down')
            if tp <= entry_price:
                tp = round_to_tick(entry_price + (tick or 0), tick or 1e-8, 'up')
        else:
            # short
            sl = round_to_tick(sl_price, tick, 'up')
            tp = round_to_tick(tp_price, tick, 'down')
            if sl <= entry_price:
                sl = round_to_tick(entry_price + (tick or 0), tick or 1e-8, 'up')
            if tp >= entry_price:
                tp = round_to_tick(entry_price - (tick or 0), tick or 1e-8, 'down')

        # 로그 (변경 사항만 표시)
        changed = []
        if abs(sl - sl_price) > 0:
            changed.append(f"SL {sl_price:.6f} -> {sl:.6f}")
        if abs(tp - tp_price) > 0:
            changed.append(f"TP {tp_price:.6f} -> {tp:.6f}")
        if changed:
            base = f"SL/TP 가격 보정: {', '.join(changed)} (tick={tick})"
            if atr_info:
                base += f" | ATR={atr_info['atr']:.6f} ({atr_info['tf']}, P={atr_info['period']})"
                base += f" | 최소거리: SL≥{atr_info['sl_mult']}*ATR, TP≥{atr_info['tp_mult']}*ATR"
            active_logger.info(base)

        return sl, tp

    def set_tp_sl_orders(self, exchange: ccxt.Exchange, symbol: str, position_side: str, qty: float, sl_price: float, tp_price: float) -> bool:
        """
        TP/SL 주문 설정 (Hedge 모드)
        
        Args:
            exchange: CCXT 거래소 객체
            symbol: 거래 심볼
            position_side: 포지션 방향 ('long' 또는 'short')
            qty: 수량
            sl_price: 손절가
            tp_price: 익절가
            
        Returns:
            성공 여부
        """       
        try:
            # None 체크: 가격이 None이면 API 호출하지 않고 에러 로그
            if tp_price is None or sl_price is None:
                active_logger.error(f"[TP/SL 등록] 실패: tp_price 또는 sl_price가 None입니다. TP={tp_price}, SL={sl_price}")
                return False
            position_idx = 1 if position_side == 'long' else 2
            market_id = symbol.replace('/', '').split(':')[0]
            active_logger.info(f"[TP/SL 등록] 입력 파라미터: symbol={symbol}, position_side={position_side}, qty={qty}, sl_price={sl_price}, tp_price={tp_price}")
            params = {
                "category": "linear",
                "symbol": market_id,
                "takeProfit": str(tp_price),
                "tpSize": str(qty),
                "stopLoss": str(sl_price),
                "slSize": str(qty),
                "tpTriggerBy": "LastPrice",
                "slTriggerBy": "LastPrice",
                "tpslMode": "Partial",
                "tpOrderType": "Market",
                "slOrderType": "Market"
            }

            config = load_config('config.json')
            position_mode = config['trading'].get('position_mode', 'hedge')
            if position_mode == 'hedge':
                params["positionIdx"] = int(position_idx)

            if position_side == "long":
                params.update({
                    "tpTriggerDirection": 1,
                    "slTriggerDirection": 2
                })
            else:
                params.update({
                    "tpTriggerDirection": 2,
                    "slTriggerDirection": 1
                })
                
            result = exchange.private_post_v5_position_trading_stop(params)
            ret_code = result.get('retCode', -1)
            if ret_code == 0 or ret_code == '0':
                tp_str = f"{tp_price:.6f}" if tp_price is not None else "None"
                sl_str = f"{sl_price:.6f}" if sl_price is not None else "None"
                active_logger.info(f"[TP/SL 등록] 성공: {position_side.upper()} | TP={tp_str} | SL={sl_str}")
                return True
            else:
                ret_msg = result.get('retMsg', 'Unknown error')
                active_logger.error(f"[TP/SL 등록] 실패 (retCode={ret_code}): {ret_msg}")
                return False
        except Exception as e:
            active_logger.error(f"[TP/SL 등록] 예외 발생: {str(e)}")
            return False
        return False

    """
    모든 미체결 주문 취소(양방향)
    Args:
        exchange: CCXT 거래소 객체
        symbol: 거래 심볼
    Returns:
        성공 여부
    """
    def cancel_all_open_orders(self, exchange: ccxt.Exchange, symbol: str) -> bool:
        try:
            #logger.info(f"미체결 주문 조회 중: {symbol}")
            open_orders = exchange.fetch_open_orders(symbol)
            if open_orders is None:
                open_orders = []
            if open_orders:
                order_count = len(open_orders)
                active_logger.info(f"미체결 주문 발견: {Colors.BOLD}{order_count}개{Colors.RESET}")
                for order in open_orders:
                    try:
                        exchange.cancel_order(order['id'], symbol)
                        order_type = order.get('type', 'N/A')
                        order_side = order.get('side', 'N/A')
                        order_amount = order.get('amount', 'N/A')
                        if order['side'] == 'buy':
                            active_logger.info(f"  {Colors.GREEN}✓{Colors.RESET} 주문 취소: {Colors.CYAN}{order['id']}{Colors.RESET} ({order_side} {order_type} {order_amount})")
                        else:
                            active_logger.info(f"  {Colors.RED}✓{Colors.RESET} 주문 취소: {Colors.CYAN}{order['id']}{Colors.RESET} ({order_side} {order_type} {order_amount})")
                    except Exception as e:
                        active_logger.info(f"  ✗ 주문 취소 실패 ({order['id']}): {e}")
                active_logger.info(f"모든 미체결 주문 취소 완료: {symbol} ({order_count}개)")
                return True
            else:
                active_logger.info(f"미체결 주문: {Colors.CYAN}없음{Colors.RESET}")
                return True
        except Exception as e:
            active_logger.info(f"미체결 주문 조회/취소 오류: {e}")
            return False

    """
    모든 미체결 주문 취소(단일 방향)
    Args:
        exchange: CCXT 거래소 객체
        symbol: 거래 심볼
    Returns:
        성공 여부
    """
    def cancel_all_side_orders(self, exchange: ccxt.Exchange, symbol: str, side: str) -> bool:
        try:
            #logger.info(f"미체결 주문 조회 중: {symbol}")
            open_orders = exchange.fetch_open_orders(symbol)
            if open_orders is None:
                open_orders = []
            if open_orders:
                order_count = len(open_orders)
                #active_logger.info(f"미체결 주문 발견: {Colors.BOLD}{order_count}개{Colors.RESET}")
                for order in open_orders:
                    try:
                        if order.get('side') == side:
                            exchange.cancel_order(order['id'], symbol)
                            order_type = order.get('type', 'N/A')
                            order_side = order.get('side', 'N/A')
                            order_amount = order.get('amount', 'N/A')
                            if order['side'] == 'buy':
                                active_logger.info(f"{Colors.GREEN}✓{Colors.RESET} 주문 취소: {Colors.CYAN}{order['id']}{Colors.RESET} ({order_side} {order_type} {order_amount})")
                            else:
                                active_logger.info(f"{Colors.RED}✓{Colors.RESET} 주문 취소: {Colors.CYAN}{order['id']}{Colors.RESET} ({order_side} {order_type} {order_amount})")
                    except Exception as e:
                        active_logger.info(f"✗ 주문 취소 실패 ({order['id']}): {e}")
                active_logger.info(f"미체결 주문 취소 완료: {symbol} ({order_count}개)")
                return True
            else:
                active_logger.info(f"미체결 주문: {Colors.CYAN}없음{Colors.RESET}")
                return True
        except Exception as e:
            active_logger.info(f"미체결 주문 조회/취소 오류: {e}")
            return False

    def place_order(self, exchange: ccxt.Exchange, symbol: str, order_type: str, side: str, amount: float, price: float = None) -> Optional[Dict]:
        """
        주문 실행 (시장가/지정가)
        Hedge 모드에서는 positionIdx 지정 필요:
        - buy  (Long 진입): positionIdx=1
        - sell (Short 진입): positionIdx=2
        """
        side = 'buy' if side == 'long' else 'sell'

        try:
            # Hedge 모드용 params 설정
            params = {
                'positionIdx': 1 if side == 'buy' else 2  # Long=1, Short=2
            }
            
            #logger.info(f"place_order: {side.upper()} {amount} {symbol} {order_type} @ {price if price else 'market'} (positionIdx={params['positionIdx']})")
            if order_type == 'market':
                order = exchange.create_market_order(symbol, side, amount, params=params)
            else:
                order = exchange.create_limit_order(symbol, side, amount, price, params=params)

            # 반환값이 dict가 아니면 None 반환
            if not isinstance(order, dict):
                active_logger.error(f"주문 결과가 dict 타입이 아님: {order}")
                return None
            return order
        except Exception as e:
            active_logger.error(f"주문 실패: {str(e)}")
            return None

    def get_tp_sl_for_side(self, exchange: ccxt.Exchange, symbol: str, side: str) -> Tuple[Optional[float], Optional[float]]:
        """
        현재 포지션(side)의 TP/SL(익절/손절) 가격을 조회합니다.
        - CCXT Bybit fetch_positions info를 우선 활용
        - 값이 없으면 Bybit TPSL 주문 API로 조회
        Args:
            symbol: 예) 'XRPUSDT' 또는 'XRP/USDT:USDT'
            side: 'long' 또는 'short'
        Returns:
            (tp_price, sl_price) 둘 다 없으면 (None, None)
        """
        tp, sl = None, None
        try:
            # 1. 포지션 정보에서 TP/SL 조회
            positions = exchange.fetch_positions([symbol], params={"recv_window": 30000})
            if not positions:
                active_logger.debug(f"TP/SL 조회: 포지션 목록이 비어있음 ({symbol})")
                return None, None
            
            for pos in positions:
                pos_side = pos.get('side')
                contracts = float(pos.get('contracts', 0))
                if pos_side == side and contracts > 0:
                    info = pos.get('info', {})
                    tp_raw = info.get('takeProfit')  # 익절가
                    sl_raw = info.get('stopLoss')    # 손절가
                    active_logger.debug(f"TP/SL 원본 값: side={side}, tp_raw={tp_raw}, sl_raw={sl_raw}")
                    try:
                        if tp_raw and tp_raw != "" and tp_raw != "0" and float(tp_raw) != 0:
                            tp = float(tp_raw)
                    except Exception as e:
                        active_logger.debug(f"TP 변환 오류: {e}")
                        tp = None
                    try:
                        if sl_raw and sl_raw != "" and sl_raw != "0" and float(sl_raw) != 0:
                            sl = float(sl_raw)
                    except Exception as e:
                        active_logger.debug(f"SL 변환 오류: {e}")
                        sl = None
                    if tp is not None or sl is not None:
                        active_logger.debug(f"TP/SL 최종 값: side={side}, tp={tp}, sl={sl}")
                        return tp, sl

            orders = exchange.fetch_open_orders(symbol)
            for order in orders:
                # 주문 타입이 'stop' 계열인지 확인
                if order['type'] in ['stop', 'take_profit', 'stop_loss']:
                    active_logger.debug(f"주문 ID: {order['id']}, 트리거 가격: {order['stopPrice']}")
                    
        except Exception as e:
            active_logger.error(f"TP/SL 조회 실패: {e}")
            return None, None

    def log_position_status(self, exchange, symbol, logger):
        """
        포지션 상태 상세 로그를 남기는 함수
        Args:
            exchange: CCXT 거래소 객체
            symbol: 거래 심볼
            logger: 로깅 인스턴스
        """
        try:
            positions = self.get_all_positions(exchange, symbol)
            if not positions or not isinstance(positions, tuple) or len(positions) != 2:
                logger.info("⚪ 포지션 상태 : 없음 | 포지션 데이터 없음")
                return
            (long_side, long_amount, long_entry), (short_side, short_amount, short_entry) = positions
        except Exception as e:
            logger.info(f"⚪ 포지션 상태 : unpack 에러 또는 NoneType - {e}")
            return
        
        logger.info(f"positions | {positions}")

        current_price = self.get_current_price(exchange, symbol)

        # None 방지: 값이 None이면 0.0으로 대체
        long_entry = float(long_entry) if long_entry is not None else 0.0
        long_amount = float(long_amount) if long_amount is not None else 0.0
        short_entry = float(short_entry) if short_entry is not None else 0.0
        short_amount = float(short_amount) if short_amount is not None else 0.0
        current_price = float(current_price) if current_price is not None else 0.0

        # TP/SL 실시간 조회
        long_sl, long_tp = self.get_tp_sl_for_side(exchange, symbol, 'long')
        short_sl, short_tp = self.get_tp_sl_for_side(exchange, symbol, 'short')
        long_sl = float(long_sl) if long_sl is not None else 0.0
        long_tp = float(long_tp) if long_tp is not None else 0.0
        short_sl = float(short_sl) if short_sl is not None else 0.0
        short_tp = float(short_tp) if short_tp is not None else 0.0

        long_pnl_rate = 0.0
        long_pnl_amount = 0.0
        if long_side == 'long' and long_entry != 0.0 and long_amount > 0 and current_price > 0:
            long_pnl_rate = round((current_price - long_entry) / long_entry * 100, 4)
            long_pnl_amount = round((current_price - long_entry) * long_amount, 4)

        short_pnl_rate = 0.0
        short_pnl_amount = 0.0
        if short_side == 'short' and short_entry != 0.0 and short_amount > 0 and current_price > 0:
            short_pnl_rate = round((short_entry - current_price) / short_entry * 100, 4)
            short_pnl_amount = round((short_entry - current_price) * short_amount, 4)

        if long_side == 'long' and long_amount > 0:
            logger.info(f"{Colors.GREEN}{Colors.BOLD}[포지션 상태] LONG : 진입가= {long_entry:.4f}, 수량= {long_amount}, 손절가= {long_sl:.4f}, 익절가= {long_tp:.4f}, 손익률= {long_pnl_rate}%, 손익액= {long_pnl_amount}{Colors.RESET}{Colors.END}")
        if short_side == 'short' and short_amount > 0:
            logger.info(f"{Colors.RED}{Colors.BOLD}[포지션 상태] SHORT: 진입가= {short_entry:.4f}, 수량= {short_amount}, 손절가= {short_sl:.4f}, 익절가= {short_tp:.4f}, 손익률= {short_pnl_rate}%, 손익액= {short_pnl_amount}{Colors.RESET}{Colors.END}")

    def log_24h_performance(self, exchange, symbol, logger):
        """
        Bybit 실현손익 집계: 최근 24시간 내 closed position의 realizedPnl 합산
        """
        now = int(time.time() * 1000) # 현재 시간 (밀리초)
        since = now - 24*60*60*1000   # 24시간 전 (밀리초)

        params = {
            "category": "linear",
            "symbol": symbol.replace('/', '').split(':')[0],
            "startTime": since,
            "endTime": now
        }
        result = exchange.private_get_v5_position_closed_pnl(params)

        long_entry_value = 0.0
        long_exit_value = 0.0
        short_entry_value = 0.0
        short_exit_value = 0.0
        long_pnl = 0.0
        short_pnl = 0.0
        pnl_sum = 0.0

        for p in result["result"]["list"]:
            ts = int(p["createdTime"])
            side = p["side"]

            entry_price = float(p["avgEntryPrice"])
            exit_price = float(p["avgExitPrice"])
            amount = float(p["qty"])
            pnl = float(p["closedPnl"])

            if since <= ts <= now:
                if side.lower() == "buy":
                    long_entry_value += entry_price * amount
                    long_exit_value += exit_price * amount
                    long_pnl += pnl
                elif side.lower() == "sell":
                    short_entry_value += entry_price * amount
                    short_exit_value += exit_price * amount
                    short_pnl += pnl
                pnl_sum += pnl

        fee = long_entry_value - long_exit_value + short_exit_value - short_entry_value - pnl_sum
        fee = fee if fee is not None else 0.0

        logger.info(f"{Colors.BRIGHT_MAGENTA}[24h실현손익] LONG : 진입= {long_entry_value:.4f}, 청산= {long_exit_value:.4f}, 손익= {long_pnl:.4f} | SHORT : 진입= {short_entry_value:.4f}, 청산= {short_exit_value:.4f}, 손익= {short_pnl:.4f} | 손익합= {pnl_sum:.4f}, 수수료= {fee:.4f}{Colors.RESET}{Colors.END}")

def fetch_ohlcv_data(exchange, symbol: str, timeframe: str, limit: int = 500) -> Optional[pd.DataFrame]:
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
    
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        if not ohlcv:
            active_logger.warning(f"OHLCV 데이터 없음: {symbol} {timeframe}")
            return None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        return df
    except Exception as e:
        active_logger.warning(f"OHLCV 데이터 조회 실패: {symbol} {timeframe} - {e}")
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
        return df

def generate_entry_order(direction, df, entry_trigger_df, config, current_price=None):
    """
    단순 진입 신호 자료 생성 (진입가, 손절가, 익절가)
    Args:
        direction: 'long' 또는 'short'
        df: 진입 신호가 발생한 타임프레임의 데이터프레임
        entry_trigger_df: 트리거용 데이터프레임 (예: 1m)
    Returns:
        entry_order dict 또는 None
    """
    entry_order = None
    if current_price is None:
        entry_price = entry_trigger_df['close'].iloc[-1]
    else:
        entry_price = current_price

    sl_ratio = config['risk_management'].get('sl_ratio', 0.01)
    tp_ratio = config['risk_management'].get('tp_ratio', 0.03)

    if direction == 'long':
        #sl_price = df['low'].iloc[-20:].min()
        #tp_price = entry_price + (entry_price - sl_price) * config['risk_management']['risk_reward_ratio']
        sl_price = entry_price * (1 - sl_ratio)
        tp_price = entry_price * (1 + tp_ratio)
        entry_order = {
            'type': 'LONG',
            'entry_price': float(entry_price),
            'sl_price': float(sl_price),
            'tp_price': float(tp_price),
            'has_signal': True
        }
    elif direction == 'short':
        # sl_price = df['high'].iloc[-20:].max()
        # tp_price = entry_price - (sl_price - entry_price) * config['risk_management']['risk_reward_ratio']
        sl_price = entry_price * (1 + sl_ratio)
        tp_price = entry_price * (1 - tp_ratio)
        entry_order = {
            'type': 'SHORT',
            'entry_price': float(entry_price),
            'sl_price': float(sl_price),
            'tp_price': float(tp_price),
            'has_signal': True
        }
    return entry_order


def get_price_tick_size(symbol: str) -> Optional[float]:
    """
    심볼의 가격 틱 사이즈 조회 (Bybit instruments info 사용)
    Args:
        symbol: 거래 심볼 (예: 'XRPUSDT' 또는 'XRP/USDT:USDT')
    Returns:
        tick_size 또는 None
    """
    try:
        market_id = symbol.replace('/', '').split(':')[0]
        tick_size_map = {
            'XRPUSDT': 0.0001,
            'BTCUSDT': 0.1,
            'ETHUSDT': 0.01,
            # 필요시 추가
        }
        return tick_size_map.get(market_id, 0.0001)
    except Exception as e:
        logging.info(f"틱 사이즈 조회 실패: {e}")
        return None

def get_recent_atr(exchange, symbol: str, timeframe: str = '1m', period: int = 14) -> Optional[float]:
    """
    최근 ATR 값을 계산하여 반환합니다.
    Args:
        exchange: CCXT 거래소 객체
        symbol: 거래 심볼
        timeframe: 시간봉 (예: '1m', '5m')
        period: ATR 계산 기간
    Returns:
        ATR 값(float) 또는 None
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=period+1)
        if not ohlcv or len(ohlcv) < period+1:
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # TR 계산
        df['prev_close'] = df['close'].shift(1)
        df['tr'] = df[['high', 'low', 'prev_close']].apply(
            lambda row: max(row['high'] - row['low'], abs(row['high'] - row['prev_close']), abs(row['low'] - row['prev_close'])), axis=1)
        atr = df['tr'].rolling(window=period).mean().iloc[-1]
        return float(atr)
    except Exception as e:
        logging.info(f"ATR 계산 실패: {e}")
        return None

def round_to_tick(price: float, tick: float, mode: str = 'nearest') -> float:
    """
    가격을 틱 사이즈에 맞춰 반올림합니다.
    mode: 'down' | 'up' | 'nearest'
    """
    if tick is None or tick <= 0:
        return price
    try:
        price = float(price)
        tick = float(tick)
        if mode == 'down':
            return (int(price / tick)) * tick
        elif mode == 'up':
            return (int((price + tick - 1e-8) / tick)) * tick
        else:
            return round(price / tick) * tick
    except Exception:
        return price
    
    