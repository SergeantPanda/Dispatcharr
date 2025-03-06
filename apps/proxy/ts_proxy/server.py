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
    
    def __init__(self, initial_url: str, channel_id: str, user_agent: Optional[str] = None):
        self.current_url: str = initial_url
        self.channel_id: str = channel_id
        self.user_agent: str = user_agent or Config.DEFAULT_USER_AGENT
        self.url_changed: threading.Event = threading.Event()
        self.running: bool = True
        self.session: requests.Session = self._create_session()
        self.connected: bool = False
        self.retry_count: int = 0
        logging.info(f"Initialized stream manager for channel {channel_id}")

    def _create_session(self) -> requests.Session:
        """Create and configure requests session"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': self.user_agent,
            'Connection': 'keep-alive'
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

class StreamBuffer:
    """Manages stream data buffering"""
    
    def __init__(self):
        self.buffer: Deque[bytes] = deque(maxlen=Config.BUFFER_SIZE)
        self.lock: threading.Lock = threading.Lock()
        self.index: int = 0

class ClientManager:
    """Manages active client connections"""
    
    def __init__(self):
        self.active_clients: Set[int] = set()
        self.lock: threading.Lock = threading.Lock()
        self.last_client_time: float = time.time()
        self.cleanup_timer: Optional[threading.Timer] = None
        self._proxy_server = None
        self._channel_id = None
        self.initialization_time: float = time.time()
        self.grace_period: float = 30.0  # 30 second grace period
        
    def start_cleanup_timer(self, proxy_server, channel_id):
        """Start timer to cleanup idle channels"""
        with self.lock:
            self._proxy_server = proxy_server
            self._channel_id = channel_id
            self.initialization_time = time.time()
            if self.cleanup_timer:
                self.cleanup_timer.cancel()
            self._start_new_timer()

    def _start_new_timer(self):
        """Start a new cleanup timer"""
        with self.lock:
            if self.cleanup_timer:
                self.cleanup_timer.cancel()
            self.cleanup_timer = threading.Timer(
                Config.CLIENT_TIMEOUT,
                self._cleanup_idle_channel
            )
            self.cleanup_timer.daemon = True
            self.cleanup_timer.start()
            
    def _cleanup_idle_channel(self):
        """Stop channel if no clients connected and grace period expired"""
        with self.lock:
            current_time = time.time()
            if current_time - self.initialization_time < self.grace_period:
                logging.info(f"Channel {self._channel_id} still in grace period, restarting timer")
                self._start_new_timer()
                return
                
            if not self.active_clients:
                logging.info(f"No clients connected for {Config.CLIENT_TIMEOUT}s, stopping channel {self._channel_id}")
                self._proxy_server.stop_channel(self._channel_id)
            else:
                self._start_new_timer()

    def add_client(self, client_id: int) -> None:
        """Add new client connection"""
        with self.lock:
            self.active_clients.add(client_id)
            self.last_client_time = time.time()  # Reset the timer
            if self.cleanup_timer:
                self.cleanup_timer.cancel()  # Cancel existing timer
                self.start_cleanup_timer(self._proxy_server, self._channel_id)  # Restart timer
            logging.info(f"New client connected: {client_id} (total: {len(self.active_clients)})")

    def remove_client(self, client_id: int) -> int:
        """Remove client and return remaining count"""
        with self.lock:
            self.active_clients.remove(client_id)
            remaining = len(self.active_clients)
            logging.info(f"Client disconnected: {client_id} (remaining: {remaining})")
            return remaining

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
        first_chunk = True
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
                    
                    # Signal ready after first chunk is buffered
                    if first_chunk and hasattr(self.manager, 'ready_event') and self.manager.ready_event:
                        logging.info("First chunk received, signaling channel ready")
                        self.manager.ready_event.set()
                        first_chunk = False

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
    def __init__(self, user_agent: Optional[str] = None):
        self.stream_managers: Dict[str, StreamManager] = {}
        self.stream_buffers: Dict[str, StreamBuffer] = {}
        self.client_managers: Dict[str, ClientManager] = {}
        self.fetch_threads: Dict[str, threading.Thread] = {}
        self.user_agent: str = user_agent or Config.DEFAULT_USER_AGENT
        self.lock: threading.Lock = threading.Lock()
        self._initialization_status: Dict[str, bool] = {}
        self._channel_ready_events: Dict[str, threading.Event] = {}

    def initialize_channel(self, url: str, channel_id: str) -> None:
        """Initialize a new channel stream"""
        with self.lock:
            logging.info(f"Starting initialization for channel {channel_id}")
            
            # Create ready event
            ready_event = threading.Event()
            self._channel_ready_events[channel_id] = ready_event
            
            # Track initialization status
            self._initialization_status[channel_id] = False
            
            if channel_id in self.stream_managers:
                logging.info(f"Stopping existing channel {channel_id}")
                self.stop_channel(channel_id)
            
            try:
                # Create manager first
                manager = StreamManager(url, channel_id, user_agent=self.user_agent)
                manager.ready_event = ready_event
                self.stream_managers[channel_id] = manager
                
                # Create buffer and client manager
                self.stream_buffers[channel_id] = StreamBuffer()
                self.client_managers[channel_id] = ClientManager()
                
                # Start fetch thread
                fetcher = StreamFetcher(manager, self.stream_buffers[channel_id])
                thread = threading.Thread(
                    target=fetcher.fetch_loop,
                    name=f"StreamFetcher-{channel_id}",
                    daemon=True
                )
                self.fetch_threads[channel_id] = thread
                
                # Mark initialization started
                self._initialization_status[channel_id] = True
                
                # Start thread
                thread.start()
                
                # Wait for ready signal or timeout
                if not ready_event.wait(timeout=10.0):
                    raise TimeoutError("Channel initialization timed out")
                
                logging.info(f"Completed initialization for channel {channel_id}")
                
            except Exception as e:
                logging.error(f"Error during channel initialization: {e}")
                self._cleanup_channel(channel_id)
                raise

    def is_channel_ready(self, channel_id: str) -> bool:
        """Check if channel is fully initialized and ready"""
        with self.lock:
            channel_exists = (
                channel_id in self._initialization_status and
                channel_id in self.stream_managers and
                channel_id in self.stream_buffers and
                channel_id in self.client_managers and
                channel_id in self._channel_ready_events
            )
            
            if not channel_exists:
                logging.debug(f"Channel {channel_id} missing components")
                return False
                
            is_ready = (
                self._initialization_status[channel_id] and
                self.stream_managers[channel_id].connected and 
                len(self.stream_buffers[channel_id].buffer) > 0 and
                self._channel_ready_events[channel_id].is_set()  # Changed: Check if event IS set
            )
            
            logging.debug(f"Channel {channel_id} ready state check:")
            logging.debug(f"- Initialization status: {self._initialization_status[channel_id]}")
            logging.debug(f"- Connected: {self.stream_managers[channel_id].connected}")
            logging.debug(f"- Buffer size: {len(self.stream_buffers[channel_id].buffer)}")
            logging.debug(f"- Ready event set: {self._channel_ready_events[channel_id].is_set()}")
            logging.debug(f"Final ready state: {is_ready}")
            
            return is_ready

    def _cleanup_channel(self, channel_id: str) -> None:
        """Remove channel resources"""
        with self.lock:
            logging.info(f"Cleaning up channel {channel_id}")
            try:
                if channel_id in self.stream_managers:
                    self.stream_managers[channel_id].stop()
                if channel_id in self.fetch_threads and self.fetch_threads[channel_id].is_alive():
                    self.fetch_threads[channel_id].join(timeout=5)
            except Exception as e:
                logging.error(f"Error during cleanup: {e}")
            finally:
                # Remove from all collections
                self.stream_managers.pop(channel_id, None)
                self.stream_buffers.pop(channel_id, None)
                self.client_managers.pop(channel_id, None)
                self.fetch_threads.pop(channel_id, None)
                self._initialization_status.pop(channel_id, None)
                self._channel_ready_events.pop(channel_id, None)
                logging.info(f"Cleanup complete for channel {channel_id}")

    def stop_channel(self, channel_id: str) -> None:
        """Stop and cleanup a channel"""
        if channel_id in self.stream_managers:
            logging.info(f"Stopping channel {channel_id}")
            try:
                self.stream_managers[channel_id].stop()
                if channel_id in self.fetch_threads:
                    self.fetch_threads[channel_id].join(timeout=5)
                    if self.fetch_threads[channel_id].is_alive():
                        logging.warning(f"Fetch thread for channel {channel_id} did not stop cleanly")
            except Exception as e:
                logging.error(f"Error stopping channel {channel_id}: {e}")
            finally:
                self._cleanup_channel(channel_id)
            
    def shutdown(self) -> None:
        """Stop all channels and cleanup"""
        for channel_id in list(self.stream_managers.keys()):
            self.stop_channel(channel_id)
        logging.info("Proxy server shutdown complete")