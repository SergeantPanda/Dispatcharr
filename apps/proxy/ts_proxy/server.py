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
    """Manages TS stream state and connection handling"""
    
    def __init__(self, initial_url: str, channel_id: str, user_agent: Optional[str] = None, buffer=None):
        self.current_url: str = initial_url
        self.channel_id: str = channel_id
        self.user_agent: str = user_agent or Config.DEFAULT_USER_AGENT
        self.url_changed: threading.Event = threading.Event()
        self.ready_event: threading.Event = threading.Event()
        self.running: bool = True
        self.connected: bool = False
        self.retry_count: int = 0
        self.session: requests.Session = self._create_session()
        self._initialized: bool = False
        self.fetch_thread: Optional[threading.Thread] = None
        self.buffer = buffer  # Add buffer attribute
        self.ready_event.clear()  # Explicitly clear the ready event
        logging.info(f"Initialized stream manager for channel {channel_id}")

    def is_ready(self) -> bool:
        """Check if stream is ready"""
        is_ready = self._initialized and self.connected and self.ready_event.is_set() and self.buffer and len(self.buffer.buffer) > 0
        logging.debug(f"Stream manager ready check: {is_ready} (initialized={self._initialized}, connected={self.connected}, ready_event={self.ready_event.is_set()}, buffer_has_data={self.buffer and len(self.buffer.buffer) > 0})")
        return is_ready

    def mark_initialized(self) -> None:
        """Mark stream as fully initialized"""
        self._initialized = True
        logging.info(f"Stream manager for channel {self.channel_id} marked as initialized")

    def _create_session(self) -> requests.Session:
        """Create and configure requests session"""
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=3,
            pool_block=True
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        session.headers.update({
            'User-Agent': self.user_agent,
            'Connection': 'keep-alive',
            'Accept': '*/*'
        })
        return session

    def update_url(self, new_url: str) -> bool:
        """Update stream URL and signal connection change"""
        if new_url != self.current_url:
            logging.info(f"Stream switch initiated: {self.current_url} -> {new_url}")
            self.current_url = new_url
            self.connected = False
            self.url_changed.set()
            return True
        return False

    def should_retry(self) -> bool:
        """Check if connection retry is allowed"""
        return self.retry_count < Config.MAX_RETRIES

    def stop(self) -> None:
        """Clean shutdown of stream manager"""
        self.running = False
        if self.session:
            self.session.close()

    def start(self) -> None:
        """Start the fetch thread"""
        if not self.fetch_thread or not self.fetch_thread.is_alive():
            self.running = True
            self.fetch_thread = threading.Thread(
                target=self._fetch_loop,
                name=f"Fetch-{self.channel_id}",
                daemon=True
            )
            self.fetch_thread.start()
            logging.info(f"Started fetch thread for channel {self.channel_id}")

    def _fetch_loop(self) -> None:
        """Main fetch loop"""
        try:
            fetcher = StreamFetcher(self, self.buffer)
            while self.running:
                fetcher.fetch_loop()
                
        except Exception as e:
            logging.error(f"Fetch loop error: {e}", exc_info=True)
            self.running = False

class StreamBuffer:
    """Manages stream data buffering"""
    
    def __init__(self):
        self.buffer: Deque[bytes] = deque(maxlen=Config.BUFFER_SIZE)
        self.lock: threading.Lock = threading.Lock()
        self.index: int = 0
        
    def get_chunks(self, start_pos: int) -> list[bytes]:
        """Get chunks from buffer starting at given position"""
        with self.lock:
            if not self.buffer:
                return []
                
            current_buffer = list(self.buffer)
            if start_pos >= len(current_buffer):
                return []
                
            return current_buffer[start_pos:]

