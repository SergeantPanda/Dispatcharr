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
from urllib.parse import urlparse
import socket
import ssl

class StreamManager:
    """Manages a connection to a TS stream"""
    
    def __init__(self, url, buffer, user_agent=None):
        self.url = url
        self.buffer = buffer
        self.running = True
        self.connected = False
        self.session = requests.Session()
        self.user_agent = user_agent or Config.DEFAULT_USER_AGENT or "VLC/3.0.20 LibVLC/3.0.20"
        self.ready_event = threading.Event()
        self.retry_count = 0
        self.max_retries = 3
        self.session.headers.update({
            'User-Agent': self.user_agent,
            'Accept': '*/*',
            'Connection': 'keep-alive',
            'Accept-Encoding': 'identity',  # Important: don't request compression
            'Accept-Language': 'en_US',     # Match VLC defaults
            'Cache-Control': 'no-cache'     # Don't cache responses
        })
        # Track empty response attempts
        self.empty_response_count = 0
        self.max_empty_responses = 5
        self.min_data_size = 188  # Minimum size for valid TS packet
        self.socket = None
        self.recv_buffer = b''
        # TS packet handling
        self.TS_PACKET_SIZE = 188
        self.recv_buffer = bytearray()
        self.continuity_counters = {}  # Track continuity for each PID
        self.sync_found = False
        
    def connect(self):
        """Connect using direct socket with support for HTTP redirects"""
        try:
            self.retry_count += 1
            logging.info(f"Connecting to stream: {self.url} (attempt {self.retry_count}/{self.max_retries})")
            
            # Parse URL
            parsed_url = urlparse(self.url)
            host = parsed_url.hostname
            port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)
            path = parsed_url.path
            if parsed_url.query:
                path += '?' + parsed_url.query
                
            # Close existing socket if any
            self._close_socket()
                
            # Create socket connection
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(15)  # 15 second timeout
            
            # Connect to host
            if parsed_url.scheme == 'https':
                context = ssl.create_default_context()
                self.socket = context.wrap_socket(self.socket, server_hostname=host)
                
            self.socket.connect((host, port))
            
            # Send HTTP request
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"User-Agent: {self.user_agent}\r\n"
                f"Accept: */*\r\n"
                f"Connection: keep-alive\r\n"
                f"Accept-Encoding: identity\r\n"
                f"Accept-Language: en_US\r\n"
                f"Cache-Control: no-cache\r\n\r\n"
            )
            
            self.socket.sendall(request.encode('utf-8'))
            
            # Read HTTP response headers
            header_data = b''
            while b'\r\n\r\n' not in header_data:
                chunk = self.socket.recv(1024)
                if not chunk:
                    logging.error("Connection closed during header reading")
                    return False
                header_data += chunk
                
            # Split headers from any content received
            header_end = header_data.find(b'\r\n\r\n') + 4
            headers = header_data[:header_end].decode('utf-8', errors='ignore')
            initial_content = header_data[header_end:]
            
            # Parse status line and headers
            header_lines = headers.split('\r\n')
            status_line = header_lines[0]
            status_code = int(status_line.split(' ')[1]) if len(status_line.split(' ')) > 1 else 0
            
            # Check if it's a redirect (3xx status code)
            if 300 <= status_code < 400:
                # Extract Location header
                location = None
                for line in header_lines:
                    if line.lower().startswith('location:'):
                        location = line.split(':', 1)[1].strip()
                        break
                
                if location:
                    logging.info(f"Following redirect to: {location}")
                    
                    # If location is a relative URL, make it absolute
                    if not location.startswith('http'):
                        if location.startswith('/'):
                            location = f"{parsed_url.scheme}://{host}{location}"
                        else:
                            location = f"{parsed_url.scheme}://{host}/{location}"
                    
                    # Update the URL and try again
                    self.url = location
                    return self.connect()  # Recursive call to follow the redirect
                else:
                    logging.error("Received redirect without Location header")
                    return False
                    
            # Check HTTP status code
            if status_code != 200:
                logging.error(f"Failed to connect: {status_line}")
                return False
                
            # Process any initial content
            if initial_content:
                if len(initial_content) < self.min_data_size:
                    logging.warning(f"Initial content too small ({len(initial_content)} bytes), might be incomplete")
                else:
                    self.buffer.add_chunk(initial_content)
                    
            self.connected = True
            self.ready_event.set()
            logging.info("Stream connected successfully")
            return True
            
        except socket.timeout:
            logging.error("Connection timed out")
            self._close_socket()
            return False
        except socket.error as e:
            logging.error(f"Socket error: {e}")
            self._close_socket()
            return False
        except Exception as e:
            logging.error(f"Connection error: {e}")
            self._close_socket()
            return False
    
    def _close_socket(self):
        """Close socket connection if it exists"""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
    
    def should_retry(self):
        """Check if we should retry connecting"""
        return self.retry_count < self.max_retries
    
    def fetch_chunk(self):
        """Fetch data with proper TS packet handling"""
        if not self.connected or not self.socket:
            return False
            
        try:
            # Read a chunk of data (intentionally larger than packet size)
            chunk = self.socket.recv(8192)
            
            if not chunk:
                # Connection closed
                logging.warning("Server closed connection")
                self.connected = False
                return False
                
            # Add to our receive buffer
            self.recv_buffer.extend(chunk)
            
            # Process complete packets from buffer
            return self._process_complete_packets()
                
        except socket.timeout:
            # No data available right now
            return False
        except socket.error as e:
            logging.error(f"Socket error: {e}")
            self.connected = False
            return False
        except Exception as e:
            logging.error(f"Error in fetch_chunk: {e}")
            return False
    
    def _process_complete_packets(self):
        """Process only complete TS packets from buffer with improved error handling"""
        try:
            # Find sync byte if needed
            if not self.sync_found and len(self.recv_buffer) >= 376:
                for i in range(min(188, len(self.recv_buffer) - 188)):
                    # Look for at least two sync bytes (0x47) at 188-byte intervals
                    if (self.recv_buffer[i] == 0x47 and 
                        self.recv_buffer[i + 188] == 0x47):
                        
                        # Trim buffer to start at first sync byte
                        self.recv_buffer = self.recv_buffer[i:]
                        self.sync_found = True
                        break
                
                # If sync not found, keep last 188 bytes and return
                if not self.sync_found:
                    if len(self.recv_buffer) > 188:
                        self.recv_buffer = self.recv_buffer[-188:]
                    return False
                    
            # If we don't have a complete packet yet, wait for more data
            if len(self.recv_buffer) < 188:
                return False
                
            # Calculate how many complete packets we have
            packet_count = len(self.recv_buffer) // 188
            
            if packet_count == 0:
                return False
                
            # Extract only complete packets
            packets_data = self.recv_buffer[:packet_count * 188]
            
            # Keep remaining data in buffer
            self.recv_buffer = self.recv_buffer[packet_count * 188:]
            
            # Send aligned packet data to buffer - even if some packets might not start with 0x47
            # This is more forgiving and prevents getting stuck
            if packets_data:
                self.buffer.add_chunk(bytes(packets_data))
                return True
                
            return False
            
        except Exception as e:
            logging.error(f"Error processing TS packets: {e}")
            self.sync_found = False  # Reset sync state on error
            return False
    
    def update_url(self, new_url):
        """Change the URL for this stream with smooth transition"""
        if self.url == new_url:
            logging.debug(f"URL unchanged: {new_url}")
            return False
            
        logging.info(f"Switching stream URL: {self.url} → {new_url}")
        self.url = new_url
        
        # Don't directly close the existing connection here
        # Instead, let the fetch thread detect the URL change and reconnect
        
        # Reset retry counter for the new connection
        self.retry_count = 0
        
        # Signal that we need to reconnect (but don't stop running)
        self.running = True
        return True
    
    def stop(self):
        """Stop the stream manager and close all connections"""
        self.running = False
        self.connected = False
        self._close_socket()
        
        # Close the session to free up resources
        try:
            self.session.close()
        except Exception as e:
            logging.warning(f"Error closing session: {e}")

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
    """Buffer that uses Redis as the primary storage with TS packet awareness"""
    
    def __init__(self, channel_id, redis_client=None, max_length=None):
        from apps.proxy.config import TSConfig as Config
        self.channel_id = channel_id
        self.redis_client = redis_client
        self.max_length = max_length or Config.STREAM_BUFFER_SIZE
        self.lock = threading.RLock()
        self.local_index = 0
        
        # TS packet handling constants
        self.TS_PACKET_SIZE = 188
        self.CHUNK_SIZE = 188 * 64  # Use multiple of TS packet size
        
        # Only keep a small local cache for the most recent chunks
        self.local_cache_size = Config.LOCAL_CACHE_SIZE
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
        """Add a chunk to shared Redis buffer with guaranteed TS packet alignment and atomic indexing"""
        try:
            # Ensure the chunk is a multiple of TS packet size
            if len(chunk) % 188 != 0:
                logging.warning(f"Received non-aligned chunk of size {len(chunk)}")
                # Truncate to multiple of TS packet size
                aligned_size = (len(chunk) // 188) * 188
                if aligned_size == 0:
                    return False
                chunk = chunk[:aligned_size]
            
            # Store aligned TS packets in Redis
            if self.redis_available and self.redis_client:
                try:
                    # Use Redis atomic increment to get next index reliably
                    index_key = f"ts_proxy:buffer:{self.channel_id}:index"
                    chunk_index = self.redis_client.incr(index_key)
                    
                    # Store chunk with expiration time from config
                    from apps.proxy.config import TSConfig as Config
                    chunk_key = f"ts_proxy:buffer:{self.channel_id}:chunk:{chunk_index}"
                    self.redis_client.setex(chunk_key, Config.REDIS_CHUNK_TTL, chunk)
                    
                    # Update our local tracking
                    with self.lock:
                        self.local_index = chunk_index
                        self.local_cache[chunk_index] = chunk
                        
                        # Keep local cache size in check
                        while len(self.local_cache) > self.local_cache_size:
                            oldest = min(self.local_cache.keys())
                            del self.local_cache[oldest]
                    
                    self.chunks_stored += 1
                    
                    # Periodic logging
                    if self.chunks_stored % 50 == 0:
                        pkts = len(chunk) // self.TS_PACKET_SIZE
                        logging.info(f"Stored chunk {chunk_index} for channel {self.channel_id} in Redis ({pkts} TS packets)")
                    
                    return True
                    
                except Exception as e:
                    logging.warning(f"Failed to store chunk in Redis: {e}")
                    self.redis_available = False
            
            return True
        except Exception as e:
            logging.error(f"Error adding chunk to buffer: {e}")
            return False
    
    def get_chunks(self, start_index=None, skip_gaps=True):
        """Get chunks starting from given index with better gap handling"""
        try:
            # First, check if Redis has any data for this channel
            if self.redis_available and self.redis_client:
                try:
                    from apps.proxy.config import TSConfig
                    
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
                        buffer_size = getattr(TSConfig, 'CLIENT_START_BUFFER_SIZE', 500)
                        start_index = max(1, current_index - buffer_size)
                        logging.debug(f"Starting client at index {start_index} (current: {current_index}, buffer: {buffer_size})")
                    
                    # Handle case where client is ahead of buffer
                    if start_index > current_index:
                        return []
                    
                    # Determine batch size (smaller to reduce impact of gaps)
                    fetch_size = 30  # Smaller batch size to handle gaps better
                    fetch_start = start_index + 1  # Next chunk after what client has
                    fetch_end = min(current_index + 1, fetch_start + fetch_size)
                    
                    # Check if chunks exist using pipelined exists commands
                    pipe = self.redis_client.pipeline()
                    for i in range(fetch_start, fetch_end):
                        chunk_key = f"ts_proxy:buffer:{self.channel_id}:chunk:{i}"
                        pipe.exists(chunk_key)
                    
                    # Get existence results
                    exist_results = pipe.execute()
                    
                    # If all chunks exist, fetch them all together
                    if all(exist_results) or not skip_gaps:
                        pipe = self.redis_client.pipeline()
                        for i in range(fetch_start, fetch_end):
                            chunk_key = f"ts_proxy:buffer:{self.channel_id}:chunk:{i}"
                            pipe.get(chunk_key)
                            
                        results = pipe.execute()
                        chunks = [r for r in results if r]
                        
                        if chunks:
                            self.local_index = fetch_start + len(chunks) - 1
                            return chunks
                    else:
                        # Get chunks up to the first gap
                        chunks = []
                        for i, exists in enumerate(exist_results):
                            idx = fetch_start + i
                            if not exists:
                                break
                                
                            chunk_key = f"ts_proxy:buffer:{self.channel_id}:chunk:{idx}"
                            chunk = self.redis_client.get(chunk_key)
                            if chunk:
                                chunks.append(chunk)
                                
                        if chunks:
                            self.local_index = fetch_start + len(chunks) - 1
                            return chunks
                            
                    return []
                    
                except Exception as e:
                    logging.warning(f"Failed to get chunks from Redis: {e}")
                    self.redis_available = False
                    
            # Fall back to local cache if Redis fails
            return []
            
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
        self.user_agent = user_agent or Config.DEFAULT_USER_AGENT or "VLC/3.0.20 LibVLC/3.0.20"
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
                
                # Add retry logic for initial connection
                retry_delay = 2
                for retry in range(3):
                    logging.info(f"Retrying initial connection in {retry_delay} seconds (retry {retry+1}/3)")
                    time.sleep(retry_delay)
                    if manager.connect():
                        logging.info(f"Successfully connected on retry {retry+1}")
                        break
                    retry_delay *= 2
                else:
                    return  # Give up after retries
            
            # Continue fetching until stopped
            last_heartbeat = 0
            consecutive_failures = 0
            max_consecutive_failures = 10
            import os
            worker_id = str(os.getpid())
            
            while manager.running:
                try:
                    current_time = time.time()
                    
                    # Check for stream switches and resets
                    # ... existing code for reset detection ...
                    
                    # Fetch next chunk of data
                    fetched = manager.fetch_chunk()
                    
                    if fetched:
                        # Reset failure counter on success
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        
                        # If we've had too many failures in a row, try to reconnect
                        if consecutive_failures >= max_consecutive_failures:
                            logging.warning(f"Too many consecutive failures ({consecutive_failures}), reconnecting")
                            if not manager.connect():
                                logging.error("Reconnection failed")
                                # Wait before next attempt
                                time.sleep(5)
                            consecutive_failures = 0
                        
                        # Small backoff to prevent tight loops
                        time.sleep(0.1)
                    
                    # Update heartbeat in Redis every 15 seconds
                    # ... existing heartbeat code ...
                    
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

    def switch_stream(self, channel_id, new_url):
        """Switch a channel to a new URL with clean transition"""
        with self.lock:
            if channel_id not in self.stream_managers:
                logging.warning(f"Cannot switch non-existent channel: {channel_id}")
                return False
            
            if channel_id not in self.stream_buffers:
                logging.warning(f"No buffer found for channel {channel_id}")
                return False
                
            # Don't switch if URL is the same
            if self.stream_managers[channel_id].url == new_url:
                logging.info(f"URL unchanged for channel {channel_id}: {new_url}")
                return False
                
            logging.info(f"Switching stream URL for {channel_id}: {self.stream_managers[channel_id].url} → {new_url}")
            
            # Keep reference to existing objects
            existing_buffer = self.stream_buffers[channel_id]
            client_manager = self.client_managers.get(channel_id)
            
            # 1. First fully stop the old manager and thread
            old_manager = self.stream_managers[channel_id]
            old_manager.running = False
            old_manager.stop()  # This will close any connections
            
            # 2. Remove the channel from our tracking (temporarily)
            if channel_id in self.fetch_threads:
                old_thread = self.fetch_threads.pop(channel_id)
                # Give thread a moment to exit
                wait_start = time.time()
                while old_thread.is_alive() and time.time() - wait_start < 1.0:
                    time.sleep(0.1)
                
            # 3. Create a completely new manager with the new URL
            new_manager = StreamManager(
                new_url,
                existing_buffer,  # Reuse buffer for continuous playback
                user_agent=self.user_agent
            )
            self.stream_managers[channel_id] = new_manager
            
            # 4. Start a fresh fetch thread
            thread = threading.Thread(
                target=self._fetch_stream,
                args=(new_manager, channel_id),
                daemon=True
            )
            self.fetch_threads[channel_id] = thread
            thread.start()
            
            # 5. Update metadata
            if self.redis_client:
                self.redis_client.set(f"ts_proxy:channel_url:{channel_id}", new_url)
            
            logging.info(f"Stream switched for channel {channel_id}: {new_url}")
            return True

    def reset_channel(self, channel_id):
        """Stop and completely reinitialize a channel"""
        with self.lock:
            if channel_id not in self.stream_managers:
                logging.warning(f"Cannot reset non-existent channel: {channel_id}")
                return False
                
            # Get current URL before stopping
            current_url = self.stream_managers[channel_id].url
            
            # Stop the channel
            self.stop_channel(channel_id)
            
            # Wait a moment for resources to clean up
            time.sleep(0.5)
            
            # Reinitialize with same URL
            self.initialize_channel(current_url, channel_id)
            logging.info(f"Channel {channel_id} reset with URL {current_url}")
            return True

    def is_channel_active(self, channel_id):
        """Check if a channel is truly active with recent heartbeats"""
        if channel_id in self.stream_managers:
            # Channel exists in this worker
            return True
            
        # Check Redis for remote workers
        if not self.redis_client:
            return False
            
        # Get worker ID
        worker_id_bytes = self.redis_client.get(f"ts_proxy:active_channel:{channel_id}")
        if not worker_id_bytes:
            return False
            
        # Check heartbeat
        last_heartbeat = self.redis_client.get(f"ts_proxy:heartbeat:{channel_id}")
        if not last_heartbeat:
            return False
            
        # Verify recent heartbeat
        try:
            last_beat_time = float(last_heartbeat.decode('utf-8') if isinstance(last_heartbeat, bytes) else last_heartbeat)
            return time.time() - last_beat_time < 30  # Active if heartbeat within 30 seconds
        except (ValueError, TypeError):
            return False  # Invalid heartbeat format

def is_valid_ts_packet(data, offset=0):
    """Check if the data at offset is a valid TS packet"""
    # TS packets start with 0x47 (71 in decimal) sync byte
    if len(data) < offset + 188:
        return False
    
    # Check sync byte
    if data[offset] != 0x47:
        return False
        
    # If this is a complete packet, the next sync byte should be at offset+188
    if len(data) >= offset + 188 + 1 and data[offset + 188] == 0x47:
        return True
        
    return True  # Assume valid if we don't have the next packet to check
