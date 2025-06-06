from django.urls import path
from . import views

app_name = 'images'

urlpatterns = [
    path('proxy/<str:url_hash>', views.proxy_image, name='proxy'),
]
