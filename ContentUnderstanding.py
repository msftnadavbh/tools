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
    """Poll operation URL until Succeeded, Failed, or Canceled.
    
    Returns the full response with 'result' key preserved for proper field access.
    """
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
            # Return full data structure - result is accessed via data["result"]
            return data
        if status in ("Failed", "Canceled"):
            raise RuntimeError(f"Analysis {status}: {json.dumps(data.get('error', data), indent=2)}")

        time.sleep(2)


def main():
    print(f"Analyzing with {ANALYZER_ID}...")
    token = get_token()
    op_url = start_analysis(token)

    print("Polling for results...")
    analysis_result = poll_until_done(op_url)

    # Save full results
    with open("cu_result.json", "w") as f:
        json.dump(analysis_result, f, indent=2)

    print(f"Done! Saved to cu_result.json")
    
    # Extract and display results with proper structure handling
    # The result structure is: analysis_result["result"]["contents"][n]["fields"]
    result = analysis_result.get("result", analysis_result)
    contents = result.get("contents", [])
    
    print(f"Extracted {len(contents)} content item(s)")
    
    if contents:
        first_content = contents[0]
        fields = first_content.get("fields", {})
        
        if fields:
            print(f"\n📊 Extracted {len(fields)} field(s):")
            print("-" * 60)
            for field_name, field_value in fields.items():
                field_type = field_value.get("type", "unknown")
                if field_type == "string":
                    print(f"  {field_name}: {field_value.get('valueString')}")
                elif field_type == "number":
                    print(f"  {field_name}: {field_value.get('valueNumber')}")
                elif field_type == "date":
                    print(f"  {field_name}: {field_value.get('valueDate')}")
                elif field_type == "array":
                    arr = field_value.get('valueArray', [])
                    print(f"  {field_name}: [{len(arr)} items]")
                elif field_type == "object":
                    print(f"  {field_name}: [object]")
                else:
                    print(f"  {field_name}: ({field_type})")
        else:
            print("\n⚠️  No fields extracted from document!")
            print("   This can happen if:")
            print("   - The document format doesn't match the analyzer type")
            print("   - The document quality is too low for extraction")
            print("   - The analyzer requires configuration (for custom analyzers)")
            print(f"\n   Content 'kind': {first_content.get('kind')}")
            print(f"   Pages: {first_content.get('startPageNumber')} - {first_content.get('endPageNumber')}")
            
            # Check if we have grounding/OCR content without fields
            if first_content.get("markdown") or first_content.get("text"):
                print("\n   ✓ Grounding content (OCR/text) IS present")
                print("   → The document was read, but field extraction failed")
            
            # Show what keys are present in the content for debugging
            print(f"\n   Available content keys: {list(first_content.keys())}")
    else:
        print("\n⚠️  No content items returned!")
        print("   Check if the document URL is accessible and the format is supported.")


if __name__ == "__main__":
    main()
