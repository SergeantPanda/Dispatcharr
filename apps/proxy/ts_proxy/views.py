import json
import threading
import logging
import redis
import time
import os
from django.http import StreamingHttpResponse, JsonResponse, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .server import ProxyServer
from django.conf import settings

# Import the persistent lock that's already in your project
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
        decode_responses=True
    )
    redis_client.ping()  # Test connection
    logger.info("Redis connection established for TS proxy")
except Exception as e:
    logger.warning(f"Redis connection failed: {e} - worker coordination will be limited")
    redis_client = None

@csrf_exempt
@require_http_methods(["GET"]) 
def stream_ts(request, channel_id):
    """Stream TS content to clients"""
    logger.debug(f"Received stream request for {channel_id}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    
    try:
        # Find the URL for this channel from various sources
        url = None
        
        # 1. Check URL parameter (highest priority)
        url_from_param = request.GET.get('url')
        if url_from_param:
            url = url_from_param
            # Store in memory for future use
            channel_urls[channel_id] = url
            # Store in Redis for other workers
            if redis_client:
                redis_client.set(f"ts_proxy:channel_url:{channel_id}", url)
        
        # 2. Check memory cache
        elif channel_id in channel_urls:
            url = channel_urls[channel_id]
            
        # 3. Check Redis (if available)
        elif redis_client:
            url = redis_client.get(f"ts_proxy:channel_url:{channel_id}")
            if url:
                # Store in memory for future use
                channel_urls[channel_id] = url
        
        logger.info(f"URL for channel {channel_id}: {url}")
        
        # Check if channel exists in this worker
        if channel_id not in proxy_server.stream_managers:
            # Channel not initialized in this worker
            if not url:
                logger.error(f"No URL found for channel {channel_id} - cannot initialize")
                return HttpResponseNotFound(f"Channel {channel_id} not found")
            
            # Initialize the channel in this worker
            logger.info(f"Initializing channel {channel_id} in current worker")
            proxy_server.initialize_channel(url, channel_id)
            
            # Wait for channel to be ready (with timeout)
            max_wait = 10
            start_time = time.time()
            while time.time() - start_time < max_wait:
                if channel_id in proxy_server.stream_managers and proxy_server.stream_managers[channel_id].connected:
                    logger.info(f"Channel {channel_id} ready for streaming")
                    break
                time.sleep(0.2)
        
        # Make sure channel is initialized
        if channel_id not in proxy_server.stream_managers:
            logger.error(f"Failed to initialize channel {channel_id}")
            return JsonResponse({'error': 'Failed to initialize channel'}, status=500)
        
        # Generate streaming response
        def generate():
            client_id = id(threading.current_thread())
            logger.info(f"Client {client_id} connecting to channel {channel_id}")
            
            try:
                # Add client to manager
                if channel_id in proxy_server.client_managers:
                    proxy_server.client_managers[channel_id].add_client(client_id)
                else:
                    logger.error(f"No client manager found for channel {channel_id}")
                    return
                
                buffer = proxy_server.stream_buffers.get(channel_id)
                if not buffer:
                    logger.error(f"No buffer found for channel {channel_id}")
                    return
                
                last_index = 0
                
                while True:
                    try:
                        # Check if channel still exists
                        if channel_id not in proxy_server.stream_managers:
                            logger.warning(f"Channel {channel_id} no longer exists")
                            break
                        
                        # Check if new data is available
                        with buffer.lock:
                            if buffer.index > last_index:
                                chunks_behind = buffer.index - last_index
                                start_pos = max(0, len(buffer.buffer) - chunks_behind)
                                
                                for i in range(start_pos, len(buffer.buffer)):
                                    yield buffer.buffer[i]
                                last_index = buffer.index
                        
                        time.sleep(0.1)  # Short sleep between checks
                        
                    except BrokenPipeError:
                        # Client disconnected - this is normal
                        logger.debug(f"Client {client_id} disconnected (broken pipe)")
                        break
                    except ConnectionResetError:
                        # Client disconnected abruptly
                        logger.debug(f"Client {client_id} connection reset")
                        break
                    except Exception as e:
                        logger.error(f"Streaming error for client {client_id}: {e}")
                        break
                    
            except Exception as e:
                logger.error(f"Client {client_id} stream error: {e}")
            finally:
                # Clean up client
                try:
                    if channel_id in proxy_server.client_managers:
                        proxy_server.client_managers[channel_id].remove_client(client_id)
                        logger.info(f"Client {client_id} disconnected from channel {channel_id}")
                except Exception as e:
                    logger.error(f"Error removing client {client_id}: {e}")
        
        # Return streaming response
        response = StreamingHttpResponse(
            generate(),
            content_type='video/MP2T'
        )
        
        # Add headers for proper streaming
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        
        return response
        
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
        
        # Store URL in memory cache
        channel_urls[channel_id] = url
        
        # Use persistent lock to ensure only one worker initializes the stream
        lock_key = f"ts_proxy:channel_lock:{channel_id}"
        lock_acquired = False
        
        try:
            if redis_client:
                # Use persistent lock with 120s timeout
                persistent_lock = PersistentLock(redis_client, lock_key, lock_timeout=120)
                lock_acquired = persistent_lock.acquire()
                
                if lock_acquired:
                    logger.info(f"Acquired lock for channel {channel_id}, initializing stream")
                    # Store URL in Redis for other workers
                    redis_client.set(f"ts_proxy:channel_url:{channel_id}", url)
                    
                    # Initialize the stream in this worker
                    if channel_id in proxy_server.stream_managers:
                        proxy_server.stop_channel(channel_id)
                    
                    proxy_server.initialize_channel(url, channel_id)
                    
                    # Release lock after initialization
                    persistent_lock.release()
                    
                    # Wait for stream to be ready
                    max_wait = 10
                    start_time = time.time()
                    while time.time() - start_time < max_wait:
                        if channel_id in proxy_server.stream_managers and proxy_server.stream_managers[channel_id].connected:
                            break
                        time.sleep(0.2)
                    
                    return JsonResponse({
                        'message': 'Stream initialized and ready',
                        'channel': channel_id,
                        'url': url
                    })
                else:
                    # Another worker is handling this, just store URL
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
                logger.info(f"Channel {channel_id} stopped and resources released")
            else:
                logger.warning(f"Channel {channel_id} not found for cleanup")
    except Exception as e:
        logger.error(f"Error during channel cleanup: {e}", exc_info=True)