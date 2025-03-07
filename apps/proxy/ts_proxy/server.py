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
    
    def __init__(self, max_length=1000):
        self.buffer = []
        self.lock = threading.RLock()
        self.max_length = max_length
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
            if not self.active_clients and not self.cleanup_timer:
                self.schedule_cleanup()
    
    def schedule_cleanup(self):
        """Schedule cleanup if no clients reconnect within the grace period"""
        if not self.cleanup_timer:
            # Wait 30 seconds before cleanup
            self.cleanup_timer = threading.Timer(30.0, self.trigger_cleanup)
            self.cleanup_timer.daemon = True
            self.cleanup_timer.start()
            logging.info("Scheduled stream cleanup in 30 seconds if no new clients connect")
    
    def trigger_cleanup(self):
        """Trigger actual cleanup if still no clients"""
        with self.lock:
            if not self.active_clients:
                logging.info("No clients reconnected, triggering stream shutdown")
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
    
    def __init__(self, user_agent: Optional[str] = None):
        self.stream_managers: Dict[str, StreamManager] = {}
        self.stream_buffers: Dict[str, StreamBuffer] = {}
        self.client_managers: Dict[str, ClientManager] = {}
        self.fetch_threads: Dict[str, threading.Thread] = {}
        self.user_agent: str = user_agent or Config.DEFAULT_USER_AGENT
        self.lock: threading.RLock = threading.RLock()  # Add a thread-safe lock

    def initialize_channel(self, url, channel_id):
        """Initialize a new channel with the given URL"""
        with self.lock:
            # Create buffer and stream manager
            self.stream_buffers[channel_id] = StreamBuffer()
            self.stream_managers[channel_id] = StreamManager(
                url, 
                self.stream_buffers[channel_id],
                user_agent=self.user_agent
            )
            
            # Pass channel_id to ClientManager constructor
            self.client_managers[channel_id] = ClientManager(channel_id=channel_id)
            
            # Start a thread to fetch from the stream
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
            while manager.running:
                try:
                    # Fetch next chunk of data
                    manager.fetch_chunk()
                    
                    # Check for client activity and possibly stop if no clients
                    with self.lock:
                        if channel_id in self.client_managers:
                            client_count = len(self.client_managers[channel_id].active_clients)

                            if client_count == 0:
                                # Check if we've been running with no clients for a while
                                if not hasattr(manager, 'no_clients_since'):
                                    manager.no_clients_since = time.time()
                                elif time.time() - manager.no_clients_since > 60:  # 60 second timeout
                                    logging.info(f"No clients for channel {channel_id} for 60 seconds, stopping")
                                    manager.stop()
                            else:
                                # Reset the counter
                                if hasattr(manager, 'no_clients_since'):
                                    delattr(manager, 'no_clients_since')
                        
                except Exception as e:
                    if manager.running:
                        logging.error(f"Error fetching from stream: {e}")
                        
                        # If we lose connection but are still supposed to be running,
                        # try to reconnect after a short delay
                        if not manager.connected:
                            time.sleep(2)
                            manager.connect()
                
                # Small delay to prevent tight CPU loop
                time.sleep(0.01)
                
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
