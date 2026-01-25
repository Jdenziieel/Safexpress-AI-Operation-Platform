# 📑 Delivery Order Email Search - Documentation Index

## 🎯 Start Here

**New to this feature?** Start with one of these:

1. **⚡ [QUICK_REFERENCE.md](QUICK_REFERENCE.md)** (5 min read)
   - Function signature
   - Common usage patterns
   - Copy-paste examples

2. **📖 [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md)** (20 min read)
   - Complete API documentation
   - All parameters explained
   - 8+ usage examples
   - Troubleshooting guide

3. **💡 [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py)** (10 min read)
   - 8 runnable example functions
   - Real-world patterns
   - Error handling demos

---

## 📂 Files at a Glance

### Code Files
| File | What It Is | Changes |
|------|-----------|---------|
| [tools.py](tools.py) | Gmail agent tools | ✅ Added function (lines 1208-1428) |
| [api.py](api.py) | FastAPI endpoints | ✅ Import + TOOL_MAP registration |

### Documentation Files
| File | Purpose | Read Time |
|------|---------|-----------|
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | ⚡ Quick start cheat sheet | 5 min |
| [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md) | 📖 Complete documentation | 20 min |
| [DELIVERY_ORDER_IMPLEMENTATION.md](DELIVERY_ORDER_IMPLEMENTATION.md) | 📋 Overview & details | 10 min |
| [DELIVERABLES.md](DELIVERABLES.md) | 📦 Full deliverables list | 10 min |
| [DELIVERY_ORDER_FEATURE_COMPLETE.md](../DELIVERY_ORDER_FEATURE_COMPLETE.md) | ✅ Summary | 5 min |

### Test Files
| File | Purpose | Examples |
|------|---------|----------|
| [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py) | Runnable examples | 8 patterns |

---

## 🔍 Find What You Need

### I want to...

