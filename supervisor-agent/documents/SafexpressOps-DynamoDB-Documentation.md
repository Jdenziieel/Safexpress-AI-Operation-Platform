# SafexpressOps DynamoDB Database Structure

## 📊 Database Overview

**Table Name:** `SafexpressOps-Production`

This is a single-table design using DynamoDB with composite keys (PK/SK) and Global Secondary Indexes (GSIs) for efficient querying.

---

## 🗂️ Entity Types & Schema

### 1. User Profile

Stores user information and Google OAuth tokens for API access.

```python
{
    'PK': 'USER#{user_id}',
    'SK': 'PROFILE',
    'EntityType': 'User',
    'user_id': 'user-456',
    'email': 'john@safexpress.com',
    'name': 'John Doe',
    'role': 'admin',
    'department': 'Operations',
    'google_access_token': 'ya29.xxx',  # Encrypted
    'google_refresh_token': '1//xxx',    # Encrypted
    'token_expiry': '2025-10-17T11:00:00Z',
    'created_at': '2025-01-15T08:00:00Z',
    'updated_at': '2025-10-17T10:00:00Z'
}
```

**Query Pattern:** Get user profile
```python
response = table.get_item(
    Key={
        'PK': f'USER#{user_id}',
        'SK': 'PROFILE'
    }
)
```

---

### 2. Activity Log

Tracks all user actions in the system for audit purposes.

```python
{
    'PK': 'USER#{user_id}',
    'SK': 'LOG#{timestamp}#{log_id}',
    'EntityType': 'ActivityLog',
    'log_id': 'log-123',
    'user_id': 'user-456',
    'user_email': 'john@safexpress.com',  # Denormalized
    'user_name': 'John Doe',              # Denormalized
    'user_role': 'admin',                 # Denormalized
    'action': 'create_document',
    'details': 'Created Q4 Report document',
    'resource_type': 'google_doc',
    'resource_id': '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms',
    'timestamp': '2025-10-17T10:30:00Z'
}
```

**Query Pattern:** Get user activity logs
```python
response = table.query(
    KeyConditionExpression=Key('PK').eq(f'USER#{user_id}') & 
                          Key('SK').begins_with('LOG#')
)
```

---

### 3. Conversation Thread

Represents a chat session between user and AI supervisor agent.

```python
{
    'PK': 'USER#{user_id}',
    'SK': 'THREAD#{thread_id}',
    'EntityType': 'Thread',
    'thread_id': 'uuid-123',
    'user_id': 'user-456',
    'title': 'Document creation assistance',
    'conversation_status': 'active',  # active, archived, paused
    'created_at': '2025-10-17T10:00:00Z',
    'updated_at': '2025-10-17T10:30:00Z',
    'message_count': 5,
    
    # For GSI4 queries (get thread by ID)
    'GSI4PK': 'THREAD#{thread_id}',
    'GSI4SK': '2025-10-17T10:30:00Z'
}
```

**Query Pattern:** Get all threads for a user
```python
response = table.query(
    KeyConditionExpression=Key('PK').eq(f'USER#{user_id}') & 
                          Key('SK').begins_with('THREAD#')
)
```

---

### 4. Chat Message

Individual messages in a conversation thread.

```python
{
    'PK': 'THREAD#{thread_id}',
    'SK': 'MSG#{timestamp}#{message_id}',
    'EntityType': 'Message',
    'message_id': 'msg-789',
    'thread_id': 'uuid-123',
    'user_id': 'user-456',
    'sender': 'user',  # 'user' or 'assistant'
    'content': 'Create a document called Q4 Report',
    'created_at': '2025-10-17T10:00:00Z',
    
    # For GSI5 queries (user message history)
    'GSI5PK': f'USER#{user_id}#MSG',
    'GSI5SK': '2025-10-17T10:00:00Z'
}
```

**Query Pattern:** Get all messages in a thread
```python
response = table.query(
    KeyConditionExpression=Key('PK').eq(f'THREAD#{thread_id}') & 
                          Key('SK').begins_with('MSG#'),
    ScanIndexForward=False,  # Newest first
    Limit=20
)
```

---

### 5. Tool Call Log

