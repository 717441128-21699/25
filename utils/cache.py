import redis.asyncio as aioredis
import redis
from typing import Optional, Any
from config import settings
import json
import pickle
from datetime import timedelta


class RedisManager:
    _sync_client: Optional[redis.Redis] = None
    _async_client: Optional[aioredis.Redis] = None

    @classmethod
    def get_sync_client(cls) -> redis.Redis:
        if cls._sync_client is None:
            kwargs = {
                "decode_responses": True,
                "socket_connect_timeout": 5,
                "socket_timeout": 5,
                "retry_on_timeout": True,
                "max_connections": 100,
            }
            if settings.redis_password:
                kwargs["password"] = settings.redis_password
            cls._sync_client = redis.from_url(settings.redis_url, **kwargs)
        return cls._sync_client

    @classmethod
    def get_async_client(cls) -> aioredis.Redis:
        if cls._async_client is None:
            kwargs = {
                "decode_responses": True,
                "socket_connect_timeout": 5,
                "socket_timeout": 5,
                "max_connections": 100,
            }
            if settings.redis_password:
                kwargs["password"] = settings.redis_password
            cls._async_client = aioredis.from_url(settings.redis_url, **kwargs)
        return cls._async_client

    @classmethod
    async def close_async(cls):
        if cls._async_client:
            await cls._async_client.close()
            cls._async_client = None

    @classmethod
    def get(cls, key: str) -> Optional[str]:
        return cls.get_sync_client().get(key)

    @classmethod
    def set(cls, key: str, value: Any, ex: Optional[int] = None) -> bool:
        return cls.get_sync_client().set(key, value, ex=ex)

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
    async def aget(cls, key: str) -> Optional[str]:
        return await cls.get_async_client().get(key)

    @classmethod
    async def aset(cls, key: str, value: Any, ex: Optional[int] = None) -> bool:
        return await cls.get_async_client().set(key, value, ex=ex)

    @classmethod
    async def aget_json(cls, key: str) -> Optional[Any]:
        data = await cls.aget(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    @classmethod
    async def aset_json(cls, key: str, value: Any, ex: Optional[int] = None) -> bool:
        return await cls.aset(key, json.dumps(value, ensure_ascii=False, default=str), ex=ex)

    @classmethod
    def delete(cls, key: str) -> int:
        return cls.get_sync_client().delete(key)

    @classmethod
    def exists(cls, key: str) -> bool:
        return bool(cls.get_sync_client().exists(key))

    @classmethod
    def acquire_lock(cls, key: str, timeout: int = 30) -> bool:
        lock_key = f"lock:{key}"
        return bool(cls.get_sync_client().set(lock_key, "1", nx=True, ex=timeout))

    @classmethod
    def release_lock(cls, key: str) -> None:
        cls.delete(f"lock:{key}")

    @classmethod
    def incr(cls, key: str, amount: int = 1) -> int:
        return cls.get_sync_client().incr(key, amount)

    @classmethod
    def expire(cls, key: str, seconds: int) -> bool:
        return bool(cls.get_sync_client().expire(key, seconds))


redis_manager = RedisManager()
