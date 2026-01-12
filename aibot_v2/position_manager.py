
"""
포지션 관리 모듈
포지션 확인, 미체결 주문 취소, 포지션 진입 및 SL/TP 설정
"""

import math
import math
import time
import ccxt
import pandas as pd
import os
from typing import Optional, Tuple, Dict
from aibot_v2.color_utils import *
from pybit.unified_trading import HTTP
from dotenv import load_dotenv
from aibot_v2.config_loader import load_config
from aibot_v2 import log_config
import logging
from typing import Optional, Dict
from aibot_v2.trend_strategy import resample_data

# Reuse existing logger if already configured by main.py; otherwise set it up here.
logger = log_config.get_logger()
if not logger.handlers:
    logger = log_config.setup_logging(log_dir="logs", log_level=logging.INFO)
else:
    logger.setLevel(logging.INFO)

# .env 파일을 aibot_v2 폴더에서 직접 로드
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

# pybit session은 환경변수에서 키를 가져와서 초기화
def get_pybit_session():
    """pybit HTTP 세션을 API 키와 함께 초기화"""
    api_key = os.getenv('BYBIT_API_KEY', '')
    api_secret = os.getenv('BYBIT_API_SECRET', '')
    if api_key and api_secret:
        return HTTP(testnet=False, api_key=api_key, api_secret=api_secret)
    else:
        logger.warning("BYBIT API 키가 없어 pybit 세션을 인증 없이 초기화합니다.")
        return HTTP(testnet=False)

session = get_pybit_session()


# 포지션별 최고 수익률 추적 (Profit Trailing Stop용)
# 구조: {symbol_side: {'peak_pnl': float, 'entry_price': float}}
position_peak_tracker = {}

# 포지션별 진입 시간 추적 (청산 시 사용)
# 구조: {symbol_side: 진입 timestamp}

def execute_trade(
    exchange: ccxt.Exchange,
    symbol: str,
    action: str,  # 'long' or 'short'
    usdt_amount: float,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    amount_mode: str = 'notional',  # 'notional' or 'margin'
    leverage: float = None
) -> bool:
    """
    거래 실행 (포지션 확인 → 수량 계산 → 주문 → TP/SL 설정)
    
    Args:
        exchange: CCXT 거래소 객체
        symbol: 거래 심볼
        action: 'long' 또는 'short'
        usdt_amount: 주문 금액 (USDT)
        entry_price: 진입가
        sl_price: 손절가
        tp_price: 익절가
        amount_mode: 'notional' 또는 'margin'
        leverage: 레버리지
        
    Returns:
        성공 여부
    """
    try:
        # 포지션 진입시 동일 포지션 존재할 때 진입여부와 청산여부를 config설정으로 확인하는 로직 추가
        # 진입여부가 True이면 동일포지션 존재시 진입, false이면 진입안함
        # 청산여부가 True이면 반대포지션 존재시 자동청산 후 진입, false이면 청산하지 않고 진입 함

        # 1. 반대/동일 포지션 확인 및 config 기반 진입/청산 정책 적용
        (current_long, long_amount, long_entry), (current_short, short_amount, short_entry) = get_all_positions(exchange, symbol)

        # config에서 포지션 정책 읽기 (기본값: 동일포지션 진입허용, 자동청산 금지)
        from aibot_v2.config_loader import load_config
        try:
            config = load_config()
            allow_same_position = config['trading'].get('allow_same_position', True)
            auto_close_opposite = config['trading'].get('auto_close_opposite', False)
        except Exception:
            allow_same_position = True
            auto_close_opposite = False

        # 동일 포지션 존재 시 진입 정책 (True: 진입허용, False: 진입안함)
        if action == 'long' and current_long == 'long':
            if allow_same_position is False:
                logger.info("동일 LONG 포지션이 이미 존재하여 진입을 스킵합니다. (config.allow_same_position=False)")
                return False
        if action == 'short' and current_short == 'short':
            if allow_same_position is False:
                logger.info("동일 SHORT 포지션이 이미 존재하여 진입을 스킵합니다. (config.allow_same_position=False)")
                return False

        # 반대 포지션 존재 시 청산 정책 (True: 자동청산 후 진입, False: 청산안함)
        if action == 'long' and current_short == 'short':
            if auto_close_opposite:
                logger.warning(f"🔄 LONG 신호 감지 → SHORT 포지션 청산 (추세 반전, config.auto_close_opposite=True)")
                close_position(exchange, symbol, 'short', short_amount)
                time.sleep(1)
            else:
                logger.info("반대 SHORT 포지션이 존재하지만 자동청산 설정이 꺼져 있어 진입을 스킵합니다. (config.auto_close_opposite=False)")
        elif action == 'short' and current_long == 'long':
            if auto_close_opposite:
                logger.warning(f"🔄 SHORT 신호 감지 → LONG 포지션 청산 (추세 반전, config.auto_close_opposite=True)")
                close_position(exchange, symbol, 'long', long_amount)
                time.sleep(1)
            else:
                logger.info("반대 LONG 포지션이 존재하지만 자동청산 설정이 꺼져 있어 진입을 스킵합니다. (config.auto_close_opposite=False)")
        
        # 2. 미체결 주문 처리 (양방향 모두 취소)
        cancel_all_open_orders(exchange, symbol)
        
        # 3. 수량 계산 (USDT → qty)
        if not entry_price or entry_price <= 0:
            logger.warning("진입가가 유효하지 않음")
            return False
        
        # amount_mode (notional 레버리지 미사용, margin 레버리지 사용) 
        effective_notional = float(usdt_amount)
        if isinstance(amount_mode, str) and amount_mode.lower() == 'margin':
            lev = float(leverage) if leverage else 1.0
            if lev < 1:
                lev = 1.0
            effective_notional = float(usdt_amount) * lev

        qty = effective_notional / float(entry_price)
        
        if qty <= 0:
            logger.warning(f"주문 수량 계산 실패: qty={qty}")
            return False
        
        # 4. 주문 실행
        order = place_order(exchange, symbol, 'limit', action, qty, entry_price) # 지정가 주문
        
        if not order:
            logger.warning("주문 실패: place_order 결과 None")
            return False
        
        logger.info(
            f"주문 완료: {action.upper()} qty={qty:.6f} {symbol} | amount_mode={amount_mode} notional={effective_notional:.2f}USDT leverage={leverage if leverage else 1}x"
        )

        # 포지션이 완전히 열릴 때까지 대기 후, 실제 포지션 수량을 재확인
        time.sleep(2)
        current_side, current_qty = get_current_position(exchange, symbol, action)
        if current_qty > 0:
            # 5. TP/SL 가격 정교화 (틱 사이즈 정렬 + 최소 간격 확보 + ATR 기반 최소 거리)
            refined_sl, refined_tp = refine_sl_tp_prices(exchange, symbol, action, entry_price, sl_price, tp_price)
            # 6. TP/SL 설정
            tp_sl_success = set_tp_sl_orders(exchange, symbol, action, current_qty, refined_sl, refined_tp)
            if tp_sl_success:
                logger.info(f"TP/SL 설정 완료: TP={refined_tp:.4f}, SL={refined_sl:.4f}")
            else:
                logger.warning(f"TP/SL 설정 실패했지만 주문은 완료됨")
        else:
            logger.warning("포지션이 아직 열리지 않아 TP/SL 주문을 스킵합니다.")
        return True
        
    except Exception as e:
        logger.error(f"거래 실행 실패: {str(e)}")
        return False


