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
import time
import signal
import logging
from datetime import datetime
from typing import Dict, Optional

# UTF-8 인코딩 설정 (Windows 한글 깨짐 방지)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Third-party imports
import ccxt
import pandas as pd
from dotenv import load_dotenv

# Local imports
from aibot_v2.config_loader import load_config, merge_configs
from aibot_v2.log_config import setup_logging
from aibot_v2.color_utils import Colors, print_error, print_success, print_warning, print_info, print_colored
from aibot_v2 import validation
from aibot_v2 import position_manager
from aibot_v2 import risk_manager
from aibot_v2 import technical_indicators
from aibot_v2.trend_strategy import TrendFollowingStrategy
from aibot_v2.trend_strategy import determine_trend, check_trend_reversal


# 간단한 캐시 구현
class SimpleCache:
    def __init__(self, ttl=60):
        self.cache = {}
        self.ttl = ttl
        self.timestamps = {}
    
    def get(self, key):
        if key in self.cache:
            import time
            if time.time() - self.timestamps[key] < self.ttl:
                return self.cache[key]
            else:
                del self.cache[key]
                del self.timestamps[key]
        return None
    
    def set(self, key, value):
        import time
        self.cache[key] = value
        self.timestamps[key] = time.time()


# Global variables
logger = None
exchange = None
should_exit = False
cache = SimpleCache(ttl=60)


def signal_handler(sig, frame):
    """신호 처리 (Ctrl+C)"""
    global should_exit
    print("\n")
    print_warning("=" * 50)
    print_warning("종료 신호 수신. 봇을 안전하게 종료합니다...")
    print_warning("=" * 50)
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
    # aibot_v2 폴더의 .env 파일을 직접 로드
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(env_path)
    
    api_key = os.getenv('BYBIT_API_KEY', '')
    api_secret = os.getenv('BYBIT_API_SECRET', '')
    
    if not api_key or not api_secret:
        print_error("API 키가 환경 변수에 설정되지 않았습니다.")
        print_error("BYBIT_API_KEY와 BYBIT_API_SECRET을 설정해주세요.")
        sys.exit(1)
    
    try:
        ex = ccxt.bybit({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': config['trading']['trade_type'],
                'defaultMarginType': 'isolated',
                'brokerId': 'NRZST'
            }
        })
        
        if config['exchange'].get('testnet', False):
            ex.set_sandbox_mode(True)
        
        # logger가 아직 준비되지 않았을 수도 있으므로 안전하게 처리
        active_logger = logger or logging.getLogger(__name__)
        active_logger.info(f"거래소 연결: {config['exchange']['name']} ({'테스트넷' if config['exchange'].get('testnet') else '실거래'})")
        return ex
    
    except Exception as e:
        print_error(f"거래소 연결 실패: {str(e)}")
        active_logger = logger or logging.getLogger(__name__)
        active_logger.error(f"Exchange initialization failed: {str(e)}")
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
        import logging
        active_logger = logger or logging.getLogger(__name__)
        active_logger.info(f"Trade occurred within last {MIN_TRADE_INTERVAL}s. (preventing duplicate entry or excessive trading)\n")
        return True
    
    return False

