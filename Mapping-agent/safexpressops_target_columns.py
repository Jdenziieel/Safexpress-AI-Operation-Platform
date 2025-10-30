"""
SafExpressOps Target Columns for Smart Mapping
Extracted from COPY_OPR.xlsx - DATA ENTRY sheet
Excludes temporal columns: Wee, Week, Date, Day
Total: 110 operational columns
"""

# Temporal columns (for reference/matching only - already in Google Sheets)
TEMPORAL_COLUMNS = ["Wee", "Week", "Date", "Day"]

OPERATIONAL_COLUMNS = [
    # Safety Metrics (11 columns)
    "Total Manhours",
    "Safe man-hours",
    "No Lost Time Incident Rate",
    "Cummulative Safe manhours",
    "Losttime Incident",
    "Days Without Lost Time Incident",
    "Cummulative Days Without Lost Time Incident",
    "Cycle Count Accuracy",
    "Warehouse Damage Incident",
    "FEFO Incident",
    "Expired Product Incident",
    # Warehouse Quality (5 columns)
    "Damaged from CV",
    "WH QA Incident",
    "Whse Capacity",
    "Space Utilized",
    "Space Utilization",
    # Inbound Operations (23 columns)
    "No. of CV Received",
    "No. of Truck Received",
    "Total Trucks+CV Received",
    "No. of Pick up",
    "No. of Pallet Received",
    "Expected Receiving Qty",
    "Discrepancy Qty\n(+ Overlanded)\n(- Short)",
    "Actual Received Qty",
    "Total Pallet Put-Away",
    "Put-Away Total Hrs",
    "Put-Away Total Hrs (Whole #)",
    "Put-Away Pallet per Manhour",
    "Put-away Perf. %",
    "Units Received w/ <=2hrs AVE Unloading time\n(HIT)",
    "Units Received exceeding 2hrs AVE Unloading time\n(MISS)",
    "TOTAL HIT in Receiveing Time",
    "Units Received with Correct Qty\n(HIT)",
    "Units Received with Discrepancy Qty\n(MISS)",
    "TOTAL HIT in Completeness",
    "INBOUND HIT",
    "INBOUND OTIF",
    "Ave. Unloading Time",
    "Ave. Unloading Time (Whole #)",
    "Ave. Inbound Dwell Time",
    "Ave. Inbound Dwell Time (Whole #)",
    "Demurage Lead Time (HIT)",
    "Demurage Lead Time (MISS)",
    # Outbound Operations (26 columns)
    "No. of Truck Dispatched",
    "No. of Pallet Dispatched",
    "Expected Dispatched Qty",
    "Discrepancy Qty\n(+ Overlanded)\n(- Short).1",
    "Actual Dispatched Qty",
    "Units Dispatched w/ <=2hrs AVE Loading time\n(HIT)",
    "Units Dispatched exceeding 2hrs AVE Loading time\n(MISS)",
    "TOTAL HIT in Loading Time",
    "Units Loaded with Correct Qty\n(HIT)",
    "Units Loaded with Discrepancy Qty\n(MISS)",
    "TOTAL HIT in Completeness\n(Outbound)",
    "OUTBOUND HIT",
    "OUTBOUND OTIF",
    "Ave Picked Qty Per Hr",
    "Ave Picking Time",
    "Ave Picking Time \n(WHOLE #)",
    "Picking Performance",
    "Ave. Checking Time",
    "Ave. Checking Time (WHOLE #)",
    "Ave Chcked Qty Per Hr",
    "Checking Performance",
    "Ave. Loading Time",
    "Ave. Loading Time (WHOLE #)",
    "Ave. Outbound Dwell Time",
    "Ave. Outbound Dwell Time (Whole #)",
    "CWO Distributor OTD",
    # Logistics (7 columns)
    "Booked Truck",
    "Actual Arrived",
    "Truck Availability",
    "Truck Utilization",
    "Load Availability",
    "Sales Invoice Amt",
    "Actual Delivery Expenses",
    # Customer Service (2 columns)
    "CTS %",
    "Dispatch Compliance",
    # Equipment (3 columns)
    "Total Number of MHE",
    "Total Units Well-Working (24-Hrs + Not 24-Hrs)",
    "MHE Uptime %",
    # Inventory (4 columns)
    "Total Stock On-Hand",
    "Good Pallet Inventory",
    "Damaged Pallet Inventory",
    "Whse Damaged Pallet Cost",
    # Expenses (10 columns)
    "Charged to SLI OT",
    "Charged to Client OT",
    "Total Overtime (Hours)",
    "LPG Expenses",
    "Diesel Expenses",
    "Cost to Sales",
    "Office Supplies",
    "Meals Expenses",
    "Other Expenses",
    "Total Expenses",
    "Warehouse Damage Incident Cost",
    # Document Management (6 columns)
    "Returned POD",
    "Unreturned POD",
    "Return Performance",
    "Transmitted to Client",
    "Not yet Transmitted",
    "Trasmitted Perfromance",
    # Manpower (8 columns)
    "Manpower Matrix",
    "Deployed",
    "Manpower Fill-rate",
    "Planned Head to Work",
    "Present",
    "Attendance Perf %",
    "Late Incident",
    "Timeliness Perf. %",
]

