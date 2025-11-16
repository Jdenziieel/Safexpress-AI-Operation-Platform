"""
Unit Tests for Google Drive Agent
Tests all tools and API endpoints with proper mocking
Run with: pytest test/test_drive_agent.py -v
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock, mock_open
from io import BytesIO
import json

# Add parent directory to path to import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import (
    create_nested_folder_impl,
    list_folders_in_safeexpress_impl,
    list_files_in_folder_impl,
    get_folder_structure_impl,
    upload_file_to_folder_impl,
    upload_stream_to_folder_impl,
    search_files_in_safeexpress_impl,
    get_folder_info_impl,
    get_safeexpress_folder_id,
    find_folder,
)

from api import (
    upload_file_tool,
    create_folder_tool,
    list_folders_tool,
    list_files_tool,
    search_files_tool,
    get_folder_info_tool,
    CredentialsDict,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def mock_drive_service():
    """Create a mock Google Drive service"""
    service = Mock()
    
    # Mock files().list()
    list_mock = Mock()
    list_mock.execute.return_value = {"files": []}
    service.files().list.return_value = list_mock
    
    # Mock files().create()
    create_mock = Mock()
    create_mock.execute.return_value = {"id": "test_file_id_123"}
    service.files().create.return_value = create_mock
    
    # Mock files().get()
    get_mock = Mock()
    get_mock.execute.return_value = {
        "id": "test_id",
        "name": "Test Folder",
        "parents": ["parent_id"]
    }
    service.files().get.return_value = get_mock
    
    return service


@pytest.fixture
def mock_credentials():
    """Create mock credentials for API calls"""
    return CredentialsDict(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test_client_id",
        client_secret="test_client_secret"
    )


@pytest.fixture
def sample_folder_structure():
    """Sample folder structure for testing"""
    return [
        {"id": "folder1", "name": "Operations", "display": "📁 Operations", "level": 0},
        {"id": "folder2", "name": "2024", "display": "  📁 2024", "level": 1},
        {"id": "folder3", "name": "Reports", "display": "    📁 Reports", "level": 2},
    ]


@pytest.fixture
def sample_files():
    """Sample files for testing"""
    return [
        {
            "id": "file1",
            "name": "report.pdf",
            "mimeType": "application/pdf",
            "size": "1048576",
            "createdTime": "2024-01-01T00:00:00Z"
        },
        {
            "id": "file2",
            "name": "data.xlsx",
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "size": "2097152",
            "createdTime": "2024-01-02T00:00:00Z"
        }
    ]


# ============================================================
# TESTS FOR tools.py - Core Functions
# ============================================================

class TestToolsFunctions:
    """Test core tool functions from tools.py"""
    
    def test_get_safeexpress_folder_id(self, mock_drive_service):
        """Test getting SafeExpress folder ID"""
        mock_drive_service.files().list().execute.return_value = {
            "files": [{"id": "safeexpress_id", "name": "SafeExpress"}]
        }
        
        with patch('tools.build', return_value=mock_drive_service):
            folder_id = get_safeexpress_folder_id(mock_drive_service)
            assert folder_id is not None
    
    def test_find_folder_exists(self, mock_drive_service):
        """Test finding an existing folder"""
        mock_drive_service.files().list().execute.return_value = {
            "files": [{"id": "found_folder_id", "name": "TestFolder"}]
        }
        
        folder_id = find_folder(mock_drive_service, "TestFolder")
        assert folder_id == "found_folder_id"
    
    def test_find_folder_not_exists(self, mock_drive_service):
        """Test finding a non-existent folder"""
        mock_drive_service.files().list().execute.return_value = {"files": []}
        
        folder_id = find_folder(mock_drive_service, "NonExistent")
        assert folder_id is None
    
    def test_create_nested_folder_impl_success(self, mock_drive_service):
        """Test creating nested folders successfully"""
        # Mock SafeExpress folder exists
        mock_drive_service.files().list().execute.return_value = {
            "files": [{"id": "safeexpress_id", "name": "SafeExpress"}]
        }
        
        # Mock folder creation
        mock_drive_service.files().create().execute.return_value = {
            "id": "new_folder_id"
        }
        
        result = create_nested_folder_impl(mock_drive_service, "Operations/2024")
        
        assert result["success"] is True
        assert result["folder_id"] is not None
        assert "Operations/2024" in result["folder_path"]
        assert result["error"] is None
    
    def test_create_nested_folder_impl_empty_path(self, mock_drive_service):
        """Test creating folder with empty path"""
        result = create_nested_folder_impl(mock_drive_service, "")
        
        assert result["success"] is False
        assert result["error"] == "Empty folder path"
    
    def test_list_folders_in_safeexpress_impl_success(self, mock_drive_service, sample_folder_structure):
        """Test listing folders in SafeExpress"""
        mock_drive_service.files().list().execute.return_value = {
            "files": [
                {"id": "folder1", "name": "Operations", "createdTime": "2024-01-01"},
                {"id": "folder2", "name": "HR", "createdTime": "2024-01-02"}
            ]
        }
        
        result = list_folders_in_safeexpress_impl(mock_drive_service)
        
        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["folders"]) == 2
        assert result["error"] is None
    
    def test_list_files_in_folder_impl_success(self, mock_drive_service, sample_files):
        """Test listing files in a folder"""
        mock_drive_service.files().list().execute.return_value = {
            "files": sample_files
        }
        
        result = list_files_in_folder_impl(mock_drive_service, "test_folder_id")
        
        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["files"]) == 2
        assert result["error"] is None
    
    def test_get_folder_structure_impl_success(self, mock_drive_service):
        """Test getting folder structure"""
        # Mock nested folder structure
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "f1", "name": "Operations", "createdTime": "2024-01-01"}]},
            {"files": [{"id": "f2", "name": "2024", "createdTime": "2024-01-02"}]},
            {"files": []}
        ]
        
        result = get_folder_structure_impl(mock_drive_service, max_level=2)
        
        assert result["success"] is True
        assert result["count"] >= 0
        assert result["error"] is None
    
    def test_upload_stream_to_folder_impl_success(self, mock_drive_service):
        """Test uploading stream to folder"""
        # Mock SafeExpress folder
        mock_drive_service.files().list().execute.return_value = {
            "files": [{"id": "safeexpress_id", "name": "SafeExpress"}]
        }
        
        # Mock file upload
        mock_drive_service.files().create().execute.return_value = {
            "id": "uploaded_file_id"
        }
        
        file_stream = BytesIO(b"test file content")
        result = upload_stream_to_folder_impl(
            mock_drive_service,
            file_stream,
            "test.txt",
            "text/plain"
        )
        
        assert result["success"] is True
        assert result["file_id"] == "uploaded_file_id"
        assert "test.txt" in result["filename"]
        assert result["error"] is None
    
    def test_search_files_in_safeexpress_impl_success(self, mock_drive_service, sample_files):
        """Test searching files"""
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "safeexpress_id", "name": "SafeExpress"}]},
            {"files": [sample_files[0]]}
        ]
        
        result = search_files_in_safeexpress_impl(mock_drive_service, "report")
        
        assert result["success"] is True
        assert result["count"] >= 0
        assert result["search_term"] == "report"
        assert result["error"] is None
    
    def test_search_files_no_results(self, mock_drive_service):
        """Test searching with no results"""
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "safeexpress_id", "name": "SafeExpress"}]},
            {"files": []}
        ]
        
        result = search_files_in_safeexpress_impl(mock_drive_service, "nonexistent")
        
        assert result["success"] is True
        assert result["count"] == 0
        assert len(result["results"]) == 0
    
    def test_get_folder_info_impl_success(self, mock_drive_service):
        """Test getting folder info"""
        # Mock folder exists
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "safeexpress_id", "name": "SafeExpress"}]},
            {"files": [{"id": "target_folder", "name": "Operations"}]},
            {"files": []},  # files in folder
            {"files": []}   # subfolders
        ]
        
        result = get_folder_info_impl(mock_drive_service, "Operations")
        
        assert result["success"] is True
        assert result["folder_id"] is not None
        assert result["error"] is None
    
    def test_upload_file_to_folder_impl_file_not_found(self, mock_drive_service):
        """Test uploading non-existent file"""
        result = upload_file_to_folder_impl(
            mock_drive_service,
            "test.txt",
            "/nonexistent/path/file.txt"
        )
        
        assert result["success"] is False
        assert "not found" in result["error"].lower()


# ============================================================
# TESTS FOR api.py - Tool Functions
# ============================================================

class TestAPITools:
    """Test API tool functions from api.py"""
    
    @patch('api.get_service_from_creds')
    def test_create_folder_tool_success(self, mock_get_service, mock_drive_service, mock_credentials):
        """Test create_folder tool"""
        mock_get_service.return_value = mock_drive_service
        
        # Mock folder creation
        mock_drive_service.files().list().execute.return_value = {
            "files": [{"id": "safeexpress_id", "name": "SafeExpress"}]
        }
        mock_drive_service.files().create().execute.return_value = {
            "id": "new_folder_id"
        }
        
        inputs = {"folder_path": "Operations/2024"}
        result = create_folder_tool(inputs, mock_credentials)
        
        assert result["success"] is True
        assert result["folder_id"] is not None
        assert result["error"] is None
    
    @patch('api.get_service_from_creds')
    def test_create_folder_tool_missing_input(self, mock_get_service, mock_credentials):
        """Test create_folder with missing folder_path"""
        inputs = {}
        result = create_folder_tool(inputs, mock_credentials)
        
        assert result["success"] is False
        assert "folder_path is required" in result["error"]
    
    @patch('api.get_service_from_creds')
    def test_list_folders_tool_success(self, mock_get_service, mock_drive_service, mock_credentials):
        """Test list_folders tool"""
        mock_get_service.return_value = mock_drive_service
        
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "safeexpress_id", "name": "SafeExpress"}]},
            {"files": [{"id": "f1", "name": "Ops", "createdTime": "2024-01-01"}]},
            {"files": []}
        ]
        
        inputs = {}
        result = list_folders_tool(inputs, mock_credentials)
        
        assert result["success"] is True
        assert "folders" in result
        assert result["error"] is None
    
    @patch('api.get_service_from_creds')
    def test_list_files_tool_success(self, mock_get_service, mock_drive_service, mock_credentials, sample_files):
        """Test list_files tool"""
        mock_get_service.return_value = mock_drive_service
        
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "safeexpress_id", "name": "SafeExpress"}]},
            {"files": sample_files}
        ]
        
        inputs = {}
        result = list_files_tool(inputs, mock_credentials)
        
        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["files"]) == 2
    
    @patch('api.get_service_from_creds')
    def test_search_files_tool_success(self, mock_get_service, mock_drive_service, mock_credentials, sample_files):
        """Test search_files tool"""
        mock_get_service.return_value = mock_drive_service
        
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "safeexpress_id", "name": "SafeExpress"}]},
            {"files": [sample_files[0]]}
        ]
        
        inputs = {"search_term": "report"}
        result = search_files_tool(inputs, mock_credentials)
        
        assert result["success"] is True
        assert result["search_term"] == "report"
    
    @patch('api.get_service_from_creds')
    def test_search_files_tool_missing_input(self, mock_get_service, mock_credentials):
        """Test search_files with missing search_term"""
        inputs = {}
        result = search_files_tool(inputs, mock_credentials)
        
        assert result["success"] is False
        assert "search_term is required" in result["error"]
    
    @patch('api.get_service_from_creds')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data=b"test content")
    def test_upload_file_tool_success(self, mock_file, mock_exists, mock_get_service, mock_drive_service, mock_credentials):
        """Test upload_file tool"""
        mock_get_service.return_value = mock_drive_service
        mock_exists.return_value = True
        
        # Mock folder and upload
        mock_drive_service.files().list().execute.return_value = {
            "files": [{"id": "safeexpress_id", "name": "SafeExpress"}]
        }
        mock_drive_service.files().create().execute.return_value = {
            "id": "uploaded_file_id"
        }
        
        inputs = {
            "file_path": "/tmp/test.txt",
            "filename": "test.txt",
            "mime_type": "text/plain"
        }
        result = upload_file_tool(inputs, mock_credentials)
        
        assert result["success"] is True
        assert result["file_id"] == "uploaded_file_id"
        assert result["filename"] == "test.txt"
    
    @patch('api.get_service_from_creds')
    def test_upload_file_tool_missing_file_path(self, mock_get_service, mock_credentials):
        """Test upload_file with missing file_path"""
        inputs = {"filename": "test.txt"}
        result = upload_file_tool(inputs, mock_credentials)
        
        assert result["success"] is False
        assert "file_path is required" in result["error"]
    
    @patch('api.get_service_from_creds')
    def test_get_folder_info_tool_success(self, mock_get_service, mock_drive_service, mock_credentials):
        """Test get_folder_info tool"""
        mock_get_service.return_value = mock_drive_service
        
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "safeexpress_id", "name": "SafeExpress"}]},
            {"files": [{"id": "ops_folder", "name": "Operations"}]},
            {"files": []},  # files
            {"files": []}   # subfolders
        ]
        
        inputs = {"folder_path": "Operations"}
        result = get_folder_info_tool(inputs, mock_credentials)
        
        assert result["success"] is True
        assert result["folder_id"] is not None
    
    @patch('api.get_service_from_creds')
    def test_get_folder_info_tool_missing_input(self, mock_get_service, mock_credentials):
        """Test get_folder_info with missing folder_path"""
        inputs = {}
        result = get_folder_info_tool(inputs, mock_credentials)
        
        assert result["success"] is False
        assert "folder_path is required" in result["error"]


# ============================================================
# INTEGRATION-STYLE TESTS
# ============================================================

class TestIntegration:
    """Integration-style tests for complete workflows"""
    
    @patch('api.get_service_from_creds')
    def test_create_and_list_folder_workflow(self, mock_get_service, mock_drive_service, mock_credentials):
        """Test creating a folder then listing it"""
        mock_get_service.return_value = mock_drive_service
        
        # Mock folder creation
        mock_drive_service.files().list().execute.return_value = {
            "files": [{"id": "safeexpress_id", "name": "SafeExpress"}]
        }
        mock_drive_service.files().create().execute.return_value = {
            "id": "new_folder_id"
        }
        
        # Create folder
        create_inputs = {"folder_path": "TestFolder"}
        create_result = create_folder_tool(create_inputs, mock_credentials)
        assert create_result["success"] is True
        
        # Mock listing with new folder
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "safeexpress_id", "name": "SafeExpress"}]},
            {"files": [{"id": "new_folder_id", "name": "TestFolder", "createdTime": "2024-01-01"}]},
            {"files": []}
        ]
        
        # List folders
        list_inputs = {}
        list_result = list_folders_tool(list_inputs, mock_credentials)
        assert list_result["success"] is True
        assert list_result["count"] >= 0
    
    @patch('api.get_service_from_creds')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data=b"test content")
    def test_upload_and_search_workflow(self, mock_file, mock_exists, mock_get_service, mock_drive_service, mock_credentials):
        """Test uploading a file then searching for it"""
        mock_get_service.return_value = mock_drive_service
        mock_exists.return_value = True
        
        # Mock upload
        mock_drive_service.files().list().execute.return_value = {
            "files": [{"id": "safeexpress_id", "name": "SafeExpress"}]
        }
        mock_drive_service.files().create().execute.return_value = {
            "id": "uploaded_file_id"
        }
        
        # Upload file
        upload_inputs = {
            "file_path": "/tmp/report.pdf",
            "filename": "report.pdf"
        }
        upload_result = upload_file_tool(upload_inputs, mock_credentials)
        assert upload_result["success"] is True
        
        # Mock search
        mock_drive_service.files().list().execute.side_effect = [
            {"files": [{"id": "safeexpress_id", "name": "SafeExpress"}]},
            {"files": [{
                "id": "uploaded_file_id",
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "size": "1024",
                "createdTime": "2024-01-01"
            }]}
        ]
        
        # Search for file
        search_inputs = {"search_term": "report"}
        search_result = search_files_tool(search_inputs, mock_credentials)
        assert search_result["success"] is True
        assert search_result["count"] >= 0


# ============================================================
# ERROR HANDLING TESTS
# ============================================================

class TestErrorHandling:
    """Test error handling and edge cases"""
    
    @patch('api.get_service_from_creds')
    def test_api_exception_handling(self, mock_get_service, mock_credentials):
        """Test that API exceptions are caught and returned properly"""
        mock_service = Mock()
        mock_service.files().list.side_effect = Exception("API Error")
        mock_get_service.return_value = mock_service
        
        inputs = {}
        result = list_folders_tool(inputs, mock_credentials)
        
        assert result["success"] is False
        assert "error" in result
    
    def test_tools_exception_handling(self, mock_drive_service):
        """Test that tools exceptions are handled"""
        mock_drive_service.files().list.side_effect = Exception("Service Error")
        
        result = list_folders_in_safeexpress_impl(mock_drive_service)
        
        assert result["success"] is False
        assert result["error"] is not None
    
    @patch('api.get_service_from_creds')
    def test_invalid_credentials(self, mock_get_service):
        """Test handling invalid credentials"""
        mock_get_service.side_effect = Exception("Invalid credentials")
        
        invalid_creds = CredentialsDict(
            access_token="invalid",
            refresh_token="invalid",
            token_uri="https://oauth2.googleapis.com/token"
        )
        
        inputs = {"folder_path": "Test"}
        result = create_folder_tool(inputs, invalid_creds)
        
        assert result["success"] is False


# ============================================================
# RUN TESTS
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])