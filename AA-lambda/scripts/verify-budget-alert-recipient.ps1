# Triggers SES email-address verification for the budget-alert recipient.
#
# Why: the AWS account is currently in SES SANDBOX mode (verified at
# the time of writing — `aws sesv2 get-account --query
# ProductionAccessEnabled` returns False). In sandbox, BOTH the sender
# AND each recipient must be verified before SES will accept the
# SendEmail call. Until production access is granted, this script gets
# the recipient verified so budget-alert emails actually deliver.
#
# Default recipient: sadmin@safexpressops.com (per the user's request).
# Pass -Email <other> to verify a different mailbox.
#
# After running this script, the recipient mailbox receives a
# verification email from AWS — click the link to complete the
# verification. After clicking, run:
#   aws ses get-identity-verification-attributes --identities <email> --region ap-southeast-1
# to confirm "VerificationStatus": "Success".
#
# Once SES production access is granted (apply via AWS console:
# https://console.aws.amazon.com/ses/home → Account dashboard → Request
# production access), recipient verification is no longer needed and
# this script becomes obsolete.

[CmdletBinding()]
param(
    [string]$Email = "admin@safexpressops.com",
    [string]$Region = "ap-southeast-1"
)

Write-Host "Sending SES verification email to $Email (region $Region) ..."
aws ses verify-email-identity --email-address $Email --region $Region

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[ok] Verification email queued." -ForegroundColor Green
    Write-Host "  Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Open the inbox of $Email."
    Write-Host "  2. Click the AWS verification link."
    Write-Host "  3. Confirm with:"
    Write-Host "     aws ses get-identity-verification-attributes --identities $Email --region $Region"
    Write-Host ""
    Write-Host "  Until step 2 is complete, SES will reject any send to this address"
    Write-Host "  with 'Email address is not verified' — budget-alert emails will be"
    Write-Host "  silently logged in CloudWatch but not delivered."
} else {
    $code = $LASTEXITCODE
    Write-Host "[err] verify-email-identity returned exit code $code." -ForegroundColor Red
}
