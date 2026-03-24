# 실시간 현재가 조회
from sideways import position_manager
from sideways.main import initialize_exchange, load_config_direct

config = load_config_direct()
#symbol = config.get('trading', {}).get('symbol', 'BTCUSDT')
symbol = 'XRP/USDT:USDT'
# # 거래소 연결
exchange = initialize_exchange(config)
position_manager = position_manager.PositionManager(exchange, symbol)

# print(f"실제 사용 심볼: {symbol}")
current_price = position_manager.get_current_price(exchange, symbol)
print(f"[감지시작] ⚪️ 현재가: {current_price} ⚪️")