def place_order(exchange: ccxt.Exchange, symbol: str, order_type: str, side: str, amount: float, price: float = None) -> Optional[Dict]:
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
        
        if order_type == 'market':
            order = exchange.create_market_order(symbol, side, amount, params=params)
        else:
            order = exchange.create_limit_order(symbol, side, amount, price, params=params)

        logger.info(f"주문 실행: {side.upper()} {amount} {symbol} @ {price if price else 'market'} (positionIdx={params['positionIdx']})")
        return order
    except Exception as e:
        logger.error(f"주문 실패: {str(e)}")
        return None


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
        resp = session.get_instruments_info(category="linear", symbol=market_id)
        instrument = resp.get('result', {}).get('list', [{}])[0]
        tick_size = float(instrument['priceFilter']['tickSize'])
        return tick_size
    except Exception as e:
        logger.info(f"틱 사이즈 조회 실패: {e}")
        return None


def round_to_tick(price: float, tick: float, mode: str) -> float:
    """가격을 틱 사이즈에 맞춰 반올림한다 (mode: 'down'|'up'|'nearest')."""
    if tick is None or tick <= 0:
        return price
    try:
        if mode == 'down':
            return math.floor(price / tick) * tick
        elif mode == 'up':
            return math.ceil(price / tick) * tick
        else:
            # nearest
            return round(price / tick) * tick
    except Exception:
        return price


def refine_sl_tp_prices(
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
        logger.info(base)

    return sl, tp


def get_recent_atr(exchange: ccxt.Exchange, symbol: str, timeframe: str = '1m', period: int = 14, limit: int = 200) -> Optional[float]:
    """
    최근 ATR 값을 계산하여 반환
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < period + 1:
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        # True Range 계산
        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else None
    except Exception as e:
        logger.info(f"ATR 계산 실패: {e}")
        return None


def set_tp_sl_orders(exchange: ccxt.Exchange, symbol: str, position_side: str, qty: float, sl_price: float, tp_price: float) -> bool:
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
    position_idx = 1 if position_side == 'long' else 2
    
    # Bybit V5 API 표준에 맞춘 심볼 변환
    market_id = symbol.replace('/', '').split(':')[0]
    
    try:
        logger.info("[TP/SL 등록] set_tp_sl_orders 함수 진입")
        position_idx = 1 if position_side == 'long' else 2
        market_id = symbol.replace('/', '').split(':')[0]
        logger.info(f"[TP/SL 등록] 입력 파라미터: symbol={symbol}, position_side={position_side}, qty={qty}, sl_price={sl_price}, tp_price={tp_price}")
        params = {
            "category": "linear",
            "symbol": market_id,
            "positionIdx": int(position_idx),
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
        logger.info(f"[TP/SL 등록] Bybit API 호출 파라미터: {params}")
        result = exchange.private_post_v5_position_trading_stop(params)
        logger.info(f"[TP/SL 등록] Bybit API 응답: {result}")
        ret_code = result.get('retCode', -1)
        if ret_code == 0 or ret_code == '0':
            logger.info(f"[TP/SL 등록] 성공: {position_side.upper()} | TP={tp_price:.4f} | SL={sl_price:.4f}")
            return True
        else:
            ret_msg = result.get('retMsg', 'Unknown error')
            logger.error(f"[TP/SL 등록] 실패 (retCode={ret_code}): {ret_msg}")
            logger.error(f"[TP/SL 등록] 실패한 파라미터: {params}")
            return False
    except Exception as e:
        logger.error(f"[TP/SL 등록] 예외 발생: {str(e)}")
        import traceback
        logger.error(f"[TP/SL 등록] 상세 오류:\n{traceback.format_exc()}")
        return False
    return False

"""
심볼의 수량 단위 및 최소 주문 수량 조회
Args:
    symbol: 거래 심볼 (예: 'BTCUSDT' 또는 'BTC/USDT:USDT') 
Returns:
    수량 단위(qtyStep)와 최소 주문 수량(minOrderQty)
"""
def get_precision_info(symbol):
    logger.info(f'심볼의 수량 단위 및 최소 주문 수량 조회: {symbol}')

    # API 호출
    resp = session.get_instruments_info(category="linear", symbol=symbol)
    instrument = resp['result']['list'][0]
    
    # 수량 단위(qtyStep)와 최소 주문 수량(minOrderQty) 추출
    qty_step = float(instrument['lotSizeFilter']['qtyStep'])
    min_qty = float(instrument['lotSizeFilter']['minOrderQty'])
    
    return qty_step, min_qty

"""
현재 포지션 확인
Args:
    exchange: CCXT 거래소 객체
    symbol: 거래 심볼 (예: 'BTCUSDT' 또는 'BTC/USDT:USDT') 
    action: 거래 액션 ('long' 또는 'short')
Returns:
    (current_side, amount) - current_side는 'long', 'short', None
"""
def get_current_position(exchange: ccxt.Exchange, v_symbol: str, action: str) -> Tuple[Optional[str], float]:
    return_side = None
    amount = 0.0
    
    try:
        # 1. 포지션 정보 가져오기 (특정 심볼 지정)
        # Bybit V5에서는 리스트 형태로 반환됩니다.
        positions = exchange.fetch_positions([v_symbol])
        
        long_pos = None
        short_pos = None

        for pos in positions:
            side = pos['side']                   # 'long' 또는 'short'
            contracts = float(pos['contracts'])  # 보유 수량

            if side == 'long' and contracts > 0:
                long_pos = pos
            elif side == 'short' and contracts > 0:
                short_pos = pos

        if long_pos:
            logger.info(f"[{v_symbol}] Long 포지션: {long_pos['contracts']}개 보유 (평균단가: {long_pos['entryPrice']})")
            if action == 'long':
                return_side = 'long'
                amount = float(long_pos['contracts'])
        if short_pos:
            logger.info(f"[{v_symbol}] Short 포지션: {short_pos['contracts']}개 보유 (평균단가: {short_pos['entryPrice']})")
            if action == 'short':
                return_side = 'short'
                amount = float(short_pos['contracts'])

        if not long_pos and not short_pos:
            logger.info(f"[{v_symbol}] 현재 보유 중인 포지션이 없습니다.")
            
    except Exception as e:
        logger.info(f"포지션 조회 중 오류 발생: {e}")

    
    return return_side, amount


def get_all_positions(exchange: ccxt.Exchange, symbol: str) -> Tuple[Tuple[Optional[str], float, Optional[float]], Tuple[Optional[str], float, Optional[float]]]:
    """
    LONG/SHORT 포지션 동시 조회
    
    Args:
        exchange: CCXT exchange 인스턴스
        symbol: 거래 심볼
        
    Returns:
        ((long_side, long_amount, long_entry_price), (short_side, short_amount, short_entry_price))
    """
    try:
        positions = exchange.fetch_positions([symbol])
        
        long_side, long_amount, long_entry = None, 0.0, None
        short_side, short_amount, short_entry = None, 0.0, None
        
        for pos in positions:
            side = pos['side']
            contracts = float(pos['contracts'])
            entry_price = None
            try:
                if 'entryPrice' in pos and pos['entryPrice']:
                    entry_price = float(pos['entryPrice'])
                elif 'avgPrice' in pos and pos['avgPrice']:
                    entry_price = float(pos['avgPrice'])
                elif 'info' in pos and isinstance(pos['info'], dict):
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
        logger.error(f"포지션 조회 오류: {e}")
        return (None, 0.0, None), (None, 0.0, None)


def is_hedge_mode(exchange: ccxt.Exchange, symbol: str) -> bool:
    """
    거래소가 Hedge mode인지 확인 (Bybit)
    
    Returns:
        True: Hedge mode (LONG/SHORT 동시 보유 가능)
        False: One-way mode (LONG 또는 SHORT 중 하나만)
    """
    try:
        # Bybit V5 API로 position mode 조회
        market_id = symbol.replace('/', '').split(':')[0]
        resp = session.get_positions(category="linear", symbol=market_id)
        positions = resp.get('result', {}).get('list', [])
        
        if not positions:
            # 포지션이 없으면 기본값으로 Hedge mode 가정
            return True
        
        # positionIdx가 1 또는 2면 Hedge mode
        for pos in positions:
            position_idx = pos.get('positionIdx', 0)
            if position_idx in [1, 2]:
                return True
        
        return False
    except Exception as e:
        logger.debug(f"Position mode 조회 실패, Hedge mode로 가정: {e}")
        return True  # 안전하게 Hedge mode로 가정


def get_position_created_time(exchange: ccxt.Exchange, symbol: str, side: str) -> Optional[float]:
    """
    포지션 진입 시간 조회 (Bybit API의 createdTime 사용)
    
    Args:
        symbol: 거래 심볼
        side: 포지션 방향 ('long' 또는 'short')
        
    Returns:
        진입 시간 (Unix timestamp in milliseconds) 또는 None
    """
    try:
        positions = exchange.fetch_positions([symbol])
        target_side = side.lower()
        
        for pos in positions:
            pos_side = (pos.get('side') or '').lower()
            contracts = float(pos.get('contracts', 0))
            
            if pos_side == target_side and contracts > 0:
                # info 필드에서 createdTime 추출
                if 'info' in pos and isinstance(pos['info'], dict):
                    created_time = pos['info'].get('createdTime')
                    if created_time:
                        return int(created_time)
                
                # 대안: timestamp 필드 사용
                if 'timestamp' in pos and pos['timestamp']:
                    return int(pos['timestamp'])
        
        return None
    except Exception as e:
        logger.error(f"포지션 진입 시간 조회 실패: {e}")
        import traceback
        logger.debug(f"상세 오류:\n{traceback.format_exc()}")
        return None


def get_tp_sl_for_side(symbol: str, side: str) -> Tuple[Optional[float], Optional[float]]:
    """
    현재 포지션(side)의 TP/SL 가격 조회 (Bybit Unified V5 via pybit)
    Args:
        symbol: 예) 'XRPUSDT' 또는 'XRP/USDT:USDT'
        side: 'long' or 'short'
    Returns:
        (tp_price, sl_price) 둘 다 없으면 (None, None)
    """
    try:
        market_id = symbol.replace('/', '').split(':')[0]
        resp = session.get_positions(category="linear", symbol=market_id)
        lst = resp.get('result', {}).get('list', [])
        if not lst:
            logger.debug(f"TP/SL 조회: 포지션 목록이 비어있음 ({market_id})")
            return None, None
        target_idx = 1 if side == 'long' else 2
        tp, sl = None, None
        for p in lst:
            try:
                idx = int(p.get('positionIdx', 0))
            except Exception:
                idx = 0
            if idx == target_idx:
                tp_raw = p.get('takeProfit')
                sl_raw = p.get('stopLoss')
                logger.debug(f"TP/SL 원본 값: side={side}, idx={idx}, tp_raw={tp_raw}, sl_raw={sl_raw}")
                try:
                    # Bybit는 "0" 또는 빈 문자열로 TP/SL이 없음을 표시할 수 있음
                    if tp_raw and tp_raw != "" and tp_raw != "0" and float(tp_raw) != 0:
                        tp = float(tp_raw)
                except Exception:
                    tp = None
                try:
                    if sl_raw and sl_raw != "" and sl_raw != "0" and float(sl_raw) != 0:
                        sl = float(sl_raw)
                except Exception:
                    sl = None
                logger.debug(f"TP/SL 최종 값: side={side}, tp={tp}, sl={sl}")
                break
        return tp, sl
    except Exception as e:
        logger.error(f"TP/SL 조회 실패: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None, None




"""
모든 미체결 주문 취소(양방향)
Args:
    exchange: CCXT 거래소 객체
    symbol: 거래 심볼
