"""
Configuration file loader for Bybit Trading Bot
Loads settings from config.json and merges with command-line arguments
"""

import json
import os
from pathlib import Path


def load_config(config_file: str = None) -> dict:
    """
    Load configuration from JSON file
    
    Args:
        config_file: Path to config.json file
        
    Returns:
        Dictionary containing all configuration settings
        
    Raises:
        FileNotFoundError: If config.json is not found
        json.JSONDecodeError: If config.json is invalid
    """
    # main.py에서 넘긴 config_file이 있으면 그대로 사용, 없으면 기본값 사용
    if config_file is None:
        config_file = os.path.join(os.path.dirname(__file__), 'config.json')
    config_path = Path(config_file)
    if not config_path.exists():
        # workspace 기준으로 aibot_v2/config.json도 시도
        alt_path = os.path.join(os.getcwd(), 'aibot_v2', 'config.json')
        if os.path.exists(alt_path):
            config_path = Path(alt_path)
        else:
            raise FileNotFoundError(f"Config file not found: {config_file}")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Invalid JSON in config file: {str(e)}", e.doc, e.pos)


def merge_configs(file_config: dict, args: object) -> dict:
    """
    Merge file-based config with command-line arguments
    Command-line args override file config (except for defaults)
    
    Args:
        file_config: Configuration loaded from config.json
        args: argparse Namespace object from command-line arguments
        
    Returns:
        Merged configuration dictionary
    """
    merged = file_config.copy()
    
    # Override trading parameters from command line only when explicitly provided
    if hasattr(args, 'symbol') and args.symbol:
        merged['trading']['symbol'] = args.symbol
    
    if hasattr(args, 'leverage') and args.leverage is not None:
        merged['trading']['leverage'] = args.leverage
    
    if hasattr(args, 'amount') and args.amount is not None:
        # config uses order_amount_usdt
        merged['trading']['order_amount_usdt'] = args.amount
    
    if hasattr(args, 'sl') and args.sl is not None:
        merged['risk_management']['sl_ratio'] = args.sl
    
    if hasattr(args, 'tp') and args.tp is not None:
        merged['risk_management']['tp_ratio'] = args.tp
    
    return merged


def print_config(config: dict):
    """Print current configuration in a readable format"""
    print("\n" + "="*50)
    print("CURRENT CONFIGURATION")
    print("="*50)
    print("\n[Trading]")
    for key, value in config['trading'].items():
        print(f"  {key}: {value}")
    print("\n[RSI Thresholds - LONG]")
    for tf, val in config['rsi_thresholds']['long'].items():
        print(f"  {tf}: {val}")
    print("\n[RSI Thresholds - SHORT]")
    for tf, val in config['rsi_thresholds']['short'].items():
        print(f"  {tf}: {val}")
    print("\n[Price Filters]")
    for key, value in config['price_filters'].items():
        print(f"  {key}: {value}")
    print("="*50 + "\n")
