"""
Indicator cache module for Bybit Trading Bot
Caches technical indicator results to reduce redundant API calls
"""

import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta


class IndicatorCache:
    """
    Cache technical indicator results with TTL (time-to-live)
    to avoid redundant API calls within short time windows
    """
    
    def __init__(self, ttl_seconds: int = 30):
        """
        Initialize cache with TTL
        
        Args:
            ttl_seconds: Time-to-live for cached values in seconds
        """
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, Dict[str, Any]] = {}
    
    def _generate_key(self, indicator: str, symbol: str, timeframes: tuple) -> str:
        """Generate cache key from indicator, symbol, and timeframes"""
        tf_str = ",".join(sorted(timeframes))
        return f"{indicator}:{symbol}:{tf_str}"
    
    def _is_expired(self, cache_entry: Dict[str, Any]) -> bool:
        """Check if cache entry has expired"""
        if 'timestamp' not in cache_entry:
            return True
        
        elapsed = time.time() - cache_entry['timestamp']
        return elapsed > self.ttl_seconds
    
    def get(self, indicator: str, symbol: str, timeframes: tuple) -> Optional[Dict]:
        """
        Get cached indicator result if exists and not expired
        
        Args:
            indicator: Name of indicator (e.g., 'bollinger', 'rsi')
            symbol: Trading symbol
            timeframes: Tuple of timeframes
            
        Returns:
            Cached result or None if not found/expired
        """
        key = self._generate_key(indicator, symbol, timeframes)
        
        if key in self.cache:
            if not self._is_expired(self.cache[key]):
                return self.cache[key]['data']
            else:
                # Remove expired entry
                del self.cache[key]
        
        return None
    
    def set(self, indicator: str, symbol: str, timeframes: tuple, data: Dict):
        """
        Cache indicator result
        
        Args:
            indicator: Name of indicator
            symbol: Trading symbol
            timeframes: Tuple of timeframes
            data: Result data to cache
        """
        key = self._generate_key(indicator, symbol, timeframes)
        self.cache[key] = {
            'timestamp': time.time(),
            'data': data
        }
    
    def clear(self):
        """Clear all cache entries"""
        self.cache.clear()
    
    def clear_expired(self):
        """Remove all expired entries"""
        expired_keys = [
            key for key, entry in self.cache.items()
            if self._is_expired(entry)
        ]
        for key in expired_keys:
            del self.cache[key]
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        total_entries = len(self.cache)
        self.clear_expired()
        active_entries = len(self.cache)
        
        return {
            'total_entries': total_entries,
            'active_entries': active_entries,
            'expired_entries': total_entries - active_entries,
            'ttl_seconds': self.ttl_seconds
        }


class APICallCounter:
    """
    Track API calls to monitor usage and prevent excessive requests
    """
    
    def __init__(self):
        self.calls: Dict[str, int] = {}
        self.last_reset = time.time()
    
    def increment(self, endpoint: str):
        """Increment counter for API endpoint"""
        if endpoint not in self.calls:
            self.calls[endpoint] = 0
        self.calls[endpoint] += 1
    
    def get_count(self, endpoint: str) -> int:
        """Get call count for endpoint"""
        return self.calls.get(endpoint, 0)
    
    def get_total_calls(self) -> int:
        """Get total API calls"""
        return sum(self.calls.values())
    
    def reset(self):
        """Reset counters"""
        self.calls.clear()
        self.last_reset = time.time()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        elapsed = time.time() - self.last_reset
        return {
            'total_calls': self.get_total_calls(),
            'calls_by_endpoint': dict(self.calls),
            'elapsed_seconds': elapsed,
            'calls_per_minute': (self.get_total_calls() / elapsed * 60) if elapsed > 0 else 0
        }
