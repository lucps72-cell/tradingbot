"""
Bybit Trading Bot - Automated Cryptocurrency Trading

Usage:
    # Run with default settings (SL: 0.20%, TP: 0.40%, Symbol: ETHUSDT, Amount: 5000 USDT)
    python main.py
    
    # Customize stop loss and take profit ratios
    python main.py --sl 0.5 --tp 1.0
    
    # Trade different symbol with custom amount
    python main.py --symbol BTCUSDT --amount 10000
    
    # Set leverage and all parameters
    python main.py --sl 1.0 --tp 2.0 --symbol BTCUSDT --amount 10000 --leverage 20
    
    # Run backtest (30 days)
    python main.py --backtest --days 30
    
    # Run backtest with custom parameters
    python main.py --backtest --days 60 --sl 0.5 --tp 1.0
    
    # Show help
    python main.py --help

Arguments:
    --sl, --stop-loss    Stop loss ratio in percentage (default: 0.20)
    --tp, --take-profit  Take profit ratio in percentage (default: 0.40)
    --symbol             Trading symbol (default: ETHUSDT)
    --amount             Order amount in USDT (default: 5000)
    --leverage           Leverage multiplier, -1 for no change (default: -1)
    --backtest           Enable backtest mode (no live trading)
    --days               Number of days to backtest (default: 30)
"""

import argparse
import json
import math
import os
import signal
import sys
import time
from datetime import datetime

from color_utils import *
import log_config
import config_loader
import validation
import indicator_cache

import ccxt
import pandas as pd
from dotenv import load_dotenv
import technical_indicators
import position_manager
import risk_manager
import backtester


# Parse command line arguments
parser = argparse.ArgumentParser(description='Bybit Trading Bot')
parser.add_argument('--config', type=str, default='config.json',
                    help='Path to config.json file (default: config.json)')
parser.add_argument('--sl', '--stop-loss', type=float, default=0.20, 
                    help='Stop loss ratio in percentage (default: 0.20)')
parser.add_argument('--tp', '--take-profit', type=float, default=0.40,
                    help='Take profit ratio in percentage (default: 0.40)')
parser.add_argument('--symbol', type=str, default='ETHUSDT',
                    help='Trading symbol (default: ETHUSDT)')
parser.add_argument('--amount', type=float, default=5000,
                    help='Order amount in USDT (default: 5000)')
parser.add_argument('--leverage', type=int, default=-1,
                    help='Leverage multiplier, -1 for no change (default: -1)')
parser.add_argument('--backtest', action='store_true',
                    help='Enable backtest mode')
parser.add_argument('--days', type=int, default=30,
                    help='Number of days to backtest (default: 30)')
args = parser.parse_args()

# Load configuration from file and merge with command-line arguments
try:
    config = config_loader.load_config(args.config)
    config = config_loader.merge_configs(config, args)
    logger_info = f"Loaded configuration from {args.config}"
except FileNotFoundError as e:
    print(f"ERROR: {e}")
    print("Please ensure config.json exists in the current directory")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"ERROR: Invalid JSON in config file: {e}")
    sys.exit(1)

# Logging setup (daily log file auto-generation)
import logging
logger = log_config.setup_logging(
    log_dir=config['logging']['log_dir'],
    log_level=getattr(logging, config['logging']['log_level'], logging.INFO)
)

logger.info(logger_info)

load_dotenv()

# Initialize Bybit futures exchange
exchange = ccxt.bybit({
    'apiKey': os.getenv("BYBIT_API_KEY"),
    'secret': os.getenv("BYBIT_API_SECRET"),
    'enableRateLimit': config['exchange']['enable_rate_limit'],
    'options': {
        'defaultType': config['exchange']['default_type'],
        'adjustForTimeDifference': True
    }
})

# Load exchange markets for symbol validation
try:
    logger.info("Loading exchange markets...")
    exchange.load_markets()
    logger.info(f"Markets loaded successfully: {len(exchange.markets)} markets available")
except Exception as e:
    print(f"ERROR: Failed to load exchange markets: {e}")
    sys.exit(1)

# Trading variables configuration (from config file + command-line overrides)
v_symbol       = config['trading']['symbol']           # Trading symbol
v_leverage     = config['trading']['leverage']         # Leverage (e.g., 50x, -1 = no change)
v_order_amount = config['trading']['order_amount']     # Maximum order amount in USDT
v_sl_ratio     = config['trading']['sl_ratio']         # Stop loss ratio %
v_tp_ratio     = config['trading']['tp_ratio']         # Take profit ratio %
v_order_type   = config['trading']['order_type']       # Order type (market/limit)
min_order_usdt = config['trading']['min_order_usdt']   # Minimum order USDT

