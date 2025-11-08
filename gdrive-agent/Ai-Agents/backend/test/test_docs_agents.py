"""
Comprehensive Unit Tests for Google Drive Agent API
Tests all endpoints, tools, error handling, and edge cases

Folder structure:
gdocs-agent/
  ├── main.py
  ├── tools.py
  ├── credentials.json
  └── test/
      ├── __init__.py
      ├── test_drive_agent.py (this file)
      ├── conftest.py
      └── test_requirements.txt
"""

import pytest
import json
import io
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from typing import Dict, Any

# Import the FastAPI app and tools from parent directory
from api import app, DRIVE_TOOLS, CredentialsDict, TaskRequest
from tools import (
    get_session_drive_service,
    create_nested_folder_impl,
    upload_stream_to_folder_impl,
    list_folders_in_safeexpress_impl,
    list_files_in_folder_impl,
    get_folder_structure_impl,
    search_files_in_safeexpress_impl,
    get_folder_info_impl,
    get_safeexpress_folder_id,
    find_folder,
)

# Initialize test client
client = TestClient(app)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def mock_credentials():
    """Mock credentials for testing"""
    return CredentialsDict(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="mock_client_id.apps.googleusercontent.com",
        client_secret="mock_client_secret"
    )


@pytest.fixture
def mock_drive_service():
    """Mock Google Drive service"""
    service = Mock()
    
    # Mock files().list() for folder listing
    mock_list = Mock()
    mock_list.execute.return_value = {
        'files': [
            {'id': 'folder1', 'name': 'Operations', 'createdTime': '2024-01-01T00:00:00Z'},
            {'id': 'folder2', 'name': 'Reports', 'createdTime': '2024-01-02T00:00:00Z'}
        ]
    }
    service.files().list.return_value = mock_list
    
    # Mock files().create() for folder/file creation
    mock_create = Mock()
    mock_create.execute.return_value = {'id': 'new_folder_id'}
    service.files().create.return_value = mock_create
    
    # Mock files().get() for folder info
    mock_get = Mock()
    mock_get.execute.return_value = {
        'id': 'folder1',
        'name': 'Operations',
        'parents': ['safeexpress_id']
    }
    service.files().get.return_value = mock_get
    
    return service