Returns:
    성공 여부
"""
def cancel_all_open_orders(exchange: ccxt.Exchange, symbol: str) -> bool:
    try:
        logger.info(f"미체결 주문 조회 중: {symbol}")
        open_orders = exchange.fetch_open_orders(symbol)
        
        if open_orders:
            order_count = len(open_orders)
            logger.info(f"미체결 주문 발견: {Colors.BOLD}{order_count}개{Colors.RESET}")
            
            for order in open_orders:
                try:
                    exchange.cancel_order(order['id'], symbol)
                    order_type = order.get('type', 'N/A')
                    order_side = order.get('side', 'N/A')
                    order_amount = order.get('amount', 'N/A')
                    if order['side'] == 'buy':
                        logger.info(f"  {Colors.GREEN}✓{Colors.RESET} 주문 취소: {Colors.CYAN}{order['id']}{Colors.RESET} ({order_side} {order_type} {order_amount})")
                    else:
                        logger.info(f"  {Colors.RED}✓{Colors.RESET} 주문 취소: {Colors.CYAN}{order['id']}{Colors.RESET} ({order_side} {order_type} {order_amount})")
                except Exception as e:
                    logger.info(f"  ✗ 주문 취소 실패 ({order['id']}): {e}")
            
            logger.info(f"모든 미체결 주문 취소 완료: {symbol} ({order_count}개)")
            return True
        else:
            logger.info(f"미체결 주문: {Colors.CYAN}없음{Colors.RESET}")
            return True
    except Exception as e:
        logger.info(f"미체결 주문 조회/취소 오류: {e}")
        return False


"""
미체결 주문 취소(포지션 사이드별)
Args:
    exchange: CCXT 거래소 객체
    symbol: 거래 심볼
Returns:
    성공 여부
"""
def cancel_open_orders(exchange: ccxt.Exchange, symbol: str, position_side: str) -> bool:
    try:
        logger.info(f"미체결 주문 조회 중: {symbol}")
        open_orders = exchange.fetch_open_orders(symbol)
        
        if open_orders:
            order_count = len(open_orders)
            logger.info(f"미체결 주문 발견: {Colors.BOLD}{order_count}개{Colors.RESET}")
            order_count = 0

            for order in open_orders:
                try:
                    if order['side'] == position_side:
                        logger.info(f"주문 취소 시도: {Colors.CYAN}{order['id']}{Colors.RESET}")
                        exchange.cancel_order(order['id'], symbol)
                        logger.info(f"{Colors.GREEN}✓{Colors.RESET} 주문 취소: {Colors.CYAN}{order['id']}{Colors.RESET} ({order.get('type', 'N/A')} {order.get('side', 'N/A')} {order.get('amount', 'N/A')})")
                        order_count += 1
                except Exception as e:
                    logger.info(f"✗ 주문 취소 실패 ({order['id']}): {e}")            
            logger.info(f"진입 시도 전 미체결 주문 취소 완료: {symbol} ({order_count}개)")
            return True
        else:
            logger.info(f"미체결 주문: {Colors.CYAN}없음{Colors.RESET}")
            return True
    except Exception as e:
        logger.info(f"미체결 주문 조회/취소 오류: {e}")
        return False

"""
주문 수량 계산 (최소 USDT 금액 기준)
Args:
    exchange: CCXT 거래소 객체
    symbol: 거래 심볼
    min_usdt: 최소 주문 금액 (USDT)
Returns:
    (amount, current_price) - 주문 수량과 현재가
