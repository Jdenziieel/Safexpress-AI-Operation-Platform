"""
Unit tests for FastAPI endpoints
"""

import pytest
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from api import app


@pytest.fixture
def client():
    """FastAPI test client"""
    return TestClient(app)


@pytest.fixture
def mock_credentials():
    """Mock OAuth credentials"""
    return {
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token"
    }


@pytest.fixture
def valid_request_data(mock_credentials):
    """Valid request data"""
    return {
        "tool": "search_emails",
        "inputs": {
            "query": "from:test@example.com",
            "max_results": 5
        },
        "credentials_dict": mock_credentials
    }


class TestHealthEndpoints:
    """Tests for health and info endpoints"""
    
    def test_root_endpoint(self, client):
        """Test root endpoint returns API info"""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["service"] == "Gmail Agent API"
        assert "endpoints" in data
        assert "example_request" in data
    
    def test_health_check(self, client):
        """Test health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "gmail-agent"
        assert data["version"] == "1.0.0"


class TestExecuteTaskEndpoint:
    """Tests for /execute_task endpoint"""
    
    @patch('api._search_emails_impl')
    def test_execute_search_emails_success(self, mock_search, client, valid_request_data):
        """Test successful search_emails execution"""
        # Mock tool implementation
        mock_search.return_value = {
            "success": True,
            "emails": [
                {
                    "message_id": "msg123",
                    "from": "test@example.com",
                    "subject": "Test Email",
                    "body": "Test body"
                }
            ],
            "count": 1,
            "query": "from:test@example.com",
            "error": None
        }
        
        response = client.post("/execute_task", json=valid_request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1
        assert len(data["emails"]) == 1
        
        # Verify mock was called with correct args
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["query"] == "from:test@example.com"
        assert call_kwargs["max_results"] == 5
    
    @patch('api._send_email_impl')
    @patch('api.ChatOpenAI')
    def test_execute_send_email_with_signature(self, mock_llm_class, mock_send, client, mock_credentials):
        """Test send_email adds signature using LLM"""
        # Mock LLM
        mock_llm_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Test body\n\n---\nThis is written by Assistant Agent"
        mock_llm_instance.invoke.return_value = mock_response
        mock_llm_class.return_value = mock_llm_instance
        
        # Mock send implementation
        mock_send.return_value = {
            "success": True,
            "message_id": "msg123",
            "thread_id": "thread123",
            "to": "recipient@example.com",
            "subject": "Test",
            "body": "Test body\n\n---\nThis is written by Assistant Agent",
            "error": None
        }
        
        request_data = {
            "tool": "send_email",
            "inputs": {
                "to": "recipient@example.com",
                "subject": "Test",
                "body": "Test body"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "Assistant Agent" in data["body"]
        
        # Verify LLM was called
        mock_llm_instance.invoke.assert_called_once()
        
        # Verify send was called with transformed body
        call_kwargs = mock_send.call_args.kwargs
        assert "Assistant Agent" in call_kwargs["body"]
    
    @patch('api._reply_to_email_impl')
    @patch('api.ChatOpenAI')
    def test_execute_reply_with_signature(self, mock_llm_class, mock_reply, client, mock_credentials):
        """Test reply_to_email adds signature using LLM"""
        # Mock LLM
        mock_llm_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Reply text\n\n---\nThis is written by Assistant Agent"
        mock_llm_instance.invoke.return_value = mock_response
        mock_llm_class.return_value = mock_llm_instance
        
        # Mock reply implementation
        mock_reply.return_value = {
            "success": True,
            "original_message_id": "msg123",
            "reply_message_id": "reply123",
            "thread_id": "thread123",
            "to": "sender@example.com",
            "subject": "Re: Test",
            "reply_body": "Reply text\n\n---\nThis is written by Assistant Agent",
            "error": None
        }
        
        request_data = {
            "tool": "reply_to_email",
            "inputs": {
                "message_id": "msg123",
                "reply_body": "Reply text"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "Assistant Agent" in data["reply_body"]
    
    @patch('api._create_draft_email_impl')
    @patch('api.ChatOpenAI')
    def test_execute_create_draft_with_signature(self, mock_llm_class, mock_create, client, mock_credentials):
        """Test create_draft_email adds signature using LLM"""
        # Mock LLM
        mock_llm_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Draft body\n\n---\nThis is written by Assistant Agent"
        mock_llm_instance.invoke.return_value = mock_response
        mock_llm_class.return_value = mock_llm_instance
        
        # Mock create implementation
        mock_create.return_value = {
            "success": True,
            "draft_id": "draft123",
            "message_id": "msg123",
            "to": "test@example.com",
            "subject": "Draft",
            "body": "Draft body\n\n---\nThis is written by Assistant Agent",
            "error": None
        }
        
        request_data = {
            "tool": "create_draft_email",
            "inputs": {
                "to": "test@example.com",
                "subject": "Draft",
                "body": "Draft body"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
    
    def test_execute_unknown_tool(self, client, mock_credentials):
        """Test execution with unknown tool"""
        request_data = {
            "tool": "nonexistent_tool",
            "inputs": {},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is False
        assert "Unknown tool" in data["error"]
    
    @patch('api._search_emails_impl')
    def test_execute_with_tool_error(self, mock_search, client, valid_request_data):
        """Test execution when tool returns error"""
        # Mock tool to return error
        mock_search.return_value = {
            "success": False,
            "emails": [],
            "count": 0,
            "query": "from:test@example.com",
            "error": "Gmail API error: 404 Not Found"
        }
        
        response = client.post("/execute_task", json=valid_request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is False
        assert "Gmail API error" in data["error"]
    
    @patch('api._search_emails_impl')
    def test_execute_with_exception(self, mock_search, client, valid_request_data):
        """Test execution when tool raises exception"""
        # Mock tool to raise exception
        mock_search.side_effect = Exception("Unexpected error occurred")
        
        response = client.post("/execute_task", json=valid_request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is False
        assert "Unexpected error" in data["error"]
    
    def test_execute_invalid_request_format(self, client):
        """Test with invalid request format"""
        invalid_data = {
            "tool": "search_emails"
            # Missing required fields
        }
        
        response = client.post("/execute_task", json=invalid_data)
        assert response.status_code == 422  # Validation error
    
    @patch('api._forward_email_impl')
    @patch('api.ChatOpenAI')
    def test_execute_forward_with_signature(self, mock_llm_class, mock_forward, client, mock_credentials):
        """Test forward_email adds signature using LLM"""
        # Mock LLM
        mock_llm_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Forward message\n\n---\nThis is written by Assistant Agent"
        mock_llm_instance.invoke.return_value = mock_response
        mock_llm_class.return_value = mock_llm_instance
        
        # Mock forward implementation
        mock_forward.return_value = {
            "success": True,
            "original_message_id": "msg123",
            "forwarded_message_id": "fwd123",
            "thread_id": "thread123",
            "to": "recipient@example.com",
            "subject": "Fwd: Test",
            "original_from": "sender@example.com",
            "forward_message": "Forward message\n\n---\nThis is written by Assistant Agent",
            "error": None
        }
        
        request_data = {
            "tool": "forward_email",
            "inputs": {
                "message_id": "msg123",
                "to": "recipient@example.com",
                "forward_message": "Forward message"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
    
    @patch('api._send_draft_email_impl')
    def test_execute_send_draft_without_body(self, mock_send_draft, client, mock_credentials):
        """Test send_draft_email (no body field to transform)"""
        mock_send_draft.return_value = {
            "success": True,
            "draft_id": "draft123",
            "message_id": "msg123",
            "thread_id": "thread123",
            "to": "test@example.com",
            "subject": "Test",
            "error": None
        }
        
        request_data = {
            "tool": "send_draft_email",
            "inputs": {
                "draft_id": "draft123"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["draft_id"] == "draft123"
    
    @patch('api._get_thread_conversation_impl')
    def test_execute_non_email_tool(self, mock_thread, client, mock_credentials):
        """Test tool that doesn't need signature (get_thread_conversation)"""
        mock_thread.return_value = {
            "success": True,
            "thread_id": "thread123",
            "message_count": 2,
            "messages": [
                {"message_id": "msg1", "body": "Message 1"},
                {"message_id": "msg2", "body": "Message 2"}
            ],
            "error": None
        }
        
        request_data = {
            "tool": "get_thread_conversation",
            "inputs": {
                "thread_id": "thread123"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["message_count"] == 2


class TestRequestValidation:
    """Tests for request validation"""
    
    def test_missing_tool(self, client, mock_credentials):
        """Test request with missing tool field"""
        request_data = {
            "inputs": {},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 422
    
    def test_missing_inputs(self, client, mock_credentials):
        """Test request with missing inputs field"""
        request_data = {
            "tool": "search_emails",
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 422
    
    def test_missing_credentials(self, client):
        """Test request with missing credentials"""
        request_data = {
            "tool": "search_emails",
            "inputs": {"query": "test"}
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 422
    
    def test_invalid_json(self, client):
        """Test request with invalid JSON"""
        response = client.post(
            "/execute_task",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422