# Grouped by business domain for easier understanding
SAFEXPRESSOPS_BY_DOMAIN = {
    "safety": [
        "Total Manhours",
        "Safe man-hours",
        "No Lost Time Incident Rate",
        "Cummulative Safe manhours",
        "Losttime Incident",
        "Days Without Lost Time Incident",
        "Cummulative Days Without Lost Time Incident",
    ],
    "quality": [
        "Cycle Count Accuracy",
        "Warehouse Damage Incident",
        "FEFO Incident",
        "Expired Product Incident",
        "Damaged from CV",
        "WH QA Incident",
        "CTS %",
    ],
    "warehouse": [
        "Whse Capacity",
        "Space Utilized",
        "Space Utilization",
        "No. of CV Received",
        "No. of Truck Received",
        "Total Trucks+CV Received",
        "No. of Pick up",
    ],
    "inbound": [
        "No. of Pallet Received",
        "Expected Receiving Qty",
        "Actual Received Qty",
        "INBOUND HIT",
        "INBOUND OTIF",
        "Ave. Unloading Time",
        "Ave. Inbound Dwell Time",
    ],
    "outbound": [
        "No. of Truck Dispatched",
        "No. of Pallet Dispatched",
        "Expected Dispatched Qty",
        "Actual Dispatched Qty",
        "OUTBOUND HIT",
        "OUTBOUND OTIF",
        "Ave Picked Qty Per Hr",
        "Ave. Loading Time",
        "Ave. Outbound Dwell Time",
    ],
    "manpower": [
        "Manpower Matrix",
        "Deployed",
        "Manpower Fill-rate",
        "Planned Head to Work",
        "Present",
        "Attendance Perf %",
        "Late Incident",
        "Timeliness Perf. %",
    ],
    "inventory": [
        "Total Stock On-Hand",
        "Good Pallet Inventory",
        "Damaged Pallet Inventory",
        "Whse Damaged Pallet Cost",
    ],
    "expenses": [
        "Charged to SLI OT",
        "Charged to Client OT",
        "Total Overtime (Hours)",
        "LPG Expenses",
        "Diesel Expenses",
        "Cost to Sales",
        "Office Supplies",
        "Meals Expenses",
        "Other Expenses",
        "Total Expenses",
        "Warehouse Damage Incident Cost",
    ],
}

# Data type hints for validation
COLUMN_DATA_TYPES = {
    # Numeric - Integer counts
    "Total Manhours": "integer",
    "Safe man-hours": "integer",
    "Losttime Incident": "integer",
    "Days Without Lost Time Incident": "integer",
    "No. of CV Received": "integer",
    "No. of Truck Received": "integer",
    "Present": "integer",
    # Numeric - Float percentages (0-1 or 0-100)
    "Cycle Count Accuracy": "percentage",
    "CTS %": "percentage",
    "Attendance Perf %": "percentage",
    "Space Utilization": "percentage",
    "INBOUND OTIF": "percentage",
    "OUTBOUND OTIF": "percentage",
    # Numeric - Float rates
    "Ave Picked Qty Per Hr": "rate",
    "Put-Away Pallet per Manhour": "rate",
    # Numeric - Currency
    "Sales Invoice Amt": "currency",
    "Actual Delivery Expenses": "currency",
    "LPG Expenses": "currency",
    "Diesel Expenses": "currency",
    # Time duration
    "Ave. Unloading Time": "time",
    "Ave. Loading Time": "time",
    "Ave. Inbound Dwell Time": "time",
    "Ave. Outbound Dwell Time": "time",
}

# Value ranges for validation
COLUMN_VALUE_RANGES = {
    "Total Manhours": (0, 500),  # Typical daily manhours
    "Losttime Incident": (0, 5),  # Safety incidents (low is good)
    "Cycle Count Accuracy": (0.8, 1.0),  # Should be high (80-100%)
    "CTS %": (0.8, 1.0),  # Customer satisfaction (high)
    "Present": (0, 50),  # Number of people
    "INBOUND OTIF": (0.7, 1.0),  # On-time in-full metric
    "OUTBOUND OTIF": (0.7, 1.0),  # On-time in-full metric
}

SAFEXPRESSOPS_TARGET_COLUMNS = TEMPORAL_COLUMNS + OPERATIONAL_COLUMNS

SAFEXPRESSOPS_OPERATIONAL_ONLY = OPERATIONAL_COLUMNS

if __name__ == "__main__":
    print(f"📊 SafExpressOps Target Columns")
    print(f"   Total columns: {len(SAFEXPRESSOPS_TARGET_COLUMNS)}")
    print(f"\n🏢 Columns by Domain:")
    for domain, cols in SAFEXPRESSOPS_BY_DOMAIN.items():
        print(f"   • {domain.upper()}: {len(cols)} columns")

    print(f"\n📋 Sample columns:")
    for i, col in enumerate(SAFEXPRESSOPS_TARGET_COLUMNS[:10], 1):
        print(f"   {i}. {col}")
    print(f"   ...")
