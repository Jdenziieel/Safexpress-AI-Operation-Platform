"""
WebSocket Disconnect Handler
Handles WebSocket disconnections and cleanup
"""
import json
import os
import boto3

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
connections_table = dynamodb.Table(os.environ.get('CONNECTIONS_TABLE', 'KB_WebSocketConnections'))


def lambda_handler(event, context):
    """
    Handle WebSocket $disconnect route
    
    Removes the connection from DynamoDB when client disconnects.
    """
    try:
        connection_id = event['requestContext']['connectionId']
        
        # Delete connection from DynamoDB
        connections_table.delete_item(
            Key={'connection_id': connection_id}
        )
        
        print(f"WebSocket disconnected: {connection_id}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Disconnected'})
        }
        
    except Exception as e:
        print(f"Error in ws_disconnect: {str(e)}")
        return {
            'statusCode': 200,
            'body': json.dumps({'error': str(e)})
        }
