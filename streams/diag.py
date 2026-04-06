import requests

url = "https://511.vdot.virginia.gov/api/map/layers/map/cams"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Referer": "https://511.vdot.virginia.gov/",
    "Accept": "application/json, text/plain, */*",
}

resp = requests.get(url, headers=headers, timeout=15)
print(f"Status: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('Content-Type')}")
print(f"Content-Length: {len(resp.content)} bytes")
print(f"First 500 chars: {repr(resp.text[:500])}")
