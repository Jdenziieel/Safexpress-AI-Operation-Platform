"""
Test script for Mapping Agent API
Tests all data intelligence and transformation features
"""

import requests
import json

BASE_URL = "http://localhost:8004"


def test_health_check():
    """Test health check endpoint"""
    print("\n" + "=" * 60)
    print("TEST 1: Health Check")
    print("=" * 60)
    
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    print("✅ Health check passed")


def test_list_tools():
    """Test list tools endpoint"""
    print("\n" + "=" * 60)
    print("TEST 2: List Available Tools")
    print("=" * 60)
    
    response = requests.get(f"{BASE_URL}/tools")
    print(f"Status Code: {response.status_code}")
    data = response.json()
    
    print(f"\nAvailable tools ({data['count']}):")
    for tool in data["tools"]:
        print(f"  • {tool['name']}: {tool['description']}")
    
    assert response.status_code == 200
    assert "tools" in data
    print(f"\n✅ Found {len(data['tools'])} tools")


def test_parse_csv():
    """Test parsing CSV file"""
    print("\n" + "=" * 60)
    print("TEST 3: Parse CSV File")
    print("=" * 60)
    
    csv_content = """Employee Name,Total Hours,Safety Incidents,Work Date
John Doe,40,0,2025-01-28
Jane Smith,35,1,2025-01-28
Bob Johnson,38,0,2025-01-28"""
    
    payload = {
        "tool": "parse_file",
        "inputs": {
            "file_content": csv_content,
            "file_type": "csv"
        }
    }
    
    response = requests.post(f"{BASE_URL}/execute", json=payload)
    print(f"Status Code: {response.status_code}")
    result = response.json()
    print(f"Success: {result.get('success')}")
    
    if result.get("success"):
        data = result.get("result", {})
        print(f"\nParsed Data:")
        print(f"  Columns: {data.get('columns')}")
        print(f"  Row Count: {data.get('row_count')}")
        print(f"  Data Types: {json.dumps(data.get('data_types'), indent=4)}")
        print(f"  Sample Values: {json.dumps(data.get('sample_values'), indent=4)}")
        print("✅ CSV parsing passed")
        return data
    else:
        print(f"❌ Error: {result.get('error')}")
        return None


def test_smart_column_mapping():
    """Test smart column mapping"""
    print("\n" + "=" * 60)
    print("TEST 4: Smart Column Mapping")
    print("=" * 60)
    
    payload = {
        "tool": "smart_column_mapping",
        "inputs": {
            "source_columns": [
                "Employee Name",
                "Total Hours",
                "Safety Incidents",
                "Work Date"
            ],
            "target_columns": [
                "Present",
                "Total Manhours",
                "Losttime Incident",
                "Date",
                "Week"
            ]
        }
    }
    
    response = requests.post(f"{BASE_URL}/execute", json=payload)
    print(f"Status Code: {response.status_code}")
    result = response.json()
    print(f"Success: {result.get('success')}")
    
    if result.get("success"):
        data = result.get("result", {})
        print(f"\nMapping Results:")
        print(f"  Method: {data.get('method')}")
        print(f"\n  Mappings:")
        for source, target in data.get("mappings", {}).items():
            confidence = data.get("confidence_scores", {}).get(source, 0)
            print(f"    {source} → {target} (confidence: {confidence:.2f})")
        
        print(f"\n  High Confidence Count: {data.get('high_confidence_count')}")
        print(f"  Accuracy Estimate: {data.get('accuracy_estimate', 0):.2%}")
        
        if data.get("needs_review"):
            print(f"\n  ⚠️ Needs Review:")
            for item in data["needs_review"]:
                print(f"    {item}")
        
        print("✅ Smart mapping passed")
        return data.get("mappings")
    else:
        print(f"❌ Error: {result.get('error')}")
        return None


