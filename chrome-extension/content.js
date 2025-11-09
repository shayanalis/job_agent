// Content script for job description extraction
// Runs on supported job sites to extract JD information

const JOB_EXTRACTORS = {
  'metacareers.com': {
    getJobDescription: () => {
      // Meta Careers specific selectors
      const jobDescElement = document.querySelector('[data-testid="job-description"]') ||
                            document.querySelector('.x1iyjqo2.xeuugli.x1odjw0f') ||
                            document.querySelector('[class*="job-description"]') ||
                            document.querySelector('div[dir="auto"]');
      
      // Try to find the main content area if above fails
      if (!jobDescElement) {
        const mainContent = document.querySelector('main') || document.querySelector('[role="main"]');
        if (mainContent) {
          // Look for a div with substantial text content
          const textDivs = mainContent.querySelectorAll('div');
          for (const div of textDivs) {
            if (div.innerText && div.innerText.length > 200 && 
                !div.innerText.includes('Resume Match') &&
                !div.innerText.includes('keywords')) {
              return div.innerText;
            }
          }
        }
      }
      
      return jobDescElement ? jobDescElement.innerText : '';
    },
    getJobTitle: () => {
      const titleElement = document.querySelector('h1') ||
                          document.querySelector('[role="heading"][aria-level="1"]') ||
                          document.querySelector('[data-testid="job-title"]');
      return titleElement ? titleElement.innerText.trim() : '';
    },
    getCompany: () => {
      // Meta careers usually shows "Meta" as company
      return 'Meta';
    },
    getLocation: () => {
      const locationElement = document.querySelector('[data-testid="job-location"]') ||
                             document.querySelector('[class*="location"]');
      return locationElement ? locationElement.innerText.trim() : '';
    },
    getPostedDate: () => {
      const dateElement = document.querySelector('[data-testid="posted-date"]') ||
                         document.querySelector('time');
      return dateElement ? dateElement.innerText.trim() : '';
    }
  },
  
  'linkedin.com': {
    getJobDescription: () => {
      // LinkedIn job posting selectors
      const jobDescElement = document.querySelector('.jobs-description__content') || 
                            document.querySelector('.description__text') ||
                            document.querySelector('[data-job-description]');
      return jobDescElement ? jobDescElement.innerText : '';
    },
    getJobTitle: () => {
      const titleElement = document.querySelector('.jobs-unified-top-card__job-title') ||
                          document.querySelector('.topcard__title') ||
                          document.querySelector('h1');
      return titleElement ? titleElement.innerText.trim() : '';
    },
    getCompany: () => {
      const companyElement = document.querySelector('.jobs-unified-top-card__company-name') ||
                            document.querySelector('.topcard__org-name-link') ||
                            document.querySelector('[data-company-name]');
      return companyElement ? companyElement.innerText.trim() : '';
    },
    getLocation: () => {
      const locationElement = document.querySelector('.jobs-unified-top-card__workplace-type') ||
                             document.querySelector('.topcard__flavor--bullet');
      return locationElement ? locationElement.innerText.trim() : '';
    },
    getPostedDate: () => {
      const dateElement = document.querySelector('.jobs-unified-top-card__posted-date') ||
                         document.querySelector('time');
      return dateElement ? dateElement.innerText.trim() : '';
    }
  },
  
  'indeed.com': {
    getJobDescription: () => {
      const jobDescElement = document.querySelector('#jobDescriptionText') ||
                            document.querySelector('.jobsearch-JobComponent-description');
      return jobDescElement ? jobDescElement.innerText : '';
    },
    getJobTitle: () => {
      const titleElement = document.querySelector('h1 span') ||
                          document.querySelector('.jobsearch-JobInfoHeader-title');
      return titleElement ? titleElement.innerText.trim() : '';
    },
    getCompany: () => {
      const companyElement = document.querySelector('[data-testid="company-name"]') ||
                            document.querySelector('.jobsearch-CompanyInfoWithoutHeaderImage a');
      return companyElement ? companyElement.innerText.trim() : '';
    },
    getLocation: () => {
      const locationElement = document.querySelector('[data-testid="job-location"]') ||
                             document.querySelector('.jobsearch-JobInfoHeader-subtitle > div:nth-child(2)');
      return locationElement ? locationElement.innerText.trim() : '';
    },
    getPostedDate: () => {
      const dateElement = document.querySelector('.jobsearch-JobMetadataFooter') ||
                         document.querySelector('[data-testid="job-age"]');
      return dateElement ? dateElement.innerText.trim() : '';
    }
  },
  
  'glassdoor.com': {
    getJobDescription: () => {
      const jobDescElement = document.querySelector('.jobDescriptionContent') ||
                            document.querySelector('[data-test="jobDescription"]');
      return jobDescElement ? jobDescElement.innerText : '';
    },
    getJobTitle: () => {
      const titleElement = document.querySelector('[data-test="job-title"]') ||
                          document.querySelector('.css-1vg6q84');
      return titleElement ? titleElement.innerText.trim() : '';
    },
    getCompany: () => {
      const companyElement = document.querySelector('[data-test="employer-name"]') ||
                            document.querySelector('.css-xuk5ye');
      return companyElement ? companyElement.innerText.trim() : '';
    },
    getLocation: () => {
      const locationElement = document.querySelector('[data-test="location"]') ||
                             document.querySelector('.css-56kyx5');
      return locationElement ? locationElement.innerText.trim() : '';
    },
    getPostedDate: () => {
      const dateElement = document.querySelector('[data-test="job-age"]');
      return dateElement ? dateElement.innerText.trim() : '';
    }
  }
};

