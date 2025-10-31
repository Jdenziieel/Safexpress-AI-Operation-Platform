import React, { useState, useEffect, useRef } from "react";
import { Sparkles, Send, Clock, CheckCircle, XCircle, Loader2, Mail, Calendar, User } from "lucide-react";
import "../css/AIChat3.css";

// Assuming you have an api.js file configured, otherwise use a direct fetch or axios
// import api from "../api";
// If not using api.js, define the base URL here:
const API_BASE_URL = "http://localhost:8000"; // Match your FastAPI server port

// Helper function to parse email results from assistant response
function parseEmailResults(content) {
  try {
    // Try to extract JSON from the response
    const jsonMatch = content.match(/\{[\s\S]*"emails"[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      if (parsed.emails && Array.isArray(parsed.emails)) {
        return parsed.emails;
      }
    }
    
    // Try to find email objects in the text
    const emailPattern = /\{\s*"message_id"[\s\S]*?"subject"[\s\S]*?"from"[\s\S]*?\}/g;
    const matches = content.match(emailPattern);
    if (matches) {
      return matches.map(match => {
        try {
          return JSON.parse(match);
        } catch {
          return null;
        }
      }).filter(Boolean);
    }
  } catch (e) {
    console.log("Could not parse emails from response:", e);
  }
  return null;
}

// Email Card Component
function EmailCard({ email }) {
  return (
    <div style={{
      background: 'white',
      border: '1px solid #e2e8f0',
      borderRadius: '8px',
      padding: '1rem',
      marginBottom: '0.75rem',
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', marginBottom: '0.5rem' }}>
        <Mail size={18} color="#26326E" style={{ flexShrink: 0, marginTop: '2px' }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, color: '#1e293b', marginBottom: '0.25rem' }}>
            {email.subject || 'No Subject'}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', fontSize: '0.85rem', color: '#64748b' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              <User size={14} />
              <span>{email.from || 'Unknown'}</span>
            </div>
            {email.date && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                <Calendar size={14} />
                <span>{new Date(email.date).toLocaleDateString()}</span>
              </div>
            )}
          </div>
        </div>
      </div>
      {email.body && (
        <div style={{
          fontSize: '0.9rem',
          color: '#475569',
          marginTop: '0.5rem',
          paddingTop: '0.5rem',
          borderTop: '1px solid #f1f5f9',
          maxHeight: '100px',
          overflow: 'hidden',
          textOverflow: 'ellipsis'
        }}>
          {email.body.substring(0, 200)}{email.body.length > 200 ? '...' : ''}
        </div>
      )}
    </div>
  );
}

function AIChat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  // Use 'threadId' to match the backend's terminology
  const [threadId, setThreadId] = useState(null);
  const [isLoadingThread, setIsLoadingThread] = useState(true); // Loading state for initial thread setup
  const [pendingActions, setPendingActions] = useState([]);
  const [isFetchingPending, setIsFetchingPending] = useState(false);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
    }
  }, [input]);

  // Load or create thread on mount
  useEffect(() => {
    loadOrCreateThread();
  }, []);

  // Poll for pending actions every 5 seconds (or use WebSocket if available)
  useEffect(() => {
    const intervalId = setInterval(() => {
      if (!isStreaming) { // Don't fetch if a message is currently being processed
        fetchPendingActions();
      }
    }, 5000); // 5 seconds

    return () => clearInterval(intervalId); // Cleanup on unmount
  }, [isStreaming]); // Re-run effect if isStreaming changes


  const loadOrCreateThread = async () => {
    setIsLoadingThread(true);
    try {
      // Try to get existing conversations
      // const response = await api.get("/conversations"); // If using api.js
      const response = await fetch(`${API_BASE_URL}/conversations`);
      if (!response.ok) {
         throw new Error(`Failed to list conversations: ${response.status} ${response.statusText}`);
      }
      const threadsData = await response.json();
      console.log("Fetched conversations:", threadsData);

      // Use the most recent thread if it exists
      if (threadsData.conversations && threadsData.conversations.length > 0) {
        const latestThread = threadsData.conversations[0]; // Assuming list is sorted by creation time
        setThreadId(latestThread.conversation_id);
        // Load messages from this thread using the GET endpoint
        await loadThreadMessages(latestThread.conversation_id);
        setIsLoadingThread(false);
        console.log("Loaded existing thread:", latestThread.conversation_id);
        return;
      }
      // No threads exist, create a new one
      await createNewThread();
    } catch (error) {
      console.error("Error loading or creating thread:", error);
      // Create new thread as fallback
      await createNewThread();
    }
  };

  const createNewThread = async () => {
    try {
      // Create a new conversation (thread) by sending an initial message
      // const response = await api.post("/chat", { message: "Hello!" }); // If using api.js
      const response = await fetch(`${API_BASE_URL}/chat`, {
         method: "POST",
         headers: {
             "Content-Type": "application/json",
         },
         body: JSON.stringify({
             message: "Hello!",
             // auto_execute: false // Explicitly set if needed, defaults to false in backend
         }),
      });
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setThreadId(data.conversation_id);
      // Add the initial bot response to the messages
      if (data.response) {
          setMessages([
              {
                  id: `bot-${Date.now()}`, // Generate a unique ID
                  role: "assistant",
                  content: data.response,
                  timestamp: new Date(),
              }
          ]);
      }
      console.log("✅ Created new thread:", data.conversation_id);
    } catch (error) {
      console.error("Error creating thread:", error);
      // Optionally add an error message to the UI
      setMessages(prev => [...prev, {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: `Failed to start a new conversation: ${error.message}`,
          timestamp: new Date(),
          error: true,
      }]);
    } finally {
      setIsLoadingThread(false);
    }
  };

  const loadThreadMessages = async (thread_id) => {
    try {
      // Fetch conversation details including history
      // const response = await api.get(`/chat/${thread_id}`); // If using api.js
      const response = await fetch(`${API_BASE_URL}/chat/${thread_id}`);
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      console.log("Loaded conversation details:", data);

      // Convert messages to UI format using the backend's structure
      const formattedMessages = (data.conversation_history || []).map((msg, idx) => ({
        id: msg.message_id || `msg-${thread_id}-${idx}`, // Use backend ID or generate one
        role: msg.sender || msg.role || "assistant", // Fallback if sender is not set
        content: msg.message || msg.content || "No content", // Fallback if content field varies
        timestamp: msg.created_at ? new Date(msg.created_at) : new Date(),
      }));
      setMessages(formattedMessages);
      console.log(`✅ Loaded ${formattedMessages.length} messages for thread ${thread_id}`);
    } catch (error) {
      console.error("Error loading messages:", error);
      // Optionally add an error message to the UI
      setMessages(prev => [...prev, {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: `Failed to load messages: ${error.message}`,
          timestamp: new Date(),
          error: true,
      }]);
    }
  };

  const fetchPendingActions = async () => {
    // Prevent multiple simultaneous fetches
    if (isFetchingPending) return;
    setIsFetchingPending(true);
    try {
      // const response = await api.get("/actions/pending"); // If using api.js
      const response = await fetch(`${API_BASE_URL}/actions/pending`);
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      console.log("Fetched pending actions:", data);
      setPendingActions(data.pending_actions || []);
    } catch (error) {
      console.error("Error fetching pending actions:", error);
      // Optionally clear pending actions or show an error
      // setPendingActions([]); // Or keep the old list if error is temporary
    } finally {
      setIsFetchingPending(false);
    }
  };

  const handleApproveAction = async (actionId) => {
    try {
      // const response = await api.post(`/action/approve/${actionId}`, { decision: 'approve' }); // If using api.js
      const response = await fetch(`${API_BASE_URL}/action/approve/${actionId}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ decision: 'approve' }),
      });
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const result = await response.json();
      console.log("Action approved:", result);
      // Remove the approved action from the local state
      setPendingActions(prev => prev.filter(action => action.action_id !== actionId));
      // Optionally add a message to the chat confirming approval
      setMessages(prev => [...prev, {
          id: `approval-${actionId}`,
          role: "assistant",
          content: `Action "${result.step_info?.description || 'Unknown Action'}" approved and executed.`,
          timestamp: new Date(),
          info: true,
      }]);
    } catch (error) {
      console.error("Error approving action:", error);
      // Optionally add an error message to the chat or update the action status
      setMessages(prev => [...prev, {
          id: `approval-error-${actionId}`,
          role: "assistant",
          content: `Failed to approve action ${actionId}: ${error.message}`,
          timestamp: new Date(),
          error: true,
      }]);
    }
  };

  const handleRejectAction = async (actionId) => {
    try {
      // const response = await api.post(`/action/approve/${actionId}`, { decision: 'reject' }); // If using api.js
      const response = await fetch(`${API_BASE_URL}/action/approve/${actionId}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ decision: 'reject' }),
      });
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const result = await response.json();
      console.log("Action rejected:", result);
      // Remove the rejected action from the local state
      setPendingActions(prev => prev.filter(action => action.action_id !== actionId));
      // Optionally add a message to the chat confirming rejection
      setMessages(prev => [...prev, {
          id: `rejection-${actionId}`,
          role: "assistant",
          content: `❌ Action was rejected and will not be executed.`,
          timestamp: new Date(),
          info: true,
      }]);
    } catch (error) {
      console.error("Error rejecting action:", error);
      // Optionally add an error message to the chat or update the action status
      setMessages(prev => [...prev, {
          id: `rejection-error-${actionId}`,
          role: "assistant",
          content: `Failed to reject action ${actionId}: ${error.message}`,
          timestamp: new Date(),
          error: true,
      }]);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isStreaming || !threadId) return;

    const userMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    const userInput = input.trim();
    setInput("");
    setIsStreaming(true);

    // Add empty assistant message for streaming effect
    const assistantMessageId = `assistant-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
      },
    ]);

    try {
      console.log("📤 Sending message to thread:", threadId, "Message:", userInput);
      // Send message to the conversational endpoint
      // const response = await api.post(`/chat`, { // If using api.js
      const response = await fetch(`${API_BASE_URL}/chat`, {
         method: "POST",
         headers: {
             "Content-Type": "application/json",
         },
         body: JSON.stringify({
             conversation_id: threadId, // Include the thread ID
             message: userInput,
             // auto_execute: false // Explicitly set if needed, defaults to false in backend
         }),
      });
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      console.log("📥 Received response from chat endpoint:", data);

      // Get the bot's response text
      const fullResponse = data.response || "No response received from the assistant.";
      // Check if the conversation is now ready for execution
      const isReadyForExecution = !!data.ready_for_execution; // Convert to boolean
      if (isReadyForExecution) {
          console.log("✅ Workflow ready for execution based on response.");
          // Optionally inform the user or trigger execution automatically if configured
          // For now, just log and continue showing the bot's response
          // You could append a message like: "The plan is ready to execute."
          // setMessages(prev => [...prev, {
          //    id: `info-${Date.now()}`,
          //    role: "assistant",
          //    content: "The plan is ready. It will be executed automatically.",
          //    timestamp: new Date(),
          //    info: true, // Add a custom flag for styling if needed
          // }]);
      }

      // Simulate streaming effect (word by word)
      let currentText = "";
      const words = fullResponse.split(" ");
      for (let i = 0; i < words.length; i++) {
        currentText += (i > 0 ? " " : "") + words[i];
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, content: currentText }
              : msg
          )
        );
        await new Promise((resolve) => setTimeout(resolve, 30));
      }

      // Update the assistant message with actual message_id from backend if provided
      if (data.assistant_message_id) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, id: data.assistant_message_id }
              : msg
          )
        );
      }

      // Check if the response indicates readiness and auto-execute if configured
      // Request: Auto-execute when ready (This will now require manual approval if risk level is DANGEROUS)
      if (isReadyForExecution) {
          console.log("🔄 Auto-executing conversation:", threadId);
          // Call the execute endpoint
          // const execResponse = await api.post(`/chat/${threadId}/execute`); // If using api.js
          const execResponse = await fetch(`${API_BASE_URL}/chat/${threadId}/execute`, {
             method: "POST",
          });
          if (!execResponse.ok) {
              const execErrorData = await execResponse.json().catch(() => ({ detail: `HTTP error! status: ${execResponse.status}` }));
              // Throw error to be caught by outer catch block
              throw new Error(execErrorData.detail || `Execution failed: ${execResponse.status}`);
          }
          const execResult = await execResponse.json();
          console.log("✅ Execution completed or paused for approval:", execResult);

          // Check if execution was paused for approval
          if (execResult.status === 'approval_required') {
              console.log("🔄 Execution paused, awaiting approval. Action ID:", execResult.action_id);
              // The backend will have added the pending action to its internal store.
              // Our polling effect should pick it up shortly.
              // Optionally add a message to the chat indicating approval is needed
              setMessages(prev => [...prev, {
                  id: `approval-needed-${Date.now()}`,
                  role: "assistant",
                  content: `Action "${execResult.step_info?.description || 'Unknown Action'}" requires your approval.`,
                  timestamp: new Date(),
                  info: true,
              }]);
          } else {
              // Execution completed immediately (or failed after execution started)
              // Optionally add execution summary to messages or inform user
              setMessages(prev => [...prev, {
                  id: `exec-summary-${Date.now()}`,
                  role: "assistant",
                  content: `Execution completed. Summary: ${execResult.execution_summary || 'Task finished.'}`,
                  timestamp: new Date(),
                  info: true,
              }]);
          }
          // Note: The backend deletes the conversation after execution if auto_execute was true in the initial request.
          // If auto_execute was false (as it is now), the conversation state is kept but might be reset depending on implementation.
          // For the approval flow, the conversation state is kept until the action is approved/rejected.
      }


    } catch (error) {
      console.error("Error during chat or execution:", error);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: `Sorry, I encountered an error: ${error.message}. Please try again.`,
                error: true,
              }
            : msg
        )
      );
    } finally {
      setIsStreaming(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleSuggestionClick = (suggestion) => {
    setInput(suggestion);
    textareaRef.current?.focus();
  };

  const handleNewChat = async () => {
    // Clear the current thread state
    setMessages([]);
    // The backend doesn't have a direct clear endpoint for the conversational API state,
    // but creating a new thread achieves the same effect.
    // If you had the old threadId, you *could* try DELETE /chat/{threadId}, but it's not strictly necessary here
    // as creating a new one starts fresh anyway.
    await createNewThread();
  };

  const suggestions = [
    "Create a document called Meeting Notes",
    "Send an email to my team about the project update",
    "Read my recent emails",
    "Help me organize my tasks for today",
  ];

  // Show loading state while thread is being created
  if (isLoadingThread) {
    return (
      <div className="ai-chat-page">
        <div className="aichat-container">
          <div className="loading-container">
            <Sparkles size={48} className="loading-icon" />
            <p>Loading chat...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ai-chat-page">
      <div className="aichat-container">
        <header className="page-header">
          <div>
            <h1 className="aichat-header-title">
              <Sparkles
                size={32}
                style={{ marginRight: "0.5rem", color: "#26326E" }}
              />
              AI Chat
            </h1>
            <p className="header-subtitle">
              Chat with AI assistant powered by your Google Workspace
            </p>
          </div>
          <button
            onClick={handleNewChat}
            className="new-chat-button"
            disabled={isStreaming}
          >
            + New Chat
          </button>
        </header>

        {/* Pending Actions Widget */}
        {pendingActions.length > 0 && (
          <div className="pending-actions-widget">
            <h3 className="pending-actions-title">
              <Clock size={18} className="pending-actions-icon" /> Pending Actions
            </h3>
            <div className="pending-actions-list">
              {pendingActions.map((action) => (
                <div key={action.action_id} className="pending-action-item">
                  <div className="pending-action-details">
                    {/* Access action properties directly (not nested under step_info) */}
                    <p className="pending-action-description">{action.description || "Action description unavailable"}</p>
                    <p className="pending-action-agent">Agent: <strong>{action.agent || "Unknown Agent"}</strong></p>
                    <p className="pending-action-tool">Tool: <strong>{action.tool || "Unknown Tool"}</strong></p>
                    {action.inputs && Object.keys(action.inputs).length > 0 && (
                      <details className="pending-action-inputs">
                        <summary>Inputs</summary>
                        <pre>{JSON.stringify(action.inputs, null, 2)}</pre>
                      </details>
                    )}
                  </div>
                  <div className="pending-action-buttons">
                    <button
                      onClick={() => handleApproveAction(action.action_id)}
                      className="approve-button"
                      disabled={isFetchingPending}
                    >
                      <CheckCircle size={16} /> Approve
                    </button>
                    <button
                      onClick={() => handleRejectAction(action.action_id)}
                      className="reject-button"
                      disabled={isFetchingPending}
                    >
                      <XCircle size={16} /> Reject
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {isFetchingPending && pendingActions.length === 0 && (
          <div className="fetching-pending-indicator">
            <Loader2 size={16} className="fetching-spinner" />
            <span>Checking for pending actions...</span>
          </div>
        )}

        <main className="chat-card">
          <div className="messages-area">
            {messages.length === 0 ? (
              <div className="welcome-container">
                <div className="welcome-icon">
                  <Sparkles size={48} />
                </div>
                <h2 className="welcome-title">
                  Hello! How can I help you today?
                </h2>
                <p className="welcome-subtitle">
                  I can help you with Gmail, Google Docs, Drive, and more
                </p>

                <div className="suggestions-grid">
                  {suggestions.map((suggestion, i) => (
                    <button
                      key={i}
                      onClick={() => handleSuggestionClick(suggestion)}
                      className="suggestion-card"
                    >
                      <span className="suggestion-icon">💡</span>
                      <span className="suggestion-text">{suggestion}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {messages.map((message) => {
                  // Check if message contains email results
                  const emails = message.role === "assistant" ? parseEmailResults(message.content) : null;
                  
                  return (
                    <div
                      key={message.id}
                      className={`message-wrapper ${message.role} ${message.error ? 'error' : ''} ${message.info ? 'info' : ''}`}
                    >
                      <div
                        className={`message-bubble ${message.role} ${
                          message.error ? "error" : ""
                        } ${message.info ? "info" : ""}`}
                      >
                        {emails && emails.length > 0 ? (
                          // Render emails in a nice card format
                          <div className="message-content">
                            <div style={{ marginBottom: '0.75rem', fontWeight: 600, color: '#26326E' }}>
                              📧 Found {emails.length} email{emails.length !== 1 ? 's' : ''}
                            </div>
                            {emails.map((email, idx) => (
                              <EmailCard key={email.message_id || idx} email={email} />
                            ))}
                          </div>
                        ) : (
                          // Render normal text message
                          <div className="message-content">
                            {message.content}
                            {message.role === "assistant" &&
                              isStreaming &&
                              message.content && (
                                <span className="cursor-blink">|</span>
                              )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          <form onSubmit={handleSubmit} className="input-area">
            <div className="input-wrapper">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Ask me to create documents, send emails, or help with tasks..."
                disabled={isStreaming || !threadId} // Disable if no thread or streaming
                className="message-textarea"
                rows={1}
              />
              <button
                type="submit"
                disabled={isStreaming || !input.trim() || !threadId} // Disable if no input, streaming, or no thread
                className="send-button"
              >
                <Send size={20} />
              </button>
            </div>
            <div className="input-footer">
              <span className="input-hint">
                {isStreaming
                  ? "AI is thinking..."
                  : "Press Enter to send, Shift+Enter for new line"}
              </span>
            </div>
          </form>
        </main>
      </div>
    </div>
  );
}

export default AIChat;