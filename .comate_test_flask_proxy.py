"""Test Flask proxy with multipart file upload"""
import sys
sys.path.insert(0, r'd:\erp_system')

import requests

# First, login to Flask to get a real session cookie
# Try to login via the Flask /api/login endpoint
login_data = {
    'username': 'admin',
    'password': 'admin123',  # Default admin password guess
}

# Try Flask login
try:
    session = requests.Session()
    r = session.post('http://127.0.0.1:5003/api/login', json=login_data, timeout=5)
    print(f"Login status: {r.status_code}")
    print(f"Login body: {r.text[:200]}")
    print(f"Cookies after login: {dict(session.cookies)}")
    
    if r.status_code == 200:
        # Now try OCR upload through Flask proxy
        files = {'files': ('test.txt', b'hello world', 'text/plain')}
        r2 = session.post(
            'http://127.0.0.1:5003/api/v1/ocr-import/upload',
            params={'session_id': 'proxy-test'},
            files=files,
            timeout=15,
        )
        print(f"\nUpload via proxy: Status={r2.status_code}")
        print(f"Body: {r2.text[:300]}")
except requests.exceptions.ConnectionError:
    print("Flask on port 5003 is not running, cannot test proxy")
except Exception as e:
    print(f"Error: {e}")
