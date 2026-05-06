"""
WebSocket Connect Handler
Handles new WebSocket connections from clients

Notes for the AI Assistant migration (see websocket.md §2):
  * The authorizer Allows the connect AFTER verifying the JWT, but the JWT
    itself is gone by the time downstream lambdas (`$default`, `sendMessage`,
    `sendAgentMessage`) run — subsequent frames don't carry it.
  * `supervisor-ws-chat` (the AI Assistant route) needs the raw JWT to call
    the quota service on the user's behalf, and benefits from a `gmail`
    alias for Google credential lookup.
  * We stash both onto the connection row here so downstream lambdas can
    read them back from `KB_WebSocketConnections`.
"""
import json
import os
import boto3
from datetime import datetime
from decimal import Decimal

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
connections_table = dynamodb.Table(os.environ.get('CONNECTIONS_TABLE', 'KB_WebSocketConnections'))


def lambda_handler(event, context):
    """
    Handle WebSocket $connect route
    
    The authorizer has already validated the JWT token and provided user context.
    We store the connection ID with user info for sending messages back.

    Additionally (per websocket.md §2.2) we stash:
      - jwt: the raw access token from the connect query string, so the
             AI Assistant supervisor can hit the quota service with
             `Authorization: Bearer <jwt>` on the user's behalf.
      - gmail: alias of user_email so the supervisor's per-user Google
               credential lookup is zero-cost (it reads gmail → email →
               user_email → JWT claims, in that order).
    """
    try:
        connection_id = event['requestContext']['connectionId']
        
        # Get user info from authorizer context (passed from Lambda authorizer)
        authorizer_context = event.get('requestContext', {}).get('authorizer', {})
        user_id = authorizer_context.get('user_id', 'anonymous')
        user_role = authorizer_context.get('role', 'user')
        user_email = authorizer_context.get('email', '')
        fullname = authorizer_context.get('fullname', '')

        # Pull the raw JWT off the connect query string. The authorizer
        # already verified it; we just persist the bytes for downstream
        # lambdas (supervisor-ws-chat, supervisor-action-approve) so they
        # can call the quota service with `Authorization: Bearer <jwt>`
        # on the user's behalf.
        qs = event.get('queryStringParameters') or {}
        raw_jwt = qs.get('token', '') or ''
        
        # Get connection timestamp
        connected_at = event['requestContext'].get('connectedAt', 
            int(datetime.utcnow().timestamp() * 1000))
        
        # Store connection in DynamoDB
        item = {
            'connection_id': connection_id,
            'user_id': user_id,
            'user_role': user_role,
            'user_email': user_email,
            'fullname': fullname,
            'connected_at': Decimal(str(connected_at)),
            'status': 'connected',
            'last_activity': datetime.utcnow().isoformat(),
            # AI Assistant migration — see module docstring and websocket.md §2.
            # `jwt` is ~1.5–2 KB per row; if KB_WebSocketConnections has a TTL,
            # the token auto-expires with the row.
            'jwt': raw_jwt,
            # `gmail` mirrors user_email so the supervisor's gmail-keyed
            # SocialTokens lookup is a single DynamoDB read with no fallback.
            'gmail': user_email,
        }
        
        connections_table.put_item(Item=item)
        
        print(f"WebSocket connected: {connection_id} for user: {user_id}")
        
        # Send connection_id to the client
        try:
            domain = event['requestContext']['domainName']
            stage = event['requestContext']['stage']
            endpoint = f"https://{domain}/{stage}"
            apigw = boto3.client('apigatewaymanagementapi', endpoint_url=endpoint)
            
            apigw.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps({
                    'type': 'connection_established',
                    'connection_id': connection_id,
                    'user_id': user_id,
                    'message': 'Connected successfully'
                }).encode('utf-8')
            )
            print(f"Sent connection_id to client: {connection_id}")
        except Exception as send_err:
            print(f"Warning: Could not send connection_id to client: {send_err}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Connected successfully', 'connection_id': connection_id})
        }
        
    except Exception as e:
        print(f"Error in ws_connect: {str(e)}")
        # Even on error, return 200 to allow connection
        # The client will handle errors via messages
        return {
            'statusCode': 200,
            'body': json.dumps({'error': str(e)})
        }
