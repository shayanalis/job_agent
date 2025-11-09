"""Test script to verify H1B sponsorship detection"""

import requests
import json

# Test job description with no sponsorship
test_jd_no_sponsorship = """
Senior Software Engineer

About the Role:
We are looking for a Senior Software Engineer to join our team. This is a full-time position.

Requirements:
- 5+ years of experience in software development
- Strong Python and JavaScript skills
- Experience with AWS

Important: Candidates must be authorized to work in the United States. We are unable to sponsor visas at this time.

Apply now!
"""

# Test job description with sponsorship unclear
test_jd_unclear = """
Software Developer Position

Join our growing team as a Software Developer!

What we're looking for:
- Bachelor's degree in Computer Science
- 3+ years experience
- Java, Spring Boot expertise

We offer competitive salary and benefits.
"""

def test_sponsorship_detection():
    """Test the sponsorship detection endpoint"""
    
    url = "http://localhost:5000/generate-resume"
    
    # Test 1: Job with no sponsorship
    print("\n=== Test 1: Job with NO sponsorship ===")
    payload = {
        "job_description": test_jd_no_sponsorship,
        "job_metadata": {
            "job_url": "https://example.com/job/no-sponsor",
            "title": "Senior Software Engineer",
            "company": "NoSponsor Corp"
        }
    }
    
    response = requests.post(url, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    # Test 2: Job with unclear sponsorship
    print("\n\n=== Test 2: Job with UNCLEAR sponsorship ===")
    payload = {
        "job_description": test_jd_unclear,
        "job_metadata": {
            "job_url": "https://example.com/job/unclear",
            "title": "Software Developer", 
            "company": "Maybe Corp"
        }
    }
    
    response = requests.post(url, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

if __name__ == "__main__":
    print("Testing H1B sponsorship detection...")
    print("Make sure the server is running on localhost:5000")
    
    try:
        test_sponsorship_detection()
    except requests.exceptions.ConnectionError:
        print("\nERROR: Could not connect to server. Make sure it's running with:")
        print("python src/api/server.py")
    except Exception as e:
        print(f"\nERROR: {e}")