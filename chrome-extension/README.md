# Resume Agent Chrome Extension

## Overview

This Chrome extension extracts job descriptions from popular job sites and sends them to your local Resume Agent server for AI-powered resume generation.

## Key Features & Limitations

### ✅ What It Can Do:
- **Extract job descriptions** from LinkedIn, Indeed, Glassdoor, and other major job sites
- **Send data to local server** (localhost:8000) for processing
- **Store temporary data** in session storage (memory only, not persisted)
- **Handle CORS properly** with Manifest V3 host_permissions

### ⚠️ Limitations & Considerations:

1. **Local Server Only**: Can only communicate with localhost:8000 (configured in manifest.json)
2. **No Remote Code**: All JavaScript must be bundled with the extension (Manifest V3 requirement)
3. **Service Workers**: Background scripts run as service workers (no persistent background pages)
4. **Storage Limits**: 
   - Session storage: 1MB limit, cleared when browser closes
   - Local storage: 5MB limit
   - No secure key storage built-in (server handles API keys)

## Installation

1. **Generate proper icons** (replace placeholder files):
   ```bash
   # Use an online converter to convert icons/icon.svg to PNG
   # Save as: icon16.png, icon48.png, icon128.png
   ```

2. **Load the extension**:
   - Open Chrome and navigate to `chrome://extensions/`
   - Enable "Developer mode" (top right)
   - Click "Load unpacked"
   - Select the `chrome-extension` directory

3. **Verify installation**:
   - Extension icon should appear in toolbar
   - Click icon to see popup

## Usage

1. **Start your local server** on port 8000
2. **Navigate to a job posting** on a supported site
3. **Click the extension icon**
4. **Click "Extract Job Description"**
5. **Review extracted data** and click "Generate Resume"
6. **Wait for generation** (15-30 seconds)
7. **Access your resume** via the Google Drive link

## Supported Sites

- LinkedIn (`linkedin.com`)
- Indeed (`indeed.com`) 
- Glassdoor (`glassdoor.com`)
- Dice (`dice.com`)
- AngelList/Wellfound (`angel.co`, `wellfound.com`)
- ZipRecruiter (`ziprecruiter.com`)

## Security Notes

- **No API keys stored**: All sensitive credentials remain on your local server
- **Session-only storage**: Job data stored temporarily in memory
- **Local-only communication**: No external API calls from extension
- **CORS handled properly**: Uses Manifest V3 host_permissions

## Troubleshooting

### "Server offline" status
- Ensure your Flask server is running on `http://localhost:8000`
- Check that the server has `/health` and `/generate-resume` endpoints

### Cannot extract job description
- Make sure you're on a job posting page (not search results)
- Try selecting the job description text manually
- Check if the site is supported

### CORS errors
- Server must include proper CORS headers:
  ```python
  response.headers['Access-Control-Allow-Origin'] = '*'
  ```

### Icons not showing
- Replace placeholder .png files with actual images
- Icons must be exactly 16x16, 48x48, and 128x128 pixels

## Development

### File Structure
```
chrome-extension/
├── manifest.json       # Extension configuration
├── background.js       # Service worker for API calls
├── content.js         # Job extraction logic
├── popup.html         # Extension UI
├── popup.js          # Popup logic
├── popup.css         # Styling
└── icons/            # Extension icons
```

### Making Changes
1. Edit files as needed
2. Go to `chrome://extensions/`
3. Click the refresh icon on your extension
4. Test changes

### Adding New Job Sites
Edit `content.js` and add extractors to `JOB_EXTRACTORS`:
```javascript
'newsite.com': {
  getJobDescription: () => { /* ... */ },
  getJobTitle: () => { /* ... */ },
  // etc.
}
```

## Notes on Manifest V3

This extension uses Chrome's Manifest V3, which includes:
- **Service workers** instead of background pages
- **Declarative permissions** for better security
- **No remote code execution**
- **Stricter content security policies**

These restrictions make the extension more secure but limit some functionality compared to Manifest V2.