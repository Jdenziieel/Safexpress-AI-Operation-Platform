"""
Lambda Function: auth-onboard-user
Onboard new users (Admin only)
Migrated from: authserver/api/views.py -> onboard_user()

DynamoDB Tables:
- Users: Primary key = gmail
- AdminActivityLogs: Primary key = log_id
"""

import json
import boto3
from datetime import datetime
import uuid
import urllib.request
import urllib.error
import os

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
users_table = dynamodb.Table(os.environ.get('USERS_TABLE', 'Users'))
logs_table = dynamodb.Table(os.environ.get('LOGS_TABLE', 'AdminActivityLogs'))
ses_client = boto3.client('ses', region_name=os.environ.get('SES_REGION', 'us-east-1'))

# Quota service URL (can be configured via environment variable)
QUOTA_SERVICE_URL = os.environ.get('QUOTA_SERVICE_URL', 'http://localhost:8011')

# SES / welcome email config
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'https://your-deployed-site.com').rstrip('/')
SES_FROM_EMAIL = os.environ.get('SES_FROM_EMAIL', '')
APP_NAME = os.environ.get('APP_NAME', 'Safexpress Portal')
TERMS_VERSION = os.environ.get('TERMS_VERSION', '1.0')


def send_welcome_email(to_email, fullname, role):
    """Send a welcome/onboarding email via Amazon SES.

    Returns True on success, False otherwise. Failures never block onboarding.
    """
    if not SES_FROM_EMAIL:
        print("SES_FROM_EMAIL is not configured; skipping welcome email")
        return False

    subject = f"Welcome to {APP_NAME} - your account is ready"

    html_body = f"""
    <html>
      <body style="margin:0; font-family: Arial, sans-serif; background:#f8fafc; padding:24px; color:#1e293b;">
        <div style="max-width:600px; margin:0 auto; background:#ffffff; border-radius:8px; padding:32px; box-shadow:0 2px 6px rgba(0,0,0,0.05);">
          <h2 style="color:#26326e; margin-top:0;">Hi {fullname},</h2>
          <p>An administrator has onboarded your account on the <strong>{APP_NAME}</strong>.
          You can now sign in using your Google work account.</p>
          <div style="background:#f1f5f9; border-radius:6px; padding:16px; margin:20px 0;">
            <p style="margin:4px 0;"><strong>Email:</strong> {to_email}</p>
            <p style="margin:4px 0;"><strong>Role:</strong> {role.capitalize()}</p>
          </div>
          <p style="text-align:center; margin:32px 0;">
            <a href="{FRONTEND_URL}/login"
               style="background:#26326e; color:#ffffff; text-decoration:none;
                      padding:12px 28px; border-radius:6px; font-weight:600;
                      display:inline-block;">
              Sign in to the Portal
            </a>
          </p>
          <p>On your first login you will be asked to review and accept our
          Terms &amp; Conditions (v{TERMS_VERSION}) before you can use the system.</p>
          <hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">
          <p style="color:#64748b; font-size:0.85rem;">If you weren't expecting this email,
          please ignore it or contact your administrator.</p>
        </div>
      </body>
    </html>
    """

    text_body = (
        f"Hi {fullname},\n\n"
        f"An administrator has onboarded your account on the {APP_NAME}.\n"
        f"You can now sign in at {FRONTEND_URL}/login using your Google work account ({to_email}).\n"
        f"Role: {role.capitalize()}\n\n"
        f"On your first login you will be asked to review and accept our Terms & Conditions "
        f"(v{TERMS_VERSION}) before you can use the system.\n\n"
        f"If you weren't expecting this email, please ignore it or contact your administrator.\n"
    )

    try:
        ses_client.send_email(
            Source=SES_FROM_EMAIL,
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html_body, 'Charset': 'UTF-8'},
                    'Text': {'Data': text_body, 'Charset': 'UTF-8'},
                },
            },
        )
        print(f"Welcome email sent to {to_email}")
        return True
    except Exception as e:
        print(f"Failed to send welcome email to {to_email}: {e}")
        return False


def call_quota_service(endpoint, method='POST', data=None, headers=None):
    """Call the quota service API"""
    try:
        url = f"{QUOTA_SERVICE_URL}{endpoint}"
        
        if data:
            data = json.dumps(data).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header('Content-Type', 'application/json')
        
        if headers:
            for key, value in headers.items():
                req.add_header(key, value)
        
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'error': str(e)}
    except Exception as e:
        print(f"Quota service error: {str(e)}")
        return None, {'error': str(e)}


def log_activity(admin_email, admin_name, action, target_email, target_name, details, ip_address=''):
    """Log admin activity to DynamoDB"""
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        logs_table.put_item(Item={
            'log_id': str(uuid.uuid4()),
            'admin_email': admin_email,
            'admin_name': admin_name,
            'action': action,
            'target_user_email': target_email,
            'target_user_name': target_name,
            'details': json.dumps(details) if details else None,
            'created_at': now,
            'ip_address': ip_address
        })
        print(f"Activity logged: {admin_email} - {action} - {target_email}")
    except Exception as e:
        print(f"Failed to log activity: {str(e)}")


