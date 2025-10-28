# Conversational Agent Integration Guide

## 🎯 Overview

The supervisor agent now has **two modes of operation**:

1. **Conversational Mode** (`/chat`) - Interactive, asks clarifying questions ✨ **NEW**
2. **Direct Execution Mode** (`/workflow`) - Assumes complete input, executes immediately

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    USER REQUEST                          │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
         ┌─────────────────────┐
         │  Which endpoint?    │
         └─────────┬───────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
         ▼                   ▼
    /chat (NEW)         /workflow (OLD)
    Interactive         Direct Execute
         │                   │
         ▼                   │
┌─────────────────┐          │
│ 🤖 Conversational│          │
│     Agent        │          │
│ - Validates      │          │
│ - Clarifies      │          │
│ - Asks questions │          │
└────────┬─────────┘          │
         │                    │
         │ [When ready]       │
         ▼                    ▼
┌──────────────────────────────────────────────────────────┐
│         🧠 SUPERVISOR AGENT                              │
│         Generates execution plan                         │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│         ⚙️ ORCHESTRATOR                                  │
│         Executes plan steps                              │
└──────────────────────────────────────────────────────────┘
```

---

## 📡 New Endpoints

### 1. `POST /chat` - Interactive Conversation

**Purpose**: Validate, clarify, and gather complete information before execution.

**Request**:
```json
{
  "message": "Send an email about the meeting",
  "conversation_id": null,  // Optional: for continuing conversations
  "auto_execute": false     // If true, executes automatically when ready
}
```

**Response**:
```json
{
  "response": "📋 Who would you like to send this email to?\n\n**So far I have:**\n- subject: meeting\n- task: send email",
  "conversation_id": "conv_a1b2c3d4",
  "ready_for_execution": false,
  "intent": "needs_clarification",
  "extracted_info": {
    "subject": "meeting",
    "task": "send email"
  },
  "execution_summary": null
}
```

---

### 2. `POST /chat/{conversation_id}/execute` - Execute Ready Conversation

**Purpose**: Execute a conversation that has all required information.

**Request**: No body needed, just conversation ID in URL

**Response**: Standard `WorkflowResponse`

**Example**:
```bash
POST /chat/conv_a1b2c3d4/execute
```

---

### 3. `GET /chat/{conversation_id}` - View Conversation State

**Purpose**: Inspect conversation history and extracted information.

**Response**:
```json
{
  "conversation_id": "conv_a1b2c3d4",
  "ready_for_execution": true,
  "intent": "ready_to_execute",
  "extracted_info": {
    "recipient": "john@example.com",
    "subject": "Meeting notes",
    "body": "Here are the notes from today's meeting"
  },
  "missing_fields": [],
  "execution_summary": "Send email to john@example.com with subject 'Meeting notes'",
  "conversation_history": [
    {"role": "user", "content": "Send an email about the meeting"},
    {"role": "assistant", "content": "Who would you like to send this email to?"},
    {"role": "user", "content": "john@example.com"}
  ]
}
```

---

### 4. `DELETE /chat/{conversation_id}` - Clear Conversation

**Purpose**: Reset or abandon a conversation.

---

### 5. `GET /conversations` - List All Conversations

**Purpose**: See all active conversations (useful for debugging).

---

## 🎭 Usage Scenarios

### Scenario 1: Multi-Turn Clarification

**Turn 1: User starts vague request**
```bash
POST /chat
{
  "message": "Send an email"
}
```

**Response**:
```json
{
  "response": "📋 I can help you send an email. Let me gather some information:\n\n1. Who should I send this email to?\n2. What should the subject be?\n3. What should I write in the email?",
  "conversation_id": "conv_abc123",
  "ready_for_execution": false,
  "intent": "needs_clarification"
}
```

**Turn 2: User provides recipient**
```bash
POST /chat
{
  "message": "Send it to john@example.com",
  "conversation_id": "conv_abc123"
}
```

**Response**:
```json
{
  "response": "📋 Great! What should the subject line be?\n\n**So far I have:**\n- recipient: john@example.com",
  "conversation_id": "conv_abc123",
  "ready_for_execution": false,
  "intent": "needs_clarification"
}
```

**Turn 3: User completes information**
```bash
POST /chat
{
  "message": "Subject is 'Meeting Notes' and tell him the meeting is rescheduled to Friday",
  "conversation_id": "conv_abc123"
}
```

**Response**:
```json
{
  "response": "✅ **Ready to execute!**\n\n**Task:** Send email to john@example.com with subject 'Meeting Notes'\n\n**Details:**\n- recipient: john@example.com\n- subject: Meeting Notes\n- body: the meeting is rescheduled to Friday\n\nShould I proceed?",
  "conversation_id": "conv_abc123",
  "ready_for_execution": true,
  "intent": "ready_to_execute",
  "execution_summary": "Send email to john@example.com with subject 'Meeting Notes' about meeting rescheduled to Friday"
}
```

**Turn 4: User confirms and executes**
```bash
POST /chat/conv_abc123/execute
```

---

### Scenario 2: Auto-Execute Mode

**Single request with auto-execute**:
```bash
POST /chat
{
  "message": "Search for emails from sarah@company.com about project alpha",
  "auto_execute": true
}
```

**Response** (if complete):
```json
{
  "response": "✅ **Ready to execute!**\n\n**Task:** Search emails from sarah@company.com with keyword 'project alpha'\n\n✅ Executed! Workflow executed successfully",
  "conversation_id": "conv_xyz789",
  "ready_for_execution": false,  // Already executed
  "intent": "ready_to_execute",
  "execution_summary": "Search emails from sarah@company.com about project alpha"
}
```

---

### Scenario 3: Infeasible Task

**Request**:
```bash
POST /chat
{
  "message": "Book a flight to Tokyo and reserve a hotel"
}
```

**Response**:
```json
{
  "response": "❌ I'm unable to help with that request.\n\n**Reason:** I don't have access to flight booking or hotel reservation systems.\n\n**What I can do instead:**\n- Search your emails for flight/hotel confirmations\n- Create a draft email to your travel agent\n- Add travel dates to your calendar\n\n**Available capabilities:**\n- gmail-agent: send_email, search_emails, reply_to_email, create_draft_email, etc.\n- calendar-agent: create_event, search_events, update_event, etc.",
  "conversation_id": "conv_def456",
  "ready_for_execution": false,
  "intent": "not_feasible"
}
```

---

### Scenario 4: Complex Task

**Request**:
```bash
POST /chat
{
  "message": "Find all emails from last month, summarize them, and send a report to my team"
}
```

**Response**:
```json
{
  "response": "⚠️ This task seems quite complex.\n\n**Analysis:** This requires multiple steps including email search, content summarization (AI processing), and team email distribution.\n\n**I suggest breaking it down:**\n1. First, let me search for emails from last month\n2. Then I can create a draft with the email list and key subjects\n3. You can review and add your summary\n4. Finally, I'll help you send it to your team\n\nWould you like to proceed with one of these approaches?",
  "conversation_id": "conv_ghi789",
  "ready_for_execution": false,
  "intent": "too_complex"
}
```

---

## 🔄 Conversation Flow States

```
┌─────────────────┐
│  SMALL_TALK     │  "Hello", "How are you?"
└─────────────────┘
         │
         ▼
