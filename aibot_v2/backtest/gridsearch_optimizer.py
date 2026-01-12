import json
import itertools
import subprocess
import os

# 최적화 대상 파라미터 값 리스트
divergence_lookback_list = [3, 4, 5, 6, 7]
ema_fast_list = [2, 3, 5]
ema_medium_list = [6, 9, 12]
ema_slow_list = [9, 12, 20]
rsi_period_list = [10, 14, 20]
rsi_overbought_list = [60, 65, 70, 75]
rsi_oversold_list = [20, 25, 30, 35]

# 결과 저장
results = []

# 모든 파라미터 조합 생성
param_grid = list(itertools.product(
    divergence_lookback_list,
    ema_fast_list,
    ema_medium_list,
    ema_slow_list,
    rsi_period_list,
    rsi_overbought_list,
    rsi_oversold_list
))

total = len(param_grid)
print(f"총 조합 수: {total}")

for idx, (lookback, fast, medium, slow, rsi_period, overbought, oversold) in enumerate(param_grid, 1):
    # config.json 로드 및 파라미터 수정
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    config['strategy']['rsi']['divergence_lookback'] = lookback
    config['strategy']['signal_ema']['fast'] = fast
    config['strategy']['signal_ema']['medium'] = medium
    config['strategy']['signal_ema']['slow'] = slow
    config['strategy']['rsi']['period'] = rsi_period
    config['strategy']['rsi']['overbought'] = overbought
    config['strategy']['rsi']['oversold'] = oversold
    # config 저장
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    # 백테스트 실행
    print(f"[{idx}/{total}] 테스트: lookback={lookback}, ema=({fast},{medium},{slow}), rsi=({rsi_period},{overbought},{oversold})")
    result = subprocess.run(['python', 'backtester.py'], capture_output=True, text=True)
    # 결과 파싱(예: stdout에서 '총 수익' 등 추출)
    output = result.stdout
    profit = None
    for line in output.splitlines():
        if '총 수익' in line or 'Total Profit' in line:
            profit = line.strip()
            break
    results.append({
        'lookback': lookback,
        'ema_fast': fast,
        'ema_medium': medium,
        'ema_slow': slow,
        'rsi_period': rsi_period,
        'rsi_overbought': overbought,
        'rsi_oversold': oversold,
        'profit': profit,
        'raw': output
    })
    # 중간 저장
    with open('gridsearch_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

print("최적화 완료! 결과는 gridsearch_results.json에서 확인하세요.")
