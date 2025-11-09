// Popup script to manage resume generation workflow status

const processBtn = document.getElementById('processBtn');
const statusDiv = document.getElementById('status');

const SERVER_BASE_URL = 'http://localhost:8000';
const GENERATE_ENDPOINT = `${SERVER_BASE_URL}/generate-resume`;
const STATUS_ENDPOINT = `${SERVER_BASE_URL}/status`;

const POLL_INTERVAL_MS = 4000;
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'no_sponsorship', 'screening_blocked']);

const TAB_STATUS_KEY = 'tabStatusMap';
const JOB_STATUS_KEY = 'jobStatusMap';
const BASE_STATUS_KEY = 'baseStatusMap';

let currentTab = null;
let pollTimerId = null;

document.addEventListener('DOMContentLoaded', () => {
  processBtn.addEventListener('click', onProcessClick);
  refreshStatus();
});

async function onProcessClick() {
  stopPolling();
  clearStatus();
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
      await updateStoredStatusMaps(currentTab.id, {
        status_id: result.status_id,
        job_url: normalized.jobUrl,
        base_url: normalized.baseUrl,
      });
    }

    setStatusMessage('Resume generation started. Tracking progress…', 'info-status');
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
      return;
    }

    const normalized = normalizeUrl(currentTab.url || '');
    if (!normalized.jobUrl) {
      setStatusMessage('Open a job posting and select the description to begin.', 'info-status');
      return;
    }

    const storedEntry = await getStoredStatusEntry(currentTab.id, normalized.jobUrl, normalized.baseUrl);
    const context = {
      statusId: storedEntry?.statusId || null,
      jobUrl: storedEntry?.jobUrl || normalized.jobUrl,
      baseUrl: storedEntry?.baseUrl || normalized.baseUrl,
    };

    const snapshot = await fetchStatus(context);
    if (snapshot.status_id) {
      await updateStoredStatusMaps(currentTab.id, snapshot);
      context.statusId = snapshot.status_id;
      context.jobUrl = snapshot.job_url || context.jobUrl;
      context.baseUrl = snapshot.base_url || context.baseUrl;
    }

    renderSnapshot(snapshot);

    if (!isTerminal(snapshot.status) && (context.statusId || context.jobUrl || context.baseUrl)) {
      startPolling(context);
    }
  } catch (error) {
    console.error('Failed to refresh status:', error);
    setStatusMessage(`Failed to refresh status: ${escapeHtml(error.message)}`, 'error');
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
  return data.snapshot || {
    status: 'not_started',
    step: 'idle',
    message: '',
    job_url: context.jobUrl,
    base_url: context.baseUrl,
  };
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

      renderSnapshot(snapshot);

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

function renderSnapshot(snapshot) {
  if (!snapshot) {
    setStatusMessage('No progress tracked yet for this page.', 'info-status');
    return;
  }

  const status = snapshot.status || 'not_started';
  const step = snapshot.step || 'idle';
  const message = snapshot.message || '';
  const resumeUrl = snapshot.resume_url || '';
  const updatedAt = snapshot.updated_at ? new Date(snapshot.updated_at * 1000) : null;

  let variant = 'info-status';
  if (status === 'completed') {
    variant = 'success';
  } else if (status === 'failed' || status === 'no_sponsorship' || status === 'screening_blocked') {
    variant = 'error';
  }

  const parts = [
    `<div><strong>Status:</strong> ${escapeHtml(formatStatus(status))}</div>`,
    `<div><strong>Step:</strong> ${escapeHtml(formatStep(step))}</div>`,
  ];

  if (message) {
    parts.push(`<div>${escapeHtml(message)}</div>`);
  }

  if (resumeUrl) {
    parts.push(
      `<div><a href="${encodeURI(resumeUrl)}" target="_blank" style="color: #059669; font-weight: bold;">Open Resume</a></div>`
    );
  }

  const metadata = snapshot.metadata || {};
  if (metadata.validation_result && typeof metadata.validation_result.keyword_coverage_score === 'number') {
    const pct = Math.round(metadata.validation_result.keyword_coverage_score * 100);
    parts.push(`<div>Keyword coverage: ${pct}%</div>`);
  }

  if (metadata.job_metadata && metadata.job_metadata.title) {
    parts.push(`<div>${escapeHtml(metadata.job_metadata.title)} @ ${escapeHtml(metadata.job_metadata.company || '')}</div>`);
  }

  if (updatedAt) {
    parts.push(`<div class="info">Updated ${updatedAt.toLocaleTimeString()}</div>`);
  }

  statusDiv.innerHTML = parts.join('');
  statusDiv.className = `status ${variant}`;
  statusDiv.style.display = 'block';
}

function setButtonLoading(isLoading) {
  if (isLoading) {
    processBtn.disabled = true;
    processBtn.innerHTML = '<span class="loading"></span>Processing...';
  } else {
    processBtn.disabled = false;
    processBtn.innerHTML = 'Extract & Send to Server';
  }
}

function clearStatus() {
  statusDiv.style.display = 'none';
  statusDiv.textContent = '';
  statusDiv.className = 'status info-status';
}

function setStatusMessage(message, variant = 'info-status') {
  statusDiv.innerHTML = message;
  statusDiv.className = `status ${variant}`;
  statusDiv.style.display = 'block';
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

function formatStep(step) {
  if (!step || step === 'idle') {
    return 'Idle';
  }
  return step
    .split('_')
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
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
  const entry = {
    statusId: snapshot.status_id,
    jobUrl: normalizedJob,
    baseUrl: normalizedBase,
    updatedAt: Date.now(),
  };

  const data = await storageGet([TAB_STATUS_KEY, JOB_STATUS_KEY, BASE_STATUS_KEY]);
  const tabMap = { ...(data[TAB_STATUS_KEY] || {}) };
  const jobMap = { ...(data[JOB_STATUS_KEY] || {}) };
  const baseMap = { ...(data[BASE_STATUS_KEY] || {}) };

  if (tabId !== null && tabId !== undefined) {
    tabMap[`tab-${tabId}`] = entry;
  }

  if (entry.jobUrl) {
    jobMap[entry.jobUrl] = entry;
  }

  if (entry.baseUrl) {
    baseMap[entry.baseUrl] = entry;
  }

  await storageSet({
    [TAB_STATUS_KEY]: tabMap,
    [JOB_STATUS_KEY]: jobMap,
    [BASE_STATUS_KEY]: baseMap,
  });
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