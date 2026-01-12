"""
로깅 설정 모듈
일별로 로그 파일을 생성하고 관리합니다.
"""

import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler


def setup_logging(
    log_dir: str = "logs",
    log_level: int = logging.INFO,
    log_format: str = None
) -> logging.Logger:
    """
    로깅 설정 및 Logger 반환
    
    Args:
        log_dir: 로그 파일이 저장될 디렉토리
        log_level: 로그 레벨 (logging.INFO, logging.DEBUG 등)
        log_format: 로그 포맷 문자열 (None이면 기본 포맷 사용)
        
    Returns:
        설정된 Logger 객체
    """
    # 로그 디렉토리 생성
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 기본 로그 포맷
    if log_format is None:
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Logger 생성
    logger = logging.getLogger('tradingbot')
    logger.setLevel(log_level)
    
    # 기존 핸들러 제거 (중복 방지)
    logger.handlers.clear()
    
    # 일별 로그 파일 핸들러 (자정에 자동으로 새 파일 생성)
    log_filename = os.path.join(log_dir, 'tradingbot_%Y-%m-%d.log')
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(log_dir, 'tradingbot.log'),
        when='midnight',  # 자정에 새 파일 생성
        interval=1,       # 매일
        backupCount=30,   # 30일치 로그 보관
        encoding='utf-8',
        delay=False
    )
    file_handler.suffix = '%Y-%m-%d'  # 파일명에 날짜 추가
    file_handler.setLevel(log_level)
    file_formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(file_formatter)
    
    # 콘솔 핸들러 (터미널에도 출력)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    
    # 핸들러 추가
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_logger(name: str = 'tradingbot') -> logging.Logger:
    """
    Logger 객체 가져오기
    
    Args:
        name: Logger 이름
        
    Returns:
        Logger 객체
    """
    return logging.getLogger(name)

