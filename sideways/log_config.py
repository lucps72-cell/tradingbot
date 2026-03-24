import json
import logging
import logging.config
import os

def setup_logging(default_path='log_config.json', default_level=logging.INFO):
    """로깅 설정을 초기화합니다."""
    if os.path.exists(default_path):
        with open(default_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=logging.DEBUG)