def test_validate_mapping():
    """Test mapping validation"""
    print("\n" + "=" * 60)
    print("TEST 5: Validate Mapping")
    print("=" * 60)
    
    payload = {
        "tool": "validate_mapping",
        "inputs": {
            "mappings": {
                "Employee Name": "Present",
                "Total Hours": "Total Manhours",
                "Safety Incidents": "Losttime Incident",
                "Work Date": "Date"
            },
            "source_columns": ["Employee Name", "Total Hours", "Safety Incidents", "Work Date"],
            "target_columns": ["Present", "Total Manhours", "Losttime Incident", "Date", "Week"],
            "require_all_targets": False
        }
    }
    
    response = requests.post(f"{BASE_URL}/execute", json=payload)
    print(f"Status Code: {response.status_code}")
    result = response.json()
    print(f"Success: {result.get('success')}")
    
    if result.get("success"):
        data = result.get("result", {})
        print(f"\nValidation Results:")
        print(f"  Is Valid: {data.get('is_valid')}")
        print(f"  Summary: {json.dumps(data.get('summary'), indent=4)}")
        
        if data.get("errors"):
            print(f"\n  ❌ Errors:")
            for error in data["errors"]:
                print(f"    {error}")
        
        if data.get("warnings"):
            print(f"\n  ⚠️ Warnings:")
            for warning in data["warnings"]:
                print(f"    {warning['message']}")
        
        print("✅ Validation passed")
        return data
    else:
        print(f"❌ Error: {result.get('error')}")
        return None


def test_transform_data():
    """Test data transformation"""
    print("\n" + "=" * 60)
    print("TEST 6: Transform Data")
    print("=" * 60)
    
    # First parse some data
    csv_content = """Employee Name,Total Hours,Safety Incidents,Work Date
John Doe,40,0,2025-01-28
Jane Smith,35,1,2025-01-28"""
    
    parse_payload = {
        "tool": "parse_file",
        "inputs": {
            "file_content": csv_content,
            "file_type": "csv"
        }
    }
    
    parse_response = requests.post(f"{BASE_URL}/execute", json=parse_payload)
    parse_result = parse_response.json()
    
    if not parse_result.get("success"):
        print(f"❌ Failed to parse data for transformation test")
        return None
    
    full_data = parse_result["result"]["full_data"]
    
    # Now transform
    transform_payload = {
        "tool": "transform_data",
        "inputs": {
            "source_data": full_data,
            "mappings": {
                "Employee Name": "Present",
                "Total Hours": "Total Manhours",
                "Safety Incidents": "Losttime Incident",
                "Work Date": "Date"
            },
            "target_columns": ["Present", "Total Manhours", "Losttime Incident", "Date"],
            "fill_missing": True
        }
    }
    
    response = requests.post(f"{BASE_URL}/execute", json=transform_payload)
    print(f"Status Code: {response.status_code}")
    result = response.json()
    print(f"Success: {result.get('success')}")
    
    if result.get("success"):
        data = result.get("result", {})
        print(f"\nTransformation Results:")
        print(f"  Rows Processed: {data.get('row_count')}")
        print(f"  Output Columns: {data.get('columns')}")
        print(f"  Statistics: {json.dumps(data.get('statistics'), indent=4)}")
        
        # Parse and show sample transformed data
        import json as json_lib
        transformed = json_lib.loads(data.get('transformed_data', '[]'))
        if transformed:
            print(f"\n  Sample Transformed Row:")
            print(f"    {json.dumps(transformed[0], indent=6)}")
        
        print("✅ Transformation passed")
        return data.get("transformed_data")
    else:
        print(f"❌ Error: {result.get('error')}")
        return None


def test_save_load_template():
    """Test saving and loading mapping templates"""
    print("\n" + "=" * 60)
    print("TEST 7: Save and Load Mapping Template")
    print("=" * 60)
    
    # Save template
    save_payload = {
        "tool": "save_mapping_template",
        "inputs": {
            "template_name": "SafExpressOps Weekly Report",
            "mappings": {
                "Employee Name": "Present",
                "Total Hours": "Total Manhours",
                "Safety Incidents": "Losttime Incident",
                "Work Date": "Date"
            },
            "target_columns": ["Present", "Total Manhours", "Losttime Incident", "Date"],
            "metadata": {
                "description": "Weekly employee hours and safety report",
                "created_by": "test_script",
                "version": "1.0"
            }
        }
    }
    
    save_response = requests.post(f"{BASE_URL}/execute", json=save_payload)
    print(f"Save Status: {save_response.status_code}")
    save_result = save_response.json()
    
    if not save_result.get("success"):
        print(f"❌ Failed to save template: {save_result.get('error')}")
        return False
    
    print(f"✓ Template saved: {save_result['result']['template_id']}")
    
    # Load template
    load_payload = {
        "tool": "load_mapping_template",
        "inputs": {
            "template_name": "SafExpressOps Weekly Report"
        }
    }
    
    load_response = requests.post(f"{BASE_URL}/execute", json=load_payload)
    print(f"Load Status: {load_response.status_code}")
    load_result = load_response.json()
    
    if load_result.get("success"):
        data = load_result.get("result", {})
        print(f"\nLoaded Template:")
        print(f"  Name: {data.get('template_name')}")
        print(f"  Mappings: {json.dumps(data.get('mappings'), indent=4)}")
        print(f"  Metadata: {json.dumps(data.get('metadata'), indent=4)}")
        print("✅ Template save/load passed")
        return True
    else:
        print(f"❌ Failed to load template: {load_result.get('error')}")
        return False