class ClientManager:
    def __init__(self):
        logging.debug("Initializing new ClientManager")
        self.active_clients = set()
        self.lock = threading.Lock()
        self.cleanup_timer = None
        self.last_client_time = time.time()
        self._channel_id = None
        self._proxy_server = None
        self.cleanup_grace_period = 300.0  # 5 minutes instead of 60 seconds
        self.cleanup_enabled = False
        self.had_clients = False  # Track if we've ever had clients
        logging.debug("ClientManager initialization complete")

    def start_cleanup_timer(self, proxy_server, channel_id):
        """Start cleanup timer with proper initialization"""
        logging.debug(f"Starting cleanup timer for channel {channel_id}")
        try:
            # Store references first without lock
            self._proxy_server = proxy_server
            self._channel_id = channel_id
            self.last_client_time = time.time()
            
            # Don't enable cleanup immediately - wait until first client connects
            self.cleanup_enabled = False
            
            # Create timer outside lock to prevent deadlock (but don't start it yet)
            timer = threading.Timer(
                self.cleanup_grace_period,
                self._check_cleanup
            )
            timer.daemon = True
            
            # Update timer reference under lock
            with self.lock:
                logging.debug("Acquired lock for cleanup timer update")
                if self.cleanup_timer:
                    self.cleanup_timer.cancel()
                self.cleanup_timer = timer
                
            # Don't start timer until first client disconnects
            logging.debug("Cleanup timer will start after first client disconnects")
            
        except Exception as e:
            logging.error(f"Error in start_cleanup_timer: {e}", exc_info=True)
            # Reset state on error
            self.cleanup_enabled = False
            self._proxy_server = None
            self._channel_id = None
            raise

    def add_client(self, client_id):
        """Add client and reset cleanup timer"""
        with self.lock:
            self.active_clients.add(client_id)
            self.last_client_time = time.time()
            self.had_clients = True  # We've had at least one client
            
            # When adding a client, cancel any existing cleanup timer
            if self.cleanup_timer:
                self.cleanup_timer.cancel()
                self.cleanup_timer = None
                logging.debug(f"Canceled cleanup timer because client {client_id} connected")
            
            self.cleanup_enabled = False  # Disable cleanup while clients are connected
            logging.debug(f"Added client {client_id}, total clients: {len(self.active_clients)}")
            
    def remove_client(self, client_id):
        """Remove client and check for cleanup"""
        with self.lock:
            if client_id in self.active_clients:
                self.active_clients.remove(client_id)
            remaining = len(self.active_clients)
            logging.debug(f"Removed client {client_id}, remaining clients: {remaining}")
            
            # Only start cleanup when all clients have disconnected AND we've had clients before
            if remaining == 0 and self.had_clients:
                self.last_client_time = time.time()
                self.cleanup_enabled = True  # Now enable cleanup
                self._schedule_cleanup()  # Schedule first cleanup check
            
            return remaining

    def _schedule_cleanup(self):
        """Schedule next cleanup check"""
        logging.debug(f"Scheduling cleanup for channel {self._channel_id}")
        try:
            # Create new timer without lock
            timer = threading.Timer(
                self.cleanup_grace_period,
                self._check_cleanup
            )
            timer.daemon = True
            
            # Update timer reference under lock
            with self.lock:
                logging.debug("Acquired lock for cleanup scheduling")
                if self.cleanup_timer:
                    logging.debug("Canceling existing cleanup timer")
                    self.cleanup_timer.cancel()
                self.cleanup_timer = timer
                
            # Start timer after releasing lock
            logging.debug("Starting new cleanup timer")
            timer.start()
            logging.debug("New cleanup timer started")
            
        except Exception as e:
            logging.error(f"Error in _schedule_cleanup: {e}", exc_info=True)
            raise

    def _check_cleanup(self):
        """Check if cleanup should occur"""
        logging.debug(f"Running cleanup check for channel {self._channel_id}")
        try:
            with self.lock:
                logging.debug("Acquired lock for cleanup check")
                if not self.cleanup_enabled:
                    logging.debug("Cleanup disabled, skipping check")
                    return
                
                current_time = time.time()
                inactive_time = current_time - self.last_client_time
                logging.debug(f"Time since last activity: {inactive_time:.1f}s")
                
                # Check Redis for active clients (cross-worker visibility)
                redis_client = None
                try:
                    import redis
                    from django.conf import settings
                    
                    # Create Redis client with proper connection parameters
                    redis_client = redis.Redis(
                        host=getattr(settings, 'REDIS_HOST', 'localhost'),
                        port=getattr(settings, 'REDIS_PORT', 6379),
                        db=getattr(settings, 'REDIS_DB', 0),
                        socket_timeout=3,
                        decode_responses=True  # Important for key pattern matching
                    )
                    
                    # Test connection before using it
                    redis_client.ping()
                    
                    # Check for active clients in Redis
                    pattern = f"ts_proxy:client:{self._channel_id}:*" 
                    client_keys = redis_client.keys(pattern)
                    if client_keys:
                        logging.debug(f"Found {len(client_keys)} active clients in Redis, not cleaning up")
                        self._schedule_cleanup()
                        return
                        
                    # Also check if channel is marked active in Redis
                    channel_active = redis_client.get(f"ts_proxy:channel_active:{self._channel_id}")
                    if channel_active:
                        logging.debug(f"Channel {self._channel_id} marked as active in Redis, not cleaning up")
                        self._schedule_cleanup()
                        return
                        
                except Exception as e:
                    logging.warning(f"Failed to check Redis for clients: {e}")
                    # Since Redis failed, be conservative and don't clean up yet
                    self._schedule_cleanup()
                    return
                
                # Local check - only execute if Redis check was successful but found no clients
                if (inactive_time >= self.cleanup_grace_period and 
                    not self.active_clients):
                    if self._proxy_server and self._channel_id:
                        logging.info(f"No clients connected for {inactive_time:.1f}s, stopping channel {self._channel_id}")
                        try:
                            if redis_client:
                                redis_client.delete(f"ts_proxy:channel_active:{self._channel_id}")
                        except Exception as e:
                            logging.warning(f"Failed to delete Redis key: {e}")
                        self._proxy_server.stop_channel(self._channel_id)
                        return  # Don't schedule another cleanup
                
                # Otherwise, schedule the next cleanup
                logging.debug(f"Channel {self._channel_id} still active or in grace period")
                self._schedule_cleanup()
                
        except Exception as e:
            logging.error(f"Error in _check_cleanup: {e}", exc_info=True)
            # Always schedule another cleanup on error
            self._schedule_cleanup()

    def cancel_cleanup(self):
        """Cancel cleanup timer"""
        with self.lock:
            self.cleanup_enabled = False
            if self.cleanup_timer:
                self.cleanup_timer.cancel()
                self.cleanup_timer = None

