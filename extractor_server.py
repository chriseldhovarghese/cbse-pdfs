import io
import re
import zipfile
import requests

from flask import Flask, request, jsonify
from urllib.parse import urlparse
from pypdf import PdfReader

app = Flask(__name__)

USER_AGENT = {"User-Agent": "Mozilla/5.0 (CBSE-Extractor/1.0)"}


def is_url(x):
    try:
        p = urlparse(x)
        return p.scheme in ("http", "https")
    except:
        return False


def download_bytes(url):
    r = requests.get(url, headers=USER_AGENT, timeout=50)
    r.raise_for_status()
    return r.content, r.headers.get("content-type", "")


def extract_pdf_from_zip(data):
    pdfs = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for m in z.infolist():
            if m.filename.lower().endswith(".pdf"):
                pdfs.append(z.read(m))
    return pdfs[0] if pdfs else None


def extract_text(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full = ""
    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            full += txt + "\n\n"
    return full.strip()


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def parse_metadata(text, filename):
    # subject from filename
    subject_match = re.search(r"_([A-Za-z]+)\.pdf$", filename)
    subject = subject_match.group(1).upper() if subject_match else "UNKNOWN"

    # QP code like 55_1_2 or 55/1/2
    qp_match = re.search(r"(\d{1,3})[_/](\d)[_/](\d)", filename)
    qp_code = None
    set_num = None

    if qp_match:
        qp_code = f"{qp_match.group(1)}/{qp_match.group(2)}/{qp_match.group(3)}"
        set_num = int(qp_match.group(3))

    # class detection
    class_match = re.search(r"Class\s+XII|12", text, re.I)
    class_val = "12" if class_match else "10"

    # year detection
    year_match = re.search(r"20\d\d", text)
    year_val = year_match.group(0) if year_match else None

    return {
        "subject": subject,
        "class": class_val,
        "year": int(year_val) if year_val else None,
        "exam_type": "MAIN",
        "qp_code": qp_code,
        "set": set_num
    }


def split_sections(text):
    sections = {}

    # Instructions before first SECTION
    inst_end = re.search(r"SECTION\s*[A-Z]", text)
    if inst_end:
        instructions = text[:inst_end.start()].strip()
    else:
        instructions = text[:1200]  # fallback

    sections["instructions"] = instructions

    # Split sections
    parts = re.split(r"(SECTION\s+[A-Z])", text)

    sec_map = {}
    current = None

    for p in parts:
        if p.strip().upper().startswith("SECTION"):
            current = p.strip()
            sec_map[current] = ""
        else:
            if current:
                sec_map[current] += p.strip() + "\n"

    for k, v in sec_map.items():
        sections[k.replace("SECTION ", "section_")] = v.strip()

    return sections


@app.route("/extract", methods=["POST"])
def extract():
    data = request.get_json(force=True)
    fileUrl = data.get("fileUrl")
    if not fileUrl:
        return jsonify({"error": "fileUrl is required"}), 400

    try:
        # Local file
        if not is_url(fileUrl):
            with open(fileUrl, "rb") as f:
                raw = f.read()
            filename = fileUrl

        # Remote file
        else:
            raw, ctype = download_bytes(fileUrl)
            filename = urlparse(fileUrl).path.split("/")[-1]

        # ZIP?
        if filename.lower().endswith(".zip") or "zip" in ctype.lower():
            pdf_bytes = extract_pdf_from_zip(raw)
            if pdf_bytes is None:
                return jsonify({"error": "No PDF found in ZIP"}), 400
        else:
            pdf_bytes = raw

        # Extract text from PDF
        text = extract_text(pdf_bytes)

        # Parse metadata
        meta = parse_metadata(text, filename)

        # Split sections
        sections = split_sections(text)

        out = {**meta, **sections}

        return jsonify(out)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