def lambda_handler(event, context):
    """Main handler for user onboarding"""
    
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'POST,OPTIONS'
    }
    
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': ''}
    
    try:
        # Get admin info from authorizer context
        request_context = event.get('requestContext', {})
        authorizer = request_context.get('authorizer', {})
        
        admin_role = authorizer.get('role', '')
        admin_email = authorizer.get('gmail') or authorizer.get('email', '')
        admin_name = authorizer.get('fullname', '')
        
        # Get client IP
        ip_address = request_context.get('identity', {}).get('sourceIp', '')
        
        # Check admin role
        if admin_role != 'admin':
            return {
                'statusCode': 403,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Permission denied. Only admins can onboard users.'})
            }
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        
        fullname = body.get('fullname', '').strip()
        gmail = body.get('gmail', '').strip().lower()
        role = body.get('role', 'user').lower()
        
        # Validate input
        if not fullname or not gmail:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'fullname and gmail are required'})
            }
        
        if role not in ['admin', 'manager', 'user']:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Invalid role. Must be admin, manager, or user'})
            }
        
        # Check if user already exists
        existing = users_table.get_item(Key={'gmail': gmail})
        
        if 'Item' in existing:
            user = existing['Item']
            if user.get('is_active', False):
                return {
                    'statusCode': 400,
                    'headers': cors_headers,
                    'body': json.dumps({'error': f'User with email {gmail} is already onboarded.'})
                }
            else:
                # Reactivate existing inactive user (reset T&C so they must accept again)
                now = datetime.utcnow().isoformat() + 'Z'
                users_table.update_item(
                    Key={'gmail': gmail},
                    UpdateExpression=(
                        'SET is_active = :active, fullname = :name, #r = :role, '
                        'updated_at = :now, created_by = :admin, '
                        'terms_accepted = :terms_false'
                    ),
                    ExpressionAttributeNames={'#r': 'role'},
                    ExpressionAttributeValues={
                        ':active': True,
                        ':name': fullname,
                        ':role': role,
                        ':now': now,
                        ':admin': admin_email,
                        ':terms_false': False,
                    }
                )
                
                # Try to restore quota
                quota_restored = False
                auth_header = event.get('headers', {}).get('Authorization', '') or event.get('headers', {}).get('authorization', '')
                status, _ = call_quota_service(
                    f"/quota/admin/user/{user['user_id']}/restore",
                    method='POST',
                    headers={'Authorization': auth_header} if auth_header else None
                )
                if status == 200:
                    quota_restored = True
                elif status == 404:
                    # Create new quota
                    status, _ = call_quota_service(
                        "/quota/admin/user/create",
                        method='POST',
                        data={'user_id': user['user_id'], 'fullname': fullname, 'tier': 'free'},
                        headers={'Authorization': auth_header} if auth_header else None
                    )
                    if status in [200, 201]:
                        quota_restored = True
                
                # Send welcome/reactivation email (best-effort, never blocks)
                email_sent = send_welcome_email(gmail, fullname, role)

                # Log activity
                log_activity(admin_email, admin_name, 'activate', gmail, fullname,
                           {'previous_status': 'inactive', 'new_status': 'active',
                            'role': role, 'quota_restored': quota_restored,
                            'welcome_email_sent': email_sent},
                           ip_address)

                return {
                    'statusCode': 200,
                    'headers': cors_headers,
                    'body': json.dumps({
                        'message': f'User {gmail} has been activated.',
                        'user': {
                            'user_id': user['user_id'],
                            'fullname': fullname,
                            'gmail': gmail,
                            'role': role,
                            'is_active': True,
                            'terms_accepted': False
                        },
                        'quota_restored': quota_restored,
                        'welcome_email_sent': email_sent
                    })
                }
        
        # Create new user (must accept T&C on first login)
        now = datetime.utcnow().isoformat() + 'Z'
        new_user_id = str(uuid.uuid4())
        new_user = {
            'gmail': gmail,
            'user_id': new_user_id,
            'fullname': fullname,
            'role': role,
            'is_active': True,
            'created_at': now,
            'updated_at': now,
            'created_by': admin_email,
            'google_picture': '',
            'terms_accepted': False,
            'terms_version_accepted': None,
            'terms_accepted_at': None,
        }

        users_table.put_item(Item=new_user)
        
        # Create quota in token-quota-service
        quota_created = False
        auth_header = event.get('headers', {}).get('Authorization', '') or event.get('headers', {}).get('authorization', '')
        status, _ = call_quota_service(
            "/quota/admin/user/create",
            method='POST',
            data={'user_id': new_user_id, 'fullname': fullname, 'tier': 'free'},
            headers={'Authorization': auth_header} if auth_header else None
        )
        if status in [200, 201]:
            quota_created = True
        
        # Send welcome email via SES (best-effort, never blocks onboarding)
        email_sent = send_welcome_email(gmail, fullname, role)

        # Log activity
        log_activity(admin_email, admin_name, 'onboard', gmail, fullname,
                   {'role': role, 'quota_created': quota_created,
                    'welcome_email_sent': email_sent},
                   ip_address)

        print(f"Admin {admin_email} onboarded new user: {gmail}")

        return {
            'statusCode': 201,
            'headers': cors_headers,
            'body': json.dumps({
                'message': f'User {gmail} has been successfully onboarded.',
                'user': {
                    'user_id': new_user_id,
                    'fullname': fullname,
                    'gmail': gmail,
                    'role': role,
                    'is_active': True,
                    'created_at': now,
                    'terms_accepted': False
                },
                'quota_created': quota_created,
                'welcome_email_sent': email_sent
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'Failed to onboard user: {str(e)}'})
        }
