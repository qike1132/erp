import sys
sys.path.insert(0, '.')
from utils.redis_cache import redis_cache
import asyncio

async def check():
    # 检查 Redis 连接
    if redis_cache.redis_client:
        print("Redis connected")
        keys = await redis_cache.redis_client.scan(match='erp:*pp:*', count=100)
        print('Redis pp keys count:', len(keys[1]))
        for k in keys[1][:10]:
            print(k)
        keys2 = await redis_cache.redis_client.scan(match='erp:*plan_fifo:*', count=100)
        print('Redis plan_fifo keys count:', len(keys2[1]))
        for k in keys2[1][:10]:
            print(k)
    else:
        print("Redis NOT connected, using fallback cache")
        print("Fallback cache keys:", list(redis_cache._fallback_cache.keys())[:20])

asyncio.run(check())
