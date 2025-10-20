import React, { useState, useRef, useEffect } from 'react';

const API_URL = 'http://localhost:5000/agent';
const CHECK_AUTH_URL = 'http://localhost:5000/check_auth';

const GoogleIcon = () => (
  <svg width="20" height="20" viewBox="0 0 48 48" style={{ marginRight: 12 }}>
    <path fill="#4285F4" d="M24 9.5c3.54 0 6.73 1.22 9.24 3.22l6.93-6.93C36.36 2.34 30.55 0 24 0 14.61 0 6.13 5.64 1.64 14.02l8.06 6.27C11.6 13.36 17.29 9.5 24 9.5z"/>
    <path fill="#34A853" d="M46.09 24.5c0-1.64-.15-3.22-.43-4.75H24v9.02h12.44c-.54 2.91-2.18 5.38-4.64 7.04l7.19 5.59C43.87 37.87 46.09 31.68 46.09 24.5z"/>
    <path fill="#FBBC05" d="M9.7 28.29c-1.13-3.36-1.13-6.94 0-10.3l-8.06-6.27C.59 15.36 0 19.59 0 24c0 4.41.59 8.64 1.64 12.28l8.06-6.27z"/>
    <path fill="#EA4335" d="M24 48c6.55 0 12.36-2.17 16.93-5.93l-7.19-5.59c-2.01 1.35-4.59 2.13-7.74 2.13-6.71 0-12.4-3.86-14.3-9.29l-8.06 6.27C6.13 42.36 14.61 48 24 48z"/>
  </svg>
);

const AttachmentIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
  </svg>
);

const SendIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="22" y1="2" x2="11" y2="13"/>
    <polygon points="22 2 15 22 11 13 2 9 22 2"/>
  </svg>
);

