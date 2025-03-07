import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import dispatcharr.routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(dispatcharr.routing.websocket_urlpatterns)
    ),
})
