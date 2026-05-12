// SafexpressOps UAT v3 (Feature-Scale) - combined Google Form generator
// One form: branded info header + required Data Privacy Agreement +
// role-branched Parts 1-5 of UAT-FeatureScale.docx (Admin / Manager / User).
//
// Source of truth: Documents/UAT-FeatureScale.docx (Parts 1-5 only — Part 6
// sign-off and Appendices A/B/C are out of scope for the form).
//
// Question types:
//   - Functional acceptance (Part 2.x) — Yes / No / N/A
//   - SUS (Part 1), Quality (Part 3), Adoption (Part 4) — 5-point Likert + N/A
//   - Open-ended (Part 5) — paragraph free text
//
// Role applicability (per the "Applies to:" tags in the docx):
//   - Part 2.3 AI Assistant     → Admin + Manager only (User skips)
//   - Part 2.8 KB Management    → Admin only
//   - Part 2.9 Account/Activity → Admin only
//   - All other sections        → ALL roles
//
// Paste into https://script.google.com → New project → save → Run createUATForm.

// =====================================================================
// CHOICE PRESETS
// =====================================================================
var YESNO_CHOICES = ["Yes", "No", "N/A"];
var LIKERT_CHOICES = [
  "1 - Strongly Disagree",
  "2 - Disagree",
  "3 - Neutral",
  "4 - Agree",
  "5 - Strongly Agree",
  "N/A"
];

// =====================================================================
// QUESTION BANKS (single source of truth — shared across roles)
// =====================================================================

// Part 1 — System Usability Scale (10 items, Likert, ALL roles)
var SUS_ITEMS = [
  "1.  I think that I would like to use SafexpressOps frequently.",
  "2.  I found SafexpressOps unnecessarily complex.",
  "3.  I thought SafexpressOps was easy to use.",
  "4.  I think that I would need the support of a technical person to use SafexpressOps.",
  "5.  I found the various functions in SafexpressOps were well integrated.",
  "6.  I thought there was too much inconsistency in SafexpressOps.",
  "7.  I would imagine that most people would learn to use SafexpressOps very quickly.",
  "8.  I found SafexpressOps very cumbersome to use.",
  "9.  I felt very confident using SafexpressOps.",
  "10. I needed to learn a lot of things before I could get going with SafexpressOps."
];

// Part 2.1 — Authentication, Roles, Access (Yes/No, ALL roles)
var FUNC_2_1_AUTH = [
  "Were you able to sign in to SafexpressOps using your Google account without needing technical help?",
  "Did the role-based access correctly match your job — you were not exposed to features outside your role, and you had access to everything you needed?",
  "Could you find and read your profile, role badge, and current token / quota usage easily?",
  "Did logging out and logging back in work cleanly, with your chat history and saved work preserved?"
];

// Part 2.2 — SFX Bot (Yes/No, ALL roles)
var FUNC_2_2_SFX = [
  "Did SFX Bot answer your company-knowledge questions accurately when the answer existed in the knowledge base?",
  "Did SFX Bot's responses include citations (filename, page) that pointed to the correct source document?",
  "When you asked something NOT in the knowledge base, did SFX Bot say so instead of guessing?",
  "Did SFX Bot keep the context of your conversation across multiple back-and-forth messages in the same thread?",
  "Could you create, switch between, rename, and delete chat sessions, with only your own sessions visible to you?",
  "Did SFX Bot stream responses in real time, and could you stop a streaming response if you no longer needed it?"
];

// Part 2.3 — AI Assistant (Yes/No, Admin + Manager ONLY)
var FUNC_2_3_AI_ASSISTANT = [
  "Did the AI Assistant correctly perform the Gmail tasks you asked of it (draft, send, reply, forward, search, manage labels)?",
  "Did the AI Assistant correctly perform the Google Calendar tasks you asked of it (create, view, update, delete events; invite attendees; generate Meet links)?",
  "Did the AI Assistant correctly perform the Google Drive tasks you asked of it (upload files, create / name folders, list, search, download)?",
  "Did the AI Assistant correctly perform the Google Docs / Sheets tasks you asked of it (create, edit, read, format)?",
  "Did the AI Assistant successfully complete multi-step workflows (e.g. 'find the latest delivery-order email, extract the PDF, push to my sheet') in a single chat turn?",
  "Were dangerous actions (sending emails, deleting events, etc.) always shown to you for explicit approval before they ran?",
  "After you approved or rejected an action, did the AI Assistant continue the workflow correctly without losing earlier context?",
  "Within the same chat session, did the AI Assistant retain the context of your conversation — so you did not have to re-explain earlier instructions or repeat information already provided in the same thread?",
  "Could you see real-time progress updates while the AI Assistant worked — including the current stage (Analyzing / Planning / Executing / Composing), the step / tool name, the step counter (e.g. Step 2 of 3), and the elapsed time?"
];

