import json
import threading
import logging
import time
import os
from django.http import StreamingHttpResponse, JsonResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from apps.proxy.config import TSConfig as Config
from .server import ProxyServer

logger = logging.getLogger(__name__)
proxy_server = ProxyServer()

# Add this global dictionary to store channel URLs
channel_urls = {}

# Flag to determine if this worker should handle proxy operations
is_master_worker = False

def determine_master_worker():
    """Check if current worker should handle proxy operations"""
    try:
        # Try to get worker ID from uwsgi - only available when running under uwsgi
        try:
            import uwsgi
            # Log all worker IDs to debug
            worker_id = uwsgi.worker_id()
            worker_count = uwsgi.numproc
            logger.info(f"Running with uWSGI worker_id={worker_id} of {worker_count} workers")
            
            # IMPORTANT: In uWSGI, worker IDs are typically 1-indexed, but let's be flexible
            # Use the LAST worker as master to ensure we have one
            return worker_id == worker_count
        except ImportError:
            # Running outside of uwsgi (development or command)
            logger.info("Not running under uWSGI - assuming primary worker role")
            return True
    except Exception as e:
        logger.warning(f"Failed to determine worker status: {e}")
        # Default to handling requests if detection fails
        return True

# Initialize the master worker flag
try:
    is_master_worker = determine_master_worker()
    logger.info(f"Proxy worker initialization: is_master_worker={is_master_worker}")
except Exception as e:
    logger.warning(f"Exception during worker detection: {e}")
    is_master_worker = True  # Default to true if we can't determine

