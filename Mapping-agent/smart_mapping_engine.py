import pandas as pd
import re
from typing import Dict, List, Any, Tuple
import numpy as np


class SmartMappingEngine:
    """
    smart column mapping engine - uses 5 AI signals for intelligent mapping
    """

    def __init__(self):
        # Import the actual SafExpressOps columns
        from safexpressops_target_columns import SAFEXPRESSOPS_TARGET_COLUMNS

        # Store the full list
        self.all_target_columns = SAFEXPRESSOPS_TARGET_COLUMNS

        # SafexpressOps operational terms - business language
        self.operational_vocabulary = {
            # safety domain
            "safety": {
                "keywords": [
                    "safety",
                    "incident",
                    "accident",
                    "injury",
                    "lost",
                    "time",
                    "manhour",
                    "hour",
                ],
                # ✅ FIXED: Use actual column names from the list
                "target_columns": [
                    col
                    for col in SAFEXPRESSOPS_TARGET_COLUMNS
                    if any(
                        kw in col.lower()
                        for kw in ["manhour", "safe", "incident", "lost time"]
                    )
                ],
            },
            # warehouse domain
            "warehouse": {
                "keywords": [
                    "warehouse",
                    "cv",
                    "container",
                    "vessel",
                    "pick",
                    "cycle",
                    "count",
                    "damage",
                    "fefo",
                ],
                # ✅ FIXED: Use actual column names
                "target_columns": [
                    col
                    for col in SAFEXPRESSOPS_TARGET_COLUMNS
                    if any(
                        kw in col.lower()
                        for kw in [
                            "cv received",
                            "picked qty",
                            "cycle count",
                            "warehouse damage",
                            "fefo",
                        ]
                    )
                ],
            },
            # quality domain
            "quality": {
                "keywords": [
                    "quality",
                    "accuracy",
                    "error",
                    "defect",
                    "cts",
                    "customer",
                    "satisfaction",
                ],
                # ✅ FIXED: Use actual column names
                "target_columns": [
                    col
                    for col in SAFEXPRESSOPS_TARGET_COLUMNS
                    if any(
                        kw in col.lower()
                        for kw in ["cts", "accuracy", "expired", "quality"]
                    )
                ],
            },
            # Attendance Domain
            "attendance": {
                "keywords": [
                    "present",
                    "attendance",
                    "staff",
                    "employee",
                    "people",
                    "worker",
                    "deployed",
                    "manpower",
                ],
                # ✅ FIXED: Use actual column names
                "target_columns": [
                    col
                    for col in SAFEXPRESSOPS_TARGET_COLUMNS
                    if any(
                        kw in col.lower()
                        for kw in [
                            "present",
                            "attendance",
                            "deployed",
                            "manpower",
                            "late",
                        ]
                    )
                ],
            },
        }

        # Common operational abbreviations - expand these automatically
        self.abbreviation_expansion = {
            "cv": "container vessel",
            "otif": "on time in full",
            "cts": "customer satisfaction",
            "fefo": "first expired first out",
            "hrs": "hours",
            "hours": "manhours",
            "hr": "hours",
            "qty": "quantity",
            "ave": "average",
            "avg": "average",
            "pct": "percent",
            "acc": "accuracy",
        }

    def smart_map_columns(
        self,
        source_columns: Any,
        target_columns: List[str],
        sample_data: pd.DataFrame = None,
    ) -> Dict[str, str]:
        """
        Main function: intelligently map source columns to target columns

        Args:
            source_columns: Columns from uploaded file ["Date", "Man  Hours", "Safety Score"]
            target_columns: Your SafexpressOps columns ["Date", "Total ManHours", "Losttime Incident"]
            sample_data: Sample of the actual data to analyze

        Returns:
            Dictionary mapping source to target columns
        """

        print("🧠 Smart Mapping Engine starting...")

        # step 1: Basic semantic mapping
        semantic_mappings = self._semantic_mapping(source_columns, target_columns)

        # step 2: Analyze actual data patterns if sample data is provided
        if sample_data is not None:
            data_insights = self._analyze_data_patterns(source_columns, sample_data)
            # Boost confidence based on data analysis
            semantic_mappings = self._apply_data_insights(
                semantic_mappings, data_insights, target_columns
            )

        # step 3: apply business domain knowledge
        final_mappings = self._apply_business_rules(
            semantic_mappings, source_columns, target_columns
        )

        return final_mappings

    def _semantic_mapping(
        self, source_cols: List[str], target_cols: List[str]
    ) -> Dict[str, Dict[str, float]]:
        """
        Step !: Better than simple string matching - understands meaning
        """

        mappings = {}

        for source_col in source_cols:
            mappings[source_col] = {}

            # clean and expand the souurce column name
            source_clean = self._clean_and_expand(source_col)

            for target_col in target_cols:
                target_clean = self._clean_and_expand(target_col)

                # calculate semantic similarity
                similarity = self._calculate_semantic_similarity(
                    source_clean, target_clean
                )
                mappings[source_col][target_col] = similarity

        return mappings

    def _clean_and_expand(self, column_name: str) -> str:
        """
        Clean columnn names and expand abbreviations to understand meaning better
        """

        # convert to lowercase and remove special characters
        cleaned = re.sub(r"[^\w\s]", " ", column_name.lower())

        # expand abbreviations
        words = cleaned.split()
        expanded_words = []

        for word in words:
            if word in self.abbreviation_expansion:
                expanded_words.extend(self.abbreviation_expansion[word].split())
            else:
                expanded_words.append(word)

        return " ".join(expanded_words)

    def _calculate_semantic_similarity(
        self, source_clean: str, target_clean: str
    ) -> float:
        """
        Calculate how similar two column names are semantically
        """

        source_words = set(source_clean.split())
        target_words = set(target_clean.split())

        if not source_words or not target_words:
            return 0.0

        # Jacred similarity (intersection over union)
        intersection = source_words & target_words
        union = source_words | target_words

        jaccard = len(intersection) / len(union)

        # Boost for exact words matches
        exact_matches = len(intersection)
        if exact_matches > 0:
            jaccard += 0.2 * exact_matches

        # boost for substring matches
        for source_word in source_words:
            for target_word in target_words:
                if source_word in target_word or target_word in source_word:
                    jaccard += 0.1

        return min(jaccard, 1.0)  # cap at 1.0

    def _analyze_data_patterns(
        self, source_cols: List[str], sample_data: pd.DataFrame
    ) -> Dict[str, Dict[str, Any]]:
        """
        Step 2 : Look at actual data to understand what each column contains
        This is where AI can analyze patterns, data types, value ranges etc.
        """

        insights = {}

        for col in source_cols:
            if col not in sample_data.columns:
                continue

            data_series = sample_data[col].dropna()
            if len(data_series) == 0:
                continue

            insights[col] = {
                "data_type": str(data_series.dtype),
                "value_pattern": self._detect_value_pattern(data_series),
                "business_domain": self._guess_business_domain(col, data_series),
            }

            print(
                f"📊 {col}: {insights[col]['data_type']}, domain: {insights[col]['business_domain']}"
            )

        return insights

    def _detect_data_type(self, series: pd.Series) -> str:
        """
        Detect What type of data this column contains
        """

        # check for dates first
        if series.dtypes == "object":
            try:
                pd.to_datetime(series.iloc[0])
                return "date"
            except:
                pass

        # check for numeric patterns
        if pd.api.types.is_numeric_dtype(series):
            min_val = series.min()
            max_val = series.max()

            # percentage-like data
            if 0 <= min_val and max_val <= 100:
                return "percentage"
            # hours-like data
            elif 0 <= min_val and max_val <= 24:
                return "hours"
            # small counts (e.g. incidents)
            elif min_val >= 0 and max_val > 50:
                return "small_counts"
            # large counts (like manhours)
            elif min_val >= 0 and max_val > 50:
                return "Large_count"

        # check for text patterns
        if series.dtype == "object":
            unique_values = series.unique()

            # week identifiers
            if any("week" in str(val).lower() for val in unique_values):
                return "week_identifier"

            # Day names
            days = [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
            if any(str(val).lower() in days for val in unique_values):
                return "day_name"

        return "unknown"

    def _detect_value_pattern(self, series: pd.Series) -> str:
        """
        Detect specific patterns in the values
        """

        if pd.api.types.is_numeric_dtype(series):
            min_val = series.min()
            max_val = series.max()

            # Safety manhours typically 50 - 500 hours per day
            if 50 <= min_val and max_val <= 500:
                return "typical_manhours"

            # incidents typically 0-5 per day
            elif 0 <= min_val and max_val <= 5:
                return "typical_incidents"

            # Percentages/rates typically 80-100
            elif 80 <= min_val and max_val <= 100:
                return "high_percentage"

        return "general"

    def _guess_business_domain(self, col_name: str, data_series: pd.Series) -> str:
        """
        Guess which SafexpressOps business domain this column belongs to
        """

        col_lower = col_name.lower()

        # check against our business vocabulary
        for domain, info in self.operational_vocabulary.items():
            for keyword in info["keywords"]:
                if keyword in col_lower:
                    return domain

        # Use data patterns as additional hints
        data_type = self._detect_data_type(data_series)
        value_pattern = self._detect_value_pattern(data_series)

        if data_type == "date":
            return "temporal"
        elif value_pattern == "typical_manhours":
            return "safety"
        elif value_pattern == "typical incidents":
            return "safety"

        return "general"

    def _apply_data_insights(
        self, semantic_mappings: Dict, data_insights: Dict, target_cols: List[str]
    ) -> Dict:
        """
        Step 3: Use data analysis to boost confidence of good mappings
        """

        for source_col, insights in data_insights.items():
            data_type = insights["data_type"]
            business_domain = insights["business_domain"]

            # Boost mappings that make sense based on data analysis
            for target_col in target_cols:
                current_score = semantic_mappings[source_col].get(target_col, 0)

                # Boost based on data type alignment
                if data_type == "date" and "date" in target_col.lower():
                    semantic_mappings[source_col][target_col] = min(
                        current_score + 0.3, 1.0
                    )
                elif data_type == "percentage" and "%" in target_col:
                    semantic_mappings[source_col][target_col] = min(
                        current_score + 0.3, 1.0
                    )
                elif (
                    data_type in ["large_count", "typical_manhours"]
                    and "manhour" in target_col.lower()
                ):
                    semantic_mappings[source_col][target_col] = min(
                        current_score + 0.3, 1.0
                    )
                elif (
                    data_type in ["small_count", "typical_incidents"]
                    and "incident" in target_col.lower()
                ):
                    semantic_mappings[source_col][target_col] = min(
                        current_score + 0.3, 1.0
                    )

                # Boost based on business domain alignment
                if business_domain in self.operational_vocabulary:
                    domain_targets = self.operational_vocabulary[business_domain][
                        "target_columns"
                    ]
                    if target_col in domain_targets:
                        semantic_mappings[source_col][target_col] = min(
                            current_score + 0.2, 1.0
                        )

        return semantic_mappings

    def _apply_business_rules(
        self, mappings: Dict, source_cols: List[str], target_cols: List[str]
    ) -> Dict[str, Any]:
        """
        Step 4: Apply SafExpressOps business rules and create final result
        """

        final_mappings = {}

        for source_col in source_cols:
            # Find the best target column for this source
            best_target = None
            best_score = 0.0

            for target_col in target_cols:
                score = mappings[source_col].get(target_col, 0)
                if score > best_score:
                    best_score = score
                    best_target = target_col

            # Determine confidence level
            if best_score >= 0.8:
                confidence_level = "high"
                confidence_score = best_score
            elif best_score >= 0.5:
                confidence_level = "medium"
                confidence_score = best_score
            else:
                confidence_level = "low"
                confidence_score = best_score
                best_target = None  # Don't map if confidence too low

            final_mappings[source_col] = {
                "target": best_target,
                "confidence_score": confidence_score,
                "confidence_level": confidence_level,
                "needs_review": confidence_level in ["low", "medium"],
            }

        # Create summary
        high_confidence = [
            k for k, v in final_mappings.items() if v["confidence_level"] == "high"
        ]
        needs_review = [k for k, v in final_mappings.items() if v["needs_review"]]

        return {
            "mappings": final_mappings,
            "summary": {
                "total_columns": len(source_cols),
                "high_confidence_mappings": len(high_confidence),
                "needs_review": len(needs_review),
                "accuracy_estimate": (
                    len(high_confidence) / len(source_cols) if source_cols else 0
                ),
            },
        }
