"""
Risk Management Module for Trading Bot

이 모듈은 다음 위험 관리 기능을 제공합니다:
- Max Drawdown (최대 인출) 추적 및 제한
- Daily Loss Limit (일일 손실 한도) 제한
- Dynamic Position Sizing (동적 포지션 크기 조정)
- Consecutive Loss Protection (연속 손실 보호)
- Account Health Monitoring (계좌 상태 모니터링)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class RiskManager:
    """
    위험 관리 클래스
    
    계좌 잔고, 최대 손실, 일일 손실, 연속 손실 등을 추적하고
    거래 허용 여부를 결정합니다.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize Risk Manager
        
        Args:
            config: 위험 관리 설정 딕셔너리
        """
        self.config = config
        
        # 최대 인출 (Max Drawdown) 설정
        self.max_drawdown_percent = config.get('max_drawdown_percent', 10.0)
        self.peak_balance = 0.0
        self.current_balance = 0.0
        self.current_drawdown_percent = 0.0
        
        # 일일 손실 한도 설정
        self.daily_loss_limit_percent = config.get('daily_loss_limit_percent', 5.0)
        self.daily_loss_limit_usdt = config.get('daily_loss_limit_usdt', None)
        self.daily_start_balance = 0.0
        self.daily_loss_usdt = 0.0
        self.last_reset_date = None
        
        # 연속 손실 보호
        self.max_consecutive_losses = config.get('max_consecutive_losses', 5)
        self.consecutive_losses = 0
        
        # 동적 포지션 크기 조정
        self.enable_dynamic_sizing = config.get('enable_dynamic_sizing', True)
        self.base_position_size = config.get('base_position_size', 5000)
        self.min_position_size = config.get('min_position_size', 1000)
        self.max_position_size = config.get('max_position_size', 10000)
        self.position_size_multiplier = 1.0
        
        # 위험 등급 임계값
        self.risk_levels = {
            'low': config.get('risk_level_low', 3.0),
            'medium': config.get('risk_level_medium', 5.0),
            'high': config.get('risk_level_high', 8.0)
        }
        
        # 초기화 완료 로그
        logger.info("="*60)
        logger.info("RISK MANAGER INITIALIZED")
        logger.info("="*60)
        logger.info(f"Max Drawdown        : {self.max_drawdown_percent}%")
        logger.info(f"Daily Loss Limit    : {self.daily_loss_limit_percent}% or {self.daily_loss_limit_usdt} USDT")
        logger.info(f"Max Consecutive Loss: {self.max_consecutive_losses} trades")
        logger.info(f"Dynamic Sizing      : {'Enabled' if self.enable_dynamic_sizing else 'Disabled'}")
        logger.info(f"Position Size Range : {self.min_position_size} - {self.max_position_size} USDT")
        logger.info("="*60 + "\n")
    
    def update_balance(self, balance: float) -> None:
        """
        잔고 업데이트 및 최대 인출 추적
        
        Args:
            balance: 현재 계좌 잔고 (USDT)
        """
        self.current_balance = balance
        
        # 최고 잔고 업데이트
        if balance > self.peak_balance:
            self.peak_balance = balance
            self.current_drawdown_percent = 0.0
            logger.info(f"✓ New peak balance reached: {self.peak_balance:.2f} USDT")
        else:
            # 현재 인출률 계산
            self.current_drawdown_percent = ((self.peak_balance - balance) / self.peak_balance) * 100
        
        # 일일 리셋 체크
        self._check_daily_reset(balance)
    
    def _check_daily_reset(self, balance: float) -> None:
        """
        일일 손실 추적을 위한 날짜 변경 체크
        
        Args:
            balance: 현재 계좌 잔고
        """
        today = datetime.now().date()
        
        if self.last_reset_date is None or self.last_reset_date != today:
            # 새로운 날짜 - 일일 통계 리셋
            self.last_reset_date = today
            self.daily_start_balance = balance
            self.daily_loss_usdt = 0.0
            logger.info(f"Daily stats reset. Starting balance: {balance:.2f} USDT")
    
    def record_trade_result(self, pnl: float, is_win: bool) -> None:
        """
        거래 결과 기록 (손익 및 승패)
        
        Args:
            pnl: 손익 (USDT)
            is_win: 승리 여부
        """
        # 일일 손실 업데이트
        if pnl < 0:
            self.daily_loss_usdt += abs(pnl)
        
        # 연속 손실 카운터 업데이트
        if is_win:
            self.consecutive_losses = 0
            # 승리 시 포지션 크기 증가 (최대치까지)
            if self.enable_dynamic_sizing and self.position_size_multiplier < 1.5:
                self.position_size_multiplier = min(1.5, self.position_size_multiplier + 0.1)
        else:
            self.consecutive_losses += 1
            # 손실 시 포지션 크기 감소 (최소치까지)
            if self.enable_dynamic_sizing and self.position_size_multiplier > 0.5:
                self.position_size_multiplier = max(0.5, self.position_size_multiplier - 0.1)
        
        logger.info(f"Trade recorded: PnL={pnl:+.2f} USDT | "
                   f"Consecutive losses: {self.consecutive_losses} | "
                   f"Position multiplier: {self.position_size_multiplier:.2f}x")
    
    def calculate_position_size(self) -> float:
        """
        현재 위험 수준에 따른 동적 포지션 크기 계산
        
        Returns:
            float: 권장 포지션 크기 (USDT)
        """
        if not self.enable_dynamic_sizing:
            return self.base_position_size
        
        # 기본 크기에 멀티플라이어 적용
        size = self.base_position_size * self.position_size_multiplier
        
        # 최대 인출률에 따른 조정
        if self.current_drawdown_percent > self.risk_levels['high']:
            size *= 0.5  # 50% 감소
        elif self.current_drawdown_percent > self.risk_levels['medium']:
            size *= 0.7  # 30% 감소
        elif self.current_drawdown_percent > self.risk_levels['low']:
            size *= 0.85  # 15% 감소
        
        # 연속 손실에 따른 조정
        if self.consecutive_losses >= 3:
            size *= (0.8 ** (self.consecutive_losses - 2))  # 연속 손실마다 20% 감소
        
        # 최소/최대 범위로 제한
        size = max(self.min_position_size, min(self.max_position_size, size))
        
        return round(size, 2)
    
    def can_trade(self) -> Tuple[bool, Optional[str]]:
        """
        현재 위험 수준을 평가하고 거래 가능 여부 판단
        
        Returns:
            Tuple[bool, Optional[str]]: (거래 가능 여부, 불가 이유)
        """
        # 최대 인출 체크
        if self.current_drawdown_percent >= self.max_drawdown_percent:
            reason = (f"Max drawdown limit reached: {self.current_drawdown_percent:.2f}% "
                     f"(Limit: {self.max_drawdown_percent}%)")
            logger.warning(f"🚫 TRADING BLOCKED: {reason}")
            return False, reason
        
        # 일일 손실 한도 체크 (퍼센트)
        if self.daily_start_balance > 0:
            daily_loss_percent = (self.daily_loss_usdt / self.daily_start_balance) * 100
            if daily_loss_percent >= self.daily_loss_limit_percent:
                reason = (f"Daily loss limit reached: {daily_loss_percent:.2f}% "
                         f"(Limit: {self.daily_loss_limit_percent}%)")
                logger.warning(f"🚫 TRADING BLOCKED: {reason}")
                return False, reason
        
        # 일일 손실 한도 체크 (USDT)
        if self.daily_loss_limit_usdt and self.daily_loss_usdt >= self.daily_loss_limit_usdt:
            reason = (f"Daily loss limit reached: {self.daily_loss_usdt:.2f} USDT "
                     f"(Limit: {self.daily_loss_limit_usdt} USDT)")
            logger.warning(f"🚫 TRADING BLOCKED: {reason}")
            return False, reason
        
        # 연속 손실 체크
        if self.consecutive_losses >= self.max_consecutive_losses:
            reason = (f"Too many consecutive losses: {self.consecutive_losses} "
                     f"(Limit: {self.max_consecutive_losses})")
            logger.warning(f"🚫 TRADING BLOCKED: {reason}")
            return False, reason
        
        return True, None
    
    def get_risk_level(self) -> str:
        """
        현재 위험 등급 반환
        
        Returns:
            str: 'low', 'medium', 'high', 'critical'
        """
        if self.current_drawdown_percent >= self.max_drawdown_percent * 0.9:
            return 'critical'
        elif self.current_drawdown_percent >= self.risk_levels['high']:
            return 'high'
        elif self.current_drawdown_percent >= self.risk_levels['medium']:
            return 'medium'
        elif self.current_drawdown_percent >= self.risk_levels['low']:
            return 'low'
        else:
            return 'safe'
    
    def get_status(self) -> Dict:
        """
        현재 위험 관리 상태 반환
        
        Returns:
            Dict: 위험 관리 상태 정보
        """
        daily_loss_percent = 0.0
        if self.daily_start_balance > 0:
            daily_loss_percent = (self.daily_loss_usdt / self.daily_start_balance) * 100
        
        return {
            'balance': self.current_balance,
            'peak_balance': self.peak_balance,
            'current_drawdown_percent': self.current_drawdown_percent,
            'max_drawdown_percent': self.max_drawdown_percent,
            'daily_loss_usdt': self.daily_loss_usdt,
            'daily_loss_percent': daily_loss_percent,
            'daily_loss_limit_percent': self.daily_loss_limit_percent,
            'consecutive_losses': self.consecutive_losses,
            'max_consecutive_losses': self.max_consecutive_losses,
            'position_size_multiplier': self.position_size_multiplier,
            'recommended_position_size': self.calculate_position_size(),
            'risk_level': self.get_risk_level(),
            'can_trade': self.can_trade()[0]
        }
    
    def log_status(self) -> None:
        """
        현재 위험 관리 상태를 로그에 출력
        """
        status = self.get_status()
        risk_color = self._get_risk_color(status['risk_level'])
        
        logger.info("─" * 60)
        logger.info("RISK MANAGEMENT STATUS")
        logger.info("─" * 60)
        logger.info(f"Balance             : {status['balance']:.2f} USDT (Peak: {status['peak_balance']:.2f})")
        logger.info(f"{risk_color}Drawdown            : {status['current_drawdown_percent']:.2f}% / {status['max_drawdown_percent']}%{self._get_reset_color()}")
        logger.info(f"Daily Loss          : {status['daily_loss_usdt']:.2f} USDT ({status['daily_loss_percent']:.2f}% / {status['daily_loss_limit_percent']}%)")
        logger.info(f"Consecutive Losses  : {status['consecutive_losses']} / {status['max_consecutive_losses']}")
        logger.info(f"Position Multiplier : {status['position_size_multiplier']:.2f}x")
        logger.info(f"Recommended Size    : {status['recommended_position_size']:.2f} USDT")
        logger.info(f"{risk_color}Risk Level          : {status['risk_level'].upper()}{self._get_reset_color()}")
        logger.info(f"Trading Status      : {'✓ ALLOWED' if status['can_trade'] else '🚫 BLOCKED'}")
        logger.info("─" * 60 + "\n")
    
    def _get_risk_color(self, risk_level: str) -> str:
        """위험 등급에 따른 색상 코드 반환"""
        from color_utils import Colors
        colors = {
            'safe': Colors.GREEN,
            'low': Colors.CYAN,
            'medium': Colors.YELLOW,
            'high': Colors.MAGENTA,
            'critical': Colors.RED
        }
        return colors.get(risk_level, Colors.RESET)
    
    def _get_reset_color(self) -> str:
        """색상 리셋 코드 반환"""
        from color_utils import Colors
        return Colors.RESET
