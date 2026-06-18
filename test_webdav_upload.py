"""
Test script to debug WebDAV upload issue.
Run this on your local machine (not Railway) to compare behavior.

Usage:
    python3 test_webdav_upload.py
"""

import io
import requests
from webdav3.client import Client

WEBDAV_USERNAME = "static"
WEBDAV_PASSWORD = "12345678"  # replace if different
WEBDAV_HOST = "https://static.hobbylab.co.il/upload"

print("=" * 60)
print("TEST 1: Plain requests HEAD on /upload/ (baseline)")
print("=" * 60)
r = requests.head(
    "https://static.hobbylab.co.il/upload/",
    auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD),
)
print("Status:", r.status_code)
print("Headers:", dict(r.headers))
print()

print("=" * 60)
print("TEST 2: webdav3 client.check() on root '/' (what webdavclient3 does internally)")
print("=" * 60)
try:
    client = Client({
        "webdav_hostname": WEBDAV_HOST,
        "webdav_login": WEBDAV_USERNAME,
        "webdav_password": WEBDAV_PASSWORD,
    })
    exists = client.check("/")
    print("check('/') result:", exists)
except Exception as e:
    print("ERROR:", repr(e))
print()

print("=" * 60)
print("TEST 3: webdav3 client.upload_to() - the actual failing operation")
print("=" * 60)
try:
    client = Client({
        "webdav_hostname": WEBDAV_HOST,
        "webdav_login": WEBDAV_USERNAME,
        "webdav_password": WEBDAV_PASSWORD,
    })
    test_bytes = b"hello world test upload"
    client.upload_to(buff=io.BytesIO(test_bytes), remote_path="debug_test_upload.txt")
    print("Upload succeeded!")
except Exception as e:
    print("ERROR:", repr(e))
print()

print("=" * 60)
print("TEST 4: Raw PROPFIND request with requests (what webdav3's check() does under the hood)")
print("=" * 60)
r = requests.request(
    "PROPFIND",
    "https://static.hobbylab.co.il/upload/",
    auth=(WEBDAV_USERNAME, WEBDAV_PASSWORD),
    headers={"Depth": "1"},
)
print("Status:", r.status_code)
print("Body (first 300 chars):", r.text[:300])