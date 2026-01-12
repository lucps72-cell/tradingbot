"""
손절 비율(sl_ratio) 비교 백테스트
0.5%, 1.0%, 1.5% 손절 비율에 따른 결과 비교
"""

import subprocess
import json
import sys
import os
from datetime import datetime

# UTF-8 인코딩 설정
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')
os.environ['PYTHONIOENCODING'] = 'utf-8'


def run_backtest_with_sl(sl_ratio: float, days: int = 30, symbol: str = 'XRPUSDT'):
    """
    특정 sl_ratio로 백테스트 실행
    
    Args:
        sl_ratio: 손절 비율 (0.005 = 0.5%, 0.01 = 1.0%, 0.015 = 1.5%)
        days: 백테스트 기간 (일)
        symbol: 거래 심볼
    """
    print("\n" + "=" * 80)
    print(f"손절 비율: {sl_ratio*100:.1f}% 백테스트 실행 중...")
    print("=" * 80)
    
    # config.json 로드 및 수정
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # sl_ratio 변경
    original_sl = config['risk_management']['sl_ratio']
    config['risk_management']['sl_ratio'] = sl_ratio
    
    # 임시 config 파일 생성
    temp_config = f'config_sl_{sl_ratio*100:.1f}.json'
    with open(temp_config, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    # 백테스트 실행
    cmd = [
        'python', 'backtester.py',
        '--config', temp_config,
        '--symbol', symbol,
        '--days', str(days),
        '--tp-mode', 'hybrid'
    ]
    
    try:
        # capture_output=False로 설정하여 결과를 직접 콘솔에 출력
        result = subprocess.run(cmd, encoding='utf-8')
        return result.returncode == 0
    except Exception as e:
        print(f"백테스트 실행 오류: {str(e)}")
        return False
    finally:
        # 임시 config 파일 삭제
        if os.path.exists(temp_config):
            os.remove(temp_config)
        
        # 원래 config 복원
        config['risk_management']['sl_ratio'] = original_sl
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)


def main():
    """메인 함수"""
    print("\n" + "=" * 80)
    print("손절 비율 비교 백테스트")
    print("=" * 80)
    
    # 설정
    symbol = 'XRPUSDT'
    days = 30
    sl_ratios = [0.001, 0.015, 0.02]  # 0.1%, 1.5%, 2.0%
    
    print(f"\n심볼: {symbol}")
    print(f"기간: {days}일")
    print(f"TP 모드: hybrid (2% 고정 + 추세 반전)")
    print(f"테스트할 SL 비율: {', '.join([f'{r*100:.1f}%' for r in sl_ratios])}")
    
    # 각 sl_ratio로 백테스트 실행
    results = {}
    for sl_ratio in sl_ratios:
        success = run_backtest_with_sl(sl_ratio, days, symbol)
        if success:
            results[f'{sl_ratio*100:.1f}%'] = '✓ 완료'
        else:
            results[f'{sl_ratio*100:.1f}%'] = '✗ 실패'
        
        # 다음 백테스트 전 구분선
        print("\n" + "=" * 80)
        input("다음 백테스트를 실행하려면 Enter를 누르세요...")
    
    print("\n" + "=" * 80)
    print("모든 백테스트 완료!")
    print("=" * 80)
    print("\n위 결과를 비교하여 최적의 손절 비율을 선택하세요.")
    print("\n주요 비교 지표:")
    print("  - 승률 (Win Rate)")
    print("  - 수익률 (Total Return %)")
    print("  - Profit Factor")
    print("  - 최대 드로우다운 (Max Drawdown)")
    print("  - 평균 거래 손익 (Average Trade)")


if __name__ == '__main__':
    main()