// Part 2.4 — Dynamic Mapping (Yes/No, ALL roles)
var FUNC_2_4_DYNAMIC_MAPPING = [
  "Could you upload Excel (.xlsx) and CSV source files, with the system rejecting unsupported types (.txt, .png, etc.) and corrupt files using clear error messages?",
  "When your source Excel had multiple sheets, did the system auto-detect them, auto-select the best match when one sheet clearly dominated, and show a sheet-picker when the choice was ambiguous?",
  "When your source contained multiple stacked data sections (title row + header row + data rows, repeated), did the system detect them and let you select the correct section?",
  "Could you paste a Google Sheets URL into the target field, see all tabs listed (with the URL's gid pre-selected if present), and have tab names with spaces still resolved correctly?",
  "Did the AI propose accurate column mappings — matching exact column names without an AI call, and using AI for synonyms (e.g. 'Qty' to 'Quantity') — and correctly choose the row-anchor strategy (date, entity, composite key, label/value, horizontal, or cross_tab) for the target layout?",
  "Before writing, did the system show a preview with the cell-level diff (current value vs new value), updated-row vs appended-row counts, and formula columns excluded from the diff — and could you deselect individual rows to skip them?",
  "After you confirmed, did the system write into the correct rows / columns / sections, report the number of rows updated and appended, preserve formula cells, and refuse to write when all rows had been deselected?",
  "Could you save and reload named column-mapping templates, with only your own (or your team's) templates visible?",
  "When something went wrong (no columns matched, Google auth error, zero rows updated), did the system surface a clear actionable message instead of a stack trace?"
];

// Part 2.5 — ABC Analysis (Yes/No, ALL roles)
var FUNC_2_5_ABC = [
  "Could you upload an Excel (.xlsx) transaction file with sensible defaults pre-filled (Date column = Transdate, Item column = Itemcode, Quantity = Qtyordered, plus Description and UOM), and have non-Excel / empty files rejected with a clear message?",
  "Could you change the Date / Item / Quantity / Description / UOM column names to match your file's headers — and if you entered a column that did not exist, did the system clearly report the missing column instead of crashing?",
  "Could you set custom Class A and Class B cumulative thresholds (default 70% / 90%) and have the system warn you or block running when A-threshold was greater than or equal to B-threshold?",
  "Did the system automatically detect all months present in the date column without manual configuration, label them correctly (e.g. 'Jan 2025'), and run successfully even when the file covered only a single month?",
  "Did the classification result give each item exactly one class (A / B / C), rank items by combined score (quantity multiplied by order count), show monotonically increasing cumulative percentages, and surface all required per-item columns (Rank, Item Code, Description, UOM, Total Qty, Order Count, Item Score, Percentage, Cumulative Pct, Class) plus a monthly comparison and an Executive Summary?",
  "After running, was a new Google Sheet auto-created with all required tabs (Executive Summary, Monthly Comparison, Complete ABC Analysis, Class A / B / C, plus one tab per detected month), all openable without permission errors via the provided link?",
  "Could you view a history list of your past ABC analyses, re-open any past result, and only see your own (not other users') analyses?"
];

