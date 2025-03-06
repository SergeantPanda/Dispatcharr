# core/api_views.py

from rest_framework import viewsets, status
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import UserAgent, StreamProfile, CoreSettings
from .serializers import UserAgentSerializer, StreamProfileSerializer, CoreSettingsSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from drf_yasg.utils import swagger_auto_schema
import requests
import os

class UserAgentViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows user agents to be viewed, created, edited, or deleted.
    """
    queryset = UserAgent.objects.all()
    serializer_class = UserAgentSerializer

class StreamProfileViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows stream profiles to be viewed, created, edited, or deleted.
    """
    queryset = StreamProfile.objects.all()
    serializer_class = StreamProfileSerializer

class CoreSettingsViewSet(viewsets.ModelViewSet):
    """
    API endpoint for editing core settings.
    This is treated as a singleton: only one instance should exist.
    """
    queryset = CoreSettings.objects.all()
    serializer_class = CoreSettingsSerializer

@swagger_auto_schema(
    method='get',
    operation_description="Endpoint for environment details",
    responses={200: "Environment variables"}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def environment(request):
    public_ip = None
    try:
        response = requests.get("https://api64.ipify.org?format=json")
        public_ip = response.json().get("ip")
    except requests.RequestException as e:
        return f"Error: {e}"

    return Response({
        'authenticated': True,
        'public_ip': public_ip,
        'env_mode': "dev" if os.getenv('DISPATCHARR_ENV', None) == "dev" else "prod",
    })