# RSI thresholds loaded from config file
RSI_OVERSOLD_1M = config['rsi_thresholds']['long']['1m']
RSI_OVERSOLD_5M = config['rsi_thresholds']['long']['5m']
RSI_OVERSOLD_15M = config['rsi_thresholds']['long']['15m']

RSI_OVERBOUGHT_1M = config['rsi_thresholds']['short']['1m']
RSI_OVERBOUGHT_5M = config['rsi_thresholds']['short']['5m']
RSI_OVERBOUGHT_15M = config['rsi_thresholds']['short']['15m']
RSI_OVERBOUGHT_1H = config['rsi_thresholds']['short']['1h']
RSI_OVERBOUGHT_1D = config['rsi_thresholds']['short']['1d']

RSI_NEUTRAL_1H = config['rsi_thresholds']['long']['1h']
RSI_NEUTRAL_1D = config['rsi_thresholds']['long']['1d']

# Price filters loaded from config file
DAILY_POSITION_LOW = config['price_filters']['daily_position_low_percent']
DAILY_POSITION_HIGH = config['price_filters']['daily_position_high_percent']
MIN_TRADE_INTERVAL = config['price_filters']['min_trade_interval_seconds']

# Print current configuration
config_loader.print_config(config)

# ============================================================
# STARTUP VALIDATION
# ============================================================
all_valid, validation_results = validation.run_all_validations(
    exchange,
    symbol=v_symbol,
    leverage=v_leverage
)

if not all_valid:
    logger.critical("⚠️  STARTUP VALIDATION FAILED - Please fix the issues above")
    validation.print_validation_results(validation_results, logger)
    sys.exit(1)

logger.info("✓ All validations passed. Starting trading bot...\n")

# ============================================================
# BACKTEST MODE HANDLING
# ============================================================
if args.backtest:
    logger.info("="*60)
    logger.info("BACKTEST MODE ACTIVATED")
    logger.info("="*60)
    
    # Create backtester
    bt = backtester.Backtester(config, exchange)
    
    # Fetch historical data
    historical_data = bt.fetch_historical_data(days=args.days)
    
    if historical_data.empty:
        logger.error("Failed to fetch historical data. Exiting.")
        sys.exit(1)
    
    # Run backtest
    success = bt.run_backtest(historical_data)
    
    if success:
        # Print report
        bt.print_report()
        
        # Export trades
        bt.export_trades_to_csv("backtest_trades.csv")
        
        logger.info("✓ Backtest completed successfully")
    else:
        logger.error("✗ Backtest failed")
    
    sys.exit(0)

logger.info("")

# ============================================================
# CHECK FOR EXISTING POSITIONS (Orphaned Position Cleanup)
# ============================================================
logger.info("Checking for existing open positions...")
try:
    existing_positions = exchange.fetch_positions(symbols=[v_symbol])
    
    if existing_positions:
        open_positions = [p for p in existing_positions if p['contracts'] != 0 or (p.get('percentage') and p['percentage'] != 0)]
        
        if open_positions:
            logger.warning(f"{Colors.YELLOW}Found {len(open_positions)} existing open position(s):{Colors.RESET}")
            
            for pos in open_positions:
                side = "LONG" if pos['side'] == 'long' else "SHORT" if pos['side'] == 'short' else "UNKNOWN"
                contracts = pos.get('contracts', 0)
                entry_price = pos.get('average', 0)
                current_price = pos.get('markPrice', 0)
                unrealized_pnl = pos.get('unrealizedPnl', 0) if pos.get('unrealizedPnl') else 0
                
                logger.warning(f"  - {side} position: {contracts} contracts @ {entry_price:.2f} | "
                             f"Current: {current_price:.2f} | Unrealized PnL: {unrealized_pnl:+.2f} USDT")
            
            logger.info(f"{Colors.YELLOW}Management options:"
                       f"{Colors.RESET}\n"
                       f"  1. Monitor existing position (continue bot)\n"
                       f"  2. Close existing position (manual action required)\n"
                       f"  3. Restart bot after manual position closure")
            logger.warning(f"{Colors.YELLOW}Bot will continue and monitor existing position...{Colors.RESET}")
        else:
            logger.info("✓ No existing open positions found")
    else:
        logger.info("✓ No existing open positions found")
        
