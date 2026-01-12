import math, time
import os
import ccxt
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime
import technical_indicators
import position_manager
from color_utils import *
import log_config

# 로깅 설정 (일별 로그 파일 자동 생성)
import logging
logger = log_config.setup_logging(
    log_dir="logs",
    log_level=logging.INFO
)

load_dotenv()

# BYBIT선물 거래소 초기화
exchange = ccxt.bybit({
    'apiKey': os.getenv("BYBIT_API_KEY"),
    'secret': os.getenv("BYBIT_API_SECRET"),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
        'adjustForTimeDifference': True
    }
})

#거래 변수 설정
v_symbol       = "ETHUSDT" #"BTC/USDT:USDT"동일 ("BTC/USDT" 안됨)
v_leverage     = -1        #레버리지 50배 (변경안함:-1)
v_order_amount = 5000      #주문하려는 최대 매수/매도 금액 USDT
v_sl_ratio     = 0.20      #손절 비율 %
v_tp_ratio     = 0.40      #익절 비율 % 

loop_count = 0
long_trades_count = 0
short_trades_count = 0
error_count = 0

start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
trades_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

#시작 로그 출력
logger.info(f"\n\n==== Bybit Trading Bot Started ====\n"
            f"Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Trading  : {v_symbol}\n"
            f"Leverage : {v_leverage if v_leverage > -1 else 'No Change'}\n"
            f"SL/TP    : {Colors.GREEN}-{v_sl_ratio}% +{v_tp_ratio}%{Colors.RESET}"
            "\n===================================")

# 레버리지 변경 실행
if v_leverage > -1:
    try:
        exchange.market(v_symbol)
        exchange.set_leverage(v_leverage, v_symbol)
        logger.info("changed leverage = ", v_leverage)
    except Exception as e:
        #logger.info(f"set_leverage Exception: {type(e).__name__}: {str(e)}")
        logger.info("equal to the present leverage = ", v_leverage)
        pass

