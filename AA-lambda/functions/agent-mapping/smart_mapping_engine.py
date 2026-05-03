import pandas as pd
import re
from typing import Dict, List, Any, Tuple, Optional
import numpy as np
import os
import json
import threading
from openai import OpenAI

# ----------------------------------------------------------------------
# AA-lambda Phase 2.5.B: per-call quota integration (mapping sub-agent).
# The Lambda handler sets _quota_ctx via `set_quota_context(...)` on entry
# (using user_id / jwt / request_id from credentials_dict) and clears it
# after `flush_quota_reports()` in a try/finally. The actual OpenAI call
# inside `_openai_mapping` then does check + report against the deployed
# Token Quota Service.
# ----------------------------------------------------------------------

import urllib.request as _ur
import urllib.error as _ue

_QUOTA_SERVICE_URL = os.getenv("QUOTA_SERVICE_URL", "").rstrip("/")
_QUOTA_ENABLED = os.getenv("QUOTA_ENABLED", "true").lower() in ("1", "true", "yes")
_SERVICE_NAME = os.getenv("SERVICE_NAME", "supervisor.mapping")

_quota_ctx_lock = threading.Lock()
_quota_ctx: Dict[str, Optional[str]] = {"user_id": None, "jwt": None, "request_id": None}


def set_quota_context(
    user_id: Optional[str] = None,
    jwt: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    with _quota_ctx_lock:
        _quota_ctx["user_id"] = user_id
        _quota_ctx["jwt"] = jwt
        _quota_ctx["request_id"] = request_id


def clear_quota_context() -> None:
    with _quota_ctx_lock:
        _quota_ctx["user_id"] = None
        _quota_ctx["jwt"] = None
        _quota_ctx["request_id"] = None


def _http_post_json(url: str, payload: dict, jwt: Optional[str], timeout: float = 5.0) -> Optional[dict]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    req = _ur.Request(url, data=body, headers=headers, method="POST")
    try:
        with _ur.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except _ue.HTTPError as he:
        if he.code == 404:
            return {"_status": 404}
        return None
    except Exception:
        return None


def _quota_check(estimated_tokens: int = 1500) -> tuple[bool, Optional[str]]:
    if not (_QUOTA_ENABLED and _QUOTA_SERVICE_URL):
        return True, None
    user_id = _quota_ctx.get("user_id")
    if not user_id:
        return True, None  # anonymous → fail-open per QUOTA_SERVICE_REFERENCE §4.4
    data = _http_post_json(
        f"{_QUOTA_SERVICE_URL}/quota/check",
        {
            "user_id": user_id,
            "estimated_tokens": estimated_tokens,
            "service": _SERVICE_NAME,
            "operation": "chat",
        },
        _quota_ctx.get("jwt"),
    )
    if data is None:
        return True, None  # fail-open
    if data.get("_status") == 404:
        return False, "Your account has been deactivated. Please contact an administrator."
    if not data.get("allowed", True):
        rem = data.get("remaining_tokens", 0)
        lim = data.get("monthly_limit", 0)
        return False, f"Token quota exceeded. {rem} tokens remaining of {lim} monthly limit."
    return True, None


def _quota_report(model: str, input_tokens: int, output_tokens: int, operation: str = "smart_column_mapping") -> None:
    if not (_QUOTA_ENABLED and _QUOTA_SERVICE_URL):
        return
    user_id = _quota_ctx.get("user_id")
    if not user_id:
        return
    _http_post_json(
        f"{_QUOTA_SERVICE_URL}/quota/report",
        {
            "user_id": user_id,
            "service": _SERVICE_NAME,
            "model": model,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "operation": operation,
            "request_id": _quota_ctx.get("request_id"),
        },
        _quota_ctx.get("jwt"),
        timeout=3.0,
    )


def flush_quota_reports() -> None:
    """No-op: reports are synchronous via _http_post_json, kept for symmetry
    with shared/logging_config.flush_pending_quota_reports."""
    return None


class SmartMappingEngine:
    """
    Hybrid smart column mapping engine - uses 3-tier approach:
    1. Exact matching (instant, free, perfect)
    2. Rule-based semantic matching (fast, free, good)
    3. OpenAI LLM fallback (slow, paid, excellent for edge cases)
    """

    def __init__(self, use_openai: bool = True):
        # Import the actual SafExpressOps columns
        from safexpressops_target_columns import SAFEXPRESSOPS_TARGET_COLUMNS

        # Store the full list
        self.all_target_columns = SAFEXPRESSOPS_TARGET_COLUMNS

        # OpenAI setup
        self.use_openai = use_openai
        if use_openai and os.getenv("OPENAI_API_KEY"):
            self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            print("✅ OpenAI integration enabled for smart mapping")
        else:
            self.use_openai = False
            print("⚠️ OpenAI integration disabled (no API key or use_openai=False)")

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
        Main function: 3-tier intelligent mapping

        Args:
            source_columns: Columns from uploaded file
            target_columns: SafExpressOps target columns
            sample_data: Sample of the actual data to analyze

        Returns:
            Dictionary mapping source to target columns with confidence scores
        """
        print("\n🧠 Smart Mapping Engine starting...")
        print(f"   Source columns: {len(source_columns)}")
        print(f"   Target columns: {len(target_columns)}")

        # Tier 1: Exact matching (instant, free, perfect)
        print("\n🎯 Tier 1: Exact matching...")
        exact_matches, remaining_sources = self._exact_matching(
            source_columns, target_columns
        )
        remaining_targets = [
            t for t in target_columns if t not in exact_matches.values()
        ]

        print(f"   ✅ Exact matches: {len(exact_matches)}")
        print(
            f"   Remaining: {len(remaining_sources)} sources, {len(remaining_targets)} targets"
        )

        # Tier 2: Rule-based semantic mapping (fast, free, good)
        semantic_mappings = {}
        if remaining_sources:
            print("\n📊 Tier 2: Semantic matching...")
            semantic_mappings = self._semantic_mapping(
                remaining_sources, remaining_targets
            )

            # Analyze data patterns if sample data is provided
            if sample_data is not None:
                data_insights = self._analyze_data_patterns(
                    remaining_sources, sample_data
                )
                semantic_mappings = self._apply_data_insights(
                    semantic_mappings, data_insights, remaining_targets
                )

        # Tier 3: OpenAI LLM for difficult cases (slow, paid, excellent)
        openai_mappings = {}
        if self.use_openai and remaining_sources:
            # Only send low-confidence mappings to OpenAI
            low_confidence_sources = self._get_low_confidence_sources(
                semantic_mappings, remaining_sources, threshold=0.6
            )

            if low_confidence_sources:
                print(
                    f"\n🤖 Tier 3: OpenAI LLM for {len(low_confidence_sources)} difficult columns..."
                )
                openai_mappings = self._openai_mapping(
                    low_confidence_sources, remaining_targets, sample_data
                )
                print(f"   ✅ OpenAI returned {len(openai_mappings)} mappings")

        # Combine all tiers
        final_mappings = self._combine_tiers(
            exact_matches,
            semantic_mappings,
            openai_mappings,
            source_columns,
            remaining_sources,
        )

        return final_mappings

    def _exact_matching(
        self, source_cols: List[str], target_cols: List[str]
    ) -> Tuple[Dict[str, str], List[str]]:
        """
        Tier 1: Find exact matches (case-insensitive)
        Returns: (exact_matches_dict, remaining_sources)
        """
        exact_matches = {}
        remaining_sources = []
        remaining_targets = list(target_cols)

        for source_col in source_cols:
            exact_match = None
            for target_col in remaining_targets:
                if source_col.lower().strip() == target_col.lower().strip():
                    exact_match = target_col
                    break

            if exact_match:
                exact_matches[source_col] = exact_match
                remaining_targets.remove(exact_match)
                if len(exact_matches) <= 5:  # Only print first 5
                    print(f"      ✓ '{source_col}' → '{exact_match}'")
            else:
                remaining_sources.append(source_col)

        if len(exact_matches) > 5:
            print(f"      ... and {len(exact_matches) - 5} more exact matches")

        return exact_matches, remaining_sources

    def _get_low_confidence_sources(
        self, semantic_mappings: Dict, source_cols: List[str], threshold: float = 0.6
    ) -> List[str]:
        """
        Identify columns that need OpenAI help (low confidence from semantic matching)
        """
        low_confidence = []

        for source_col in source_cols:
            if source_col not in semantic_mappings:
                low_confidence.append(source_col)
                continue

            # Find best score for this source
            best_score = (
                max(semantic_mappings[source_col].values())
                if semantic_mappings[source_col]
                else 0
            )

            if best_score < threshold:
                low_confidence.append(source_col)

        return low_confidence

    def _openai_mapping(
        self,
        source_cols: List[str],
        target_cols: List[str],
        sample_data: pd.DataFrame = None,
    ) -> Dict[str, str]:
        """
        Tier 3: Use OpenAI to map difficult columns
        """
        if not self.use_openai:
            return {}

        # Prepare sample data context
        sample_context = ""
        if sample_data is not None and len(source_cols) > 0:
            sample_context = "\n\nSample data (first 3 rows):\n"
            for source_col in source_cols[:10]:  # Show up to 10 columns
                if source_col in sample_data.columns:
                    values = sample_data[source_col].head(3).tolist()
                    sample_context += f"- {source_col}: {values}\n"

        # Create prompt
        prompt = f"""You are a data mapping expert for SafExpressOps, a warehouse operations company.

**Task**: Map source column names to target column names.

**Source columns to map** ({len(source_cols)} columns):
{json.dumps(source_cols, indent=2)}

**Available target columns** ({len(target_cols)} columns):
{json.dumps(target_cols, indent=2)}
{sample_context}

**Business context**:
- SafExpressOps tracks: safety metrics, warehouse operations, quality, inventory, expenses
- Common abbreviations: CV = Container Vessel, FEFO = First Expired First Out, CTS = Customer Satisfaction
- "Manhours" refers to labor hours worked
- "Incidents" are safety/quality issues
- "OTD" = On-Time Delivery, "OTIF" = On-Time In Full

**Instructions**:
1. For each source column, find the BEST matching target column
2. Only map if you're confident (>70% confidence)
3. Return JSON format: {{"source_column": "target_column" or null}}
4. If no good match exists, use null
5. Consider abbreviations and business context

Return ONLY valid JSON, no explanation:"""

        # AA-lambda Phase 2.5.B: pre-flight quota check; raise if denied so
        # the mapping tool surfaces a clean error to the user instead of
        # burning tokens. Estimated tokens = prompt-character / 4 + max_tokens
        # ceiling — same heuristic used by shared/logging_config.
        est_tokens = (len(prompt) // 4) + 2000
        ok, denial = _quota_check(estimated_tokens=est_tokens)
        if not ok:
            raise RuntimeError(denial or "Quota check denied")

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",  # Fast and cheap
                messages=[
                    {
                        "role": "system",
                        "content": "You are a data mapping expert. Return only valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,  # Low temperature for consistent results
                max_tokens=2000,
            )

            # AA-lambda Phase 2.5.B: report actual token usage from the
            # OpenAI response — this credits the user_id stash via the
            # deployed Token Quota Service.
            try:
                usage = getattr(response, "usage", None)
                if usage is not None:
                    _quota_report(
                        model="gpt-4o-mini",
                        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                        operation="smart_column_mapping",
                    )
            except Exception:
                # Never let quota reporting break the mapping result.
                pass

            # Parse response
            response_text = response.choices[0].message.content.strip()

            # Remove markdown code blocks if present
            if response_text.startswith("```json"):
                response_text = response_text[7:-3].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:-3].strip()

            mappings = json.loads(response_text)

            # Validate mappings
            validated_mappings = {}
            for source, target in mappings.items():
                if target and target in target_cols:
                    validated_mappings[source] = target
                    print(f"      ✓ '{source}' → '{target}' (via OpenAI)")

            return validated_mappings

        except Exception as e:
            print(f"      ⚠️ OpenAI mapping failed: {str(e)}")
            return {}

    def _combine_tiers(
        self,
        exact_matches: Dict[str, str],
        semantic_mappings: Dict,
        openai_mappings: Dict[str, str],
        all_source_cols: List[str],
        remaining_sources: List[str],
    ) -> Dict[str, Any]:
        """
        Combine results from all 3 tiers into final mappings
        """
        final_mappings = {}

        # Add exact matches (highest confidence)
        for source_col, target_col in exact_matches.items():
            final_mappings[source_col] = {
                "target": target_col,
                "confidence_score": 1.0,
                "confidence_level": "high",
                "needs_review": False,
                "method": "exact_match",
            }

        # Add OpenAI mappings (overrides semantic for low-confidence)
        for source_col, target_col in openai_mappings.items():
            final_mappings[source_col] = {
                "target": target_col,
                "confidence_score": 0.85,  # OpenAI gets high confidence
                "confidence_level": "high",
                "needs_review": False,
                "method": "openai_llm",
            }

        # Add semantic mappings for remaining columns
        remaining_targets = [
            t
            for t in self.all_target_columns
            if t not in exact_matches.values() and t not in openai_mappings.values()
        ]

        for source_col in remaining_sources:
            if source_col in openai_mappings:
                continue  # Already handled by OpenAI

            # Find best semantic match
            best_target = None
            best_score = 0.0

            if source_col in semantic_mappings:
                for target_col in remaining_targets:
                    score = semantic_mappings[source_col].get(target_col, 0)
                    if score > best_score:
                        best_score = score
                        best_target = target_col

            # Determine confidence level
            if best_score >= 0.7:
                confidence_level = "high"
            elif best_score >= 0.5:
                confidence_level = "medium"
            else:
                confidence_level = "low"
                best_target = None  # Don't map if confidence too low

            final_mappings[source_col] = {
                "target": best_target,
                "confidence_score": best_score,
                "confidence_level": confidence_level,
                "needs_review": confidence_level in ["low", "medium"],
                "method": "semantic" if best_target else "none",
            }

        # Create summary
        high_confidence = sum(
            1 for v in final_mappings.values() if v["confidence_level"] == "high"
        )
        needs_review = sum(1 for v in final_mappings.values() if v["needs_review"])

        print(f"\n📊 Final Mapping Summary:")
        print(f"   Total columns: {len(all_source_cols)}")
        print(f"   Exact matches: {len(exact_matches)}")
        print(f"   OpenAI matches: {len(openai_mappings)}")
        print(
            f"   Semantic matches: {len([v for v in final_mappings.values() if v.get('method') == 'semantic'])}"
        )
        print(f"   High confidence: {high_confidence}")
        print(f"   Needs review: {needs_review}")
        print(f"   Accuracy: {high_confidence / len(all_source_cols) * 100:.1f}%")

        return {
            "mappings": final_mappings,
            "summary": {
                "total_columns": len(all_source_cols),
                "high_confidence_mappings": high_confidence,
                "needs_review": needs_review,
                "accuracy_estimate": (
                    high_confidence / len(all_source_cols) if all_source_cols else 0
                ),
                "methods_used": {
                    "exact": len(exact_matches),
                    "openai": len(openai_mappings),
                    "semantic": len(
                        [
                            v
                            for v in final_mappings.values()
                            if v.get("method") == "semantic"
                        ]
                    ),
                },
            },
        }

    # ============================================================
    # EXISTING METHODS (Keep these unchanged)
    # ============================================================

    def _semantic_mapping(
        self, source_cols: List[str], target_cols: List[str]
    ) -> Dict[str, Dict[str, float]]:
        """Step 1: Better than simple string matching - understands meaning"""
        mappings = {}

        for source_col in source_cols:
            mappings[source_col] = {}
            source_clean = self._clean_and_expand(source_col)

            for target_col in target_cols:
                target_clean = self._clean_and_expand(target_col)
                similarity = self._calculate_semantic_similarity(
                    source_clean, target_clean
                )
                mappings[source_col][target_col] = similarity

        return mappings

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

    def _calculate_semantic_similarity(
        self, source_clean: str, target_clean: str
    ) -> float:
        """Calculate how similar two column names are semantically"""
        source_words = set(source_clean.split())
        target_words = set(target_clean.split())

        if not source_words or not target_words:
            return 0.0

        intersection = source_words & target_words
        union = source_words | target_words
        jaccard = len(intersection) / len(union)

        exact_matches = len(intersection)
        if exact_matches > 0:
            jaccard += 0.2 * exact_matches

        for source_word in source_words:
            for target_word in target_words:
                if source_word in target_word or target_word in source_word:
                    jaccard += 0.1

        return min(jaccard, 1.0)

    def _analyze_data_patterns(
        self, source_cols: List[str], sample_data: pd.DataFrame
    ) -> Dict[str, Dict[str, Any]]:
        """Step 2: Look at actual data to understand what each column contains"""
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

        return insights

    def _detect_value_pattern(self, series: pd.Series) -> str:
        """Detect specific patterns in the values"""
        if pd.api.types.is_numeric_dtype(series):
            min_val = series.min()
            max_val = series.max()

            if 50 <= min_val and max_val <= 500:
                return "typical_manhours"
            elif 0 <= min_val and max_val <= 5:
                return "typical_incidents"
            elif 80 <= min_val and max_val <= 100:
                return "high_percentage"

        return "general"

    def _guess_business_domain(self, col_name: str, data_series: pd.Series) -> str:
        """Guess which business domain this column belongs to"""
        col_lower = col_name.lower()

        for domain, info in self.operational_vocabulary.items():
            for keyword in info["keywords"]:
                if keyword in col_lower:
                    return domain

        return "general"

    def _apply_data_insights(
        self, semantic_mappings: Dict, data_insights: Dict, target_cols: List[str]
    ) -> Dict:
        """Step 3: Use data analysis to boost confidence of good mappings"""
        for source_col, insights in data_insights.items():
            data_type = insights["data_type"]
            business_domain = insights["business_domain"]

            for target_col in target_cols:
                current_score = semantic_mappings[source_col].get(target_col, 0)

                # Boost based on data type alignment
                if data_type == "percentage" and "%" in target_col:
                    semantic_mappings[source_col][target_col] = min(
                        current_score + 0.3, 1.0
                    )
                elif "manhour" in target_col.lower():
                    semantic_mappings[source_col][target_col] = min(
                        current_score + 0.3, 1.0
                    )
                elif "incident" in target_col.lower():
                    semantic_mappings[source_col][target_col] = min(
                        current_score + 0.3, 1.0
                    )

                # Boost based on business domain
                if business_domain in self.operational_vocabulary:
                    domain_targets = self.operational_vocabulary[business_domain][
                        "target_columns"
                    ]
                    if target_col in domain_targets:
                        semantic_mappings[source_col][target_col] = min(
                            current_score + 0.2, 1.0
                        )

        return semantic_mappings
