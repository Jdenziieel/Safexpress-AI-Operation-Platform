from rest_framework.permissions import BasePermission
from rest_framework_simplejwt.tokens import AccessToken


class IsAdminUser(BasePermission):
    """
    Permission class to check if user has Admin role in JWT token
    """

    def has_permission(self, request, view):
        # Get JWT token from Authorization header
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")

        if not auth_header.startswith("Bearer "):
            return False

        token = auth_header.split(" ")[1]

        try:
            # Decode JWT token
            access_token = AccessToken(token)

            # Check role in token payload
            role = access_token.get("role", "User")

            return role == "Admin"
        except Exception as e:
            print(f"Error checking admin permission: {str(e)}")
            return False
