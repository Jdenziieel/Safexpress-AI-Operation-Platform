"""
Test script to verify the context manager truncation fix
"""

from services.context_manager import ContextManager

def test_kpi_chunk():
    """Test that the KPI chunk is not truncated prematurely"""
    
    # Simulate the KPI chunk that was being truncated
    kpi_text = """KPI | Core Value | Definition and Expectation

Safety | Accountability | Measures the effectiveness of workplace safety protocols, aiming for zero accidents and injuries. Protect yourself, your colleagues, the cargo, and company assets.

Quality | Excellence | Assesses the quality of services by tracking defect rates, customer complaints, and adherence to quality standards. This includes ensuring 100% inventory record accuracy.

Delivery | Reliability | Evaluates the efficiency and reliability of the delivery process. Commit to timely and accurate deliveries that meet client deadlines.

Cost | Efficiency | Monitors cost efficiency in operations, focusing on reducing waste and optimizing resource usage (time, fuel, supplies, etc.).

Morale | Teamwork | Gauges employee satisfaction and engagement. We recognize that a motivated, professional, and engaged workforce is essential for high performance and a client-focused environment."""
    
    chunk = {
        'document_name': 'Company-Manual.pdf',
        'page': 2.0,
        'text': kpi_text,
        'chunk_type': 'table',
        'section': 'KPIs',
        'metadata': {
            'context': 'Company Key Performance Indicators',
            'tags': ['kpi', 'metrics', 'performance']
        },
        'score': 0.95
    }
    
    # Test with old limit (500 chars) - would have truncated
    print("=" * 80)
    print("Testing KPI Chunk Processing")
    print("=" * 80)
    print(f"\nOriginal chunk length: {len(kpi_text)} characters")
    print(f"Contains 'Cost': {'Cost' in kpi_text}")
    print(f"Contains 'Morale': {'Morale' in kpi_text}")
    
    # Build context
    context_manager = ContextManager()
    context = context_manager.build_kb_context([chunk])
    
    print(f"\n{'=' * 80}")
    print("Generated Context:")
    print("=" * 80)
    print(context)
    
    # Verify all KPIs are present
    print(f"\n{'=' * 80}")
    print("Verification Results:")
    print("=" * 80)
    
    kpis = ['Safety', 'Quality', 'Delivery', 'Cost', 'Morale']
    all_present = True
    
    for kpi in kpis:
        present = kpi in context
        status = "✓ FOUND" if present else "✗ MISSING"
        print(f"{kpi:12} - {status}")
        if not present:
            all_present = False
    
    print(f"\n{'=' * 80}")
    if all_present:
        print("✅ SUCCESS: All KPIs preserved in context!")
    else:
        print("❌ FAILURE: Some KPIs are missing from context")
    print("=" * 80)
    
    return all_present


def test_long_table():
    """Test that long tables are split appropriately"""
    
    # Create a long table
    table_text = "Product | Price | Stock\n" + "-" * 30 + "\n"
    for i in range(20):
        table_text += f"Product {i+1} | ${(i+1)*10} | {(i+1)*5} units\n"
    
    chunk = {
        'document_name': 'Inventory.pdf',
        'page': 1,
        'text': table_text,
        'chunk_type': 'table',
        'metadata': {'context': 'Product inventory'}
    }
    
    print("\n" + "=" * 80)
    print("Testing Long Table Splitting")
    print("=" * 80)
    print(f"Original table length: {len(table_text)} characters")
    print(f"Number of product rows: 20")
    
    context_manager = ContextManager()
    context = context_manager.build_kb_context([chunk])
    
    # Count how many sources were generated (split chunks)
    source_count = context.count('[Source')
    
    print(f"\nTable was split into {source_count} parts")
    print(f"\nGenerated context length: {len(context)} characters")
    
    # Verify all products are present
    missing_products = []
    for i in range(20):
        if f"Product {i+1}" not in context:
            missing_products.append(i+1)
    
    if missing_products:
        print(f"\n❌ Missing products: {missing_products}")
    else:
        print("\n✅ All 20 products preserved in context")
    
    return len(missing_products) == 0


def test_smart_truncation():
    """Test that regular text is smartly truncated"""
    
    long_text = """This is the first paragraph with important information about our company's mission and values.

This is the second paragraph that discusses our strategic goals for the upcoming year. We aim to expand our market presence and improve customer satisfaction.

This is the third paragraph covering our operational excellence initiatives. We focus on efficiency, quality, and continuous improvement.

This is the fourth paragraph about employee development and training programs. We believe in investing in our people.

This is the fifth paragraph discussing sustainability and corporate responsibility. We are committed to environmental stewardship."""
    
    chunk = {
        'document_name': 'Strategic-Plan.pdf',
        'page': 5,
        'text': long_text,
        'chunk_type': 'paragraph',
        'metadata': {}
    }
    
    print("\n" + "=" * 80)
    print("Testing Smart Truncation")
    print("=" * 80)
    print(f"Original text length: {len(long_text)} characters")
    
    context_manager = ContextManager()
    context = context_manager.build_kb_context([chunk])
    
    print(f"Context length: {len(context)} characters")
    
    # Check if truncated at sentence boundary
    if "[Content continues...]" in context:
        print("\n✅ Text was smartly truncated at sentence boundary")
        # Find where it was cut
        before_marker = context.split("[Content continues...]")[0]
        print(f"Preserved: {len(before_marker)} characters")
    elif "..." in context:
        print("\n⚠️ Text was truncated with fallback method")
    else:
        print("\n✓ Text was short enough, no truncation needed")
    
    print("\nContext preview:")
    print(context[:500] + "..." if len(context) > 500 else context)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("CONTEXT MANAGER FIX VERIFICATION TEST")
    print("=" * 80)
    
    # Run tests
    test1_pass = test_kpi_chunk()
    test2_pass = test_long_table()
    test_smart_truncation()
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"KPI Preservation Test: {'✅ PASSED' if test1_pass else '❌ FAILED'}")
    print(f"Long Table Split Test: {'✅ PASSED' if test2_pass else '❌ FAILED'}")
    print("=" * 80)
    
    if test1_pass and test2_pass:
        print("\n🎉 All critical tests passed! The fix is working correctly.")
    else:
        print("\n⚠️ Some tests failed. Please review the implementation.")
