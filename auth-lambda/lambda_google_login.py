"""
Lambda Function: auth-google-login
Handles Google OAuth authentication with DynamoDB
Migrated from: authserver/api/views.py -> google_auth_dynamodb()

DynamoDB Tables:
- Users: Primary key = gmail
- SocialTokens: Primary key = gmail, Sort key = provider
"""

import json
import boto3
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import hashlib
import hmac
import base64
import uuid
import os

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager')

# Table references
users_table = dynamodb.Table(os.environ.get('USERS_TABLE', 'Users'))
tokens_table = dynamodb.Table(os.environ.get('SOCIAL_TOKENS_TABLE', 'SocialTokens'))

# Cache for secrets (Lambda container reuse)
_secrets_cache = {}


def get_secret(secret_name):
    """Get secret from Secrets Manager with caching"""
    if secret_name in _secrets_cache:
        return _secrets_cache[secret_name]
    
    response = secrets_client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response['SecretString'])
    _secrets_cache[secret_name] = secret
    return secret


def exchange_code_for_tokens(auth_code, client_id, client_secret):
    """Exchange authorization code for Google tokens"""
    token_url = "https://oauth2.googleapis.com/token"
    
    data = urllib.parse.urlencode({
        'code': auth_code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': 'postmessage',
        'grant_type': 'authorization_code'
    }).encode('utf-8')
    
    req = urllib.request.Request(token_url, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))


def get_google_user_info(access_token):
    """Get user info from Google"""
    userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
    
    req = urllib.request.Request(userinfo_url)
    req.add_header('Authorization', f'Bearer {access_token}')
    
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))


def generate_jwt(payload, secret):
    """Generate a JWT token"""
    header = {"alg": "HS256", "typ": "JWT"}
    
    header_b64 = base64.urlsafe_b64encode(
        json.dumps(header, separators=(',', ':')).encode()
    ).rstrip(b'=').decode()
    
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode()
    ).rstrip(b'=').decode()
    
    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()
    
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def lambda_handler(event, context):
    """Main Lambda handler for Google OAuth login"""
    
    # CORS headers
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'POST,OPTIONS'
    }
    
    # Handle preflight OPTIONS request
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        auth_code = body.get('code')
        
        if not auth_code:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Authorization code is missing.'})
            }
        
        print(f"Received auth code: {auth_code[:20]}...")
        
        # Get secrets
        google_creds = get_secret(os.environ.get('GOOGLE_OAUTH_SECRET', 'prod/app/google-oauth'))
        jwt_secret = get_secret(os.environ.get('JWT_SECRET', 'prod/app/jwt'))['JWT_SECRET_KEY']
        
        # Step 1: Exchange code for Google tokens
        print("Exchanging auth code for tokens...")
        token_response = exchange_code_for_tokens(
            auth_code,
            google_creds['GOOGLE_CLIENT_ID'],
            google_creds['GOOGLE_CLIENT_SECRET']
        )
        
        if 'error' in token_response:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({
                    'error': token_response.get('error_description', token_response['error'])
                })
            }
        
        google_access_token = token_response.get('access_token')
        google_refresh_token = token_response.get('refresh_token', '')
        expires_in = token_response.get('expires_in', 3600)
        
        # Step 2: Get user info from Google
        print("Getting user info from Google...")
        userinfo = get_google_user_info(google_access_token)
        
        email = userinfo.get('email')
        name = userinfo.get('name', '')
        google_id = userinfo.get('id')
        picture = userinfo.get('picture', '')
        
        if not email:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Email not provided by Google'})
            }
        
        print(f"User email: {email}")
        
        # Step 3: Check if user is onboarded (DynamoDB lookup)
        print("Checking onboarding status...")
        user_response = users_table.get_item(Key={'gmail': email})
        user = user_response.get('Item')
        
        if not user:
            print(f"User {email} not found - not onboarded")
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({
                    'error': 'Account not found',
                    'message': 'Your account has not been onboarded yet. Please contact an administrator to create your account.',
                    'email': email
                })
            }
        
        if not user.get('is_active', False):
            print(f"User {email} exists but is not active")
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({
                    'error': 'Account not activated',
                    'message': 'Your account has not been onboarded yet. Please contact an administrator to activate your account.',
                    'email': email
                })
            }
        
        print(f"User {email} is onboarded and active")
        
        # Step 4: Update user's picture if changed
        if picture and user.get('google_picture') != picture:
            now = datetime.utcnow().isoformat() + 'Z'
            users_table.update_item(
                Key={'gmail': email},
                UpdateExpression='SET google_picture = :pic, updated_at = :now',
                ExpressionAttributeValues={':pic': picture, ':now': now}
            )
        
        # Step 5: Store/Update Google tokens in SocialTokens table
        expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat() + 'Z'
        
        tokens_table.put_item(Item={
            'gmail': email,
            'provider': 'google',
            'access_token': google_access_token,
            'refresh_token': google_refresh_token,
            'expires_at': expires_at,
            'uid': google_id,
            'extra_data': userinfo
        })
        
        print(f"Stored Google tokens for {email}")
        
        # Step 6: Generate JWT tokens
        now = datetime.utcnow()
        access_exp = now + timedelta(minutes=60)
        refresh_exp = now + timedelta(days=7)
        
        # Access token payload (matches Django CustomTokenObtainPairSerializer)
        access_payload = {
            'token_type': 'access',
            'exp': int(access_exp.timestamp()),
            'iat': int(now.timestamp()),
            'jti': str(uuid.uuid4()),
            'user_id': user['user_id'],
            'role': user.get('role', 'user'),
            'fullname': user.get('fullname', ''),
            'gmail': email,
            'picture': user.get('google_picture', picture)
        }
        
        # Refresh token payload
        refresh_payload = {
            'token_type': 'refresh',
            'exp': int(refresh_exp.timestamp()),
            'iat': int(now.timestamp()),
            'jti': str(uuid.uuid4()),
            'user_id': user['user_id']
        }
        
        access_token = generate_jwt(access_payload, jwt_secret)
        refresh_token = generate_jwt(refresh_payload, jwt_secret)
        
        print(f"Generated JWT for {email}")
        
        # Step 7: Return response 
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'access': access_token,
                'refresh': refresh_token,
                'user': {
                    'user_id': user['user_id'],
                    'fullname': user.get('fullname', ''),
                    'gmail': email,
                    'role': user.get('role', 'user'),
                    'is_active': user.get('is_active', False),
                    'picture': picture,
                    'created_at': user.get('created_at', ''),
                    'terms_accepted': bool(user.get('terms_accepted', False)),
                    'terms_version_accepted': user.get('terms_version_accepted'),
                    'terms_accepted_at': user.get('terms_accepted_at'),
                }
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Authentication failed: {str(e)}'})
        }
