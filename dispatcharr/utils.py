# dispatcharr/utils.py
from django.http import JsonResponse
from django.core.exceptions import ValidationError
import redis
from django.conf import settings

def json_error_response(message, status=400):
    """Return a standardized error JSON response."""
    return JsonResponse({'success': False, 'error': message}, status=status)

def json_success_response(data=None, status=200):
    """Return a standardized success JSON response."""
    response = {'success': True}
    if data is not None:
        response.update(data)
    return JsonResponse(response, status=status)

def validate_logo_file(file):
    """Validate uploaded logo file size and MIME type."""
    valid_mime_types = ['image/jpeg', 'image/png', 'image/gif']
    if file.content_type not in valid_mime_types:
        raise ValidationError('Unsupported file type. Allowed types: JPEG, PNG, GIF.')
    if file.size > 2 * 1024 * 1024:
        raise ValidationError('File too large. Max 2MB.')

def release_all_proxy_locks():
    """Release any stuck proxy locks"""
    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB
    )
    
    # Clear any stuck locks
    pattern = "proxy:lock:*"
    for key in redis_client.scan_iter(pattern):
        redis_client.delete(key)

