"""
포지션 관리 모듈
포지션 확인, 미체결 주문 취소, 포지션 진입 및 SL/TP 설정
"""

import math
import time
import ccxt
from typing import Optional, Tuple
from color_utils import *
from pybit.unified_trading import HTTP

import log_config
import logging

# Reuse existing logger if already configured by main.py; otherwise set it up here.
logger = log_config.get_logger()
if not logger.handlers:
    logger = log_config.setup_logging(log_dir="logs", log_level=logging.INFO)
else:
    logger.setLevel(logging.INFO)

session = HTTP(testnet=False)

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



"""
모든 미체결 주문 취소
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
                    if order['side'] == 'buy':
                        logger.info(f"매수 주문 취소 시도: {Colors.CYAN}{order['id']}{Colors.RESET}")
                        exchange.cancel_order(order['id'], symbol)
                        order_type = order.get('type', 'N/A')
                        order_side = order.get('side', 'N/A')
                        order_amount = order.get('amount', 'N/A')
                        logger.info(f"  {Colors.GREEN}✓{Colors.RESET} 주문 취소: {Colors.CYAN}{order['id']}{Colors.RESET} ({order_side} {order_type} {order_amount})")
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
포지션별 미체결 주문 취소
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
        logger.info(f"LONG Position Opened (Bybit)")
        logger.info(f"{'='*35}")
        logger.info(f"{Colors.CYAN}Entry price:{Colors.RESET} {Colors.BOLD}{entry_price:,.2f}{Colors.RESET}")
        
        if sl_price is not None and tp_price is not None:
            logger.info(f"{Colors.RED}Stop Loss  :{Colors.RESET} {Colors.BOLD}{sl_price:,.2f}{Colors.RESET} ({Colors.RED}-{sl_ratio}%{Colors.RESET})")
            logger.info(f"{Colors.GREEN}Take Profit:{Colors.RESET} {Colors.BOLD}{tp_price:,.2f}{Colors.RESET} ({Colors.GREEN}+{tp_ratio}%{Colors.RESET})")
        else:
            logger.warning(f"{Colors.YELLOW}SL/TP 설정 실패{Colors.RESET} - 수동으로 설정해야 합니다")
        
        logger.info(f"{Colors.CYAN}Amount     :{Colors.RESET} {Colors.BOLD}{amount}{Colors.RESET}")
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
            order = exchange.create_market_sell_order(symbol, amount, None, None, order_params)
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
        logger.info(f"SHORT Position Opened (Bybit)")
        logger.info(f"{'='*35}")
        logger.info(f"{Colors.CYAN}Entry price:{Colors.RESET} ${Colors.BOLD}{entry_price:,.2f}{Colors.RESET}")
        
        if sl_price is not None and tp_price is not None:
            logger.info(f"{Colors.RED}Stop Loss  :{Colors.RESET} ${Colors.BOLD}{sl_price:,.2f}{Colors.RESET} ({Colors.RED}+{sl_ratio}%{Colors.RESET})")
            logger.info(f"{Colors.GREEN}Take Profit:{Colors.RESET} ${Colors.BOLD}{tp_price:,.2f}{Colors.RESET} ({Colors.GREEN}-{tp_ratio}%{Colors.RESET})")
        else:
            logger.warning(f"{Colors.YELLOW}SL/TP 설정 실패{Colors.RESET} - 수동으로 설정해야 합니다")
        
        logger.info(f"{Colors.CYAN}Amount     :{Colors.RESET} {Colors.BOLD}{amount}{Colors.RESET}")
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
    
    try:
        logger.info(f"포지션 청산 시작: {symbol}")
        
        # 포지션 상세 조회 (Hedge mode 지원)
        try:
            positions = exchange.fetch_positions([symbol])
            long_position = None
            short_position = None
            
            for position in positions:
                if position['symbol'] == symbol:
                    # 포지션 수량 확인
                    if 'info' in position and 'positionAmt' in position['info']:
                        amt = float(position['info']['positionAmt'])
                    elif 'contracts' in position:
                        amt = float(position['contracts'])
                    else:
                        amt = float(position.get('size', 0))
                    
                    if amt > 0:
                        long_position = {'side': 'long', 'amount': amt, 'position': position}
                    elif amt < 0:
                        short_position = {'side': 'short', 'amount': abs(amt), 'position': position}
        except Exception as e:
            logger.info(f"상세 포지션 조회 실패, 기본 방식으로 시도: {e}")
            long_position = None
            short_position = None
        
        # 기본 방식으로 포지션 확인 (One-way mode용)
        current_side, current_amount = get_current_position(exchange, symbol)
        
        # Hedge mode 감지 (LONG과 SHORT가 동시에 존재)
        is_hedge_mode = (long_position is not None) and (short_position is not None)
        
        if not current_side and not is_hedge_mode:
            logger.info(f"청산할 포지션이 없습니다: {symbol}")
            return True  # 포지션이 없으면 성공으로 처리
        
        # Hedge mode인 경우 모든 포지션 청산
        if is_hedge_mode:
            logger.info(f"Hedge mode 감지: LONG {long_position['amount']}, SHORT {short_position['amount']}")
            
            if side is None:
                # 모든 포지션 청산
                logger.info("모든 포지션 청산 중...")
                success = True
                
                # LONG 포지션 청산
                if long_position['amount'] > 0:
                    long_success = _close_single_position(
                        exchange, symbol, 'long', 
                        long_position['amount'] if amount is None else min(amount, long_position['amount']),
                        positionIdx=1  # Hedge mode: Buy side
                    )
                    success = success and long_success
                    time.sleep(0.5)
                
                # SHORT 포지션 청산
                if short_position['amount'] > 0:
                    short_success = _close_single_position(
                        exchange, symbol, 'short',
                        short_position['amount'] if amount is None else min(amount, short_position['amount']),
                        positionIdx=2  # Hedge mode: Sell side
                    )
                    success = success and short_success
                
                return success
            else:
                # 특정 방향만 청산
                if side == 'long' and long_position:
                    return _close_single_position(
                        exchange, symbol, 'long',
                        long_position['amount'] if amount is None else min(amount, long_position['amount']),
                        positionIdx=1
                    )
                elif side == 'short' and short_position:
                    return _close_single_position(
                        exchange, symbol, 'short',
                        short_position['amount'] if amount is None else min(amount, short_position['amount']),
                        positionIdx=2
                    )
                else:
                    logger.info(f"요청한 방향({side})의 포지션이 없습니다.")
                    return False
        
        # One-way mode 처리
        if not current_side:
            logger.info(f"청산할 포지션이 없습니다: {symbol}")
            return True
        
        # side가 지정되지 않았으면 자동 감지하여 전체 청산
        if side is None:
            side = current_side
            logger.info(f"자동 감지된 포지션 방향: {side.upper()}")
        
        # side가 현재 포지션과 일치하는지 확인
        if side != current_side:
            logger.info(f"포지션 방향 불일치: 요청={side}, 현재={current_side}")
            logger.info(f"현재 포지션({current_side})을 청산하려면 side=None으로 호출하세요.")
            return False
        
        # One-way mode로 청산 (positionIdx=0)
        return _close_single_position(
            exchange, symbol, side,
            current_amount if amount is None else min(amount, current_amount),
            positionIdx=0  # One-way mode
        )
        
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
            order = exchange.create_market_sell_order(symbol, amount, None, None, order_params)
        elif side == 'short':
            order = exchange.create_market_buy_order(symbol, amount, None, None, order_params)
        else:
            logger.info(f"지원하지 않는 포지션 방향: {side}")
            return False
        
        order_id = order.get('id', 'N/A')
        logger.info(f"청산 주문 완료: {Colors.CYAN}{order_id}{Colors.RESET}")
        
        # 결과 출력
        logger.info(f"\n{'='*35}")
        logger.info(f"  Position Closed (Bybit)")
        logger.info(f"{'='*35}")
        logger.info(f"{Colors.CYAN}Symbol     :{Colors.RESET} {Colors.BOLD}{symbol}{Colors.RESET}")
        logger.info(f"{Colors.YELLOW}Side       :{Colors.RESET} {Colors.BOLD}{side.upper()}{Colors.RESET}")
        logger.info(f"{Colors.CYAN}Amount     :{Colors.RESET} {Colors.BOLD}{amount}{Colors.RESET}")
        logger.info(f"{Colors.CYAN}PositionIdx:{Colors.RESET} {Colors.BOLD}{positionIdx}{Colors.RESET}")
        logger.info(f"{'='*35}\n")
        
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
        logger.info(f"Attempting to close {side_lower} position: {position_amount} contracts")
        
        order = exchange.create_order(
            symbol=symbol,
            type='market',
            side=close_side,
            amount=position_amount
        )
        
        logger.info(f"{Colors.GREEN}Orphaned position closed successfully: {order.get('id')}{Colors.RESET}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to close orphaned position: {type(e).__name__}: {str(e)}")
        return False
