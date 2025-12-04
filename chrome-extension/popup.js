// Popup script to manage resume generation workflow status

const processBtn = document.getElementById('processBtn');
const messageDiv = document.getElementById('message');
const selectedSnippetDiv = document.getElementById('selectedSnippet');
const activeCardContainer = document.getElementById('activeCard');
const historySection = document.getElementById('historySection');
const appliedToggle = document.getElementById('appliedToggle');
const appliedContainer = document.getElementById('appliedContainer');

const SERVER_BASE_URL = 'http://localhost:8000';
const GENERATE_ENDPOINT = `${SERVER_BASE_URL}/generate-resume`;
const STATUS_ENDPOINT = `${SERVER_BASE_URL}/status`;
const STATUS_LIST_ENDPOINT = `${SERVER_BASE_URL}/statuses`;
const MARK_APPLIED_ENDPOINT = (statusId) => `${SERVER_BASE_URL}/statuses/${statusId}/applied`;
const DOWNLOAD_RESUME_ENDPOINT = `${SERVER_BASE_URL}/download-resume`;

const POLL_INTERVAL_MS = 4000;
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'no_sponsorship', 'screening_blocked']);

const STEP_LABELS = new Map([
  ['screening', 'Screening'],
  ['screened', 'Screening'],
  ['screening_blocked', 'Screening Blocked'],
  ['screening_failed', 'Screening'],
  ['loading_pointers', 'Loading Pointers'],
  ['pointers_loaded', 'Pointers Loaded'],
  ['pointers_missing', 'Pointers Missing'],
  ['pointers_failed', 'Pointers Failed'],
  ['pointers_error', 'Pointers Error'],
  ['analyzing_jd', 'Analyzing JD'],
  ['jd_analyzed', 'JD Analyzed'],
  ['jd_analysis_failed', 'JD Analysis Failed'],
  ['analysis_failed', 'JD Analysis Failed'],
  ['no_sponsorship', 'Stopped'],
  ['writing_resume', 'Writing Resume'],
  ['resume_written', 'Resume Drafted'],
  ['resume_write_failed', 'Resume Draft Failed'],
  ['resume_sections_missing', 'Resume Draft Missing'],
  ['generating_document', 'Generating Document'],
  ['document_generated', 'Document Generated'],
  ['document_generation_failed', 'Document Generation Failed'],
  ['validating_resume', 'Validating Resume'],
  ['validation_failed', 'Validation Failed'],
  ['resume_uploaded', 'Resume Uploaded'],
  ['retrying_after_validation', 'Retrying (Validation)'],
  ['retrying', 'Retrying'],
  ['validation_error', 'Validation Error'],
  ['workflow_error', 'Workflow Error'],
  ['workflow_failed', 'Workflow Failed'],
  ['exception', 'Workflow Error'],
  ['completed', 'Completed'],
  ['success', 'Completed'],
  ['failed', 'Failed'],
  ['processing', 'In Progress'],
]);

let currentTab = null;
let pollTimerId = null;
let activeContext = null;

document.addEventListener('DOMContentLoaded', () => {
  processBtn.addEventListener('click', onProcessClick);
  appliedToggle.addEventListener('click', toggleAppliedSection);
  refreshSelectionPreview();
  refreshStatus();
});

