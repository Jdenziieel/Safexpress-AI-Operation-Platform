"""
Lambda response utilities for Knowledge Base functions.
Provides consistent response formatting with CORS headers.
"""
import json
from typing import Any, Dict
from decimal import Decimal


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder for Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def cors_headers() -> Dict[str, str]:
    """Return CORS headers for all responses."""
    return {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS'
    }


def success_response(data: Any, status_code: int = 200) -> Dict:
    """
    Create a successful Lambda response.
    
    Args:
        data: Response data (will be JSON serialized)
        status_code: HTTP status code (default 200)
        
    Returns:
        dict: Lambda response with CORS headers
    """
    return {
        'statusCode': status_code,
        'headers': cors_headers(),
        'body': json.dumps(data, cls=DecimalEncoder)
    }


def error_response(message: str, status_code: int = 400, error_code: str = None) -> Dict:
    """
    Create an error Lambda response.
    
    Args:
        message: Error message
        status_code: HTTP status code (default 400)
        error_code: Optional error code for client handling
        
    Returns:
        dict: Lambda error response with CORS headers
    """
    body = {'error': message}
    if error_code:
        body['error_code'] = error_code
    
    return {
        'statusCode': status_code,
        'headers': cors_headers(),
        'body': json.dumps(body)
    }


def not_found_response(message: str = "Resource not found") -> Dict:
    """Create a 404 response."""
    return error_response(message, 404, 'NOT_FOUND')


def unauthorized_response(message: str = "Authentication required") -> Dict:
    """Create a 401 response."""
    return error_response(message, 401, 'UNAUTHORIZED')


def forbidden_response(message: str = "Access denied") -> Dict:
    """Create a 403 response."""
    return error_response(message, 403, 'FORBIDDEN')


def validation_error_response(message: str) -> Dict:
    """Create a 422 validation error response."""
    return error_response(message, 422, 'VALIDATION_ERROR')


def server_error_response(message: str = "Internal server error") -> Dict:
    """Create a 500 response."""
    return error_response(message, 500, 'SERVER_ERROR')


def options_response() -> Dict:
    """Create an OPTIONS response for CORS preflight."""
    return {
        'statusCode': 200,
        'headers': cors_headers(),
        'body': ''
    }


def parse_body(event: Dict) -> Dict:
    """
    Parse JSON body from Lambda event.
    
    Args:
        event: Lambda event
        
    Returns:
        dict: Parsed body or empty dict
    """
    body = event.get('body', '')
    if not body:
        return {}
    
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    
    return body if isinstance(body, dict) else {}


def get_path_parameter(event: Dict, param_name: str) -> str:
    """
    Get path parameter from Lambda event.
    
    Args:
        event: Lambda event
        param_name: Parameter name
        
    Returns:
        str: Parameter value or None
    """
    path_params = event.get('pathParameters', {}) or {}
    return path_params.get(param_name)


def get_query_parameter(event: Dict, param_name: str, default: str = None) -> str:
    """
    Get query string parameter from Lambda event.
    
    Args:
        event: Lambda event
        param_name: Parameter name
        default: Default value if not found
        
    Returns:
        str: Parameter value or default
    """
    query_params = event.get('queryStringParameters', {}) or {}
    return query_params.get(param_name, default)


def get_http_method(event: Dict) -> str:
    """
    Get HTTP method from Lambda event.
    
    Args:
        event: Lambda event
        
    Returns:
        str: HTTP method (GET, POST, etc.)
    """
    # API Gateway v2 format
    request_context = event.get('requestContext', {})
    if 'http' in request_context:
        return request_context['http'].get('method', 'GET')
    
    # API Gateway v1 format
    return event.get('httpMethod', 'GET')


def get_route_path(event: Dict) -> str:
    """
    Get route path from Lambda event.
    
    Args:
        event: Lambda event
        
    Returns:
        str: Route path
    """
    # API Gateway v2 format
    request_context = event.get('requestContext', {})
    if 'http' in request_context:
        return request_context['http'].get('path', '/')
    
    # API Gateway v1 format
    return event.get('path', '/')


def get_user_from_authorizer(event: Dict) -> Dict:
    """
    Extract user information from API Gateway authorizer context.
    The Lambda authorizer passes user info in requestContext.authorizer.
    
    Args:
        event: Lambda event
        
    Returns:
        dict: User information with keys:
            - user_id: User ID
            - email: User email
            - role: User role (admin, manager, user)
            - fullname: User's full name
            - is_active: Whether user is active
            
    Raises:
        Exception: If user info not found in authorizer context
    """
    request_context = event.get('requestContext', {})
    
    # API Gateway REST API with Lambda Authorizer
    authorizer = request_context.get('authorizer', {})
    
    # Extract user info from authorizer context
    user_id = authorizer.get('user_id')
    
    if not user_id:
        # Try to get from principalId (set by authorizer)
        user_id = authorizer.get('principalId')
    
    if not user_id:
        raise Exception("User not authenticated - no authorizer context")
    
    return {
        'user_id': str(user_id),
        'email': authorizer.get('email', ''),
        'role': authorizer.get('role', 'user'),
        'fullname': authorizer.get('fullname', ''),
        'is_active': authorizer.get('is_active', 'true').lower() == 'true'
    }


def get_user_id(event: Dict) -> str:
    """
    Get user ID from authorizer context.
    
    Args:
        event: Lambda event
        
    Returns:
        str: User ID
        
    Raises:
        Exception: If user ID not found
    """
    user = get_user_from_authorizer(event)
    return user['user_id']


def get_user_role(event: Dict) -> str:
    """
    Get user role from authorizer context.
    
    Args:
        event: Lambda event
        
    Returns:
        str: User role (admin, manager, user)
    """
    user = get_user_from_authorizer(event)
    return user['role'].lower()


def is_admin(event: Dict) -> bool:
    """Check if user is admin."""
    return get_user_role(event) == 'admin'


def is_manager_or_above(event: Dict) -> bool:
    """Check if user is manager or admin."""
    role = get_user_role(event)
    return role in ['admin', 'manager']

