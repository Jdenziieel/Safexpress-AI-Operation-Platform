"""JSON schemas for PDF parsing API requests and responses."""

JSON_SCHEMA = """{
  "chunks": [
    {
      "text": "string",
      "metadata": {
        "type": "heading|paragraph|list|table|image",
        "section": "string",
        "section_title": "string",
        "parent_section": "string",
        "context": "string (maximum one sentence)",
        "tags": ["string"],
        "continues": "boolean",
        "is_page_break": "boolean",
        "siblings": ["string"],  
        "page": "integer"
      }
    }
  ]
}"""

ENHANCED_CHUNKING_INSTRUCTIONS = """
**CRITICAL: SECTION FIELD REQUIREMENTS**

The "section" field MUST follow these strict rules:

1. **Section Numbering Format**:
   - Main sections: Use just the number (e.g., "1", "2", "3")
   - Subsections: Use dot notation (e.g., "1.1", "2.3", "3.1")
   - Sub-subsections: Use extended dots (e.g., "1.1.1", "3.2.1")
   - For unnumbered sections: Use descriptive names ("Introduction", "Conclusion", "Appendix A")

2. **Section Title** (NEW FIELD):
   - Extract the FULL section title text (e.g., "Transportation & Fleet Safety")
   - For subsections, include the subsection title (e.g., "Driver Fitness and Vehicle Condition")
   - This helps with semantic matching when section numbers alone aren't descriptive

3. **Parent Section** (NEW FIELD):
   - For subsections, ALWAYS include the parent section number
   - Examples:
     * If section="3.1", then parent_section="3"
     * If section="2.3.4", then parent_section="2.3"
     * If section="1", then parent_section="" (empty for top-level)
   - This creates a clear hierarchy for search and retrieval

4. **Section Inheritance**:
   - Content under "3.1 Driver Fitness" belongs to BOTH section "3.1" AND parent section "3"
   - When a user asks about "Section 3", they want ALL content including 3.1, 3.2, etc.
   - Always populate parent_section so queries can find related content

5. **Context Field Requirements**:
   - Must be ONE concise sentence (max 15 words)
   - Describe what information this chunk contains, not just restate the heading
   - Examples:
     * Good: "Requirements for driver licensing and vehicle inspections"
     * Bad: "Section about drivers"
     * Good: "Procedures for reporting workplace accidents and incidents"
     * Bad: "Accident reporting"

6. **Tags Field Requirements**:
   - Extract 3-7 relevant keywords from the chunk
   - Include both specific terms (e.g., "DVIR", "PPE") and general concepts (e.g., "safety", "training")
   - Include parent section topics for subsections
   - Examples:
     * For section 3.1 about driver fitness: ["transportation", "fleet", "driver", "license", "vehicle", "inspection", "safety"]
     * For section 2.1 about PPE: ["warehouse", "safety", "ppe", "equipment", "protective", "requirements"]

7. **Type Field Requirements**:
   - heading: Section/subsection titles (typically < 100 characters)
   - paragraph: Continuous prose text (typically 100-2000 characters)
   - list: Bulleted or numbered lists (keep items together)
   - table: Tabular data — ALWAYS keep the ENTIRE table (header + all rows) as ONE single chunk. NEVER split a table into separate row chunks.
   - image: Visual content references

**Key Principles:**
- Subsection chunks MUST have parent_section filled to enable hierarchical search
- Tags should include BOTH parent section concepts AND specific chunk topics
- Context should be actionable and descriptive, not just labels
- Section titles help with semantic matching when numbers don't
"""
