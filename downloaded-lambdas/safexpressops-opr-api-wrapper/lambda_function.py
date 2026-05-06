import json
import boto3
import os

lambda_client = boto3.client('lambda', region_name='ap-southeast-1')
dynamodb = boto3.resource('dynamodb', region_name='ap-southeast-1')

OPR_LAMBDA_ARN = 'safexpressops-opr-agent'


def get_google_tokens(gmail):
    try:
        table = dynamodb.Table('SocialTokens')
        response = table.get_item(Key={'gmail': gmail, 'provider': 'google'})
        item = response.get('Item')
        if not item:
            raise Exception(f"No Google tokens found for {gmail}")

        secrets_client = boto3.client('secretsmanager', region_name='ap-southeast-1')
        secret_name = os.environ.get('GOOGLE_OAUTH_SECRET', 'prod/app/google-oauth')
        secret_response = secrets_client.get_secret_value(SecretId=secret_name)
        secret_data = json.loads(secret_response['SecretString'])

        return {
            'access_token': item.get('access_token', ''),
            'refresh_token': item.get('refresh_token', ''),
            'client_id': secret_data.get('GOOGLE_CLIENT_ID', ''),
            'client_secret': secret_data.get('GOOGLE_CLIENT_SECRET', ''),
        }
    except Exception as e:
        print(f"❌ Error fetching tokens: {str(e)}")
        raise


def get_gmail_from_jwt(auth_header):
    import base64
    try:
        token = auth_header.replace('Bearer ', '')
        payload_b64 = token.split('.')[1]
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.b64decode(payload_b64).decode('utf-8'))
        return payload.get('gmail')
    except Exception as e:
        print(f"❌ Error decoding JWT: {str(e)}")
        return None


def lambda_handler(event, context):
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token',
        'Access-Control-Allow-Methods': 'POST,OPTIONS',
    }

    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers, 'body': json.dumps({'message': 'OK'})}

    try:
        body = event.get('body', '{}')
        if isinstance(body, str):
            body = json.loads(body)

        if not body or not body.get('file_data'):
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'success': False, 'error': 'Missing file_data'})
            }

        # Extract gmail from JWT and fetch Google tokens
        auth_header = event.get('headers', {}).get('Authorization') or \
                      event.get('headers', {}).get('authorization', '')
        gmail = get_gmail_from_jwt(auth_header)

        if not gmail:
            return {
                'statusCode': 401,
                'headers': cors_headers,
                'body': json.dumps({'success': False, 'error': 'Could not extract gmail from token'})
            }

        print(f"📤 OPR request for: {gmail}, workflow: {body.get('workflow_type', 'process')}")

        google_credentials = get_google_tokens(gmail)

        # Inject credentials into body for OPR agent
        body['google_credentials'] = google_credentials

        response = lambda_client.invoke(
            FunctionName=OPR_LAMBDA_ARN,
            InvocationType='RequestResponse',
            Payload=json.dumps(body)
        )

        result = json.loads(response['Payload'].read().decode('utf-8'))

        # Handle nested body
        if 'body' in result:
            result_body = json.loads(result['body']) if isinstance(result['body'], str) else result['body']
            status_code = result.get('statusCode', 200)
        else:
            result_body = result
            status_code = 200 if result.get('success', False) else 500

        return {
            'statusCode': status_code,
            'headers': cors_headers,
            'body': json.dumps(result_body)
        }

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'success': False, 'error': str(e)})
        }