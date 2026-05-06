"""
SafexpressOps Target Columns for Smart Mapping
Updated with SIMPLIFIED column names (no \n newlines)
Total: 147 columns (4 temporal + 143 operational)
"""

# Temporal columns (for reference/matching only - already in Google Sheets)
TEMPORAL_COLUMNS = ["Wee", "Week", "Date", "Day"]

# ============================================================
# RED COLUMNS - Original operational columns (E to T)
# ============================================================
RED_OPERATIONAL_COLUMNS = [
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
]

# ============================================================
# BLUE COLUMNS - INPUT columns (U to CG)
# ============================================================
BLUE_INPUT_COLUMNS = [
    # Inbound/Receiving (U-AU: 16 columns)
    "No. of CV Received",
    "No. of Truck Received",
    "No. of Pick up",
    "No. of Pallet Received",
    "Expected Receiving Qty",
    "Discrepancy Qty Inbound",  # ✅ UPDATED: was "Discrepancy Qty\n(+ Overlanded)\n(- Short)"
    "Total Pallet Put-Away",
    "Put-Away Total Hrs",
    "Units Received Fast Unloading HIT",  # ✅ UPDATED: was "Units Received w/ <=2hrs AVE Unloading time\n(HIT)"
    "Units Received Slow Unloading MISS",  # ✅ UPDATED: was "Units Received exceeding 2hrs AVE Unloading time\n(MISS)"
    "Units Received Correct Qty HIT",  # ✅ UPDATED: was "Units Received with Correct Qty\n(HIT)"
    "Units Received Discrepancy Qty MISS",  # ✅ UPDATED: was "Units Received with Discrepancy Qty\n(MISS)"
    "Ave. Unloading Time",
    "Ave. Inbound Dwell Time",
    "Demurage Lead Time (HIT)",
    "Demurage Lead Time (MISS)",
    # Outbound/Dispatching (AV-BE: 8 columns)
    "No. of Truck Dispatched",
    "No. of Pallet Dispatched",
    "Expected Dispatched Qty",
    "Discrepancy Qty Outbound",  # ✅ UPDATED: was "Discrepancy Qty\n(+ Overlanded)\n(- Short).1"
    "Units Dispatched Fast Loading HIT",  # ✅ UPDATED: was "Units Dispatched w/ <=2hrs AVE Loading time\n(HIT)"
    "Units Dispatched Slow Loading MISS",  # ✅ UPDATED: was "Units Dispatched exceeding 2hrs AVE Loading time\n(MISS)"
    "Units Loaded Correct Qty HIT",  # ✅ UPDATED: was "Units Loaded with Correct Qty\n(HIT)"
    "Units Loaded Discrepancy Qty MISS",  # ✅ UPDATED: was "Units Loaded with Discrepancy Qty\n(MISS)"
    # Picking & Checking (BI-BS: 6 columns)
    "Ave Picked Qty Per Hr",
    "Ave Picking Time",
    "Ave. Checking Time",
    "Ave Chcked Qty Per Hr",
    "Ave. Loading Time",
    "Ave. Outbound Dwell Time",
    # Logistics & Trucks (BU-BZ: 5 columns)
    "CWO Distributor OTD",
    "Booked Truck",
    "Actual Arrived",
    "Truck Utilization",
    "Load Availability",
    # Financial (CA-CB: 2 columns)
    "Sales Invoice Amt",
    "Actual Delivery Expenses",
    # Compliance & MHE (CD-CF: 3 columns)
    "Dispatch Compliance",
    "Total Number of MHE",
    "Total Units Well-Working (24-Hrs + Not 24-Hrs)",
]