┌─────────────────┐
│ NEEDS_CLARIF... │  Missing required info
└────────┬────────┘
         │ User provides more info
         ▼
┌─────────────────┐
│ READY_TO_EXEC...│  All info collected ✅
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   EXECUTING     │  Passed to supervisor
└─────────────────┘

Alternative paths:
┌─────────────────┐
│ NOT_FEASIBLE    │  Can't do with available tools ❌
└─────────────────┘

┌─────────────────┐
│ TOO_COMPLEX     │  Needs breaking down ⚠️
└─────────────────┘
```

---

## 🛠️ Integration Examples

### Python Client Example

```python
import requests

BASE_URL = "http://localhost:8000"

def send_message(message: str, conversation_id: str = None, auto_execute: bool = False):
    """Send a message to the conversational agent"""
    response = requests.post(
        f"{BASE_URL}/chat",
        json={
            "message": message,
            "conversation_id": conversation_id,
            "auto_execute": auto_execute
        }
    )
    return response.json()

# Multi-turn conversation
conv_id = None

# Turn 1
result = send_message("Send an email")
print(result["response"])
conv_id = result["conversation_id"]

# Turn 2
result = send_message("To john@example.com", conversation_id=conv_id)
print(result["response"])

# Turn 3
result = send_message(
    "Subject: Meeting, Body: Let's meet tomorrow",
    conversation_id=conv_id
)
print(result["response"])

