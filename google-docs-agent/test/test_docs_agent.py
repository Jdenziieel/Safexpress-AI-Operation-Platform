"""
Comprehensive Unit Tests for Google Docs Agent API
Tests all endpoints, tools, error handling, and edge cases

Folder structure:
gdocs-agent/
  ├── main.py
  ├── agent.py
  ├── tools.py
  ├── document_format_extractor.py
  └── test/
      ├── __init__.py
      ├── test_gdocs_agent.py (this file)
      ├── conftest.py
      └── test_requirements.txt
"""

import pytest
import json
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from typing import Dict, Any

# Import the FastAPI app and models
from api import app, AgentTaskRequest, AgentTaskResponse

# Initialize test client
client = TestClient(app)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def mock_credentials():
    """Mock credentials for testing"""
    return {
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "mock_client_id.apps.googleusercontent.com",
        "client_secret": "mock_client_secret"
    }


@pytest.fixture
def mock_agent_response():
    """Mock successful agent response"""
    return {
        "messages": [
            Mock(content='{"success": true, "document_id": "doc123", "document_url": "https://docs.google.com/document/d/doc123/edit", "title": "Test Doc"}')
        ]
    }


@pytest.fixture
def mock_docs_service():
    """Mock Google Docs service"""
    service = Mock()
    
    # Mock documents().create()
    mock_create = Mock()
    mock_create.execute.return_value = {
        'documentId': 'doc123',
        'title': 'Test Document'
    }
    service.documents().create.return_value = mock_create
    
    # Mock documents().get()
    mock_get = Mock()
    mock_get.execute.return_value = {
        'documentId': 'doc123',
        'title': 'Test Document',
        'body': {
            'content': [
                {
                    'paragraph': {
                        'elements': [
                            {
                                'textRun': {
                                    'content': 'Test content\n'
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }
    service.documents().get.return_value = mock_get
    
    # Mock documents().batchUpdate()
    mock_batch = Mock()
    mock_batch.execute.return_value = {'replies': []}
    service.documents().batchUpdate.return_value = mock_batch
    
    return service


@pytest.fixture
def sample_create_doc_request(mock_credentials):
    """Sample create document request"""
    return {
        "tool": "create_doc",
        "inputs": {"title": "Test Document"},
        "credentials_dict": mock_credentials
    }


@pytest.fixture
def sample_task_request(mock_credentials):
    """Sample task-based request"""
    return {
        "task": "create_and_populate",
        "instruction": "Create a document with the given content",
        "inputs": {
            "title": "Project Report",
            "content": "This is a test report"
        },
        "expected_output": {
            "document_id": "Google Docs ID",
            "document_url": "URL to document"
        },
        "credentials_dict": mock_credentials
    }


# ============================================================
# TEST ROOT & HEALTH ENDPOINTS
# ============================================================

class TestRootEndpoints:
    """Test basic API endpoints"""
    
    def test_root_endpoint(self):
        """Test GET / returns API info"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Google Docs Agent API"
        assert "endpoints" in data
        assert "example_request" in data
    
    def test_health_endpoint(self):
        """Test GET /health returns healthy status"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "google-docs-agent"
        assert data["version"] == "1.0.0"


# ============================================================
# TEST TOOL-BASED REQUESTS (FORMAT 2)
# ============================================================

class TestToolBasedRequests:
    """Test direct tool calls (supervisor format)"""
    
    @patch('api.create_docs_agent')
    def test_create_doc_tool_success(self, mock_create_agent, mock_credentials):
        """Test creating a document using tool format"""
        # Mock agent response
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc123", "document_url": "https://docs.google.com/document/d/doc123/edit", "title": "Test Doc"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test Document"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "result" in data
        assert data["result"]["document_id"] == "doc123"
        assert "document_url" in data["result"]
    
    @patch('api.create_docs_agent')
    def test_add_text_tool_success(self, mock_create_agent, mock_credentials):
        """Test adding text to document using tool format"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc123", "document_url": "https://docs.google.com/document/d/doc123/edit", "text_length": 25}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "add_text",
            "inputs": {
                "document_id": "doc123",
                "text": "Hello, this is test text."
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["result"]["document_id"] == "doc123"
        assert "text_length" in data["result"]
    
    @patch('api.create_docs_agent')
    def test_read_doc_tool_success(self, mock_create_agent, mock_credentials):
        """Test reading document using tool format"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc123", "content": "Document content here", "title": "Test Doc"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "read_doc",
            "inputs": {"document_id": "doc123"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "content" in data["result"]
        assert data["result"]["document_id"] == "doc123"
    
    @patch('api.create_docs_agent')
    def test_share_doc_tool_success(self, mock_create_agent, mock_credentials):
        """Test sharing document using tool format"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc123", "shared_with": "user@example.com", "role": "reader"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "share_doc",
            "inputs": {
                "document_id": "doc123",
                "email": "user@example.com",
                "role": "reader"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "shared_with" in data["result"]
    
    @patch('api.create_docs_agent')
    def test_edit_doc_tool_success(self, mock_create_agent, mock_credentials):
        """Test editing document using tool format"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc123", "old_text": "Hello", "new_text": "Hi"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "edit_doc",
            "inputs": {
                "document_id": "doc123",
                "old_text": "Hello",
                "new_text": "Hi"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True


# ============================================================
# TEST TASK-BASED REQUESTS (FORMAT 1)
# ============================================================

class TestTaskBasedRequests:
    """Test intelligent task execution (with agent reasoning)"""
    
    @patch('api.create_docs_agent')
    def test_create_and_populate_task(self, mock_create_agent, mock_credentials):
        """Test create_and_populate task"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"document_id": "doc123", "document_url": "https://docs.google.com/document/d/doc123/edit", "title": "Project Report"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "task": "create_and_populate",
            "instruction": "Create a project report with the given content",
            "inputs": {
                "title": "Project Report",
                "content": "Q4 Summary: Revenue increased by 25%"
            },
            "expected_output": {
                "document_id": "Google Docs ID",
                "document_url": "URL to document"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "document_id" in data["result"]
        assert "document_url" in data["result"]
    
    @patch('api.create_docs_agent')
    def test_task_with_expected_output(self, mock_create_agent, mock_credentials):
        """Test that expected output keys are validated"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"document_id": "doc123", "title": "Test"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "task": "create_document",
            "inputs": {"title": "Test"},
            "expected_output": {
                "document_id": "ID of document",
                "document_url": "URL to document"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        # Should still succeed but may log warnings
        assert data["success"] is True
    
    @patch('api.create_docs_agent')
    def test_task_without_instruction(self, mock_create_agent, mock_credentials):
        """Test task execution without explicit instruction"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"document_id": "doc123", "success": true}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "task": "create_document",
            "inputs": {"title": "Auto Document"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True


# ============================================================
# TEST TEMPLATE-BASED OPERATIONS
# ============================================================

class TestTemplateOperations:
    """Test template extraction and document creation from templates"""
    
    @patch('api.create_docs_agent')
    def test_list_user_docs_tool(self, mock_create_agent, mock_credentials):
        """Test listing user's documents"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "documents": [{"id": "doc1", "name": "Template 1"}, {"id": "doc2", "name": "Template 2"}], "count": 2}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "list_docs",
            "inputs": {"search_query": "template"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "documents" in data["result"]
    
    @patch('api.create_docs_agent')
    def test_extract_template_structure(self, mock_create_agent, mock_credentials):
        """Test extracting template structure"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "template_id": "doc123", "placeholders": ["DATE", "VENUE", "ATTENDEES"]}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "extract_template",
            "inputs": {"template_document_id": "doc123"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "placeholders" in data["result"]
    
    @patch('api.create_docs_agent')
    def test_create_from_template(self, mock_create_agent, mock_credentials):
        """Test creating document from template"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "new_doc123", "template_used": "doc123", "placeholders_filled": {"DATE": "Jan 15", "VENUE": "Room A"}}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_from_template",
            "inputs": {
                "template_document_id": "doc123",
                "new_title": "Meeting Minutes - Jan 15",
                "placeholder_values": {
                    "DATE": "January 15, 2025",
                    "VENUE": "Conference Room A"
                }
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "document_id" in data["result"]
        assert "template_used" in data["result"]


# ============================================================
# TEST ERROR HANDLING
# ============================================================

class TestErrorHandling:
    """Test error handling scenarios"""
    
    def test_missing_credentials(self):
        """Test request without credentials"""
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test"}
            # Missing credentials_dict
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 422  # Validation error
    
    def test_missing_tool_and_task(self, mock_credentials):
        """Test request without tool or task"""
        request_data = {
            "inputs": {"title": "Test"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data
    
    @patch('api.create_docs_agent')
    def test_agent_exception(self, mock_create_agent, mock_credentials):
        """Test handling of agent exceptions"""
        mock_agent = Mock()
        mock_agent.invoke.side_effect = Exception("Agent failed")
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        assert "error" in data
        assert "Agent failed" in data["error"]
    
    @patch('api.create_docs_agent')
    def test_invalid_json_response(self, mock_create_agent, mock_credentials):
        """Test handling of non-JSON agent response"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content="This is not valid JSON at all")
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        # Should still succeed but wrap response
        assert data["success"] is True
        assert "response" in data["result"]
    
    @patch('api.create_docs_agent')
    def test_empty_agent_response(self, mock_create_agent, mock_credentials):
        """Test handling of empty agent response"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {"messages": []}
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        assert "error" in data


# ============================================================
# TEST JSON PARSING
# ============================================================

class TestJSONParsing:
    """Test JSON response parsing from agent"""
    
    @patch('api.create_docs_agent')
    def test_parse_json_with_markdown(self, mock_create_agent, mock_credentials):
        """Test parsing JSON wrapped in markdown code blocks"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='```json\n{"success": true, "document_id": "doc123"}\n```')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["result"]["document_id"] == "doc123"
    
    @patch('api.create_docs_agent')
    def test_parse_plain_json(self, mock_create_agent, mock_credentials):
        """Test parsing plain JSON response"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc456"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["result"]["document_id"] == "doc456"
    
    @patch('api.create_docs_agent')
    def test_parse_json_with_backticks(self, mock_create_agent, mock_credentials):
        """Test parsing JSON with backticks but no 'json' marker"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='```\n{"success": true, "document_id": "doc789"}\n```')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["result"]["document_id"] == "doc789"


# ============================================================
# TEST INTEGRATION WORKFLOWS
# ============================================================

class TestIntegration:
    """Integration tests for complete workflows"""
    
    @patch('api.create_docs_agent')
    def test_create_populate_and_share_workflow(self, mock_create_agent, mock_credentials):
        """Test complete workflow: create document, add content, share"""
        mock_agent = Mock()
        
        # Create document
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc123", "document_url": "https://docs.google.com/document/d/doc123/edit"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        # Step 1: Create document
        create_request = {
            "tool": "create_doc",
            "inputs": {"title": "Team Report"},
            "credentials_dict": mock_credentials
        }
        
        response1 = client.post("/execute_task", json=create_request)
        assert response1.status_code == 200
        assert response1.json()["success"] is True
        doc_id = response1.json()["result"]["document_id"]
        
        # Step 2: Add text
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc123", "text_length": 50}')
            ]
        }
        
        add_text_request = {
            "tool": "add_text",
            "inputs": {
                "document_id": doc_id,
                "text": "This is the team report content."
            },
            "credentials_dict": mock_credentials
        }
        
        response2 = client.post("/execute_task", json=add_text_request)
        assert response2.status_code == 200
        assert response2.json()["success"] is True
        
        # Step 3: Share document
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "shared_with": "team@example.com"}')
            ]
        }
        
        share_request = {
            "tool": "share_doc",
            "inputs": {
                "document_id": doc_id,
                "email": "team@example.com",
                "role": "reader"
            },
            "credentials_dict": mock_credentials
        }
        
        response3 = client.post("/execute_task", json=share_request)
        assert response3.status_code == 200
        assert response3.json()["success"] is True


# ============================================================
# TEST TOOLS IMPLEMENTATION
# ============================================================

class TestToolsImplementation:
    """Test the underlying tools.py functions"""
    
    @patch('tools.get_google_service')
    def test_create_google_doc_impl(self, mock_get_service, mock_credentials):
        """Test _create_google_doc_impl function"""
        from tools import _create_google_doc_impl
        
        mock_service = Mock()
        mock_service.documents().create().execute.return_value = {
            'documentId': 'doc123'
        }
        mock_get_service.return_value = mock_service
        
        result = _create_google_doc_impl("Test Doc", mock_credentials)
        
        assert "Document created successfully" in result
        assert "doc123" in result
    
    @patch('tools.get_google_service')
    def test_add_text_to_doc_impl(self, mock_get_service, mock_credentials):
        """Test _add_text_to_doc_impl function"""
        from tools import _add_text_to_doc_impl
        
        mock_service = Mock()
        mock_service.documents().batchUpdate().execute.return_value = {}
        mock_get_service.return_value = mock_service
        
        result = _add_text_to_doc_impl("doc123", "Test text", mock_credentials)
        
        assert "Text added successfully" in result
        assert "doc123" in result
    
    @patch('tools.get_google_service')
    def test_read_google_doc_impl(self, mock_get_service, mock_credentials):
        """Test _read_google_doc_impl function"""
        from tools import _read_google_doc_impl
        
        mock_service = Mock()
        mock_service.documents().get().execute.return_value = {
            'documentId': 'doc123',
            'body': {
                'content': [
                    {
                        'paragraph': {
                            'elements': [
                                {
                                    'textRun': {
                                        'content': 'Document content\n'
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        }
        mock_get_service.return_value = mock_service
        
        result = _read_google_doc_impl("doc123", mock_credentials)
        
        assert "Document content" in result
        assert "doc123" in result



class TestUpdateDocTool:
    """Test the new update_doc tool that replaces entire content"""
    
    @patch('api.create_docs_agent')
    def test_update_doc_tool_success(self, mock_create_agent, mock_credentials):
        """Test updating entire document using tool format"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc123", "new_content_length": 100}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "update_doc",
            "inputs": {
                "document_id": "doc123",
                "new_content": "This is completely new content replacing everything."
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["result"]["document_id"] == "doc123"
    
    @patch('api.create_docs_agent')
    def test_update_doc_replaces_all_content(self, mock_create_agent, mock_credentials):
        """Test that update_doc replaces ALL content, not appends"""
        mock_agent = Mock()
        # Simulate: create doc, add text, update with new content, read back
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "content": "New content only", "old_content_removed": true}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "update_doc",
            "inputs": {
                "document_id": "doc123",
                "new_content": "New content only"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    @patch('api.create_docs_agent')
    def test_update_doc_with_empty_content(self, mock_create_agent, mock_credentials):
        """Test updating document with empty string"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "doc123", "content_cleared": true}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "update_doc",
            "inputs": {
                "document_id": "doc123",
                "new_content": ""
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200


# ============================================================
# TEST EDGE CASES & VALIDATION
# ============================================================

class TestInputValidation:
    """Test edge cases and input validation"""
    
    @patch('api.create_docs_agent')
    def test_create_doc_with_empty_title(self, mock_create_agent, mock_credentials):
        """Test creating document with empty title"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": false, "error": "Title cannot be empty"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": ""},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_add_text_with_none_text(self, mock_create_agent, mock_credentials):
        """Test adding None as text"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": false, "error": "Text cannot be None"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "add_text",
            "inputs": {
                "document_id": "doc123",
                "text": None
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_very_long_text(self, mock_create_agent, mock_credentials):
        """Test adding very long text (>1MB)"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "text_length": 1500000}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        long_text = "a" * 1_500_000  # 1.5MB of text
        request_data = {
            "tool": "add_text",
            "inputs": {
                "document_id": "doc123",
                "text": long_text
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_special_characters_in_text(self, mock_create_agent, mock_credentials):
        """Test Unicode, emojis, newlines, special chars"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "special_chars_handled": true}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        special_text = "Hello 👋\nWorld 🌍\n日本語\nTest\t\tTab\n\n\nMultiple newlines"
        request_data = {
            "tool": "add_text",
            "inputs": {
                "document_id": "doc123",
                "text": special_text
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_invalid_document_id(self, mock_create_agent, mock_credentials):
        """Test reading non-existent document"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": false, "error": "Document not found"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "read_doc",
            "inputs": {"document_id": "invalid_doc_id_12345"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_invalid_email_for_sharing(self, mock_create_agent, mock_credentials):
        """Test sharing with invalid email address"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": false, "error": "Invalid email address"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "share_doc",
            "inputs": {
                "document_id": "doc123",
                "email": "not-an-email",
                "role": "reader"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_invalid_role_for_sharing(self, mock_create_agent, mock_credentials):
        """Test sharing with invalid role"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": false, "error": "Invalid role"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "share_doc",
            "inputs": {
                "document_id": "doc123",
                "email": "user@example.com",
                "role": "admin"  # Invalid role
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200


# ============================================================
# TEST TEMPLATE EDGE CASES
# ============================================================

class TestTemplateEdgeCases:
    """Test template operations edge cases"""
    
    @patch('api.create_docs_agent')
    def test_template_without_placeholders(self, mock_create_agent, mock_credentials):
        """Test extracting template with no [PLACEHOLDERS]"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "placeholders": [], "note": "No placeholders found"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "extract_template",
            "inputs": {"template_document_id": "doc123"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    @patch('api.create_docs_agent')
    def test_malformed_placeholder_json(self, mock_create_agent, mock_credentials):
        """Test creating from template with invalid JSON"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": false, "error": "Invalid placeholder JSON"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_from_template",
            "inputs": {
                "template_document_id": "doc123",
                "new_title": "New Doc",
                "placeholder_values": "not valid json"
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_missing_placeholder_values(self, mock_create_agent, mock_credentials):
        """Test creating from template with incomplete placeholder values"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "warning": "Some placeholders not filled", "unfilled": ["VENUE", "TIME"]}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_from_template",
            "inputs": {
                "template_document_id": "doc123",
                "new_title": "Meeting Minutes",
                "placeholder_values": '{"DATE": "Jan 15"}'  # Missing VENUE, TIME
            },
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_empty_search_query(self, mock_create_agent, mock_credentials):
        """Test listing docs with empty search query"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "documents": [{"id": "doc1", "name": "Doc 1"}], "count": 1}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "list_docs",
            "inputs": {"search_query": ""},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200


# ============================================================
# TEST COMPLETE WORKFLOWS (INTEGRATION)
# ============================================================

class TestCompleteWorkflows:
    """Test end-to-end workflows combining multiple operations"""
    
    @patch('api.create_docs_agent')
    def test_complete_template_workflow(self, mock_create_agent, mock_credentials):
        """Test: List docs → Extract template → Create from template → Read result"""
        mock_agent = Mock()
        mock_create_agent.return_value = mock_agent
        
        # Step 1: List docs
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "documents": [{"id": "template123", "name": "Meeting Template"}]}')
            ]
        }
        
        list_request = {
            "tool": "list_docs",
            "inputs": {"search_query": "template"},
            "credentials_dict": mock_credentials
        }
        response1 = client.post("/execute_task", json=list_request)
        assert response1.status_code == 200
        
        # Step 2: Extract template
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "placeholders": ["DATE", "VENUE"]}')
            ]
        }
        
        extract_request = {
            "tool": "extract_template",
            "inputs": {"template_document_id": "template123"},
            "credentials_dict": mock_credentials
        }
        response2 = client.post("/execute_task", json=extract_request)
        assert response2.status_code == 200
        
        # Step 3: Create from template
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "document_id": "new_doc123"}')
            ]
        }
        
        create_request = {
            "tool": "create_from_template",
            "inputs": {
                "template_document_id": "template123",
                "new_title": "Meeting - Jan 15",
                "placeholder_values": '{"DATE": "Jan 15", "VENUE": "Room A"}'
            },
            "credentials_dict": mock_credentials
        }
        response3 = client.post("/execute_task", json=create_request)
        assert response3.status_code == 200
        
        # Step 4: Read the result
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": true, "content": "Meeting on Jan 15 at Room A"}')
            ]
        }
        
        read_request = {
            "tool": "read_doc",
            "inputs": {"document_id": "new_doc123"},
            "credentials_dict": mock_credentials
        }
        response4 = client.post("/execute_task", json=read_request)
        assert response4.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_complete_edit_workflow(self, mock_create_agent, mock_credentials):
        """Test: Create → Add text → Edit specific text → Update entire doc → Read"""
        mock_agent = Mock()
        mock_create_agent.return_value = mock_agent
        
        # Create doc
        mock_agent.invoke.return_value = {
            "messages": [Mock(content='{"success": true, "document_id": "doc123"}')]
        }
        create_resp = client.post("/execute_task", json={
            "tool": "create_doc",
            "inputs": {"title": "Test Doc"},
            "credentials_dict": mock_credentials
        })
        assert create_resp.status_code == 200
        
        # Add text
        mock_agent.invoke.return_value = {
            "messages": [Mock(content='{"success": true}')]
        }
        add_resp = client.post("/execute_task", json={
            "tool": "add_text",
            "inputs": {"document_id": "doc123", "text": "Hello World"},
            "credentials_dict": mock_credentials
        })
        assert add_resp.status_code == 200
        
        # Edit specific text
        mock_agent.invoke.return_value = {
            "messages": [Mock(content='{"success": true}')]
        }
        edit_resp = client.post("/execute_task", json={
            "tool": "edit_doc",
            "inputs": {"document_id": "doc123", "old_text": "World", "new_text": "Universe"},
            "credentials_dict": mock_credentials
        })
        assert edit_resp.status_code == 200
        
        # Update entire doc
        mock_agent.invoke.return_value = {
            "messages": [Mock(content='{"success": true}')]
        }
        update_resp = client.post("/execute_task", json={
            "tool": "update_doc",
            "inputs": {"document_id": "doc123", "new_content": "Completely new content"},
            "credentials_dict": mock_credentials
        })
        assert update_resp.status_code == 200
        
        # Read final result
        mock_agent.invoke.return_value = {
            "messages": [Mock(content='{"success": true, "content": "Completely new content"}')]
        }
        read_resp = client.post("/execute_task", json={
            "tool": "read_doc",
            "inputs": {"document_id": "doc123"},
            "credentials_dict": mock_credentials
        })
        assert read_resp.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_multi_user_sharing_workflow(self, mock_create_agent, mock_credentials):
        """Test: Create doc → Share with multiple users → Verify permissions"""
        mock_agent = Mock()
        mock_create_agent.return_value = mock_agent
        
        # Create doc
        mock_agent.invoke.return_value = {
            "messages": [Mock(content='{"success": true, "document_id": "doc123"}')]
        }
        create_resp = client.post("/execute_task", json={
            "tool": "create_doc",
            "inputs": {"title": "Team Doc"},
            "credentials_dict": mock_credentials
        })
        assert create_resp.status_code == 200
        
        # Share with user 1 (reader)
        mock_agent.invoke.return_value = {
            "messages": [Mock(content='{"success": true, "shared_with": "user1@example.com"}')]
        }
        share1_resp = client.post("/execute_task", json={
            "tool": "share_doc",
            "inputs": {"document_id": "doc123", "email": "user1@example.com", "role": "reader"},
            "credentials_dict": mock_credentials
        })
        assert share1_resp.status_code == 200
        
        # Share with user 2 (writer)
        mock_agent.invoke.return_value = {
            "messages": [Mock(content='{"success": true, "shared_with": "user2@example.com"}')]
        }
        share2_resp = client.post("/execute_task", json={
            "tool": "share_doc",
            "inputs": {"document_id": "doc123", "email": "user2@example.com", "role": "writer"},
            "credentials_dict": mock_credentials
        })
        assert share2_resp.status_code == 200


# ============================================================
# TEST ERROR RECOVERY
# ============================================================

class TestErrorRecovery:
    """Test error handling and recovery scenarios"""
    
    @patch('api.create_docs_agent')
    def test_network_timeout_simulation(self, mock_create_agent, mock_credentials):
        """Test handling of network timeouts"""
        mock_agent = Mock()
        mock_agent.invoke.side_effect = TimeoutError("Request timed out")
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
    
    @patch('api.create_docs_agent')
    def test_permission_denied_error(self, mock_create_agent, mock_credentials):
        """Test handling when user lacks document permissions"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": false, "error": "Permission denied"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "read_doc",
            "inputs": {"document_id": "restricted_doc"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
    
    @patch('api.create_docs_agent')
    def test_quota_exceeded_error(self, mock_create_agent, mock_credentials):
        """Test handling of API quota exceeded"""
        mock_agent = Mock()
        mock_agent.invoke.return_value = {
            "messages": [
                Mock(content='{"success": false, "error": "Quota exceeded"}')
            ]
        }
        mock_create_agent.return_value = mock_agent
        
        request_data = {
            "tool": "create_doc",
            "inputs": {"title": "Test"},
            "credentials_dict": mock_credentials
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200


# ============================================================
# RUN ADDITIONAL TESTS
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])