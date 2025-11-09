// Popup script to extract job descriptions and send to server

// DOM elements
const processBtn = document.getElementById('processBtn');
const statusDiv = document.getElementById('status');

// Fixed server URL
const SERVER_URL = 'http://localhost:8000/generate-resume';

processBtn.addEventListener('click', async () => {
  // Reset status
  statusDiv.style.display = 'none';
  
  // Disable button and show loading
  processBtn.disabled = true;
  processBtn.innerHTML = '<span class="loading"></span>Processing...';
  
  try {
    // Get active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    // Get selected text from the page
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window.getSelection().toString().trim()
    });
    
    const selectedText = results[0].result;
    
    if (!selectedText || selectedText.length < 50) {
      throw new Error('Please select the job description text on the page first');
    }
    
    // Log extraction to console
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (url, text) => {
        console.log('=== SENDING TO SERVER ===');
        console.log('URL:', url);
        console.log('Job Description Length:', text.length, 'characters');
        console.log('First 200 chars:', text.substring(0, 200) + '...');
      },
      args: [tab.url, selectedText]
    });
    
    // Prepare simple payload with just URL and job description
    const payload = {
      job_description: selectedText,
      job_metadata: {
        job_url: tab.url
      }
    };
    
    // Send to server
    const response = await fetch(SERVER_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload)
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Server error (${response.status}): ${errorText}`);
    }
    
    const result = await response.json();
    
    // Show success with resume URL if available
    let successMessage = 'Resume generated successfully!';
    if (result.resume_url) {
      successMessage += ` <a href="${result.resume_url}" target="_blank" style="color: #059669; font-weight: bold;">Open Resume</a>`;
    }
    if (result.metadata) {
      successMessage += `<br><small>${result.metadata.bullets_count || 0} bullets, ${Math.round((result.metadata.keyword_coverage || 0) * 100)}% keyword coverage</small>`;
    }
    
    statusDiv.innerHTML = successMessage;
    statusDiv.className = 'status success';
    statusDiv.style.display = 'block';
    
    // Log server response to webpage console
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (result) => {
        console.log('=== SERVER RESPONSE ===');
        console.log('Status:', result.status);
        console.log('Resume URL:', result.resume_url);
        console.log('Metadata:', result.metadata);
      },
      args: [result]
    });
    
  } catch (error) {
    console.error('Error:', error);
    
    if (error.message.includes('Failed to fetch')) {
      statusDiv.innerHTML = `Cannot connect to server.<br><small>Make sure it's running at: ${SERVER_URL}</small>`;
    } else {
      statusDiv.textContent = error.message;
    }
    statusDiv.className = 'status error';
    statusDiv.style.display = 'block';
  } finally {
    // Re-enable button
    processBtn.disabled = false;
    processBtn.innerHTML = 'Extract & Send to Server';
  }
});