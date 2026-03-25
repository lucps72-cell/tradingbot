"""
Bybit Trading Bot v2 - Multi-Timeframe Trend Following Strategy

Usage:
    # Run live trading
    python main.py
    
    # For backtest, use: python backtester.py --symbol XRPUSDT --days 30
"""
import argparse
import json
import os
import sys
import time  # time 모듈은 sleep 용도로만 사용
import signal
import datetime  # datetime 모듈 전체 import
from typing import Dict, Optional
import logging
from logging import config
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("comtypes").setLevel(logging.WARNING)

# Third-party imports
import ccxt
import pandas as pd
from dotenv import load_dotenv

# Local imports
from sideways.log_config import setup_logging
from sideways.common import is_time_between
from sideways.color_utils import Colors
from sideways.config_loader import load_config
from sideways.simple_strategy import SidewaysStrategy


# UTF-8 인코딩 설정 (Windows 한글 깨짐 방지)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')
os.environ['PYTHONIOENCODING'] = 'utf-8'

if os.name == 'nt': # Windows 환경일 경우 터미널에서 한글나오도록
    import ctypes
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)

# 간단한 캐시 구현
class SimpleCache:
    def __init__(self, ttl=60):
        self.cache = {}
        self.ttl = ttl
        self.timestamps = {}
    
    def get(self, key):
        if key in self.cache:
            if time.time() - self.timestamps[key] < self.ttl:
                return self.cache[key]
            else:
                del self.cache[key]
                del self.timestamps[key]
        return None
    
    def set(self, key, value):
        self.cache[key] = value
        self.timestamps[key] = time.time()


# 로그 설정을 프로그램 시작 직후 한 번만 적용
from sideways.log_config import setup_logging
setup_logging(default_path="sideways/log_config.json")
# Global variables
logger = logging.getLogger('sideways')
exchange = None
should_exit = False
cache = SimpleCache(ttl=60)
trade_logger = logging.getLogger("trade")

def signal_handler(sig, frame):
    """신호 처리 (Ctrl+C)"""
    global should_exit
    logger.info("\n" + "=" * 50)
    logger.info("종료 신호 수신. 봇을 안전하게 종료합니다...")
    logger.info("=" * 50)
    should_exit = True

def initialize_exchange(config: Dict) -> ccxt.bybit:
    """
    거래소 연결 초기화
    Args:
        config: 설정 딕셔너리
    Returns:
        CCXT Bybit 인스턴스
    """
    global logger  # use shared logger instance set in main
    # sideways 폴더의 .env 파일을 직접 로드
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(env_path)

    # testnet 여부에 따라 API 키/시크릿 분기
    if config['exchange'].get('testnet', False):
        api_key = os.getenv('TST_BYBIT_API_KEY', '')
        api_secret = os.getenv('TST_BYBIT_API_SECRET', '')
    else:
        api_key = os.getenv('BYBIT_API_KEY', '')
        api_secret = os.getenv('BYBIT_API_SECRET', '')

    if not api_key or not api_secret:
        logger.error("API 키가 환경 변수에 설정되지 않았습니다.")
        if config['exchange'].get('testnet', False):
            logger.error("TST_BYBIT_API_KEY와 TST_BYBIT_API_SECRET을 설정해주세요.")
        else:
            logger.error("BYBIT_API_KEY와 BYBIT_API_SECRET을 설정해주세요.")
        sys.exit(1)

    try:
        ex = ccxt.bybit({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': config['trading']['trade_type'],
                'defaultMarginType': 'isolated',
                'brokerId': 'NRZST',
                'recvWindow': 10000
            }
        })

        if config['exchange'].get('testnet', False):
            ex.set_sandbox_mode(True)

        logger.info(f"거래소 연결: {config['exchange']['name']} ({'테스트넷' if config['exchange'].get('testnet') else '실거래'})")
        return ex
    except Exception as e:
        logger.error(f"거래소 연결 실패: {str(e)}")
        logger.error(f"Exchange initialization failed: {str(e)}")
        sys.exit(1)

