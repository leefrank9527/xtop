from aiohttp import web, WSMsgType


async def index(request: web.Request):
    return web.json_response({
        "status": "ok",
        "message": "Hello from HTTP"
    })