# ============================================================
# BLUE CALCULATED COLUMNS (have formulas - DO NOT MAP)
# ============================================================
BLUE_CALCULATED_COLUMNS = [
    "Total Trucks+CV Received",  # W: =sum(U2:V2)
    "Actual Received Qty",  # AB: =if(AA2<0,Z2-abs(AA2),Z2+AA2)
    "Put-Away Total Hrs (Whole #)",  # AE: Time to decimal
    "Put-Away Pallet per Manhour",  # AF: =iferror(Y2/AE2,0)
    "Put-away Perf. %",  # AG: =iferror(AF2/20,"")
    "TOTAL HIT in Receiveing Time",  # AJ: =AH2
    "TOTAL HIT in Completeness",  # AM: =AK2
    "INBOUND HIT",  # AN: =iferror(AVERAGE(AJ2,AM2),0)
    "INBOUND OTIF",  # AO: =IFERROR(AN2/W2,0)
    "Ave. Unloading Time (Whole #)",  # AQ: Time to decimal
    "Ave. Inbound Dwell Time (Whole #)",  # AS: Time to decimal
    "Actual Dispatched Qty",  # AZ: =if(AY2<0,AX2-abs(AY2),AX2+AY2)
    "TOTAL HIT in Loading Time",  # BC: =BA2
    "TOTAL HIT Completeness Outbound",  # BF: ✅ UPDATED: was "TOTAL HIT in Completeness\n(Outbound)"
    "OUTBOUND HIT",  # BG: =iferror(AVERAGE(BC2,BF2),0)
    "OUTBOUND OTIF",  # BH: =IFERROR(BG2/AV2,0)
    "Ave Picking Time Whole",  # BK: ✅ UPDATED: was "Ave Picking Time \n(WHOLE #)"
    "Picking Performance",  # BL: =IFERROR(BI2/DG2/BK2,0)
    "Ave. Checking Time (WHOLE #)",  # BN: Time to decimal
    "Checking Performance",  # BP: =iferror(BO2/DG2/BN2,0)
    "Ave. Loading Time (WHOLE #)",  # BR: Time to decimal
    "Ave. Outbound Dwell Time (Whole #)",  # BT: Time to decimal
    "Truck Availability",  # BX: =iferror(BW2/BV2,0)
    "CTS %",  # CC: =iferror(CB2/CA2,0)
    "MHE Uptime %",  # CG: IMPORTRANGE formula
]

# ============================================================
# YELLOW COLUMNS - Inventory & Expenses (CH to CV)
# ============================================================
YELLOW_INPUT_COLUMNS = [
    # Inventory (4 columns)
    "Total Stock On-Hand",
    "Good Pallet Inventory",
    "Damaged Pallet Inventory",
    "Whse Damaged Pallet Cost",
    # Overtime (2 columns)
    "Charged to SLI OT",
    "Charged to Client OT",
    # Expenses (6 columns)
    "LPG Expenses",
    "Diesel Expenses",
    "Cost to Sales",
    "Office Supplies",
    "Meals Expenses",
    "Other Expenses",
    "Warehouse Damage Incident Cost",
]

YELLOW_CALCULATED_COLUMNS = [
    "Total Overtime (Hours)",  # CN: =SUM(CL2:CM2)
    "Total Expenses",  # CU: =sum(CO2:CT2)
]

# ============================================================
# PURPLE COLUMNS - Documents & Manpower (CW to DJ)
# ============================================================
PURPLE_INPUT_COLUMNS = [
    # POD/Documents (6 columns)
    "Returned POD",
    "Unreturned POD",
    "Return Performance",
    "Transmitted to Client",
    "Not yet Transmitted",
    "Trasmitted Perfromance",  # Note: Typo exists in actual sheet
    # Manpower (5 columns)
    "Manpower Matrix",
    "Deployed",
    "Planned Head to Work",
    "Present",
    "Late Incident",
]

PURPLE_CALCULATED_COLUMNS = [
    "Manpower Fill-rate",  # DE: =iferror(DD2/DC2,0)
    "Attendance Perf %",  # DH: =IFERROR(DG2/DF2,0)
    "Timeliness Perf. %",  # DJ: =IFERROR((DG2-DI2)/DG2,0)
]

# ============================================================
# COMBINED LISTS
# ============================================================

# All operational columns (RED + BLUE + YELLOW + PURPLE)
OPERATIONAL_COLUMNS = (
    RED_OPERATIONAL_COLUMNS
    + BLUE_INPUT_COLUMNS
    + BLUE_CALCULATED_COLUMNS
    + YELLOW_INPUT_COLUMNS
    + YELLOW_CALCULATED_COLUMNS
    + PURPLE_INPUT_COLUMNS
    + PURPLE_CALCULATED_COLUMNS
)

# All columns including temporal
SAFEXPRESSOPS_TARGET_COLUMNS = TEMPORAL_COLUMNS + OPERATIONAL_COLUMNS

# Only operational (excludes temporal)
SAFEXPRESSOPS_OPERATIONAL_ONLY = OPERATIONAL_COLUMNS

# ============================================================
# CALCULATED COLUMNS (RED + BLUE + YELLOW + PURPLE with formulas)
# ============================================================
RED_CALCULATED_COLUMNS = [
    # Safety (5)
    "Total Manhours",
    "Safe man-hours",
    "No Lost Time Incident Rate",
    "Days Without Lost Time Incident",
    "Cummulative Days Without Lost Time Incident",
    # Warehouse (2)
    "WH QA Incident",
    "Space Utilization",
]

