"""
Validation module for Bybit Trading Bot
Performs startup checks for API keys, symbols, balances, etc.
"""

import os
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


def validate_api_credentials() -> Tuple[bool, str]:
    """
    Validate that API credentials are set in environment variables
    
    Returns:
        Tuple of (is_valid: bool, message: str)
    """
    api_key = os.getenv("BYBIT_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET")
    
    if not api_key:
        return False, "BYBIT_API_KEY environment variable not set"
    
    if not api_secret:
        return False, "BYBIT_API_SECRET environment variable not set"
    
    if len(api_key) < 10:
        return False, "BYBIT_API_KEY appears to be invalid (too short)"
    
    if len(api_secret) < 10:
        return False, "BYBIT_API_SECRET appears to be invalid (too short)"
    
    return True, "API credentials validated successfully"


def validate_symbol(exchange, symbol: str) -> Tuple[bool, str]:
    """
    Validate that the trading symbol exists on the exchange
    
    Args:
        exchange: CCXT exchange object
        symbol: Trading symbol (e.g., 'ETHUSDT')
        
    Returns:
        Tuple of (is_valid: bool, message: str)
    """
    try:
        # Fetch market to verify symbol exists
        market = exchange.market(symbol)
        if market:
            return True, f"Symbol {symbol} validated successfully"
        else:
            return False, f"Symbol {symbol} not found on exchange"
    except Exception as e:
        return False, f"Failed to validate symbol {symbol}: {str(e)}"


def validate_balance(exchange, symbol: str) -> Tuple[bool, str, Optional[dict]]:
    """
    Validate that account has sufficient balance for trading
    
    Args:
        exchange: CCXT exchange object
        symbol: Trading symbol (e.g., 'ETHUSDT')
        
    Returns:
        Tuple of (is_valid: bool, message: str, balance_info: dict or None)
    """
    try:
        # Fetch account balance
        balance = exchange.fetch_balance()
        
        if not balance:
            return False, "Failed to fetch account balance", None
        
        # Check USDT balance
        usdt_balance = balance.get('USDT', {})
        free_balance = usdt_balance.get('free', 0)
        total_balance = usdt_balance.get('total', 0)
        
        if free_balance <= 0:
            return False, f"No available USDT balance (free: {free_balance}, total: {total_balance})", balance
        
        balance_info = {
            'free_usdt': free_balance,
            'total_usdt': total_balance,
            'used_usdt': usdt_balance.get('used', 0)
        }
        
        return True, f"Balance validated: {free_balance:.2f} USDT available", balance_info
        
    except Exception as e:
        return False, f"Failed to fetch balance: {str(e)}", None


def validate_leverage(exchange, symbol: str, leverage: int) -> Tuple[bool, str]:
    """
    Validate that leverage setting is valid for the symbol
    
    Args:
        exchange: CCXT exchange object
        symbol: Trading symbol (e.g., 'ETHUSDT')
        leverage: Leverage multiplier (e.g., 20)
        
    Returns:
        Tuple of (is_valid: bool, message: str)
    """
    if leverage == -1:
        return True, "Leverage: No change (keeping current)"
    
    if leverage < 1 or leverage > 100:
        return False, f"Invalid leverage: {leverage}. Must be between 1 and 100"
    
    try:
        # Try to get market limits
        market = exchange.market(symbol)
        if 'limits' in market:
            limits = market['limits']
            if 'leverage' in limits:
                max_leverage = limits['leverage'].get('max', 100)
                if leverage > max_leverage:
                    return False, f"Leverage {leverage} exceeds maximum {max_leverage} for {symbol}"
        
        return True, f"Leverage {leverage}x is valid"
    except Exception as e:
        return False, f"Failed to validate leverage: {str(e)}"


def validate_connection(exchange) -> Tuple[bool, str]:
    """
    Validate connection to exchange by fetching server time
    
    Args:
        exchange: CCXT exchange object
        
    Returns:
        Tuple of (is_valid: bool, message: str)
    """
    try:
        server_time = exchange.fetch_time()
        if server_time:
            return True, "Connection to Bybit verified"
        else:
            return False, "Failed to verify connection to Bybit"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


def run_all_validations(exchange, symbol: str, leverage: int = -1) -> Tuple[bool, list]:
    """
    Run all startup validations
    
    Args:
        exchange: CCXT exchange object
        symbol: Trading symbol
        leverage: Leverage multiplier
        
    Returns:
        Tuple of (all_valid: bool, results: list of validation messages)
    """
    results = []
    all_valid = True
    
    # Check 1: API Credentials
    valid, msg = validate_api_credentials()
    results.append(("API Credentials", valid, msg))
    all_valid = all_valid and valid
    
    # Check 2: Connection
    valid, msg = validate_connection(exchange)
    results.append(("Exchange Connection", valid, msg))
    all_valid = all_valid and valid
    
    # Check 3: Symbol
    valid, msg = validate_symbol(exchange, symbol)
    results.append(("Symbol Validation", valid, msg))
    all_valid = all_valid and valid
    
    # Check 4: Balance
    valid, msg, _ = validate_balance(exchange, symbol)
    results.append(("Account Balance", valid, msg))
    all_valid = all_valid and valid
    
    # Check 5: Leverage
    valid, msg = validate_leverage(exchange, symbol, leverage)
    results.append(("Leverage Setting", valid, msg))
    all_valid = all_valid and valid
    
    return all_valid, results


def print_validation_results(results: list, logger: logging.Logger):
    """
    Print validation results in a formatted way
    
    Args:
        results: List of validation tuples (name, is_valid, message)
        logger: Logger instance
    """
    logger.info("\n" + "="*60)
    logger.info("STARTUP VALIDATION RESULTS")
    logger.info("="*60)
    
    for check_name, is_valid, message in results:
        status = "✓ PASS" if is_valid else "✗ FAIL"
        log_level = "info" if is_valid else "error"
        getattr(logger, log_level)(f"{status:8} | {check_name:25} | {message}")
    
    logger.info("="*60 + "\n")
