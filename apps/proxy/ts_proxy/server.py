"""
Transport Stream (TS) Proxy Server
Handles live TS stream proxying with support for:
- Stream switching
- Buffer management
- Multiple client connections
- Connection state tracking
"""

import requests
import threading
import logging
from collections import deque
import time
from typing import Optional, Set, Deque, Dict
from apps.proxy.config import TSConfig as Config

class StreamManager:
    """Manages a connection to a TS stream"""
    
    def __init__(self, url, buffer, user_agent=None):
        self.url = url
        self.buffer = buffer
        self.running = True
        self.connected = False
        self.session = requests.Session()
        self.user_agent = user_agent or "Dispatcharr/1.0"
        self.ready_event = threading.Event()
        self.retry_count = 0
        self.max_retries = 3
        self.session.headers.update({'User-Agent': self.user_agent})
    
    def connect(self):
        """Establish connection to the stream"""
        try:
            self.retry_count += 1
            logging.info(f"Connecting to stream: {self.url} (attempt {self.retry_count}/{self.max_retries})")
            
            self.response = self.session.get(
                self.url,
                stream=True,
                timeout=10
            )
            
            if self.response.status_code != 200:
                logging.error(f"Failed to connect: HTTP {self.response.status_code}")
                return False
                
            self.connected = True
            self.ready_event.set()
            logging.info("Stream connected successfully")
            return True
            
        except Exception as e:
            logging.error(f"Connection error: {e}")
            self.connected = False
            return False
    
    def should_retry(self):
        """Check if we should retry connecting"""
        return self.retry_count < self.max_retries
    
    def fetch_chunk(self):
        """Fetch the next chunk from the stream"""
        if not self.connected or not hasattr(self, 'response'):
            return False
            
        try:
            chunk = next(self.response.iter_content(chunk_size=4096))
            if chunk:
                self.buffer.add_chunk(chunk)
                return True
        except StopIteration:
            # End of stream
            logging.warning("End of stream reached")
            self.connected = False
        except Exception as e:
            logging.error(f"Error reading from stream: {e}")
            self.connected = False
            
        return False
    
    def update_url(self, new_url):
        """Change the URL for this stream"""
        if self.url == new_url:
            return False
            
        self.url = new_url
        self.retry_count = 0
        
        # Disconnect current stream
        self.connected = False
        if hasattr(self, 'response'):
            try:
                self.response.close()
            except:
                pass
            
        # Reconnect with new URL
        return self.connect()
    
    def stop(self):
        """Stop the stream manager"""
        self.running = False
        self.connected = False
        
        # Close the response if it exists
        if hasattr(self, 'response'):
            try:
                self.response.close()
            except:
                pass

class StreamBuffer:
    """Buffer for storing stream chunks"""
    
    def __init__(self, max_length=None):
        self.buffer = []
        self.lock = threading.RLock()
        # Use config value by default, with parameter override if provided
        self.max_length = max_length if max_length is not None else Config.STREAM_BUFFER_SIZE
        self.index = 0
    
    def add_chunk(self, chunk):
        """Add a chunk to the buffer"""
        with self.lock:
            self.buffer.append(chunk)
            self.index += 1
            
            # Prevent buffer from growing too large
            if len(self.buffer) > self.max_length:
                # Remove oldest chunks
                self.buffer = self.buffer[-self.max_length:]
    
    def get_chunks(self, start_pos=0):
        """Get chunks starting from position"""
        with self.lock:
            if start_pos >= len(self.buffer):
                return []
            return self.buffer[start_pos:]

