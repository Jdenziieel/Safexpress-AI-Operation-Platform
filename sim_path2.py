"""Quick simulation: verify _detect_sections_single_pass with Path 2 detection."""
import sys
sys.path.insert(0, r'c:\Users\Denz\Documents\tigers\Ai-Agents\safexpressops-mapping-agent-287212a2-db05-452d-8bd4-54af56d985d4')

from mapping_agent_api import _detect_sections_single_pass, _detect_sections


def show(label, sections):
    print(f"\n=== {label} ===")
    print(f"  count: {len(sections)}")
    for i, s in enumerate(sections):
        print(f"  #{i}: title={s['title']!r}, header_row={s['header_row']}, data={s['data_start']}..{s['data_end']}, headers={s['headers']}")


# A. User's Outbound Metrics tab structure
outbound_tab = [
    ['Date', 'Dispatched', 'Cases'],
    ['2025-05-01', 3, 60],
    ['2025-05-02', 6, 120],
    [None, None, None],
    [None, None, None],
    ['Inbound Metrics', None, None],
    ['Date', 'Trucks', 'Pallets'],
    ['11/03/2025', 200, 50],
    ['12/03/2025', 100, 10],
]
show("A1. Outbound tab via _detect_sections (titled-only, requires >=2)", _detect_sections(outbound_tab))
show("A2. Outbound tab via _detect_sections_single_pass (Path 1 + Path 2)", _detect_sections_single_pass(outbound_tab))

# B. Flat tab ? no titles
flat_tab = [
    ['Date', 'Trucks', 'Pallets'],
    ['2025-03-01', 5, 100],
    ['2025-03-02', 4, 80],
]
show("B. Flat tab via _detect_sections_single_pass (should be 1 section)", _detect_sections_single_pass(flat_tab))

# C. Both titled
both_titled = [
    ['Inbound Metrics', None, None],
    ['Date', 'Trucks', 'Pallets'],
    ['2025-03-01', 5, 100],
    [None, None, None],
    ['Outbound Metrics', None, None],
    ['Date', 'Dispatched', 'Cases'],
    ['2025-05-01', 3, 60],
]
show("C. Both titled (should find 2 via Path 1 only)", _detect_sections_single_pass(both_titled))

# D. Date-first tab ? must NOT trigger Path 2
date_first = [
    ['2025-03-01', 5, 100],
    ['2025-03-02', 4, 80],
]
show("D. Date-first tab ? Path 2 must NOT trigger", _detect_sections_single_pass(date_first))
