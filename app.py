from __future__ import annotations

import csv
import io
import json
import re
from typing import Dict, Iterable, List

import requests
import streamlit as st

APP_TITLE = "Sistem Bibliografi Riset"
COLUMNS = [
    "title", "authors", "year", "journal", "publisher", "doi", "url",
    "database", "impact_factor", "indexing_status", "verification_reason",
    "abstract", "keywords", "notes"
]

HIGH_IMPACT_HINTS = [
    "nature", "science", "cell", "lancet", "jama", "new england journal",
    "ieee transactions", "acm transactions", "review of educational research",
]
SCOPUS_HINTS = ["scopus", "elsevier", "eid", "source-id", "source id"]
WOS_HINTS = ["web of science", "wos", "clarivate", "sci-expanded", "ssci", "ahci", "esci", "ut "]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def first(row: Dict[str, object], keys: Iterable[str]) -> str:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        val = clean(lowered.get(key.lower(), ""))
        if val:
            return val
    return ""


def doi_from_text(text: str) -> str:
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", clean(text), re.I)
    return match.group(0).strip(".,;) ").lower() if match else ""


def year_from_text(text: str) -> str:
    match = re.search(r"(?:19|20)\d{2}", clean(text))
    return match.group(0) if match else clean(text)


def authors_to_text(authors: object) -> str:
    if isinstance(authors, list):
        return "; ".join(clean(a) for a in authors if clean(a))
    text = clean(authors)
    text = re.sub(r"\s+and\s+", "; ", text, flags=re.I)
    return text.replace("|", ";")


def classify(row: Dict[str, str]) -> tuple[str, str]:
    joined = " ".join(row.get(k, "") for k in ["journal", "publisher", "database", "notes", "url"]).lower()
    tags: List[str] = []
    reasons: List[str] = []
    if any(h in joined for h in SCOPUS_HINTS):
        tags.append("Scopus candidate")
        reasons.append("metadata mengandung indikator Scopus/Elsevier/EID")
    if any(h in joined for h in WOS_HINTS):
        tags.append("Web of Science candidate")
        reasons.append("metadata mengandung indikator WoS/Clarivate/SCI/SSCI/AHCI/ESCI")
    if any(h in joined for h in HIGH_IMPACT_HINTS):
        tags.append("High-impact candidate")
        reasons.append("nama jurnal/publisher terdeteksi sebagai kandidat jurnal bereputasi tinggi")
    impact = clean(row.get("impact_factor", "")).replace(",", ".")
    try:
        if impact and float(impact) >= 5:
            tags.append("High impact factor")
            reasons.append("impact factor/JIF/CiteScore input pengguna >= 5")
    except ValueError:
        pass
    if not tags:
        tags.append("Needs verification")
        reasons.append("belum ada bukti indeks/impact factor pada metadata")
    return "; ".join(dict.fromkeys(tags)), "; ".join(dict.fromkeys(reasons))


def standardize(records: Iterable[Dict[str, object]]) -> List[Dict[str, str]]:
    output: List[Dict[str, str]] = []
    seen = set()
    for raw in records:
        title = first(raw, ["title", "article title", "document title", "judul", "dc:title", "ti"])
        doi = doi_from_text(first(raw, ["doi", "prism:doi", "di", "url", "link"]))
        journal = first(raw, ["journal", "source title", "publication name", "container title", "source", "booktitle", "so"])
        row = {
            "title": title,
            "authors": authors_to_text(first(raw, ["authors", "author", "creators", "penulis", "dc:creator", "au"])),
            "year": year_from_text(first(raw, ["year", "publication year", "published year", "cover date", "date", "publication date", "py"])),
            "journal": journal,
            "publisher": first(raw, ["publisher", "publisher name", "host organization name"]),
            "doi": doi,
            "url": first(raw, ["url", "link", "links", "record url"]),
            "database": first(raw, ["database", "source database", "index", "web of science index"]),
            "impact_factor": first(raw, ["impact factor", "impact_factor", "jif", "citescore", "sjr"]),
            "abstract": first(raw, ["abstract", "description", "ab"]),
            "keywords": first(raw, ["keywords", "author keywords", "index keywords", "keyword", "de"]),
            "notes": first(raw, ["notes", "eid", "ut", "accession number", "document type"]),
        }
        if not row["title"] and not row["doi"]:
            continue
        row["indexing_status"], row["verification_reason"] = classify(row)
        key = row["doi"] or re.sub(r"\W+", " ", (row["title"] + row["journal"] + row["year"]).lower()).strip()
        if key and key not in seen:
            seen.add(key)
            output.append({col: row.get(col, "") for col in COLUMNS})
    return output