async function onProcessClick() {
  stopPolling();
  hideMessage();
  setButtonLoading(true);

  try {
    currentTab = await getActiveTab();
    if (!currentTab) {
      throw new Error('Unable to determine the active tab.');
    }

    const normalized = normalizeUrl(currentTab.url || '');
    if (!normalized.jobUrl) {
      throw new Error('Unable to parse the current page URL. Open the job posting before sending.');
    }

    const selectedText = await getSelectionFromTab(currentTab.id);
    if (!selectedText || selectedText.length < 50) {
      throw new Error('Please select the job description text on the page first');
    }
    
    updateSelectedSnippet(selectedText);

    await chrome.scripting.executeScript({
      target: { tabId: currentTab.id },
      args: [currentTab.url, selectedText],
      func: (url, text) => {
        console.log('=== SENDING TO SERVER ===');
        console.log('URL:', url);
        console.log('Job Description Length:', text.length, 'characters');
        console.log('First 200 chars:', text.substring(0, 200) + '...');
      }
    });
    
    const payload = {
      job_description: selectedText,
      job_metadata: {
        job_url: normalized.jobUrl,
      },
    };
    
    const response = await fetch(GENERATE_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    
    const result = await response.json();
    if (!response.ok) {
      const message = result?.error || `Server error (${response.status})`;
      throw new Error(message);
    }

    if (result.status_id) {
      activeContext = {
        statusId: result.status_id,
        jobUrl: normalized.jobUrl,
        baseUrl: normalized.baseUrl,
      };
    }

    setStatusMessage('Tracking resume generation…', 'info-status');
    await refreshStatus();
  } catch (error) {
    console.error('Error:', error);
    if (error.message.includes('Failed to fetch')) {
      setStatusMessage(`Cannot connect to server.<br><small>Make sure it's running at: ${GENERATE_ENDPOINT}</small>`, 'error');
    } else {
      setStatusMessage(escapeHtml(error.message), 'error');
    }
  } finally {
    setButtonLoading(false);
  }
}

async function refreshStatus() {
  stopPolling();

  try {
    currentTab = await getActiveTab();
    if (!currentTab) {
      setStatusMessage('Unable to determine the active tab.', 'error');
      await showAllStatuses();
      return;
    }

    const normalized = normalizeUrl(currentTab.url || '');
    if (!normalized.jobUrl) {
      setStatusMessage('Open a job posting and select the description to begin.', 'info-status');
      await showAllStatuses();
      return;
    }

    const context = {
      statusId: activeContext?.statusId || null,
      jobUrl: activeContext?.jobUrl || normalized.jobUrl,
      baseUrl: activeContext?.baseUrl || normalized.baseUrl,
    };

    let snapshot = await fetchStatus(context);
    const matched = snapshot && snapshot.__responseStatus === 'success';

    if (matched) {
      hideMessage();
      setActiveContextFromSnapshot(snapshot);
      renderActiveSnapshot(snapshot, true);
      await renderRecentSnapshots(snapshot.status_id);

      if (!isTerminal(snapshot.status)) {
        startPolling();
      }
      return;
    }

    const allSnapshots = await fetchAllSnapshots(false);
    const normalizedJobUrl = normalized.jobUrl;
    const normalizedBaseUrl = normalized.baseUrl;

    const matchingSnapshot =
      allSnapshots.find((snap) => {
        const snapUrl = snap.job_url || '';
        const parsed = normalizeUrl(snapUrl);
        return parsed.jobUrl === normalizedJobUrl;
      }) ||
      allSnapshots.find((snap) => {
        const snapUrl = snap.job_url || '';
        const parsed = normalizeUrl(snapUrl);
        return parsed.baseUrl === normalizedBaseUrl;
      });

    hideMessage();
    clearHistorySection();

    if (matchingSnapshot) {
      setActiveContextFromSnapshot(matchingSnapshot);
      renderActiveSnapshot(matchingSnapshot, true);
      await renderRecentSnapshots(matchingSnapshot.status_id);
      if (!isTerminal(matchingSnapshot.status)) {
        startPolling();
      }
      return;
    }

    if (!allSnapshots.length) {
      setStatusMessage('No resumes generated yet. Run the extractor on a job description to get started.', 'info-status');
      clearActiveCard();
      clearHistorySection();
      updateSelectedSnippet('');
      activeContext = null;
      return;
    }

    clearActiveCard();
    renderStatusList(allSnapshots, 'Recent Resumes');
  } catch (error) {
    console.error('Failed to refresh status:', error);
    setStatusMessage(`Failed to refresh status: ${escapeHtml(error.message)}`, 'error');
    await showAllStatuses();
  }
}

async function fetchStatus(context) {
  const params = new URLSearchParams();
  if (context.statusId) params.set('status_id', context.statusId);
  if (context.jobUrl) params.set('job_url', context.jobUrl);
  if (context.baseUrl) params.set('base_url', context.baseUrl);

  const url = `${STATUS_ENDPOINT}?${params.toString()}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Status request failed (${response.status})`);
  }

  const data = await response.json();
  const snapshot = data.snapshot || {
    status: 'not_started',
    step: 'idle',
    message: '',
    job_url: context.jobUrl,
    base_url: context.baseUrl,
  };
  snapshot.__responseStatus = data.status || 'unknown';
  return snapshot;
}