// Part 2.6 — One-Page Report / OPR (Yes/No, ALL roles)
var FUNC_2_6_OPR = [
  "Could you upload an Excel (.xlsx) or CSV daily-operations file, with PDFs / images / corrupt files rejected via a specific error message and the filename + size shown so you could confirm the correct file?",
  "Did the system correctly find and parse the Date column, recognise common date formats (Excel-style, ISO, US, dotted), skip blank or unparseable rows gracefully, and report the count of dates extracted (e.g. '31 dates extracted')?",
  "Did the SmartMappingEngine produce accurate mappings — via Tier 0 forced typo corrections (e.g. 'Toal Manhours' to 'Total Manhours'), Tier 1 exact match, Tier 2 Levenshtein similarity, Tier 3 OpenAI fallback — while preserving formula columns, never confusing Inbound vs Outbound or Manhours vs Safe-Manhours, and showing a confidence score per source-target column pair?",
  "Did the mapping preview list every column with its proposed target and confidence, flag low-confidence mappings for review, allow you to override or 'Skip' any mapping via a dropdown, show a cell-level diff (current vs new value) excluding formula cells, and report matched-vs-unmatched date counts?",
  "After you confirmed, did the system write the data into the 'DATA ENTRY' sheet using exactly your approved mappings (no AI re-run), update only matching dates with cell-level writes that preserve formula cells in the same row, and report the number of rows and cells updated?",
  "When errors occurred (no source columns mapped to the target, zero matching dates between source and sheet, Google auth error, header-only file with no data rows), did the system surface a clear actionable message — including a sample of the file's dates for the zero-date-match case?",
  "Could you view a history list of your past OPR processings (filename, date processed, rows updated), re-open any past record to review what was written, and only see your own (not other users') OPR records?"
];

// Part 2.7 — Workload Analysis (Yes/No, ALL roles)
var FUNC_2_7_WORKLOAD = [
  "Did the Workload Analysis page load with at least one item row by default, and could you add new item rows, fill in description / pallets / items per pallet, and remove rows (with at least one row always remaining)?",
  "Could you expand the warehouse rate settings, see the default phase rates loaded, and edit the rates for Inbound Checking, Put-away, Picking, and Outbound Checking?",
  "When you clicked Calculate Workload with valid data, did the system produce totals (time, pallets, items, workers) plus a per-phase breakdown, with totals matching the inputs (total pallets equals entered pallet count; total items equals pallets multiplied by items per pallet)?",
  "If required data was missing (no item data or empty workers field), did the system stop the calculation and show a clear message?",
  "Could you export the result to PDF with the summary, phase breakdown, and items breakdown all included?",
  "Could you save the calculation to the database when the backend was connected, with the Save button correctly disabled when no result existed or when the backend was offline — and could you still calculate using the loaded default rates while offline, with the offline state communicated clearly?"
];

// Part 2.8 — Knowledge Base management (Yes/No, Admin ONLY)
var FUNC_2_8_KB_MGMT = [
  "Could you upload a PDF, see it parsed into chunks with proper structure (headings, tables, embedded images), and edit chunks if needed before pushing to the knowledge base?",
  "Did the Document Extraction interface show a real-time PDF preview with page navigation and side-by-side highlight overlay marking where each chunk came from on the page?",
  "Did the system detect duplicate uploads (by content hash and filename) and warn you before re-processing?",
  "Could you see KB analytics (queries per document, token usage, popular topics) in a clear dashboard?",
  "After you pushed a new document, was SFX Bot able to answer questions about it and cite it correctly?"
];

// Part 2.9 — Account and activity management (Yes/No, Admin ONLY)
var FUNC_2_9_ACCOUNT = [
  "Could you onboard new accounts (set name, email, role) and have the new user sign in immediately?",
  "Could you edit, deactivate, and reactivate accounts cleanly, with chat history preserved across reactivation?",
  "Could you review activity logs by user, time window, or action type to support audit / compliance?",
  "Could you set per-user token quotas and confirm they were enforced when the user crossed the limit?",
  "Could you review and approve or reject pending dangerous actions from a single queue?"
];

// Part 3 — Quality scale (Likert, ALL roles)
var QUALITY_ITEMS = [
  "Q1. The system gave me clear, actionable error messages when something went wrong — not technical jargon or stack traces.",
  "Q2. When the system was unsure about my request, it asked me to clarify rather than guessing.",
  "Q3. Dangerous actions never ran without my explicit approval.",
  "Q4. I felt confident that my data and credentials were handled securely.",
  "Q5. I was only able to see and act on what my role allows. I was never exposed to other users' data or features outside my role.",
  "Q6. SafexpressOps worked properly on the device and browser I normally use at work.",
  "Q7. The system responded fast enough that I did not lose my train of thought waiting for it.",
  "Q8. Quota / usage indicators were clear, so I never ran out of capacity unexpectedly."
];

