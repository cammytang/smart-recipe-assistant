from fastapi.responses import JSONResponse


class AuthError(Exception):
    def __init__(self, status, code, message, headers=None):
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def error_response(error):
    return JSONResponse(
        status_code=error.status,
        content={'error': {'code': error.code, 'message': error.message}},
        headers={'Cache-Control': 'no-store', **error.headers},
    )
