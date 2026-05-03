import React, { useState, useRef, useEffect } from 'react';
import api from '../api';
import '../css/TermsAndConditionsModal.css';

const TERMS_VERSION = '1.0';

function TermsAndConditionsModal({ user, onAccept, onDecline }) {
  const [accepting, setAccepting] = useState(false);
  const [checked, setChecked] = useState(false);
  const [scrolledToEnd, setScrolledToEnd] = useState(false);
  const [error, setError] = useState(null);
  const bodyRef = useRef(null);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const handleScroll = () => {
      const threshold = 24;
      const reachedBottom =
        el.scrollTop + el.clientHeight >= el.scrollHeight - threshold;
      if (reachedBottom) setScrolledToEnd(true);
    };
    handleScroll();
    el.addEventListener('scroll', handleScroll);
    return () => el.removeEventListener('scroll', handleScroll);
  }, []);

  const handleAccept = async () => {
    if (!checked || !scrolledToEnd) return;
    setAccepting(true);
    setError(null);
    try {
      const response = await api.post('/api/auth/accept-terms', {
        version: TERMS_VERSION,
      });

      const updatedUser = {
        ...user,
        terms_accepted: true,
        terms_version_accepted: response.data?.terms_version_accepted || TERMS_VERSION,
        terms_accepted_at: response.data?.terms_accepted_at || new Date().toISOString(),
      };
      localStorage.setItem('user', JSON.stringify(updatedUser));
      onAccept(updatedUser);
    } catch (err) {
      console.error('Failed to accept terms:', err);
      setError(
        err.response?.data?.error ||
          'Failed to save your acceptance. Please try again.'
      );
    } finally {
      setAccepting(false);
    }
  };

  return (
    <div className="tnc-overlay" role="dialog" aria-modal="true" aria-labelledby="tnc-title">
      <div className="tnc-modal">
        <div className="tnc-header">
          <h2 id="tnc-title" className="tnc-title">Terms &amp; Conditions</h2>
          <p className="tnc-subtitle">
            Please review and accept the terms below before using the portal.
          </p>
        </div>

        <div className="tnc-body" ref={bodyRef}>
          <h3>1. Acceptance of Terms</h3>
          <p>
            By accessing or using the Safexpress Portal (the "Service") &mdash;
            operated by Safexpress Logistics Inc. &mdash; you agree to be bound
            by these Terms &amp; Conditions. If you do not agree, you must not
            use the Service.
          </p>

          <h3>2. Authorized Use &amp; Role-Based Access</h3>
          <p>
            Your account has been provisioned by an administrator of your
            organization and is assigned a role (Admin, Manager, or User).
            Each role unlocks a specific set of features:
          </p>
          <ul>
            <li>
              <strong>Admin</strong> &mdash; full access, including account
              management, Knowledge Base deletion, token quota administration,
              and activity logs.
            </li>
            <li>
              <strong>Manager</strong> &mdash; Knowledge Base management
              (upload/replace), AI Assistant, Dashboard, and audit logs.
            </li>
            <li>
              <strong>User</strong> &mdash; SFX Bot, Dynamic Mapping, and
              Analysis Reports only.
            </li>
          </ul>
          <p>
            You may use the Service only for legitimate Safexpress business
            purposes associated with your assigned role
            ({(user?.role || 'user').toString()}). You will not share your
            credentials, impersonate another user, or attempt to access
            features outside your role.
          </p>

          <h3>3. Authentication &amp; Session</h3>
          <p>
            Authentication is performed exclusively via Google OAuth 2.0.{' '}
            <strong>
              Only Google Workspace accounts provided and authorized by
              Safexpress Logistics Inc. may be used to sign in.
            </strong>{' '}
            The Service issues a short-lived JWT access token (&asymp; 60
            minutes) and a refresh token to maintain your session. You are
            responsible for maintaining the security of your Google account,
            including multi-factor authentication. Report suspected
            unauthorized access to your administrator immediately.
          </p>

          <h3>4. Google Workspace Access &amp; Agent Actions</h3>
          <p>
            The AI Assistant (internally, the "supervisor agent") can take
            actions on your behalf against the Google Workspace account you
            signed in with. Granted scopes include, and are not limited to:
          </p>
          <ul>
            <li>
              <strong>Gmail</strong> &mdash; search, read threads, download
              attachments, draft, send, reply, and forward emails (including
              adding a system-generated signature such as "Written by Assistant
              Agent" where applicable).
            </li>
            <li>
              <strong>Google Calendar</strong> &mdash; list, create, update, and
              delete events; send/cancel invitations to attendees.
            </li>
            <li>
              <strong>Google Docs</strong> &mdash; create, read, edit, and
              update documents; generate documents from templates.
            </li>
            <li>
              <strong>Google Sheets</strong> &mdash; read, create, append, and
              update rows.
            </li>
            <li>
              <strong>Google Drive</strong> &mdash; upload, download, list,
              search, and rename files or folders within the SafeExpress root
              folder.
            </li>
          </ul>
          <p>
            By using the AI Assistant you authorize the Service to perform
            these actions on your Google account in response to your
            natural-language requests.
          </p>

          <h3>5. Approval for High-Risk Actions</h3>
          <p>
            The AI Assistant classifies every tool call by risk level. Actions
            marked <strong>DANGEROUS</strong> or <strong>CRITICAL</strong>
            {' '}(for example, deleting a calendar event, deleting a Drive file,
            or mass-editing a document) will pause and require your explicit
            in-chat approval before they are executed. Actions marked{' '}
            <strong>MODERATE</strong> (e.g. creating or updating a calendar
            event, sending an email draft) may execute without a separate
            approval prompt; you are expected to review the AI Assistant's plan
            before confirming your request.
          </p>

          <h3>6. Knowledge Base Uploads</h3>
          <p>
            Documents you upload to the Knowledge Base (currently limited to
            PDF) are:
          </p>
          <ol>
            <li>Parsed and split into content chunks.</li>
            <li>
              Converted to vector embeddings via OpenAI's embedding models.
            </li>
            <li>Indexed in a Weaviate vector database for retrieval.</li>
            <li>
              Tracked in a document database (including filename, size, page
              count, upload date, uploaded-by identity, and a content hash for
              duplicate detection).
            </li>
          </ol>
          <p>
            When a document with the same filename is re-uploaded with
            "force replace", the previous version is archived and retained as
            version history rather than permanently destroyed. You agree not
            to upload content that is personal, sensitive, unlawful, or that
            you are not authorized to share or store in the Service.
          </p>

          <h3>7. Data Storage &amp; Processing</h3>
          <p>
            Data handled by the Service is stored and processed across the
            following systems in accordance with your organization's
            data-handling policies:
          </p>
          <ul>
            <li>
              <strong>Amazon Web Services</strong> &mdash; DynamoDB (document
              metadata, chat sessions and messages, system logs) and S3
              (temporary storage for uploaded files, subject to a 24-hour
              lifecycle cleanup rule).
            </li>
            <li>
              <strong>Weaviate Cloud</strong> &mdash; vector embeddings and
              chunked document content for semantic search.
            </li>
            <li>
              <strong>Relational / embedded databases</strong> &mdash;
              SQLite-based stores for accounts, token quotas, thread state,
              and audit logs in non-Lambda deployments.
            </li>
            <li>
              <strong>OpenAI API</strong> &mdash; prompts, conversation history,
              retrieved Knowledge Base chunks, and uploaded document text are
              transmitted to OpenAI for embedding and response generation
              (models may include GPT-4, GPT-4o, GPT-4o-mini, GPT-3.5-turbo,
              and text-embedding-3-small).
            </li>
            <li>
              <strong>Google Workspace APIs</strong> &mdash; requests described
              in Section 4 are sent directly to Google on your behalf.
            </li>
          </ul>
          <p>
            You acknowledge that by submitting content to the Service, you also
            authorize its transmission to these sub-processors for the purposes
            described above.
          </p>

          <h3>8. Acceptable Use</h3>
          <p>You will not:</p>
          <ol className="tnc-list-alpha">
            <li>
              attempt to reverse-engineer, probe, or bypass the Service's
              authentication, role-based access, rate limits, or security
              controls;
            </li>
            <li>
              upload malware, malicious code, or files that exploit parsing
              vulnerabilities;
            </li>
            <li>
              use the Service to violate any law, regulation, or third-party
              right;
            </li>
            <li>
              attempt prompt injection, jailbreaks, or manipulation of the AI
              to reveal its system prompt, escape its topical scope, or produce
              content that is defamatory, harassing, discriminatory, or
              otherwise harmful;
            </li>
            <li>
              submit requests for sensitive or confidential information
              (credentials, salary data, PII, etc.) that you are not authorized
              to access; or
            </li>
            <li>
              use the AI Assistant to perform actions against a Google
              Workspace account that you do not lawfully control.
            </li>
          </ol>
          <p>
            The Service applies automated input and output guardrails
            (including prompt-injection detection, off-topic filtering,
            sensitive-data blocking, and PII masking of outputs such as SSNs,
            credit card numbers, phone numbers, and email addresses). Attempts
            to circumvent these controls are a violation of these Terms.
          </p>

          <h3>9. AI-Generated Content</h3>
          <p>
            Responses produced by the Service's AI components (the AI
            Assistant, the Knowledge Base chat, and SFX Bot) are generated
            automatically by third-party large language models using the
            context available at the time of the request. Outputs may be
            incomplete, outdated, or factually incorrect, and the AI may cite
            sources (e.g. <code>[Source: filename, Page X]</code>) that do not
            fully support the associated statement.{' '}
            <strong>
              You are responsible for reviewing and validating any output
              &mdash; and any action executed on your behalf &mdash; before
              relying on it for business decisions.
            </strong>{' '}
            Safexpress makes no warranty as to the accuracy, completeness, or
            fitness for purpose of AI-generated output.
          </p>

          <h3>10. Token Usage &amp; Quotas</h3>
          <p>
            Your LLM usage (input and output tokens, cost, and operation
            metadata) is metered and reported to the Safexpress Token Quota
            Service. Each account is assigned a monthly token allowance and
            tier (e.g. free, pro, enterprise). When your allowance is
            exhausted, requests that consume tokens may be rejected until the
            quota resets or your tier is upgraded by an administrator.
            Knowledge Base retrieval queries are currently tracked for
            analytics but are not strictly enforced against the quota.
          </p>

          <h3>11. Monitoring &amp; Audit</h3>
          <p>
            For security, compliance, and operational purposes, the Service
            logs:
          </p>
          <ul>
            <li>Authentication events (sign-ins, token refreshes).</li>
            <li>
              Administrative actions (account creation/deactivation, role
              changes, document deletion).
            </li>
            <li>Knowledge Base uploads, replacements, and version history.</li>
            <li>
              AI Assistant executions (plan, steps, tool calls, inputs at
              substitution time, outputs, token usage, and cost) keyed to your
              user identifier.
            </li>
            <li>
              Chat session activity, including messages and Knowledge Base
              sources referenced.
            </li>
            <li>Blocked or modified requests flagged by guardrails.</li>
          </ul>
          <p>
            By using the Service, you consent to this monitoring and to the
            retention of these logs for as long as Safexpress determines is
            necessary.
          </p>

          <h3>12. Suspension &amp; Termination</h3>
          <p>
            Administrators may deactivate your account at any time. Upon
            deactivation, new chat sessions, Knowledge Base uploads, and AI
            Assistant executions are rejected. Violation of these Terms
            &mdash; including any attempt to bypass guardrails, abuse the AI
            Assistant against unauthorized accounts, or upload prohibited
            content &mdash; may result in immediate suspension. Safexpress may
            also suspend the Service (in whole or in part) for maintenance,
            security, or quota reasons.
          </p>

          <h3>13. Changes to the Terms</h3>
          <p>
            These Terms may be updated from time to time. If a new version is
            published, you will be asked to review and accept it at your next
            login. Continued use of the Service after acceptance of a revised
            version constitutes your agreement to the updated Terms.
          </p>

          <h3>14. Contact</h3>
          <p>
            For questions about these Terms, your role, your token quota,
            suspected unauthorized access, or data-handling concerns, contact
            your system administrator.
          </p>
        </div>

        {!scrolledToEnd && (
          <div className="tnc-scroll-hint">
            Scroll to the bottom to enable the acceptance checkbox.
          </div>
        )}

        {error && <div className="tnc-error">{error}</div>}

        <label
          className={`tnc-checkbox ${!scrolledToEnd ? 'tnc-checkbox-disabled' : ''}`}
        >
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
            disabled={accepting || !scrolledToEnd}
          />
          <span>
            I have read and agree to the Terms &amp; Conditions.
          </span>
        </label>

        <div className="tnc-actions">
          {onDecline && (
            <button
              type="button"
              className="tnc-btn tnc-btn-decline"
              onClick={onDecline}
              disabled={accepting}
            >
              Decline &amp; Sign Out
            </button>
          )}
          <button
            type="button"
            className="tnc-btn tnc-btn-accept"
            onClick={handleAccept}
            disabled={!checked || !scrolledToEnd || accepting}
          >
            {accepting ? 'Saving…' : 'Accept & Continue'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default TermsAndConditionsModal;