class SharedStreamBuffer:
    """Buffer that uses Redis as the primary storage with minimal local caching"""
    
    def __init__(self, channel_id, redis_client=None, max_length=None):
        from apps.proxy.config import TSConfig as Config
        self.channel_id = channel_id
        self.redis_client = redis_client
        self.max_length = max_length or Config.STREAM_BUFFER_SIZE
        self.lock = threading.RLock()
        self.local_index = 0
        
        # Only keep a small local cache for the most recent chunks
        self.local_cache_size = 10  
        self.local_cache = {}  # Index -> chunk mapping
        
        # For statistics
        self.chunks_stored = 0
        self.chunks_retrieved = 0
        
        # Track if Redis is working
        self.redis_available = False
        if self.redis_client:
            try:
                self.redis_client.ping()
                self.redis_available = True
                logging.debug(f"Redis available for SharedStreamBuffer {channel_id}")
            except Exception as e:
                logging.error(f"Redis ping failed in SharedStreamBuffer: {e}")
        
        logging.debug(f"SharedStreamBuffer initialized for {channel_id}")
    
    def add_chunk(self, chunk):
        """Add a chunk to shared Redis buffer"""
        try:
            # Always store in local cache
            with self.lock:
                self.local_index += 1
                index = self.local_index
                self.local_cache[index] = chunk
                
                # Keep local cache within size limit
                if len(self.local_cache) > self.local_cache_size:
                    oldest = min(self.local_cache.keys())
                    del self.local_cache[oldest]
            
            self.chunks_stored += 1
            
            # Also try to store in Redis if available
            if self.redis_available and self.redis_client:
                try:
                    # Use channel-specific index key
                    index_key = f"ts_proxy:buffer:{self.channel_id}:index"
                    chunk_key_prefix = f"ts_proxy:buffer:{self.channel_id}:chunk:"
                    
                    # Store the chunk first
                    chunk_key = f"{chunk_key_prefix}{index}"
                    self.redis_client.setex(chunk_key, 30, chunk)
                    
                    # Then update the index atomically
                    self.redis_client.set(index_key, str(index))
                    
                    # Log periodic progress
                    if index % 50 == 0:
                        logging.info(f"Stored chunk {index} for channel {self.channel_id} in Redis (size: {len(chunk)} bytes)")
                    
                    # Clean up old chunks
                    if index > self.max_length:
                        old_index = index - self.max_length
                        self.redis_client.delete(f"{chunk_key_prefix}{old_index}")
                    
                    return True
                except Exception as e:
                    logging.warning(f"Failed to store chunk in Redis: {e}")
                    self.redis_available = False
            
            return True
        except Exception as e:
            logging.error(f"Error adding chunk to buffer: {e}")
            return False
    
    def get_chunks(self, start_index=None):
        """Get chunks starting from given index"""
        try:
            # First, check if Redis has any data for this channel
            if self.redis_available and self.redis_client:
                try:
                    # Get current index from Redis
                    index_key = f"ts_proxy:buffer:{self.channel_id}:index"
                    current_index_raw = self.redis_client.get(index_key)
                    
                    if not current_index_raw:
                        logging.debug(f"No index found in Redis for channel {self.channel_id}")
                        return []
                    
                    # Convert to integer
                    current_index = int(current_index_raw.decode('utf-8') if isinstance(current_index_raw, bytes) else current_index_raw)
                    
                    # If no start_index provided, use a relative starting point
                    if start_index is None or start_index == 0:
                        # Start from the newest chunk minus 50 chunks (or from 1 if less than 50)
                        # This ensures a new client gets some recent data without trying to load everything
                        start_index = max(1, current_index - 50)
                        logging.debug(f"No start_index provided, starting from {start_index} (current: {current_index})")
                    
                    # Nothing new to fetch
                    if start_index > current_index:
                        return []
                    
                    # Determine range to fetch (limited batch size)
                    fetch_start = max(1, start_index)
                    fetch_end = min(current_index + 1, fetch_start + 100)  # Get up to 100 chunks at once
                    
                    # Fetch chunks from Redis
                    redis_chunks = []
                    for idx in range(fetch_start, fetch_end):
                        chunk_key = f"ts_proxy:buffer:{self.channel_id}:chunk:{idx}"
                        chunk = self.redis_client.get(chunk_key)
                        if chunk:
                            redis_chunks.append(chunk)
                    
                    # Update local tracking
                    if redis_chunks:
                        with self.lock:
                            self.local_index = fetch_end
                            self.chunks_retrieved += len(redis_chunks)
                        
                        # Log chunk retrieval only for significant retrievals
                        if len(redis_chunks) > 5:
                            logging.info(f"Retrieved {len(redis_chunks)} chunks from Redis for {self.channel_id} ({fetch_start}-{fetch_end-1})")
                    
                    return redis_chunks
                
                except Exception as e:
                    logging.warning(f"Failed to get chunks from Redis: {e}")
                    self.redis_available = False
            
            # If we get here, Redis failed or we're using local only
            # Fetch from local cache
            with self.lock:
                if not self.local_cache:
                    return []
                    
                if start_index is None:
                    start_index = min(self.local_cache.keys())
                    
                cache_keys = sorted([k for k in self.local_cache.keys() if k >= start_index])
                return [self.local_cache[k] for k in cache_keys]
                    
        except Exception as e:
            logging.error(f"Error in get_chunks: {e}")
            return []

    def get_stats(self):
        """Get buffer statistics"""
        return {
            'stored': self.chunks_stored,
            'retrieved': self.chunks_retrieved,
            'channel': self.channel_id,
            'local_index': self.local_index
        }