except Exception as e:
    logger.warning(f"Could not fetch existing positions (may not be critical): {type(e).__name__}: {str(e)}")

logger.info("")

# Bot settings from config
LOOP_INTERVAL = config['bot_settings']['loop_interval_seconds']
CACHE_TTL = config['bot_settings']['cache_ttl_seconds']
STATS_DISPLAY_INTERVAL = config['bot_settings']['stats_display_interval']
AUTO_CLOSE_ORPHANED = config['bot_settings'].get('auto_close_orphaned_positions', False)

# Initialize Risk Manager
risk_mgr = risk_manager.RiskManager(config.get('risk_management', {}))

# Initialize cache for indicator results (TTL from config to reduce API calls)
cache = indicator_cache.IndicatorCache(ttl_seconds=CACHE_TTL)
api_counter = indicator_cache.APICallCounter()

loop_count = 0
long_trades_count = 0
short_trades_count = 0
error_count = 0
start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
trades_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# 포지션 모니터링 및 수익/손실 추적
active_position = None  # Current open position {'side': 'long'/'short', 'entry_price': X, 'entry_time': datetime, 'pnl': 0}
tracked_orphaned_sides = set()  # Track which orphaned positions (LONG/SHORT) have been logged to avoid repetition
total_pnl = 0.0  # Cumulative PnL
total_winning_trades = 0  # Count of profitable trades
total_losing_trades = 0  # Count of losing trades
max_win = 0.0  # Largest winning trade
max_loss = 0.0  # Largest losing trade

# Startup log output
logger.info(f"\n\n==== Bybit Trading Bot Started ====\n"
            f"Time     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Trading  : {v_symbol}\n"
            f"Leverage : {v_leverage if v_leverage > -1 else 'No Change'}\n"
            f"Amount   : {v_order_amount} USDT\n"
            f"SL/TP    : {Colors.RED}-{v_sl_ratio}%{Colors.RESET} / {Colors.GREEN}+{v_tp_ratio}%{Colors.RESET}\n"
            f"Loop     : {LOOP_INTERVAL}s interval, {CACHE_TTL}s cache TTL\n"
            f"AutoClose: {Colors.YELLOW}{'ENABLED' if AUTO_CLOSE_ORPHANED else 'DISABLED'}{Colors.RESET}"
            "\n===================================")

# Fetch initial balance and initialize risk manager
try:
    balance_info = exchange.fetch_balance()
    initial_balance = balance_info['USDT']['free'] + balance_info['USDT']['used']
    risk_mgr.update_balance(initial_balance)
    logger.info(f"Initial balance loaded: {initial_balance:.2f} USDT")
except Exception as e:
    logger.warning(f"Could not fetch initial balance: {type(e).__name__}: {str(e)}")
    logger.warning("Risk management will start tracking once balance is available")


# Execute leverage change
if v_leverage > -1:
    try:
        exchange.market(v_symbol)
        exchange.set_leverage(v_leverage, v_symbol)
        logger.info(f"Leverage changed to {v_leverage}x")
    except Exception as e:
        logger.warning(f"Failed to set leverage (may already be {v_leverage}x): {type(e).__name__}: {str(e)}")

# 심볼 형식 정규화: 슬래시 제거 (예: 'ETH/USDT' -> 'ETHUSDT')
def normalize_symbol(symbol):
    """Convert symbol to non-slash format by removing '/' if present."""
    return symbol.replace('/', '') if '/' in symbol else symbol