"""
def calculate_order_amount(exchange: ccxt.Exchange, symbol: str, min_usdt: float = 100.0) -> Tuple[Optional[float], Optional[float]]:

    try:
        ticker = exchange.fetch_ticker(symbol)
        current_price = float(ticker['last'])
        
        # 수량 단위 및 최소 주문 수량 조회 (BTCUSDT 소수점 3자리, ETHUSDT 소수점 2자리 등)
        qty_step, min_qty = get_precision_info(symbol) 
        logger.info(f"수량 단위(qtyStep): {qty_step}, 최소 주문 수량(minOrderQty): {min_qty}")

        precision = abs(int(math.log10(qty_step))) # 소수점 자리수 계산
        result = 1.0 * (10 ** precision) # 10의 precision 승만큼 곱함

        # 최소 주문 금액 이상이 되도록 수량 계산
        #amount = math.ceil((min_usdt / current_price) * 1000) / 1000
        amount = math.ceil((min_usdt / current_price) * result) / result

        logger.info(f"현재가: ${current_price:,.2f}")
        logger.info(f"주문 수량: {amount} (최소 {min_usdt} USDT)")
        
        return amount, current_price
    except Exception as e:
        logger.info(f"가격 조회 오류: {e}")
        return None, None


"""
포지션 진입 실행 (전체 프로세스)
Args:
    exchange: CCXT 거래소 객체
    symbol: 거래 심볼
    action: 거래 액션 ('long' 또는 'short')
    order_amount: 주문하려는 금액 (USDT)
    min_order_usdt: 최소 주문 금액 (USDT) - 기본값 100
Returns:
    성공 여부
"""
def execute_position_entry(
    exchange: ccxt.Exchange,
    symbol: str,
    action: str,
    order_amount: float,
    sl_ratio: float,
    tp_ratio: float,
    order_type: str,
    min_order_usdt: float = 100.0
) -> bool:

    # 포지션 확인
    current_side, amount = get_current_position(exchange, symbol, action)

    if current_side == action:
        if symbol == "ETHUSDT" and amount < 2.0 :  # 기존 포지션 수량이 매우 작을 경우 진입 허용
            logger.info(f"보유 수량 작아 진입 허용. {amount} ")
        else:
            logger.info(f"동일 포지션 존재로 진입 차단.  {current_side.upper()}, {amount}")
            return False

    # 포지션이 없을 경우, 남아있는 미체결 주문 취소
    cancel_open_orders(exchange, symbol, action)
    
    time.sleep(1)
        
    # 주문 수량 계산 (최소 주문 금액과 입력 금액 중 큰 값 사용)
    max_usdt = max(min_order_usdt, order_amount)
    amount, current_price = calculate_order_amount(exchange, symbol, max_usdt)
    
    if amount is None or current_price is None:
        logger.info(f"가격 조회 실패로 주문을 실행할 수 없습니다.")
        return False
    
    # 포지션 진입
    if action == "long":
        return open_long_position(exchange, symbol, action, amount, current_price, order_type, sl_ratio, tp_ratio)
    elif action == "short":
        return open_short_position(exchange, symbol, action, amount, current_price, order_type, sl_ratio, tp_ratio)
    else:
        #logger.info(f"Action이 'long' 또는 'short'가 아니므로 주문을 실행하지 않습니다. (현재: {action})")
        return False


"""
LONG 포지션 진입 (Bybit 전용)
Args:
    exchange: CCXT Bybit 거래소 객체
    symbol: 거래 심볼 (예: 'BTCUSDT' 또는 'BTC/USDT:USDT')
    action: 거래 액션 ('long')  
    amount: 주문 수량
    entry_price: 진입 가격
    order_type: 주문 타입 ('market' 또는 'limit')
    sl_ratio: 손절 비율 (%)
    tp_ratio: 익절 비율 (%)
Returns:
    성공 여부 
""" 
def open_long_position(
    exchange: ccxt.Exchange,
    symbol: str,
    action: str,
    amount: float,
    entry_price: float,
    order_type: str,
    sl_ratio: float,
    tp_ratio: float
) -> bool:

    positionIdx = 1  # Hedge mode: Buy side

    try:
        logger.info(f"Called open_long_position() : symbol={symbol}, amount={amount}, entry_price={entry_price}, order_type={order_type}, sl_ratio={sl_ratio}, tp_ratio={tp_ratio}")
        
        # Bybit 주문 옵션 설정
        order_params = {
            'category': 'linear',       # Bybit 선물 거래 카테고리
            'positionIdx': positionIdx  # 0: One-way mode, 1: Buy side (Hedge mode)
        }
        
        # Bybit 주문 생성
        if order_type == "market": 
            # 시장가 매수 주문
            logger.info(f"시장가 매수주문 중...")
            order = exchange.create_market_buy_order(symbol, amount, order_params)
        elif order_type == "limit": 
            # 지정가 매수 주문
            logger.info(f"지정가 매수주문 중...")
            order = exchange.create_limit_buy_order(symbol, amount, entry_price, order_params)
        else:
            logger.info(f"지원하지 않는 주문 타입: {order_type}")
            return False

        order_id = order.get('id', 'N/A')
        logger.info(f"매수 주문 완료 id: {Colors.CYAN}{order_id}{Colors.RESET}")
        
        time.sleep(3) # 주문 완료 시까지 약간 대기
        
        # Bybit API를 통한 SL/TP 설정
        sl_price, tp_price = set_position_tplc(exchange
                                            , symbol=symbol
                                            , position_side=action
                                            , entry_price=entry_price
                                            , sl_ratio=sl_ratio
                                            , tp_ratio=tp_ratio
                                            , positionIdx=positionIdx
                                            , amount=amount) 
        
        # 결과 출력
        logger.info(f"\n{'='*35}")
        logger.info(f"롱 포지션 오픈 완료 (Bybit)")
        logger.info(f"{'='*35}")
        logger.info(f"{Colors.CYAN}진입가     :{Colors.RESET} {Colors.BOLD}{entry_price:,.2f}{Colors.RESET}")
        
        if sl_price is not None and tp_price is not None:
            logger.info(f"{Colors.RED}손절가     :{Colors.RESET} {Colors.BOLD}{sl_price:,.2f}{Colors.RESET} ({Colors.RED}-{sl_ratio}%{Colors.RESET})")
            logger.info(f"{Colors.GREEN}익절가     :{Colors.RESET} {Colors.BOLD}{tp_price:,.2f}{Colors.RESET} ({Colors.GREEN}+{tp_ratio}%{Colors.RESET})")
        else:
            logger.warning(f"{Colors.YELLOW}SL/TP 설정 실패{Colors.RESET} - 수동으로 설정해야 합니다")
        
        logger.info(f"{Colors.CYAN}수량        :{Colors.RESET} {Colors.BOLD}{amount}{Colors.RESET}")
        logger.info(f"{'='*35}\n")
        
        return True
        
    except Exception as e:
        logger.info(f"LONG 포지션 진입 실패: {e}")
        import traceback
        logger.error(f"상세 오류:\n{traceback.format_exc()}")
        return False


"""
SHORT 포지션 진입 (Bybit 전용)
Args:
    exchange: CCXT Bybit 거래소 객체
    symbol: 거래 심볼 (예: 'BTCUSDT' 또는 'BTC/USDT:USDT')
    action: 거래 액션 ('short')
    amount: 주문 수량
    entry_price: 진입 가격
    order_type: 주문 타입 ('market' 또는 'limit')
    sl_ratio: 손절 비율 (%)
    tp_ratio: 익절 비율 (%)
Returns:
    성공 여부 
