from fastapi import HTTPException
from fastapi.responses import JSONResponse


class UploadSizeLimitMiddleware:
    """
    Rejects request bodies larger than max_bytes on the given paths with a 413,
    before they are read: straight away when the Content-Length header is too
    big, otherwise as soon as the bytes received pass the limit.
    """

    def __init__(self, app, max_bytes: int, paths: tuple, detail: str):
        self.app = app
        self.max_bytes = max_bytes
        self.paths = paths
        self.detail = detail

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] not in self.paths:
            await self.app(scope, receive, send)
            return

        content_length = dict(scope["headers"]).get(b"content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            response = JSONResponse({"detail": self.detail}, status_code=413)
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI re-raises HTTPExceptions from body parsing, so this becomes a 413.
                    raise HTTPException(status_code=413, detail=self.detail)
            return message

        await self.app(scope, limited_receive, send)
