import streamlit as st
import pandas as pd
import time
import re
import os
from unstract.llmwhisperer import LLMWhispererClientV2


# =====================================================
# LOAD API KEY FROM ENV (Vercel Safe)
# =====================================================
LLMWHISPERER_API_KEY = os.getenv("LLMWHISPERER_API_KEY")

if not LLMWHISPERER_API_KEY:
    st.error("API Key not found. Please configure environment variable.")
    st.stop()


# =====================================================
# INITIALIZE LLM WHISPERER CLIENT
# =====================================================
@st.cache_resource
def load_client():
    return LLMWhispererClientV2(
        base_url="https://llmwhisperer-api.us-central.unstract.com/api/v2",
        api_key=LLMWHISPERER_API_KEY
    )


# =====================================================
# TABLE HEADER DETECTION
# =====================================================
def detect_header_index(lines):
    for i, line in enumerate(lines):
        if sum(k in line.lower() for k in
               ["description", "product", "item",
                "qty", "quantity",
                "unit", "price",
                "amount", "rate"]) >= 2:
            return i
    return None


# =====================================================
# TABLE PARSER
# =====================================================
def parse_table(lines):

    header_index = detect_header_index(lines)
    if header_index is None:
        return pd.DataFrame()

    header_line = lines[header_index]
    headers = re.split(r"\s{2,}", header_line.strip())
    headers = [h.strip() for h in headers if h.strip()]

    rows = []

    for i in range(header_index + 1, len(lines)):
        line = lines[i]
        lower = line.lower()

        if any(k in lower for k in ["subtotal", "total", "tax", "balance"]):
            break

        parts = re.split(r"\s{2,}", line.strip())
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) >= 2:
            rows.append(parts)

    if not rows:
        return pd.DataFrame()

    max_cols = max(len(r) for r in rows)
    rows = [r + [''] * (max_cols - len(r)) for r in rows]

    df = pd.DataFrame(rows)

    if len(headers) == df.shape[1]:
        df.columns = headers
    else:
        df.columns = headers + [f"Extra_{i}" for i in range(df.shape[1] - len(headers))]

    return df


# =====================================================
# METADATA EXTRACTION
# =====================================================
def extract_metadata_from_text(text):

    metadata = {}
    lines = [l.rstrip() for l in text.split("\n") if l.strip()]
    full_text = "\n".join(lines)

    currency_pattern = r"[$₹€£]?\s?\d+(?:,\d{3})*(?:\.\d+)?"
    date_pattern = (
        r"\b(?:"
        r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
        r"[A-Za-z]{3,9}\s\d{1,2},\s\d{4}|"
        r"\d{1,2}\s[A-Za-z]{3,9}\s\d{4}"
        r")\b"
    )
    invoice_id_pattern = r"\b[A-Z0-9\-\/]{4,}\b"

    def search_pattern(label_list, pattern):
        for label in label_list:
            regex = rf"{label}\s*:?\s*({pattern})"
            match = re.search(regex, full_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    metadata["invoice_number"] = search_pattern(
        ["invoice no", "invoice number", "invoice #"],
        invoice_id_pattern
    )

    metadata["date"] = search_pattern(["invoice date", "date"], date_pattern)
    metadata["due_date"] = search_pattern(["due date"], date_pattern)
    metadata["subtotal"] = search_pattern(["subtotal", "sub-total"], currency_pattern)

    tax_match = re.search(
        rf"(tax|vat|gst)[^\n]*?({currency_pattern})",
        full_text,
        re.IGNORECASE
    )
    if tax_match:
        metadata["tax"] = tax_match.group(2)

    total_candidates = re.findall(
        rf"\btotal\b\s*:?\s*({currency_pattern})",
        full_text,
        re.IGNORECASE
    )

    if total_candidates:
        numeric_values = []
        for val in total_candidates:
            clean_val = re.sub(r"[^\d.]", "", val)
            try:
                numeric_values.append((float(clean_val), val))
            except:
                pass

        if numeric_values:
            metadata["total_amount"] = max(numeric_values)[1]

    return {k: v for k, v in metadata.items() if v}


# =====================================================
# STREAMLIT UI
# =====================================================
st.title("📄 Invoice Extractor (Production Mode – Secure)")

uploaded_file = st.file_uploader("Upload Invoice", type=["pdf", "png", "jpg", "jpeg", "webp"])

if uploaded_file:

    with open("temp_file", "wb") as f:
        f.write(uploaded_file.read())

    client = load_client()

    st.info("Processing... ⏳")

    result = client.whisper(file_path="temp_file")

    while True:
        status = client.whisper_status(result["whisper_hash"])
        if status["status"] == "processed":
            resultx = client.whisper_retrieve(result["whisper_hash"])
            break
        time.sleep(2)

    extracted_text = resultx['extraction']['result_text']

    st.subheader("Raw Extracted Text")
    st.text(extracted_text)

    lines = [l.rstrip() for l in extracted_text.split("\n") if l.strip()]
    df = parse_table(lines)

    st.subheader("📊 Structured Table Output")
    if df.empty:
        st.warning("Table not detected properly")
    else:
        st.dataframe(df, use_container_width=True)

    metadata = extract_metadata_from_text(extracted_text)

    st.subheader("📌 Invoice Details")
    if metadata:
        for key, value in metadata.items():
            st.write(f"**{key.replace('_', ' ').title()}**: {value}")
    else:
        st.warning("Invoice details not detected.")