"""
def open_short_position( 
    exchange: ccxt.Exchange,
    symbol: str,
    action: str,
    amount: float,
    entry_price: float,
    order_type: str,
    sl_ratio: float,
    tp_ratio: float
) -> bool:

    positionIdx = 2  # Hedge mode: Sell side

    try:
        logger.info(f"SHORT 포지션 진입 시작: {symbol}")
        
        # Bybit 주문 옵션 설정
        order_params = {
            'category': 'linear',      # Bybit 선물 거래 카테고리
            'positionIdx': positionIdx # 0: One-way mode, 2: Sell side (Hedge mode)
        }
        
        # 주문 생성
        if order_type == "market":
            # 시장가 매도 주문
            logger.info("시장가 매도 주문 전송 중...")
            order = exchange.create_market_sell_order(symbol, amount, order_params)
        elif order_type == "limit":
            # 지정가 매도 주문
            logger.info(f"지정가 매도 주문 전송 중... (가격: {entry_price})")
            order = exchange.create_limit_sell_order(symbol, amount, entry_price, None, order_params)
        else:
            logger.info(f"지원하지 않는 주문 타입: {order_type}")
            return False

        order_id = order.get('id', 'N/A')
        logger.info(f"매도 주문 완료: {Colors.CYAN}{order_id}{Colors.RESET})")
        
        
        time.sleep(3) # 주문 완료 시까지 약간 대기
        
        # Bybit API를 통한 SL/TP 설정
        sl_price, tp_price = set_position_tplc(exchange
                                            , symbol=symbol
                                            , position_side=action
                                            , entry_price=entry_price
                                            , sl_ratio=sl_ratio
                                            , tp_ratio=tp_ratio
                                            , positionIdx=positionIdx
                                            , amount=amount) 
        
        # 결과 출력
        logger.info(f"\n{'='*35}")
        logger.info(f"숏 포지션 오픈 완료 (Bybit)")
        logger.info(f"{'='*35}")
        logger.info(f"{Colors.CYAN}진입가     :{Colors.RESET} {Colors.BOLD}{entry_price:,.2f}{Colors.RESET}")
        
        if sl_price is not None and tp_price is not None:
            logger.info(f"{Colors.RED}손절가     :{Colors.RESET} {Colors.BOLD}{sl_price:,.2f}{Colors.RESET} ({Colors.RED}+{sl_ratio}%{Colors.RESET})")
            logger.info(f"{Colors.GREEN}익절가     :{Colors.RESET} {Colors.BOLD}{tp_price:,.2f}{Colors.RESET} ({Colors.GREEN}-{tp_ratio}%{Colors.RESET})")
        else:
            logger.warning(f"{Colors.YELLOW}SL/TP 설정 실패{Colors.RESET} - 수동으로 설정해야 합니다")
        
        logger.info(f"{Colors.CYAN}수량        :{Colors.RESET} {Colors.BOLD}{amount}{Colors.RESET}")
        logger.info(f"{'='*35}\n")
        
        return True
        
    except Exception as e:
        logger.info(f"SHORT 포지션 진입 실패: {e}")
        import traceback
        logger.info(f"상세 오류:\n{traceback.format_exc()}")
        return False


"""
손절/익절 설정
Args:
    exchange: CCXT 거래소 객체
    symbol: 거래 심볼

Returns:
    (sl_price, tp_price) 
"""
def set_position_tplc(exchange: ccxt.Exchange
                    , symbol: str
                    , position_side: str
                    , entry_price: float
                    , sl_ratio: float
                    , tp_ratio: float
                    , positionIdx: int
                    , amount: float) -> Tuple[Optional[float], Optional[float]]:

        if position_side == 'long':
            # SL/TP 가격 계산 (LONG의 경우)
            sl_price = round(entry_price * (1.0 - (sl_ratio/100)), 2)   # sl_ratio % 하락 (손절)
            tp_price = round(entry_price * (1.0 + (tp_ratio/100)), 2)   # tp_ratio % 상승 (익절)
        elif position_side == 'short':
            # SL/TP 가격 계산 (SHORT의 경우)
            sl_price = round(entry_price * (1.0 + (sl_ratio/100)), 2)   # sl_ratio % 상승 (손절)
            tp_price = round(entry_price * (1.0 - (tp_ratio/100)), 2)   # tp_ratio % 하락 (익절)
        else:
            logger.info(f"지원하지 않는 포지션 사이드: {position_side}")
            return None, None

        logger.info(f"Position side: {position_side}")
        logger.info(f"Entry price  : {entry_price:,.2f}")
        logger.info(f"Stop Loss    : {sl_price:,.2f} ({Colors.RED}-{sl_ratio}%{Colors.RESET})")
        logger.info(f"Take Profit  : {tp_price:,.2f} ({Colors.GREEN}+{tp_ratio}%{Colors.RESET})")

        # Bybit API를 통한 SL/TP 설정
        if hasattr(exchange, 'private_post_v5_position_trading_stop'):
            try:
                # Bybit V5 API 표준에 맞춘 심볼 변환 (예: BTC/USDT:USDT -> BTCUSDT)
                market_id = symbol.replace('/', '').split(':')[0]

                params = {
                    "category": "linear",
                    "symbol": market_id,
                    "positionIdx": int(positionIdx), # 정수형 보장
                    "takeProfit" : str(tp_price),
                    "tpSize"     : str(amount),  # Partial 모드: TP 수량
                    "stopLoss"   : str(sl_price),
                    "slSize"     : str(amount),  # Partial 모드: SL 수량
                    "tpTriggerBy": "LastPrice",
                    "slTriggerBy": "LastPrice",
                    "tpslMode"   : "Partial",  # Partial: 부분 청산 허용 (Limit/Market 모두 가능)
                }

                if position_side == "long":
                    # Partial 모드: Limit/Market 모두 가능
                    params.update({
                        "tpOrderType": "Limit",  # Partial 모드에서는 Limit 사용 가능
                        "slOrderType": "Market", # 손절은 Market으로 확실하게
                        "tpTriggerDirection": 1,
                        "slTriggerDirection": 2
                    })
                else: # short
                    # Partial 모드: Limit/Market 모두 가능
                    params.update({
                        "tpOrderType": "Limit",  # Partial 모드에서는 Limit 사용 가능
                        "slOrderType": "Market", # 손절은 Market으로 확실하게
                        "tpTriggerDirection": 2,
                        "slTriggerDirection": 1
                    })
                    
                logger.info(f"SL/TP 설정 파라미터: {params}")
                result = exchange.private_post_v5_position_trading_stop(params)
                logger.info(f"1.손절/익절 설정 완료: {result}")

            except AttributeError as ae:
                logger.error(f"메서드 오류: {ae}")
                logger.error(f"exchange 객체 타입: {type(exchange)}")
                logger.error(f"사용 가능한 메서드: {[m for m in dir(exchange) if 'trading_stop' in m.lower()]}")
                import traceback
                logger.error(f"상세 오류:\n{traceback.format_exc()}")
                # SL/TP 설정 실패해도 주문은 성공했으므로 계속 진행
                return None, None
            except Exception as e:
                logger.error(f"1.손절/익절 설정 실패: {e}")
                import traceback
                logger.error(f"상세 오류:\n{traceback.format_exc()}")
                # SL/TP 설정 실패해도 주문은 성공했으므로 계속 진행
                return None, None
            
        else:
            logger.info("손절/익절 설정을 지원하지 않는 거래소입니다.")
            return None, None

        return sl_price, tp_price


"""
포지션 청산 (Bybit 전용)
특정 심볼에 대해 열려있는 모든 포지션을 청산할 수 있습니다.
One-way mode와 Hedge mode 모두 지원합니다.

Args:
    exchange: CCXT Bybit 거래소 객체
    symbol: 거래 심볼 (예: 'BTCUSDT' 또는 'BTC/USDT:USDT')
    side: 포지션 방향 ('long' 또는 'short') - None이면 자동 감지하여 전체 청산
    amount: 청산할 수량 (None이면 전체 청산)

동작 방식:
    - One-way mode: positionIdx=0으로 설정하여 포지션 청산
    - Hedge mode: 
      * side=None: LONG(positionIdx=1)과 SHORT(positionIdx=2) 모두 청산
      * side="long": LONG만 청산 (positionIdx=1)
      * side="short": SHORT만 청산 (positionIdx=2)
    
