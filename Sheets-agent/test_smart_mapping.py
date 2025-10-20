"""
test_smart_mapping.py - Test your smart mapping locally
"""

import pandas as pd
from smart_mapping_engine import SmartMappingEngine


def test_with_safexpressops_data():
    """Test smart mapping with realistic SafExpressOps data"""

    print("🧪 Testing Smart Mapping with SafExpressOps-style data...")

    # Create realistic test data
    test_data = pd.DataFrame(
        {
            "Date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "Man Hours": [120, 115, 130],
            "Safety Incidents": [0, 1, 0],
            "Staff Present": [25, 23, 26],
            "CV Count": [15, 18, 12],
            "Pick Rate": [95.2, 98.1, 92.8],
        }
    )

    # SafExpressOps target columns
    safexpressops_targets = [
        "Date",
        "Week",
        "Day",
        "Total Manhours",
        "Safe man-hours",
        "Losttime Incident",
        "Days Without Lost Time Incident",
        "Present",
        "No. of CV Received",
        "Ave Picked Qty Per Hr",
        "CTS %",
    ]

    # Test the smart mapping
    engine = SmartMappingEngine()
    result = engine.smart_map_columns(
        source_columns=test_data.columns.tolist(),
        target_columns=safexpressops_targets,
        sample_data=test_data,
    )

    # Show results
    print(f"\n📊 SMART MAPPING RESULTS:")
    print(f"Overall Accuracy: {result['summary']['accuracy_estimate']:.1%}")
    print(
        f"High Confidence: {result['summary']['high_confidence_mappings']}/{result['summary']['total_columns']}"
    )

    print(f"\n📋 DETAILED MAPPINGS:")
    for source, mapping_info in result["mappings"].items():
        target = mapping_info["target"] or "UNMAPPED"
        confidence = mapping_info["confidence_score"]
        level = mapping_info["confidence_level"]

        status = "✅" if level == "high" else "⚠️" if level == "medium" else "❌"
        print(f"{status} {source:20} → {target:25} ({confidence:.2f})")

    return result


if __name__ == "__main__":
    test_with_safexpressops_data()
