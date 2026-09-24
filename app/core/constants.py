"""Platform-wide constants and key formats."""

# Redis Key Prefix Convention: controlhub:{feature}:{identifier}
REDIS_KEY_PREFIX = "controlhub"

# Redis key templates
REDIS_KEY_SESSION = f"{REDIS_KEY_PREFIX}:session:{{identifier}}"
REDIS_KEY_LOCK = f"{REDIS_KEY_PREFIX}:lock:{{identifier}}"
REDIS_KEY_RATE_LIMIT = f"{REDIS_KEY_PREFIX}:rate-limit:{{bot_id}}:{{user_id}}"
REDIS_KEY_VIDEO_PROCESSING = f"{REDIS_KEY_PREFIX}:video-processing:{{video_id}}"
REDIS_KEY_BROADCAST_LOCK = f"{REDIS_KEY_PREFIX}:broadcast-lock:{{broadcast_id}}"

# Header Constants
HEADER_REQUEST_ID = "X-Request-ID"
HEADER_INTERNAL_KEY = "X-Internal-Key"
HEADER_TELEGRAM_BOT_API_SECRET_TOKEN = "X-Telegram-Bot-Api-Secret-Token"
