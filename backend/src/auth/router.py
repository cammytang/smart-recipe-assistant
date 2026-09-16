import logging
import traceback

from fastapi import APIRouter, Depends, Request, Response, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from psycopg import OperationalError, InterfaceError
from psycopg_pool import PoolClosed, PoolTimeout, TooManyRequests
from .dependencies import check_write_request, get_current_user
from .errors import AuthError, error_response
from .schemas import Credentials, UserResponse, RegisteredUser, SessionResponse, ErrorResponse
from .security import COOKIE_NAME

logger = logging.getLogger(__name__)


class AuthRoute(APIRoute):
    request_guard = staticmethod(check_write_request)

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                self.request_guard(request)
                response = await original(request)
                response.headers['Cache-Control'] = 'no-store'
                return response
            except AuthError as error:
                return error_response(error)
            except HTTPException:
                raise
            except RequestValidationError:
                return error_response(AuthError(422, 'VALIDATION_ERROR', '请求格式或字段不符合要求'))
            except (OperationalError, InterfaceError, PoolClosed, PoolTimeout, TooManyRequests):
                return error_response(AuthError(503, 'SERVICE_UNAVAILABLE', '数据库服务暂时不可用'))
            except Exception as error:
                # Do not emit request bodies, cookies, SQL parameters or exception text.
                frames = traceback.extract_tb(error.__traceback__)
                logger.error('Unhandled route error: %s; frames=%s', type(error).__name__,
                             ' -> '.join(f'{frame.filename}:{frame.lineno} ({frame.name})'
                                         for frame in frames))
                return error_response(AuthError(500, 'INTERNAL_ERROR', '服务内部错误'))
        return handler


router = APIRouter(prefix='/api/v1', tags=['Authentication'], route_class=AuthRoute,
                   responses={status: {'model': ErrorResponse} for status in (401, 403, 409, 415, 422, 429, 500, 503)})


@router.post('/users', response_model=RegisteredUser, status_code=201)
def register(credentials: Credentials, request: Request):
    return request.app.state.auth_service.register(credentials)


@router.post('/sessions', response_model=SessionResponse, status_code=201)
def login(credentials: Credentials, request: Request, response: Response):
    request.app.state.auth_limiter.hit(('username', credentials.username), 10, 60)
    result, token = request.app.state.auth_service.login(credentials, request.cookies.get(COOKIE_NAME))
    config = request.app.state.auth_config
    response.set_cookie(COOKIE_NAME, token, max_age=config.session_ttl, httponly=True,
                        secure=config.cookie_secure, samesite='lax', path='/')
    return result


@router.get('/users/me', response_model=UserResponse)
def current_user(user=Depends(get_current_user)):
    return user


@router.delete('/sessions/current', status_code=204)
def logout(request: Request):
    request.app.state.auth_service.logout(request.cookies.get(COOKIE_NAME))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path='/', httponly=True,
                           secure=request.app.state.auth_config.cookie_secure, samesite='lax')
    return response
