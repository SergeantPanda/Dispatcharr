import json
from channels.generic.websocket import AsyncWebsocketConsumer

class MyWebSocketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.room_name = "updates"
        await self.channel_layer.group_add(self.room_name, self.channel_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        print("Received:", data)

    async def m3u_refresh(self, event):
        await self.send(text_data=json.dumps(event))
