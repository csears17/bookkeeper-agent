"""Generate the Bookkeeper Agent Phase-1 setup checklist as a PDF.

Run: ../.venv/Scripts/python.exe docs/make_setup_pdf.py
Output: C:/Users/Cole/Downloads/Bookkeeper-Agent-Setup-Checklist.pdf
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

OUT = r"C:\Users\Cole\Downloads\Bookkeeper-Agent-Setup-Checklist.pdf"

NAVY = colors.HexColor("#1f3a5f")
ACCENT = colors.HexColor("#2e7d32")
LIGHT = colors.HexColor("#eef2f7")
GREY = colors.HexColor("#555555")

styles = getSampleStyleSheet()
H_TITLE = ParagraphStyle("HTitle", parent=styles["Title"], fontSize=22, textColor=NAVY, spaceAfter=4)
SUB = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10.5, textColor=GREY, spaceAfter=14)
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=14, textColor=colors.white,
                    backColor=NAVY, borderPadding=(6, 8, 6, 8), spaceBefore=16, spaceAfter=8, leading=18)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=11.5, textColor=NAVY, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=4)
STEP = ParagraphStyle("Step", parent=styles["Normal"], fontSize=10, leading=14, leftIndent=14,
                      firstLineIndent=-14, spaceAfter=4)
SUBSTEP = ParagraphStyle("SubStep", parent=styles["Normal"], fontSize=9.5, leading=13, leftIndent=30,
                         firstLineIndent=-12, spaceAfter=2, textColor=GREY)
CODE = ParagraphStyle("Code", parent=styles["Code"], fontSize=8.5, leading=11, leftIndent=14,
                      backColor=LIGHT, borderPadding=(4, 4, 4, 4), spaceBefore=2, spaceAfter=6)
NOTE = ParagraphStyle("Note", parent=styles["Normal"], fontSize=9, leading=12, textColor=GREY,
                      leftIndent=14, spaceAfter=6)


def cb(text):
    return Paragraph("[ ]&nbsp;&nbsp;" + text, STEP)


def sub(text):
    return Paragraph("&ndash;&nbsp;" + text, SUBSTEP)


def code(text):
    return Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), CODE)


def h1(text):
    return Paragraph(text, H1)


def h2(text):
    return Paragraph(text, H2)


def body(text):
    return Paragraph(text, BODY)


def note(text):
    return Paragraph("Note: " + text, NOTE)


story = []
story.append(Paragraph("Bookkeeper Agent &mdash; Setup Checklist", H_TITLE))
story.append(Paragraph(
    "Phase 1: accounts &amp; developer apps you set up yourself. Do these on your PC. "
    "None require the Mac Mini. Capture every credential into the table on the last page "
    "(and store secrets in a password manager). Work through the sections in order; "
    "tick each box as you go.", SUB))

story.append(body(
    "<b>What this gets you:</b> the four service connections the agent needs &mdash; Anthropic "
    "(the brain), Google &amp; Microsoft (read your client mailboxes), QuickBooks Online (write bills), "
    "and Slack (approve bills). Exact <font face='Courier'>.env</font> variable names for the provider "
    "secrets are finalized when we build the connectors (WS-B); for now just create each app and "
    "<b>safely capture</b> the credentials."))

# 1. Anthropic
story.append(h1("1. Anthropic (the model + your spend cap)"))
story.append(cb("Go to <b>console.anthropic.com</b>, sign in or create an account."))
story.append(cb("Settings &rarr; API Keys &rarr; <b>Create Key</b>. Copy it (starts <font face='Courier'>sk-ant-</font>). Goes in <font face='Courier'>.env</font> as ANTHROPIC_API_KEY."))
story.append(cb("Settings &rarr; Limits/Billing &rarr; set an <b>organization spend limit</b> as a hard backstop (separate from the agent's own cap)."))
story.append(cb("Decide your monthly cap (e.g. <b>$25</b>). Goes in <font face='Courier'>.env</font> as MONTHLY_USD_CAP. The agent warns at 75% and hard-stops at 100%."))
story.append(cb("(Recommended) Ask Anthropic to enable <b>Zero Data Retention</b> for your org, so prompt content isn't retained on their side."))

# 2. Encryption key
story.append(h1("2. Encryption key (protects all stored tokens)"))
story.append(cb("In the project folder on your PC, generate a Fernet key:"))
story.append(code(r'.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'))
story.append(cb("Paste the output into <font face='Courier'>.env</font> as TOKEN_ENC_KEYS. <b>Back it up in your password manager.</b>"))
story.append(note("This is the master key. If you lose it, stored OAuth tokens can't be decrypted; if it leaks, they're exposed. Never commit it."))

# 3. Google
story.append(h1("3. Google Workspace &mdash; for your Google-hosted client mailboxes"))
story.append(body("Because you administer the domain, a service account reads mail server-to-server &mdash; no per-mailbox logins, no token expiry, no security review."))
story.append(cb("<b>console.cloud.google.com</b> &rarr; create a project (e.g. \"bookkeeper-agent\")."))
story.append(cb("APIs &amp; Services &rarr; Library &rarr; enable <b>Gmail API</b>."))
story.append(cb("APIs &amp; Services &rarr; Credentials &rarr; Create credentials &rarr; <b>Service account</b> (e.g. \"bookkeeper-reader\")."))
story.append(cb("Open the service account &rarr; <b>Keys</b> &rarr; Add key &rarr; <b>JSON</b> &rarr; download. Save the file somewhere safe on your PC (you'll reference its path)."))
story.append(cb("On the service account, enable <b>Domain-wide Delegation</b> and note its <b>Client ID</b> (a long number)."))
story.append(cb("<b>admin.google.com</b> &rarr; Security &rarr; Access &amp; data control &rarr; API controls &rarr; <b>Domain-wide delegation</b> &rarr; Add new:"))
story.append(sub("Client ID: the service account's client ID"))
story.append(sub("OAuth scope: <font face='Courier'>https://www.googleapis.com/auth/gmail.readonly</font>"))
story.append(cb("If you have more than one Workspace domain, repeat the Admin authorize step in each."))

# 4. Microsoft
story.append(h1("4. Microsoft 365 &mdash; for your Microsoft-hosted client mailboxes"))
story.append(cb("<b>entra.microsoft.com</b> &rarr; App registrations &rarr; <b>New registration</b> (name \"bookkeeper-agent\", single tenant). Register."))
story.append(cb("Note the <b>Application (client) ID</b> and <b>Directory (tenant) ID</b>."))
story.append(cb("Certificates &amp; secrets &rarr; <b>New client secret</b> &rarr; copy the secret <b>Value</b> immediately (shown only once)."))
story.append(cb("API permissions &rarr; Add &rarr; Microsoft Graph &rarr; <b>Application permissions</b> &rarr; <b>Mail.Read</b> &rarr; Add &rarr; then <b>Grant admin consent</b>."))
story.append(cb("Least-privilege: restrict the app to only your client mailboxes via an <b>Application Access Policy</b> (Exchange Online PowerShell):"))
story.append(sub("Make a mail-enabled security group containing only the client mailboxes (e.g. bookkeeper-mailboxes@yourdomain)."))
story.append(code(r'New-ApplicationAccessPolicy -AppId <client-id> -PolicyScopeGroupId bookkeeper-mailboxes@yourdomain -AccessRight RestrictAccess -Description "Limit bookkeeper-agent to client mailboxes"'))
story.append(sub("Verify: Test-ApplicationAccessPolicy on a listed mailbox returns Granted; an unlisted one returns Denied."))

# 5. QBO
story.append(h1("5. Intuit / QuickBooks Online &mdash; where bills get written"))
story.append(cb("<b>developer.intuit.com</b> &rarr; sign in &rarr; create a developer account."))
story.append(cb("Create an app &rarr; \"QuickBooks Online and Payments\" &rarr; select the <b>Accounting</b> scope."))
story.append(cb("In Keys &amp; credentials, note the <b>Development (sandbox) Client ID + Client Secret</b>. (Production keys later.)"))
story.append(cb("Add a Redirect URI for the connect flow (a localhost URL &mdash; exact value finalized in WS-B)."))
story.append(cb("Later, before going live on real books: complete Intuit's app questionnaire for <b>Production keys</b>. Sandbox is fine to start."))
story.append(note("Each client company's realm ID is captured during the \"Connect to QuickBooks\" step we build in WS-B. Leave qbo_realm_id blank in clients.toml until then."))

# 6. Slack
story.append(h1("6. Slack &mdash; where you approve bills"))
story.append(cb("<b>api.slack.com/apps</b> &rarr; Create New App &rarr; <b>From scratch</b> &rarr; name \"Bookkeeper Agent\", pick your workspace."))
story.append(cb("<b>Socket Mode</b> &rarr; enable. Generate an <b>App-Level Token</b> (scope connections:write) &rarr; copy (starts <font face='Courier'>xapp-</font>)."))
story.append(cb("OAuth &amp; Permissions &rarr; Bot Token Scopes &rarr; add <b>chat:write</b>."))
story.append(cb("Interactivity &amp; Shortcuts &rarr; turn <b>on</b> (Socket Mode delivers button clicks &mdash; no public URL needed)."))
story.append(cb("Install App &rarr; Install to Workspace &rarr; copy the <b>Bot User OAuth Token</b> (starts <font face='Courier'>xoxb-</font>)."))
story.append(cb("Create a private channel for approvals, invite the bot (<font face='Courier'>/invite @Bookkeeper Agent</font>), and note the <b>channel ID</b>."))

# 7. Per-client info
story.append(h1("7. Per-client info to collect (one row per client company)"))
story.append(body("For each of your client companies, jot down: name, which provider hosts its mailbox, the mailbox address, and which QBO company it maps to. Autonomy starts at 0 (Slack-approve everything)."))
client_tbl = Table(
    [["Client name", "Provider", "Mailbox address", "QBO company / realm id", "Autonomy"]] + [["", "", "", "", "0"]] * 6,
    colWidths=[1.3 * inch, 0.9 * inch, 1.9 * inch, 1.7 * inch, 0.7 * inch],
)
client_tbl.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
]))
story.append(client_tbl)

# 8. Put together
story.append(h1("8. Put it together on your PC"))
story.append(cb("In <font face='Courier'>C:\\Users\\Cole\\bookkeeper-agent</font>: copy <font face='Courier'>.env.example</font> &rarr; <font face='Courier'>.env</font> and fill ANTHROPIC_API_KEY, TOKEN_ENC_KEYS, MONTHLY_USD_CAP."))
story.append(cb("Copy <font face='Courier'>clients.example.toml</font> &rarr; <font face='Courier'>clients.toml</font>; add one [[client]] block per client (key, display_name, provider, mailbox, qbo_realm_id, autonomy_level = 0)."))
story.append(cb("Keep <font face='Courier'>.env</font>, <font face='Courier'>clients.toml</font>, the Google JSON key, and all secrets <b>out of git</b> (already ignored) and in your password manager."))
story.append(note("Exact .env names for the Google JSON path, Microsoft secret/tenant/app id, QBO id/secret, and Slack tokens are added when we build WS-B. For now, just capture and store every credential."))

# 9. Later
story.append(h1("9. Later &mdash; Mac Mini (nothing to do now)"))
story.append(body("After WS-A/B/C are built and tested on your PC, we copy the repo + <font face='Courier'>.env</font> + encryption key + database to the Mac Mini and set it to run continuously. No action required today."))

# Security reminders
story.append(h1("Security reminders"))
story.append(Paragraph("&bull; Never paste secrets into chat, email, screenshots, or git.", BODY))
story.append(Paragraph("&bull; The Fernet key is the master key &mdash; back it up; losing it loses all stored tokens, leaking it exposes them.", BODY))
story.append(Paragraph("&bull; Least privilege everywhere: read-only Gmail, Mail.Read only, scoped Microsoft app access policy, QBO accounting scope, Slack chat:write.", BODY))

# Credentials capture table
story.append(h1("Credentials capture (fill as you go; keep values in a password manager)"))
rows = [["Item", "Where it goes", "Value / location"]]
for item, dest in [
    ("Anthropic API key", ".env ANTHROPIC_API_KEY"),
    ("Fernet key", ".env TOKEN_ENC_KEYS"),
    ("Monthly cap (USD)", ".env MONTHLY_USD_CAP"),
    ("Google Cloud project id", "reference"),
    ("Google service-account JSON (file path)", "WS-B config"),
    ("Google SA client ID", "Admin DWD authorize"),
    ("Microsoft tenant ID", "WS-B config"),
    ("Microsoft app (client) ID", "WS-B config"),
    ("Microsoft client secret", "WS-B config"),
    ("QBO client ID (sandbox)", "WS-B config"),
    ("QBO client secret (sandbox)", "WS-B config"),
    ("Slack bot token (xoxb-)", "WS-B config"),
    ("Slack app token (xapp-)", "WS-B config"),
    ("Slack approval channel ID", "WS-B config"),
]:
    rows.append([item, dest, ""])
cred_tbl = Table(rows, colWidths=[2.4 * inch, 2.0 * inch, 2.1 * inch])
cred_tbl.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ("FONTNAME", (1, 1), (1, -1), "Courier"),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
]))
story.append(cred_tbl)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(0.75 * inch, 0.5 * inch, "Bookkeeper Agent — Phase 1 Setup Checklist")
    canvas.drawRightString(7.75 * inch, 0.5 * inch, "Page %d" % doc.page)
    canvas.restoreState()


doc = BaseDocTemplate(OUT, pagesize=letter,
                      leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                      topMargin=0.7 * inch, bottomMargin=0.8 * inch)
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=footer)])
doc.build(story)
print("WROTE", OUT)