while True:
    try:                    
        # 기본값 설정
        v_action       = None    # long / short
        v_order_type   = "limit" # market / limit
        v_order_result = None    # 주문 결과 여부


        # Bollinger Bands Start
        #logger.info('Start fetching Bollinger Bands...')
        try:
            symbol_for_boll = v_symbol if '/' in v_symbol else (v_symbol[:-4] + '/USDT')
            bands = technical_indicators.get_bollinger_for_timeframes(symbol_for_boll, timeframes=['1m', '5m', '15m', '1h', '1d'], exchange=exchange)
            #technical_indicators.print_bollinger_results(bands, decimals=6) # 결과출력
        except Exception as e:
            logger.info('Failed to fetch Bollinger bands:', type(e).__name__, str(e))

        # 현재가와 볼린저 밴드 위치 비교
        current_price = exchange.fetch_ticker(v_symbol)['last']
        logger.info(f"Current price: {current_price}")  

        band_values = {}
        tmp_str = 'Bands values : '

        for tf, v in bands.items():
            if current_price > v['upper']:
                pos = 'above_upper'  
                tmp_str = (tmp_str + f'{Colors.GREEN}{tf} Up{Colors.RESET}, ')
            elif current_price < v['lower']:
                pos = 'below_lower'  
                tmp_str = (tmp_str + f'{Colors.RED}{tf} Dn{Colors.RESET}, ')
            else:
                pos = 'inside_bands'
                tmp_str = (tmp_str + f'{tf}, ')
            band_values[tf] = pos

        logger.info(tmp_str.rstrip(', '))


        # RSI start
        try:
            symbol_for_rsi = v_symbol if '/' in v_symbol else (v_symbol[:-4] + '/USDT')
            rsi_results = technical_indicators.get_rsi_for_timeframes(symbol_for_rsi, timeframes=['1m', '5m', '15m', '1h', '1d'], exchange=exchange)
            #technical_indicators.print_rsi_results(rsi_results, decimals=2)

            rsi_values = {tf: (float(v['rsi']) if v.get('rsi') is not None else None) for tf, v in rsi_results.items()}
            rsi_1m  = rsi_values.get('1m')
            rsi_5m  = rsi_values.get('5m')
            rsi_15m = rsi_values.get('15m')
            rsi_1h  = rsi_values.get('1h')
            rsi_1d  = rsi_values.get('1d')
            logger.info(f"RSI values   : {rsi_1m:.0f}, {rsi_5m:.0f}, {rsi_15m:.0f}, {rsi_1h:.0f}, {rsi_1d:.0f}")
        except Exception as e:
            logger.info('Failed to fetch RSI:', type(e).__name__, str(e))
            rsi_results = {}
            rsi_values = {}
            rsi_1m = rsi_5m = rsi_15m = rsi_1h = rsi_1d = None

        # collect midpoints using technical_indicators (live fetch returns last candle)
        mid_15 = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '15m', 'mid')
        mid_1h = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1h', 'mid')
        mid_1d = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1d', 'mid')


        # 매수(long) 포지션 진입 조건 (조건 충족 시에만 `v_action`을 'long'으로 설정)
        # - 1m:  RSI <= 30 or 현재가가 볼린저 하단 아래
        # - 5m:  RSI <= 30 그리고 현재가가 볼린저 하단 아래
        # - 15m: RSI <= 60 그리고 현재가 < 15m 볼린저 MA(중간) 그리고 현재가 < 15m (high+low)/2
        # - 1h:  RSI <= 70 그리고 현재가가 1h 볼린저 하단 위(=below_lower 아님) 그리고 현재가 < 1h (high+low)/2
        # - 1d:  RSI >= 30 그리고 현재가가 1d 볼린저 하단 위 그리고 현재가 < 1d (high+low)/2

        # evaluate each condition safely (None이 있을 경우 False로 처리)
        cond_1m = (rsi_1m is not None and rsi_1m <= 30 or band_values['1m'] == 'below_lower')
        cond_5m = ((rsi_5m is not None and rsi_5m <= 40 and band_values['5m'] == 'below_lower')
                   or (cond_1m == True and rsi_5m <= 30 and rsi_5m <= rsi_1m))  # 1m 조건 충족 후 5m RSI가 더 낮을 때도 허용
        cond_15m = (
            rsi_15m is not None and rsi_15m <= 60
            #and (technical_indicators.get_band_values(bands, '15m', 'ma') is not None and current_price < float(technical_indicators.get_band_values(bands, '15m', 'ma')))
            and (mid_15 is not None and current_price < mid_15)
        )
        cond_1h = (
            rsi_1h is not None and rsi_1h <= 70
            #and (band_values.get('1h') is not None and band_values.get('1h') == 'below_lower')
            and (mid_1h is not None and current_price < mid_1h)
        )
        cond_1d = (
            rsi_1d is not None and rsi_1d >= 30
            #and (band_values.get('1d') is not None and band_values.get('1d') != 'below_lower')
            and (mid_1d is not None and current_price < mid_1d)
        )

        logger.info(f"Long  conditions : "
            f"{(Colors.GREEN + str(cond_1m) + Colors.RESET) if cond_1m else cond_1m}, "
            f"{(Colors.GREEN + str(cond_5m) + Colors.RESET) if cond_5m else cond_5m}, "
            f"{(Colors.GREEN + str(cond_15m) + Colors.RESET) if cond_15m else cond_15m}, "
            f"{(Colors.GREEN + str(cond_1h) + Colors.RESET) if cond_1h else cond_1h}, "
            f"{(Colors.GREEN + str(cond_1d) + Colors.RESET) if cond_1d else cond_1d}")
        
        if cond_1m and cond_5m and cond_15m and cond_1h and cond_1d:
            v_action = 'long'
            logger.info('Long entry conditions met -> set v_action = long')
        else:
            v_action = None #logger.info('Long entry conditions NOT met')


        # 매도(short) 포지션 진입 조건 = 조건 충족 시에만 `v_action`을 'short'으로 설정)
        # - 1m: RSI >= 70 or 현재가가 볼린저 상단 위
        # - 5m: RSI >= 70 그리고 현재가가 볼린저 상단 위
        # - 15m: RSI >= 40 그리고 현재가 > 15m 볼린저 MA(중간) 그리고 현재가 > 15m (high+low)/2
        # - 1h: RSI >= 30 그리고 현재가가 1h 볼린저 상단 아래 그리고 현재가 > 1h (high+low)/2
        # - 1d: RSI <= 70 그리고 현재가가 1d 볼린저 상단 아래 그리고 현재가 > 1d (high+low)/2
        if v_action != 'long':
            scond_1m = (rsi_1m is not None and rsi_1m >= 70 or band_values['1m'] == 'above_upper')
            scond_5m = (rsi_5m is not None and rsi_5m >= 60 and band_values['5m'] == 'above_upper')
            scond_15m = (
                rsi_15m is not None and rsi_15m >= 40
                #and (technical_indicators.get_band_values(bands, '15m', 'ma') is not None and current_price > float(technical_indicators.get_band_values(bands, '15m', 'ma')))
                and (mid_15 is not None and current_price > mid_15)
            )
            scond_1h = (
                rsi_1h is not None and rsi_1h >= 30
                #and (band_values['1h'] is not None and band_values['1h'] != 'above_upper')
                and (mid_1h is not None and current_price > mid_1h)
            )
            scond_1d = (
                rsi_1d is not None and rsi_1d <= 70
                #and (band_values['1d'] is not None and band_values['1d'] != 'above_upper')
                and (mid_1d is not None and current_price > mid_1d)
            )

            logger.info(f"Short conditions : "
                f"{(Colors.RED + str(scond_1m) + Colors.RESET) if scond_1m else scond_1m}, "
                f"{(Colors.RED + str(scond_5m) + Colors.RESET) if scond_5m else scond_5m}, "
                f"{(Colors.RED + str(scond_15m) + Colors.RESET) if scond_15m else scond_15m}, "
                f"{(Colors.RED + str(scond_1h) + Colors.RESET) if scond_1h else scond_1h}, "
                f"{(Colors.RED + str(scond_1d) + Colors.RESET) if scond_1d else scond_1d}")           

            if scond_1m and scond_5m and scond_15m and scond_1h and scond_1d:
                v_action = 'short'
                logger.info('Short entry conditions met -> set v_action = short')
            else:
                v_action = None  #logger.info('Short entry conditions NOT met')
        else:
            logger.info('already set to long... skipping short check')


        # 강제진입 조건 : 
        if v_action == None:
            # 1.RSI 보조 조건 - 1분봉, 5분봉 RSI가 극단값(70 이상 또는 30 이하)일 때 우선 진입
            if scond_1m and scond_5m and (rsi_1m is not None and rsi_1m >= 70):
                v_action = 'short'
                logger.info(f'{Colors.RED}Short entry conditions enabled by low RSI -> short{Colors.RESET}')
            elif scond_1m and scond_5m and (rsi_1m is not None and rsi_1m <= 30):
                v_action = 'long'
                logger.info(f'{Colors.GREEN}Long entry conditions enabled by high RSI -> long{Colors.RESET}')
            else:
                v_action = None

        # 진입제외 조건
        high_1d = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1d', 'high')
        low_1d  = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1d', 'low')
        ratio_pos = ((current_price - low_1d) / (high_1d - low_1d)) * 100 if (high_1d is not None and low_1d is not None and high_1d != low_1d) else None   
        logger.info(f"Daily position : {low_1d:.2f}, {mid_1d:.2f}, {high_1d:.2f} {Colors.YELLOW}{ratio_pos:.2f}{Colors.RESET}%" if ratio_pos is not None else f"Daily position : passed ")

        if v_action != None:
            # 1.진입제외 조건 : 일간 포지션 비율에 따른 보조 조건(특정 일일구간에서는 진입하지 않음)          
            if v_action == 'short' and ratio_pos <= 30:
                v_action = None
                logger.info(f'{Colors.YELLOW}Short entry conditions rejected by daily position -> set v_action = None{Colors.RESET}')
            if v_action == 'long' and ratio_pos >= 70:
                v_action = None
                logger.info(f'{Colors.YELLOW}Long entry conditions rejected by daily position -> set v_action = None{Colors.RESET}')
            
            # 2.추세전환 시 변경
            if (rsi_1m is not None and rsi_15m >= rsi_1h and rsi_1h >= rsi_1d):
                v_action = 'long'
                logger.info(f'{Colors.RED}Short entry conditions enabled by trend reversal -> long{Colors.RESET}')
            elif (rsi_1m is not None and rsi_15m <= rsi_1h and rsi_1h <= rsi_1d):
                v_action = 'short'
                logger.info(f'{Colors.GREEN}Long entry conditions enabled by trend reversal -> short{Colors.RESET}')

            # 3.최근 거래 시간과 비교하여 과도한 진입 방지
            diff_time = datetime.now() - datetime.strptime(trades_time, '%Y-%m-%d %H:%M:%S')
            if abs(diff_time.total_seconds()) < 60: # 1분 이내
                v_action = None
                logger.info(f"최근 1분 이내에 거래가 발생. ('중복 진입 방지' 또는 '과도한 거래 방지')")


        #포지션 진입
        #1.포지션 존재여부 확인 => 포지션(long, shor) 없으면 진입, 포지션 있으면 패스
        #2.진입 오더 존재여부 확인 => 오더 있으면 삭제 후 진입
        if v_action != None:
            logger.info(f'{Colors.YELLOW}Start a trading action decided : {v_action}{Colors.RESET}')
            
            try:
                v_order_result = position_manager.execute_position_entry(
                    exchange = exchange,
                    symbol   = v_symbol,
                    action   = v_action,
                    order_amount = v_order_amount,
                    sl_ratio =   v_sl_ratio,
                    tp_ratio =  v_tp_ratio,
                    order_type = v_order_type,
                    min_order_usdt = 100.0
                )

                time.sleep(1) #포지션 반영 대기

                if v_order_result:
                    if v_action == 'long':
                        long_trades_count += 1
                    elif v_action == 'short':
                        short_trades_count += 1

                    trades_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    logger.info(f"포지션 진입 성공: {v_action}")
                else:
                    logger.info(f"포지션 진입 거부 또는 이미 포지션 존재")
                    error_count += 1

            except Exception as e:
                error_count += 1
                logger.info(f'포지션 진입 중 오류 발생: {type(e).__name__}, {str(e)}')

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        diff_time = datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S') - datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
        logger.info(f"Bot running time: {diff_time}")
        diff_time = datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S') - datetime.strptime(trades_time, '%Y-%m-%d %H:%M:%S')
        logger.info(f"Trade waiting time: {diff_time}")
        
        loop_count += 1
        logger.info(f"long trades = {long_trades_count}, short trades = {short_trades_count}, error count = {error_count}, total loop = {loop_count} end.\n")
        

    except Exception as e:
        logger.info(f'Error in main loop:', type(e).__name__, str(e))
    finally:
        time.sleep(15)  # delay seconds before next iteration


logger.info(v_order_result)