Tracks agent actions (Google API calls, document creation, etc.).

```python
{
    'PK': 'THREAD#{thread_id}',
    'SK': 'TOOL#{timestamp}#{tool_call_id}',
    'EntityType': 'ToolCall',
    'tool_call_id': 'tool-999',
    'message_id': 'msg-789',
    'thread_id': 'uuid-123',
    'user_id': 'user-456',
    'tool_name': 'create_google_doc',
    'input_params': {
        'title': 'Q4 Report',
        'content': 'Document content here...'
    },
    'output_result': {
        'doc_id': '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms',
        'doc_url': 'https://docs.google.com/document/d/...'
    },
    'status': 'success',  # success or error
    'created_at': '2025-10-17T10:00:05Z'
}
```

**Query Pattern:** Get all tool calls in a thread
```python
response = table.query(
    KeyConditionExpression=Key('PK').eq(f'THREAD#{thread_id}') & 
                          Key('SK').begins_with('TOOL#')
)
```

---

## 🔑 Global Secondary Indexes (GSIs)

### GSI4: Thread Messages Index ⭐ (MOST IMPORTANT)

```
Index Name: thread-messages-index
Partition Key: thread_id (String)
Sort Key: created_at (String)
Projection: All attributes
```

**Purpose:** Efficiently retrieve all messages in a conversation thread

**Use Case:** When supervisor agent needs to load conversation history

**Query Example:**
```python
# Get last 20 messages in a thread
response = table.query(
    IndexName='thread-messages-index',
    KeyConditionExpression=Key('thread_id').eq(thread_id),
    ScanIndexForward=False,  # Newest first
    Limit=20
)
```

---

### GSI5: User Message History Index (Optional)

```
Index Name: user-messages-index
Partition Key: user_id (String)
Sort Key: created_at (String)
Projection: All attributes
```

**Purpose:** Get all messages from a user across all threads

**Use Case:** Analytics, user behavior tracking

---

## 💻 Python Code Examples

### Database Helper Functions