사용 예시:
    # One-way mode: 특정 심볼의 모든 포지션 자동 청산
    close_position(exchange, "BTCUSDT")
    
    # Hedge mode: 모든 포지션 청산 (LONG과 SHORT 모두)
    close_position(exchange, "BTCUSDT")  # 자동으로 LONG과 SHORT 모두 청산
    
    # Hedge mode: 특정 방향만 청산
    close_position(exchange, "BTCUSDT", side="long")   # LONG만 청산
    close_position(exchange, "BTCUSDT", side="short")  # SHORT만 청산
    
    # 부분 청산
    close_position(exchange, "BTCUSDT", side="long", amount=0.01)

Returns:
    성공 여부 (bool)
"""
def close_position(
    exchange: ccxt.Exchange,
    symbol: str,
    side: Optional[str] = None,
    amount: Optional[float] = None
) -> bool:
    
    global position_peak_tracker
    
    try:
        logger.info(f"포지션 청산 시작: {symbol}")
        
        # 포지션 청산 시 트래커 초기화
        if side:
            pos_key = f"{symbol}_{side}"
            if pos_key in position_peak_tracker:
                del position_peak_tracker[pos_key]
                logger.debug(f"수익 추적 초기화: {pos_key}")
        
        # Position mode 확인 (Hedge mode vs One-way mode)
        hedge_mode = is_hedge_mode(exchange, symbol)
        logger.debug(f"Position mode: {'Hedge' if hedge_mode else 'One-way'}")
        
        # 현재 포지션 확인
        (current_long, long_amt, _), (current_short, short_amt, _) = get_all_positions(exchange, symbol)
        has_any_position = (current_long == 'long') or (current_short == 'short')
        
        if not has_any_position:
            logger.info(f"청산할 포지션이 없습니다: {symbol}")
            return True
        
        # side가 지정되지 않았으면 모든 포지션 청산
        if side is None:
            success = True
            if current_long == 'long':
                position_idx = 1 if hedge_mode else 0
                logger.info(f"LONG 포지션 청산 (positionIdx={position_idx})")
                long_success = _close_single_position(
                    exchange, symbol, 'long', long_amt, positionIdx=position_idx
                )
                success = success and long_success
                if current_short == 'short':
                    time.sleep(0.5)
            
            if current_short == 'short':
                position_idx = 2 if hedge_mode else 0
                logger.info(f"SHORT 포지션 청산 (positionIdx={position_idx})")
                short_success = _close_single_position(
                    exchange, symbol, 'short', short_amt, positionIdx=position_idx
                )
                success = success and short_success
            
            return success
        
        # 특정 방향만 청산
        if side == 'long':
            if current_long != 'long':
                logger.info(f"LONG 포지션이 없습니다.")
                return False
            position_idx = 1 if hedge_mode else 0
            close_amount = long_amt if amount is None else min(amount, long_amt)
            return _close_single_position(
                exchange, symbol, 'long', close_amount, positionIdx=position_idx
            )
        elif side == 'short':
            if current_short != 'short':
                logger.info(f"SHORT 포지션이 없습니다.")
                return False
            position_idx = 2 if hedge_mode else 0
            close_amount = short_amt if amount is None else min(amount, short_amt)
            return _close_single_position(
                exchange, symbol, 'short', close_amount, positionIdx=position_idx
            )
        else:
            logger.info(f"지원하지 않는 포지션 방향: {side}")
            return False
        
    except Exception as e:
        logger.info(f"포지션 청산 실패: {e}")
        import traceback
        logger.info(f"상세 오류:\n{traceback.format_exc()}")
        return False


"""
단일 포지션 청산 (내부 헬퍼 함수)
One-way mode와 Hedge mode 모두 지원합니다.

Args:
    exchange: CCXT Bybit 거래소 객체
    symbol: 거래 심볼
    side: 포지션 방향 ('long' 또는 'short')
    amount: 청산할 수량
    positionIdx: 포지션 인덱스
        - 0: One-way mode
        - 1: Hedge mode (Buy side / LONG)
        - 2: Hedge mode (Sell side / SHORT)

Returns:
    성공 여부 (bool)
"""
def _close_single_position(
    exchange: ccxt.Exchange,
    symbol: str,
    side: str,
    amount: float,
    positionIdx: int = 0
) -> bool:
    """단일 포지션 청산 헬퍼 함수"""
    try:
        logger.info(f"{side.upper()} 포지션 청산 중... (수량: {amount}, positionIdx: {positionIdx})")
        
        # Bybit 주문 옵션 설정
        order_params = {
            'category': 'linear',
            'positionIdx': positionIdx,  # 0: One-way, 1: Hedge Buy, 2: Hedge Sell
            'reduceOnly': True
        }
        
        # 반대 방향 주문으로 청산
        if side == 'long':
            order = exchange.create_market_sell_order(symbol, amount, order_params)
        elif side == 'short':
            order = exchange.create_market_buy_order(symbol, amount, order_params)
        else:
            logger.info(f"지원하지 않는 포지션 방향: {side}")
            return False
        
        order_id = order.get('id', 'N/A')
        logger.info(f"청산 주문 완료: {Colors.CYAN}{order_id}{Colors.RESET}")
        
        # Profit Trailing Stop 추적 초기화
        pos_key = f"{symbol}_{side}"
        if pos_key in position_peak_tracker:
            del position_peak_tracker[pos_key]
            logger.debug(f"수익 추적 초기화: {pos_key}")
        
        # 결과 출력
        logger.info(f"{'='*35}")
        logger.info(f"포지션 청산 완료 (Bybit)")
        logger.info(f"{'='*35}")
        logger.info(f"{Colors.CYAN}Symbol     :{Colors.RESET} {Colors.BOLD}{symbol}{Colors.RESET}")
        logger.info(f"{Colors.YELLOW}Side       :{Colors.RESET} {Colors.BOLD}{side.upper()}{Colors.RESET}")
        logger.info(f"{Colors.CYAN}Amount     :{Colors.RESET} {Colors.BOLD}{amount}{Colors.RESET}")
        logger.info(f"{Colors.CYAN}PositionIdx:{Colors.RESET} {Colors.BOLD}{positionIdx}{Colors.RESET}")
        logger.info(f"{'='*35}")
        
        return True
        
    except Exception as e:
        logger.info(f"{side.upper()} 포지션 청산 실패: {e}")
        return False


"""
모든 포지션 청산 (Bybit 전용)
열려있는 모든 심볼의 포지션을 한번에 청산합니다.
One-way mode와 Hedge mode 모두 지원합니다.

Args:
    exchange: CCXT Bybit 거래소 객체
    category: 거래 카테고리 ('linear', 'inverse', 'option') - 기본값: 'linear'
    side: 포지션 방향 ('long' 또는 'short') - None이면 모든 방향 청산
    
사용 예시:
    # 모든 포지션 청산 (모든 심볼, 모든 방향)
    close_all_positions(exchange)
    
    # 특정 방향만 청산 (모든 심볼)
    close_all_positions(exchange, side="long")
    close_all_positions(exchange, side="short")

Returns:
    청산 결과 딕셔너리: {'success': int, 'failed': int, 'total': int, 'symbols': list}