# 시장 데이터 수집: 볼린저 밴드, RSI, 현재가 조회 (캐싱 적용)
def fetch_market_data(exchange, symbol, cache, api_counter):
    """Fetch Bollinger Bands, RSI, and price data with caching.
    
    Returns:
        tuple: (bands, current_price, band_values, rsi_values, midpoints) or (None, None, None, None, None) on error
    """
    try:
        symbol_normalized = normalize_symbol(symbol)
        tf_tuple = tuple(['1m', '5m', '15m', '1h', '1d'])
        
        # Get current price first
        current_price = exchange.fetch_ticker(symbol)['last']
        logger.info(f"Current price: {current_price}")
        
        # Fetch Bollinger Bands
        cached_bands = cache.get('bollinger', symbol_normalized, tf_tuple)
        if cached_bands:
            bands = cached_bands
            bands_source = "cache"
        else:
            bands = technical_indicators.get_bollinger_for_timeframes(
                symbol_normalized, timeframes=['1m', '5m', '15m', '1h', '1d'], exchange=exchange)
            cache.set('bollinger', symbol_normalized, tf_tuple, bands)
            bands_source = "API"
        api_counter.increment('fetch_bollinger_bands')
        
        # Analyze Bollinger Band positions and log in one line
        band_values = {}
        band_positions = []
        for tf, v in bands.items():
            if current_price > v['upper']:
                pos = 'above_upper'
                band_positions.append(f'{Colors.GREEN}{tf} Up{Colors.RESET}')
            elif current_price < v['lower']:
                pos = 'below_lower'
                band_positions.append(f'{Colors.RED}{tf} Dn{Colors.RESET}')
            else:
                pos = 'inside_bands'
                band_positions.append(f'{tf}')
            band_values[tf] = pos
        logger.info(f"B-Bands ({bands_source}): {', '.join(band_positions)}")
        
        # Fetch RSI
        cached_rsi = cache.get('rsi', symbol_normalized, tf_tuple)
        if cached_rsi:
            rsi_results = cached_rsi
            rsi_source = "cache"
        else:
            rsi_results = technical_indicators.get_rsi_for_timeframes(
                symbol_normalized, timeframes=['1m', '5m', '15m', '1h', '1d'], exchange=exchange)
            cache.set('rsi', symbol_normalized, tf_tuple, rsi_results)
            rsi_source = "API"
        api_counter.increment('fetch_rsi')
        
        rsi_values = {tf: (float(v['rsi']) if v.get('rsi') is not None else None) 
                     for tf, v in rsi_results.items()}
        logger.info(f"RSI     ({rsi_source}): 1m={rsi_values['1m']:.0f}, 5m={rsi_values['5m']:.0f}, "
                   f"15m={rsi_values['15m']:.0f}, 1h={rsi_values['1h']:.0f}, 1d={rsi_values['1d']:.0f}")
        
        # Fetch midpoints
        midpoints = {
            '15m': technical_indicators.fetch_ohlcv_field(exchange, symbol, '15m', 'mid'),
            '1h': technical_indicators.fetch_ohlcv_field(exchange, symbol, '1h', 'mid'),
            '1d': technical_indicators.fetch_ohlcv_field(exchange, symbol, '1d', 'mid')
        }
        
        return bands, current_price, band_values, rsi_values, midpoints
        
    except Exception as e:
        logger.error(f'Failed to fetch market data: {type(e).__name__}: {str(e)}')
        return None, None, None, None, None