export default function GoogleDriveAgent() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [messages, setMessages] = useState([
    { sender: 'agent', text: '👋 Hi! I manage your SafeExpress folders. Try "list folders" or create nested folders!' }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const fileInputRef = useRef();
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);
  
  useEffect(() => {
    fetch(CHECK_AUTH_URL, { credentials: 'include' })
      .then(res => res.json())
      .then(data => setIsAuthenticated(data.authenticated))
      .catch(() => setIsAuthenticated(false));
  }, []);

  const loginWithGoogle = async () => {
    try {
      const res = await fetch('http://localhost:5000/authorize', { credentials: 'include' });
      const data = await res.json();
      window.location.href = data.auth_url;
    } catch (err) {
      console.error('Login error:', err);
      alert('Failed to start Google OAuth login.');
    }
  };

  const handleLogout = async () => {
    await fetch('http://localhost:5000/logout', { 
      method: 'POST',
      credentials: 'include' 
    });
    setIsAuthenticated(false);
    setMessages([{ sender: 'agent', text: '👋 Logged out successfully.' }]);
  };

  const handleFileChange = (e) => {
    setSelectedFile(e.target.files[0] || null);
  };

  const sendMessage = async () => {
    if (!input.trim() && !selectedFile) return;
    setLoading(true);

    const userMessage = selectedFile 
      ? `${input || 'Upload file'}: ${selectedFile.name}` 
      : input;
    
    setMessages(prev => [...prev, { sender: 'user', text: userMessage }]);
    
    const currentInput = input;
    setInput('');

    try {
      if (selectedFile) {
        const formData = new FormData();
        formData.append('file', selectedFile);
        formData.append('message', currentInput || 'upload file');

        const res = await fetch(API_URL, {
          method: 'POST',
          credentials: 'include',
          body: formData
        });
        
        const data = await res.json();
        setMessages(prev => [...prev, { 
          sender: 'agent', 
          text: data.reply || 'File uploaded!' 
        }]);
        
        setSelectedFile(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
      } else {
        const res = await fetch(API_URL, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: currentInput })
        });
        
        const data = await res.json();
        setMessages(prev => [...prev, { 
          sender: 'agent', 
          text: data.reply || 'Done!' 
        }]);
      }
    } catch (error) {
      console.error('Agent error:', error);
      setMessages(prev => [...prev, { sender: 'agent', text: 'Error connecting to agent.' }]);
    }
    
    setLoading(false);
  };

  const quickAction = (action) => {
    setInput(action);
  };

  if (!isAuthenticated) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      }}>
        <div style={{
          background: 'white',
          padding: '3rem',
          borderRadius: '16px',
          boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
          textAlign: 'center',
          maxWidth: '400px'
        }}>
          <div style={{ fontSize: '48px', marginBottom: '1rem' }}>📁</div>
          <h2 style={{ margin: '0 0 0.5rem 0', fontSize: '24px', color: '#1a1a1a' }}>
            SafeExpress Manager
          </h2>
          <p style={{ color: '#666', marginBottom: '2rem' }}>
            Organize your files with intelligent folder management
          </p>
          <button onClick={loginWithGoogle} style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '100%',
            padding: '12px 24px',
            background: 'white',
            border: '2px solid #e0e0e0',
            borderRadius: '8px',
            fontSize: '16px',
            fontWeight: '500',
            cursor: 'pointer',
            transition: 'all 0.2s'
          }}>
            <GoogleIcon />
            <span>Continue with Google</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      background: '#f5f7fa',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    }}>
      {/* Header */}
      <div style={{
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        color: 'white',
        padding: '1rem 2rem',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        boxShadow: '0 2px 10px rgba(0,0,0,0.1)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '24px' }}>📁</span>
          <h2 style={{ margin: 0, fontSize: '20px', fontWeight: '600' }}>SafeExpress Manager</h2>
        </div>
        <button onClick={handleLogout} style={{
          background: 'rgba(255,255,255,0.2)',
          border: 'none',
          padding: '8px 16px',
          borderRadius: '6px',
          color: 'white',
          cursor: 'pointer',
          fontWeight: '500',
          transition: 'background 0.2s'
        }} onMouseOver={e => e.target.style.background = 'rgba(255,255,255,0.3)'}
           onMouseOut={e => e.target.style.background = 'rgba(255,255,255,0.2)'}>
          Logout
        </button>
      </div>

      {/* Quick Actions */}
      <div style={{
        background: 'white',
        padding: '1rem 2rem',
        borderBottom: '1px solid #e0e0e0',
        display: 'flex',
        gap: '8px',
        flexWrap: 'wrap'
      }}>
        {['list folders', 'list files', 'create folder Operations/2024'].map(action => (
          <button
            key={action}
            onClick={() => quickAction(action)}
            style={{
              padding: '6px 12px',
              background: '#f0f0f0',
              border: 'none',
              borderRadius: '6px',
              fontSize: '13px',
              cursor: 'pointer',
              transition: 'background 0.2s'
            }}
            onMouseOver={e => e.target.style.background = '#e0e0e0'}
            onMouseOut={e => e.target.style.background = '#f0f0f0'}
          >
            {action}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '2rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '1rem'
      }}>
        {messages.map((msg, i) => (
          <div key={i} style={{
            display: 'flex',
            justifyContent: msg.sender === 'user' ? 'flex-end' : 'flex-start'
          }}>
            <div style={{
              maxWidth: '70%',
              padding: '12px 16px',
              borderRadius: '12px',
              background: msg.sender === 'user' ? '#667eea' : 'white',
              color: msg.sender === 'user' ? 'white' : '#1a1a1a',
              boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
              whiteSpace: 'pre-wrap',
              fontSize: '14px',
              lineHeight: '1.5'
            }}>
              {msg.text}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div style={{
        background: 'white',
        padding: '1rem 2rem',
        borderTop: '1px solid #e0e0e0'
      }}>
        {selectedFile && (
          <div style={{
            marginBottom: '8px',
            padding: '8px 12px',
            background: '#f0f0f0',
            borderRadius: '6px',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <span>📎</span>
            <strong>{selectedFile.name}</strong>
            <button
              onClick={() => {
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
              }}
              style={{
                marginLeft: 'auto',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontSize: '16px'
              }}
            >
              ✕
            </button>
          </div>
        )}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendMessage()}
            placeholder="Type your request..."
            disabled={loading}
            style={{
              flex: 1,
              padding: '12px 16px',
              border: '2px solid #e0e0e0',
              borderRadius: '8px',
              fontSize: '14px',
              outline: 'none',
              transition: 'border 0.2s'
            }}
            onFocus={e => e.target.style.borderColor = '#667eea'}
            onBlur={e => e.target.style.borderColor = '#e0e0e0'}
          />
          <label htmlFor="file-upload" style={{
            padding: '12px',
            background: '#f0f0f0',
            borderRadius: '8px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'background 0.2s'
          }} onMouseOver={e => e.target.style.background = '#e0e0e0'}
             onMouseOut={e => e.target.style.background = '#f0f0f0'}>
            <AttachmentIcon />
          </label>
          <input
            id="file-upload"
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            style={{ display: 'none' }}
            disabled={loading}
          />
          <button
            onClick={sendMessage}
            disabled={loading || (!input.trim() && !selectedFile)}
            style={{
              padding: '12px 24px',
              background: loading || (!input.trim() && !selectedFile) ? '#ccc' : '#667eea',
              border: 'none',
              borderRadius: '8px',
              color: 'white',
              cursor: loading || (!input.trim() && !selectedFile) ? 'not-allowed' : 'pointer',
              fontWeight: '500',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'background 0.2s'
            }}
            onMouseOver={e => {
              if (!loading && (input.trim() || selectedFile)) {
                e.target.style.background = '#5568d3';
              }
            }}
            onMouseOut={e => {
              if (!loading && (input.trim() || selectedFile)) {
                e.target.style.background = '#667eea';
              }
            }}
          >
            {loading ? (
              <div style={{
                width: '16px',
                height: '16px',
                border: '2px solid rgba(255,255,255,0.3)',
                borderTop: '2px solid white',
                borderRadius: '50%',
                animation: 'spin 1s linear infinite'
              }} />
            ) : (
              <>
                <SendIcon />
                <span>Send</span>
              </>
            )}
          </button>
        </div>
      </div>
      <style>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}