async function fetchAllSnapshots(includeApplied = false) {
  const params = new URLSearchParams();
  if (!includeApplied) {
    params.set('include_applied', 'false');
  }
  const url = params.toString() ? `${STATUS_LIST_ENDPOINT}?${params}` : STATUS_LIST_ENDPOINT;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Status list request failed (${response.status})`);
  }
  const data = await response.json();
  if (data.status !== 'success') {
    return [];
  }
  return Array.isArray(data.snapshots) ? data.snapshots : [];
}

function startPolling() {
  if (!activeContext) {
    return;
  }
  stopPolling();

  pollTimerId = setInterval(async () => {
    try {
      const snapshot = await fetchStatus(activeContext);
      setActiveContextFromSnapshot(snapshot);

      hideMessage();
      renderActiveSnapshot(snapshot, true);
      await renderRecentSnapshots(snapshot.status_id);

      if (isTerminal(snapshot.status)) {
        stopPolling();
      }
    } catch (error) {
      console.error('Status polling failed:', error);
      stopPolling();
      setStatusMessage(`Failed to refresh status: ${escapeHtml(error.message)}`, 'error');
    }
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimerId) {
    clearInterval(pollTimerId);
    pollTimerId = null;
  }
}

function renderActiveSnapshot(snapshot, showResumeButton) {
  clearActiveCard();
  if (!snapshot) {
    updateSelectedSnippet('');
    return;
  }

  const jobInfo = extractJobInfo(snapshot);
  const card = buildProgressCard(snapshot, {
    heading: jobInfo.title || snapshot.job_url || 'Resume Progress',
    subheading: jobInfo.company || '',
    showResumeButton,
  });

  activeCardContainer.appendChild(card);
  updateSelectedSnippet(getSelectionSnippet(snapshot));
}

async function showAllStatuses() {
  try {
    const snapshots = await fetchAllSnapshots(false);
    clearActiveCard();
    renderStatusList(snapshots, 'Recent Resumes');
  } catch (error) {
    console.warn('Unable to retrieve status list:', error);
    clearActiveCard();
    clearHistorySection();
    updateSelectedSnippet('');
  }
}

async function renderRecentSnapshots(excludeStatusId = null) {
  try {
    const snapshots = await fetchAllSnapshots(false);
    const filtered = excludeStatusId
      ? snapshots.filter((snap) => snap.status_id !== excludeStatusId)
      : snapshots;
    renderStatusList(filtered, 'Recent Resumes');
  } catch (error) {
    console.warn('Unable to retrieve status list:', error);
    clearHistorySection();
  }
}

function setActiveContextFromSnapshot(snapshot) {
  if (!snapshot) {
    activeContext = null;
    return;
  }

  activeContext = {
    statusId: snapshot.status_id || null,
    jobUrl: snapshot.job_url || activeContext?.jobUrl || '',
    baseUrl: snapshot.base_url || activeContext?.baseUrl || '',
  };
}

function renderStatusList(snapshots, headingText = 'Recent Resumes') {
  clearHistorySection();
  updateSelectedSnippet('');

  if (!snapshots || !snapshots.length) {
    return;
  }

  const label = document.createElement('div');
  label.className = 'history-header';
  label.textContent = headingText;
  historySection.appendChild(label);
  snapshots.forEach((snapshot) => {
    const jobInfo = extractJobInfo(snapshot);
    const card = buildProgressCard(snapshot, {
      heading: jobInfo.title || snapshot.job_url || 'Resume',
      subheading: jobInfo.company || '',
      showResumeButton: Boolean(snapshot.resume_url),
    });
    historySection.appendChild(card);
  });
}

function buildProgressCard(snapshot, options = {}) {
  const {
    heading = 'Resume Progress',
    subheading = '',
    showResumeButton = true,
  } = options;

  const card = document.createElement('div');
  card.className = 'card';

  const resumeUrl = snapshot.resume_url || (snapshot.metadata && snapshot.metadata.resume_url);
  const isCompletedStatus = snapshot.status === 'completed' || snapshot.status === 'success';

  // Header row with title, match pill, and resume button
  const headerRow = document.createElement('div');
  headerRow.className = 'card-header';

  const titleRow = document.createElement('div');
  titleRow.className = 'card-title-row';

  const isRawUrlHeading = typeof heading === 'string' && /^https?:\/\//i.test(heading.trim());
  const titleEl = document.createElement(isRawUrlHeading ? 'div' : 'h2');
  titleEl.textContent = heading;
  if (isRawUrlHeading) {
    titleEl.className = 'card-url';
  }
  titleRow.appendChild(titleEl);

  // Add match pill next to title
  const metadata = snapshot.metadata || {};
  if (metadata.validation_result && typeof metadata.validation_result.keyword_coverage_score === 'number') {
    let coverageValue = metadata.validation_result.keyword_coverage_score;
    if (coverageValue <= 1) {
      coverageValue = Math.round(coverageValue * 100);
    } else {
      coverageValue = Math.round(coverageValue);
    }
    const matchPill = document.createElement('span');
    matchPill.className = 'match-pill';
    matchPill.textContent = `${coverageValue}% match`;
    titleRow.appendChild(matchPill);
  }

  headerRow.appendChild(titleRow);

  // Add action buttons to header
  const actionButtons = document.createElement('div');
  actionButtons.className = 'card-actions';
  actionButtons.style.display = 'flex';
  actionButtons.style.gap = '8px';
  actionButtons.style.alignItems = 'center';

  // Add "Mark as Applied" button first (on the left)
  const statusId = snapshot.status_id;
  if (statusId) {
    const appliedBtn = document.createElement('button');
    appliedBtn.className = 'applied-icon';
    appliedBtn.title = 'Mark as applied';
    appliedBtn.setAttribute('aria-label', 'Mark as applied');
    appliedBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M20 6L9 17l-5-5" />
      </svg>
    `;
    appliedBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await markAsApplied(statusId);
    });
    actionButtons.appendChild(appliedBtn);
  }

  // Add job link button if job URL is available
  const jobUrl = snapshot.job_url;
  if (jobUrl) {
    const jobLinkBtn = document.createElement('button');
    jobLinkBtn.className = 'resume-icon';
    jobLinkBtn.title = 'Open job description';
    jobLinkBtn.setAttribute('aria-label', 'Open job description');
    jobLinkBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
      </svg>
    `;
    jobLinkBtn.addEventListener('click', () => {
      chrome.tabs.create({ url: jobUrl });
    });
    actionButtons.appendChild(jobLinkBtn);
  }

  // Add resume buttons if available (on the right)
  if (resumeUrl && showResumeButton) {
    // View button - opens in new tab
    const viewBtn = document.createElement('button');
    viewBtn.className = 'resume-icon';
    viewBtn.title = 'Open generated resume';
    viewBtn.setAttribute('aria-label', 'Open generated resume');
    viewBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6" />
        <path d="M16 13H8" />
        <path d="M16 17H8" />
        <path d="M10 9H8" />
      </svg>
    `;
    viewBtn.addEventListener('click', () => {
      chrome.tabs.create({ url: resumeUrl });
    });
    actionButtons.appendChild(viewBtn);

    // Download button
    const downloadBtn = document.createElement('button');
    downloadBtn.className = 'resume-icon';
    downloadBtn.title = 'Download resume';
    downloadBtn.setAttribute('aria-label', 'Download resume');
    downloadBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
    `;
    downloadBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await downloadResume(statusId, resumeUrl);
    });
    actionButtons.appendChild(downloadBtn);
  }

  if (actionButtons.children.length > 0) {
    headerRow.appendChild(actionButtons);
  }

  card.appendChild(headerRow);

  if (subheading) {
    const subtitleEl = document.createElement('small');
    subtitleEl.textContent = subheading;
    card.appendChild(subtitleEl);
  }

  const shouldShowStage = !(isCompletedStatus && resumeUrl);
  if (shouldShowStage) {
    const stageLabel = STEP_LABELS.get(snapshot.step || '') || STEP_LABELS.get(snapshot.status || '') || 'In Progress';
    const stageState = isCompletedStatus
      ? 'complete'
      : TERMINAL_STATUSES.has(snapshot.status)
        ? 'error'
        : 'active';
    const stagePill = document.createElement('div');
    stagePill.className = `stage-pill ${stageState}`;
    const stageDot = document.createElement('span');
    stageDot.className = 'stage-dot';
    stagePill.appendChild(stageDot);
    const stageText = document.createElement('span');
    stageText.textContent = stageLabel;
    stagePill.appendChild(stageText);
    card.appendChild(stagePill);
  }

  // Only show message if there's no resume URL (to avoid "resume generated successfully" when link is available)
  if (snapshot.message && !resumeUrl) {
    const messageEl = document.createElement('div');
    messageEl.style.fontSize = '13px';
    messageEl.style.marginBottom = '8px';
    if (!isTerminal(snapshot.status)) {
      const spinner = document.createElement('span');
      spinner.className = 'loading';
      messageEl.appendChild(spinner);
    }
    const text = document.createElement('span');
    text.textContent = snapshot.message;
    messageEl.appendChild(text);
    card.appendChild(messageEl);
  }

  // Footer with last updated time (positioned at bottom left)
  const footer = document.createElement('div');
  footer.className = 'card-footer';

  const updatedAt = snapshot.updated_at ? new Date(snapshot.updated_at * 1000) : null;
  const updatedText = updatedAt ? `${formatRelativeTime(updatedAt)}` : 'In progress';

  const timeEl = document.createElement('span');
  timeEl.textContent = updatedText;
  footer.appendChild(timeEl);

  card.appendChild(footer);

  return card;
}

function clearActiveCard() {
  activeCardContainer.innerHTML = '';
}

function clearHistorySection() {
  historySection.innerHTML = '';
}

function setButtonLoading(isLoading) {
  if (isLoading) {
    processBtn.disabled = true;
    processBtn.innerHTML = '<span class="loading"></span><span>Creating…</span>';
  } else {
    processBtn.disabled = false;
    processBtn.innerHTML = `
      <span class="btn-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </span>
      <span>Create Resume</span>
    `;
  }
}

function hideMessage() {
  messageDiv.style.display = 'none';
  messageDiv.textContent = '';
  messageDiv.className = 'status info-status';
}

function setStatusMessage(message, variant = 'info-status') {
  messageDiv.innerHTML = message;
  messageDiv.className = `status ${variant}`;
  messageDiv.style.display = 'block';
}

function formatStatus(status) {
  const labels = {
    completed: 'Completed',
    failed: 'Failed',
    processing: 'In Progress',
    no_sponsorship: 'Stopped',
    screening_blocked: 'Screening Blocked',
    not_started: 'Not Started',
  };
  return labels[status] || status;
}

function formatRelativeTime(date) {
  if (!(date instanceof Date)) {
    return 'just now';
  }

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();

  if (Number.isNaN(diffMs) || diffMs < 0) {
    return date.toLocaleString();
  }

  const diffSeconds = Math.floor(diffMs / 1000);
  if (diffSeconds < 45) {
    return 'a few seconds ago';
  }
  if (diffSeconds < 90) {
    return '1 min ago';
  }

  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) {
    return diffMinutes === 1 ? '1 min ago' : `${diffMinutes} mins ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 6) {
    return diffHours === 1 ? '1 hour ago' : `${diffHours} hours ago`;
  }

  const sameDay = now.toDateString() === date.toDateString();
  if (sameDay) {
    return `${formatClockTime(date)} today`;
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);

  if (yesterday.toDateString() === date.toDateString()) {
    return `yesterday ${formatClockTime(date)}`;
  }

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) {
    return diffDays === 1 ? '1 day ago' : `${diffDays} days ago`;
  }

  return date.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