def parse_csv_bytes(data: bytes) -> List[Dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return standardize(list(reader))


def parse_bibtex(text: str) -> List[Dict[str, str]]:
    records = []
    entries = re.findall(r"@\w+\s*\{(.*?)(?=\n@|\Z)", text, flags=re.S)
    for entry in entries:
        fields = {}
        for match in re.finditer(r"(\w+)\s*=\s*([\{\"])(.*?)(?:\}|\")\s*,?", entry, flags=re.S):
            fields[match.group(1).lower()] = clean(match.group(3))
        if fields:
            records.append(fields)
    return standardize(records)


def parse_ris(text: str) -> List[Dict[str, str]]:
    keymap = {"TI": "title", "T1": "title", "AU": "authors", "PY": "year", "Y1": "year", "JO": "journal", "JF": "journal", "JA": "journal", "DO": "doi", "UR": "url", "AB": "abstract", "KW": "keywords"}
    records = []
    current: Dict[str, object] = {}
    for line in text.splitlines():
        if line.startswith("ER"):
            if current:
                records.append(current)
            current = {}
            continue
        m = re.match(r"([A-Z0-9]{2})\s*-\s*(.*)", line)
        if not m:
            continue
        field = keymap.get(m.group(1))
        if not field:
            continue
        value = clean(m.group(2))
        current[field] = clean(current.get(field, "")) + ("; " if current.get(field) else "") + value
    if current:
        records.append(current)
    return standardize(records)


def search_crossref(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    headers = {"User-Agent": f"BibliografiStreamlit/3.0 (mailto:{email or 'example@example.com'})"}
    params = {"query.bibliographic": query, "rows": min(rows, 100), "sort": "relevance"}
    r = requests.get("https://api.crossref.org/works", params=params, headers=headers, timeout=20)
    r.raise_for_status()
    records = []
    for item in r.json().get("message", {}).get("items", []):
        year = ""
        for date_key in ["published-print", "published-online", "published", "created"]:
            parts = item.get(date_key, {}).get("date-parts", []) if isinstance(item.get(date_key), dict) else []
            if parts and parts[0]:
                year = str(parts[0][0])
                break
        authors = []
        for a in item.get("author", []) or []:
            name = clean((a.get("given", "") + " " + a.get("family", "")).strip())
            if name:
                authors.append(name)
        records.append({
            "title": (item.get("title") or [""])[0],
            "authors": authors,
            "year": year,
            "journal": (item.get("container-title") or [""])[0],
            "publisher": item.get("publisher", ""),
            "doi": item.get("DOI", ""),
            "url": item.get("URL", ""),
            "database": "Crossref",
            "abstract": item.get("abstract", ""),
            "notes": item.get("type", ""),
        })
    return standardize(records)


def search_openalex(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    params = {"search": query, "per-page": min(rows, 200)}
    if email:
        params["mailto"] = email
    r = requests.get("https://api.openalex.org/works", params=params, timeout=20)
    r.raise_for_status()
    records = []
    for item in r.json().get("results", []):
        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
        authors = [a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])]
        records.append({
            "title": item.get("title", ""),
            "authors": authors,
            "year": item.get("publication_year", ""),
            "journal": source.get("display_name", ""),
            "publisher": source.get("host_organization_name", ""),
            "doi": item.get("doi", ""),
            "url": item.get("id", ""),
            "database": "OpenAlex",
            "keywords": "; ".join(c.get("display_name", "") for c in item.get("concepts", [])[:6]),
        })
    return standardize(records)


def to_csv(records: List[Dict[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(records)
    return buf.getvalue().encode("utf-8-sig")


def escape_bib(value: str) -> str:
    return clean(value).replace("{", "").replace("}", "")


def to_bibtex(records: List[Dict[str, str]]) -> str:
    chunks = []
    for i, r in enumerate(records, 1):
        key = re.sub(r"\W+", "", (r.get("authors", "ref").split(";")[0] + r.get("year", "") + str(i))) or f"ref{i}"
        chunks.append("@article{" + key + ",\n" + "\n".join([
            f"  title = {{{escape_bib(r.get('title',''))}}},",
            f"  author = {{{escape_bib(r.get('authors','').replace(';', ' and '))}}},",
            f"  year = {{{escape_bib(r.get('year',''))}}},",
            f"  journal = {{{escape_bib(r.get('journal',''))}}},",
            f"  publisher = {{{escape_bib(r.get('publisher',''))}}},",
            f"  doi = {{{escape_bib(r.get('doi',''))}}},",
            f"  url = {{{escape_bib(r.get('url',''))}}}",
        ]) + "\n}")
    return "\n\n".join(chunks)


def to_ris(records: List[Dict[str, str]]) -> str:
    lines = []
    for r in records:
        lines += ["TY  - JOUR", f"TI  - {r.get('title','')}"]
        for author in [a.strip() for a in r.get("authors", "").split(";") if a.strip()]:
            lines.append(f"AU  - {author}")
        lines += [f"PY  - {r.get('year','')}", f"JO  - {r.get('journal','')}", f"DO  - {r.get('doi','')}", f"UR  - {r.get('url','')}", "ER  - "]
    return "\n".join(lines)


def add_records(new_records: List[Dict[str, str]]) -> None:
    st.session_state.records = standardize(st.session_state.records + new_records)


st.set_page_config(page_title=APP_TITLE, page_icon="📚", layout="wide")
if "records" not in st.session_state:
    st.session_state.records = []

st.title("📚 Sistem Bibliografi Riset")
st.caption("Untuk mengelola bibliografi dari Crossref, OpenAlex, ekspor Scopus/WoS, dan kandidat jurnal high-impact. Validasi indeks resmi tetap dilakukan manual melalui Scopus/WoS/JCR/SJR.")

with st.sidebar:
    st.header("Pengaturan")
    email = st.text_input("Email opsional untuk API publik", placeholder="nama@email.com")
    rows = st.slider("Jumlah hasil per sumber", 5, 100, 20, 5)
    if st.button("Reset data", use_container_width=True):
        st.session_state.records = []
        st.success("Data dikosongkan.")

search_tab, upload_tab, manual_tab, data_tab, export_tab, guide_tab = st.tabs(["🔎 Cari", "⬆️ Upload", "✍️ Manual", "📊 Data", "📤 Ekspor", "🚀 Panduan"])

with search_tab:
    st.subheader("Cari metadata bibliografi")
    query = st.text_input("Topik/keyword riset", placeholder="Contoh: artificial intelligence education bibliometric")
    sources = st.multiselect("Sumber", ["Crossref", "OpenAlex"], default=["Crossref", "OpenAlex"])
    if st.button("Cari & gabungkan", type="primary", use_container_width=True):
        if not query.strip():
            st.warning("Keyword masih kosong.")
        else:
            found = []
            errors = []
            with st.spinner("Mengambil data bibliografi..."):
                if "Crossref" in sources:
                    try:
                        found += search_crossref(query, rows, email)
                    except Exception as e:
                        errors.append(f"Crossref: {e}")
                if "OpenAlex" in sources:
                    try:
                        found += search_openalex(query, rows, email)
                    except Exception as e:
                        errors.append(f"OpenAlex: {e}")
            add_records(found)
            st.success(f"Selesai. Total record unik: {len(st.session_state.records)}")
            if errors:
                st.error("Sebagian sumber gagal:\n" + "\n".join("- " + e for e in errors))

with upload_tab:
    st.subheader("Upload file bibliografi")
    st.write("Format stabil untuk Cloud: CSV, BibTeX `.bib`, dan RIS `.ris`. Untuk Scopus/WoS, ekspor sebagai CSV agar kolomnya terbaca.")
    uploaded = st.file_uploader("Pilih file", type=["csv", "bib", "ris", "txt"])
    if uploaded and st.button("Proses upload", type="primary", use_container_width=True):
        data = uploaded.getvalue()
        name = uploaded.name.lower()
        try:
            if name.endswith(".csv"):
                parsed = parse_csv_bytes(data)
            elif name.endswith(".ris"):
                parsed = parse_ris(data.decode("utf-8", errors="replace"))
            else:
                parsed = parse_bibtex(data.decode("utf-8", errors="replace"))
            add_records(parsed)
            st.success(f"Berhasil membaca {len(parsed)} record. Total unik: {len(st.session_state.records)}")
        except Exception as e:
            st.error(f"Gagal memproses file: {e}")

with manual_tab:
    st.subheader("Tambah referensi manual")
    with st.form("manual"):
        c1, c2 = st.columns(2)
        with c1:
            title = st.text_area("Judul")
            authors = st.text_input("Penulis", placeholder="Nama 1; Nama 2")
            year = st.text_input("Tahun")
            journal = st.text_input("Jurnal/Prosiding")
        with c2:
            publisher = st.text_input("Publisher")
            doi = st.text_input("DOI")
            url = st.text_input("URL")
            database = st.selectbox("Database", ["Manual", "Scopus", "Web of Science", "SINTA", "Google Scholar", "Lainnya"])
            impact = st.text_input("Impact Factor/JIF/CiteScore")
        abstract = st.text_area("Abstrak/catatan")
        submit = st.form_submit_button("Tambahkan")
    if submit:
        add_records(standardize([{"title": title, "authors": authors, "year": year, "journal": journal, "publisher": publisher, "doi": doi, "url": url, "database": database, "impact_factor": impact, "abstract": abstract}]))
        st.success("Data ditambahkan.")

with data_tab:
    st.subheader("Data bibliografi")
    records = st.session_state.records
    m1, m2, m3 = st.columns(3)
    m1.metric("Total", len(records))
    m2.metric("Dengan DOI", sum(1 for r in records if r.get("doi")))
    m3.metric("Scopus/WoS/High-impact", sum(1 for r in records if "candidate" in r.get("indexing_status", "").lower() or "impact" in r.get("indexing_status", "").lower()))
    keyword = st.text_input("Filter kata kunci")
    shown = records
    if keyword.strip():
        q = keyword.lower()
        shown = [r for r in records if q in json.dumps(r, ensure_ascii=False).lower()]
    st.dataframe(shown, use_container_width=True, height=460)

with export_tab:
    st.subheader("Ekspor")
    records = st.session_state.records
    if not records:
        st.info("Belum ada data untuk diekspor.")
    else:
        st.download_button("Download CSV", data=to_csv(records), file_name="bibliografi_riset.csv", mime="text/csv")
        st.download_button("Download BibTeX", data=to_bibtex(records).encode("utf-8"), file_name="bibliografi_riset.bib", mime="text/plain")
        st.download_button("Download RIS", data=to_ris(records).encode("utf-8"), file_name="bibliografi_riset.ris", mime="text/plain")
        st.download_button("Download JSON", data=json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"), file_name="bibliografi_riset.json", mime="application/json")

with guide_tab:
    st.subheader("Panduan deploy Streamlit Cloud")
    st.markdown("""
1. Upload semua file ke GitHub: `app.py`, `requirements.txt`, folder `.streamlit`, dan folder `data`.
2. Di Streamlit Community Cloud, pilih repo dan main file `app.py`.
3. Pada **Advanced settings**, pilih Python **3.12** atau **3.11**. Jangan gunakan Python 3.14 untuk aplikasi ini.
4. Klik Deploy/Reboot.

Catatan: file ini sengaja memakai dependency minimal (`streamlit` dan `requests`) supaya lebih aman di Streamlit Cloud.
""")
