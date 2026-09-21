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
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("comtypes").setLevel(logging.WARNING)

# Third-party imports
import ccxt
import pandas as pd
from dotenv import load_dotenv

# Local imports
from sideways.log_config import setup_logging
from sideways.common import is_time_between
from sideways.common import play_voice_alert, play_voice_alert_signal, send_telegram
from sideways.color_utils import Colors
from sideways.config_loader import load_config
from sideways.simple_strategy import SidewaysStrategy
from sideways.trade_recorder import TradeRecorder


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
                'recvWindow': 20000,
                'adjustForTimeDifference': True
            }
        })

        if config['exchange'].get('testnet', False):
            ex.set_sandbox_mode(True)

        # Bybit private requests require the local clock to stay close to server time.
        ex.load_time_difference()

        logger.info(f"거래소 연결: {config['exchange']['name']} ({'테스트넷' if config['exchange'].get('testnet') else '실거래'})")
        return ex
    except Exception as e:
        logger.error(f"거래소 연결 실패: {str(e)}")
        logger.error(f"Exchange initialization failed: {str(e)}")
        sys.exit(1)

# (정리 2026-09-20) check_exclusion_filters()를 여기서 제거했다. 코드 전체에서 단 한 번도
# 호출되지 않는 죽은 함수였고, 참조하던 config['trading']['entry_cooldown_sec']도 이 함수
# 말고는 아무도 안 읽는 죽은 설정이었다 — 실제 재진입 방지는 아래 메인 루프에 하드코딩된
# 180초/60초 창(반대/동일 포지션)이 담당하고 있었다. 이번에 그 하드코딩을 config의
# `trading.reentry_guard`로 빼서(§ 사용자 지시 3번) 이 죽은 함수·설정은 대체하고 제거한다.


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
    trade_recorder = None
    
    def sigint_handler(sig, frame):
        logger.info("SIGINT(Ctrl+C) 신호 수신. 안전하게 종료합니다.")
        if trade_recorder:
            trade_recorder.close()
        sys.exit(0)
    signal.signal(signal.SIGINT, sigint_handler)

    # 로그 설정 (sideways/logs/tradingbot.log에 기록)
    config = load_config_direct()
    symbol = config.get('trading', {}).get('symbol', 'BTCUSDT')
    limit = config.get('limit', 180)
    check_interval = config.get('loop', {}).get('check_interval', 15)

    timeframe_higher = config['strategy']['timeframes']['higher_trend'][0] if isinstance(config['strategy']['timeframes']['higher_trend'], list) else config['strategy']['timeframes']['higher_trend']
    timeframe_lower = config['strategy']['timeframes']['lower_signal'][0] if isinstance(config['strategy']['timeframes']['lower_signal'], list) else config['strategy']['timeframes']['lower_signal']
    logger.info(f"[실시간 거래] 심볼: {symbol} 타임프레임: {timeframe_higher}/{timeframe_lower}")

    # 거래소 연결
    exchange = initialize_exchange(config)

    # TradeRecorder 초기화
    try:
        trade_recorder = TradeRecorder(config)
        logger.info("[성공] TradeRecorder 초기화 완료")
    except Exception as e:
        import traceback
        logger.error(f"[TradeRecorder 초기화 실패] {e}")
        logger.error(f"[스택 트레이스] {traceback.format_exc()}")
        sys.exit(1)
    
    # 거래소와 심볼을 넘겨서 PositionManager가 포지션을 동기화하도록 생성
    try:
        strategy = SidewaysStrategy(exchange, symbol, config, trade_recorder=trade_recorder)
        logger.info("[성공] SidewaysStrategy 초기화 완료")
    except Exception as e:
        import traceback
        logger.error(f"[SidewaysStrategy 초기화 실패] {e}")
        logger.error(f"[스택 트레이스] {traceback.format_exc()}")
        if trade_recorder:
            trade_recorder.close()
        sys.exit(1)

    current_trend = None
    success_count = 0
    skipped_count = 0
    loop_count = 0
    rate_limit_backoff_sec = config.get('api', {}).get('rate_limit_backoff_sec', 60)
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

                # (2026-09-20 수정, 사용자 지시 3번) 이전엔 180/60초와 0.1% 가격밴드가
                # main.py에 하드코딩돼 있었다 — config['trading']['reentry_guard']로 빼서
                # 조정 가능하게 만들었다(기본값은 기존 하드코딩값과 동일해서 동작 변화 없음).
                reentry_cfg = config['trading'].get('reentry_guard', {})
                opposite_cooldown_sec = reentry_cfg.get('opposite_position_cooldown_sec', 180)
                same_cooldown_sec = reentry_cfg.get('same_position_cooldown_sec', 60)
                band = reentry_cfg.get('price_band_pct', 0.001)

                # 직전 거래의 포지션, 가격, 시간 대비 waiting 처리 (반대포지션이 일정가격 이내이거나, 동일포지션이 일정가격 이상이면 거래 방지)
                if (
                    entry_position != last_trade_position
                    and last_trade_price is not None
                    and current_price <= last_trade_price * (1 + band)
                    and current_price >= last_trade_price * (1 - band)
                    and abs(diff_trades_time.total_seconds()) <= opposite_cooldown_sec
                ):
                    logger.info(f"최근 거래와 반대 포지션 감지. (현재가: {current_price}, 마지막 거래가: {last_trade_price}, 시간 차이: {diff_trades_time})")
                    skipped_count += 1
                elif (
                    # 수정: 이전 조건은 "101%↑ AND 99.9%↓"라는 동시에 참일 수 없는 조건이라
                    # 이 분기가 항상 거짓이었다. 주석(동일포지션이 일정가격 "이상"이면 거래 방지)의
                    # 의도대로 "밴드 밖(위 또는 아래)으로 벗어났으면"이 되도록 OR로 정정.
                    entry_position == last_trade_position
                    and last_trade_price is not None
                    and (current_price >= last_trade_price * (1 + band) or current_price <= last_trade_price * (1 - band))
                    and abs(diff_trades_time.total_seconds()) <= same_cooldown_sec
                ):
                    logger.info(f"최근 거래와 동일 포지션 감지. (현재가: {current_price}, 마지막 거래가: {last_trade_price}, 시간 차이: {diff_trades_time})")
                    skipped_count += 1
                else:
                    if entry_position != last_trade_position:
                        requested_symbol = symbol.replace('/', '').split(':')[0]
                        send_telegram(f"{requested_symbol} {entry_position} 신호: {current_price} ")

                    # (2026-09-17 정리, Finding G) 이전엔 여기가 "if True: #read_only_mode...
                    # is False:"라는 죽은 분기였다 — 조건이 상수라 read_only_mode와 무관하게
                    # 항상 execute_transaction()이 호출됐지만, 실제 주문 실행 여부는
                    # execute_transaction() 내부(execute_trade 호출 직전)에서 이미
                    # read_only_mode를 정확히 재검사하고 있어서 위험하지는 않았다.
                    # 바깥 조건을 실제 read_only_mode 체크로 "풀되", execute_transaction()
                    # 자체는 모드와 무관하게 항상 호출해야 한다 — 그 안에서
                    # record_entry()(거래 기록 DB 저장)와 update_simulated_position()
                    # (2026-09-17 신규 페이퍼 트레이딩 가상 포지션 추적)가 실행되기 때문에,
                    # 여기서 호출을 건너뛰면 시뮬레이션 모드의 진입 기록·가상 포지션 추적이
                    # 전부 멈춰버린다(실제 발견한 회귀 위험 — 반영 전 확인함).
                    # (2026-09-21 추가 수정, 사용자 리포트 — "매도 진입이 안 된다") 이전엔 여기서
                    # main.py 자체 repeat_entry_count(같은 방향 신호가 쿨다운을 통과한 "시도"
                    # 횟수)가 entry_split_count에 도달하면 execute_transaction() 호출 자체를
                    # 조용히 건너뛰었다. 이 카운터는 "실제 성공한 진입 수"가 아니라 "시도 횟수"라,
                    # execute_transaction() 내부에서 총액초과 등으로 거절된 시도도 그대로
                    # 카운트에 들어가서 — 실제로는 분할이 2회만 성공했는데 카운터가 먼저 3에
                    # 도달해 그 이후 같은 방향 신호는 로그 한 줄 없이 반대 방향 신호가 뜨기
                    # 전까지 영원히 막혔다(실거래 로그로 재현 확인). execute_transaction() 안에
                    # 이미 DB/포지션 상태 기반의 정확한 entry_count/split_count 체크가 있고
                    # 거절 시 이유도 로그로 남긴다(R에서 단위불일치 버그 수정 완료) — 그 안쪽
                    # 체크 하나로 충분하므로 바깥의 부정확하고 조용한 이 게이트를 제거한다.
                    rtn_success_count, rtn_skipped_count = strategy.execute_transaction(entry_position, close_position)
                    success_count += rtn_success_count
                    skipped_count += rtn_skipped_count
                    if rtn_success_count > 0:
                        last_trade_position = entry_position
                        last_trade_price = current_price
                        last_trades_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    elif config['trading'].get('read_only_mode', False):
                        # 시뮬레이션 모드에서는 rtn_success_count가 항상 0이다(성공 카운트는
                        # execute_transaction() 내부의 "read_only_mode is False" 블록에서만
                        # 증가함). 그래도 반복 진입 방지 로직(위쪽 entry_position ==
                        # last_trade_position 비교)이 동작하도록 여기서 직접 갱신해 준다.
                        last_trade_position = entry_position
                        last_trade_price = current_price
                        last_trades_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if config['trading'].get('read_only_mode', False) is False:
                # 트레일링 스탑 모니터링 및 조정
                strategy.position_manager.trailing_stop_monitor(exchange, symbol, config)
            else:
                # (2026-09-17 신규) read_only_mode=True(시뮬레이션): 실제 주문 없이 가상 포지션의
                # SL/TP/트레일링을 평가해서 조건 충족 시 DB에 가상 청산 기록을 남긴다(페이퍼 트레이딩).
                strategy.position_manager.simulate_position_monitor(exchange, symbol, config)

            # 포지션 상태 상세 로그 함수 호출
            strategy.position_manager.log_position_status(exchange, symbol, logger)

            # 24시간 거래금액 및 손익금액 로그
            strategy.position_manager.log_24h_performance(exchange, symbol, logger)

        except ccxt.RateLimitExceeded as e:
            logger.warning(
                "[Bybit 레이트 리밋] API 호출 제한에 도달했습니다. "
                f"{rate_limit_backoff_sec}초 후 재시도합니다: {e}"
            )
            time.sleep(rate_limit_backoff_sec)
            continue
        except Exception as e:
            logger.error(f"[에러] {e}")
            import traceback
            logger.error(f"[스택 트레이스] {traceback.format_exc()}")

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

