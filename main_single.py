import math, time
import os
import ccxt
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime
import technical_indicators
import position_manager
from color_utils import *

load_dotenv()

# BYBIT선물 거래소 초기화
api_key    = os.getenv("BYBIT_API_KEY")
api_secret = os.getenv("BYBIT_API_SECRET")

exchange = ccxt.bybit({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
        'adjustForTimeDifference': True
    }
})


v_symbol       = "ETHUSDT" #"BTC/USDT:USDT"동일 ("BTC/USDT" 안됨)
v_leverage     = -1        #레버리지 50배 (변경안함:-1)
v_order_amount = 500       #주문하려는 최대 매수/매도 금액 USDT
v_sl_ratio     = 0.2
v_tp_ratio     = 0.4 


print("\n==== Bybit Trading Bot Started ====")
print(f"Time    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("Trading  : ", v_symbol)
print("Leverage : x ", v_leverage if v_leverage > -1 else "No Change")
print(f"SL/TP    : {Colors.GREEN}-{v_sl_ratio} % +{v_tp_ratio} %{Colors.RESET}")
print("===================================\n")

# 레버리지 변경 실행
if v_leverage > -1:
    try:
        exchange.market(v_symbol)
        exchange.set_leverage(v_leverage, v_symbol)
        print("changed leverage = ", v_leverage)
    except Exception as e:
        #print(f"set_leverage Exception: {type(e).__name__}: {str(e)}")
        print("equal to the present leverage = ", v_leverage)
        pass

count = 0

while True:
    try:                    
        # 기본값 설정
        v_action       = None    # long / short
        v_order_type   = "limit" # market / limit
        v_order_result = None    # 주문 결과 여부


        # Bollinger Bands Start
        print('Start fetching Bollinger Bands...')
        try:
            symbol_for_boll = v_symbol if '/' in v_symbol else (v_symbol[:-4] + '/USDT')
            bands = technical_indicators.get_bollinger_for_timeframes(symbol_for_boll, timeframes=['1m', '5m', '15m', '1h', '1d'], exchange=exchange)
            technical_indicators.print_bollinger_results(bands, decimals=6) # 결과출력
        except Exception as e:
            print('Failed to fetch Bollinger bands:', type(e).__name__, str(e))

        # 현재가와 볼린저 밴드 위치 비교
        current_price = exchange.fetch_ticker(v_symbol)['last']

        band_values = {}

        for tf, v in bands.items():
            if current_price > v['upper']:
                pos = 'above_upper'  
                print('Bands values :', tf, 'current above upper')
            elif current_price < v['lower']:
                pos = 'below_lower'  
                print('Bands values :', tf, 'current below lower')
            else:
                pos = 'inside_bands' #print(tf, 'inside bands')

            band_values[tf] = pos


        # RSI start
        print('Start fetching RSI...')
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
            print(f"RSI values : {rsi_1m:.0f}, {rsi_5m:.0f}, {rsi_15m:.0f}, {rsi_1h:.0f}, {rsi_1d:.0f}")

        except Exception as e:
            print('Failed to fetch RSI:', type(e).__name__, str(e))
            rsi_results = {}
            rsi_values = {}
            rsi_1m = rsi_5m = rsi_15m = rsi_1h = rsi_1d = None


        # 매수(long) 포지션 진입 조건 (조건 충족 시에만 `v_action`을 'long'으로 설정)
        # 1분봉  기준  RSI가 30 이하이고 현재가가 볼린저 밴드 하단 아래에 위치할 때
        # 5분봉  기준  RSI가 30 이하이고 현재가가 볼린저 밴드 하단 아래에 위치할 때 
        # 15분봉 기준  RSI가 70 이하이고 현재가가 볼린저 밴드 중간 아래에 위치하고 현재가가 15분봉의 저점과 고점 사이 중간값 아래에 있을때 
        # 1시간봉 기준 RSI가 70 이하이고 현재가가 볼린저 밴드 하단 위에 위치하고 현재가가 1시간봉의 저점과 고점 사이 중간값 아래에 있을때
        # 1일봉  기준  RSI가 30 이상이고 현재가가 볼린저 밴드 하단 위에 위치하고 현재가가 일봉의 저점과 고점 사이 중간값 아래에 있을때
        # 조건 요약:
        # - 1m:  RSI <= 30 그리고 현재가가 볼린저 하단 아래
        # - 5m:  RSI <= 30 그리고 현재가가 볼린저 하단 아래
        # - 15m: RSI <= 70 그리고 현재가 < 15m 볼린저 MA(중간) 그리고 현재가 < 15m (high+low)/2
        # - 1h:  RSI <= 70 그리고 현재가가 1h 볼린저 하단 위(=below_lower 아님) 그리고 현재가 < 1h (high+low)/2
        # - 1d:  RSI >= 30 그리고 현재가가 1d 볼린저 하단 위 그리고 현재가 < 1d (high+low)/2

        # collect midpoints using technical_indicators (live fetch returns last candle)
        mid_15 = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '15m', 'mid')
        mid_1h = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1h', 'mid')
        mid_1d = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1d', 'mid')

        # evaluate each condition safely (None이 있을 경우 False로 처리)
        cond_1m = (rsi_1m is not None and rsi_1m <= 30 and band_values['1m'] == 'below_lower')
        cond_5m = (rsi_5m is not None and rsi_5m <= 40 and band_values['5m'] == 'below_lower')
        cond_15m = (
            rsi_15m is not None and rsi_15m <= 70
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

        print('Long entry conditions : ', cond_1m, cond_5m, cond_15m, cond_1h, cond_1d)
        if cond_1m and cond_5m and cond_15m and cond_1h and cond_1d:
            v_action = 'long'
            print_green('Long entry conditions met -> set v_action = long')
        else:
            v_action = None
            #print('Long entry conditions NOT met')


        #매도(short) 포지션 진입 조건 (조건 충족 시에만 `v_action`을 'short'으로 설정)
        #1. 1분봉  기준  RSI가 70 이상이고 현재가가 볼린저 밴드 하단 아래에 위치할 때
        #2. 5분봉  기준  RSI가 70 이상이고 현재가가 볼린저 밴드 하단 아래에 위치할 때 
        #3. 15분봉 기준  RSI가 30 이상이고 현재가가 볼린저 밴드 중간 아래에 위치하고 현재가가 15분봉의 저점과 고점 사이 중간값 아래에 있을때 
        #4. 1시간봉 기준 RSI가 30 이상이고 현재가가 볼린저 밴드 하단 위에 위치하고 현재가가 1시간봉의 저점과 고점 사이 중간값 아래에 있을때
        #5. 1일봉  기준  RSI가 70 이하이고 현재가가 볼린저 밴드 하단 위에 위치하고 현재가가 일봉의 저점과 고점 사이 중간값 위에 있을때
        # 조건 요약:
        # - 1m: RSI >= 70 그리고 현재가가 볼린저 상단 위
        # - 5m: RSI >= 70 그리고 현재가가 볼린저 상단 위
        # - 15m: RSI >= 30 그리고 현재가 > 15m 볼린저 MA(중간) 그리고 현재가 > 15m (high+low)/2
        # - 1h: RSI >= 30 그리고 현재가가 1h 볼린저 상단 아래 그리고 현재가 > 1h (high+low)/2
        # - 1d: RSI <= 70 그리고 현재가가 1d 볼린저 상단 아래 그리고 현재가 > 1d (high+low)/2

        if v_action != 'long':
            # collect midpoints using technical_indicators.fetch_ohlcv_field (live only)
            mid_15 = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '15m', 'mid')
            mid_1h = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1h', 'mid')
            mid_1d = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1d', 'mid')

            # short-entry conditions (요약 기준에 따름)
            scond_1m = (rsi_1m is not None and rsi_1m >= 70 and band_values['1m'] == 'above_upper')
            scond_5m = (rsi_5m is not None and rsi_5m >= 60 and band_values['5m'] == 'above_upper')
            scond_15m = (
                rsi_15m is not None and rsi_15m >= 30
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

            print('Short entry conditions : ', cond_1m, cond_5m, cond_15m, cond_1h, cond_1d)
            if scond_1m and scond_5m and scond_15m and scond_1h and scond_1d:
                v_action = 'short'
                print_red('Short entry conditions met -> set v_action = short')
            else:
                v_action = None
                #print('Short entry conditions NOT met')
        else:
            print('already set to long; skipping short-entry evaluation')


        # 강제진입 조건 : 
        # 1.RSI 보조 조건 - 1분봉, 5분봉 RSI가 극단값(60 이상 또는 40 이하)일 때 우선 진입
        # 2.추세전환 신호로 간주하여 진입을 허용(추후 추가)
        if v_action == None:
            if scond_1m and scond_5m and scond_15m and (rsi_1m is not None and rsi_1m >= 60):
                v_action = 'short'
                print('Short entry conditions by low rsi -> set v_action = short')
            elif scond_1m and scond_5m and scond_15m and (rsi_1m is not None and rsi_1m <= 40):
                v_action = 'long'
                print('Long entry conditions by high rsi -> set v_action = long')
            else:
                v_action = None


        # 진입제외 조건 : 일간 포지션 비율에 따른 보조 조건(40%~60% 구간에서는 진입하지 않음)
        high_1d = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1d', 'high')
        low_1d = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1d', 'low')
        ratio_pos = ((current_price - low_1d) / (high_1d - low_1d)) * 100 if (high_1d is not None and low_1d is not None and high_1d != low_1d) else None   
        print(f"Current price : {current_price}, Today middle price : {mid_1d:.2f}, Position in daily range : {ratio_pos:.2f}%" if ratio_pos is not None else f"Current price : {current_price}, Today middle price : {mid_1d}, Position in daily range : N/A")
        
        if v_action != None:
            if ratio_pos >= 40 and ratio_pos <= 60:
                v_action = None
                print('Short/long entry conditions by daily position -> set v_action = None')
  

        #포지션 진입 조건 : v_action값이 long, short일때
        #1.포지션 존재여부 확인 => 포지션 없으면 진입, 포지션 있으면 패스
        #2.진입 오더 존재여부 확인 => 오더 있으면 삭제 후 진입

        if v_action != None:
            print(f'Final trading action decided: {v_action}')
            
            # position_manager 모듈을 사용하여 포지션 진입 실행
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

                if v_order_result:
                    print(f"포지션 진입 성공: {v_action}")
                else:
                    print(f"포지션 진입 거부 또는 이미 포지션 존재")
            except Exception as e:
                print(f'포지션 진입 중 오류 발생: {type(e).__name__}, {str(e)}')
                v_order_result = None

        count += 1

        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} : {count} loop end.\n")

    except Exception as e:
        print('Error in main loop:', type(e).__name__, str(e))
    finally:
        #time.sleep(15)  # 150 seconds delay before next iteration
        exit

print(v_order_result)


