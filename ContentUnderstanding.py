"""
Azure Content Understanding - Invoice Analyzer

Extracts structured data from invoices using Azure AI Foundry's Content Understanding service.
Supports prebuilt analyzers (invoice, receipt, idDocument, etc.) or custom analyzers.

Usage:
    export AZURE_CU_ENDPOINT="https://<resource>.services.ai.azure.com"
    export DOCUMENT_URL="https://<storage>.blob.core.windows.net/..."
    python ContentUnderstanding.py
"""

import json
import os
import time
from datetime import datetime
import requests
from azure.identity import DefaultAzureCredential

# Configuration - set these environment variables before running
ENDPOINT = os.environ.get("AZURE_CU_ENDPOINT", "https://<your-resource>.services.ai.azure.com")

# Token cache to avoid repeated auth calls
_token_cache = {"token": None, "expires": 0}
ANALYZER_ID = os.environ.get("AZURE_CU_ANALYZER_ID", "prebuilt-invoice")
API_VERSION = "2025-11-01"
PDF_URL = os.environ.get("DOCUMENT_URL", "https://<your-storage>.blob.core.windows.net/container/document.pdf")
PAGE_RANGE = os.environ.get("PAGE_RANGE", "1-")  # Defaults to all pages


def get_token():
    """Get Azure AD token (cached for 50 minutes)."""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    
    credential = DefaultAzureCredential()
    token_response = credential.get_token("https://cognitiveservices.azure.com/.default")
    _token_cache["token"] = token_response.token
    _token_cache["expires"] = now + 3000  # Cache for ~50 minutes
    return token_response.token


def start_analysis(token: str) -> str:
    """Submit document for analysis. Returns operation URL for polling."""
    url = f"{ENDPOINT}/contentunderstanding/analyzers/{ANALYZER_ID}:analyze?api-version={API_VERSION}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"inputs": [{"url": PDF_URL, "range": PAGE_RANGE}]}

    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()

    # Track request for debugging/support
    request_id = resp.headers.get("x-ms-request-id") or resp.headers.get("apim-request-id")
    if request_id:
        print(f"Request ID: {request_id}")
        with open("requests.txt", "a") as f:
            f.write(f"{request_id}\n")

    # Long-running operation - result location returned in header
    op_url = resp.headers.get("Operation-Location")
    if not op_url:
        raise RuntimeError(f"Missing Operation-Location header: {resp.text}")
    return op_url


def poll_until_done(op_url: str) -> dict:
    """Poll operation URL until Succeeded, Failed, or Canceled."""
    start_time = time.time()
    while True:
        token = get_token()
        resp = requests.get(op_url, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status")  # Running, Succeeded, Failed, or Canceled
        elapsed = int(time.time() - start_time)
        print(f"Status: {status} ({elapsed}s elapsed)")

        if status == "Succeeded":
            return data.get("result", data)
        if status in ("Failed", "Canceled"):
            raise RuntimeError(f"Analysis {status}: {json.dumps(data.get('error', data), indent=2)}")

        time.sleep(2)


def main():
    print(f"Analyzing with {ANALYZER_ID}...")
    token = get_token()
    op_url = start_analysis(token)

    print("Polling for results...")
    result = poll_until_done(op_url)

    # Save results
    with open("cu_result.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Done! Saved to cu_result.json")
    print(f"Extracted {len(result.get('contents', []))} content item(s)")


if __name__ == "__main__":
    main()
