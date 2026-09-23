"""
Redis Caching Layer for SentinelCV

Implements intelligent caching strategies for:
- Face embeddings and recognition results
- Visitor metadata and search results
- Analytics aggregations
- Configuration data
- Session management
"""

import redis
import json
import hashlib
from typing import Any, Optional, Callable, Dict
from functools import wraps
from datetime import datetime, timedelta
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class RedisCache:
    """Thread-safe Redis caching utility for SentinelCV."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0", default_ttl: int = 300):
        """Initialize Redis cache connection.
        
        Args:
            redis_url: Redis connection URL
            default_ttl: Default time-to-live in seconds (5 minutes)
        """
        try:
            self.client = redis.from_url(redis_url, decode_responses=True)
            self.client.ping()
            self.default_ttl = default_ttl
            logger.info(f"Redis cache initialized: {redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.client = None
    
    def is_connected(self) -> bool:
        """Check if Redis is connected and healthy."""
        try:
            return self.client is not None and self.client.ping()
        except Exception:
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        if not self.client:
            return None
        try:
            value = self.client.get(key)
            if value:
                logger.debug(f"Cache HIT: {key}")
                # Try to deserialize JSON
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache get error for {key}: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized if dict/list)
            ttl: Time-to-live in seconds (uses default if None)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.client:
            return False
        try:
            ttl = ttl or self.default_ttl
            # Serialize complex types to JSON
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            self.client.setex(key, ttl, value)
            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Cache set error for {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if deleted, False otherwise
        """
        if not self.client:
            return False
        try:
            result = self.client.delete(key) > 0
            if result:
                logger.debug(f"Cache DELETE: {key}")
            return result
        except Exception as e:
            logger.error(f"Cache delete error for {key}: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists in cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if exists, False otherwise
        """
        if not self.client:
            return False
        try:
            return self.client.exists(key) > 0
        except Exception as e:
            logger.error(f"Cache exists error for {key}: {e}")
            return False
    
    def flush(self, pattern: Optional[str] = None) -> int:
        """Flush cache entries.
        
        Args:
            pattern: Glob pattern to match keys (e.g., 'visitor:*'). If None, flushes entire DB.
            
        Returns:
            Number of keys deleted
        """
        if not self.client:
            return 0
        try:
            if pattern:
                keys = self.client.keys(pattern)
                if keys:
                    deleted = self.client.delete(*keys)
                    logger.info(f"Cache FLUSH: {deleted} keys matching '{pattern}'")
                    return deleted
                return 0
            else:
                self.client.flushdb()
                logger.info("Cache FLUSH: Database cleared")
                return -1
        except Exception as e:
            logger.error(f"Cache flush error: {e}")
            return 0
    
    def incr(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> Optional[int]:
        """Increment counter in cache.
        
        Args:
            key: Cache key
            amount: Amount to increment by
            ttl: Time-to-live for new keys
            
        Returns:
            New value or None on error
        """
        if not self.client:
            return None
        try:
            value = self.client.incrby(key, amount)
            if ttl and self.client.ttl(key) == -1:
                self.client.expire(key, ttl)
            return value
        except Exception as e:
            logger.error(f"Cache incr error for {key}: {e}")
            return None
    
    def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on existing key.
        
        Args:
            key: Cache key
            ttl: Time-to-live in seconds
            
        Returns:
            True if successful, False otherwise
        """
        if not self.client:
            return False
        try:
            return self.client.expire(key, ttl)
        except Exception as e:
            logger.error(f"Cache expire error for {key}: {e}")
            return False


# ─── Cache Key Generators ──────────────────────────────────────────────────────


def make_visitor_cache_key(visitor_id: str, org_id: str) -> str:
    """Generate cache key for visitor data."""
    return f"visitor:{org_id}:{visitor_id}"


def make_embedding_cache_key(face_data_id: str, org_id: str) -> str:
    """Generate cache key for face embedding."""
    return f"embedding:{org_id}:{face_data_id}"


def make_search_cache_key(query_hash: str, org_id: str, limit: int, offset: int) -> str:
    """Generate cache key for search results."""
    return f"search:{org_id}:{query_hash}:{limit}:{offset}"


def make_stats_cache_key(org_id: str, stat_type: str, time_window: str) -> str:
    """Generate cache key for statistics."""
    return f"stats:{org_id}:{stat_type}:{time_window}"


def make_config_cache_key(org_id: str, config_type: str) -> str:
    """Generate cache key for configuration."""
    return f"config:{org_id}:{config_type}"


# ─── Caching Decorators ────────────────────────────────────────────────────────


def cache_result(key_func: Callable, ttl: int = 300):
    """Decorator for caching function results.
    
    Args:
        key_func: Function that generates cache key from function arguments
        ttl: Time-to-live in seconds
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            try:
                cache_key = key_func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Failed to generate cache key: {e}")
                return func(*args, **kwargs)
            
            # Try to get from cache
            cache = RedisCache()
            if cache.is_connected():
                cached = cache.get(cache_key)
                if cached is not None:
                    return cached
            
            # Call function and cache result
            result = func(*args, **kwargs)
            if cache.is_connected() and result is not None:
                cache.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator


# ─── Context Managers ──────────────────────────────────────────────────────────


@contextmanager
def cache_invalidation_scope(patterns: list[str]):
    """Context manager for batch cache invalidation.
    
    Usage:
        with cache_invalidation_scope(['visitor:*', 'stats:*']):
            # ...do operations that change data...
            # Patterns will be invalidated after context exit
    """
    try:
        yield
    finally:
        cache = RedisCache()
        if cache.is_connected():
            for pattern in patterns:
                cache.flush(pattern)
                logger.info(f"Invalidated cache pattern: {pattern}")


# ─── Analytics Cache Helpers ────────────────────────────────────────────────────


class AnalyticsCacheManager:
    """Manages caching for analytics and aggregated metrics."""
    
    def __init__(self, cache: RedisCache):
        self.cache = cache
    
    def get_visitor_stats(self, org_id: str, time_window: str = "24h") -> Optional[Dict]:
        """Get cached visitor statistics.
        
        Args:
            org_id: Organization ID
            time_window: Time window ('24h', '7d', '30d', 'all')
            
        Returns:
            Cached stats or None
        """
        key = make_stats_cache_key(org_id, "visitor_count", time_window)
        return self.cache.get(key)
    
    def set_visitor_stats(self, org_id: str, stats: Dict, time_window: str = "24h", ttl: int = 3600):
        """Cache visitor statistics.
        
        Args:
            org_id: Organization ID
            stats: Statistics dictionary
            time_window: Time window
            ttl: Cache time-to-live
        """
        key = make_stats_cache_key(org_id, "visitor_count", time_window)
        self.cache.set(key, stats, ttl)
    
    def invalidate_org_analytics(self, org_id: str) -> int:
        """Invalidate all analytics for organization.
        
        Args:
            org_id: Organization ID
            
        Returns:
            Number of keys deleted
        """
        return self.cache.flush(f"stats:{org_id}:*")


# ─── Distributed Lock for Concurrent Operations ──────────────────────────────


class DistributedLock:
    """Simple distributed lock using Redis."""
    
    def __init__(self, cache: RedisCache, lock_key: str, ttl: int = 30):
        self.cache = cache
        self.lock_key = lock_key
        self.ttl = ttl
        self.token = None
    
    def acquire(self) -> bool:
        """Try to acquire lock."""
        if not self.cache.is_connected():
            return True  # Proceed without lock if Redis unavailable
        
        # Generate unique token
        self.token = hashlib.sha256(
            f"{datetime.now().isoformat()}".encode()
        ).hexdigest()
        
        # Try to set key if not exists
        try:
            result = self.cache.client.set(
                self.lock_key,
                self.token,
                nx=True,
                ex=self.ttl
            )
            return result is not None
        except Exception as e:
            logger.error(f"Failed to acquire lock {self.lock_key}: {e}")
            return False
    
    def release(self) -> bool:
        """Release lock if we own it."""
        if not self.cache.is_connected() or not self.token:
            return True
        
        try:
            # Only delete if token matches (prevent releasing others' locks)
            current_token = self.cache.client.get(self.lock_key)
            if current_token == self.token:
                self.cache.client.delete(self.lock_key)
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to release lock {self.lock_key}: {e}")
            return False
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


# ─── Global Cache Instance ─────────────────────────────────────────────────────

# Initialize global cache instance
_cache_instance: Optional[RedisCache] = None


def get_cache() -> RedisCache:
    """Get or initialize global cache instance."""
    global _cache_instance
    if _cache_instance is None:
        import os
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _cache_instance = RedisCache(redis_url)
    return _cache_instance