// Part 4 — Adoption / business outcome scale (Likert, ALL roles)
var ADOPTION_ITEMS = [
  "B1. I believe SafexpressOps would save me significant time on my recurring tasks.",
  "B2. I would trust the system's outputs (reports, mapped data, drafted emails) for my real work.",
  "B3. I would adopt SafexpressOps in my daily work if it were available tomorrow.",
  "B4. I could learn to use SafexpressOps effectively WITHOUT formal training.",
  "B5. I would recommend SafexpressOps to my SLI colleagues.",
  "B6. Compared to my current process, SafexpressOps is a meaningful improvement (not just a different way to do the same thing)."
];

// Part 5 — Open-ended (paragraph text, ALL roles)
var OPEN_ENDED_ITEMS = [
  {
    title: "Top 3 things you LIKED about SafexpressOps",
    help: "List up to three. Specific examples are most useful (which page, which feature, what made it good)."
  },
  {
    title: "Top 3 things that FRUSTRATED you while using SafexpressOps",
    help: "List up to three. Specific examples are most useful (which page, which step, what went wrong)."
  },
  {
    title: "ONE feature that, if added or improved, would make SafexpressOps indispensable for your job",
    help: "Be specific. \"AI Assistant should remember my last template across sessions\" is more useful than \"better memory\"."
  }
];

// =====================================================================
// HELPERS
// =====================================================================
function addYesNoBlock(form, items) {
  for (var i = 0; i < items.length; i++) {
    form.addMultipleChoiceItem()
        .setTitle(items[i])
        .setChoiceValues(YESNO_CHOICES)
        .setRequired(false);
  }
}

function addLikertBlock(form, items) {
  for (var i = 0; i < items.length; i++) {
    form.addMultipleChoiceItem()
        .setTitle(items[i])
        .setChoiceValues(LIKERT_CHOICES)
        .setRequired(false);
  }
}

function addOpenEndedBlock(form, items) {
  for (var i = 0; i < items.length; i++) {
    form.addParagraphTextItem()
        .setTitle(items[i].title)
        .setHelpText(items[i].help)
        .setRequired(false);
  }
}

// =====================================================================
// PER-ROLE PIPELINE BUILDER
//
// Adds the page sequence applicable to `role` and returns
// { first, last } so the caller can wire role-dropdown choices and
// the final-page jump.
// =====================================================================
function buildRolePipeline(form, role, prefix) {
  var firstPage = null;
  var lastPage  = null;

  function newPage(title, help) {
    var p = form.addPageBreakItem().setTitle("[" + prefix + "] " + title);
    if (help) p.setHelpText(help);
    if (!firstPage) firstPage = p;
    lastPage = p;
    return p;
  }

  // ---- Part 1 — SUS (ALL roles) ----
  newPage(
    "Part 1 — System Usability Scale (SUS)",
    "Industry-standard 10-item Likert scale. Answer based on your first reaction. Every item applies to every tester — use the 1-5 scale, NOT N/A."
  );
  addLikertBlock(form, SUS_ITEMS);

  // ---- Part 2 — Functional acceptance (Yes/No) ----
  // Section 2.1 — Authentication (ALL)
  newPage(
    "Part 2.1 — Authentication, roles, and access",
    "Applies to: ALL roles. Tick Yes if the feature behaved as the question describes during your hands-on session. Use N/A if you did not exercise the feature."
  );
  addYesNoBlock(form, FUNC_2_1_AUTH);

  // Section 2.2 — SFX Bot (ALL)
  newPage(
    "Part 2.2 — SFX Bot (knowledge base Q&A)",
    "Applies to: ALL roles."
  );
  addYesNoBlock(form, FUNC_2_2_SFX);

  // Section 2.3 — AI Assistant (Admin + Manager ONLY)
  if (role === "Admin" || role === "Manager") {
    newPage(
      "Part 2.3 — AI Assistant (personal productivity / Google Workspace)",
      "Applies to: Administrator and Manager only. Users skip this section entirely."
    );
    addYesNoBlock(form, FUNC_2_3_AI_ASSISTANT);
  }

  // Section 2.4 — Dynamic Mapping (ALL)
  newPage(
    "Part 2.4 — Dynamic Mapping",
    "Applies to: ALL roles."
  );
  addYesNoBlock(form, FUNC_2_4_DYNAMIC_MAPPING);

  // Section 2.5 — ABC Analysis (ALL)
  newPage(
    "Part 2.5 — ABC Analysis",
    "Applies to: ALL roles."
  );
  addYesNoBlock(form, FUNC_2_5_ABC);

  // Section 2.6 — OPR (ALL)
  newPage(
    "Part 2.6 — One-Page Report (OPR)",
    "Applies to: ALL roles."
  );
  addYesNoBlock(form, FUNC_2_6_OPR);

  // Section 2.7 — Workload Analysis (ALL)
  newPage(
    "Part 2.7 — Workload Analysis",
    "Applies to: ALL roles."
  );
  addYesNoBlock(form, FUNC_2_7_WORKLOAD);

  // Section 2.8 — KB Management (Admin ONLY)
  if (role === "Admin") {
    newPage(
      "Part 2.8 — Knowledge Base management",
      "Applies to: Administrator only. Manager and User skip this section entirely."
    );
    addYesNoBlock(form, FUNC_2_8_KB_MGMT);
  }

  // Section 2.9 — Account & Activity (Admin ONLY)
  if (role === "Admin") {
    newPage(
      "Part 2.9 — Account and activity management",
      "Applies to: Administrator only. Manager and User skip this section entirely."
    );
    addYesNoBlock(form, FUNC_2_9_ACCOUNT);
  }

  // ---- Part 3 — Quality scale (Likert, ALL) ----
  newPage(
    "Part 3 — Quality scale (Reliability, Security, Compatibility, Efficiency)",
    "These items measure how well the system behaves overall, in your perception. Answer on the 1-5 scale."
  );
  addLikertBlock(form, QUALITY_ITEMS);

  // ---- Part 4 — Adoption scale (Likert, ALL) ----
  newPage(
    "Part 4 — Adoption and business outcome scale",
    "These items measure whether you would actually USE the system. The aggregate score here is the most important signal of whether SafexpressOps is ready to deploy at SLI."
  );
  addLikertBlock(form, ADOPTION_ITEMS);

  // ---- Part 5 — Open-ended (ALL) ----
  newPage(
    "Part 5 — Open-ended feedback",
    "Free-text answers. The project lead will run thematic analysis across all testers' responses to surface recurring issues that the Yes/No and Likert items alone cannot capture."
  );
  addOpenEndedBlock(form, OPEN_ENDED_ITEMS);

  return { first: firstPage, last: lastPage };
}

