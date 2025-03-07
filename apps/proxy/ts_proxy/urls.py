from django.urls import path
from . import views

app_name = 'ts_proxy'

urlpatterns = [
    path('stream/<str:channel_id>', views.stream_ts, name='stream'),
    path('initialize/<str:channel_id>', views.initialize_stream, name='initialize'),
    path('status/<str:channel_id>', views.channel_status, name='status'),
    path('health/<str:channel_id>', views.channel_health, name='health'),  
    path('preload/<str:channel_id>', views.preload_channel, name='preload'),  # Add this
]