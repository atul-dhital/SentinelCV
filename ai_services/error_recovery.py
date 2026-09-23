"""
Error Recovery and Resilience Module for SentinelCV AI Service.

Provides graceful error handling, automatic reconnection, and fallback mechanisms.
"""

import time
import logging
import traceback
from typing import Optional, Callable, Any, Dict
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ErrorContext:
    """Context information for an error."""
    error: Exception
    severity: ErrorSeverity
    component: str
    operation: str
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    recovery_action: Optional[str] = None


class ErrorRecoveryManager:
    """Manages error recovery and resilience for the AI service."""
    
    def __init__(self):
        self._error_history: list[ErrorContext] = []
        self._component_health: Dict[str, bool] = {}
        self._fallback_modes: Dict[str, bool] = {}
        self._max_history = 1000
        
    def record_error(self, error: Exception, component: str, operation: str, 
                     severity: ErrorSeverity = ErrorSeverity.MEDIUM) -> ErrorContext:
        """Record an error and return context."""
        context = ErrorContext(
            error=error,
            severity=severity,
            component=component,
            operation=operation,
        )
        
        self._error_history.append(context)
        if len(self._error_history) > self._max_history:
            self._error_history = self._error_history[-self._max_history:]
        
        self._component_health[component] = False
        
        logger.error(f"[ERROR] {component}.{operation}: {error}")
        
        return context
    
    def mark_healthy(self, component: str):
        """Mark a component as healthy."""
        self._component_health[component] = True
        
    def is_healthy(self, component: str) -> bool:
        """Check if a component is healthy."""
        return self._component_health.get(component, True)
    
    def enable_fallback(self, component: str):
        """Enable fallback mode for a component."""
        self._fallback_modes[component] = True
        logger.warning(f"[FALLBACK] Enabled for {component}")
        
    def disable_fallback(self, component: str):
        """Disable fallback mode for a component."""
        self._fallback_modes[component] = False
        
    def is_fallback_enabled(self, component: str) -> bool:
        """Check if fallback mode is enabled."""
        return self._fallback_modes.get(component, False)
    
    def get_error_stats(self) -> dict:
        """Get error statistics."""
        total = len(self._error_history)
        if total == 0:
            return {"total": 0, "by_severity": {}, "by_component": {}}
        
        by_severity = {}
        by_component = {}
        
        for ctx in self._error_history:
            sev = ctx.severity.value
            by_severity[sev] = by_severity.get(sev, 0) + 1
            
            by_component[ctx.component] = by_component.get(ctx.component, 0) + 1
        
        return {
            "total": total,
            "by_severity": by_severity,
            "by_component": by_component,
            "healthy_components": sum(1 for v in self._component_health.values() if v),
            "total_components": len(self._component_health),
        }


_error_manager = ErrorRecoveryManager()


def get_error_manager() -> ErrorRecoveryManager:
    """Get the global error manager instance."""
    return _error_manager


def with_retry(max_retries: int = 3, delay: float = 1.0, 
               backoff: float = 2.0, 
               exceptions: tuple = (Exception,)):
    """
    Decorator for automatic retry with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exception types to catch
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"[RETRY] {func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        _error_manager.record_error(
                            e, 
                            func.__module__, 
                            func.__name__,
                            ErrorSeverity.HIGH
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


def with_fallback(fallback_func: Callable, fallback_value: Any = None):
    """
    Decorator that provides a fallback when the main function fails.
    
    Args:
        fallback_func: Function to call when main function fails
        fallback_value: Default value to return if both fail
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"[FALLBACK] {func.__name__} failed, trying fallback: {e}")
                _error_manager.record_error(
                    e,
                    func.__module__,
                    func.__name__,
                    ErrorSeverity.MEDIUM
                )
                
                try:
                    return fallback_func(*args, **kwargs)
                except Exception as fallback_error:
                    logger.error(f"[FALLBACK] Also failed: {fallback_error}")
                    return fallback_value
        
        return wrapper
    return decorator


class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance."""
    
    def __init__(self, failure_threshold: int = 5, 
                 recovery_timeout: float = 60.0,
                 expected_exception: type = BaseException):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._state = "closed"  # closed, open, half-open
        
    @property
    def state(self) -> str:
        if self._state == "open":
            if self._last_failure_time and (time.time() - self._last_failure_time) > self.recovery_timeout:
                self._state = "half-open"
                logger.info("[CIRCUIT] State changed to half-open")
        return self._state
    
    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "open":
            raise Exception(f"Circuit breaker is open for {func.__name__}")
        
        try:
            result = func(*args, **kwargs)
            if self._state == "half-open":
                self._state = "closed"
                self._failure_count = 0
                logger.info("[CIRCUIT] Circuit breaker closed")
            return result
        except self.expected_exception as e:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._failure_count >= self.failure_threshold:
                self._state = "open"
                logger.warning(f"[CIRCUIT] Circuit breaker opened after {self._failure_count} failures")
            
            raise


class StreamReconnection:
    """Handles automatic reconnection for RTSP streams."""
    
    def __init__(self, max_retries: int = 10, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        
    def reconnect(self, connect_func: Callable, *args, **kwargs):
        """Attempt to reconnect with exponential backoff."""
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                return connect_func(*args, **kwargs)
            except Exception as e:
                last_error = e
                delay = self.base_delay * (2 ** attempt)
                logger.warning(
                    f"[RECONNECT] Attempt {attempt + 1}/{self.max_retries} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
        
        raise last_error


def graceful_degradation(func: Callable) -> Callable:
    """
    Decorator that enables graceful degradation for video processing.
    Returns partial results instead of failing completely.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_ctx = _error_manager.record_error(
                e,
                func.__module__,
                func.__name__,
                ErrorSeverity.MEDIUM
            )
            
            logger.warning(f"[GRACEFUL] {func.__name__} failed, returning degraded result: {e}")
            
            if "extract_face" in func.__name__:
                return []
            elif "get_embedding" in func.__name__:
                return None
            elif "track" in func.__name__:
                return []
            else:
                return None
    
    return wrapper


class ResourceMonitor:
    """Monitors system resources and adapts processing accordingly."""
    
    def __init__(self):
        self._cpu_usage = 0.0
        self._memory_usage = 0.0
        self._processing_mode = "normal"  # normal, low, minimal
        
    def update_stats(self, cpu: float, memory: float):
        """Update resource usage statistics."""
        self._cpu_usage = cpu
        self._memory_usage = memory
        
        if cpu > 90 or memory > 90:
            self._processing_mode = "minimal"
            logger.warning("[RESOURCE] Switching to minimal processing mode")
        elif cpu > 70 or memory > 70:
            self._processing_mode = "low"
            logger.info("[RESOURCE] Switching to low processing mode")
        else:
            self._processing_mode = "normal"
    
    @property
    def processing_mode(self) -> str:
        return self._processing_mode
    
    def get_frame_skip(self) -> int:
        """Get frame skip count based on resource usage."""
        if self._processing_mode == "minimal":
            return 5
        elif self._processing_mode == "low":
            return 3
        return 1
    
    def get_batch_size(self) -> int:
        """Get batch size based on resource usage."""
        if self._processing_mode == "minimal":
            return 1
        elif self._processing_mode == "low":
            return 4
        return 8


_resource_monitor = ResourceMonitor()


def get_resource_monitor() -> ResourceMonitor:
    """Get the global resource monitor instance."""
    return _resource_monitor