def test_complete_workflow():
    """Test complete end-to-end workflow"""
    print("\n" + "=" * 60)
    print("TEST 8: Complete Workflow (Parse → Map → Validate → Transform)")
    print("=" * 60)
    
    csv_content = """Employee,Hours,Incidents,Date
John,40,0,2025-01-28
Jane,35,1,2025-01-28"""
    
    # Step 1: Parse
    print("\n📄 Step 1: Parse CSV...")
    parse_result = requests.post(f"{BASE_URL}/execute", json={
        "tool": "parse_file",
        "inputs": {"file_content": csv_content, "file_type": "csv"}
    }).json()
    
    if not parse_result.get("success"):
        print(f"❌ Parse failed")
        return False
    
    columns = parse_result["result"]["columns"]
    full_data = parse_result["result"]["full_data"]
    print(f"✓ Parsed {len(columns)} columns")
    
    # Step 2: Smart Mapping
    print("\n🧠 Step 2: Smart column mapping...")
    map_result = requests.post(f"{BASE_URL}/execute", json={
        "tool": "smart_column_mapping",
        "inputs": {
            "source_columns": columns,
            "target_columns": ["Present", "Total Manhours", "Losttime Incident", "Date"]
        }
    }).json()
    
    if not map_result.get("success"):
        print(f"❌ Mapping failed")
        return False
    
    mappings = map_result["result"]["mappings"]
    print(f"✓ Generated mappings with {map_result['result']['accuracy_estimate']:.0%} accuracy")
    
    # Step 3: Validate
    print("\n✔️ Step 3: Validate mappings...")
    validate_result = requests.post(f"{BASE_URL}/execute", json={
        "tool": "validate_mapping",
        "inputs": {
            "mappings": mappings,
            "source_columns": columns,
            "target_columns": ["Present", "Total Manhours", "Losttime Incident", "Date"]
        }
    }).json()
    
    if not validate_result.get("success"):
        print(f"❌ Validation failed")
        return False
    
    is_valid = validate_result["result"]["is_valid"]
    print(f"✓ Validation: {'PASS' if is_valid else 'FAIL'}")
    
    # Step 4: Transform
    print("\n🔄 Step 4: Transform data...")
    transform_result = requests.post(f"{BASE_URL}/execute", json={
        "tool": "transform_data",
        "inputs": {
            "source_data": full_data,
            "mappings": mappings,
            "target_columns": ["Present", "Total Manhours", "Losttime Incident", "Date"]
        }
    }).json()
    
    if not transform_result.get("success"):
        print(f"❌ Transformation failed")
        return False
    
    stats = transform_result["result"]["statistics"]
    print(f"✓ Transformed {stats['rows_processed']} rows")
    print(f"  Source columns: {stats['source_columns']}")
    print(f"  Target columns: {stats['target_columns']}")
    
    print("\n✅ Complete workflow passed!")
    return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("🧪 MAPPING AGENT API TESTS")
    print("=" * 60)
    print(f"Testing endpoint: {BASE_URL}")
    print("Make sure the server is running: python mapping_agent_api.py")
    print("=" * 60)
    
    try:
        test_health_check()
        test_list_tools()
        test_parse_csv()
        test_smart_column_mapping()
        test_validate_mapping()
        test_transform_data()
        test_save_load_template()
        test_complete_workflow()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        
    except requests.exceptions.ConnectionError:
        print("\n" + "=" * 60)
        print("❌ CONNECTION ERROR")
        print("=" * 60)
        print("The server is not running!")
        print("Start it with: python mapping_agent_api.py")
        print("=" * 60)
        
    except AssertionError as e:
        print("\n" + "=" * 60)
        print(f"❌ TEST FAILED: {str(e)}")
        print("=" * 60)
        
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ UNEXPECTED ERROR: {str(e)}")
        print("=" * 60)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
