import json
import subprocess

lookback_list = [4, 5, 6]
results = []

for lookback in lookback_list:
    # config.json 로드 및 파라미터 수정
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    config['strategy']['rsi']['divergence_lookback'] = lookback
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    # 백테스트 실행
    print(f"[divergence_lookback={lookback}] 백테스트 실행...")
    result = subprocess.run(['python', 'backtest/backtester.py'], capture_output=True, text=True)
    output = result.stdout
    profit = None
    for line in output.splitlines():
        if '총 수익' in line or 'Total Profit' in line:
            profit = line.strip()
            break
    results.append({'lookback': lookback, 'profit': profit, 'raw': output})

with open('lookback_test_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print("테스트 완료! 결과는 lookback_test_results.json에서 확인하세요.")
