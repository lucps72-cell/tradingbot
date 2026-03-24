import logging

class RiskManager:
    """리스크 관리 클래스."""
    def __init__(self, stop_loss=0.02, take_profit=0.04):
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def check_risk(self, entry_price, current_price, side):
        if side == 'long':
            if current_price <= entry_price * (1 - self.stop_loss):
                return 'stop_loss'
            if current_price >= entry_price * (1 + self.take_profit):
                return 'take_profit'
        elif side == 'short':
            if current_price >= entry_price * (1 + self.stop_loss):
                return 'stop_loss'
            if current_price <= entry_price * (1 - self.take_profit):
                return 'take_profit'
        return None
