"""Shared configuration between proxy types"""

class BaseConfig:
    # User agent sent in HTTP requests to source streams
    # Using a common player agent can help avoid blocks by some providers
    DEFAULT_USER_AGENT = 'VLC/3.0.20 LibVLC/3.0.20'
    
    # Size of data chunks to read from source (bytes)
    # Affects memory usage and network efficiency
    CHUNK_SIZE = 8192
    
    # How often to check for client activity (seconds)
    # Lower values improve responsiveness but use more CPU
    CLIENT_POLL_INTERVAL = 0.1
    
    # Number of connection attempts before failing
    # Balances reliability with preventing excessive reconnection attempts
    MAX_RETRIES = 3

class HLSConfig(BaseConfig):
    # Minimum segments to keep in buffer
    MIN_SEGMENTS = 12
    
    # Maximum segments to store in memory
    MAX_SEGMENTS = 16
    
    # Number of segments in a sliding window
    WINDOW_SIZE = 12
    
    # Segments to load immediately when stream starts
    INITIAL_SEGMENTS = 3
    
    # Window size for initial connection phase (seconds)
    INITIAL_CONNECTION_WINDOW = 10
    
    # Multiplier for client timeout calculation
    CLIENT_TIMEOUT_FACTOR = 1.5
    
    # Interval between client cleanup checks (seconds)
    CLIENT_CLEANUP_INTERVAL = 10
    
    # Timeout for receiving first segment (seconds)
    # Critical for determining initial connection success
    FIRST_SEGMENT_TIMEOUT = 5.0
    
    # How much buffer to build before playback starts (seconds)
    INITIAL_BUFFER_SECONDS = 25.0
    
    # Cap on initial segments to prevent excessive buffering
    MAX_INITIAL_SEGMENTS = 10
    
    # Maximum time to wait for buffer to be ready (seconds)
    BUFFER_READY_TIMEOUT = 30.0

class TSConfig(BaseConfig):
    """Configuration for TS Proxy"""
    # Override base class values if needed
    #DEFAULT_USER_AGENT = 'VLC/3.0.20 LibVLC/3.0.20'
    
    # Timeout for upstream server connections (seconds)
    # Prevents hanging when source servers are unreachable
    CONNECTION_TIMEOUT = 15
    
    #MAX_RETRIES = 3
    
    # Stream settings
    # Maximum number of chunks to keep per stream
    # Higher values use more memory but provide smoother playback
    STREAM_BUFFER_SIZE = 5000
    
    # Time to wait before cleaning up a stream after clients disconnect (seconds)
    # Zero means immediate cleanup when no clients are connected
    STREAM_CLEANUP_DELAY = 0
    
    # Client connection settings
    # How many chunks back from the latest to start new clients
    # Larger value = more initial buffering, smoother playback but higher latency
    # Value of 500 chunks equals approximately 4MB of initial data
    CLIENT_START_BUFFER_SIZE = 1000
    
    # Maximum bytes to send in initial data burst to clients
    # Helps quickly fill client's buffer for smooth start
    CLIENT_INITIAL_BURST_SIZE = 1024_000  # 1024KB
    
    # Redis settings
    # How long to keep chunks in Redis before they expire (seconds)
    # Should be longer than heartbeat interval to prevent premature expiration
    REDIS_CHUNK_TTL = 60
    
    # How often to update Redis heartbeat for active streams (seconds)
    # Used to detect if a stream process is still running
    REDIS_HEARTBEAT_INTERVAL = 15
    
    # TTL for Redis keys that track active channels (seconds)
    # Should be at least 2-3x the heartbeat interval for reliable failure detection
    REDIS_ACTIVE_TTL = 60
    
    # Local cache settings
    # Number of recent chunks to keep in local worker memory
    # Higher values reduce Redis load but use more RAM per worker
    LOCAL_CACHE_SIZE = 1000
    
    # How long to wait for a missing chunk before skipping
    MISSING_CHUNK_MAX_WAIT = 2.0
    
    # Maximum empty reads before terminating stream
    MAX_EMPTY_READS = 100
    
    # How many recent chunks to check when skipping missing ones
    SKIP_CHUNK_SEARCH_RANGE = 50
    
    # Don't log every missing chunk, only significant ones
    LOG_MISSING_CHUNK_THRESHOLD = 20