class ClientManager:
    def __init__(self, channel_id=None):
        self.active_clients = {}
        self.cleanup_timer = None
        self.lock = threading.RLock()
        self.channel_id = channel_id  # Store channel ID for cleanup
        
    def add_client(self, client_id):
        with self.lock:
            self.active_clients[client_id] = time.time()
            # Cancel any pending cleanup
            if self.cleanup_timer:
                self.cleanup_timer.cancel()
                self.cleanup_timer = None
    
    def remove_client(self, client_id):
        with self.lock:
            if client_id in self.active_clients:
                del self.active_clients[client_id]
                logging.info(f"Client disconnected: {client_id} (remaining: {len(self.active_clients)})")
                
            # Start cleanup timer if this was the last client
            if not self.active_clients:
                self.schedule_cleanup()
    
    def schedule_cleanup(self):
        """Schedule cleanup if no clients reconnect within the grace period"""
        if self.cleanup_timer:
            return
            
        # Get cleanup delay from config
        cleanup_delay = getattr(Config, 'STREAM_CLEANUP_DELAY', 0)
        
        if cleanup_delay <= 0:
            # Immediate cleanup
            logging.info("No clients connected, cleaning up immediately")
            self.trigger_cleanup()
        else:
            # Delayed cleanup
            self.cleanup_timer = threading.Timer(cleanup_delay, self.trigger_cleanup)
            self.cleanup_timer.daemon = True
            self.cleanup_timer.start()
            logging.info(f"Scheduled stream cleanup in {cleanup_delay} seconds if no new clients connect")
    
    def trigger_cleanup(self):
        """Trigger actual cleanup if still no clients"""
        with self.lock:
            if not self.active_clients:
                logging.info("No clients, triggering stream shutdown")
                # Import cleanup function to avoid circular import
                from apps.proxy.ts_proxy.views import cleanup_channel
                
                # Use the stored channel_id
                if self.channel_id:
                    cleanup_channel(self.channel_id)
            self.cleanup_timer = None

class StreamFetcher:
    """Handles stream data fetching"""
    
    def __init__(self, manager: StreamManager, buffer: StreamBuffer):
        self.manager = manager
        self.buffer = buffer

    def fetch_loop(self) -> None:
        """Main fetch loop for stream data"""
        while self.manager.running:
            try:
                if not self._handle_connection():
                    continue

                with self.manager.session.get(self.manager.current_url, stream=True) as response:
                    if response.status_code == 200:
                        self._handle_successful_connection()
                        self._process_stream(response)

            except requests.exceptions.RequestException as e:
                self._handle_connection_error(e)

    def _handle_connection(self) -> bool:
        """Handle connection state and retries"""
        if not self.manager.connected:
            if not self.manager.should_retry():
                logging.error(f"Failed to connect after {Config.MAX_RETRIES} attempts")
                return False
            
            if not self.manager.running:
                return False
                
            self.manager.retry_count += 1
            logging.info(f"Connecting to stream: {self.manager.current_url} "
                        f"(attempt {self.manager.retry_count}/{Config.MAX_RETRIES})")
        return True

    def _handle_successful_connection(self) -> None:
        """Handle successful stream connection"""
        if not self.manager.connected:
            logging.info("Stream connected successfully")
            self.manager.connected = True
            self.manager.retry_count = 0

    def _process_stream(self, response: requests.Response) -> None:
        """Process incoming stream data"""
        for chunk in response.iter_content(chunk_size=Config.CHUNK_SIZE):
            if not self.manager.running:
                logging.info("Stream fetch stopped - shutting down")
                return
                
            if chunk:
                if self.manager.url_changed.is_set():
                    logging.info("Stream switch in progress, closing connection")
                    self.manager.url_changed.clear()
                    break
                    
                with self.buffer.lock:
                    self.buffer.buffer.append(chunk)
                    self.buffer.index += 1

    def _handle_connection_error(self, error: Exception) -> None:
        """Handle stream connection errors"""
        logging.error(f"Stream connection error: {error}")
        self.manager.connected = False
        
        if not self.manager.running:
            return
            
        logging.info(f"Attempting to reconnect in {Config.RECONNECT_DELAY} seconds...")
        if not wait_for_running(self.manager, Config.RECONNECT_DELAY):
            return

def wait_for_running(manager: StreamManager, delay: float) -> bool:
    """Wait while checking manager running state"""
    start = time.time()
    while time.time() - start < delay:
        if not manager.running:
            return False
        threading.Event().wait(0.1)
    return True

