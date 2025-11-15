// Popup script to manage resume generation workflow status

const processBtn = document.getElementById('processBtn');
const messageDiv = document.getElementById('message');
const selectedSnippetDiv = document.getElementById('selectedSnippet');
const activeCardContainer = document.getElementById('activeCard');
const historySection = document.getElementById('historySection');

const SERVER_BASE_URL = 'http://localhost:8000';
const GENERATE_ENDPOINT = `${SERVER_BASE_URL}/generate-resume`;
const STATUS_ENDPOINT = `${SERVER_BASE_URL}/status`;
const STATUS_LIST_ENDPOINT = `${SERVER_BASE_URL}/statuses`;

const POLL_INTERVAL_MS = 4000;
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'no_sponsorship', 'screening_blocked']);

const TAB_STATUS_KEY = 'tabStatusMap';
const JOB_STATUS_KEY = 'jobStatusMap';
const BASE_STATUS_KEY = 'baseStatusMap';
const RECENT_STATUS_KEY = 'recentStatusHistory';
const MAX_HISTORY_ENTRIES = 5;

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
  ['no_sponsorship', 'No Sponsorship'],
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

document.addEventListener('DOMContentLoaded', () => {
  processBtn.addEventListener('click', onProcessClick);
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
      await updateStoredStatusMaps(
        currentTab.id,
        { ...result, selection_snippet: selectedText }
      );
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

    const storedEntry = await getStoredStatusEntry(currentTab.id, normalized.jobUrl, normalized.baseUrl);
    const context = buildContextFromEntry(storedEntry, normalized);

    let snapshot = null;
    let matched = Boolean(context.statusId);

    if (matched) {
      snapshot = await fetchStatus(context);
      matched = snapshot.__responseStatus === 'success';
    }

    if (matched && snapshot) {
      hideMessage();
      renderActiveSnapshot(snapshot, true);
      clearHistorySection();

      if (!isTerminal(snapshot.status)) {
        startPolling(context);
      }
      return;
    }

    const allSnapshots = await fetchAllSnapshots(true);
    const normalizedJobUrl = normalized.jobUrl;
    const matchingSnapshot = allSnapshots.find((snap) => {
      const snapUrl = snap.job_url || '';
      return normalizeUrl(snapUrl).jobUrl === normalizedJobUrl;
    });

    hideMessage();
    clearHistorySection();

    if (matchingSnapshot) {
      renderActiveSnapshot(matchingSnapshot, true);
      if (!isTerminal(matchingSnapshot.status)) {
        const contextFromMatch = buildContextFromSnapshot(matchingSnapshot);
        startPolling(contextFromMatch);
      }
      const remaining = allSnapshots.filter(
        (snap) => snap.status_id !== matchingSnapshot.status_id
      );
      if (remaining.length) {
        renderStatusList(remaining, 'Recent Resumes');
      }
      return;
    }

    if (!allSnapshots.length) {
      setStatusMessage('No resumes generated yet. Run the extractor on a job description to get started.', 'info-status');
      clearActiveCard();
      clearHistorySection();
      updateSelectedSnippet('');
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

async function fetchAllSnapshots(includeApplied = true) {
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

function startPolling(context) {
  stopPolling();

  pollTimerId = setInterval(async () => {
    try {
      const snapshot = await fetchStatus(context);

      if (snapshot.status_id) {
        await updateStoredStatusMaps(currentTab?.id ?? null, snapshot);
        context.statusId = snapshot.status_id;
        context.jobUrl = snapshot.job_url || context.jobUrl;
        context.baseUrl = snapshot.base_url || context.baseUrl;
      }

      hideMessage();
      renderActiveSnapshot(snapshot, true);
      clearHistorySection();

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
    const snapshots = await fetchAllSnapshots(true);
    clearActiveCard();
    renderStatusList(snapshots, 'Recent Resumes');
  } catch (error) {
    console.warn('Unable to retrieve status list:', error);
    clearActiveCard();
    clearHistorySection();
    updateSelectedSnippet('');
  }
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

  const isRawUrlHeading = typeof heading === 'string' && /^https?:\/\//i.test(heading.trim());
  const titleEl = document.createElement(isRawUrlHeading ? 'div' : 'h2');
  titleEl.textContent = heading;
  if (isRawUrlHeading) {
    titleEl.className = 'card-url';
  }
  card.appendChild(titleEl);

  if (subheading) {
    const subtitleEl = document.createElement('small');
    subtitleEl.textContent = subheading;
    card.appendChild(subtitleEl);
  }

  const resumeUrl = snapshot.resume_url || (snapshot.metadata && snapshot.metadata.resume_url);
  const isCompletedStatus = snapshot.status === 'completed' || snapshot.status === 'success';

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

  if (snapshot.message) {
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

  const metadata = snapshot.metadata || {};
  if (metadata.validation_result && typeof metadata.validation_result.keyword_coverage_score === 'number') {
    let coverageValue = metadata.validation_result.keyword_coverage_score;
    if (coverageValue <= 1) {
      coverageValue = Math.round(coverageValue * 100);
    } else {
      coverageValue = Math.round(coverageValue);
    }
    const coverageEl = document.createElement('div');
    coverageEl.style.fontSize = '13px';
    coverageEl.style.marginBottom = '8px';
    coverageEl.textContent = `Keyword coverage: ${coverageValue}%`;
    card.appendChild(coverageEl);
  }

  const footer = document.createElement('div');
  footer.className = 'card-footer';

  const updatedAt = snapshot.updated_at ? new Date(snapshot.updated_at * 1000) : null;
  const updatedText = updatedAt ? `Updated ${formatRelativeTime(updatedAt)}` : 'In progress';

  if (resumeUrl && showResumeButton) {
    const actionGroup = document.createElement('div');
    actionGroup.className = 'resume-action';

    const resumeBtn = document.createElement('button');
    resumeBtn.className = 'resume-icon';
    resumeBtn.title = 'Open generated resume';
    resumeBtn.setAttribute('aria-label', 'Open generated resume');
    resumeBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 15l6-6" />
        <path d="M9 9h6v6" />
      </svg>
    `;
    resumeBtn.addEventListener('click', () => {
      chrome.tabs.create({ url: resumeUrl });
    });

    const timeEl = document.createElement('span');
    timeEl.textContent = updatedText;

    actionGroup.appendChild(resumeBtn);
    actionGroup.appendChild(timeEl);
    footer.appendChild(actionGroup);
  } else {
    const timeEl = document.createElement('span');
    timeEl.textContent = updatedText;
    footer.appendChild(timeEl);
  }

  card.appendChild(footer);

  return card;
}

async function getRecentHistory() {
  const data = await storageGet([RECENT_STATUS_KEY]);
  return data[RECENT_STATUS_KEY] || [];
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
    no_sponsorship: 'No Sponsorship',
    screening_blocked: 'Screening Blocked',
    not_started: 'Not Started',
  };
  return labels[status] || status;
}

function formatRelativeTime(date) {
  if (!(date instanceof Date)) {
    return 'recently';
  }

  const now = Date.now();
  const diffMs = now - date.getTime();

  if (Number.isNaN(diffMs)) {
    return date.toLocaleString();
  }

  if (diffMs < 0) {
    return date.toLocaleString();
  }

  const diffSeconds = Math.floor(diffMs / 1000);
  if (diffSeconds < 30) {
    return 'just now';
  }
  if (diffSeconds < 60) {
    return 'less than a minute ago';
  }

  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) {
    return diffMinutes === 1 ? '1 minute ago' : `${diffMinutes} minutes ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return diffHours === 1 ? '1 hour ago' : `${diffHours} hours ago`;
  }

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) {
    return diffDays === 1 ? '1 day ago' : `${diffDays} days ago`;
  }

  const diffWeeks = Math.floor(diffDays / 7);
  if (diffWeeks < 5) {
    return diffWeeks === 1 ? '1 week ago' : `${diffWeeks} weeks ago`;
  }

  return date.toLocaleDateString();
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

async function getStoredStatusEntry(tabId, jobUrl, baseUrl) {
  const data = await storageGet([TAB_STATUS_KEY, JOB_STATUS_KEY, BASE_STATUS_KEY]);
  const tabMap = data[TAB_STATUS_KEY] || {};
  const jobMap = data[JOB_STATUS_KEY] || {};
  const baseMap = data[BASE_STATUS_KEY] || {};

  if (tabId !== null && tabId !== undefined) {
    const tabEntry = tabMap[`tab-${tabId}`];
    if (tabEntry) {
      return tabEntry;
    }
  }

  if (jobUrl && jobMap[jobUrl]) {
    return { jobUrl, baseUrl, ...jobMap[jobUrl] };
  }

  if (baseUrl && baseMap[baseUrl]) {
    return { jobUrl, baseUrl, ...baseMap[baseUrl] };
  }

  return null;
}

async function updateStoredStatusMaps(tabId, snapshot) {
  if (!snapshot || !snapshot.status_id) {
    return;
  }

  const normalizedJob = snapshot.job_url || (snapshot.jobUrl ?? '');
  const normalizedBase = snapshot.base_url || (normalizedJob ? normalizeUrl(normalizedJob).baseUrl : (snapshot.baseUrl ?? ''));
  const data = await storageGet([TAB_STATUS_KEY, JOB_STATUS_KEY, BASE_STATUS_KEY, RECENT_STATUS_KEY]);
  const tabMap = { ...(data[TAB_STATUS_KEY] || {}) };
  const jobMap = { ...(data[JOB_STATUS_KEY] || {}) };
  const baseMap = { ...(data[BASE_STATUS_KEY] || {}) };
  const history = Array.isArray(data[RECENT_STATUS_KEY]) ? [...data[RECENT_STATUS_KEY]] : [];

  const existingEntries = [];
  if (tabId !== null && tabId !== undefined) {
    existingEntries.push(tabMap[`tab-${tabId}`]);
  }
  if (normalizedJob) {
    existingEntries.push(jobMap[normalizedJob]);
  }
  if (normalizedBase) {
    existingEntries.push(baseMap[normalizedBase]);
  }
  const existingSnippet = existingEntries.find((item) => item && item.selectionSnippet)?.selectionSnippet;
  const selectionSnippet = snapshot.selection_snippet || existingSnippet || '';
  if (!snapshot.selection_snippet && selectionSnippet) {
    snapshot.selection_snippet = selectionSnippet;
  }
  const jobHash =
    snapshot.metadata?.job_hash ||
    snapshot.metadata?.job_metadata?.job_hash ||
    snapshot.job_hash ||
    existingEntries.find((item) => item && item.jobHash)?.jobHash ||
    '';

  const entry = {
    statusId: snapshot.status_id,
    jobUrl: normalizedJob,
    baseUrl: normalizedBase,
    updatedAt: snapshot.updated_at ? snapshot.updated_at * 1000 : Date.now(),
    selectionSnippet,
    jobHash,
  };

  if (tabId !== null && tabId !== undefined) {
    tabMap[`tab-${tabId}`] = entry;
  }

  if (entry.jobUrl) {
    jobMap[entry.jobUrl] = entry;
  }

  if (entry.baseUrl) {
    baseMap[entry.baseUrl] = entry;
  }

  const historyEntry = buildHistoryEntry(snapshot, entry);
  const filteredHistory = history.filter((item) => item.statusId !== historyEntry.statusId);
  filteredHistory.unshift(historyEntry);
  const trimmedHistory = filteredHistory.slice(0, MAX_HISTORY_ENTRIES);

  await storageSet({
    [TAB_STATUS_KEY]: tabMap,
    [JOB_STATUS_KEY]: jobMap,
    [BASE_STATUS_KEY]: baseMap,
    [RECENT_STATUS_KEY]: trimmedHistory,
  });
}

function buildHistoryEntry(snapshot, entry) {
  const metadata = snapshot.metadata || {};
  const jobMeta = metadata.job_metadata || {};
  const selectionSnippet = snapshot.selection_snippet || entry.selectionSnippet || metadata.selection_snippet || jobMeta.selection_snippet || '';

  const historyMetadata = {
    ...metadata,
    selection_snippet: selectionSnippet,
    job_metadata: {
      ...jobMeta,
      selection_snippet: selectionSnippet,
    },
  };

  return {
    statusId: entry.statusId,
    jobUrl: entry.jobUrl,
    baseUrl: entry.baseUrl,
    status: snapshot.status || 'processing',
    step: snapshot.step || '',
    message: snapshot.message || '',
    resumeUrl: snapshot.resume_url || '',
    updatedAt: entry.updatedAt,
    jobTitle: jobMeta.title || metadata.title || '',
    company: jobMeta.company || metadata.company || '',
    metadata: historyMetadata,
    selectionSnippet,
  };
}

function convertHistoryEntryToSnapshot(entry) {
  return {
    status: entry.status,
    step: entry.step,
    message: entry.message,
    resume_url: entry.resumeUrl,
    metadata: entry.metadata || {
      job_metadata: {
        title: entry.jobTitle,
        company: entry.company,
      }
    },
    updated_at: Math.floor((entry.updatedAt || Date.now()) / 1000),
    status_id: entry.statusId,
    job_url: entry.jobUrl,
    base_url: entry.baseUrl,
    selection_snippet: entry.selectionSnippet || '',
  };
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

function buildContextFromEntry(entry, fallbackNormalized) {
  if (entry) {
    return {
      statusId: entry.statusId || null,
      jobUrl: entry.jobUrl || fallbackNormalized.jobUrl,
      baseUrl: entry.baseUrl || fallbackNormalized.baseUrl,
    };
  }

  return {
    statusId: null,
    jobUrl: fallbackNormalized.jobUrl,
    baseUrl: fallbackNormalized.baseUrl,
  };
}

function buildContextFromSnapshot(snapshot) {
  if (!snapshot) {
    return {
      statusId: null,
      jobUrl: '',
      baseUrl: '',
    };
  }
  return {
    statusId: snapshot.status_id || null,
    jobUrl: snapshot.job_url || '',
    baseUrl: snapshot.base_url || '',
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

function escapeHtml(input) {
  return String(input)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function storageGet(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.get(keys, (result) => resolve(result || {}));
  });
}

function storageSet(items) {
  return new Promise((resolve) => {
    chrome.storage.local.set(items, () => resolve());
  });
}