function getCurrentSiteExtractor() {
  const hostname = window.location.hostname;
  for (const [site, extractor] of Object.entries(JOB_EXTRACTORS)) {
    if (hostname.includes(site)) {
      return extractor;
    }
  }
  return null;
}

function extractJobData() {
  const extractor = getCurrentSiteExtractor();
  
  if (!extractor) {
    // Fallback: Try generic extraction
    const genericExtractor = {
      getJobDescription: () => {
        // First check for selected text
        const selectedText = window.getSelection().toString().trim();
        if (selectedText && selectedText.length > 100) {
          return selectedText;
        }
        
        // Try to find main content area
        const mainContent = document.querySelector('main') || 
                          document.querySelector('[role="main"]') ||
                          document.querySelector('article') ||
                          document.querySelector('.job-description') ||
                          document.querySelector('#job-description');
        
        if (mainContent) {
          // Look for the largest text block that's not a navigation or header
          const textBlocks = mainContent.querySelectorAll('div, section, article');
          let largestBlock = null;
          let largestLength = 0;
          
          for (const block of textBlocks) {
            const text = block.innerText || '';
            // Skip if it contains common non-job-description content
            if (text.includes('Resume Match') || 
                text.includes('Sign in') || 
                text.includes('Cookie') ||
                text.length < 200) {
              continue;
            }
            
            if (text.length > largestLength) {
              largestLength = text.length;
              largestBlock = block;
            }
          }
          
          if (largestBlock) {
            return largestBlock.innerText;
          }
        }
        
        // Last resort: get all text from body
        const bodyText = document.body.innerText;
        if (bodyText && bodyText.length > 500) {
          return bodyText;
        }
        
        return '';
      },
      getJobTitle: () => {
        const h1 = document.querySelector('h1');
        return h1 ? h1.innerText.trim() : 'Unknown';
      },
      getCompany: () => 'Unknown',
      getLocation: () => 'Unknown', 
      getPostedDate: () => 'Unknown'
    };
    
    const jobData = {
      jobDescription: genericExtractor.getJobDescription(),
      jobTitle: genericExtractor.getJobTitle(),
      company: genericExtractor.getCompany(),
      location: genericExtractor.getLocation(),
      postedDate: genericExtractor.getPostedDate(),
      url: window.location.href,
      extractionMethod: 'generic'
    };
    
    // Only return if we got meaningful content
    if (jobData.jobDescription && jobData.jobDescription.length > 100) {
      return jobData;
    }
    
    return null;
  }
  
  try {
    const jobData = {
      jobDescription: extractor.getJobDescription(),
      jobTitle: extractor.getJobTitle(),
      company: extractor.getCompany(),
      location: extractor.getLocation(),
      postedDate: extractor.getPostedDate(),
      url: window.location.href,
      extractionMethod: 'automatic'
    };
    
    // Validate that we got at least the job description
    if (!jobData.jobDescription || jobData.jobDescription.length < 50) {
      return null;
    }
    
    return jobData;
  } catch (error) {
    console.error('Error extracting job data:', error);
    return null;
  }
}

// Listen for messages from the popup/background script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'extractJobData') {
    const jobData = extractJobData();
    sendResponse({ success: !!jobData, data: jobData });
  }
  return true; // Keep the message channel open for async response
});