```python
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime
import uuid

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb', region_name='ap-southeast-1')
table = dynamodb.Table('SafexpressOps-Production')

def create_user(user_id, email, name, role, department, oauth_tokens):
    """Create a new user profile"""
    timestamp = datetime.utcnow().isoformat()
    
    item = {
        'PK': f'USER#{user_id}',
        'SK': 'PROFILE',
        'EntityType': 'User',
        'user_id': user_id,
        'email': email,
        'name': name,
        'role': role,
        'department': department,
        'google_access_token': oauth_tokens['access_token'],
        'google_refresh_token': oauth_tokens['refresh_token'],
        'token_expiry': oauth_tokens['expires_at'],
        'created_at': timestamp,
        'updated_at': timestamp
    }
    
    table.put_item(Item=item)
    return item

def get_user(user_id):
    """Get user profile"""
    response = table.get_item(
        Key={
            'PK': f'USER#{user_id}',
            'SK': 'PROFILE'
        }
    )
    return response.get('Item')

def update_user_oauth_tokens(user_id, access_token, refresh_token, expires_at):
    """Update user's OAuth tokens"""
    table.update_item(
        Key={
            'PK': f'USER#{user_id}',
            'SK': 'PROFILE'
        },
        UpdateExpression='SET google_access_token = :at, google_refresh_token = :rt, token_expiry = :exp, updated_at = :ua',
        ExpressionAttributeValues={
            ':at': access_token,
            ':rt': refresh_token,
            ':exp': expires_at,
            ':ua': datetime.utcnow().isoformat()
        }
    )

def log_activity(user_id, user_email, user_name, user_role, action, details, resource_type=None, resource_id=None):
    """Log user activity"""
    timestamp = datetime.utcnow().isoformat()
    log_id = str(uuid.uuid4())
    
    item = {
        'PK': f'USER#{user_id}',
        'SK': f'LOG#{timestamp}#{log_id}',
        'EntityType': 'ActivityLog',
        'log_id': log_id,
        'user_id': user_id,
        'user_email': user_email,
        'user_name': user_name,
        'user_role': user_role,
        'action': action,
        'details': details,
        'timestamp': timestamp
    }
    
    if resource_type:
        item['resource_type'] = resource_type
    if resource_id:
        item['resource_id'] = resource_id
    
    table.put_item(Item=item)
    return item

def create_thread(user_id, title):
    """Create a new conversation thread"""
    timestamp = datetime.utcnow().isoformat()
    thread_id = str(uuid.uuid4())
    
    item = {
        'PK': f'USER#{user_id}',
        'SK': f'THREAD#{thread_id}',
        'EntityType': 'Thread',
        'thread_id': thread_id,
        'user_id': user_id,
        'title': title,
        'conversation_status': 'active',
        'created_at': timestamp,
        'updated_at': timestamp,
        'message_count': 0,
        'GSI4PK': f'THREAD#{thread_id}',
        'GSI4SK': timestamp
    }
    
    table.put_item(Item=item)
    return item

def add_message(thread_id, user_id, sender, content):
    """Add a message to a thread"""
    timestamp = datetime.utcnow().isoformat()
    message_id = str(uuid.uuid4())
    
    item = {
        'PK': f'THREAD#{thread_id}',
        'SK': f'MSG#{timestamp}#{message_id}',
        'EntityType': 'Message',
        'message_id': message_id,
        'thread_id': thread_id,
        'user_id': user_id,
        'sender': sender,  # 'user' or 'assistant'
        'content': content,
        'created_at': timestamp,
        'GSI5PK': f'USER#{user_id}#MSG',
        'GSI5SK': timestamp
    }
    
    table.put_item(Item=item)
    
    # Update thread message count
    table.update_item(
        Key={
            'PK': f'USER#{user_id}',
            'SK': f'THREAD#{thread_id}'
        },
        UpdateExpression='SET message_count = message_count + :inc, updated_at = :ua',
        ExpressionAttributeValues={
            ':inc': 1,
            ':ua': timestamp
        }
    )
    
    return item

def get_thread_messages(thread_id, limit=20):
    """Get messages from a thread (newest first)"""
    response = table.query(
        KeyConditionExpression=Key('PK').eq(f'THREAD#{thread_id}') & 
                              Key('SK').begins_with('MSG#'),
        ScanIndexForward=False,  # Newest first
        Limit=limit
    )
    return response.get('Items', [])

def get_user_threads(user_id):
    """Get all threads for a user"""
    response = table.query(
        KeyConditionExpression=Key('PK').eq(f'USER#{user_id}') & 
                              Key('SK').begins_with('THREAD#'),
        ScanIndexForward=False  # Newest first
    )
    return response.get('Items', [])

def log_tool_call(thread_id, message_id, user_id, tool_name, input_params, output_result, status):
    """Log an agent tool call"""
    timestamp = datetime.utcnow().isoformat()
    tool_call_id = str(uuid.uuid4())
    
    item = {
        'PK': f'THREAD#{thread_id}',
        'SK': f'TOOL#{timestamp}#{tool_call_id}',
        'EntityType': 'ToolCall',
        'tool_call_id': tool_call_id,
        'message_id': message_id,
        'thread_id': thread_id,
        'user_id': user_id,
        'tool_name': tool_name,
        'input_params': input_params,
        'output_result': output_result,
        'status': status,
        'created_at': timestamp
    }
    
    table.put_item(Item=item)
    return item

def get_user_activity_logs(user_id, limit=50):
    """Get user activity logs"""
    response = table.query(
        KeyConditionExpression=Key('PK').eq(f'USER#{user_id}') & 
                              Key('SK').begins_with('LOG#'),
        ScanIndexForward=False,  # Newest first
        Limit=limit
    )
    return response.get('Items', [])
```

---

## 🚀 Complete Workflow Example

### User Chats with AI → Agent Creates Google Doc