class StreamFetcher:
    """Handles stream data fetching"""
    
    def __init__(self, manager: StreamManager, buffer: StreamBuffer):
        self.manager = manager
        self.buffer = buffer
        self._first_chunk_received = False
        self._chunks_received = 0

    def fetch_loop(self) -> None:
        """Main fetch loop for stream data"""
        logging.info(f"Starting fetch loop for channel {self.manager.channel_id}")
        
        while self.manager.running:
            try:
                logging.debug(f"Fetch loop iteration starting for channel {self.manager.channel_id}")
                
                # Handle connection first
                if not self._handle_connection():
                    logging.error(f"Connection handling failed for channel {self.manager.channel_id}")
                    time.sleep(Config.RECONNECT_DELAY)
                    continue

                # Make streaming request
                logging.info(f"Making streaming request for channel {self.manager.channel_id}")
                response = self.manager.session.get(
                    self.manager.current_url,
                    stream=True,
                    timeout=(5.0, 30.0),
                    verify=False  # Add this to help debug SSL issues
                )
                
                logging.info(f"Streaming response received: Status={response.status_code}")
                response.raise_for_status()

                if response.status_code == 200:
                    self._handle_successful_connection()
                    self._process_stream(response)
                else:
                    logging.error(f"Unexpected status {response.status_code} for channel {self.manager.channel_id}")
                    self.manager.connected = False

            except requests.exceptions.RequestException as e:
                logging.error(f"Request failed for channel {self.manager.channel_id}", exc_info=True)
                self._handle_connection_error(e)
            except Exception as e:
                logging.error(f"Unexpected error in fetch loop for channel {self.manager.channel_id}", exc_info=True)

    def _handle_connection(self) -> bool:
        """Handle connection state and retries"""
        logging.debug(f"Handling connection for channel {self.manager.channel_id}")
        logging.debug(f"Current connection state: connected={self.manager.connected}")
        
        if not self.manager.connected:
            if not self.manager.should_retry():
                logging.error(f"Failed to connect after {Config.MAX_RETRIES} attempts for channel {self.manager.channel_id}")
                return False
                
            self.manager.retry_count += 1
            logging.info(f"Connection attempt {self.manager.retry_count}/{Config.MAX_RETRIES} for channel {self.manager.channel_id}")
            logging.info(f"URL: {self.manager.current_url}")
            
            try:
                logging.debug(f"Making connection with headers: {dict(self.manager.session.headers)}")
                logging.debug(f"Starting GET request to: {self.manager.current_url}")
                
                response = self.manager.session.get(
                    self.manager.current_url,
                    stream=True,
                    timeout=(5.0, 30.0),
                    allow_redirects=True,
                    verify=False  # Add this to help debug SSL issues
                )
                
                logging.info(f"Initial response received: Status={response.status_code}, Content-Type={response.headers.get('content-type')}")
                
                if response.history:
                    logging.info(f"Request was redirected {len(response.history)} times:")
                    for r in response.history:
                        logging.info(f"  {r.status_code} -> {r.url}")
                    logging.info(f"Final URL: {response.url}")
                
                response.raise_for_status()
                self.manager.connected = True
                logging.info(f"Connection successful for channel {self.manager.channel_id}")
                logging.debug(f"Response headers: {dict(response.headers)}")
                return True
                
            except Exception as e:
                logging.error(f"Connection attempt failed for channel {self.manager.channel_id}", exc_info=True)
                logging.error(f"Error details: {str(e)}")
                return False
        
        logging.debug(f"Channel {self.manager.channel_id} already connected")
        return True

    def _handle_successful_connection(self) -> None:
        """Handle successful stream connection"""
        if not self.manager.connected:
            logging.info("Stream connected successfully")
            self.manager.connected = True
            self.manager.retry_count = 0

    def _process_stream(self, response: requests.Response) -> None:
        """Process incoming stream data"""
        try:
            logging.info("Starting stream data processing")
            chunk_count = 0
            total_bytes = 0
            
            for chunk in response.iter_content(chunk_size=Config.CHUNK_SIZE):
                if not self.manager.running:
                    logging.info("Stream fetch stopped - shutting down")
                    return
                    
                if chunk:  # Filter out keep-alive chunks
                    chunk_size = len(chunk)
                    total_bytes += chunk_size
                    chunk_count += 1
                    
                    if self.manager.url_changed.is_set():
                        logging.info("Stream switch in progress, closing connection")
                        self.manager.url_changed.clear()
                        break
                        
                    with self.buffer.lock:
                        self.buffer.buffer.append(chunk)
                        self.buffer.index += 1
                        self._chunks_received += 1
                        
                        # Signal ready after first chunk
                        if not self._first_chunk_received:
                            logging.info(f"First chunk received: {chunk_size} bytes")
                            self._first_chunk_received = True
                            logging.info("Setting ready event")
                            self.manager.ready_event.set()
                            logging.debug("Channel state after first chunk:")
                            logging.debug(f"- Connected: {self.manager.connected}")
                            logging.debug(f"- Ready Event: {self.manager.ready_event.is_set()}")
                            logging.debug(f"- Buffer Size: {len(self.buffer.buffer)}")
                        
                        if chunk_count % 100 == 0:
                            logging.info(f"Stream stats - Chunks: {chunk_count}, Total bytes: {total_bytes}, Buffer size: {len(self.buffer.buffer)}")
                            
        except Exception as e:
            logging.error(f"Error processing stream: {str(e)}", exc_info=True)
            self.manager.connected = False
            if self.manager.running:
                self._handle_connection_error(e)

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
    def __init__(self):
        self.lock = threading.Lock()
        self.stream_managers = {}
        self.stream_buffers = {}
        self.client_managers = {} 
        self.fetch_threads = {}
        self._initialization_status = {}
        self._channel_ready_events = {}
        self._cleanup_events = {}

    def initialize_channel(self, url: str, channel_id: str) -> None:
        """Initialize a new channel"""
        with self.lock:
            # Create buffer first
            buffer = StreamBuffer()
            self.stream_buffers[channel_id] = buffer
            
            # Create manager with buffer
            manager = StreamManager(url, channel_id, buffer=buffer)
            self.stream_managers[channel_id] = manager
            self.client_managers[channel_id] = ClientManager()
            self._channel_ready_events[channel_id] = threading.Event()
            self._cleanup_events[channel_id] = threading.Event()
            
            # Start manager
            manager.mark_initialized()  # Mark as initialized before starting
            manager.start()
            
            # Mark as initialized in proxy server too 
            self._initialization_status[channel_id] = True

            logging.info(f"Channel {channel_id} components initialized")

    def stop_channel(self, channel_id: str) -> None:
        """Stop and cleanup channel"""
        with self.lock:
            if channel_id not in self.stream_managers:
                return
                
            # Signal cleanup
            if channel_id in self._cleanup_events:
                self._cleanup_events[channel_id].set()
                
            # Stop components
            if channel_id in self.stream_managers:
                self.stream_managers[channel_id].stop()
                
            if channel_id in self.client_managers:
                self.client_managers[channel_id].cancel_cleanup()
                
            # Remove from collections
            self._cleanup_channel(channel_id)
            
            logging.info(f"Channel {channel_id} stopped and cleaned up")

    def _cleanup_channel(self, channel_id: str) -> None:
        """Clean up all resources for a channel"""
        with self.lock:
            collections = [
                self.stream_managers,
                self.stream_buffers,
                self.client_managers,
                self.fetch_threads,
                self._initialization_status,
                self._channel_ready_events
            ]
            
            try:
                # Stop components first
                if channel_id in self.client_managers:
                    self.client_managers[channel_id].cancel_cleanup()
                
                if channel_id in self.stream_managers:
                    self.stream_managers[channel_id].stop()
                    
                if channel_id in self.fetch_threads:
                    thread = self.fetch_threads[channel_id]
                    if thread and thread.is_alive():
                        thread.join(timeout=1.0)
                
                # Remove from collections atomically
                for collection in collections:
                    if channel_id in collection:
                        collection.pop(channel_id)
                
                # Clean up Redis keys
                try:
                    from django.conf import settings
                    import redis
                    
                    redis_client = redis.Redis(
                        host=getattr(settings, 'REDIS_HOST', 'localhost'),
                        port=getattr(settings, 'REDIS_PORT', 6379),
                        db=getattr(settings, 'REDIS_DB', 0),
                        password=getattr(settings, 'REDIS_PASSWORD', None),
                        socket_timeout=2,
                        decode_responses=True
                    )
                    
                    redis_keys = [
                        f"ts_proxy:channel_url:{channel_id}",
                        f"ts_proxy:channel_active:{channel_id}"
                    ]
                    
                    for key in redis_keys:
                        try:
                            redis_client.delete(key)
                        except:
                            pass
                except:
                    # Redis cleanup is best-effort only
                    pass
                    
                logging.info(f"Cleanup complete for channel {channel_id}")
                
            except Exception as e:
                logging.error(f"Error during channel cleanup: {e}")
                # Force removal from collections
                for collection in collections:
                    collection.pop(channel_id, None)

    def is_channel_ready(self, channel_id: str) -> bool:
        """Check if channel is fully initialized and ready"""
        try:
            with self.lock:
                # First check basic existence
                if channel_id not in self.stream_managers:
                    logging.debug(f"Channel {channel_id} not found in stream_managers")
                    return False
                
                # Get component references
                manager = self.stream_managers.get(channel_id)
                buffer = self.stream_buffers.get(channel_id)
                
                # Check if stream manager is ready (this calls manager.is_ready())
                manager_ready = manager.is_ready() if manager else False
                
                logging.debug(f"Channel {channel_id} manager ready check: {manager_ready}")
                
                # Check buffer has data directly
                buffer_has_data = bool(buffer and len(buffer.buffer) > 0)
                logging.debug(f"Channel {channel_id} buffer check: {buffer_has_data} (size: {len(buffer.buffer) if buffer else 0})")
                
                # Successful check if both manager is ready and buffer has data
                is_ready = manager_ready and buffer_has_data
                
                logging.debug(f"Channel {channel_id} ready state: {is_ready}")
                return is_ready
                
        except Exception as e:
            logging.error(f"Error checking channel ready state: {e}", exc_info=True)
            return False

    def _check_components(self, channel_id: str) -> bool:
        """Check if all required components exist"""
        with self.lock:
            components = {
                'stream_manager': channel_id in self.stream_managers,
                'stream_buffer': channel_id in self.stream_buffers,
                'client_manager': channel_id in self.client_managers,
                'ready_event': channel_id in self._channel_ready_events,
                'init_status': channel_id in self._initialization_status
            }
            
            self._component_status[channel_id] = components
            all_exist = all(components.values())
            
            if not all_exist:
                missing = [k for k, v in components.items() if not v]
                logging.debug(f"Channel {channel_id} missing components: {missing}")
                
            return all_exist

    def _verify_channel_state(self, channel_id: str) -> bool:
        """Verify channel state and components"""
        try:
            with self.lock:
                # First verify components exist
                components = {
                    'stream_manager': channel_id in self.stream_managers,
                    'stream_buffer': channel_id in self.stream_buffers,
                    'client_manager': channel_id in self.client_managers,
                    'ready_event': channel_id in self._channel_ready_events,
                    'init_status': channel_id in self._initialization_status
                }
                
                # Log component status
                logging.debug(f"Component status for channel {channel_id}:")
                for comp, exists in components.items():
                    logging.debug(f"- {comp}: {exists}")
                
                if not all(components.values()):
                    missing = [k for k, v in components.items() if not v]
                    logging.debug(f"Missing components: {missing}")
                    return False

                # Get component references
                manager = self.stream_managers[channel_id]
                buffer = self.stream_buffers[channel_id]
                fetcher = self.fetch_threads.get(channel_id)
                
                # Get state under lock 
                state = {
                    'manager_exists': True,
                    'manager_running': manager.running,
                    'manager_connected': manager.connected,
                    'buffer_exists': True,
                    'buffer_has_data': len(buffer.buffer) > 0,
                    'ready_event_set': manager.ready_event.is_set(),
                    'initialization_status': self._initialization_status[channel_id],
                    'thread_alive': fetcher and fetcher.is_alive()
                }
                
                # Log detailed state
                logging.debug(f"State for channel {channel_id}:")
                for key, value in state.items():
                    logging.debug(f"- {key}: {value}")
                
                return all(state.values())
                
        except Exception as e:
            logging.error(f"Error verifying channel state: {e}")
            return False

    def stop_channel(self, channel_id: str) -> None:
        """Stop and cleanup a channel"""
        with self.lock:
            if channel_id not in self.stream_managers:
                return
                
            logging.info(f"Stopping channel {channel_id}")
            try:
                self._cleanup_channel(channel_id)
            except Exception as e:
                logging.error(f"Error stopping channel {channel_id}: {e}")
            
    def shutdown(self) -> None:
        """Stop all channels and cleanup"""
        for channel_id in list(self.stream_managers.keys()):
            self.stop_channel(channel_id)
        logging.info("Proxy server shutdown complete")