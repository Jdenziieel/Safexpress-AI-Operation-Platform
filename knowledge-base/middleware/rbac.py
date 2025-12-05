"""
Role-Based Access Control (RBAC) middleware for FastAPI.
Provides role checking and permission enforcement using JWT claims.
"""
from fastapi import HTTPException, status, Depends
from middleware.jwt_middleware import get_current_user
from typing import List, Optional
from functools import wraps


class Roles:
    """Role constants matching Django User model."""
    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"


# Role hierarchy - higher roles inherit lower role permissions
# Admin can do everything Manager can do, Manager can do everything User can do
ROLE_HIERARCHY = {
    Roles.ADMIN: [Roles.ADMIN, Roles.MANAGER, Roles.USER],
    Roles.MANAGER: [Roles.MANAGER, Roles.USER],
    Roles.USER: [Roles.USER]
}


def get_user_permissions(role: str) -> List[str]:
    """
    Get all permissions for a given role based on hierarchy.
    
    Args:
        role: User's role from JWT
        
    Returns:
        List of roles this user has permission for
    """
    return ROLE_HIERARCHY.get(role.lower(), [Roles.USER])


def require_roles(allowed_roles: List[str]):
    """
    FastAPI dependency that enforces role-based access.
    
    Usage:
        @router.post('/admin-only')
        async def admin_endpoint(
            current_user: dict = Depends(require_roles([Roles.ADMIN]))
        ):
            ...
            
        @router.post('/managers-and-admins')
        async def manager_endpoint(
            current_user: dict = Depends(require_roles([Roles.ADMIN, Roles.MANAGER]))
        ):
            ...
    
    Args:
        allowed_roles: List of roles that can access this endpoint
        
    Returns:
        Dependency function that validates user role
    """
    async def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        # Extract role from JWT (default to 'user' if not present)
        user_role = current_user.get("role", Roles.USER)
        user_email = current_user.get("email") or current_user.get("gmail", "unknown")
        
        print(f"[RBAC] Checking access for user: {user_email}, role: {user_role}")
        print(f"[RBAC] Required roles: {allowed_roles}")
        
        # Get all roles this user has permission for (based on hierarchy)
        user_permissions = get_user_permissions(user_role)
        
        print(f"[RBAC] User permissions: {user_permissions}")
        
        # Check if any of the allowed roles are in user's permission set
        has_permission = any(
            allowed_role.lower() in [p.lower() for p in user_permissions]
            for allowed_role in allowed_roles
        )
        
        if not has_permission:
            print(f"[RBAC] ❌ Access DENIED for {user_email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "access_denied",
                    "message": f"This action requires one of these roles: {', '.join(allowed_roles)}",
                    "your_role": user_role
                }
            )
        
        print(f"[RBAC] ✅ Access GRANTED for {user_email}")
        return current_user
    
    return role_checker


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Convenience dependency for admin-only endpoints.
    
    Usage:
        @router.delete('/dangerous-action')
        async def admin_only(current_user: dict = Depends(require_admin)):
            ...
    """
    user_role = current_user.get("role", Roles.USER)
    
    if user_role.lower() != Roles.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "admin_required",
                "message": "This action requires administrator privileges",
                "your_role": user_role
            }
        )
    
    return current_user


def require_manager_or_above(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Convenience dependency for manager-and-above endpoints.
    
    Usage:
        @router.post('/manage-resource')
        async def manager_action(current_user: dict = Depends(require_manager_or_above)):
            ...
    """
    user_role = current_user.get("role", Roles.USER)
    allowed = [Roles.ADMIN, Roles.MANAGER]
    
    if user_role.lower() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "manager_required", 
                "message": "This action requires manager or administrator privileges",
                "your_role": user_role
            }
        )
    
    return current_user


def get_user_role(current_user: dict = Depends(get_current_user)) -> str:
    """
    Simple dependency to extract just the role.
    
    Usage:
        @router.get('/my-info')
        async def get_info(role: str = Depends(get_user_role)):
            return {"your_role": role}
    """
    return current_user.get("role", Roles.USER)


def check_resource_ownership(
    current_user: dict,
    resource_owner_id: str,
    allow_admin_override: bool = True
) -> bool:
    """
    Check if user owns a resource or is admin.
    
    Args:
        current_user: JWT payload
        resource_owner_id: User ID who owns the resource
        allow_admin_override: If True, admins can access any resource
        
    Returns:
        True if access allowed, False otherwise
    """
    user_id = current_user.get("user_id") or current_user.get("sub")
    user_role = current_user.get("role", Roles.USER)
    
    # Check ownership
    if str(user_id) == str(resource_owner_id):
        return True
    
    # Admin override
    if allow_admin_override and user_role.lower() == Roles.ADMIN:
        return True
    
    return False
