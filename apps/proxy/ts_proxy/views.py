import json
import threading
import logging
import time
import redis
from django.http import StreamingHttpResponse, JsonResponse, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from apps.proxy.config import TSConfig as Config
from .server import ProxyServer

logger = logging.getLogger(__name__)

# Store the last known URLs for channels to support reconnection (in-memory fallback)
channel_urls = {}
# Track active channels in memory as fallback
active_channels = set()

# Make proxy_server a global singleton
proxy_server = ProxyServer()

# Initialize Redis connection with error handling
redis_client = None
redis_available = False

def get_redis():
    """Get Redis connection with fallback"""
    global redis_client, redis_available
    if redis_client is None:
        try:
            redis_client = redis.Redis(
                host=getattr(settings, 'REDIS_HOST', 'localhost'),
                port=getattr(settings, 'REDIS_PORT', 6379),
                db=getattr(settings, 'REDIS_DB', 0),
                password=getattr(settings, 'REDIS_PASSWORD', None),  # Add password support
                socket_timeout=3,
                socket_connect_timeout=3,
                retry_on_timeout=True,
                decode_responses=True,
                health_check_interval=5  # Add health check
            )
            # Test connection with a simple string value
            redis_client.set('test_key', 'test_value')
            redis_client.get('test_key')
            redis_available = True
            logger.info("Redis connection successful")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}")
            redis_available = False
    return redis_client

def set_redis_key(key, value, expire=None):
    """Set Redis key with error handling"""
    if not redis_available:
        return False
    try:
        # Make sure we're storing string values
        value_str = str(value)
        get_redis().set(key, value_str, ex=expire)
        logger.debug(f"Redis: Set {key}={value_str} (expire={expire})")
        return True
    except Exception as e:
        logger.warning(f"Redis set_key error: {e}")
        return False

def get_redis_key(key):
    """Get Redis key with error handling"""
    if not redis_available:
        return None
    try:
        value = get_redis().get(key)
        logger.debug(f"Redis: Get {key}={value}")
        return value
    except Exception as e:
        logger.warning(f"Redis get_key error: {e}")
        return None

def delete_redis_key(key):
    """Delete Redis key with error handling"""
    if not redis_available:
        return False
    try:
        get_redis().delete(key)
        return True
    except Exception as e:
        logger.warning(f"Redis delete_key error: {e}")
        return False

def sync_url_to_memory(channel_id, url):
    """Sync URL to memory store for channel from any source"""
    if url:
        channel_urls[channel_id] = url
        active_channels.add(channel_id)
        logger.debug(f"Synchronized URL for {channel_id} to memory store")

