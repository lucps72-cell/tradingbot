"""
데이터베이스 테스트 스크립트
SQLite와 MySQL 모두 테스트
"""
import sys
import json
from datetime import datetime
from pathlib import Path

# 프로젝트 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from sideways.database import create_database, SQLiteDatabase, MySQLDatabase
from sideways.trade_recorder import TradeRecorder

def test_sqlite():
    """SQLite 테스트"""
    print("\n" + "="*60)
    print("SQLite 테스트 시작")
    print("="*60)
    
    config = {
        'database': {
            'type': 'sqlite',
            'path': 'test_trades.db',
            'save_trades': True
        }
    }
    
    try:
        # 1. 데이터베이스 생성
        db = create_database(config)
        assert db is not None, "데이터베이스 생성 실패"
        print("✅ SQLite 데이터베이스 생성 완료")
        
        # 2. 거래 기록 저장
        trade_data = {
            'symbol': 'BTC/USDT:USDT',
            'side': 'long',
            'entry_price': 45000.5,
            'quantity': 0.01,
            'entry_usdt': 450.0,
            'tp_price': 46000.0,
            'sl_price': 44000.0,
            'status': 'open',
            'signal_reason': 'Test Entry - EMA Crossover',
            'order_type': 'market',
            'leverage': 50,
            'entry_split_count': 1,
        }
        
        result = db.save_trade(trade_data)
        assert result, "거래 기록 저장 실패"
        print("✅ 거래 기록 저장 완료")
        
        # 3. 거래 기록 조회
        trades = db.get_trades()
        assert len(trades) > 0, "거래 기록 조회 실패"
        print(f"✅ 거래 기록 조회 완료 ({len(trades)}개)")
        print(f"   첫 번째 거래: {trades[0]}")
        
        # 4. 통계 조회
        stats = db.get_trade_statistics()
        assert stats, "통계 조회 실패"
        print(f"✅ 통계 조회 완료")
        print(f"   총 거래: {stats.get('total_trades')}")
        print(f"   총 손익: ${stats.get('total_pnl', 'N/A')}")
        
        # 5. 연결 종료
        db.close()
        print("✅ SQLite 연결 종료 완료")
        
        print("\n✅ SQLite 테스트 통과")
        return True
        
    except Exception as e:
        print(f"\n❌ SQLite 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_trade_recorder():
    """TradeRecorder 테스트"""
    print("\n" + "="*60)
    print("TradeRecorder 테스트 시작")
    print("="*60)
    
    config = {
        'database': {
            'type': 'sqlite',
            'path': 'test_recorder.db',
            'save_trades': True
        }
    }
    
    try:
        # 1. TradeRecorder 초기화
        recorder = TradeRecorder(config)
        print("✅ TradeRecorder 초기화 완료")
        
        # 2. 거래 진입 기록
        entry_result = recorder.record_entry(
            symbol='ETH/USDT:USDT',
            side='long',
            entry_price=3000.0,
            quantity=0.1,
            entry_usdt=300.0,
            tp_price=3100.0,
            sl_price=2900.0,
            signal_reason='Test Entry Signal',
            leverage=10,
            entry_split_count=1
        )
        assert entry_result, "거래 진입 기록 실패"
        print("✅ 거래 진입 기록 완료")
        
        # 3. 거래 청산 기록
        exit_result = recorder.record_exit(
            symbol='ETH/USDT:USDT',
            side='long',
            exit_price=3050.0,
            quantity=0.1,
            entry_price=3000.0,
            entry_usdt=300.0,
            pnl=5.0,
            pnl_pct=1.67,
            exit_reason='Test Exit - Take Profit'
        )
        assert exit_result, "거래 청산 기록 실패"
        print("✅ 거래 청산 기록 완료")
        
        # 4. 거래 조회
        trades = recorder.get_trades()
        assert len(trades) > 0, "거래 조회 실패"
        print(f"✅ 거래 조회 완료 ({len(trades)}개)")
        
        # 5. 통계 조회
        stats = recorder.get_statistics()
        print(f"✅ 통계 조회 완료")
        if stats:
            print(f"   총 거래: {stats.get('total_trades')}")
            print(f"   승리: {stats.get('winning_trades')}")
            print(f"   총 손익: ${stats.get('total_pnl', 'N/A')}")
        
        # 6. 연결 종료
        recorder.close()
        print("✅ TradeRecorder 연결 종료 완료")
        
        print("\n✅ TradeRecorder 테스트 통과")
        return True
        
    except Exception as e:
        print(f"\n❌ TradeRecorder 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mysql_connection():
    """MySQL 연결 테스트 (선택)"""
    print("\n" + "="*60)
    print("MySQL 연결 테스트 시작 (선택)")
    print("="*60)
    
    try:
        import mysql.connector
    except ImportError:
        print("⚠️  mysql-connector-python이 설치되지 않았습니다.")
        print("   MySQL을 사용하려면: pip install mysql-connector-python")
        return True
    
    # 환경 변수나 설정에서 MySQL 정보 읽기
    config = {
        'database': {
            'type': 'mysql',
            'host': 'localhost',
            'port': 3306,
            'user': 'root',
            'password': '',
            'database': 'trading_bot_test'
        }
    }
    
    try:
        # MySQL 연결 테스트
        db = MySQLDatabase(
            host=config['database']['host'],
            user=config['database']['user'],
            password=config['database']['password'],
            database=config['database']['database'],
            port=config['database']['port']
        )
        print("✅ MySQL 데이터베이스 연결 완료")
        
        # 거래 기록 저장
        trade_data = {
            'symbol': 'XRP/USDT:USDT',
            'side': 'short',
            'entry_price': 2.5,
            'quantity': 100,
            'entry_usdt': 250.0,
            'tp_price': 2.3,
            'sl_price': 2.7,
            'status': 'open',
            'signal_reason': 'Test MySQL Entry',
            'order_type': 'market',
            'leverage': 20,
            'entry_split_count': 1,
        }
        
        result = db.save_trade(trade_data)
        if result:
            print("✅ MySQL 거래 기록 저장 완료")
        else:
            print("⚠️  MySQL 거래 기록 저장 건너뜀")
        
        db.close()
        print("✅ MySQL 연결 종료 완료")
        print("\n✅ MySQL 테스트 완료")
        return True
        
    except Exception as e:
        print(f"⚠️  MySQL 연결 실패 (선택사항): {e}")
        print("   MySQL 서버가 실행 중인지 확인하세요.")
        return True  # 선택사항이므로 실패해도 무방


def main():
    """메인 테스트 함수"""
    print("\n" + "="*60)
    print("거래 데이터베이스 테스트 시작")
    print("="*60)
    
    results = []
    
    # 1. SQLite 테스트
    results.append(("SQLite", test_sqlite()))
    
    # 2. TradeRecorder 테스트
    results.append(("TradeRecorder", test_trade_recorder()))
    
    # 3. MySQL 테스트 (선택)
    results.append(("MySQL Connection", test_mysql_connection()))
    
    # 결과 요약
    print("\n" + "="*60)
    print("테스트 결과 요약")
    print("="*60)
    for name, passed in results:
        status = "✅ 통과" if passed else "❌ 실패"
        print(f"{name:30} {status}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("\n✅ 모든 필수 테스트 통과!")
        return 0
    else:
        print("\n❌ 일부 테스트 실패")
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