# 진입 제외 필터: 일봉 위치, 변동폭 과도, 중복 거래 방지 등 체크
def check_exclusion_filters(config, v_action, trades_time):
    """Apply exclusion filters to prevent unwanted entries.
    
    Returns: (True or False)
    """
    if v_action is None:
        return False
    
    # Check daily position ratio
    # 변동폭 과도
        
    # Prevent excessive trading
    # 동일 포지션 내에서 너무 잦은 거래 방지
    MIN_TRADE_INTERVAL = config['trading'].get('entry_cooldown_sec', 60)  # seconds
    diff_time = datetime.now() - datetime.strptime(trades_time, '%Y-%m-%d %H:%M:%S')
    if abs(diff_time.total_seconds()) < MIN_TRADE_INTERVAL:
        logger.info(f"Trade occurred within last {MIN_TRADE_INTERVAL}s. (preventing duplicate entry or excessive trading)\n")
        return True
    
    return False


# config.json 직접 로드 (v2 소스 미참조)
def load_config_direct():
    parser = argparse.ArgumentParser(description='Bybit Trading Bot v2')
    parser.add_argument('--config', type=str, default='config.json', help='설정 파일 경로 (기본값: config.json)')
    parser.add_argument('--symbol', type=str, default=None, help='거래 심볼 (기본값: config.json의 심볼)')
    parser.add_argument('--amount', type=float, default=None, help='주문 금액 (미지정 시 config.json 사용)')
    args = parser.parse_args()

    config_path = args.config if args.config and args.config != 'config.json' else os.path.join(os.path.dirname(__file__), 'config.json')
    if not os.path.exists(config_path):
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        if not os.path.exists(config_path):
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        if not os.path.exists(config_path):
            config_path = os.path.join(os.getcwd(), 'sideways', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"설정 로드 실패: {str(e)}")
        sys.exit(1)
    if args.symbol:
        config['trading']['symbol'] = args.symbol
    return config