// =====================================================================
// MAIN ENTRY
// =====================================================================
function createUATForm() {
  var form = FormApp.create("SafexpressOps — User Acceptance Test (Feature-Scale)");

  form.setDescription(
    "Greetings from the SafexpressOps capstone team!\n\n" +
    "Thank you for participating in the User Acceptance Test (UAT) of SafexpressOps — the AI-powered logistics support platform that combines a company-aware Knowledge Base + chatbot (SFX Bot), an AI Assistant for Google Workspace tasks, Dynamic Mapping, ABC / OPR / Workload analysis reports, and admin / quota management.\n\n" +
    "This UAT measures user acceptance of every shipped feature using a mix of Yes / No items (Part 2 — functional acceptance) and 5-point Likert items (Parts 1, 3, 4 — usability, quality, adoption). Part 5 collects open-ended feedback. Please test each feature available to your role during a 30-45 minute hands-on session, then complete this form independently.\n\n" +
    "Your email address will be recorded automatically when you submit. The submission date and time are also captured automatically.\n\n" +
    "Estimated completion time:\n" +
    "  • User: ~25-30 minutes (~66 questions)\n" +
    "  • Manager: ~30-35 minutes (~75 questions)\n" +
    "  • Administrator: ~35-45 minutes (~85 questions)\n\n" +
    "Source-of-truth document: UAT-FeatureScale.docx (Parts 1-5). Part 6 (formal sign-off) and the appendices live in the docx and are aggregated separately by the project lead."
  );
  form.setCollectEmail(true);
  form.setProgressBar(true);
  form.setShowLinkToRespondAgain(false);

  // ===========================================================
  // DATA PRIVACY AGREEMENT (mandatory — retained verbatim from
  // the previous UAT form so SLI's policy reading is unchanged).
  // ===========================================================
  form.addSectionHeaderItem()
      .setTitle("Data Privacy Agreement")
      .setHelpText(
        "The personal information gathered through this form will be processed with the utmost confidentiality in accordance with the Data Privacy Act of 2012 (Republic Act No. 10173) and applicable SafeXpress Inc. data protection policies. The data collected (your email address, full name, role, and questionnaire responses) will be used solely for the purposes of:\n\n" +
        "  - validating the readiness of SafexpressOps for production deployment,\n" +
        "  - identifying defects, gaps, or improvements before roll-out,\n" +
        "  - producing aggregate UAT sign-off reports for SafeXpress management.\n\n" +
        "Your individual responses will not be shared with parties outside the project team without your consent. By selecting \"I accept\" below, you signify your consent and authorize SafeXpress Inc. and the project team to collect and process the data indicated herein for the purposes mentioned above."
      );

  form.addMultipleChoiceItem()
      .setTitle("Data Privacy Agreement *")
      .setHelpText("This acknowledgment is required to proceed with the UAT. If you do not accept, please close this form and contact the project lead.")
      .setChoiceValues(["I accept the Data Privacy Agreement"])
      .setRequired(true);

  // ===========================================================
  // TESTER INFORMATION + role dropdown (drives branching)
  // ===========================================================
  form.addSectionHeaderItem()
      .setTitle("Tester Information")
      .setHelpText("Tell us who you are. Your selected role determines which sections you will see next — sections that do not apply to your role are skipped automatically.");

  form.addTextItem()
      .setTitle("Tester full name")
      .setRequired(true);

  form.addTextItem()
      .setTitle("Warehouse / department")
      .setHelpText("e.g. VFP warehouse, HQ Operations, Manila Branch.")
      .setRequired(false);

  form.addTextItem()
      .setTitle("Hands-on session duration (minutes)")
      .setHelpText("Roughly how long you actually used the system before filling out this form.")
      .setRequired(false);

  var roleDropdown = form.addListItem()
      .setTitle("Tester role")
      .setHelpText("Pick the role you tested under. Administrators see all sections (including KB Management and Account & Activity Management). Managers see Admin sections except KB Management and Account & Activity. Users see only the sections that apply to standard end-users.")
      .setRequired(true);

  // ===========================================================
  // PER-ROLE PIPELINES
  // Each role gets its own page sequence; sections that do not
  // apply to that role are simply not added.
  // ===========================================================
  var adminPages   = buildRolePipeline(form, "Admin",   "ADMIN");
  var managerPages = buildRolePipeline(form, "Manager", "MANAGER");
  var userPages    = buildRolePipeline(form, "User",    "USER");

  // ===========================================================
  // FINAL PAGE — sign-off (shared by all roles)
  // ===========================================================
  var finalPage = form.addPageBreakItem()
      .setTitle("Final notes & sign-off")
      .setHelpText("Mirrors Part 6 of UAT-FeatureScale.docx. Your verdict here is your personal acceptance decision; the project lead aggregates verdicts across testers per the criteria in the docx cover page.");

  form.addParagraphTextItem()
      .setTitle("Notes / blockers")
      .setHelpText("Anything that did not work, was confusing, or needs follow-up. Be as specific as possible (steps to reproduce, expected vs actual). This complements the open-ended Part 5 questions.")
      .setRequired(false);

  form.addMultipleChoiceItem()
      .setTitle("Personal verdict")
      .setHelpText("ACCEPT = I would use SafexpressOps in my daily work and recommend it to colleagues. ACCEPT WITH CONDITIONS = I would use it once the issues I noted above are addressed. REJECT = I would NOT use SafexpressOps in its current form.")
      .setChoiceValues([
        "Accept",
        "Accept with conditions",
        "Reject"
      ])
      .setRequired(true);

  form.addTextItem()
      .setTitle("Signature / initials")
      .setHelpText("Type your full name or initials to confirm submission.")
      .setRequired(true);

  // ===========================================================
  // WIRE UP NAVIGATION
  // - Each role's last page jumps directly to the final page so
  //   testers don't fall through into another role's pages.
  // - Role dropdown choices set the FIRST page each role enters.
  // ===========================================================
  adminPages.last.setGoToPage(finalPage);
  managerPages.last.setGoToPage(finalPage);
  userPages.last.setGoToPage(finalPage);

  roleDropdown.setChoices([
    roleDropdown.createChoice("Administrator", adminPages.first),
    roleDropdown.createChoice("Manager",       managerPages.first),
    roleDropdown.createChoice("User",          userPages.first)
  ]);

  Logger.log("Form created.");
  Logger.log("Edit URL: " + form.getEditUrl());
  Logger.log("Live URL: " + form.getPublishedUrl());
}