function formatClockTime(date) {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const period = hours >= 12 ? 'pm' : 'am';
  const displayHour = hours % 12 === 0 ? 12 : hours % 12;
  const displayMinutes = minutes < 10 ? `0${minutes}` : minutes;
  return `${displayHour}:${displayMinutes} ${period}`;
}

function isTerminal(status) {
  return TERMINAL_STATUSES.has(status);
}

function normalizeUrl(rawUrl = '') {
  try {
    const parsed = new URL(rawUrl);
    const scheme = parsed.protocol ? parsed.protocol.replace(':', '') : 'https';
    const host = parsed.host.toLowerCase();
    let path = parsed.pathname || '';
    if (path.length > 1 && path.endsWith('/')) {
      path = path.slice(0, -1);
    }

    const jobUrl = `${scheme}://${host}${path}`;
    const baseUrl = `${scheme}://${host}`;

    return { jobUrl, baseUrl };
  } catch (error) {
    console.warn('Failed to normalize URL:', rawUrl, error);
    return { jobUrl: '', baseUrl: '' };
  }
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0] || null;
}

async function getSelectionFromTab(tabId) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => window.getSelection().toString().trim(),
  });
  return result;
}

function extractJobInfo(snapshot) {
  const metadata = snapshot.metadata || {};
  const jobMeta = metadata.job_metadata || metadata || {};
  return {
    title: jobMeta.title || '',
    company: jobMeta.company || '',
    selectionSnippet: metadata.selection_snippet || jobMeta.selection_snippet || '',
  };
}

