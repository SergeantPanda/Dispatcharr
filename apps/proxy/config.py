"""Shared configuration between proxy types"""

class BaseConfig:
    DEFAULT_USER_AGENT = 'VLC/3.0.20 LibVLC/3.0.20'
    CHUNK_SIZE = 8192
    CLIENT_POLL_INTERVAL = 0.1
    MAX_RETRIES = 3

class HLSConfig(BaseConfig):
    MIN_SEGMENTS = 12
    MAX_SEGMENTS = 16
    WINDOW_SIZE = 12
    INITIAL_SEGMENTS = 3
    INITIAL_CONNECTION_WINDOW = 10
    CLIENT_TIMEOUT_FACTOR = 1.5
    CLIENT_CLEANUP_INTERVAL = 10
    FIRST_SEGMENT_TIMEOUT = 5.0
    INITIAL_BUFFER_SECONDS = 25.0
    MAX_INITIAL_SEGMENTS = 10
    BUFFER_READY_TIMEOUT = 30.0

class TSConfig(BaseConfig):
    """Configuration for TS Proxy"""
    DEFAULT_USER_AGENT = "Dispatcharr/1.0"
    CONNECTION_TIMEOUT = 15
    MAX_RETRIES = 3
    STREAM_BUFFER_SIZE = 1000
    
    # Stream cleanup delay in seconds (0 for immediate)
    # How long to wait after all clients disconnect before cleaning up the stream
    STREAM_CLEANUP_DELAY = 0
    
    # Set to True to enable verbose debug logging
    DEBUG_LOGGING = False
    
    # Redis settings
    REDIS_CHUNK_TTL = 30  # How long to keep chunks in Redis (seconds)
    REDIS_HEARTBEAT_INTERVAL = 15  # How often to update Redis heartbeat
    REDIS_ACTIVE_TTL = 60  # TTL for active channel markers (seconds)
    
    # Local cache settings
    LOCAL_CACHE_SIZE = 10  # Number of recent chunks to keep in memory