# 진입 조건 평가: Long/Short 진입 신호 판단 및 강제 진입 조건 확인
def evaluate_entry_conditions(rsi_values, band_values, current_price, midpoints):
    """Evaluate long and short entry conditions.
    
    Returns:
        tuple: (v_action, scond_1m, scond_5m) where v_action is 'long', 'short', or None
    """
    rsi_1m = rsi_values.get('1m')
    rsi_5m = rsi_values.get('5m')
    rsi_15m = rsi_values.get('15m')
    rsi_1h = rsi_values.get('1h')
    rsi_1d = rsi_values.get('1d')
    
    # Long entry conditions
    cond_1m = (rsi_1m is not None and rsi_1m <= RSI_OVERSOLD_1M or band_values['1m'] == 'below_lower')
    cond_5m = ((rsi_5m is not None and rsi_5m <= RSI_OVERSOLD_5M and band_values['5m'] == 'below_lower')
               or (cond_1m == True and rsi_5m <= RSI_OVERSOLD_1M and rsi_5m <= rsi_1m))
    cond_15m = (rsi_15m is not None and rsi_15m <= RSI_OVERSOLD_15M
                and (midpoints['15m'] is not None and current_price < midpoints['15m']))
    cond_1h = (rsi_1h is not None and rsi_1h <= RSI_NEUTRAL_1H
               and (midpoints['1h'] is not None and current_price < midpoints['1h']))
    cond_1d = (rsi_1d is not None and rsi_1d >= RSI_NEUTRAL_1D
               and (midpoints['1d'] is not None and current_price < midpoints['1d']))
    
    logger.info(f"Long  conditions : "
                f"{(Colors.GREEN + str(cond_1m) + Colors.RESET) if cond_1m else cond_1m}, "
                f"{(Colors.GREEN + str(cond_5m) + Colors.RESET) if cond_5m else cond_5m}, "
                f"{(Colors.GREEN + str(cond_15m) + Colors.RESET) if cond_15m else cond_15m}, "
                f"{(Colors.GREEN + str(cond_1h) + Colors.RESET) if cond_1h else cond_1h}, "
                f"{(Colors.GREEN + str(cond_1d) + Colors.RESET) if cond_1d else cond_1d}")
    
    v_action = None
    if cond_1m and cond_5m and cond_15m and cond_1h and cond_1d:
        v_action = 'long'
        logger.info('Long entry conditions met -> set v_action = long')
    
    # Short entry conditions (initialize scond_1m/5m early for forced entry checks)
    scond_1m = (rsi_1m is not None and rsi_1m >= RSI_OVERBOUGHT_1M or band_values['1m'] == 'above_upper')
    scond_5m = (rsi_5m is not None and rsi_5m >= RSI_OVERBOUGHT_5M and band_values['5m'] == 'above_upper')
    
    if v_action != 'long':
        scond_15m = (rsi_15m is not None and rsi_15m >= RSI_OVERBOUGHT_15M
                     and (midpoints['15m'] is not None and current_price > midpoints['15m']))
        scond_1h = (rsi_1h is not None and rsi_1h >= RSI_OVERBOUGHT_1H
                    and (midpoints['1h'] is not None and current_price > midpoints['1h']))
        scond_1d = (rsi_1d is not None and rsi_1d <= RSI_OVERBOUGHT_1D
                    and (midpoints['1d'] is not None and current_price > midpoints['1d']))
        
        logger.info(f"Short conditions : "
                    f"{(Colors.RED + str(scond_1m) + Colors.RESET) if scond_1m else scond_1m}, "
                    f"{(Colors.RED + str(scond_5m) + Colors.RESET) if scond_5m else scond_5m}, "
                    f"{(Colors.RED + str(scond_15m) + Colors.RESET) if scond_15m else scond_15m}, "
                    f"{(Colors.RED + str(scond_1h) + Colors.RESET) if scond_1h else scond_1h}, "
                    f"{(Colors.RED + str(scond_1d) + Colors.RESET) if scond_1d else scond_1d}")
        
        if scond_1m and scond_5m and scond_15m and scond_1h and scond_1d:
            v_action = 'short'
            logger.info('Short entry conditions met -> set v_action = short')
    else:
        logger.info('already set to long... skipping short check')
    
    # Forced entry conditions (extreme RSI values)
    if v_action is None:
        if scond_1m and scond_5m and (rsi_1m is not None and rsi_1m >= RSI_OVERBOUGHT_1M):
            v_action = 'short'
            logger.info(f'{Colors.RED}Short entry conditions enabled by extreme high RSI -> short{Colors.RESET}')
        elif scond_1m and scond_5m and (rsi_1m is not None and rsi_1m <= RSI_OVERSOLD_1M):
            v_action = 'long'
            logger.info(f'{Colors.GREEN}Long entry conditions enabled by extreme low RSI -> long{Colors.RESET}')
    
    return v_action, scond_1m, scond_5m


# 포지션 모니터링: 기존 포지션 상태 확인 및 추적
def monitor_existing_positions(exchange, symbol):
    """Monitor existing positions and return their status (supports Hedge Mode with LONG and SHORT).
    
    Returns:
        list: List of position information dicts, or empty list if no positions exist
    """
    try:
        positions = exchange.fetch_positions(symbols=[symbol])
        open_positions_list = []
        
        if positions:
            open_positions = [p for p in positions if p.get('contracts') != 0 or (p.get('percentage') and p['percentage'] != 0)]
            
            for pos in open_positions:
                side = "LONG" if pos['side'] == 'long' else "SHORT" if pos['side'] == 'short' else None
                
                if side:
                    # Get entry price from multiple possible field locations
                    entry_price = pos.get('average', 0)
                    if entry_price == 0 and 'info' in pos:
                        # Try to get from info dict (raw API response)
                        entry_price = float(pos['info'].get('avgPrice', pos['info'].get('entryPrice', 0)))
                    
                    open_positions_list.append({
                        'side': side,
                        'contracts': pos.get('contracts', 0),
                        'entry_price': entry_price,
                        'current_price': pos.get('markPrice', 0),
                        'unrealized_pnl': pos.get('unrealizedPnl', 0),
                        'percentage': pos.get('percentage', 0)
                    })
    except Exception as e:
        logger.debug(f"Could not fetch positions: {str(e)}")
    
    return open_positions_list


