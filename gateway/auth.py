"""
鉴权模块 - JWT 签发与验证
"""

import jwt
import time
from fastapi import Request, HTTPException
from config import get_settings


def create_token(password: str) -> dict:
    """验证密码并签发 JWT"""
    settings = get_settings()
    if password != settings.auth_password:
        raise HTTPException(status_code=401, detail="密码错误")

    expire = int(time.time()) + settings.jwt_expire_days * 86400
    token = jwt.encode(
        {"sub": "dream", "exp": expire},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"token": token, "expires_at": expire}


def verify_token(token: str) -> dict:
    """验证 JWT"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token 无效")


async def auth_required(request: Request):
    """FastAPI 依赖注入 — 需要 JWT 的接口挂这个"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Authorization 头")
    token = auth_header.replace("Bearer ", "")
    return verify_token(token)