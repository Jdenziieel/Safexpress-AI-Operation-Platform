# 🎲 Multiple Response Generation (n Parameter)

## What Changed?

Added ability to generate **multiple LLM responses in one API call** using the `n` parameter. Perfect for testing consistency and exploring variations.

---

## How It Works

### Before (Single Response):
```python
llm_response = self.llm.invoke(...)  # Returns 1 response
```

### After (Multiple Responses):
```python
llm_responses = self.llm.generate(..., n=5)  # Returns 5 responses
```

---

## Configuration

### Option 1: Use `test_unified_quick.py` (Easiest)

```python
# Edit these two variables:
USER_MESSAGE = "cancel and send email to john"
N_RESPONSES = 5  # 👈 Number of variations to generate
```

Run:
```bash
python test_unified_quick.py
```

---

### Option 2: Create Agent with Custom N

```python
from conversational_agent import ConversationalAgent

agent = ConversationalAgent(
    openai_api_key="your-key",
    test_mode=True,
    test_n_responses=10  # 👈 Generate 10 different responses
)
```

---

## JSON Output Format

**Before (Single Response):**
```json
{
    "category": "confirmation",
    "confidence": "high",
    "reasoning": "Clear approval",
    ...
}
```

**After (Multiple Responses):**
```json
{
    "count": 3,
    "responses": [
        {
            "category": "cancellation",
            "confidence": "high",
            "reasoning": "Compound cancel with new task",
            "has_compound_cancel": true
        },
        {
            "category": "cancellation",
            "confidence": "high",
            "reasoning": "Compound cancel with new task",
            "has_compound_cancel": true
        },
        {
            "category": "cancellation",
            "confidence": "high",
            "reasoning": "Compound cancel with new task",
            "has_compound_cancel": true
        }
    ]
}
```

---

## Use Cases

### 1. **Consistency Testing**
Generate 10 responses to check if LLM is consistent:
```python
N_RESPONSES = 10
USER_MESSAGE = "yes"

# Check if all 10 responses have same category
```

### 2. **Edge Case Exploration**
Test ambiguous messages:
```python
N_RESPONSES = 5
USER_MESSAGE = "maybe later"

# See how LLM interprets uncertain input
```

### 3. **Variation Analysis**
Complex compound messages:
```python
N_RESPONSES = 5
USER_MESSAGE = "cancel and search emails from john"

# Check if all detect compound_cancel
```

---

## Cost Considerations

⚠️ **Important:** Each response costs tokens!

| N Responses | Cost Multiplier | Example Cost (500 tokens) |
|-------------|-----------------|---------------------------|
| 1 (default) | 1x              | $0.0025                   |
| 3           | 3x              | $0.0075                   |
| 5           | 5x              | $0.0125                   |
| 10          | 10x             | $0.0250                   |

**Recommendation:**
- Development: Use `n=3-5` for quick testing
- Production: Use `n=1` (default)
- Consistency checks: Use `n=10` occasionally

---

## How to Use Different Values

### Test 1 Response (Cheapest):
```python
N_RESPONSES = 1
```

### Test 3 Responses (Good balance):
```python
N_RESPONSES = 3
```

### Test 10 Responses (Thorough testing):
```python
N_RESPONSES = 10
```

---

## Analyzing Results

### Check Consistency:
```python
# Load JSON
import json
with open("Unified_LLM_results.json") as f:
    data = json.load(f)

# Count categories
from collections import Counter
categories = [r['category'] for r in data['responses']]
print(Counter(categories))

# Example output:
# Counter({'cancellation': 10})  ✅ 100% consistent
# Counter({'cancellation': 7, 'task_request': 3})  ⚠️ Inconsistent!
```

### Find Variations:
```python
# Find unique reasonings
reasonings = set(r['reasoning'] for r in data['responses'])
print(f"Found {len(reasonings)} different reasoning variations")

for i, reason in enumerate(reasonings, 1):
    print(f"{i}. {reason}")
```

---

## Quick Examples

### Example 1: Test Confirmation Consistency
```python
USER_MESSAGE = "yes"
N_RESPONSES = 5

# Expected: All 5 should return category="confirmation"
```

### Example 2: Test Ambiguous Input
```python
USER_MESSAGE = "ok maybe"
N_RESPONSES = 5

# Check: Do some return "confirmation" and others "casual_conversation"?
```

### Example 3: Test Compound Cancel Detection
```python
USER_MESSAGE = "cancel and send email to sarah"
N_RESPONSES = 10

# Check: Do all 10 detect has_compound_cancel=true?
```

---

## Modified Files

1. **conversational_agent.py**:
   - Added `test_n_responses` parameter to `__init__` (line 88)
   - Modified `_unified_quick_check()` to use `llm.generate(n=N)` (line 490)
   - Returns array of results instead of single result in test mode

2. **test_unified_quick.py**:
   - Added `N_RESPONSES` configuration variable
   - Updated output message to show number of responses

---

## Disabling Multiple Responses

### For Normal Operation (Production):
```python
# Don't set test_mode
agent = ConversationalAgent(
    openai_api_key="your-key"
    # test_mode=False by default
)
```

### For Single Response Testing:
```python
agent = ConversationalAgent(
    openai_api_key="your-key",
    test_mode=True,
    test_n_responses=1  # Just 1 response
)
```

---

## Benefits

✅ **Test Consistency** - See if LLM gives same answer multiple times
✅ **Explore Variations** - Discover edge cases in reasoning
✅ **Quality Assurance** - Validate prompt engineering
✅ **No Code Changes** - Just change N_RESPONSES variable
✅ **All in JSON** - Easy to analyze programmatically

---

## Tips

1. **Start Small**: Use `n=3` first, then increase if needed
2. **Check Costs**: Remember each response costs tokens
3. **Analyze Patterns**: Look for inconsistencies in category/reasoning
4. **Use for Ambiguous Cases**: Most valuable for unclear inputs
5. **Compare Reasonings**: Different LLM "thoughts" reveal prompt issues

---

## Summary

**What:** Generate multiple LLM responses in one API call
**Where:** `test_n_responses` parameter in `ConversationalAgent.__init__()`
**Why:** Test consistency, explore variations, improve prompts
**Cost:** Multiplies token costs by N (use wisely!)
**Best Practice:** Use n=3-5 for development, n=1 for production