```python
def handle_chat_message(user_id, thread_id, message_content):
    """Handle incoming chat message and process with AI agent"""
    
    # 1. Get user profile and OAuth tokens
    user = get_user(user_id)
    oauth_tokens = {
        'access_token': user['google_access_token'],
        'refresh_token': user['google_refresh_token'],
        'expires_at': user['token_expiry']
    }
    
    # 2. Create thread if new conversation
    if not thread_id:
        thread = create_thread(user_id, title='New conversation')
        thread_id = thread['thread_id']
    
    # 3. Save user message
    user_message = add_message(
        thread_id=thread_id,
        user_id=user_id,
        sender='user',
        content=message_content
    )
    
    # 4. Load conversation history (last 20 messages)
    message_history = get_thread_messages(thread_id, limit=20)
    
    # 5. Call AI supervisor agent with context
    agent_response = supervisor_agent.invoke(
        user_message=message_content,
        conversation_history=message_history,
        oauth_tokens=oauth_tokens
    )
    
    # 6. Save agent response
    assistant_message = add_message(
        thread_id=thread_id,
        user_id=user_id,
        sender='assistant',
        content=agent_response['message']
    )
    
    # 7. Log tool calls if agent used any
    if agent_response.get('tool_calls'):
        for tool_call in agent_response['tool_calls']:
            log_tool_call(
                thread_id=thread_id,
                message_id=assistant_message['message_id'],
                user_id=user_id,
                tool_name=tool_call['name'],
                input_params=tool_call['input'],
                output_result=tool_call['output'],
                status=tool_call['status']
            )
    
    # 8. Log activity
    log_activity(
        user_id=user_id,
        user_email=user['email'],
        user_name=user['name'],
        user_role=user['role'],
        action='chat_message',
        details=f'User chatted with AI supervisor',
        resource_type='thread',
        resource_id=thread_id
    )
    
    return {
        'thread_id': thread_id,
        'assistant_message': assistant_message,
        'tool_calls': agent_response.get('tool_calls', [])
    }
```

---

## 📝 Usage Examples

### Example 1: Creating a New User
```python
user = create_user(
    user_id='user-123',
    email='john@safexpress.com',
    name='John Doe',
    role='admin',
    department='Operations',
    oauth_tokens={
        'access_token': 'ya29.xxx',
        'refresh_token': '1//xxx',
        'expires_at': '2025-10-17T11:00:00Z'
    }
)
```

### Example 2: Starting a Conversation
```python
# User starts chatting
result = handle_chat_message(
    user_id='user-123',
    thread_id=None,  # New conversation
    message_content='Create a Q4 report document for me'
)

print(f"Thread ID: {result['thread_id']}")
print(f"AI Response: {result['assistant_message']['content']}")
```

### Example 3: Loading Conversation History
```python
# Get all threads for a user
threads = get_user_threads('user-123')

# Get messages from a specific thread
messages = get_thread_messages('uuid-123', limit=50)

for msg in messages:
    print(f"{msg['sender']}: {msg['content']}")
```

### Example 4: Viewing Activity Logs
```python
# Get user activity
logs = get_user_activity_logs('user-123', limit=100)

for log in logs:
    print(f"{log['timestamp']} - {log['action']}: {log['details']}")
```

---

## 🔒 Security Best Practices

1. **Encrypt OAuth Tokens:** Use AWS KMS to encrypt tokens before storing
2. **IAM Roles:** Lambda functions should have minimal permissions
3. **Token Refresh:** Implement automatic token refresh logic
4. **Audit Logs:** Activity logs provide complete audit trail
5. **Access Control:** Verify user_id matches JWT claims

---

## 📊 Access Patterns Summary

| Pattern | Keys Used | GSI |
|---------|-----------|-----|
| Get user profile | PK=USER#id, SK=PROFILE | None |
| Get user threads | PK=USER#id, SK^=THREAD# | None |
| Get thread messages | PK=THREAD#id, SK^=MSG# | None |
| Get user activity | PK=USER#id, SK^=LOG# | None |
| Search by thread ID | thread_id | GSI4 |
| User message history | user_id | GSI5 |

---

## 🎯 Key Benefits of This Design

✅ **Single Table Design** - Reduces costs and latency  
✅ **Composite Keys** - Enables hierarchical data access  
✅ **Denormalization** - Reduces need for joins  
✅ **GSI Flexibility** - Supports multiple access patterns  
✅ **Scalable** - Handles millions of messages efficiently  
✅ **Audit Trail** - Complete activity logging built-in

---

**Created for:** SafexpressOps Capstone Project  
**Database:** AWS DynamoDB  
**Region:** ap-southeast-1 (Singapore)