def setup_and_load():
    """
    신호 핸들러 등록, 설정 로드, 로깅 설정, 기본 정보 출력까지 한 번에 처리
    Returns: (config, logger)
    """
    signal.signal(signal.SIGINT, signal_handler)

    parser = argparse.ArgumentParser(description='Bybit Trading Bot v2')
    parser.add_argument('--config', type=str, default='config.json',
                        help='설정 파일 경로 (기본값: config.json)')
    parser.add_argument('--symbol', type=str, default=None,
                        help='거래 심볼 (기본값: config.json의 심볼)')
    parser.add_argument('--amount', type=float, default=None,
                        help='주문 금액 (미지정 시 config.json 사용)')
    args = parser.parse_args()

    try:
        config_path = args.config if args.config and args.config != 'config.json' else os.path.join(os.path.dirname(__file__), 'config.json')
        if not os.path.exists(config_path):
            config_path = os.path.join(os.path.dirname(__file__), 'config.json')
            if not os.path.exists(config_path):
                config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
            if not os.path.exists(config_path):
                config_path = os.path.join(os.getcwd(), 'aibot_v2', 'config.json')
        config = load_config(config_path)
        config = merge_configs(config, args)
        if args.symbol:
            config['trading']['symbol'] = args.symbol
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print_error(f"설정 로드 실패: {str(e)}")
        sys.exit(1)

    logger = setup_logging(
        log_dir='logs',
        log_level=logging.INFO
    )

    print_success("\n" + "=" * 60)
    print_success("[BYBIT TRADING BOT V2 - TREND FOLLOWING]")
    print_success("=" * 60)

    amount_mode = config['trading'].get('amount_mode', 'notional')
    leverage = config['trading'].get('leverage', 1)
    base_amount = config['trading']['order_amount_usdt']
    effective_notional = base_amount if amount_mode == 'notional' else base_amount * leverage

    print_info(f"심볼    : {config['trading']['symbol']}")
    print_info(f"레버리지 : {leverage}x")
    print_info(f"주문 금액: {base_amount} USDT ({amount_mode}, 유효노출 {effective_notional} USDT)")
    print_info(f"체크 간격: {config['loop']['check_interval']}초")

    return config, logger