function getSelectionSnippet(snapshot) {
  if (!snapshot) {
    return '';
  }

  return snapshot.selection_snippet
    || snapshot.metadata?.selection_snippet
    || snapshot.metadata?.job_metadata?.selection_snippet
    || '';
}

async function refreshSelectionPreview() {
  try {
    const tab = await getActiveTab();
    if (!tab?.id) {
      return;
    }

    const selectedText = await getSelectionFromTab(tab.id);
    if (selectedText) {
      updateSelectedSnippet(selectedText);
    }
  } catch (error) {
    console.warn('Unable to read current selection snippet:', error);
  }
}

function updateSelectedSnippet(text) {
  if (!selectedSnippetDiv) {
    return;
  }

  if (text) {
    const trimmed = text.slice(0, 30);
    selectedSnippetDiv.textContent = `Selected: “${trimmed}${text.length > 30 ? '…' : ''}”`;
    selectedSnippetDiv.style.display = 'inline-flex';
    selectedSnippetDiv.setAttribute('title', text);
  } else {
    selectedSnippetDiv.textContent = '';
    selectedSnippetDiv.style.display = 'none';
    selectedSnippetDiv.removeAttribute('title');
  }
}

async function markAsApplied(statusId) {
  try {
    const response = await fetch(MARK_APPLIED_ENDPOINT(statusId), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ applied: true }),
    });

    if (!response.ok) {
      const result = await response.json();
      throw new Error(result?.error || `Failed to mark as applied (${response.status})`);
    }

    // Refresh the status to hide the applied job
    await refreshStatus();
    
    // Refresh applied section if it's expanded
    if (appliedToggle.classList.contains('expanded')) {
      await loadAppliedResumes();
    }
  } catch (error) {
    console.error('Failed to mark as applied:', error);
    setStatusMessage(`Failed to mark as applied: ${escapeHtml(error.message)}`, 'error');
  }
}