def sync_url_to_all(channel_id, url):
    """Sync URL to all storage locations with aggressive retries"""
    try:
        # Always sync to memory first
        channel_urls[channel_id] = url
        active_channels.add(channel_id)
        
        # Aggressive Redis sync with multiple retries
        if redis_available:
            success = False
            for attempt in range(5):  # Try up to 5 times
                try:
                    # Set both URL and active status
                    url_key = f"ts_proxy:channel_url:{channel_id}"
                    active_key = f"ts_proxy:channel_active:{channel_id}"
                    
                    client = get_redis()
                    pipe = client.pipeline()
                    pipe.set(url_key, url)
                    pipe.set(active_key, "1")
                    pipe.execute()
                    
                    # Verify it was actually set
                    stored_url = client.get(url_key)
                    if (stored_url == url):
                        logger.info(f"URL successfully synced to Redis: {url}")
                        success = True
                        break
                    else:
                        logger.warning(f"Redis verification failed: got {stored_url}, expected {url}")
                except Exception as e:
                    logger.warning(f"Redis sync attempt {attempt+1} failed: {e}")
                    
                # Wait before retrying
                time.sleep(0.2)
                
            if not success:
                logger.error("All Redis sync attempts failed")
        
        return True
    except Exception as e:
        logger.error(f"URL sync error: {e}", exc_info=True)
        return False

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
        
        # Aggressively sync URL to all storage locations
        sync_url_to_all(channel_id, url)
        
        # Stop any existing channel with this ID
        if channel_id in proxy_server.stream_managers:
            proxy_server.stop_channel(channel_id)
            
        # Initialize channel
        proxy_server.initialize_channel(url, channel_id)
        
        # Wait for channel to be ready (with timeout)
        start_time = time.time()
        timeout = 30.0  # 30 second timeout
        
        while (time.time() - start_time) < timeout:
            if proxy_server.is_channel_ready(channel_id):
                logger.info(f"Channel {channel_id} initialized and ready")
                # Setup client manager for auto-cleanup when needed
                if channel_id in proxy_server.client_managers:
                    proxy_server.client_managers[channel_id].start_cleanup_timer(proxy_server, channel_id)
                return JsonResponse({
                    'status': 'success', 
                    'message': 'Stream initialized'
                })
            time.sleep(0.1)
            
        logger.error(f"Initialization timed out for channel {channel_id}")
        proxy_server.stop_channel(channel_id)
        delete_redis_key(f"ts_proxy:channel_active:{channel_id}")
        active_channels.discard(channel_id)
        return JsonResponse({'error': 'Initialization timed out'}, status=504)
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to initialize channel: {str(e)}", exc_info=True)
        if channel_id in proxy_server.stream_managers:
            proxy_server.stop_channel(channel_id)
        delete_redis_key(f"ts_proxy:channel_active:{channel_id}")
        active_channels.discard(channel_id)
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"]) 
def stream_ts(request, channel_id):
    """Stream TS content to clients"""
    logger.debug(f"Received stream request for {channel_id}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    
    try:
        # First check for URL parameter - highest priority
        url = request.GET.get('url')
        if url:
            logger.info(f"Using URL from query parameter: {url}")
            # Sync this URL to all workers
            sync_url_to_all(channel_id, url)
        else:
            # Try to get URL from memory
            if channel_id in channel_urls:
                url = channel_urls[channel_id]
                logger.info(f"Found URL in memory: {url}")
            
            # Try Redis as backup if not in memory
            elif redis_available:
                try:
                    url_from_redis = get_redis_key(f"ts_proxy:channel_url:{channel_id}")
                    if url_from_redis:
                        url = url_from_redis
                        logger.info(f"Found URL in Redis: {url}")
                        # Sync back to memory
                        channel_urls[channel_id] = url
                except Exception as e:
                    logger.warning(f"Redis URL retrieval failed: {e}")

        # Log what we found             
        logger.debug(f"Available channels in this worker: {list(proxy_server.stream_managers.keys())}")
        
        # If we have a URL but no channel, initialize it
        if url and channel_id not in proxy_server.stream_managers:
            logger.info(f"Initializing channel {channel_id} with URL: {url}")
            proxy_server.initialize_channel(url, channel_id)
            
            # Wait for ready with timeout
            start_time = time.time()
            while time.time() - start_time < 10:
                if proxy_server.is_channel_ready(channel_id):
                    logger.info(f"Channel {channel_id} ready for streaming")
                    break
                time.sleep(0.1)
        
        # Final check for channel
        if channel_id not in proxy_server.stream_managers:
            if not url:
                logger.error(f"No URL found for channel {channel_id} - cannot initialize")
                return HttpResponseNotFound(f"Channel {channel_id} URL not found")
            else:
                logger.error(f"Failed to initialize channel {channel_id}")
                return HttpResponseNotFound(f"Channel {channel_id} failed to initialize")
                
        # Get components to verify channel is fully available
        manager = proxy_server.stream_managers.get(channel_id)
        buffer = proxy_server.stream_buffers.get(channel_id)
        client_manager = proxy_server.client_managers.get(channel_id)
        
        # Full detail debug info for troubleshooting
        logger.debug(f"Channel {channel_id} state in worker:")
        logger.debug(f"- Manager exists: {manager is not None}")
        logger.debug(f"- Buffer exists: {buffer is not None}")
        logger.debug(f"- Client Manager exists: {client_manager is not None}")
        if manager:
            logger.debug(f"- Manager running: {manager.running}")
            logger.debug(f"- Manager connected: {manager.connected}")
            logger.debug(f"- Manager ready_event: {manager.ready_event.is_set()}")
        if buffer:
            logger.debug(f"- Buffer size: {len(buffer.buffer)}")
        if client_manager:
            logger.debug(f"- Client count: {len(client_manager.active_clients)}")
        
        if not all([manager, buffer, client_manager]):
            logger.error(f"Missing components for channel {channel_id}")
            return HttpResponseNotFound(f"Channel {channel_id} components not found")
        
        # Verify channel is actually ready before streaming
        if not proxy_server.is_channel_ready(channel_id):
            logger.error(f"Channel {channel_id} exists but not ready for streaming")
            return JsonResponse({"error": "Channel exists but not ready"}, status=503)

        # Generate streaming response
        def generate():
            client_id = id(threading.current_thread())
            logger.info(f"Client {client_id} connecting to channel {channel_id}")
            
            try:
                # Add the client to the manager
                proxy_server.client_managers[channel_id].add_client(client_id)
                
                # Track active client in Redis with expiration if available
                if redis_available:
                    set_redis_key(
                        f"ts_proxy:client:{channel_id}:{client_id}", 
                        "1",
                        expire=300  # 5 minute expiration as safety
                    )
                
                # Start with position 0
                start_pos = 0
                
                logger.debug(f"Starting stream for client {client_id} from position {start_pos}")
                
                while True:
                    # Refresh activity tracking periodically
                    if redis_available:
                        set_redis_key(
                            f"ts_proxy:client:{channel_id}:{client_id}", 
                            "1",
                            expire=300
                        )
                    
                    # Check if channel still exists locally
                    if channel_id not in proxy_server.stream_managers:
                        logger.error(f"Channel {channel_id} disappeared from local worker during streaming")
                        break
                    
                    chunks = buffer.get_chunks(start_pos)
                    if not chunks:
                        # No new chunks, wait a bit
                        time.sleep(0.1)
                        continue
                    
                    # Update position for next iteration
                    start_pos += len(chunks)
                    
                    # Yield all chunks
                    for chunk in chunks:
                        yield chunk
                    
            except Exception as e:
                logger.error(f"Streaming error for client {client_id}: {e}", exc_info=True)
            finally:
                # Clean up client
                try:
                    delete_redis_key(f"ts_proxy:client:{channel_id}:{client_id}")
                    
                    if channel_id in proxy_server.client_managers:
                        proxy_server.client_managers[channel_id].remove_client(client_id)
                        logger.info(f"Client {client_id} disconnected from channel {channel_id}")
                except Exception as e:
                    logger.error(f"Error removing client {client_id}: {e}")

        # Create streaming response
        response = StreamingHttpResponse(
            generate(),
            content_type='video/MP2T'
        )
        
        # Add important headers for streaming
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        response['X-Accel-Buffering'] = 'no'
        
        return response

    except Exception as e:
        logger.error(f"Error in stream_ts: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
    
@csrf_exempt
@require_http_methods(["POST"])
def change_stream(request, channel_id):
    """Change stream URL for existing channel"""
    try:
        if channel_id not in proxy_server.stream_managers:
            return JsonResponse({'error': 'Channel not found'}, status=404)
            
        data = json.loads(request.body)
        new_url = data.get('url')
        if not new_url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
            
        manager = proxy_server.stream_managers[channel_id]
        if manager.update_url(new_url):
            return JsonResponse({
                'message': 'Stream URL updated',
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

@csrf_exempt
@require_http_methods(["GET"])
def channel_status(request, channel_id):
    """Debug endpoint to check channel state"""
    logger.info(f"Checking status for channel {channel_id}")
    try:
        with proxy_server.lock:
            status = {
                'exists': channel_id in proxy_server.stream_managers,
                'initialized': channel_id in proxy_server._initialization_status,
                'ready_event': False,
                'connected': False,
                'has_buffer': False,
                'clients': 0,
                'buffer_size': 0,
                'retry_count': 0
            }
            
            if channel_id in proxy_server.stream_managers:
                manager = proxy_server.stream_managers[channel_id]
                buffer = proxy_server.stream_buffers.get(channel_id)
                client_manager = proxy_server.client_managers.get(channel_id)
                ready_event = proxy_server._channel_ready_events.get(channel_id)
                
                status.update({
                    'ready_event': ready_event.is_set() if ready_event else False,
                    'connected': manager.connected,
                    'has_buffer': bool(buffer and buffer.buffer),
                    'buffer_size': len(buffer.buffer) if buffer else 0,
                    'clients': len(client_manager.active_clients) if client_manager else 0,
                    'retry_count': manager.retry_count
                })
                
            status['ready'] = all([
                status['exists'],
                status['initialized'],
                status['connected'],
                status['has_buffer'],
                status['ready_event']
            ])
            
            logger.debug(f"Status for channel {channel_id}: {status}")
            return JsonResponse(status)
            
    except Exception as e:
        logger.error(f"Error checking channel status: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def channel_health(request, channel_id):
    """Health check endpoint that ensures channel is fully ready across workers"""
    logger.info(f"Health check for channel {channel_id}")
    
    try:
        # Get URL from Redis or memory
        url_in_redis = get_redis_key(f"ts_proxy:channel_url:{channel_id}")
        url = url_in_redis or channel_urls.get(channel_id)
        
        # If channel doesn't exist locally but we have a URL, initialize it
        if channel_id not in proxy_server.stream_managers and url:
            logger.info(f"Initializing channel {channel_id} from health check")
            proxy_server.initialize_channel(url, channel_id)
            # Wait briefly for it to initialize
            time.sleep(3)
        
        # Check status and return health info
        status = {
            'channel_id': channel_id,
            'exists_locally': channel_id in proxy_server.stream_managers,
            'exists_in_redis': bool(get_redis_key(f"ts_proxy:channel_active:{channel_id}")),
            'url_in_redis': bool(url_in_redis),
            'url_in_memory': channel_id in channel_urls,
            'ready': proxy_server.is_channel_ready(channel_id) if channel_id in proxy_server.stream_managers else False
        }
        
        if not status['exists_locally'] or not status['ready']:
            return JsonResponse(status, status=503)  # Service Unavailable
            
        return JsonResponse(status)
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET", "POST"])
def preload_channel(request, channel_id):
    """Preload channel in worker process before streaming"""
    try:
        # First try to get URL from request
        if request.method == "POST":
            try:
                data = json.loads(request.body)
                url = data.get('url')
            except:
                url = None
        else:
            url = request.GET.get('url')
            
        # If no URL in request, try existing sources
        if not url:
            if redis_available:
                url = get_redis_key(f"ts_proxy:channel_url:{channel_id}")
            
            if not url and channel_id in channel_urls:
                url = channel_urls[channel_id]
                
        if not url:
            return JsonResponse({
                'success': False,
                'message': 'No URL available for channel'
            }, status=404)
            
        # Store URL in all places
        sync_url_to_memory(channel_id, url)
        if redis_available:
            set_redis_key(f"ts_proxy:channel_url:{channel_id}", url)
            set_redis_key(f"ts_proxy:channel_active:{channel_id}", "1")
            
        # Initialize channel in this worker if needed
        if channel_id not in proxy_server.stream_managers:
            logger.info(f"Preloading channel {channel_id} with URL: {url}")
            proxy_server.initialize_channel(url, channel_id)
            
            # Wait for readiness with timeout
            start_time = time.time()
            timeout = 5.0
            ready = False
            
            while (time.time() - start_time) < timeout:
                if proxy_server.is_channel_ready(channel_id):
                    ready = True
                    break
                time.sleep(0.1)
                
            return JsonResponse({
                'success': True,
                'channel': channel_id,
                'ready': ready,
                'message': 'Channel preloaded successfully' if ready else 'Channel initializing'
            })
        
        # Channel already exists in this worker
        return JsonResponse({
            'success': True,
            'channel': channel_id,
            'ready': proxy_server.is_channel_ready(channel_id),
            'message': 'Channel already loaded in this worker'
        })
        
    except Exception as e:
        logger.error(f"Preload error: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)