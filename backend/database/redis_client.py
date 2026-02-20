import os
import json
import redis
from redis.exceptions import ConnectionError
from typing import List, Optional, Dict

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))

# Initialize Redis client with fallback
print(f"DEBUG: RedisClient connecting to {redis_host}:{redis_port}")
try:
    r = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)
    r.ping() # Test connection immediately
    print("DEBUG: Redis connection successful.")
except ConnectionError:
    print("WARNING: Redis connection failed. Falling back to in-memory storage.")
    r = None

class RedisClient:
    _memory_store = {}

    @staticmethod
    def get_chat_history(conv_id: str) -> List[Dict]:
        """Retrieve full chat history from Redis or memory."""
        key = f"chat:{conv_id}:messages"
        if r:
            try:
                raw_msgs = r.lrange(key, 0, -1)
                return [json.loads(m) for m in raw_msgs]
            except ConnectionError:
                pass # Fallback if connection drops later
        
        # Fallback
        return RedisClient._memory_store.get(key, [])

    @staticmethod
    def add_message(conv_id: str, message: Dict):
        """Append a message to the chat history."""
        key = f"chat:{conv_id}:messages"
        if r:
            try:
                r.rpush(key, json.dumps(message))
                # Set expiry to 24 hours (86400 seconds)
                r.expire(key, 86400)
                return
            except ConnectionError:
                pass
        
        # Fallback
        if key not in RedisClient._memory_store:
            RedisClient._memory_store[key] = []
        RedisClient._memory_store[key].append(message)

    @staticmethod
    def save_resume_context(conv_id: str, context: Dict):
        """Save parsed resume info."""
        key = f"chat:{conv_id}:resume"
        if r:
            try:
                r.set(key, json.dumps(context), ex=86400)
                return
            except ConnectionError:
                pass

        # Fallback
        RedisClient._memory_store[key] = context

    @staticmethod
    def get_resume_context(conv_id: str) -> Optional[Dict]:
        """Retrieve parsed resume info."""
        key = f"chat:{conv_id}:resume"
        if r:
            try:
                data = r.get(key)
                return json.loads(data) if data else None
            except ConnectionError:
                pass

        # Fallback
        return RedisClient._memory_store.get(key)

    @staticmethod
    def save_job_context(conv_id: str, context: List[Dict]):
        """Save recommended jobs."""
        key = f"chat:{conv_id}:jobs"
        if r:
            try:
                r.set(key, json.dumps(context), ex=86400)
                return
            except ConnectionError:
                pass

        # Fallback
        RedisClient._memory_store[key] = context

    @staticmethod
    def get_job_context(conv_id: str) -> Optional[List[Dict]]:
        """Retrieve recommended jobs."""
        key = f"chat:{conv_id}:jobs"
        if r:
            try:
                data = r.get(key)
                return json.loads(data) if data else None
            except ConnectionError:
                pass

        # Fallback
        return RedisClient._memory_store.get(key)

    @staticmethod
    def clear_conversation(conv_id: str):
        """Clear chat, resume, and job data for a conversation."""
        keys = [f"chat:{conv_id}:messages", f"chat:{conv_id}:resume", f"chat:{conv_id}:jobs"]
        if r:
            try:
                for k in keys:
                    r.delete(k)
                return
            except ConnectionError:
                pass
        
        # Fallback
        for k in keys:
            if k in RedisClient._memory_store:
                del RedisClient._memory_store[k]
