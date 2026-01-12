"""
Configuration file loader for Bybit Trading Bot
Loads settings from config.json and merges with command-line arguments
"""

import json
import os
from pathlib import Path


def load_config(config_file: str = 'config.json') -> dict:
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
    config_path = Path(config_file)
    
    if not config_path.exists():
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
    
    # Override trading parameters from command line if provided
    if hasattr(args, 'symbol') and args.symbol != 'ETHUSDT':  # Default value
        merged['trading']['symbol'] = args.symbol
    
    if hasattr(args, 'leverage') and args.leverage != -1:  # Default value
        merged['trading']['leverage'] = args.leverage
    
    if hasattr(args, 'amount') and args.amount != 5000:  # Default value
        merged['trading']['order_amount'] = args.amount
    
    if hasattr(args, 'sl') and args.sl != 0.20:  # Default value
        merged['trading']['sl_ratio'] = args.sl
    
    if hasattr(args, 'tp') and args.tp != 0.40:  # Default value
        merged['trading']['tp_ratio'] = args.tp
    
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
