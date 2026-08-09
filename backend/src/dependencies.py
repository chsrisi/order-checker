from fastapi import Depends, HTTPException
from .services.auth_service import get_current_user, require_admin
from .models import User


__all__ = ["get_current_user", "require_admin"]
