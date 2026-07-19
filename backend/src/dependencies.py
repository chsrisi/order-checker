from fastapi import Depends, HTTPException
from .services.auth_service import get_current_user
from .models import User


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    return current_user


__all__ = ["get_current_user", "require_admin"]