async function toggleAppliedSection() {
  const isExpanded = appliedToggle.classList.contains('expanded');
  
  if (isExpanded) {
    // Collapse
    appliedToggle.classList.remove('expanded');
    appliedContainer.style.display = 'none';
  } else {
    // Expand
    appliedToggle.classList.add('expanded');
    appliedContainer.style.display = 'block';
    
    // Load applied resumes if container is empty
    if (appliedContainer.children.length === 0) {
      await loadAppliedResumes();
    }
  }
}

async function loadAppliedResumes() {
  try {
    const snapshots = await fetchAllSnapshots(true); // Include applied jobs
    const appliedSnapshots = snapshots.filter((snap) => {
      const metadata = snap.metadata || {};
      return metadata.applied === true;
    });

    appliedContainer.innerHTML = '';

    if (appliedSnapshots.length === 0) {
      const emptyState = document.createElement('div');
      emptyState.className = 'empty-state';
      emptyState.textContent = 'No applied resumes yet';
      appliedContainer.appendChild(emptyState);
      return;
    }

    appliedSnapshots.forEach((snapshot) => {
      const jobInfo = extractJobInfo(snapshot);
      const card = buildProgressCard(snapshot, {
        heading: jobInfo.title || snapshot.job_url || 'Resume',
        subheading: jobInfo.company || '',
        showResumeButton: Boolean(snapshot.resume_url),
      });
      appliedContainer.appendChild(card);
    });
  } catch (error) {
    console.error('Failed to load applied resumes:', error);
    appliedContainer.innerHTML = `
      <div class="empty-state">
        Failed to load applied resumes: ${escapeHtml(error.message)}
      </div>
    `;
  }
}

