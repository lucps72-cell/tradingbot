import itertools
import json
import os
from backtester import run_backtest
from log_config import setup_logging

# EMA 파라미터 후보
ema_short_list = [5, 9, 12, 15]
ema_long_list = [20, 26, 30, 50]

symbol = 'XRPUSDT'
days = 30
config_path = 'config.json'

best_result = None
best_params = None
results = []

for short, long in itertools.product(ema_short_list, ema_long_list):
    if short >= long:
        continue
    # config 불러오기 및 EMA 파라미터 수정
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    # EMA 파라미터 위치에 맞게 수정 (예시)
    config['strategy']['ema_short'] = short
    config['strategy']['ema_long'] = long

    # 로거 (info만 출력)
    logger = setup_logging(log_dir='logs', log_level='INFO')

    # 백테스트 실행
    result = run_backtest(config, symbol=symbol, days=days, logger=logger)
    print(f"EMA({short},{long}) -> 수익률: {result['total_return_pct']:.2f}%, 승률: {result['win_rate']*100:.2f}%")
    results.append({'ema_short': short, 'ema_long': long, 'total_return_pct': result['total_return_pct'], 'win_rate': result['win_rate']})

    # 최고 성능 갱신
    if (best_result is None) or (result['total_return_pct'] > best_result['total_return_pct']):
        best_result = result
        best_params = (short, long)

print(f"\n최적 EMA: {best_params}, 최고 수익률: {best_result['total_return_pct']:.2f}%")

# 결과를 CSV로 저장
import pandas as pd
df = pd.DataFrame(results)
df.to_csv('ema_optimization_results.csv', index=False, encoding='utf-8-sig')
print("[CSV 저장 완료] ema_optimization_results.csv")