@csrf_exempt
@require_http_methods(["POST"])
def initialize_stream(request, channel_id):
    """Initialize a new TS stream"""
    try:
        # Non-master workers redirect to the master worker
        if not is_master_worker:
            logger.info(f"Non-master worker redirecting stream initialization for {channel_id}")
            return JsonResponse({
                'status': 'redirect',
                'message': 'Request handled by secondary worker',
                'master_worker': False
            })
        
        # Parse the request body
        data = json.loads(request.body)
        url = data.get('url')
        if not url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
        
        # Store URL in memory
        channel_urls[channel_id] = url
        
        logger.info(f"Master worker initializing stream for channel {channel_id} with URL {url}")
        
        # Initialize the channel
        proxy_server.initialize_channel(url, channel_id)
        
        # Wait for connection to be established
        manager = proxy_server.stream_managers[channel_id]
        wait_start = time.time()
        while not manager.connected:
            if time.time() - wait_start > Config.CONNECTION_TIMEOUT:
                proxy_server.stop_channel(channel_id)
                return JsonResponse({
                    'error': 'Connection timeout'
                }, status=504)
            if not manager.should_retry():
                proxy_server.stop_channel(channel_id)
                return JsonResponse({
                    'error': 'Failed to connect'
                }, status=502)
            time.sleep(0.1)
            
        return JsonResponse({
            'message': 'Stream initialized and connected',
            'channel': channel_id,
            'url': url,
            'master_worker': True
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to initialize stream: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def stream_ts(request, channel_id):
    """Stream TS content to clients"""
    logger.debug(f"Received stream request for {channel_id}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    
    # Non-master workers redirect to the master worker
    if not is_master_worker:
        redirect_url = f"/proxy/ts/stream/{channel_id}"
        
        # Preserve URL parameter if present
        url_param = request.GET.get('url')
        if url_param:
            redirect_url += f"?url={url_param}"
            
        logger.info(f"Non-master worker redirecting to master worker for channel {channel_id}")
        return HttpResponseRedirect(redirect_url)
    
    # Master worker handles the actual streaming logic
    try:
        # Get channel URL from various sources
        url = None
        url_sources = []
        
        # Check URL parameter (highest priority)
        url_from_param = request.GET.get('url')
        if url_from_param:
            url = url_from_param
            url_sources.append("parameter")
            logger.info(f"Using URL from request parameter: {url}")
            # Store in memory for future use
            channel_urls[channel_id] = url
            
        # Check memory
        elif channel_id in channel_urls:
            url = channel_urls[channel_id]
            url_sources.append("memory")
            logger.info(f"Found URL in memory: {url}")
            
        # Log what we found
        logger.info(f"URL for channel {channel_id} found in: {', '.join(url_sources) if url_sources else 'nowhere'}")
        
        # Initialize channel if needed and URL is available
        if url and channel_id not in proxy_server.stream_managers:
            logger.info(f"Master worker initializing channel {channel_id} with URL: {url}")
            proxy_server.initialize_channel(url, channel_id)
            
            # Wait for channel to be ready with timeout
            start_time = time.time()
            while time.time() - start_time < 10:
                if proxy_server.is_channel_ready(channel_id):
                    logger.info(f"Channel {channel_id} ready for streaming")
                    break
                time.sleep(0.1)
        
        # Check if channel exists in this worker - USE LOCK HERE
        available_channels = []
        with proxy_server.lock:  # Now this will work with the added lock attribute
            available_channels = list(proxy_server.stream_managers.keys())
            
        logger.debug(f"Available channels in this worker: {available_channels}")
        
        if channel_id not in available_channels:
            logger.error(f"No URL found for channel {channel_id} - cannot initialize")
            return JsonResponse({'error': 'Channel not found'}, status=404)
        
        # Debug state information - SAFE ACCESS WITH LOCK
        with proxy_server.lock:
            manager = proxy_server.stream_managers.get(channel_id)
            buffer = proxy_server.stream_buffers.get(channel_id)
            client_manager = proxy_server.client_managers.get(channel_id)
        
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
        
        # Generate streaming response
        def generate():
            client_id = id(threading.current_thread())
            logger.info(f"Client {client_id} connecting to channel {channel_id}")
            
            try:
                # Add the client to the manager
                proxy_server.client_managers[channel_id].add_client(client_id)
                
                # Start with position 0
                start_pos = 0
                
                logger.debug(f"Starting stream for client {client_id} from position {start_pos}")
                
                while True:
                    # Check if channel still exists
                    if channel_id not in proxy_server.stream_managers:
                        logger.error(f"Channel {channel_id} disappeared during streaming")
                        break
                        
                    # Get chunks from buffer
                    chunks = proxy_server.stream_buffers[channel_id].get_chunks(start_pos)
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
                if channel_id in proxy_server.client_managers:
                    proxy_server.client_managers[channel_id].remove_client(client_id)
                    logger.info(f"Client {client_id} disconnected from channel {channel_id}")
        
        # Return the streaming response
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
def change_stream(request, channel_id):
    """Change stream URL for existing channel"""
    try:
        # Non-master workers redirect to the master worker
        if not is_master_worker:
            logger.info(f"Non-master worker redirecting change_stream for {channel_id}")
            return JsonResponse({
                'status': 'redirect',
                'message': 'Request handled by secondary worker',
                'master_worker': False
            })
            
        # Parse the request body
        data = json.loads(request.body)
        new_url = data.get('url')
        if not new_url:
            return JsonResponse({'error': 'No URL provided'}, status=400)
        
        # Update URL in memory
        channel_urls[channel_id] = new_url
            
        if channel_id not in proxy_server.stream_managers:
            return JsonResponse({'error': 'Channel not found'}, status=404)
            
        manager = proxy_server.stream_managers[channel_id]
        if manager.update_url(new_url):
            return JsonResponse({
                'message': 'Stream URL updated',
                'channel': channel_id,
                'url': new_url,
                'master_worker': True
            })
            
        return JsonResponse({
            'message': 'URL unchanged',
            'channel': channel_id,
            'url': new_url,
            'master_worker': True
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Failed to change stream: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def worker_info(request):
    """Debug endpoint to show worker info"""
    try:
        import uwsgi
        worker_id = uwsgi.worker_id()
        worker_count = uwsgi.numproc
        is_master = is_master_worker
    except ImportError:
        worker_id = 0
        worker_count = 1
        is_master = True

    channels_info = []
    with proxy_server.lock:
        for channel_id in proxy_server.stream_managers.keys():
            channel_info = {
                "channel_id": channel_id,
                "url": channel_urls.get(channel_id, "unknown"),
                "manager_running": proxy_server.stream_managers[channel_id].running,
                "manager_connected": proxy_server.stream_managers[channel_id].connected,
                "buffer_size": len(proxy_server.stream_buffers[channel_id].buffer) if channel_id in proxy_server.stream_buffers else 0,
                "clients": list(proxy_server.client_managers[channel_id].active_clients.keys()) if channel_id in proxy_server.client_managers else []
            }
            channels_info.append(channel_info)
    
    # Return detailed information about this worker
    return JsonResponse({
        "worker_id": worker_id,
        "worker_count": worker_count,
        "is_master": is_master,
        "channels": channels_info,
        "memory_channel_urls": list(channel_urls.keys())
    })