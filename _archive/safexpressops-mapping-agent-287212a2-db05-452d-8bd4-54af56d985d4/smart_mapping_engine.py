import pandas as pd
import re
from typing import Dict, List, Any, Tuple, Optional
import numpy as np
import os
import json
from difflib import SequenceMatcher


class SmartMappingEngine:
    """
    Hybrid smart column mapping engine - uses 4-tier approach:
    1.  Exact matching (instant, free, perfect)
    2.  Typo detection via Levenshtein (fast, free, good for misspellings)
    3. Semantic matching (fast, free, good for word overlap)
    4. OpenAI LLM (smart, paid, excellent for edge cases)
    
    UPDATED: Robust OpenAI integration for ALL edge cases
    """

    def __init__(self, use_openai: bool = True):
        from safexpressops_target_columns import (
            SAFEXPRESSOPS_TARGET_COLUMNS,
            CALCULATED_COLUMNS,
            INPUT_COLUMNS,
            is_calculated_column,
        )

        self.all_target_columns = SAFEXPRESSOPS_TARGET_COLUMNS
        self.calculated_columns = CALCULATED_COLUMNS
        self.input_columns = INPUT_COLUMNS
        self.is_calculated = is_calculated_column

        # OpenAI setup
        self.use_openai = use_openai
        self.openai_client = None
        
        if use_openai:
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                try:
                    from openai import OpenAI
                    self.openai_client = OpenAI(api_key=api_key)
                    print("OpenAI integration enabled for smart mapping")
                except ImportError:
                    print("OpenAI package not installed")
                    self.use_openai = False
            else:
                print("OpenAI integration disabled (no API key)")
                self.use_openai = False

        # ============================================================
        # KNOWN INCORRECT MAPPINGS - Block these pairs
        # ============================================================
        self.incorrect_mappings = {
            # Manhours confusion - these are DIFFERENT metrics! 
            ("Toal Manhours", "Cummulative Safe manhours"),
            ("Total Manhours", "Cummulative Safe manhours"),
            ("Toal Manhours", "Safe man-hours"),
            ("Total Manhours", "Safe man-hours"),
            ("Toal Manhours", "No Lost Time Incident Rate"),
            ("Total Manhours", "No Lost Time Incident Rate"),
            ("Toal Manhours", "Days Without Lost Time Incident"),
            ("Total Manhours", "Days Without Lost Time Incident"),
            # Cross-category confusion
            ("Warehouse Damage Incident", "Warehouse Damage Incident Cost"),
            ("Space Utilization", "Truck Utilization"),
            ("Truck Utilization", "Space Utilization"),
            ("Whse Capacity", "Space Utilized"),
            ("Whse Capasity", "Space Utilized"),
            # Different incident types
            ("Warehouse Damage Incident", "Losttime Incident"),
            ("FEFO Incident", "Losttime Incident"),
            ("Expired Product Incident", "Losttime Incident"),
            ("WH QA Incident", "Losttime Incident"),
            ("Cycle Count Accuracy", "Losttime Incident"),
            # Inventory vs Expenses
            ("Good Pallet Inventory", "LPG Expenses"),
            ("Good Pallet Inventory", "Diesel Expenses"),
            ("Good Pallet Inventory", "Total Expenses"),
            ("Damaged Pallet Inventory", "Whse Damaged Pallet Cost"),
            ("Total Stock On-Hand", "Total Expenses"),
            # Different expense types
            ("LPG Expenses", "Diesel Expenses"),
            ("Diesel Expenses", "LPG Expenses"),
            ("Office Supplies", "Meals Expenses"),
            ("Meals Expenses", "Office Supplies"),
            # POD vs Transmission
            ("Returned POD", "Transmitted to Client"),
            ("Unreturned POD", "Not yet Transmitted"),
            ("Return Performance", "Trasmitted Perfromance"),
            # Manpower types
            ("Manpower Matrix", "Deployed"),
            ("Deployed", "Present"),
            ("Present", "Deployed"),
            # Performance metrics
            ("Manpower Fill-rate", "Attendance Perf %"),
            ("Attendance Perf %", "Timeliness Perf.  %"),
            # Inbound vs Outbound
            ("Discrepancy Qty Inbound", "Discrepancy Qty Outbound"),
            ("Discrepancy Qty Outbound", "Discrepancy Qty Inbound"),
            ("Units Received Fast Unloading HIT", "Units Dispatched Fast Loading HIT"),
            ("Units Dispatched Fast Loading HIT", "Units Received Fast Unloading HIT"),
        }

        # ============================================================
        # KNOWN CORRECT MAPPINGS - Force these typo corrections
        # ============================================================
        self.forced_mappings = {
            # Typo corrections (source with typo → correct target)
            "Toal Manhours": "Total Manhours",
            "Whse Capasity": "Whse Capacity",
            "Space Utilised": "Space Utilized",
            "No. of CV Recieved": "No. of CV Received",
            "Discrepency Qty Inbound": "Discrepancy Qty Inbound",
            "Discrepency Qty Outbound": "Discrepancy Qty Outbound",
            "Ave Chcked Qty Per Hr": "Ave Chcked Qty Per Hr",
        }

        # Common abbreviations
        self.abbreviation_expansion = {
            "cv": "container vessel",
            "otif": "on time in full",
            "cts": "customer satisfaction",
            "fefo": "first expired first out",
            "hrs": "hours",
            "hr": "hours",
            "qty": "quantity",
            "ave": "average",
            "avg": "average",
            "pct": "percent",
            "acc": "accuracy",
            "whse": "warehouse",
            "perf": "performance",
        }

    # ============================================================
    # UTILITY METHODS
    # ============================================================

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein (edit) distance between two strings"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def _calculate_typo_similarity(self, source: str, target: str) -> float:
        """
        Calculate similarity score optimized for TYPO DETECTION
        Uses character-level similarity (Levenshtein) + SequenceMatcher
        """
        s1 = source.lower().strip()
        s2 = target.lower().strip()

        if s1 == s2:
            return 1.0

        # Calculate Levenshtein distance
        lev_distance = self._levenshtein_distance(s1, s2)
        max_len = max(len(s1), len(s2))

        if max_len == 0:
            return 0.0

        lev_similarity = 1.0 - (lev_distance / max_len)
        seq_similarity = SequenceMatcher(None, s1, s2).ratio()

        # Take the higher score
        return max(lev_similarity, seq_similarity)

    def _calculate_semantic_similarity(self, source: str, target: str) -> float:
        """Calculate semantic similarity based on word overlap"""
        source_clean = self._clean_and_expand(source)
        target_clean = self._clean_and_expand(target)

        source_words = set(source_clean.split())
        target_words = set(target_clean.split())

        if not source_words or not target_words:
            return 0.0

        intersection = source_words & target_words
        union = source_words | target_words

        if len(union) == 0:
            return 0.0

        jaccard = len(intersection) / len(union)

        # Boost for exact word matches
        if len(intersection) > 0:
            jaccard += 0.15 * len(intersection)

        # Boost for partial word matches
        for sw in source_words:
            for tw in target_words:
                if sw != tw and len(sw) > 3 and len(tw) > 3:
                    if sw in tw or tw in sw:
                        jaccard += 0.05

        return min(jaccard, 1.0)

    def _clean_and_expand(self, column_name: str) -> str:
        """Clean column names and expand abbreviations"""
        cleaned = re.sub(r"[^\w\s]", " ", column_name.lower())
        words = cleaned.split()
        expanded_words = []

        for word in words:
            if word in self.abbreviation_expansion:
                expanded_words.extend(self.abbreviation_expansion[word].split())
            else:
                expanded_words.append(word)

        return " ".join(expanded_words)

    def _is_blocked_mapping(self, source: str, target: str) -> bool:
        """Check if this source→target mapping is known to be incorrect"""
        if (source, target) in self.incorrect_mappings:
            return True

        # Check normalized versions
        s_lower = source.lower().strip()
        t_lower = target.lower().strip()

        for blocked_source, blocked_target in self.incorrect_mappings:
            if (s_lower == blocked_source.lower().strip() and
                t_lower == blocked_target.lower().strip()):
                return True

        return False

    def _get_forced_mapping(self, source: str) -> Optional[str]:
        """Check if this source has a forced/known correct mapping"""
        # Exact match
        if source in self.forced_mappings:
            return self.forced_mappings[source]

        # Case-insensitive match
        s_lower = source.lower().strip()
        for forced_source, forced_target in self.forced_mappings.items():
            if s_lower == forced_source.lower().strip():
                return forced_target

        return None

    # ============================================================
    # OPENAI INTEGRATION - ROBUST FOR ALL EDGE CASES
    # ============================================================

    def _openai_map_single_column(
        self,
        source_col: str,
        available_targets: List[str],
        sample_values: List[Any] = None,
    ) -> Tuple[Optional[str], float]:
        """
        Use OpenAI to map a SINGLE column with detailed context
        Returns: (target_column, confidence_score)
        """
        if not self.use_openai or not self.openai_client:
            return None, 0.0

        # Prepare sample values context
        sample_context = ""
        if sample_values:
            sample_context = f"\nSample values from '{source_col}': {sample_values[:5]}"

        # Find similar targets to suggest
        similar_targets = []
        for target in available_targets[:30]:  # Limit to prevent token overflow
            sim = self._calculate_typo_similarity(source_col, target)
            if sim > 0.4:
                similar_targets.append((target, sim))
        
        similar_targets.sort(key=lambda x: x[1], reverse=True)
        top_similar = [t[0] for t in similar_targets[:10]]

        prompt = f"""You are a data mapping expert for SafExpressOps warehouse operations.

**Task**: Find the BEST matching target column for this source column. 

**Source column**: "{source_col}"
{sample_context}

**Most similar target columns** (ranked by text similarity):
{json.dumps(top_similar, indent=2)}

**All available targets** ({len(available_targets)} columns):
{json.dumps(available_targets[:50], indent=2)}

**RULES**:
1.  TYPO DETECTION: If source is a typo of a target, match it! 
   - "Capasity" → "Capacity"
   - "Recieved" → "Received"
   - "Toal" → "Total"
   - "Utilised" → "Utilized"
   - "Discrepency" → "Discrepancy"

2. SEMANTIC MATCHING: Match by meaning, not just text
   - "Total Manhours" should match "Total Manhours", NOT "Cummulative Safe manhours"
   - "Manhours" is different from "Safe manhours" or "Cummulative Safe manhours"

3. BLOCK WRONG MAPPINGS:
   - Don't match "Total Manhours" to "Cummulative Safe manhours" (different metrics!)
   - Don't match incidents to unrelated incidents
   - Don't match inbound metrics to outbound metrics

4. If NO good match exists, return null

**Return JSON only**:
{{"target": "column_name" or null, "confidence": 0.0-1.0, "reason": "brief explanation"}}
"""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise data mapping expert.  Always check for typos first.  Return only valid JSON."
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=500,
            )

            response_text = response.choices[0].message.content.strip()

            # Remove markdown code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()

            result = json.loads(response_text)
            target = result.get("target")
            confidence = float(result.get("confidence", 0.0))
            reason = result.get("reason", "")

            # Validate the target exists
            if target and target in available_targets:
                # Check if blocked
                if self._is_blocked_mapping(source_col, target):
                    print(f"      OpenAI suggested blocked mapping: {source_col} → {target}")
                    return None, 0.0

                print(f"      OpenAI: '{source_col}' → '{target}' ({confidence*100:.0f}%) - {reason}")
                return target, confidence

            return None, 0.0

        except Exception as e:
            print(f"      OpenAI error for '{source_col}': {str(e)}")
            return None, 0.0

    def _openai_batch_mapping(
        self,
        source_cols: List[str],
        available_targets: List[str],
        sample_data: pd.DataFrame = None,
    ) -> Dict[str, Tuple[str, float]]:
        """
        Use OpenAI to map MULTIPLE columns at once (more efficient)
        Returns: {source: (target, confidence)}
        """
        if not self.use_openai or not self.openai_client or not source_cols:
            return {}

        # Prepare sample data context
        sample_context = ""
        if sample_data is not None:
            sample_context = "\n**Sample data**:\n"
            for col in source_cols[:10]:
                if col in sample_data.columns:
                    values = sample_data[col].dropna().head(3).tolist()
                    sample_context += f"- {col}: {values}\n"

        prompt = f"""You are a data mapping expert for SafExpressOps warehouse operations.

**Task**: Map each source column to the BEST matching target column. 

**Source columns to map** ({len(source_cols)} columns):
{json.dumps(source_cols, indent=2)}

**Available target columns** ({len(available_targets)} columns):
{json.dumps(available_targets[:60], indent=2)}
{sample_context}

**CRITICAL RULES**:

1. **TYPO DETECTION** (HIGHEST PRIORITY):
   - "Whse Capasity" → "Whse Capacity" (spelling fix)
   - "Space Utilised" → "Space Utilized" (British→American)
   - "No. of CV Recieved" → "No. of CV Received" (typo fix)
   - "Discrepency Qty Inbound" → "Discrepancy Qty Inbound" (typo fix)
   - "Toal Manhours" → "Total Manhours" (typo fix, NOT Cummulative!)

2. **SEMANTIC CORRECTNESS**:
   - "Total Manhours" = raw hours worked → matches "Total Manhours"
   - "Cummulative Safe manhours" = running total of safe hours → DIFFERENT metric!
   - "Safe man-hours" = hours without incidents → DIFFERENT metric!
   - DO NOT confuse these! 

3. **BLOCKED MAPPINGS** (NEVER suggest these):
   - "Total Manhours" or "Toal Manhours" → "Cummulative Safe manhours" 
   - "Total Manhours" or "Toal Manhours" → "Safe man-hours" 
   - Any incident type → different incident type 
   - Inbound metrics → Outbound metrics 

4. Return null if no good match (don't force bad mappings)

**Return JSON only** (array of mappings):
[
  {{"source": "col1", "target": "matched_col" or null, "confidence": 0.0-1.0}},
  ... 
]
"""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise data mapping expert.  Prioritize typo fixes.  Never confuse different metrics. Return only valid JSON array."
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
            )

            response_text = response.choices[0].message.content.strip()

            # Remove markdown code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()

            results = json.loads(response_text)

            mappings = {}
            for item in results:
                source = item.get("source")
                target = item.get("target")
                confidence = float(item.get("confidence", 0.0))

                if source and target and target in available_targets:
                    # Check if blocked
                    if self._is_blocked_mapping(source, target):
                        print(f"      OpenAI blocked: {source} → {target}")
                        continue

                    mappings[source] = (target, confidence)
                    print(f"      OpenAI: '{source}' → '{target}' ({confidence*100:.0f}%)")

            return mappings

        except Exception as e:
            print(f"      OpenAI batch error: {str(e)}")
            return {}

    # ============================================================
    # MAIN MAPPING FUNCTION
    # ============================================================

    def smart_map_columns(
        self,
        source_columns: List[str],
        target_columns: List[str],
        sample_data: pd.DataFrame = None,
    ) -> Dict[str, Any]:
        """
        Main function: 4-tier intelligent mapping with robust OpenAI integration
        """
        print("\nSmart Mapping Engine starting...")
        print(f"   Source columns: {len(source_columns)}")
        print(f"   Target columns: {len(target_columns)}")

        # Filter out calculated columns from targets
        original_count = len(target_columns)
        target_columns = [col for col in target_columns if not self.is_calculated(col)]

        print(f"\nFormula-Aware Filtering:")
        print(f"   Calculated excluded: {original_count - len(target_columns)}")
        print(f"   Mappable targets: {len(target_columns)}")

        final_mappings = {}
        used_targets = set()

        # ============================================================
        # TIER 0: Forced mappings (known typo corrections)
        # ============================================================
        print("\nTier 0: Forced mappings (known corrections)...")
        forced_count = 0

        for source_col in source_columns:
            forced_target = self._get_forced_mapping(source_col)
            if forced_target and forced_target in target_columns and forced_target not in used_targets:
                final_mappings[source_col] = {
                    "target": forced_target,
                    "confidence_score": 0.98,
                    "confidence_level": "high",
                    "needs_review": False,
                    "method": "forced_correction",
                }
                used_targets.add(forced_target)
                forced_count += 1
                print(f"      '{source_col}' → '{forced_target}' (forced)")

        print(f"   Forced corrections: {forced_count}")

        # ============================================================
        # TIER 1: Exact matching (case-insensitive)
        # ============================================================
        remaining_sources = [s for s in source_columns if s not in final_mappings]
        remaining_targets = [t for t in target_columns if t not in used_targets]

        print("\nTier 1: Exact matching...")
        exact_count = 0

        for source_col in remaining_sources[:]:
            for target_col in remaining_targets:
                if source_col.lower().strip() == target_col.lower().strip():
                    final_mappings[source_col] = {
                        "target": target_col,
                        "confidence_score": 1.0,
                        "confidence_level": "high",
                        "needs_review": False,
                        "method": "exact_match",
                    }
                    used_targets.add(target_col)
                    remaining_sources.remove(source_col)
                    remaining_targets.remove(target_col)
                    exact_count += 1
                    if exact_count <= 5:
                        print(f"      '{source_col}' → '{target_col}' (100%)")
                    break

        if exact_count > 5:
            print(f"      ...  and {exact_count - 5} more")
        print(f"   Exact matches: {exact_count}")

        # ============================================================
        # TIER 2: Typo detection (character-level similarity ≥ 0.85)
        # ============================================================
        print("\nTier 2: Typo detection...")
        typo_count = 0

        for source_col in remaining_sources[:]:
            best_target = None
            best_score = 0.0

            for target_col in remaining_targets:
                if self._is_blocked_mapping(source_col, target_col):
                    continue

                score = self._calculate_typo_similarity(source_col, target_col)
                if score > best_score:
                    best_score = score
                    best_target = target_col

            # High threshold for typo detection
            if best_target and best_score >= 0.85:
                final_mappings[source_col] = {
                    "target": best_target,
                    "confidence_score": best_score,
                    "confidence_level": "high",
                    "needs_review": False,
                    "method": "typo_correction",
                }
                used_targets.add(best_target)
                remaining_sources.remove(source_col)
                remaining_targets.remove(best_target)
                typo_count += 1
                print(f"      '{source_col}' → '{best_target}' ({best_score*100:.0f}%)")

        print(f"   Typo corrections: {typo_count}")

        # ============================================================
        # TIER 3: OpenAI for ALL remaining columns (before semantic!)
        # ============================================================
        if self.use_openai and self.openai_client and remaining_sources:
            print(f"\nTier 3: OpenAI mapping for {len(remaining_sources)} columns...")

            # Use batch mapping for efficiency
            openai_results = self._openai_batch_mapping(
                remaining_sources,
                remaining_targets,
                sample_data
            )

            openai_count = 0
            for source_col, (target_col, confidence) in openai_results.items():
                if target_col in remaining_targets:
                    final_mappings[source_col] = {
                        "target": target_col,
                        "confidence_score": confidence,
                        "confidence_level": "high" if confidence >= 0.7 else "medium",
                        "needs_review": confidence < 0.7,
                        "method": "openai_llm",
                    }
                    used_targets.add(target_col)
                    if source_col in remaining_sources:
                        remaining_sources.remove(source_col)
                    if target_col in remaining_targets:
                        remaining_targets.remove(target_col)
                    openai_count += 1

            print(f"   OpenAI matches: {openai_count}")

        # ============================================================
        # TIER 4: Semantic matching for remaining columns
        # ============================================================
        if remaining_sources:
            print(f"\nTier 4: Semantic matching for {len(remaining_sources)} remaining...")
            semantic_count = 0

            for source_col in remaining_sources[:]:
                best_target = None
                best_score = 0.0

                for target_col in remaining_targets:
                    if self._is_blocked_mapping(source_col, target_col):
                        continue

                    # Combined score: semantic + character similarity
                    sem_score = self._calculate_semantic_similarity(source_col, target_col)
                    char_score = self._calculate_typo_similarity(source_col, target_col)
                    combined = (sem_score * 0.6) + (char_score * 0.4)

                    if combined > best_score:
                        best_score = combined
                        best_target = target_col

                # Determine confidence level
                if best_score >= 0.7:
                    confidence_level = "high"
                    needs_review = False
                elif best_score >= 0.5:
                    confidence_level = "medium"
                    needs_review = True
                else:
                    confidence_level = "low"
                    needs_review = True
                    best_target = None

                if best_target:
                    final_mappings[source_col] = {
                        "target": best_target,
                        "confidence_score": best_score,
                        "confidence_level": confidence_level,
                        "needs_review": needs_review,
                        "method": "semantic",
                    }
                    used_targets.add(best_target)
                    remaining_sources.remove(source_col)
                    remaining_targets.remove(best_target)
                    semantic_count += 1
                    print(f"      [{'HIGH' if confidence_level == 'high' else 'LOW'}] '{source_col}' -> '{best_target}' ({best_score*100:.0f}%)")
                else:
                    final_mappings[source_col] = {
                        "target": None,
                        "confidence_score": best_score,
                        "confidence_level": "low",
                        "needs_review": True,
                        "method": "none",
                    }
                    print(f"      '{source_col}' → No match found")

            print(f"   Semantic matches: {semantic_count}")

        # ============================================================
        # Handle any remaining unmapped columns
        # ============================================================
        for source_col in remaining_sources:
            if source_col not in final_mappings:
                final_mappings[source_col] = {
                    "target": None,
                    "confidence_score": 0.0,
                    "confidence_level": "low",
                    "needs_review": True,
                    "method": "none",
                }

        # ============================================================
        # Summary
        # ============================================================
        high_conf = sum(1 for v in final_mappings.values() if v["confidence_level"] == "high")
        medium_conf = sum(1 for v in final_mappings.values() if v["confidence_level"] == "medium")
        low_conf = sum(1 for v in final_mappings.values() if v["confidence_level"] == "low")
        needs_review = sum(1 for v in final_mappings.values() if v["needs_review"])
        
        methods = {}
        for v in final_mappings.values():
            m = v.get("method", "none")
            methods[m] = methods.get(m, 0) + 1

        print(f"\nFinal Mapping Summary:")
        print(f"   Total columns: {len(source_columns)}")
        print(f"   High confidence: {high_conf}")
        print(f"   Medium confidence: {medium_conf}")
        print(f"   Low/None: {low_conf}")
        print(f"   Needs review: {needs_review}")
        print(f"   Methods: {methods}")
        print(f"   Accuracy estimate: {high_conf / len(source_columns) * 100:.1f}%")

        return {
            "mappings": final_mappings,
            "summary": {
                "total_columns": len(source_columns),
                "high_confidence_mappings": high_conf,
                "medium_confidence_mappings": medium_conf,
                "low_confidence_mappings": low_conf,
                "needs_review": needs_review,
                "accuracy_estimate": high_conf / len(source_columns) if source_columns else 0,
                "methods_used": methods,
            },
        }