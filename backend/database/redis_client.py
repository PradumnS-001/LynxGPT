import os
import json
import redis
from typing import List, Optional, Dict

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))

# Initialize Redis client
print(f"DEBUG: RedisClient connecting to {redis_host}:{redis_port}")
r = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)

class RedisClient:
    @staticmethod
    def get_chat_history(conv_id: str) -> List[Dict]:
        """Retrieve full chat history from Redis."""
        key = f"chat:{conv_id}:messages"
        raw_msgs = r.lrange(key, 0, -1)
        return [json.loads(m) for m in raw_msgs]

    @staticmethod
    def add_message(conv_id: str, message: Dict):
        """Append a message to the chat history."""
        key = f"chat:{conv_id}:messages"
        r.rpush(key, json.dumps(message))
        # Set expiry to 24 hours (86400 seconds) to avoid infinite growth if not flushed
        r.expire(key, 86400)

    @staticmethod
    def save_resume_context(conv_id: str, context: Dict):
        """Save parsed resume info."""
        key = f"chat:{conv_id}:resume"
        r.set(key, json.dumps(context), ex=86400)

    @staticmethod
    def get_resume_context(conv_id: str) -> Optional[Dict]:
        """Retrieve parsed resume info."""
        key = f"chat:{conv_id}:resume"
        data = r.get(key)
        return json.loads(data) if data else None

    @staticmethod
    def clear_conversation(conv_id: str):
        """Clear chat and resume data for a conversation."""
        r.delete(f"chat:{conv_id}:messages")
        r.delete(f"chat:{conv_id}:resume")
