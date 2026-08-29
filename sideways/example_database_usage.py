"""
거래 데이터베이스 사용 예시
SQLite와 MySQL에서 거래 데이터를 조회하고 분석하는 방법
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from sideways.config_loader import load_config
from sideways.trade_recorder import TradeRecorder


def example_1_basic_queries():
    """예시 1: 기본 조회"""
    print("\n" + "="*60)
    print("예시 1: 기본 조회")
    print("="*60)
    
    # 설정 로드
    config = load_config('config.json')
    
    # TradeRecorder 초기화
    recorder = TradeRecorder(config)
    
    # 최근 10개 거래 조회
    print("\n[최근 10개 거래]")
    trades = recorder.get_trades(limit=10)
    for i, trade in enumerate(trades, 1):
        print(f"\n{i}. {trade['symbol']} {trade['side'].upper()}")
        print(f"   진입: {trade['entry_price']} @ {trade['entry_time']}")
        print(f"   청산: {trade['exit_price']} @ {trade['exit_time']}")
        if trade['pnl']:
            print(f"   손익: ${trade['pnl']:.2f} ({trade['pnl_pct']:.2f}%)")
        print(f"   상태: {trade['status']}")
        print(f"   신호: {trade['signal_reason']}")
    
    recorder.close()


def example_2_symbol_specific():
    """예시 2: 심볼별 조회"""
    print("\n" + "="*60)
    print("예시 2: 심볼별 조회")
    print("="*60)
    
    config = load_config('config.json')
    recorder = TradeRecorder(config)
    
    # BTC 거래만 조회
    symbol = 'BTC/USDT:USDT'
    print(f"\n[{symbol} 거래 내역]")
    btc_trades = recorder.get_trades(symbol=symbol, limit=20)
    
    if btc_trades:
        print(f"총 {len(btc_trades)}개 거래")
        for trade in btc_trades:
            status = "손익" if trade['pnl'] else "진행중"
            print(f"  {trade['timestamp']}: {trade['side'].upper()} @ {trade['entry_price']} - {status}")
    else:
        print(f"{symbol}의 거래 기록이 없습니다.")
    
    recorder.close()


def example_3_statistics():
    """예시 3: 통계 분석"""
    print("\n" + "="*60)
    print("예시 3: 통계 분석")
    print("="*60)
    
    config = load_config('config.json')
    recorder = TradeRecorder(config)
    
    # 전체 통계
    print("\n[전체 거래 통계]")
    all_stats = recorder.get_statistics()
    
    if all_stats:
        print(f"총 거래: {all_stats.get('total_trades', 0)}건")
        print(f"승리: {all_stats.get('winning_trades', 0)}건")
        print(f"패배: {all_stats.get('losing_trades', 0)}건")
        print(f"승률: {all_stats.get('win_rate', 0):.2f}%")
        print(f"총 손익: ${all_stats.get('total_pnl', 0):.2f}")
        print(f"평균 손익률: {all_stats.get('avg_pnl_pct', 0):.2f}%")
        print(f"최대 수익: ${all_stats.get('max_profit', 0):.2f}")
        print(f"최대 손실: ${all_stats.get('max_loss', 0):.2f}")
    else:
        print("통계 데이터가 없습니다.")
    
    # 심볼별 통계
    print("\n[심볼별 통계]")
    all_trades = recorder.get_trades(limit=1000)
    
    symbol_stats = {}
    for trade in all_trades:
        symbol = trade['symbol']
        if symbol not in symbol_stats:
            symbol_stats[symbol] = {
                'total': 0,
                'wins': 0,
                'losses': 0,
                'total_pnl': 0,
                'total_pnl_pct': 0
            }
        
        symbol_stats[symbol]['total'] += 1
        if trade['pnl']:
            symbol_stats[symbol]['total_pnl'] += trade['pnl']
            symbol_stats[symbol]['total_pnl_pct'] += (trade['pnl_pct'] or 0)
            if trade['pnl'] > 0:
                symbol_stats[symbol]['wins'] += 1
            else:
                symbol_stats[symbol]['losses'] += 1
    
    for symbol, stats in sorted(symbol_stats.items()):
        win_rate = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
        avg_pnl_pct = stats['total_pnl_pct'] / stats['total'] if stats['total'] > 0 else 0
        print(f"\n{symbol}:")
        print(f"  총 거래: {stats['total']}건")
        print(f"  승률: {win_rate:.2f}%")
        print(f"  총 손익: ${stats['total_pnl']:.2f}")
        print(f"  평균 손익률: {avg_pnl_pct:.2f}%")
    
    recorder.close()


def example_4_daily_performance():
    """예시 4: 일일 성과"""
    print("\n" + "="*60)
    print("예시 4: 일일 성과 분석")
    print("="*60)
    
    config = load_config('config.json')
    recorder = TradeRecorder(config)
    
    print("\n[최근 7일 성과]")
    all_trades = recorder.get_trades(limit=10000)
    
    daily_stats = {}
    for trade in all_trades:
        # timestamp를 날짜로 변환
        if isinstance(trade['timestamp'], str):
            date = trade['timestamp'].split()[0]  # YYYY-MM-DD
        else:
            date = trade['timestamp'].date().isoformat()
        
        if date not in daily_stats:
            daily_stats[date] = {
                'trades': 0,
                'wins': 0,
                'total_pnl': 0,
                'trades_list': []
            }
        
        daily_stats[date]['trades'] += 1
        if trade['pnl']:
            daily_stats[date]['total_pnl'] += trade['pnl']
            daily_stats[date]['trades_list'].append(trade)
            if trade['pnl'] > 0:
                daily_stats[date]['wins'] += 1
    
    # 최근순으로 정렬
    for date in sorted(daily_stats.keys(), reverse=True)[:7]:
        stats = daily_stats[date]
        win_rate = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
        print(f"\n{date}:")
        print(f"  거래: {stats['trades']}건, 승률: {win_rate:.1f}%")
        print(f"  일일 손익: ${stats['total_pnl']:.2f}")
    
    recorder.close()


def example_5_signal_analysis():
    """예시 5: 신호별 분석"""
    print("\n" + "="*60)
    print("예시 5: 신호별 성과")
    print("="*60)
    
    config = load_config('config.json')
    recorder = TradeRecorder(config)
    
    print("\n[신호별 성과]")
    all_trades = recorder.get_trades(limit=5000)
    
    signal_stats = {}
    for trade in all_trades:
        signal = trade['signal_reason'][:20] if trade['signal_reason'] else 'Unknown'  # 처음 20글자만
        
        if signal not in signal_stats:
            signal_stats[signal] = {
                'total': 0,
                'wins': 0,
                'total_pnl': 0,
                'total_pnl_pct': 0
            }
        
        signal_stats[signal]['total'] += 1
        if trade['pnl']:
            signal_stats[signal]['total_pnl'] += trade['pnl']
            signal_stats[signal]['total_pnl_pct'] += (trade['pnl_pct'] or 0)
            if trade['pnl'] > 0:
                signal_stats[signal]['wins'] += 1
    
    # 총 거래수로 정렬
    for signal, stats in sorted(signal_stats.items(), key=lambda x: x[1]['total'], reverse=True):
        if stats['total'] >= 3:  # 최소 3건 이상만 표시
            win_rate = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
            avg_pnl_pct = stats['total_pnl_pct'] / stats['total'] if stats['total'] > 0 else 0
            print(f"\n{signal}:")
            print(f"  건수: {stats['total']}건, 승률: {win_rate:.1f}%")
            print(f"  총 손익: ${stats['total_pnl']:.2f}, 평균: {avg_pnl_pct:.2f}%")
    
    recorder.close()


def example_6_db_selection():
    """예시 6: SQLite vs MySQL 선택"""
    print("\n" + "="*60)
    print("예시 6: 데이터베이스 타입 선택")
    print("="*60)
    
    # SQLite 설정
    sqlite_config = {
        'database': {
            'type': 'sqlite',
            'path': 'sideways/trades.db',
            'save_trades': True
        }
    }
    
    # MySQL 설정
    mysql_config = {
        'database': {
            'type': 'mysql',
            'host': 'localhost',
            'port': 3306,
            'user': 'trading_bot',
            'password': 'your_password',
            'database': 'trading_bot',
            'save_trades': True
        }
    }
    
    print("\n[SQLite] - 로컬 단일 인스턴스용")
    print(f"  경로: {sqlite_config['database']['path']}")
    print("  장점:")
    print("    - 설정 간단")
    print("    - 별도 서버 불필요")
    print("    - 파일 기반 백업 용이")
    
    print("\n[MySQL] - 서버 기반 멀티 인스턴스용")
    print(f"  호스트: {mysql_config['database']['host']}")
    print(f"  데이터베이스: {mysql_config['database']['database']}")
    print("  장점:")
    print("    - 멀티 인스턴스 지원")
    print("    - 확장성 우수")
    print("    - 원격 접속 가능")
    print("    - 고급 쿼리 지원")
    
    print("\n사용 방법:")
    print("  1. config.json에서 type을 'sqlite' 또는 'mysql'로 설정")
    print("  2. 필요한 설정 값 입력")
    print("  3. main.py 실행 시 자동으로 데이터베이스 선택")


def main():
    """메인 함수"""
    print("\n" + "="*60)
    print("거래 데이터베이스 사용 예시")
    print("="*60)
    
    examples = [
        ("1", "기본 조회", example_1_basic_queries),
        ("2", "심볼별 조회", example_2_symbol_specific),
        ("3", "통계 분석", example_3_statistics),
        ("4", "일일 성과", example_4_daily_performance),
        ("5", "신호별 분석", example_5_signal_analysis),
        ("6", "DB 타입 선택", example_6_db_selection),
    ]
    
    print("\n실행할 예시를 선택하세요:")
    for code, name, _ in examples:
        print(f"  {code}. {name}")
    print("  0. 모두 실행")
    print("  q. 종료")
    
    choice = input("\n선택 (0-6, q): ").strip().lower()
    
    if choice == 'q':
        print("종료합니다.")
        return
    
    if choice == '0':
        for code, name, func in examples:
            try:
                func()
            except Exception as e:
                print(f"\n❌ {name} 실행 중 오류: {e}")
    else:
        for code, name, func in examples:
            if code == choice:
                try:
                    func()
                except Exception as e:
                    print(f"\n❌ {name} 실행 중 오류: {e}")
                return
        
        print("잘못된 선택입니다.")


if __name__ == '__main__':
    main()