"""
def close_all_positions(
    exchange: ccxt.Exchange,
    category: str = 'linear',
    side: Optional[str] = None
) -> dict:
    
    try:
        logger.info(f"\n{'='*50}")
        logger.info(f"  Close All Positions (Bybit)")
        logger.info(f"{'='*50}")
        logger.info(f"카테고리: {category}, 방향: {side if side else 'ALL'}")
        
        # 모든 포지션 조회
        logger.info("모든 포지션 조회 중...")
        all_positions = exchange.fetch_positions()
        
        # 열려있는 포지션 필터링
        open_positions = []
        for position in all_positions:
            # 카테고리 필터링
            if category and position.get('info', {}).get('category') != category:
                continue
            
            # 포지션 수량 확인
            if 'info' in position and 'positionAmt' in position['info']:
                amt = float(position['info']['positionAmt'])
            elif 'contracts' in position:
                amt = float(position['contracts'])
            else:
                amt = float(position.get('size', 0))
            
            # 열려있는 포지션만 추가
            if abs(amt) > 0:
                pos_side = 'long' if amt > 0 else 'short'
                # side 필터링
                if side is None or pos_side == side:
                    open_positions.append({
                        'symbol': position['symbol'],
                        'side': pos_side,
                        'amount': abs(amt),
                        'position': position
                    })
        
        if not open_positions:
            logger.info("청산할 포지션이 없습니다.")
            return {'success': 0, 'failed': 0, 'total': 0, 'symbols': []}
        
        logger.info(f"열려있는 포지션: {Colors.BOLD}{len(open_positions)}개{Colors.RESET}")
        for pos in open_positions:
            logger.info(f"  - {pos['symbol']}: {pos['side'].upper()} {pos['amount']}")
        
        # 각 포지션 청산
        results = {
            'success': 0,
            'failed': 0,
            'total': len(open_positions),
            'symbols': []
        }
        
        logger.info(f"\n포지션 청산 시작...\n")
        
        for i, pos in enumerate(open_positions, 1):
            symbol = pos['symbol']
            pos_side = pos['side']
            amount = pos['amount']
            
            logger.info(f"[{i}/{len(open_positions)}] {symbol} ({pos_side.upper()} {amount}) 청산 중...")
            
            try:
                success = close_position(exchange, symbol, side=pos_side, amount=None)
                if success:
                    results['success'] += 1
                    results['symbols'].append({'symbol': symbol, 'side': pos_side, 'status': 'success'})
                    logger.info(f"✓ {symbol} 청산 완료\n")
                else:
                    results['failed'] += 1
                    results['symbols'].append({'symbol': symbol, 'side': pos_side, 'status': 'failed'})
                    logger.info(f"✗ {symbol} 청산 실패\n")
                
                # 다음 청산 전 약간 대기 (API 레이트 리밋 방지)
                if i < len(open_positions):
                    time.sleep(0.5)
                    
            except Exception as e:
                results['failed'] += 1
                results['symbols'].append({'symbol': symbol, 'side': pos_side, 'status': 'error', 'error': str(e)})
                logger.info(f"✗ {symbol} 청산 중 오류: {e}\n")
        
        # 최종 결과 출력
        logger.info(f"\n{'='*50}")
        logger.info(f"  청산 완료 요약")
        logger.info(f"{'='*50}")
        logger.info(f"{Colors.GREEN}성공:{Colors.RESET} {Colors.BOLD}{results['success']}{Colors.RESET}개")
        logger.info(f"{Colors.RED}실패:{Colors.RESET} {Colors.BOLD}{results['failed']}{Colors.RESET}개")
        logger.info(f"{Colors.CYAN}전체:{Colors.RESET} {Colors.BOLD}{results['total']}{Colors.RESET}개")
        logger.info(f"{'='*50}\n")
        
        return results
        
    except Exception as e:
        logger.info(f"모든 포지션 청산 실패: {e}")
        import traceback
        logger.info(f"상세 오류:\n{traceback.format_exc()}")
        return {'success': 0, 'failed': 0, 'total': 0, 'symbols': [], 'error': str(e)}


def close_orphaned_position(exchange: ccxt.Exchange, symbol: str, side: str) -> bool:
    """
    고아 포지션을 시장가로 즉시 청산
    
    Args:
        exchange: CCXT exchange object
        symbol: Trading symbol
        side: Position side ('LONG' or 'SHORT' in uppercase, or 'long'/'short' in lowercase)
    
    Returns:
        bool: True if close was successful, False otherwise
    """
    try:
        # Normalize side to lowercase
        side_lower = side.lower()
        
        # Opposite side order to close position
        close_side = 'sell' if side_lower == 'long' else 'buy'
        
        # Get current position size
        positions = exchange.fetch_positions(symbols=[symbol])
        if not positions:
            logger.warning(f"Could not fetch position size for {symbol}")
            return False
        
        pos = positions[0]
        position_amount = abs(pos.get('contracts', 0))
        
        if position_amount <= 0:
            logger.info(f"No position to close for {symbol}")
            return False
        
        # Create market close order
        logger.info(f"고아 포지션 청산 시도: 방향={side_lower}, 수량={position_amount}")
        
        order = exchange.create_order(
            symbol=symbol,
            type='market',
            side=close_side,
            amount=position_amount
        )
        
        logger.info(f"{Colors.GREEN}고아 포지션 청산 완료: {order.get('id')}{Colors.RESET}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to close orphaned position: {type(e).__name__}: {str(e)}")
        return False


def check_profit_trailing_stop(symbol: str, side: str, current_pnl_pct: Optional[float], entry_price: float, config: Dict) -> Tuple[bool, str]:
    """
    수익 보호 트레일링 스탑 체크
    
    Args:
        symbol: 거래 심볼
        side: 포지션 방향 ('long' 또는 'short')
        current_pnl_pct: 현재 수익률 (소수, 예: 0.01 = 1%)
        entry_price: 진입가
        config: 설정 딕셔너리
        
    Returns:
        (청산 여부, 청산 사유)
    """
    global position_peak_tracker
    
    # 설정 확인
    if not config['risk_management'].get('use_profit_trailing', False):
        return False, ""
    
    # 현재 수익률이 없으면 체크 안함
    if current_pnl_pct is None:
        return False, ""
    
    # 손실 포지션은 체크 안함
    if current_pnl_pct <= 0:
        return False, ""
    
    # 설정값 가져오기
    activation_threshold = config['risk_management'].get('profit_trailing_activation', 0.005)  # 0.5% 수익 시 활성화
    drawdown_threshold = config['risk_management'].get('profit_trailing_drawdown', 0.3)  # 고점 대비 30% 하락 시 청산
    
    # 활성화 임계값 미달 시 체크 안함
    if current_pnl_pct < activation_threshold:
        return False, ""
    
    # 포지션 키 생성
    pos_key = f"{symbol}_{side}"
    
    # 최고 수익률 추적
    if pos_key not in position_peak_tracker:
        position_peak_tracker[pos_key] = {
            'peak_pnl': current_pnl_pct,
            'entry_price': entry_price
        }
        logger.info(f"📈 {side.upper()} 포지션 수익 추적 시작: 고점 {(current_pnl_pct*100):.2f}%")
        return False, ""
    
    tracker = position_peak_tracker[pos_key]
    
    # 새로운 고점 갱신
    if current_pnl_pct > tracker['peak_pnl']:
        old_peak = tracker['peak_pnl']
        tracker['peak_pnl'] = current_pnl_pct
        logger.info(f"📈 {side.upper()} 포지션 새 고점: {(old_peak*100):.2f}% → {(current_pnl_pct*100):.2f}%")
        return False, ""
    
    # 고점 대비 하락률 계산
    peak_pnl = tracker['peak_pnl']
    drawdown_from_peak = (peak_pnl - current_pnl_pct) / peak_pnl
    
    # 로그 출력 (디버깅용)
    logger.debug(
        f"💹 수익 추적: 현재 {(current_pnl_pct*100):.2f}% | "
        f"고점 {(peak_pnl*100):.2f}% | "
        f"하락률 {(drawdown_from_peak*100):.1f}% (임계값: {(drawdown_threshold*100):.0f}%)"
    )
    
    # 고점 대비 임계값 이상 하락 시 청산
    if drawdown_from_peak >= drawdown_threshold:
        reason = f"고점 {(peak_pnl*100):.2f}% 대비 {(drawdown_from_peak*100):.1f}% 하락"
        # 트래커 초기화
        del position_peak_tracker[pos_key]
        return True, reason
    
    return False, ""


def check_position_status(exchange, symbol: str, config: Dict, cache=None):
    """
    포지션 상태 확인 및 출력 (모니터링 + Profit Trailing Stop 전용)
    
    Args:
        exchange: CCXT 거래소 객체
        symbol: 거래 심볼
        config: 설정 딕셔너리
        cache: 캐시 객체
        
    Returns:
        Tuple: (has_long, has_short, long_amount, short_amount)
        - has_long: LONG 포지션 존재 여부 (bool)
        - has_short: SHORT 포지션 존재 여부 (bool)
        - long_amount: LONG 포지션 수량 (float)
        - short_amount: SHORT 포지션 수량 (float)
    """
    try:
        # 1. 현재 포지션 확인
        (current_long, long_amount, long_entry), (current_short, short_amount, short_entry) = get_all_positions(exchange, symbol)
        has_long = (current_long == 'long')
        has_short = (current_short == 'short')
        
        # 2. 포지션이 없으면 바로 리턴
        if not has_long and not has_short:
            return False, False, 0, 0
        
        # 3. 현재 가격 조회
        current_price = None
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = float(ticker.get('last') or ticker.get('close'))
        except Exception:
            current_price = None
        
        # 4. LONG 포지션 상태 출력 및 Profit Trailing Stop 체크
        if current_long == 'long':
            pnl_pct = None
            pnl_usdt = None
            if long_entry and current_price:
                pnl_pct = (current_price - long_entry) / long_entry
                pnl_usdt = (current_price - long_entry) * long_amount
            
            # TP/SL 조회
            tp_price, sl_price = get_tp_sl_for_side(symbol, 'long')
            msg = f"[포지션 모니터링] LONG {long_amount:.4f}개"
            if long_entry:
                msg += f" | 진입가 {long_entry:.4f}"
            if pnl_pct is not None:
                msg += f" | 손익 {(pnl_pct*100):.2f}%"
            if pnl_usdt is not None:
                msg += f" ({pnl_usdt:+.2f} USDT)"
            if tp_price:
                msg += f" | TP {tp_price:.4f}"
            if sl_price:
                msg += f" | SL {sl_price:.4f}"
            logger.info(f"{Colors.GREEN}{msg}{Colors.RESET}")
            
            # Profit Trailing Stop 체크
            should_close, reason = check_profit_trailing_stop(
                symbol, 'long', pnl_pct, long_entry, config
            )
            if should_close:
                logger.warning(f"💰 LONG 포지션 수익 보호 청산! ({reason})")
                close_position(exchange, symbol, 'long', long_amount)
        
        # 5. SHORT 포지션 상태 출력 및 Profit Trailing Stop 체크
        if current_short == 'short':
            pnl_pct = None
            pnl_usdt = None
            if short_entry and current_price:
                pnl_pct = (short_entry - current_price) / short_entry
                pnl_usdt = (short_entry - current_price) * short_amount
            
            # TP/SL 조회
            tp_price, sl_price = get_tp_sl_for_side(symbol, 'short')
            msg = f"[포지션 모니터링] SHORT {short_amount:.4f}개"
            if short_entry:
                msg += f" | 진입가 {short_entry:.4f}"
            if pnl_pct is not None:
                msg += f" | 손익 {(pnl_pct*100):.2f}%"
            if pnl_usdt is not None:
                msg += f" ({pnl_usdt:+.2f} USDT)"
            if tp_price:
                msg += f" | TP {tp_price:.4f}"
            if sl_price:
                msg += f" | SL {sl_price:.4f}"
            logger.info(f"{Colors.RED}{msg}{Colors.RESET}")
            
            # Profit Trailing Stop 체크
            should_close, reason = check_profit_trailing_stop(
                symbol, 'short', pnl_pct, short_entry, config
            )
            if should_close:
                logger.warning(f"💰 SHORT 포지션 수익 보호 청산! ({reason})")
                close_position(exchange, symbol, 'short', short_amount)
        
        return has_long, has_short, long_amount, short_amount
        
    except Exception as e:
        logger.error(f"포지션 모니터링 오류: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False, False, 0, 0


def close_and_reverse_position(exchange, symbol: str, position_type: str, position_amount: float, config: Dict) -> bool:
    """
    포지션 청산 후 즉시 반대 포지션으로 진입
    
    Args:
        exchange: CCXT 거래소 객체
        symbol: 거래 심볼
        position_type: 현재 포지션 타입 ('long' or 'short')
        position_amount: 현재 포지션 수량
        config: 설정 딕셔너리
        
    Returns:
        반대 포지션 진입 성공 여부
    """
    try:
        logger.warning(f"🔄 {position_type.upper()} 청산 신호 → 반대 포지션 즉시 진입")
        
        # 1. 청산 실행
        close_position(exchange, symbol, position_type, position_amount)
        
        # 2. 반대 포지션 방향 결정
        reverse_action = 'short' if position_type == 'long' else 'long'
        
        # 3. 현재가 기반 진입
        ticker = exchange.fetch_ticker(symbol)
        entry_price = float(ticker.get('last') or ticker.get('close'))
        
        # 4. SL/TP 계산 (진입가 기준)
        sl_ratio = config['risk_management']['sl_ratio']
        tp_ratio = config['risk_management']['tp_ratio']
        
        if reverse_action == 'long':
            sl_price = entry_price * (1 - sl_ratio)
            tp_price = entry_price * (1 + tp_ratio)
        else:
            sl_price = entry_price * (1 + sl_ratio)
            tp_price = entry_price * (1 - tp_ratio)
        
        # 5. 반대 포지션 진입
        success = execute_trade(
            exchange,
            symbol,
            reverse_action,
            config['trading']['order_amount_usdt'],
            entry_price,
            sl_price,
            tp_price,
            amount_mode=config['trading'].get('amount_mode', 'notional'),
            leverage=config['trading'].get('leverage', 1)
        )
        
        if success:
            print_success(f"✓ 반대 포지션 {reverse_action.upper()} 진입 완료!")
        
        return success
        
    except Exception as e:
        logger.error(f"포지션 청산/반전 오류: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

# 진입 신호 자료를 한 번에 생성하는 함수
def get_entry_signal(exchange, config, cache, trend):
    """
    진입 신호 자료를 한 번에 생성 (main에서 한 줄로 사용)
    Args:
        exchange: CCXT 거래소 인스턴스
        config: 설정 dict
        cache: 데이터 캐시
        trend: 'uptrend' 또는 'downtrend' (진입 방향)
    Returns:
        analysis dict (진입가, 손절가, 익절가 등)
    """
    from aibot_v2.trend_strategy import fetch_ohlcv_data, generate_entry_order
    from aibot_v2 import technical_indicators
    # 데이터 준비
    base_df = fetch_ohlcv_data(
        exchange, config['trading']['symbol'], '1m', limit=1500, cache=cache)
    lower_df = resample_data(base_df, '5m')
    entry_trigger_df = base_df
    direction = 'long' if trend == 'uptrend' else 'short'
    
    # 실시간 현재가 조회
    try:
        ticker = exchange.fetch_ticker(config['trading']['symbol'])
        current_price = ticker['last']
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"실시간 현재가 조회 실패: {e}")
        current_price = entry_trigger_df['close'].iloc[-1]  # fallback
    return generate_entry_order(direction, lower_df, entry_trigger_df, config, current_price=current_price)
