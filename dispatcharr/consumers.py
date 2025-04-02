import json
from channels.generic.websocket import AsyncWebsocketConsumer
import re, logging

logger = logging.getLogger(__name__)

class MyWebSocketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.room_name = "updates"
        await self.channel_layer.group_add(self.room_name, self.channel_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)

        if data["type"] == "m3u_profile_test":
            from apps.proxy.ts_proxy.url_utils import transform_url

            def replace_with_mark(match):
                # Wrap the match in <mark> tags
                return f"<mark>{match.group(0)}</mark>"

            # Apply the transformation using the replace_with_mark function
            try:
                search_preview = re.sub(data["search"], replace_with_mark, data["url"])
            except Exception as e:
                search_preview = data["search"]
                logger.error(f"Failed to generate replace preview: {e}")

            result = transform_url(data["url"], data["search"], data["replace"])
            await self.send(text_data=json.dumps({
                "data": {
                   'type': 'm3u_profile_test',
                    'search_preview': search_preview,
                    'result': result,
                }
            }))

    async def update(self, event):
        await self.send(text_data=json.dumps(event))