# Combine all calculated columns
CALCULATED_COLUMNS = (
    RED_CALCULATED_COLUMNS
    + BLUE_CALCULATED_COLUMNS
    + YELLOW_CALCULATED_COLUMNS
    + PURPLE_CALCULATED_COLUMNS
)

# ============================================================
# INPUT COLUMNS (can be mapped from Excel)
# ============================================================
INPUT_COLUMNS = [col for col in OPERATIONAL_COLUMNS if col not in CALCULATED_COLUMNS]

# ============================================================
# HELPER FUNCTIONS
# ============================================================


def is_calculated_column(column_name: str) -> bool:
    """Check if column has a formula"""
    return column_name in CALCULATED_COLUMNS


def is_input_column(column_name: str) -> bool:
    """Check if column needs input data"""
    return column_name in INPUT_COLUMNS


def get_mappable_columns() -> list:
    """Get columns that should be mapped from source data"""
    return INPUT_COLUMNS.copy()


# Alias for backwards compatibility
SAFEXPRESSOPS_MAPPABLE_COLUMNS = INPUT_COLUMNS

# ============================================================
# STATISTICS
# ============================================================

if __name__ == "__main__":
    print("📊 SafExpressOps Target Columns (UPDATED - Simplified Names)")
    print("=" * 60)
    print(f"Total columns:            {len(SAFEXPRESSOPS_TARGET_COLUMNS)}")
    print(f"  - Temporal:             {len(TEMPORAL_COLUMNS)}")
    print(f"  - RED Operational:      {len(RED_OPERATIONAL_COLUMNS)}")
    print(f"  - BLUE INPUT:           {len(BLUE_INPUT_COLUMNS)}")
    print(f"  - BLUE CALCULATED:      {len(BLUE_CALCULATED_COLUMNS)}")
    print(f"  - YELLOW INPUT:         {len(YELLOW_INPUT_COLUMNS)}")
    print(f"  - YELLOW CALCULATED:    {len(YELLOW_CALCULATED_COLUMNS)}")
    print(f"  - PURPLE INPUT:         {len(PURPLE_INPUT_COLUMNS)}")
    print(f"  - PURPLE CALCULATED:    {len(PURPLE_CALCULATED_COLUMNS)}")
    print()
    print(f"Mappable INPUT columns:   {len(INPUT_COLUMNS)}")
    print(
        f"  - RED INPUT:            {len([c for c in RED_OPERATIONAL_COLUMNS if c in INPUT_COLUMNS])}"
    )
    print(f"  - BLUE INPUT:           {len(BLUE_INPUT_COLUMNS)}")
    print(f"  - YELLOW INPUT:         {len(YELLOW_INPUT_COLUMNS)}")
    print(f"  - PURPLE INPUT:         {len(PURPLE_INPUT_COLUMNS)}")
    print()
    print(f"Protected CALCULATED:     {len(CALCULATED_COLUMNS)}")
    print(f"  - RED CALCULATED:       {len(RED_CALCULATED_COLUMNS)}")
    print(f"  - BLUE CALCULATED:      {len(BLUE_CALCULATED_COLUMNS)}")
    print(f"  - YELLOW CALCULATED:    {len(YELLOW_CALCULATED_COLUMNS)}")
    print(f"  - PURPLE CALCULATED:    {len(PURPLE_CALCULATED_COLUMNS)}")
    print("=" * 60)

    # Verify totals
    assert len(INPUT_COLUMNS) + len(CALCULATED_COLUMNS) == len(OPERATIONAL_COLUMNS)
    print("✅ All columns accounted for!")

    print("\n📝 UPDATED Column Names:")
    print("-" * 60)
    print("✅ Units Received Fast Unloading HIT")
    print("✅ Units Received Slow Unloading MISS")
    print("✅ Units Received Correct Qty HIT")
    print("✅ Units Received Discrepancy Qty MISS")
    print("✅ Units Dispatched Fast Loading HIT")
    print("✅ Units Dispatched Slow Loading MISS")
    print("✅ Units Loaded Correct Qty HIT")
    print("✅ Units Loaded Discrepancy Qty MISS")
    print("✅ Discrepancy Qty Inbound")
    print("✅ Discrepancy Qty Outbound")
    print("✅ TOTAL HIT Completeness Outbound")
    print("✅ Ave Picking Time Whole")