#### 📝 **Use the function quickly**
→ Read [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
- Copy-paste code snippets
- Common parameter patterns
- Error handling checklist

#### 🎓 **Understand all the details**
→ Read [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md)
- Complete parameter documentation
- Return value structure
- 8+ examples with explanations
- Performance considerations
- Troubleshooting section

#### 💻 **See working code examples**
→ Check [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py)
- 8 different usage patterns
- Error handling examples
- File processing examples
- API integration examples
- Cleanup examples

#### 🚀 **Get started immediately**
→ Quick start section below

#### 🐛 **Debug or troubleshoot**
→ [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#troubleshooting)
- Common issues
- Solutions
- Tips

#### 🔗 **Integrate with my app**
→ [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#api-integration)
- API endpoint usage
- Python SDK examples
- Request/response format

#### 📊 **Process downloaded files**
→ [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#downstream-processing)
- PDF extraction
- Excel data processing
- Database integration

---

## ⚡ Quick Start

### Minimal Example
```python
from tools import _search_emails_with_delivery_order_attachments_impl

result = _search_emails_with_delivery_order_attachments_impl(
    credentials_dict=your_oauth_credentials
)

print(result)
```

### Check Results
```python
if result["success"]:
    print(f"Found {result['total_attachments_downloaded']} files")
    print(f"Saved to: {result['temp_directory']}")
else:
    print(f"Error: {result['error']}")
```

### Process Files
```python
for email in result["emails_with_attachments"]:
    print(f"From: {email['from']}")
    for attachment in email['attachments']:
        print(f"  {attachment['filename']} → {attachment['file_path']}")
```

### Via API
```bash
curl -X POST http://localhost:8000/execute_task \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "search_emails_with_delivery_order_attachments",
    "inputs": {"query": "delivery order"},
    "credentials_dict": {"access_token": "...", "refresh_token": "..."}
  }'
```

---

## 📚 Documentation Organization

### Level 1: Quick Reference (5 min)
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
- Common patterns
- Parameter table
- Error checklist

### Level 2: Getting Started (10 min)
- [DELIVERY_ORDER_IMPLEMENTATION.md](DELIVERY_ORDER_IMPLEMENTATION.md)
- What was built
- How to use it
- Key features

### Level 3: Complete Guide (20 min)
- [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md)
- All parameters
- Complete examples
- Troubleshooting

### Level 4: Examples & Testing (10 min)
- [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py)
- 8 runnable examples
- Real-world patterns

---

## 🎯 By Use Case

### Use Case: Basic Search
**Goal**: Find and download all delivery orders

📖 **Guide**: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#basic-usage---search-for-delivery-orders)  
💡 **Example**: [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py#L4-L18)  
⚡ **Quick**: [QUICK_REFERENCE.md](QUICK_REFERENCE.md#pattern-1-simple-search--download)

---

### Use Case: Custom Supplier Search
**Goal**: Find orders from specific suppliers

📖 **Guide**: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#custom-query)  
💡 **Example**: [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py#L22-L39)  
⚡ **Quick**: [QUICK_REFERENCE.md](QUICK_REFERENCE.md#pattern-2-custom-query)

---

### Use Case: Get Metadata Only
**Goal**: Check what's available without downloading

📖 **Guide**: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#metadata-only-no-downloads)  
💡 **Example**: [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py#L43-L61)  
⚡ **Quick**: [QUICK_REFERENCE.md](QUICK_REFERENCE.md#pattern-3-metadata-only)

---

### Use Case: Process Downloaded Files
**Goal**: Download and process with pandas

📖 **Guide**: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#downstream-processing)  
💡 **Example**: [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py#L155-L175)  

---

### Use Case: API Integration
**Goal**: Call from external application

📖 **Guide**: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#api-integration)  
💡 **Example**: [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py#L179-L215)  
⚡ **Quick**: [QUICK_REFERENCE.md](QUICK_REFERENCE.md#via-api-endpoint)

---

### Use Case: Error Handling
**Goal**: Build robust error handling

📖 **Guide**: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#error-handling)  
💡 **Example**: [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py#L219-L247)  

---

## 🔗 Cross-References

### Return Value Structure
- Full details: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#return-value)
- Quick reference: [QUICK_REFERENCE.md](QUICK_REFERENCE.md#return-value-fields-reference)
- Implementation notes: [DELIVERY_ORDER_IMPLEMENTATION.md](DELIVERY_ORDER_IMPLEMENTATION.md#return-value-structure)

### Parameters
- Full documentation: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#parameters)
- Quick table: [QUICK_REFERENCE.md](QUICK_REFERENCE.md#key-parameters)
- Implementation: [DELIVERY_ORDER_IMPLEMENTATION.md](DELIVERY_ORDER_IMPLEMENTATION.md)

### File Types Supported
- Complete list: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#supported-file-types)
- Quick reference: [QUICK_REFERENCE.md](QUICK_REFERENCE.md#supported-file-types)

### Error Scenarios
- Complete guide: [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md#error-handling)
- Quick checklist: [QUICK_REFERENCE.md](QUICK_REFERENCE.md#error-scenarios)

---

## 📊 Documentation Statistics

| Document | Lines | Sections | Examples |
|----------|-------|----------|----------|
| QUICK_REFERENCE.md | ~400 | 10+ | 5+ |
| DELIVERY_ORDER_SEARCH_GUIDE.md | ~500 | 15+ | 8+ |
| DELIVERY_ORDER_IMPLEMENTATION.md | ~250 | 10+ | 5+ |
| test_delivery_order_examples.py | ~300 | 8 | 8 |
| DELIVERABLES.md | ~300 | 12+ | Multiple |

---

## ✅ Checklist

Before using the function, make sure you have:

- ✅ Read [QUICK_REFERENCE.md](QUICK_REFERENCE.md) (5 minutes)
- ✅ Reviewed one example from [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py)
- ✅ Prepared your OAuth2 credentials
- ✅ (Optional) Read full [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md) for advanced usage

---

## 🚀 You're Ready!

Pick your starting point:

| Goal | Start With |
|------|-----------|
| **Use it right now** | [QUICK_REFERENCE.md](QUICK_REFERENCE.md) |
| **Understand everything** | [DELIVERY_ORDER_SEARCH_GUIDE.md](DELIVERY_ORDER_SEARCH_GUIDE.md) |
| **See it in action** | [test/test_delivery_order_examples.py](test/test_delivery_order_examples.py) |
| **Get the details** | [DELIVERY_ORDER_IMPLEMENTATION.md](DELIVERY_ORDER_IMPLEMENTATION.md) |
| **Check deliverables** | [DELIVERABLES.md](DELIVERABLES.md) |

---

## 📞 Support

All documentation is in this directory. Each file is self-contained and complete.

For quick answers, use the quick reference.  
For detailed information, use the complete guide.  
For working code, check the examples.

---

**Implementation Status**: ✅ **COMPLETE & READY**

Start with [QUICK_REFERENCE.md](QUICK_REFERENCE.md) and you'll be up and running in 5 minutes!