def main():
    def sigint_handler(sig, frame):
        logger.info("SIGINT(Ctrl+C) 신호 수신. 안전하게 종료합니다.")
        sys.exit(0)
    signal.signal(signal.SIGINT, sigint_handler)

    # 로그 설정 (sideways/logs/tradingbot.log에 기록)
    global config
    config = load_config_direct()
    symbol = config.get('trading', {}).get('symbol', 'BTCUSDT')
    limit = config.get('limit', 180)
    check_interval = config.get('loop', {}).get('check_interval', 15)

    timeframe_higher = config['strategy']['timeframes']['higher_trend'][0] if isinstance(config['strategy']['timeframes']['higher_trend'], list) else config['strategy']['timeframes']['higher_trend']
    timeframe_lower = config['strategy']['timeframes']['lower_signal'][0] if isinstance(config['strategy']['timeframes']['lower_signal'], list) else config['strategy']['timeframes']['lower_signal']
    logger.info(f"[실시간 거래] 심볼: {symbol} 타임프레임: {timeframe_higher}/{timeframe_lower}")

    # 거래소 연결
    exchange = initialize_exchange(config)

    # 거래소와 심볼을 넘겨서 PositionManager가 포지션을 동기화하도록 생성
    strategy = SidewaysStrategy(exchange, symbol, config)

    current_trend = None
    success_count = 0
    skipped_count = 0
    repeat_entry_count = 0  # 동일 포지션 반복 진입 카운트
    loop_count = 0
    start_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    last_trades_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') #'1970-01-01 00:00:00'  # 마지막 거래 시간 초기화 오래전으로
    last_trade_position = None
    last_trade_price = None

    while True:
        rtn_success_count = 0
        rtn_skipped_count = 0
        entry_position = None
        close_position = None

        # if is_time_between(datetime.time(23, 0), datetime.time(1, 30)):
        #     logger.info("23:00~01:30 피크타임 구간입니다.")

        try:
            # 거래조건 체크함수 호출 (진입 및 청산 조건 판단)
            current_trend, entry_position, close_position, current_price = strategy.execute_trading(current_trend, verbose=True)
            #logger.info(f"현재가: {current_price}, 마지막 거래가: {last_trade_price}, 가격 차이: {last_trade_price * 1.001}, {last_trade_price * 0.999}")

            if entry_position or close_position:
                current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                diff_trades_time = datetime.datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S') - datetime.datetime.strptime(last_trades_time, '%Y-%m-%d %H:%M:%S')

                # 직전 거래의 포지션, 가격, 시간 대비 waiting 처리 (반대포지션이 일정가격 이내이거나, 동일포지션이 일정가격 이상이면 거래 방지)
                if (
                    entry_position != last_trade_position
                    and last_trade_price is not None
                    and current_price <= last_trade_price * 1.001
                    and current_price >= last_trade_price * 0.999
                    and abs(diff_trades_time.total_seconds()) <= 180
                ):
                    logger.info(f"최근 거래와 반대 포지션 감지. (현재가: {current_price}, 마지막 거래가: {last_trade_price}, 시간 차이: {diff_trades_time})")
                    skipped_count += 1
                elif (
                    entry_position == last_trade_position
                    and last_trade_price is not None
                    and current_price >= last_trade_price * 1.001
                    and current_price <= last_trade_price * 0.999
                    and abs(diff_trades_time.total_seconds()) <= 60
                ):
                    logger.info(f"최근 거래와 동일 포지션 감지. (현재가: {current_price}, 마지막 거래가: {last_trade_price}, 시간 차이: {diff_trades_time})")
                    skipped_count += 1
                else:
                    if entry_position != last_trade_position:
                        repeat_entry_count = 0  # 포지션 변경 시 카운트 초기화
                    else:
                        repeat_entry_count += 1  # 동일 포지션 반복 시 카운트 증가
                    entry_split_count = config['trading'].get('entry_split_count', 1)
                    
                    if repeat_entry_count < entry_split_count:
                        if config['trading'].get('read_only_mode', False) is False: 
                            # 거래실행 함수 호출 (양방향 포지션 구조 대응)
                            rtn_success_count, rtn_skipped_count = strategy.execute_transaction(entry_position, close_position)
                            success_count += rtn_success_count
                            skipped_count += rtn_skipped_count
                            if rtn_success_count > 0:
                                last_trade_position = entry_position
                                last_trade_price = current_price
                                last_trades_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            # true인 경우 진입/청산 시뮬레이션 모드로 실행 (실제 주문은 실행하지 않음)
                            last_trade_position = entry_position
                            last_trade_price = current_price
                            last_trades_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if config['trading'].get('read_only_mode', False) is False: 
                # 트레일링 스탑 모니터링 및 조정
                strategy.position_manager.trailing_stop_monitor(exchange, symbol, config)

            # 포지션 상태 상세 로그 함수 호출
            strategy.position_manager.log_position_status(exchange, symbol, logger)

            # 24시간 거래금액 및 손익금액 로그
            strategy.position_manager.log_24h_performance(exchange, symbol, logger)

        except Exception as e:
            logger.error(f"[에러] {e}")

        loop_count += 1
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        diff_time = datetime.datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S') - datetime.datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
        diff_trades_time = datetime.datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S') - datetime.datetime.strptime(last_trades_time, '%Y-%m-%d %H:%M:%S')
        logger.info(f"Started at {start_time} | waiting: {diff_time}, last trade: {diff_trades_time} | Loop: {loop_count} | Success: {success_count} | Skipps: {skipped_count}\n")

        if rtn_success_count > 0:
            time.sleep(config['loop']['indicator_cache_ttl'])
        else:
            time.sleep(config['loop']['check_interval'])

if __name__ == "__main__":
    logger.info("[INFO] sideways.main.py 프로그램 시작")
    main()

