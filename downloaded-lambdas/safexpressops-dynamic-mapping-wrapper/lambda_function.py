import json
import boto3
import base64
import os
import re

lambda_client = boto3.client('lambda', region_name='ap-southeast-1')
dynamodb      = boto3.resource('dynamodb', region_name='ap-southeast-1')

DYNAMIC_MAPPING_LAMBDA = 'safexpressops-dynamic-mapping-agent'

CORS_HEADERS = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'POST,OPTIONS'
}


def lambda_handler(event, context):
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': '{}'}

    try:
        auth_header = (event.get('headers', {}).get('authorization') or
                       event.get('headers', {}).get('Authorization', ''))
        gmail = get_gmail_from_jwt(auth_header)
        credentials = get_google_tokens(gmail)

        content_type = (event.get('headers', {}).get('content-type') or
                        event.get('headers', {}).get('Content-Type', ''))
        raw_body = event.get('body', '')

        if event.get('isBase64Encoded'):
            raw_body = base64.b64decode(raw_body)
        elif isinstance(raw_body, str):
            try:
                raw_body = raw_body.encode('latin-1')
            except UnicodeEncodeError:
                return {
                    'statusCode': 502,
                    'headers': CORS_HEADERS,
                    'body': json.dumps({
                        'success': False,
                        'error': 'Binary upload corrupted by API Gateway. '
                                 'Add "multipart/form-data" to Binary Media Types in API Gateway settings and redeploy the API.'
                    })
                }

        parsed = parse_multipart(raw_body, content_type)
        tool = parsed.get('tool', 'run_dynamic_mapping')

        if tool == 'fetch_tabs':
            if 'target_sheet_url' not in parsed:
                return {
                    'statusCode': 400,
                    'headers': CORS_HEADERS,
                    'body': json.dumps({'success': False, 'error': 'target_sheet_url is required'})
                }
            payload = {
                'tool': 'fetch_tabs',
                'inputs': {
                    'target_sheet_url': parsed['target_sheet_url'],
                    'credentials': credentials
                }
            }
        else:
            if 'file_content' not in parsed:
                return {
                    'statusCode': 400,
                    'headers': CORS_HEADERS,
                    'body': json.dumps({'success': False, 'error': 'No file uploaded'})
                }
            if 'target_sheet_url' not in parsed:
                return {
                    'statusCode': 400,
                    'headers': CORS_HEADERS,
                    'body': json.dumps({'success': False, 'error': 'target_sheet_url is required'})
                }

            inputs = {
                'file_content':      parsed['file_content'],
                'file_type':         parsed.get('file_type', 'xlsx'),
                'sheet_name':        parsed.get('sheet_name') or parsed.get('source_sheet_name', 0),
                'target_sheet_url':  parsed['target_sheet_url'],
                'target_sheet_name': parsed.get('target_sheet_name', 'Sheet1'),
                'credentials':       credentials
            }

            if parsed.get('section_index') is not None:
                inputs['section_index'] = parsed['section_index']

            # Fields the frontend may send on EITHER preview or run:
            #   - target_tab_chosen: user's pick from the multi-tab anchor-overlap picker.
            #   - conflict_choices: user's per-identifier picks from the multi-sheet
            #     aggregate cross-sheet conflict resolution modal. JSON-encoded
            #     {anchor_value: sheet_name|"skip"} on the wire — pass through as-is
            #     and let the agent json.loads it (the agent already handles both
            #     the dict and the string form for backwards compatibility).
            #   - intra_section_choices: user's per-anchor row pick from the
            #     same-section duplicate conflict modal. JSON-encoded
            #     {anchor_value: "row_<N>"|"skip"} on the wire — same shape
            #     contract as conflict_choices so the agent treats them the
            #     same way (str-or-dict tolerant).
            for shared_key in (
                'target_tab_chosen',
                'conflict_choices',
                'intra_section_choices',
            ):
                val = parsed.get(shared_key)
                if val is None or val == '':
                    continue
                try:
                    inputs[shared_key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    inputs[shared_key] = val

            if tool == 'run_dynamic_mapping':
                # Run-only fields: previewCache envelope + per-row write filter.
                # write_only is the per-row checkbox state from the diff/append
                # tables; the agent enforces it for row-keyed strategies (incl.
                # multi_sheet_aggregate) and ignores it for matrix layouts.
                for key in ('write_strategy', 'anchor_column', 'source_anchor',
                            'column_mappings', 'formula_cols',
                            'header_row_count', 'composite_to_col_index',
                            'strategy_metadata',
                            'pivot_source_col', 'value_source_col',
                            'write_only'):
                    val = parsed.get(key)
                    if val:
                        try:
                            inputs[key] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            inputs[key] = val

            payload = {'tool': tool, 'inputs': inputs}

        print(f"📞 Invoking dynamic-mapping-agent, tool={tool}")
        response = lambda_client.invoke(
            FunctionName=DYNAMIC_MAPPING_LAMBDA,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        result = json.loads(response['Payload'].read().decode('utf-8'))

        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': json.dumps(result)}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'success': False, 'error': str(e)})
        }


def parse_multipart(body, content_type):
    """Parse multipart/form-data without the deprecated cgi module."""
    if isinstance(body, str):
        body = body.encode('utf-8')

    m = re.search(rb'boundary=([^\s;]+)', content_type.encode('utf-8') if isinstance(content_type, str) else content_type)
    if not m:
        raise ValueError('No boundary found in Content-Type')

    boundary = m.group(1)
    # Handle quoted boundaries
    if boundary.startswith(b'"') and boundary.endswith(b'"'):
        boundary = boundary[1:-1]

    delimiter = b'--' + boundary
    parts = body.split(delimiter)
    # First part is empty (before first boundary), last part is "--\r\n" (closing)
    parts = parts[1:-1]

    result = {}
    for part in parts:
        # Strip leading \r\n
        if part.startswith(b'\r\n'):
            part = part[2:]

        # Split headers from body at the first double CRLF
        sep = part.find(b'\r\n\r\n')
        if sep == -1:
            continue

        header_block = part[:sep].decode('utf-8', errors='replace')
        part_body = part[sep + 4:]

        # Strip trailing \r\n left by the boundary split
        if part_body.endswith(b'\r\n'):
            part_body = part_body[:-2]

        # Extract name and filename from Content-Disposition
        name_match = re.search(r'name="([^"]+)"', header_block)
        filename_match = re.search(r'filename="([^"]*)"', header_block)

        if not name_match:
            continue

        field_name = name_match.group(1)

        if filename_match and filename_match.group(1):
            filename = filename_match.group(1)
            result['file_content'] = base64.b64encode(part_body).decode('utf-8')
            result['file_type'] = 'xlsx' if filename.lower().endswith('.xlsx') else 'csv'
            print(f"   Parsed file: {filename} ({len(part_body)} bytes)")
        else:
            result[field_name] = part_body.decode('utf-8', errors='replace').strip()

    return result


def get_gmail_from_jwt(auth_header):
    token = auth_header.replace('Bearer ', '')
    parts = token.split('.')
    if len(parts) < 2:
        raise Exception('Invalid JWT')
    padding = 4 - len(parts[1]) % 4
    payload_bytes = base64.urlsafe_b64decode(parts[1] + '=' * padding)
    payload = json.loads(payload_bytes)
    gmail = payload.get('gmail') or payload.get('email') or payload.get('sub')
    if not gmail:
        raise Exception('No gmail found in JWT')
    return gmail


def get_google_tokens(gmail):
    table = dynamodb.Table('SocialTokens')
    response = table.get_item(Key={
        'gmail': gmail,
        'provider': 'google'  # ← sort key required
    })
    item = response.get('Item')
    if not item:
        raise Exception(f'No tokens found for {gmail}')

    secrets_client = boto3.client('secretsmanager', region_name='ap-southeast-1')
    secret_name = os.environ.get('GOOGLE_OAUTH_SECRET', 'prod/app/google-oauth')
    secret_response = secrets_client.get_secret_value(SecretId=secret_name)
    secret_data = json.loads(secret_response['SecretString'])

    return {
        'access_token':  item.get('access_token', ''),
        'refresh_token': item.get('refresh_token', ''),
        'client_id':     secret_data.get('GOOGLE_CLIENT_ID', ''),
        'client_secret': secret_data.get('GOOGLE_CLIENT_SECRET', '')
    }