# 진입 제외 필터: 일봉 위치, 추세 반전, 중복 거래 방지 등 체크
def check_exclusion_filters(v_action, current_price, rsi_values, midpoints, trades_time):
    """Apply exclusion filters to prevent unwanted entries.
    
    Returns:
        str or None: Updated v_action ('long', 'short', or None)
    """
    if v_action is None:
        return None
    
    # Check daily position ratio
    high_1d = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1d', 'high')
    low_1d = technical_indicators.fetch_ohlcv_field(exchange, v_symbol, '1d', 'low')
    ratio_pos = ((current_price - low_1d) / (high_1d - low_1d)) * 100 \
                if (high_1d is not None and low_1d is not None and high_1d != low_1d) else None
    
    logger.info(f"Daily position : {low_1d:.2f}, {midpoints['1d']:.2f}, {high_1d:.2f} "
                f"{Colors.YELLOW}{ratio_pos:.2f}{Colors.RESET}%" 
                if ratio_pos is not None else "Daily position : passed")
    
    # Filter by daily position range
    if v_action == 'short' and ratio_pos and ratio_pos <= DAILY_POSITION_LOW:
        logger.info(f'{Colors.YELLOW}Short entry rejected: price too low in daily range '
                   f'({ratio_pos:.1f}% < {DAILY_POSITION_LOW}%){Colors.RESET}')
        return None
    
    if v_action == 'long' and ratio_pos and ratio_pos >= DAILY_POSITION_HIGH:
        logger.info(f'{Colors.YELLOW}Long entry rejected: price too high in daily range '
                   f'({ratio_pos:.1f}% > {DAILY_POSITION_HIGH}%){Colors.RESET}')
        return None
    
    # Override on trend reversal
    rsi_1m = rsi_values.get('1m')
    rsi_15m = rsi_values.get('15m')
    rsi_1h = rsi_values.get('1h')
    rsi_1d = rsi_values.get('1d')
    
    if rsi_1m is not None:
        if rsi_15m >= rsi_1h >= rsi_1d:
            logger.info(f'{Colors.GREEN}Trend reversal detected: uptrend momentum -> override to long{Colors.RESET}')
            return 'long'
        elif rsi_15m <= rsi_1h <= rsi_1d:
            logger.info(f'{Colors.RED}Trend reversal detected: downtrend momentum -> override to short{Colors.RESET}')
            return 'short'
    
    # Prevent excessive trading
    diff_time = datetime.now() - datetime.strptime(trades_time, '%Y-%m-%d %H:%M:%S')
    if abs(diff_time.total_seconds()) < MIN_TRADE_INTERVAL:
        logger.info(f"Trade occurred within last {MIN_TRADE_INTERVAL}s. (preventing duplicate entry or excessive trading)")
        return None
    
    return v_action

# Graceful shutdown handling
shutdown_flag = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_flag
    signal_name = 'SIGINT' if signum == signal.SIGINT else 'SIGTERM'
    logger.info(f"\n{Colors.YELLOW}Received {signal_name} - Initiating graceful shutdown...{Colors.RESET}")
    shutdown_flag = True

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

logger.info("Press Ctrl+C to stop the bot gracefully")

