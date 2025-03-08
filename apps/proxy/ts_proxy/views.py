import json
import threading
import logging
import redis
import time
import os
from django.http import StreamingHttpResponse, JsonResponse, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .server import ProxyServer, SharedStreamBuffer, StreamManager
from django.conf import settings
from apps.proxy.config import TSConfig as Config
from dispatcharr.persistent_lock import PersistentLock

logger = logging.getLogger(__name__)
proxy_server = ProxyServer()

# Global channel URL cache
channel_urls = {}

# Create Redis client for coordination
redis_client = None
try:
    redis_client = redis.Redis(
        host=getattr(settings, 'REDIS_HOST', 'localhost'),
        port=getattr(settings, 'REDIS_PORT', 6379),
        db=getattr(settings, 'REDIS_DB', 0),
        password=getattr(settings, 'REDIS_PASSWORD', None),
        # Remove decode_responses=True for binary data
        decode_responses=False  # Changed from True
    )
    redis_client.ping()  # Test connection
    logger.info("Redis connection established for TS proxy")
except Exception as e:
    logger.warning(f"Redis connection failed: {e} - worker coordination will be limited")
    redis_client = None

# Update the ProxyServer with the Redis client
proxy_server = ProxyServer(redis_client=redis_client)

@csrf_exempt
@require_http_methods(["GET"]) 
def stream_ts(request, channel_id):
    """Stream TS content to clients"""
    logger.debug(f"Received stream request for {channel_id}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    
    try:
        # Find the URL for this channel 
        url = find_channel_url(request, channel_id)
        logger.info(f"URL for channel {channel_id}: {url}")
        
        # Determine if this worker should stream directly or use shared buffer
        import os
        my_pid = str(os.getpid())
        is_origin_worker = channel_id in proxy_server.stream_managers
        
        # Get active worker from Redis
        active_worker = None
        if redis_client:
            active_worker = redis_client.get(f"ts_proxy:active_channel:{channel_id}")
            if active_worker:
                active_worker = active_worker.decode() if isinstance(active_worker, bytes) else active_worker
        
        # This worker has the stream
        if is_origin_worker:
            logger.debug(f"Channel {channel_id} already streaming in this worker")
            # Update active status
            if redis_client:
                redis_client.set(f"ts_proxy:active_channel:{channel_id}", my_pid, ex=60)
                
        # Another worker has the stream
        elif active_worker and active_worker != my_pid:
            logger.info(f"Channel {channel_id} is streaming in worker {active_worker}")
        
        # No worker has the stream, initialize here
        elif url:
            logger.info(f"Initializing channel {channel_id} in this worker")
            
            # Initialize with appropriate locking
            initialize_with_lock(channel_id, url, my_pid)
            is_origin_worker = True
        else:
            logger.error(f"No URL found for channel {channel_id}")
            return HttpResponseNotFound(f"Channel {channel_id} not found")
        
        # Generate streaming response
        return create_streaming_response(channel_id, is_origin_worker)
        
    except Exception as e:
        logger.error(f"Error in stream_ts: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def initialize_stream(request, channel_id):
    """Initialize a new TS stream"""
    try:
        data = json.loads(request.body)
        url = data.get('url')
        if not url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
        
        logger.info(f"Initializing stream for channel {channel_id} with URL {url}")
        
        # Store URL in memory cache and Redis
        channel_urls[channel_id] = url
        if redis_client:
            redis_client.set(f"ts_proxy:channel_url:{channel_id}", url)
        
        # Check if channel already exists anywhere
        channel_exists = False
        channel_in_this_worker = channel_id in proxy_server.stream_managers
        
        if channel_in_this_worker:
            # Channel exists in this worker - update URL if needed
            channel_exists = True
            current_url = proxy_server.stream_managers[channel_id].url
            if url != current_url:
                logger.info(f"Updating URL for channel {channel_id}: {current_url} -> {url}")
                proxy_server.stream_managers[channel_id].update_url(url)
            else:
                logger.info(f"Channel {channel_id} already using URL {url}")
                
            # Refresh active status
            if redis_client:
                import os
                worker_id = os.getpid()
                redis_client.set(f"ts_proxy:active_channel:{channel_id}", str(worker_id), ex=60)
                
            return JsonResponse({
                'message': 'Stream URL updated',
                'channel': channel_id,
                'url': url,
                'status': 'updated' if url != current_url else 'unchanged'
            })
        
        # Check if channel exists in another worker
        if redis_client:
            worker_id = redis_client.get(f"ts_proxy:active_channel:{channel_id}")
            if worker_id:
                channel_exists = True
                logger.info(f"Channel {channel_id} already exists in worker {worker_id}")
                return JsonResponse({
                    'message': 'Stream already initialized in another worker',
                    'channel': channel_id,
                    'worker': worker_id,
                    'url': url
                })
        
        # Use persistent lock to ensure only one worker initializes the stream
        lock_key = f"ts_proxy:channel_lock:{channel_id}"
        lock_acquired = False
        
        try:
            if redis_client:
                # Use persistent lock with 10s timeout
                persistent_lock = PersistentLock(redis_client, lock_key, lock_timeout=10)
                lock_acquired = persistent_lock.acquire()
                
                if lock_acquired:
                    logger.info(f"Acquired lock for channel {channel_id}, initializing stream")
                    
                    # Register ownership in Redis
                    import os
                    worker_id = os.getpid()
                    redis_client.set(f"ts_proxy:active_channel:{channel_id}", str(worker_id), ex=60)
                    
                    # Initialize the stream in this worker
                    if channel_id in proxy_server.stream_managers:
                        proxy_server.stop_channel(channel_id)
                    
                    proxy_server.initialize_channel(url, channel_id)
                    
                    # Release lock after initialization
                    persistent_lock.release()
                    lock_acquired = False
                    
                    # Wait for stream to be ready
                    max_wait = 10
                    ready = False
                    start_time = time.time()
                    while time.time() - start_time < max_wait:
                        if channel_id in proxy_server.stream_managers and proxy_server.stream_managers[channel_id].connected:
                            ready = True
                            break
                        time.sleep(0.2)
                    
                    return JsonResponse({
                        'message': 'Stream initialized and ready',
                        'channel': channel_id,
                        'url': url,
                        'ready': ready
                    })
                else:
                    # Another worker is handling this
                    logger.info(f"Another worker is initializing channel {channel_id}")
                    return JsonResponse({
                        'message': 'Stream initialization delegated to another worker',
                        'channel': channel_id,
                        'url': url
                    })
            else:
                # No Redis, initialize locally
                if channel_id in proxy_server.stream_managers:
                    proxy_server.stop_channel(channel_id)
                
                proxy_server.initialize_channel(url, channel_id)
                return JsonResponse({
                    'message': 'Stream initialized locally',
                    'channel': channel_id,
                    'url': url
                })
                
        except Exception as e:
            logger.error(f"Error during stream initialization: {e}")
            if lock_acquired and redis_client:
                persistent_lock.release()
            raise
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to initialize stream: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def change_stream(request, channel_id):
    """Change stream URL for existing channel"""
    try:
        data = json.loads(request.body)
        new_url = data.get('url')
        if not new_url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
        
        # Store in memory
        channel_urls[channel_id] = new_url
        
        # Store in Redis for other workers
        if redis_client:
            redis_client.set(f"ts_proxy:channel_url:{channel_id}", new_url)
            
        # Update in local worker if channel exists
        if channel_id in proxy_server.stream_managers:
            manager = proxy_server.stream_managers[channel_id]
            if manager.update_url(new_url):
                logger.info(f"Updated URL for channel {channel_id}")
                return JsonResponse({
                    'message': 'Stream URL updated',
                    'channel': channel_id,
                    'url': new_url
                })
        else:
            # Initialize channel if it doesn't exist
            proxy_server.initialize_channel(new_url, channel_id)
            logger.info(f"Created new channel {channel_id} with URL {new_url}")
            return JsonResponse({
                'message': 'New stream created',
                'channel': channel_id,
                'url': new_url
            })
            
        return JsonResponse({
            'message': 'URL unchanged',
            'channel': channel_id,
            'url': new_url
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to change stream: {e}")
        return JsonResponse({'error': str(e)}, status=500)

def cleanup_channel(channel_id):
    """Stop a channel when no longer needed"""
    logger.info(f"Cleaning up channel {channel_id} after all clients disconnected")
    
    try:
        with proxy_server.lock:
            # Check if channel exists
            if channel_id in proxy_server.stream_managers:
                # Stop the channel
                proxy_server.stop_channel(channel_id)
                
                # Remove Redis markers if available
                if redis_client:
                    try:
                        # Get current marker
                        marker = redis_client.get(f"ts_proxy:active_channel:{channel_id}")
                        
                        # Only delete if this worker owns it
                        import os
                        worker_id = str(os.getpid())
                        
                        if marker == worker_id:
                            # Delete active channel marker
                            redis_client.delete(f"ts_proxy:active_channel:{channel_id}")
                            logger.info(f"Removed active marker for channel {channel_id}")
                        else:
                            logger.info(f"Not removing marker - owned by worker {marker}, we are {worker_id}")
                    except Exception as e:
                        logger.warning(f"Failed to clean Redis markers: {e}")
                
                logger.info(f"Channel {channel_id} stopped and resources released")
            else:
                logger.warning(f"Channel {channel_id} not found for cleanup")
    except Exception as e:
        logger.error(f"Error during channel cleanup: {e}", exc_info=True)

def find_channel_url(request, channel_id):
    """Find URL for a channel from various sources"""
    # URL from request parameter (highest priority)
    url_from_param = request.GET.get('url')
    if url_from_param:
        url = url_from_param
        # Store for future use
        channel_urls[channel_id] = url
        if redis_client:
            redis_client.set(f"ts_proxy:channel_url:{channel_id}", url)
        return url
        
    # URL from memory cache
    if channel_id in channel_urls:
        return channel_urls[channel_id]
        
    # URL from Redis
    if redis_client:
        url = redis_client.get(f"ts_proxy:channel_url:{channel_id}")
        if url:
            url = url.decode() if isinstance(url, bytes) else url
            channel_urls[channel_id] = url
            return url
            
    return None

def initialize_with_lock(channel_id, url, worker_pid):
    """Initialize a channel with proper locking"""
    if redis_client:
        try:
            # Use a short timeout - we don't want to block too long
            lock = PersistentLock(redis_client, f"ts_proxy:init_lock:{channel_id}", lock_timeout=10)
            lock_acquired = lock.acquire()
            
            if lock_acquired:
                try:
                    logger.info(f"Acquired lock for channel {channel_id}")
                    
                    # Double-check if the channel was created while waiting for lock
                    if channel_id not in proxy_server.stream_managers:
                        # Mark this worker as the owner
                        redis_client.set(f"ts_proxy:active_channel:{channel_id}", worker_pid, ex=60)
                        
                        # Check if channel data already exists in Redis
                        index_key = f"ts_proxy:buffer:{channel_id}:index"
                        existing_index = redis_client.get(index_key)
                        
                        # Create buffer object with Redis connection
                        shared_buffer = SharedStreamBuffer(channel_id, redis_client=redis_client)
                        
                        # Initialize the channel
                        proxy_server.initialize_channel(url, channel_id, shared_buffer)
                finally:
                    lock.release()
            else:
                # Another worker is initializing
                logger.info(f"Another worker is initializing channel {channel_id}, waiting")
                time.sleep(1)
        except Exception as e:
            logger.error(f"Error with locking: {e}")
            # Fall back to local initialization
            proxy_server.initialize_channel(url, channel_id)
    else:
        # No Redis, initialize locally
        proxy_server.initialize_channel(url, channel_id)

def create_streaming_response(channel_id, is_origin_worker):
    """Create the streaming response for the client"""
    def generate():
        client_id = id(threading.current_thread())
        
        try:
            # Add to client manager if we're the origin
            if is_origin_worker:
                logger.info(f"Client {client_id} connecting directly to channel {channel_id}")
                proxy_server.client_managers[channel_id].add_client(client_id)
            else:
                logger.info(f"Client {client_id} connecting to shared buffer for channel {channel_id}")
            
            # Get the appropriate buffer
            if is_origin_worker:
                buffer = proxy_server.stream_buffers.get(channel_id)
            else:
                buffer = SharedStreamBuffer(channel_id, redis_client=redis_client)
                
            if not buffer:
                logger.error(f"No buffer found for channel {channel_id}")
                return
                
            # Set up streaming loop variables
            local_index = None  # Start from dynamic position
            empty_reads = 0
            last_data_time = time.time()
            has_sent_data = False
            
            while True:
                try:
                    # Check if stream is still active
                    if is_origin_worker and channel_id not in proxy_server.stream_managers:
                        logger.info(f"Channel {channel_id} no longer exists")
                        break
                    elif not is_origin_worker:
                        active = redis_client and redis_client.get(f"ts_proxy:active_channel:{channel_id}")
                        if not active:
                            logger.info(f"Channel {channel_id} no longer active")
                            break
                    
                    # Get chunks with new dynamic start
                    chunks = buffer.get_chunks(local_index)
                    
                    if chunks:
                        # Reset empty read counter when we get data
                        empty_reads = 0
                        last_data_time = time.time()
                        has_sent_data = True
                        
                        for chunk in chunks:
                            yield chunk
                            
                        # Update local index for next read
                        local_index = buffer.local_index
                        logger.debug(f"Sent {len(chunks)} chunks to client, next index: {local_index}")
                    else:
                        # Increment empty read counter
                        empty_reads += 1
                        
                        # Different timeouts for before/after first data
                        timeout = 30 if not has_sent_data else 10
                        
                        # Give up after too many empty reads or too much time
                        if empty_reads > 150 or (time.time() - last_data_time > timeout):
                            logger.warning(f"No data received for channel {channel_id} for too long, disconnecting")
                            break
                            
                        # Backoff for efficiency
                        sleep_time = min(0.1 * (empty_reads / 10), 0.5)
                        time.sleep(sleep_time)
                
                except BrokenPipeError:
                    logger.debug(f"Client {client_id} disconnected (broken pipe)")
                    break
                except ConnectionResetError: 
                    logger.debug(f"Client {client_id} connection reset")
                    break
                except Exception as e:
                    logger.error(f"Streaming error: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"Client error: {e}")
        finally:
            # Clean up client tracking
            if is_origin_worker and channel_id in proxy_server.client_managers:
                proxy_server.client_managers[channel_id].remove_client(client_id)
            logger.info(f"Client {client_id} disconnected from channel {channel_id}")
    
    # Return streaming response
    response = StreamingHttpResponse(
        generate(),
        content_type='video/MP2T'
    )
    
    # Important headers for streaming
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    
    return response