from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.views.decorators.cache import cache_control
import requests
import logging
import hashlib
import os
from django.conf import settings

logger = logging.getLogger(__name__)

# Create cache directory if it doesn't exist
CACHE_DIR = os.path.join(settings.MEDIA_ROOT, 'image_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

@cache_control(max_age=86400, public=True)  # Cache for 24 hours
def proxy_image(request, url_hash):
    """
    Proxy an image by its URL hash and cache it locally

    The URL should be provided as a GET parameter 'url'
    """
    source_url = request.GET.get('url')

    if not source_url:
        return Http404("No URL provided")

    # Verify that the hash matches the URL to prevent abuse
    computed_hash = hashlib.md5(source_url.encode()).hexdigest()
    if computed_hash != url_hash:
        logger.warning(f"Hash mismatch: {url_hash} != {computed_hash} for {source_url}")
        return Http404("Invalid hash")

    # Check if we have the image cached locally
    cache_path = os.path.join(CACHE_DIR, f"{url_hash}")

    # If cached file exists and is less than 7 days old, serve it
    if os.path.exists(cache_path):
        file_age = time.time() - os.path.getmtime(cache_path)
        if file_age < 7 * 86400:  # 7 days in seconds
            # Let nginx serve the file directly from disk
            response = HttpResponse()
            response['X-Accel-Redirect'] = f'/media/image_cache/{url_hash}'
            response['Content-Type'] = 'image/jpeg'  # Default type, nginx will determine actual type
            return response

    # Otherwise fetch the image
    try:
        response = requests.get(source_url, timeout=10, stream=True)
        response.raise_for_status()

        # Save to cache
        with open(cache_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        # Let nginx serve the newly cached file
        response = HttpResponse()
        response['X-Accel-Redirect'] = f'/media/image_cache/{url_hash}'
        response['Content-Type'] = response.headers.get('Content-Type', 'image/jpeg')
        return response

    except Exception as e:
        logger.error(f"Error proxying image {source_url}: {str(e)}")
        # Fallback to redirect to the original URL
        return HttpResponseRedirect(source_url)