while not shutdown_flag:
    try:                    
        # Initialize default values
        v_action = None
        v_order_result = None
        
        # Update balance and risk status at the start of each loop
        try:
            balance_info = exchange.fetch_balance()
            current_balance = balance_info['USDT']['free'] + balance_info['USDT']['used']
            risk_mgr.update_balance(current_balance)
        except Exception as e:
            logger.warning(f"Could not fetch balance: {type(e).__name__}: {str(e)}")
        
        # Step 1: Fetch market data (Bollinger Bands, RSI, price)
        bands, current_price, band_values, rsi_values, midpoints = fetch_market_data(
            exchange, v_symbol, cache, api_counter)
        
        if bands is None:  # Skip iteration if data fetch failed
            continue
        
        # Step 2: Evaluate entry conditions (long/short)
        v_action, scond_1m, scond_5m = evaluate_entry_conditions(
            rsi_values, band_values, current_price, midpoints)
        
        # Step 3: Apply exclusion filters
        v_action = check_exclusion_filters(v_action, current_price, rsi_values, midpoints, trades_time)
        
        # Step 4: Execute trade if action decided
        if v_action is not None:
            # Check risk limits before trading
            can_trade, block_reason = risk_mgr.can_trade()
            
            if not can_trade:
                logger.warning(f"{Colors.RED}Trade blocked by risk manager: {block_reason}{Colors.RESET}")
                v_action = None  # Cancel trade
            else:
                # Calculate dynamic position size based on risk level
                dynamic_size = risk_mgr.calculate_position_size()
                actual_order_amount = min(v_order_amount, dynamic_size)  # Use smaller of configured or dynamic size
                
                logger.info(f'{Colors.YELLOW}Start a trading action decided : {v_action}{Colors.RESET}')
                if actual_order_amount < v_order_amount:
                    logger.info(f"{Colors.CYAN}Position size adjusted by risk manager: {v_order_amount} → {actual_order_amount:.2f} USDT{Colors.RESET}")
                
                try:
                    v_order_result = position_manager.execute_position_entry(
                        exchange=exchange,
                        symbol=v_symbol,
                        action=v_action,
                        order_amount=actual_order_amount,
                        sl_ratio=v_sl_ratio,
                        tp_ratio=v_tp_ratio,
                        order_type=v_order_type,
                        min_order_usdt=min_order_usdt
                    )
                    
                    time.sleep(1)  # Wait for position reflection
                    
                    if v_order_result:
                        if v_action == 'long':
                            long_trades_count += 1
                        elif v_action == 'short':
                            short_trades_count += 1
                        
                        # Track position entry for monitoring
                        active_position = {
                            'side': v_action,
                            'entry_price': current_price,
                            'entry_time': datetime.now(),
                            'entry_value': actual_order_amount
                        }
                        
                        trades_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        logger.info(f"{Colors.GREEN}Position entry successful: {v_action} @ {current_price:.2f}{Colors.RESET}")
                    else:
                        logger.info(f"Position entry rejected or position already exists")
                        error_count += 1
                
                except Exception as e:
                    error_count += 1
                    logger.error(f'Error during position entry: {type(e).__name__}, {str(e)}')
        
        # Step 5: Monitor existing exchange positions (detect abandoned positions)
        existing_positions = monitor_existing_positions(exchange, v_symbol)
        
        # Detect if active position was closed (SL/TP hit)
        if active_position and not existing_positions:
            # Position was closed - calculate realized PnL
            if active_position['side'] == 'long':
                realized_pnl_pct = (current_price - active_position['entry_price']) / active_position['entry_price'] * 100
            else:  # short
                realized_pnl_pct = (active_position['entry_price'] - current_price) / active_position['entry_price'] * 100
            
            realized_pnl_usdt = (realized_pnl_pct / 100) * active_position.get('entry_value', v_order_amount)
            is_win = realized_pnl_usdt > 0
            
            # Update statistics
            total_pnl += realized_pnl_usdt
            if is_win:
                total_winning_trades += 1
                max_win = max(max_win, realized_pnl_usdt)
            else:
                total_losing_trades += 1
                max_loss = min(max_loss, realized_pnl_usdt)
            
            # Record in risk manager
            risk_mgr.record_trade_result(realized_pnl_usdt, is_win)
            
            # Log position close
            pnl_color = Colors.GREEN if is_win else Colors.RED
            logger.info(f"{pnl_color}[POSITION CLOSED] {active_position['side'].upper()} @ {active_position['entry_price']:.2f} | "
                       f"Close: {current_price:.2f} | Realized PnL: {realized_pnl_usdt:+.2f} USDT ({realized_pnl_pct:+.3f}%){Colors.RESET}")
            
            active_position = None
        
        # Monitor all open positions (supports Hedge Mode with LONG and SHORT simultaneously)
        if existing_positions:
            for existing_pos in existing_positions:
                side_lower = existing_pos['side'].lower()
                
                # Track orphaned position internally without logging every iteration
                if side_lower not in tracked_orphaned_sides:
                    tracked_orphaned_sides.add(side_lower)
                    
                    # Auto-close if enabled in config
                    if AUTO_CLOSE_ORPHANED:
                        logger.info(f"{Colors.YELLOW}Closing orphaned {existing_pos['side']} position...{Colors.RESET}")
                        close_success = position_manager.close_orphaned_position(exchange, v_symbol, existing_pos['side'])
                        
                        if close_success:
                            logger.info(f"{Colors.GREEN}Orphaned {existing_pos['side']} position closed successfully{Colors.RESET}")
                            tracked_orphaned_sides.discard(side_lower)  # Clear tracking after successful close
                        else:
                            active_position = existing_pos  # Track failed close attempt
                            logger.warning(f"{Colors.YELLOW}Failed to close orphaned {existing_pos['side']} position, tracking it...{Colors.RESET}")
                    else:
                        # Manual mode - just track silently
                        if not active_position:
                            active_position = existing_pos
        else:
            # Clear tracked orphaned positions when no positions exist anymore
            if tracked_orphaned_sides:
                tracked_orphaned_sides.clear()
        
        # Step 6: Monitor open positions and calculate unrealized PnL
        # Display all existing positions (LONG and SHORT both in Hedge Mode)
        if existing_positions:
            for pos in existing_positions:
                unrealized_pnl = 0.0
                entry_price = pos.get('entry_price', 0) or 0
                current_pos_price = pos.get('current_price', current_price)
                
                # Calculate PnL if entry price is available
                if entry_price > 0:
                    if pos['side'].lower() == 'long':
                        unrealized_pnl = (current_pos_price - entry_price) / entry_price * 100
                    else:  # short
                        unrealized_pnl = (entry_price - current_pos_price) / entry_price * 100
                    
                    logger.info(f"[POSITION] {pos['side'].upper()} @ {entry_price:.2f} | "
                               f"Current: {current_pos_price:.2f} | Unrealized PnL: {unrealized_pnl:+.3f}%")
                else:
                    # No entry price available
                    logger.info(f"[POSITION] {pos['side'].upper()} @ N/A | "
                               f"Current: {current_pos_price:.2f} | Unrealized PnL: N/A")
        
        # Step 6: Log statistics
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        diff_time = datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S') - datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
        logger.info(f"Bot running time: {diff_time}")
        diff_time = datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S') - datetime.strptime(trades_time, '%Y-%m-%d %H:%M:%S')
        logger.info(f"Trade waiting time: {diff_time}")
        
        loop_count += 1
        
        # Log API usage stats and risk status every N iterations (from config)
        if loop_count % STATS_DISPLAY_INTERVAL == 0:
            stats = api_counter.get_stats()
            cache_stats = cache.get_stats()
            logger.info(f"[STATS] API calls: {stats['total_calls']} ({stats['calls_per_minute']:.1f}/min) | "
                       f"Cache: {cache_stats['active_entries']} active entries")
            # Display risk management status
            risk_mgr.log_status()
        
        logger.info(f"long trades = {long_trades_count}, short trades = {short_trades_count}, "
                   f"error count = {error_count}, total loop = {loop_count} end.\n")
        

    except Exception as e:
        logger.error(f'Error in main loop: {type(e).__name__}: {str(e)}')
        import traceback
        logger.error(f'Traceback: {traceback.format_exc()}')
        error_count += 1
    except KeyboardInterrupt:
        logger.info(f"\n{Colors.YELLOW}Keyboard interrupt detected - Shutting down...{Colors.RESET}")
        shutdown_flag = True
    finally:
        if not shutdown_flag:
            time.sleep(LOOP_INTERVAL)  # Configurable delay before next iteration