class ProxyServer:
    """Manages TS proxy server instance"""
    
    def __init__(self, user_agent=None, redis_client=None):
        self.stream_managers = {}
        self.stream_buffers = {}
        self.client_managers = {}
        self.fetch_threads = {}
        self.user_agent = user_agent or "Dispatcharr/1.0"
        self.lock = threading.RLock()
        self.redis_client = redis_client  # Store Redis client reference
    
    def initialize_channel(self, url, channel_id, shared_buffer=None):
        """Initialize a new channel with the given URL"""
        with self.lock:
            # Always use SharedStreamBuffer with Redis client
            if shared_buffer:
                self.stream_buffers[channel_id] = shared_buffer
            else:
                # Create a proper SharedStreamBuffer (not a regular StreamBuffer)
                from apps.proxy.config import TSConfig as Config
                self.stream_buffers[channel_id] = SharedStreamBuffer(
                    channel_id, 
                    redis_client=self.redis_client,
                    max_length=Config.STREAM_BUFFER_SIZE
                )
            
            # Create stream manager with the shared buffer
            self.stream_managers[channel_id] = StreamManager(
                url, 
                self.stream_buffers[channel_id],
                user_agent=self.user_agent
            )
            
            # Initialize client manager
            self.client_managers[channel_id] = ClientManager(channel_id=channel_id)
            
            # Start fetch thread
            thread = threading.Thread(
                target=self._fetch_stream,
                args=(self.stream_managers[channel_id], channel_id),
                daemon=True
            )
            self.fetch_threads[channel_id] = thread
            thread.start()
            
            logging.info(f"Initialized channel {channel_id} with URL {url}")

    def _fetch_stream(self, manager, channel_id):
        """Internal method to continuously fetch from a stream"""
        try:
            # Connect to the stream
            if not manager.connect():
                logging.error(f"Failed to connect to stream for channel {channel_id}")
                return
                
            # Continue fetching until stopped
            last_heartbeat = 0
            import os
            worker_id = str(os.getpid())
            
            while manager.running:
                try:
                    current_time = time.time()
                    
                    # Fetch next chunk of data
                    fetched = manager.fetch_chunk()
                    
                    # Update heartbeat in Redis every 15 seconds
                    if current_time - last_heartbeat >= 15:
                        try:
                            # Update active channel status with worker ID and extend TTL
                            if self.redis_client:
                                # Store additional metadata about this channel
                                pipe = self.redis_client.pipeline()
                                pipe.set(f"ts_proxy:active_channel:{channel_id}", worker_id, ex=60)
                                pipe.set(f"ts_proxy:channel_owner:{channel_id}", worker_id)
                                pipe.execute()
                                last_heartbeat = current_time
                        except Exception as e:
                            logging.warning(f"Failed to update stream heartbeat: {e}")
                    
                    # If no data fetched, small sleep to prevent tight loop
                    if not fetched:
                        time.sleep(0.05)
                    
                except Exception as e:
                    if manager.running:
                        logging.error(f"Error fetching from stream: {e}")
                        
                        # If we lose connection but are still supposed to be running,
                        # try to reconnect after a short delay
                        if not manager.connected:
                            time.sleep(2)
                            manager.connect()
            
            logging.info(f"Stream manager for {channel_id} stopped")
            
        except Exception as e:
            logging.error(f"Fetch thread error: {e}")
        finally:
            # Make sure we're marked as disconnected when thread ends
            manager.connected = False
            logging.info(f"Fetch thread for channel {channel_id} exited")

    def stop_channel(self, channel_id):
        """Stop a channel and clean up resources"""
        with self.lock:
            if channel_id in self.stream_managers:
                try:
                    # Stop the stream manager
                    manager = self.stream_managers[channel_id]
                    manager.stop()
                    
                    # Wait for thread to end gracefully
                    if channel_id in self.fetch_threads:
                        thread = self.fetch_threads[channel_id]
                        if thread and thread.is_alive():
                            thread.join(timeout=2.0)  # Wait up to 2 seconds
                    
                    # Clean up all resources
                    self.stream_managers.pop(channel_id, None)
                    self.stream_buffers.pop(channel_id, None)
                    
                    # Handle client manager cleanup
                    if channel_id in self.client_managers:
                        client_manager = self.client_managers[channel_id]
                        # Cancel any cleanup timer
                        if client_manager.cleanup_timer:
                            client_manager.cleanup_timer.cancel()
                        self.client_managers.pop(channel_id, None)
                        
                    self.fetch_threads.pop(channel_id, None)
                    
                    logging.info(f"Channel {channel_id} stopped and resources released")
                    return True
                except Exception as e:
                    logging.error(f"Error stopping channel {channel_id}: {e}")
            return False

    def _cleanup_channel(self, channel_id: str) -> None:
        """Remove channel resources"""
        for collection in [self.stream_managers, self.stream_buffers, 
                         self.client_managers, self.fetch_threads]:
            collection.pop(channel_id, None)

    def shutdown(self) -> None:
        """Stop all channels and cleanup"""
        for channel_id in list(self.stream_managers.keys()):
            self.stop_channel(channel_id)
