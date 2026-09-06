import redis.asyncio


def get_redis_client(redis_url: str) -> redis.asyncio.Redis:
    return redis.asyncio.from_url(redis_url, decode_responses=False)