# Shutdown summary
end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
total_runtime = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S') - datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')

logger.info("\n" + "="*60)
logger.info("TRADING BOT SHUTDOWN SUMMARY")
logger.info("="*60)
logger.info(f"Start Time      : {start_time}")
logger.info(f"End Time        : {end_time}")
logger.info(f"Total Runtime   : {total_runtime}")
logger.info(f"Total Loops     : {loop_count}")
logger.info(f"Long Trades     : {long_trades_count}")
logger.info(f"Short Trades    : {short_trades_count}")
logger.info(f"Total Trades    : {long_trades_count + short_trades_count}")
logger.info(f"Errors          : {error_count}")
logger.info(f"Success Rate    : {((loop_count - error_count) / loop_count * 100):.1f}%" if loop_count > 0 else "N/A")
# PnL statistics
logger.info("")
logger.info(f"Total PnL       : {Colors.GREEN if total_pnl >= 0 else Colors.RED}{total_pnl:+.2f} USDT{Colors.RESET}")
logger.info(f"Winning Trades  : {total_winning_trades}")
logger.info(f"Losing Trades   : {total_losing_trades}")
win_rate = (total_winning_trades / (total_winning_trades + total_losing_trades) * 100) if (total_winning_trades + total_losing_trades) > 0 else 0
logger.info(f"Win Rate        : {win_rate:.1f}%")
logger.info(f"Max Win         : {Colors.GREEN}{max_win:+.2f} USDT{Colors.RESET}")
logger.info(f"Max Loss        : {Colors.RED}{max_loss:+.2f} USDT{Colors.RESET}")
# Final API stats
final_stats = api_counter.get_stats()
logger.info(f"Total API Calls : {final_stats['total_calls']} ({final_stats['calls_per_minute']:.1f}/min)")
# Final risk management status
logger.info("")
risk_mgr.log_status()
logger.info("="*60)
logger.info(f"{Colors.GREEN}Bot stopped gracefully. Goodbye!{Colors.RESET}\n")



