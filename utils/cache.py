from typing import Optional, Any
import json
import pickle
from datetime import timedelta
from config import settings
from utils.logger import get_logger

logger = get_logger("cache")

_redis_available = None


def check_redis_available() -> bool:
    global _redis_available
    if _redis_available is not None:
        return _redis_available
    try:
        import redis
        kwargs = {
            "decode_responses": True,
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
        }
        if settings.redis_password:
            kwargs["password"] = settings.redis_password
        client = redis.from_url(settings.redis_url, **kwargs)
        client.ping()
        _redis_available = True
        return True
    except Exception as e:
        logger.warning(f"Redis不可用，将使用内存缓存: {e}")
        _redis_available = False
        return False


_memory_store = {}


class RedisManager:

    @classmethod
    def get_sync_client(cls):
        try:
            import redis
            kwargs = {
                "decode_responses": True,
                "socket_connect_timeout": 2,
                "socket_timeout": 2,
            }
            if settings.redis_password:
                kwargs["password"] = settings.redis_password
            return redis.from_url(settings.redis_url, **kwargs)
        except Exception:
            return None

    @classmethod
    def get(cls, key: str) -> Optional[str]:
        try:
            if check_redis_available():
                client = cls.get_sync_client()
                if client:
                    return client.get(key)
        except Exception:
            pass
        return _memory_store.get(key)

    @classmethod
    def set(cls, key: str, value: Any, ex: Optional[int] = None) -> bool:
        try:
            if check_redis_available():
                client = cls.get_sync_client()
                if client:
                    return bool(client.set(key, value, ex=ex))
        except Exception:
            pass
        _memory_store[key] = value
        return True

    @classmethod
    def get_json(cls, key: str) -> Optional[Any]:
        data = cls.get(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    @classmethod
    def set_json(cls, key: str, value: Any, ex: Optional[int] = None) -> bool:
        return cls.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ex)

    @classmethod
    def delete(cls, key: str) -> int:
        try:
            if check_redis_available():
                client = cls.get_sync_client()
                if client:
                    return client.delete(key)
        except Exception:
            pass
        if key in _memory_store:
            del _memory_store[key]
            return 1
        return 0

    @classmethod
    def exists(cls, key: str) -> bool:
        try:
            if check_redis_available():
                client = cls.get_sync_client()
                if client:
                    return bool(client.exists(key))
        except Exception:
            pass
        return key in _memory_store

    @classmethod
    def acquire_lock(cls, key: str, timeout: int = 30) -> bool:
        try:
            if check_redis_available():
                import redis
                client = cls.get_sync_client()
                if client:
                    lock_key = f"lock:{key}"
                    return bool(client.set(lock_key, "1", nx=True, ex=timeout))
        except Exception:
            pass
        lock_key = f"lock:{key}"
        import time
        now = time.time()
        if lock_key in _memory_store and _memory_store[lock_key] > now:
            return False
        _memory_store[lock_key] = now + timeout
        return True

    @classmethod
    def release_lock(cls, key: str) -> None:
        try:
            if check_redis_available():
                cls.delete(f"lock:{key}")
                return
        except Exception:
            pass
        lock_key = f"lock:{key}"
        if lock_key in _memory_store:
            del _memory_store[lock_key]

    @classmethod
    def incr(cls, key: str, amount: int = 1) -> int:
        try:
            if check_redis_available():
                client = cls.get_sync_client()
                if client:
                    return client.incr(key, amount)
        except Exception:
            pass
        current = int(_memory_store.get(key, 0))
        _memory_store[key] = current + amount
        return _memory_store[key]

    @classmethod
    def expire(cls, key: str, seconds: int) -> bool:
        try:
            if check_redis_available():
                client = cls.get_sync_client()
                if client:
                    return bool(client.expire(key, seconds))
        except Exception:
            pass
        return True


redis_manager = RedisManager()