async function downloadResume(statusId, resumeUrl) {
  try {
    const params = new URLSearchParams();
    if (statusId) {
      params.set('status_id', statusId);
    } else if (resumeUrl) {
      params.set('resume_url', resumeUrl);
    } else {
      throw new Error('No status_id or resume_url provided');
    }

    const url = `${DOWNLOAD_RESUME_ENDPOINT}?${params.toString()}`;
    const response = await fetch(url);

    if (!response.ok) {
      const result = await response.json();
      throw new Error(result?.error || `Download failed (${response.status})`);
    }

    // Get filename from Content-Disposition header or use default
    const contentDisposition = response.headers.get('Content-Disposition');
    let filename = 'resume.docx';
    if (contentDisposition) {
      // Try to extract filename from Content-Disposition header
      // Format: attachment; filename="filename.docx" or attachment; filename*=UTF-8''filename.docx
      const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
      if (filenameMatch && filenameMatch[1]) {
        filename = filenameMatch[1].replace(/['"]/g, '').trim();
      }
      // If filename starts with UTF-8'' (RFC 5987 encoding), extract the actual filename
      if (filename.startsWith("UTF-8''")) {
        filename = decodeURIComponent(filename.replace(/^UTF-8''/, ''));
      }
    }
    
    // Fallback: use default if filename is still empty or invalid
    if (!filename || filename === 'download') {
      filename = 'resume.docx';
    }

    // Download the file as blob
    const blob = await response.blob();
    const blobUrl = window.URL.createObjectURL(blob);
    
    // Create temporary anchor element to trigger download
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    
    // Clean up blob URL
    window.URL.revokeObjectURL(blobUrl);
  } catch (error) {
    console.error('Failed to download resume:', error);
    setStatusMessage(`Failed to download resume: ${escapeHtml(error.message)}`, 'error');
  }
}

function escapeHtml(input) {
  return String(input)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