@pytest.fixture
def sample_task_request():
    """Sample task request payload"""
    return {
        "tool": "list_folders",
        "inputs": {},
        "credentials_dict": {
            "access_token": "mock_access_token",
            "refresh_token": "mock_refresh_token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "mock_client_id",
            "client_secret": "mock_client_secret"
        }
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
        assert data["service"] == "Google Drive Agent API"
        assert data["version"] == "2.0.0"
        assert "available_tools" in data
        assert len(data["available_tools"]) == 6
    
    def test_health_endpoint(self):
        """Test GET /health returns healthy status"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "drive-agent"
        assert "available_tools" in data


# ============================================================
# TEST TOOLS - CREATE FOLDER
# ============================================================

class TestCreateFolder:
    """Test create_folder tool"""
    
    @patch('api.get_service_from_creds')
    def test_create_single_folder_success(self, mock_get_service, mock_credentials, mock_drive_service):
        """Test creating a single folder"""
        mock_get_service.return_value = mock_drive_service
        
        request_data = {
            "tool": "create_folder",
            "inputs": {"folder_path": "Operations"},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["folder_id"] is not None
        assert "SafeExpress/Operations" in data["folder_path"]
        assert "folder_url" in data
        assert data["error"] is None
    
    @patch('api.get_service_from_creds')
    def test_create_nested_folder_success(self, mock_get_service, mock_credentials, mock_drive_service):
        """Test creating nested folders"""
        mock_get_service.return_value = mock_drive_service
        
        request_data = {
            "tool": "create_folder",
            "inputs": {"folder_path": "Operations/2024/January"},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "SafeExpress/Operations/2024/January" in data["folder_path"]
    
    def test_create_folder_missing_path(self, mock_credentials):
        """Test create_folder without folder_path"""
        request_data = {
            "tool": "create_folder",
            "inputs": {},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        assert "folder_path is required" in data["error"]
    
    @patch('api.get_service_from_creds')
    def test_create_folder_api_error(self, mock_get_service, mock_credentials):
        """Test create_folder with API error"""
        mock_service = Mock()
        mock_service.files().create.side_effect = Exception("Drive API error")
        mock_get_service.return_value = mock_service
        
        request_data = {
            "tool": "create_folder",
            "inputs": {"folder_path": "TestFolder"},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        assert data["error"] is not None


# ============================================================
# TEST TOOLS - UPLOAD FILE
# ============================================================

class TestUploadFile:
    """Test upload_file tool"""
    
    @patch('api.get_service_from_creds')
    @patch('os.path.exists')
    @patch('builtins.open', create=True)
    def test_upload_file_success(self, mock_open, mock_exists, mock_get_service, 
                                 mock_credentials, mock_drive_service):
        """Test successful file upload"""
        mock_exists.return_value = True
        mock_open.return_value.__enter__ = Mock()
        mock_open.return_value.__exit__ = Mock()
        mock_get_service.return_value = mock_drive_service
        
        # Mock upload result
        mock_drive_service.files().create().execute.return_value = {'id': 'file123'}
        
        request_data = {
            "tool": "upload_file",
            "inputs": {
                "file_path": "/tmp/test.txt",
                "filename": "test.txt"
            },
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["file_id"] == "file123"
        assert "file_url" in data
        assert "test.txt" in data["filename"]
    
    @patch('api.get_service_from_creds')
    @patch('os.path.exists')
    @patch('builtins.open', create=True)
    def test_upload_file_to_folder(self, mock_open, mock_exists, mock_get_service,
                                   mock_credentials, mock_drive_service):
        """Test file upload to specific folder"""
        mock_exists.return_value = True
        mock_open.return_value.__enter__ = Mock()
        mock_open.return_value.__exit__ = Mock()
        mock_get_service.return_value = mock_drive_service
        mock_drive_service.files().create().execute.return_value = {'id': 'file456'}
        
        request_data = {
            "tool": "upload_file",
            "inputs": {
                "file_path": "/tmp/report.pdf",
                "filename": "report.pdf",
                "folder_path": "Reports/2024"
            },
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "Reports/2024" in data["folder_path"]
    
    def test_upload_file_missing_params(self, mock_credentials):
        """Test upload_file with missing parameters"""
        request_data = {
            "tool": "upload_file",
            "inputs": {"file_path": "/tmp/test.txt"},  # Missing filename
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        assert "filename is required" in data["error"]
    
    @patch('os.path.exists')
    def test_upload_file_not_found(self, mock_exists, mock_credentials):
        """Test upload_file with non-existent file"""
        mock_exists.return_value = False
        
        request_data = {
            "tool": "upload_file",
            "inputs": {
                "file_path": "/nonexistent/file.txt",
                "filename": "file.txt"
            },
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        assert "File not found" in data["error"]


# ============================================================
# TEST TOOLS - LIST FOLDERS
# ============================================================

class TestListFolders:
    """Test list_folders tool"""
    
    @patch('api.get_service_from_creds')
    def test_list_folders_success(self, mock_get_service, mock_credentials, mock_drive_service):
        """Test listing folders successfully"""
        mock_get_service.return_value = mock_drive_service
        
        request_data = {
            "tool": "list_folders",
            "inputs": {},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "folders" in data
        assert data["count"] >= 0
        assert "tree" in data
    
    @patch('api.get_service_from_creds')
    def test_list_folders_empty(self, mock_get_service, mock_credentials):
        """Test listing folders when none exist"""
        mock_service = Mock()
        mock_list = Mock()
        mock_list.execute.return_value = {'files': []}
        mock_service.files().list.return_value = mock_list
        mock_get_service.return_value = mock_service
        
        request_data = {
            "tool": "list_folders",
            "inputs": {},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["count"] == 0


# ============================================================
# TEST TOOLS - LIST FILES
# ============================================================

class TestListFiles:
    """Test list_files tool"""
    
    @patch('api.get_service_from_creds')
    def test_list_files_root(self, mock_get_service, mock_credentials, mock_drive_service):
        """Test listing files in SafeExpress root"""
        # Mock file list response
        mock_list = Mock()
        mock_list.execute.return_value = {
            'files': [
                {
                    'id': 'file1',
                    'name': 'document.pdf',
                    'mimeType': 'application/pdf',
                    'size': '1024000',
                    'createdTime': '2024-01-01T00:00:00Z'
                }
            ]
        }
        mock_drive_service.files().list.return_value = mock_list
        mock_get_service.return_value = mock_drive_service
        
        request_data = {
            "tool": "list_files",
            "inputs": {},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "files" in data
        assert data["count"] >= 0
        assert "folder_path" in data
    
    @patch('api.get_service_from_creds')
    def test_list_files_in_folder(self, mock_get_service, mock_credentials, mock_drive_service):
        """Test listing files in specific folder"""
        mock_get_service.return_value = mock_drive_service
        
        request_data = {
            "tool": "list_files",
            "inputs": {"folder_path": "Operations"},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        # May succeed or fail depending on folder existence
        assert "success" in data
        assert "files" in data
    
    @patch('api.get_service_from_creds')
    def test_list_files_folder_not_found(self, mock_get_service, mock_credentials):
        """Test listing files in non-existent folder"""
        mock_service = Mock()
        mock_list = Mock()
        mock_list.execute.return_value = {'files': []}
        mock_service.files().list.return_value = mock_list
        mock_get_service.return_value = mock_service
        
        request_data = {
            "tool": "list_files",
            "inputs": {"folder_path": "NonExistentFolder"},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        assert "not found" in data["error"].lower()


# ============================================================
# TEST TOOLS - SEARCH FILES
# ============================================================

class TestSearchFiles:
    """Test search_files tool"""
    
    @patch('api.get_service_from_creds')
    def test_search_files_found(self, mock_get_service, mock_credentials, mock_drive_service):
        """Test searching files with results"""
        # Mock search results
        mock_list = Mock()
        mock_list.execute.return_value = {
            'files': [
                {'id': 'file1', 'name': 'report_2024.pdf', 'mimeType': 'application/pdf'}
            ]
        }
        mock_drive_service.files().list.return_value = mock_list
        mock_get_service.return_value = mock_drive_service
        
        request_data = {
            "tool": "search_files",
            "inputs": {"search_term": "report"},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "results" in data
        assert data["count"] >= 0
        assert data["search_term"] == "report"
    
    @patch('api.get_service_from_creds')
    def test_search_files_not_found(self, mock_get_service, mock_credentials):
        """Test searching files with no results"""
        mock_service = Mock()
        mock_list = Mock()
        mock_list.execute.return_value = {'files': []}
        mock_service.files().list.return_value = mock_list
        mock_get_service.return_value = mock_service
        
        request_data = {
            "tool": "search_files",
            "inputs": {"search_term": "nonexistent"},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["count"] == 0
    
    def test_search_files_missing_term(self, mock_credentials):
        """Test search_files without search term"""
        request_data = {
            "tool": "search_files",
            "inputs": {},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        assert "search_term is required" in data["error"]


# ============================================================
# TEST TOOLS - GET FOLDER INFO
# ============================================================

class TestGetFolderInfo:
    """Test get_folder_info tool"""
    
    @patch('api.get_service_from_creds')
    def test_get_folder_info_success(self, mock_get_service, mock_credentials, mock_drive_service):
        """Test getting folder info successfully"""
        mock_get_service.return_value = mock_drive_service
        
        # Mock files and subfolders
        mock_list = Mock()
        mock_list.execute.return_value = {'files': []}
        mock_drive_service.files().list.return_value = mock_list
        
        request_data = {
            "tool": "get_folder_info",
            "inputs": {"folder_path": "Operations"},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        # May succeed or fail depending on folder existence
        assert "success" in data
        if data["success"]:
            assert "folder_id" in data
            assert "file_count" in data
            assert "subfolder_count" in data
    
    def test_get_folder_info_missing_path(self, mock_credentials):
        """Test get_folder_info without folder path"""
        request_data = {
            "tool": "get_folder_info",
            "inputs": {},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        assert "folder_path is required" in data["error"]


# ============================================================
# TEST ERROR HANDLING
# ============================================================

class TestErrorHandling:
    """Test error handling scenarios"""
    
    def test_missing_credentials(self):
        """Test request without credentials"""
        request_data = {
            "tool": "list_folders",
            "inputs": {}
            # No credentials_dict
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 401
    
    def test_invalid_tool_name(self, mock_credentials):
        """Test request with invalid tool name"""
        request_data = {
            "tool": "invalid_tool_name",
            "inputs": {},
            "credentials_dict": mock_credentials.dict()
        }
        
        response = client.post("/execute_task", json=request_data)
        assert response.status_code == 400
        assert "Unknown tool" in response.json()["detail"]
    
    def test_malformed_request(self):
        """Test malformed JSON request"""
        response = client.post(
            "/execute_task",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422  # Unprocessable Entity


# ============================================================
# TEST HELPER FUNCTIONS
# ============================================================

class TestHelperFunctions:
    """Test helper functions"""
    
    def test_format_folder_tree_empty(self):
        """Test formatting empty folder tree"""
        from api import format_folder_tree
        result = format_folder_tree([])
        assert "No folders found" in result
    
    def test_format_folder_tree_with_data(self):
        """Test formatting folder tree with data"""
        from api import format_folder_tree
        folders = [
            {"display": "📁 Operations"},
            {"display": "  📁 2024"}
        ]
        result = format_folder_tree(folders)
        assert "SafeExpress" in result
        assert "Operations" in result
    
    def test_format_file_list_empty(self):
        """Test formatting empty file list"""
        from api import format_file_list
        result = format_file_list([])
        assert "No files" in result
    
    def test_format_file_list_with_data(self):
        """Test formatting file list with data"""
        from api import format_file_list
        files = [
            {"name": "test.pdf", "size": "1048576"},  # 1MB
            {"name": "doc.txt", "size": "N/A"}
        ]
        result = format_file_list(files)
        assert "test.pdf" in result
        assert "MB" in result


# ============================================================
# INTEGRATION TESTS
# ============================================================

class TestIntegration:
    """Integration tests for complete workflows"""
    
    @patch('main.get_service_from_creds')
    def test_create_folder_and_upload_workflow(self, mock_get_service, 
                                               mock_credentials, mock_drive_service):
        """Test creating folder then uploading file"""
        mock_get_service.return_value = mock_drive_service
        mock_drive_service.files().create().execute.return_value = {'id': 'folder123'}
        
        # Step 1: Create folder
        create_request = {
            "tool": "create_folder",
            "inputs": {"folder_path": "TestWorkflow"},
            "credentials_dict": mock_credentials.dict()
        }
        
        response1 = client.post("/execute_task", json=create_request)
        assert response1.status_code == 200
        assert response1.json()["success"] is True
        
        # Step 2: Upload file to folder
        with patch('os.path.exists', return_value=True), \
             patch('builtins.open', create=True):
            
            upload_request = {
                "tool": "upload_file",
                "inputs": {
                    "file_path": "/tmp/test.txt",
                    "filename": "test.txt",
                    "folder_path": "TestWorkflow"
                },
                "credentials_dict": mock_credentials.dict()
            }
            
            mock_drive_service.files().create().execute.return_value = {'id': 'file123'}
            response2 = client.post("/execute_task", json=upload_request)
            assert response2.status_code == 200
            assert response2.json()["success"] is True


# ============================================================
# RUN TESTS
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--color=yes"])