# Execute if ready
if result["ready_for_execution"]:
    execute_response = requests.post(f"{BASE_URL}/chat/{conv_id}/execute")
    print(execute_response.json())
```

### cURL Examples

```bash
# Start conversation
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Send an email about project update",
    "auto_execute": false
  }'

# Continue conversation
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Send it to team@company.com",
    "conversation_id": "conv_abc123"
  }'

# Get conversation state
curl http://localhost:8000/chat/conv_abc123

# Execute when ready
curl -X POST http://localhost:8000/chat/conv_abc123/execute

# List all conversations
curl http://localhost:8000/conversations

# Clear conversation
curl -X DELETE http://localhost:8000/chat/conv_abc123
```

---

## 🆚 When to Use Each Endpoint

### Use `/chat` (Conversational) When:
- ✅ Building a chatbot or interactive UI
- ✅ User input might be incomplete or ambiguous
- ✅ You want to validate requests before execution
- ✅ Users are non-technical and need guidance
- ✅ Tasks might be infeasible or too complex
- ✅ You want to suggest alternatives

### Use `/workflow` (Direct) When:
- ✅ You have complete, well-formed input
- ✅ Input is programmatically generated
- ✅ You want immediate execution without validation
- ✅ You're doing automated/scheduled tasks
- ✅ You've already validated the request

---

## 🎨 Frontend Integration Example (React)

```jsx
import { useState } from 'react';

function ChatInterface() {
  const [messages, setMessages] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [input, setInput] = useState('');

  const sendMessage = async () => {
    const response = await fetch('http://localhost:8000/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: input,
        conversation_id: conversationId,
        auto_execute: false
      })
    });
    
    const data = await response.json();
    
    setMessages([
      ...messages,
      { role: 'user', content: input },
      { role: 'assistant', content: data.response }
    ]);
    
    setConversationId(data.conversation_id);
    setInput('');
    
    // Show execute button if ready
    if (data.ready_for_execution) {
      setShowExecuteButton(true);
    }
  };

  const execute = async () => {
    const response = await fetch(
      `http://localhost:8000/chat/${conversationId}/execute`,
      { method: 'POST' }
    );
    const result = await response.json();
    
    setMessages([
      ...messages,
      { role: 'system', content: '✅ Task executed successfully!' }
    ]);
  };

  return (
    <div className="chat-interface">
      <div className="messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
      </div>
      <input 
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyPress={e => e.key === 'Enter' && sendMessage()}
      />
      {showExecuteButton && (
        <button onClick={execute}>Execute Task</button>
      )}
    </div>
  );
}
```

---

## 🔒 Security Considerations

1. **Conversation Timeout**: Implement TTL for conversations (currently in-memory)
2. **User Authentication**: Associate conversations with authenticated users
3. **Rate Limiting**: Prevent abuse of clarification questions
4. **Sensitive Data**: Don't log full conversation history in production
5. **Session Management**: Use Redis/DB instead of in-memory `CONVERSATIONS`

---

## 📊 Migration Path

### Phase 1: Add conversational endpoints (✅ Done)
- Implement `/chat` endpoints
- Keep `/workflow` for backward compatibility

### Phase 2: Test with users
- Collect feedback on clarification quality
- Tune LLM prompts based on real conversations

### Phase 3: Make conversation default
- Update frontend to use `/chat` by default
- Keep `/workflow` for API/automation use

### Phase 4: Add advanced features
- Conversation branching (alternative approaches)
- Confidence scoring (show uncertainty)
- User preference learning

---

## 🎯 Summary

| Feature | `/chat` (NEW) | `/workflow` (OLD) |
|---------|---------------|-------------------|
| Validates input | ✅ Yes | ❌ No |
| Asks questions | ✅ Yes | ❌ No |
| Multi-turn | ✅ Yes | ❌ No |
| Checks feasibility | ✅ Yes | ❌ No |
| Suggests alternatives | ✅ Yes | ❌ No |
| Auto-execute option | ✅ Yes | ✅ Always |
| Best for | Humans | APIs/Scripts |

**Bottom Line**: Use `/chat` for interactive user-facing applications, use `/workflow` for programmatic execution! 🎉
