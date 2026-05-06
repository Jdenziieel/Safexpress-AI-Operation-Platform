"""
WebSocket Default Handler
Handles unrecognized WebSocket actions/routes.
Also handles:
  - 'ping' heartbeat
  - 'register' — client requests its connection_id (workaround for the
    well-known API Gateway race where post_to_connection from inside
    $connect fails with GoneException because the connection isn't yet
    fully registered. Sending from $default works because by then the
    handshake is complete.)
"""
import json
import os
import boto3
from datetime import datetime

# Initialize API Gateway Management API client
def get_apigw_client(event):
    """Create API Gateway Management API client for sending messages"""
    domain = event['requestContext']['domainName']
    stage = event['requestContext']['stage']
    endpoint = f"https://{domain}/{stage}"
    return boto3.client('apigatewaymanagementapi', endpoint_url=endpoint)


def lambda_handler(event, context):
    """
    Handle WebSocket $default route

    Recognized actions:
      - ping       → returns pong (heartbeat)
      - register   → returns connection_established with the connection_id
                     so the frontend can include it in subsequent HTTP calls
                     (e.g. /api/pdf/parse-pdf needs the WS connection_id to
                     push progress updates back).
      - anything else → informational error response.
    """
    try:
        connection_id = event['requestContext']['connectionId']

        # Parse the message body
        body = {}
        if event.get('body'):
            try:
                body = json.loads(event['body'])
            except json.JSONDecodeError:
                body = {'raw': event['body']}

        action = body.get('action', 'unknown')

        apigw = get_apigw_client(event)

        # ── Handle heartbeat / keepalive pings ────────────────────────────
        if action == 'ping':
            pong_message = {
                'type': 'pong',
                'message': 'keepalive acknowledged'
            }
            try:
                apigw.post_to_connection(
                    ConnectionId=connection_id,
                    Data=json.dumps(pong_message).encode('utf-8')
                )
            except apigw.exceptions.GoneException:
                print(f"Connection {connection_id} is gone (stale)")
            except Exception as e:
                print(f"Error sending pong to {connection_id}: {str(e)}")

            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'pong'})
            }

        # ── Handle client connection_id registration ───────────────────────
        # Why this exists: ws_connect tries to push connection_established
        # during $connect, but API Gateway's $connect handler races with
        # the WebSocket handshake — post_to_connection often returns
        # GoneException because the connection isn't fully ready yet. By
        # the time $default fires, the connection is guaranteed live.
        if action == 'register':
            authorizer_ctx = event.get('requestContext', {}).get('authorizer', {})
            user_id = authorizer_ctx.get('user_id', 'anonymous')

            register_message = {
                'type': 'connection_established',
                'connection_id': connection_id,
                'user_id': user_id,
                'message': 'Connection registered',
                'registered_at': datetime.utcnow().isoformat() + 'Z',
            }
            try:
                apigw.post_to_connection(
                    ConnectionId=connection_id,
                    Data=json.dumps(register_message).encode('utf-8')
                )
                print(f"Registered connection {connection_id} for user {user_id}")
            except apigw.exceptions.GoneException:
                # Should be very rare — connection died between handshake
                # and the register call. Client will hit our auto-reconnect
                # loop and try again.
                print(f"Connection {connection_id} is gone before register response")
            except Exception as e:
                print(f"Error sending register response to {connection_id}: {str(e)}")

            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'registered', 'connection_id': connection_id})
            }

        # ── Unknown action — send error response ─────────────────────────
        # `sendAgentMessage` lives on the same WebSocket API but routes to
        # the AI Assistant supervisor (`supervisor-ws-chat` Lambda) — it
        # never reaches $default, but we list it here so a typo or stale
        # client gets a useful hint instead of a silent miss.
        error_message = {
            'type': 'error',
            'message': f"Unknown action: '{action}'",
            'valid_actions': ['sendMessage', 'sendAgentMessage', 'ping', 'register'],
            'received': body
        }

        try:
            apigw.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps(error_message).encode('utf-8')
            )
        except apigw.exceptions.GoneException:
            print(f"Connection {connection_id} is gone (stale)")
        except Exception as e:
            print(f"Error sending error msg to {connection_id}: {str(e)}")

        print(f"Unknown action received: {action} from {connection_id}")

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Unknown action'})
        }

    except Exception as e:
        print(f"Error in ws_default: {str(e)}")
        return {
            'statusCode': 200,
            'body': json.dumps({'error': str(e)})
        }