def main():
    #global logger, ok_call_count, skipped_count  # ensure we update the module-level logger for other functions
    loop_count = 0
    ok_call_count = 0
    skipped_count = 0
    current_trend = None  # 현재 추세 상태: 'uptrend', 'downtrend', None

    # 신호 핸들러 등록 및 설정 로드, 로깅, 기본 정보 출력 분리
    config, logger = setup_and_load()

    # 메인 루프
    try:
        loop_count = 0
        start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        trades_time = '1970-01-01 00:00:00'  # 마지막 거래 시간 초기화 오래전으로
        v_action    = None  # 마지막 액션 상태
        current_trend = None  # 현재 추세 상태: 'uptrend', 'downtrend', None
        entry_split_count = config['trading'].get('entry_split_count', 3)

        # 거래소 연결
        exchange = initialize_exchange(config)

        while not should_exit:
            try:
                # Step 1: Apply exclusion filters
                if check_exclusion_filters(config, v_action, trades_time) :
                    time.sleep(config['trading']['entry_cooldown_sec'])
                    continue

                # Step 2. 현재 추세 체크 (매번 확인) ===
                new_trend, entry_key, close_key = determine_trend(
                    exchange, 
                    config['trading']['symbol'], 
                    config, 
                    cache,
                    current_trend=current_trend
                )

                # === 2. 추세 변동 시 업데이트 ===
                if new_trend is not None:
                    if current_trend is None:
                        current_trend = new_trend
                        logger.info(f"{Colors.BOLD}🔵 추세 확정: {new_trend}{Colors.END}")
                    elif new_trend != current_trend:
                        current_trend = new_trend
                        logger.info(f"{Colors.BOLD}🔄 추세 변경: {current_trend} → {new_trend}{Colors.END}")
                    else:
                        logger.info(f"⚪ 추세 유지: {current_trend}")   
                else:   
                    logger.info(f"⚪ 추세 유지: {current_trend if current_trend is not None else '미결정'}")

                # === 3. 포지션 상태 확인 ===
                has_long, has_short, long_amount, short_amount = position_manager.check_position_status(
                    exchange, 
                    config['trading']['symbol'], 
                    config, 
                    cache
                )

                # === 4. 청산신호 확인 및 실행 ===
                if current_trend is not None and new_trend is not None and close_key is not None and close_key:
                    logger.info(f"✅ 청산 신호 확인: {close_key}")

                    # 청산 시도 
                    if close_key == 'uptrend' and has_long:
                        success = position_manager.close_position(exchange, config['trading']['symbol'], 'long', long_amount)
                        if success:
                            ok_call_count += 1
                            print_success(f"{Colors.BLUE}✓ 'long' 포지션 청산 완료!{Colors.END}")
                            trades_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            v_action = 'long'

                    elif close_key == 'downtrend' and has_short:
                        success = position_manager.close_position(exchange, config['trading']['symbol'], 'short', short_amount)
                        if success:
                            ok_call_count += 1
                            print_success(f"{Colors.BLUE}✓ 'short' 포지션 청산 완료!{Colors.END}")
                            trades_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            v_action = 'short'

                    # 추세 변경 시 신규 진입 시도 (분할 진입 로직 개선)
                    if current_trend is not None and new_trend is not None and entry_key is not None:
                        analysis = position_manager.get_entry_signal(exchange, config, cache, entry_key)
                        if analysis and analysis.get('has_signal'):
                            action = 'long' if analysis['type'].upper() == 'LONG' else 'short'
                            split_amount = config['trading']['order_amount_usdt'] / entry_split_count

                            # 현재 포지션 수량 기반 진입회수/진입금액 계산
                            if action == 'long':
                                entry_count = int(long_amount * analysis['entry_price'] // split_amount) if has_long else 0
                                total_amount = long_amount * analysis['entry_price'] if has_long else 0.0
                            else:
                                entry_count = int(short_amount * analysis['entry_price'] // split_amount) if has_short else 0
                                total_amount = short_amount * analysis['entry_price'] if has_short else 0.0
                            # 진입 제한 체크
                            entry_limit_flag = False
                            if entry_count >= entry_split_count:
                                logger.info(f"{Colors.YELLOW}⚠️ 분할 진입 최대 횟수({entry_split_count}) 초과 → 진입 거절{Colors.END}")
                                entry_limit_flag = True
                            if total_amount + split_amount > config['trading']['order_amount_usdt']:
                                logger.info(f"{Colors.YELLOW}⚠️ 분할 진입 총액 초과: {total_amount + split_amount:.2f} > {config['trading']['order_amount_usdt']:.2f} USDT → 진입 거절{Colors.END}")
                                entry_limit_flag = True

                            if entry_limit_flag is False:
                                # 진입 실행
                                success = position_manager.execute_trade(
                                    exchange,
                                    config['trading']['symbol'],
                                    action,
                                    split_amount,
                                    analysis['entry_price'],
                                    analysis['sl_price'],
                                    analysis['tp_price'],
                                    amount_mode=config['trading'].get('amount_mode', 'notional'),
                                    leverage=config['trading'].get('leverage', 1)
                                )
                                if success:
                                    ok_call_count += 1
                                    print_success(f"{Colors.BLUE}✓ {action.upper()} 분할 진입 {entry_count+1}/{entry_split_count}회 완료! (총액: {total_amount+split_amount:.2f} USDT){Colors.END}")
                                    trades_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                    v_action = action
                                else:
                                    print_error(f"{Colors.RED}✗ {action.upper()} 분할 진입 실패!{Colors.END}")
                                    skipped_count += 1
                        else:
                            print_error(f"{Colors.RED}⚪ 진입가, 익절가, 손절가 생성 실패 ){Colors.END}")

            except Exception as e:
                import traceback
                logger.error(traceback.format_exc())
                print_error(f"{Colors.RED}메인 루프 오류: {str(e)}{Colors.END}")
            
            loop_count += 1            
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            diff_time = datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S') - datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
            logger.info(f"Started at {start_time} | waiting: {diff_time} | Loop: {loop_count} | Success: {ok_call_count} | Skipps: {skipped_count}\n")
            
            time.sleep(config['loop']['check_interval'])
    
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Goodbye!")



if __name__ == "__main__":
    main()
