"""
Test email formatter integration
"""
from email_formatter import format_email_object

# Test with your MongoDB email example
test_email = {
    "message_id": "19a1e8f0f72d30e2",
    "thread_id": "19a1e8f0f72d30e2",
    "from": "MongoDB Atlas <mongodb-atlas@mongodb.com>",
    "subject": "Your MongoDB Atlas M0 cluster has been automatically paused",
    "date": "Sun, 26 Oct 2025 03:28:03 +0000",
    "internal_date": "1761449283000",
    "label_ids": ["CATEGORY_UPDATES", "INBOX"],
    "body": """<meta charset="UTF-8"/>
    <table width="100%" height="100%" cellpadding="0" cellspacing="0" bgcolor="#f5f6f7">
        <tr><td height="50"></td></tr>
        <tr>
            <td align="center" valign="top">
                <table width="600" cellpadding="0" cellspacing="0" bgcolor="#ffffff">
                    <tr>
                        <td colspan="3" height="60" bgcolor="#ffffff">
                            <img src="https://cloud.mongodb.com/static/images/logo-mongodb-atlas.png"/>
                        </td>
                    </tr>
                    <tr>
                        <td width="20"></td>
                        <td align="left">
                            <table cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td colspan="3"><span>ORGANIZATION</span></td>
                                </tr>
                                <tr>
                                    <td colspan="3"><span><a href="https://cloud.mongodb.com/v2#/org/682202f8100dde53143b050b/projects">LANCE JOSHUA's Org - 2025-05-12</a></span></td>
                                </tr>
                                <tr>
                                    <td colspan="3"><span>PROJECT</span></td>
                                </tr>
                                <tr>
                                    <td colspan="3"><span><a href="https://cloud.mongodb.com/v2/68aaea4635fa730dc9bd20ea">Capstone</a></span></td>
                                </tr>
                                <tr>
                                    <td colspan="3">
                                        <div>
                                            <p>Hi LANCE JOSHUA,</p>
                                            <p>Your M0 free tier cluster, <a href="https://cloud.mongodb.com/v2/68aaea4635fa730dc9bd20ea#/clusters/detail/Capstone-DB">Capstone-DB</a>, was automatically paused at 11:28 PM EDT on 2025/10/25 due to prolonged inactivity.</p>
                                            <p>All of your cluster data has been retained, and you may resume your cluster by visiting the Atlas UI.</p>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                        <td width="20"></td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>""",
    "has_attachments": False,
    "attachments": []
}

print("="*80)
print("TESTING EMAIL FORMATTER INTEGRATION")
print("="*80)

print("\nBEFORE FORMATTING:")
print("-"*80)
print(f"Body preview (first 200 chars):")
print(test_email['body'][:200] + "...")
print(f"\nBody is HTML: {bool('<' in test_email['body'] and '>' in test_email['body'])}")

# Format the email
formatted_email = format_email_object(test_email)

print("\n" + "="*80)
print("AFTER FORMATTING:")
print("="*80)

print(f"\n📧 From: {formatted_email['from']}")
print(f"📧 Subject: {formatted_email['subject']}")
print(f"📧 Date: {formatted_email['date']}")

print("\n" + "-"*80)
print("📄 CLEAN BODY:")
print("-"*80)
print(formatted_email['body'])

print("\n" + "-"*80)
print("🔗 EXTRACTED LINKS:")
print("-"*80)
for i, link in enumerate(formatted_email['body_links'], 1):
    print(f"{i}. {link}")

print("\n" + "-"*80)
print("🖼️ EXTRACTED IMAGES:")
print("-"*80)
for i, img in enumerate(formatted_email['body_images'], 1):
    alt = img.get('alt', 'No description')
    src = img.get('src', 'No source')
    print(f"{i}. {alt} - {src}")

print("\n" + "-"*80)
print("⚡ ACTION ITEMS:")
print("-"*80)
if formatted_email['action_items']:
    for i, item in enumerate(formatted_email['action_items'], 1):
        print(f"{i}. {item}")
else:
    print("None detected")

print("\n" + "-"*80)
print("📊 METADATA:")
print("-"*80)
print(f"Has tables: {formatted_email['body_has_tables']}")
print(f"Links found: {len(formatted_email['body_links'])}")
print(f"Images found: {len(formatted_email['body_images'])}")
print(f"Action items: {len(formatted_email['action_items'])}")

print("\n" + "="*80)
print("✅ FORMATTING COMPLETE!")
print("="*80)

print("\n📦 Available fields in formatted email:")
for key in formatted_email.keys():
    print(f"  - {key}")

print("\n💡 Usage in supervisor plans:")
print("  {{ emails[0].body }}        ← Clean text (no HTML!)")
print("  {{ emails[0].body_clean }}  ← Also clean text")
print("  {{ emails[0].body_html }}   ← Original HTML")
print("  {{ emails[0].body_links }}  ← List of URLs")
print("  {{ emails[0].action_items }} ← Extracted actions")
