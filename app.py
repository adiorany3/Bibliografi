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


st.set_page_config(page_title=APP_TITLE, page_icon="📚", layout="wide", initial_sidebar_state="expanded")
if "records" not in st.session_state:
    st.session_state.records = []
if "sort_year" not in st.session_state:
    st.session_state.sort_year = "desc"

st.title("📚 Sistem Bibliografi Riset")
st.caption("Kelola bibliografi dari Crossref, OpenAlex, ekspor Scopus/WoS, dan identifikasi jurnal high-impact. Validasi indeks resmi tetap dilakukan manual di Scopus/WoS/JCR/SJR.")

with st.sidebar:
    st.header("⚙️ Pengaturan")
    email = st.text_input("Email opsional untuk API publik", placeholder="nama@email.com")
    rows = st.slider("Jumlah hasil per sumber", 5, 100, 20, 5)
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Baru", use_container_width=True):
            st.session_state.records = []
            st.success("Data dikosongkan.")
    with col2:
        if st.button("📥 Muat Sample", use_container_width=True):
            try:
                import os
                sample_path = os.path.join(os.path.dirname(__file__), "data", "sample_references.csv")
                if os.path.exists(sample_path):
                    with open(sample_path, 'rb') as f:
                        parsed = parse_csv_bytes(f.read())
                    add_records(parsed)
                    st.success(f"Dimuat {len(parsed)} referensi sampel.")
                else:
                    st.error("File sampel tidak ditemukan.")
            except Exception as e:
                st.error(f"Error: {e}")

search_tab, upload_tab, manual_tab, data_tab, insights_tab, export_tab, guide_tab = st.tabs(["🔎 Cari", "⬆️ Upload", "✍️ Manual", "📊 Data", "📈 Insight", "📤 Ekspor", "🚀 Panduan"])

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
    st.subheader("📋 Data Bibliografi")
    records = st.session_state.records
    
    if not records:
        st.info("Belum ada data. Gunakan tab Cari, Upload, atau Manual untuk menambah referensi.")
    else:
        # Metrics
        with_doi = sum(1 for r in records if r.get("doi"))
        high_impact = sum(1 for r in records if "candidate" in r.get("indexing_status", "").lower() or "impact" in r.get("indexing_status", "").lower())
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📚 Total", len(records))
        col2.metric("🔗 Dengan DOI", with_doi)
     insights_tab:
    st.subheader("📈 Analisis & Insight")
    records = st.session_state.records
    
    if not records:
        st.info("Belum ada data untuk dianalisis.")
    else:
        st.write(f"**Total referensi:** {len(records)}")
        st.divider()
        
        # Create columns for visualizations
        viz_col1, viz_col2 = st.columns(2)
        
        with viz_col1:
            st.write("### 📅 Distribusi Publikasi per Tahun")
            # Year distribution
            years = {}
            for r in records:
                year = r.get("year", "Unknown")
                if year and year != "Unknown":
                    years[year] = years.get(year, 0) + 1
            
            if years:
                years_sorted = dict(sorted(years.items(), key=lambda x: x[0]))
                st.bar_chart(years_sorted)
                st.caption(f"Tahun terbaru: {max(years.keys())}, Tahun terlama: {min(years.keys())}")
            else:
                st.info("Tidak ada data tahun.")
        
        with viz_col2:
            st.write("### 🗂️ Distribusi Database")
            # Database distribution
            databases = {}
            for r in records:
                db = r.get("database", "Manual")
                databases[db] = databases.get(db, 0) + 1
            
            if databases:
                st.bar_chart(databases)
            else:
                st.info("Tidak ada data database.")
        
        st.divider()
        
        # Status distribution
        col_status1, col_status2 = st.columns(2)
        
        with col_status1:
            st.write("### ✅ Status Verifikasi Indeks")
            status_data = {}
            for r in records:
                status = r.get("indexing_status", "Unknown")
                # Group by category
                if "Scopus" in status:
                    status_data["Scopus"] = status_data.get("Scopus", 0) + 1
                elif "Web of Science" in status:
                    status_data["WoS"] = status_data.get("WoS", 0) + 1
                elif "High-impact" in status:
                    status_data["High-Impact"] = status_data.get("High-Impact", 0) + 1
                elif "Needs verification" in status:
                    status_data["Perlu Verifikasi"] = status_data.get("Perlu Verifikasi", 0) + 1
            
            if status_data:
                st.bar_chart(status_data)
            else:
                st.info("Tidak ada data status.")
        
        with col_status2:
            st.write("### 📊 Statistik")
            with_doi = sum(1 for r in records if r.get("doi"))
            with_abstract = sum(1 for r in records if r.get("abstract"))
            with_keywords = sum(1 for r in records if r.get("keywords"))
            
            stats = {
                "Dengan DOI": with_doi,
                "Dengan Abstrak": with_abstract,
                "Dengan Keywords": with_keywords,
            }
            
            for label, count in stats.items():
                pct = (count / len(records) * 100) if records else 0
                st.metric(label, f"{count} ({pct:.1f}%)")
        
        st.divider()
        
        # Top authors and journals
        col_top1, col_top2 = st.columns(2)
        
        with col_top1:
            st.write("### 👥 Penulis Terbanyak")
            author_count = {}
            for r in records:
                authors = r.get("authors", "").split(";")
                for author in authors:
                    author = author.strip()
                    if author:
                        author_count[author] = author_count.get(author, 0) + 1
            
            if author_count:
                top_authors = sorted(author_count.items(), key=lambda x: x[1], reverse=True)[:10]
                author_dict = {k: v for k, v in top_authors}
                st.bar_chart(author_dict)
            else:
                st.info("Tidak ada data penulis.")
        
        with col_top2:
            st.write("### 📰 Jurnal Terbanyak")
            journal_count = {}
            for r in records:
                journal = r.get("journal", "").strip()
                if journal:
                    journal_count[journal[:40]] = journal_count.get(journal[:40], 0) + 1
            
            if journal_count:
                top_journals = sorted(journal_count.items(), key=lambda x: x[1], reverse=True)[:10]
                journal_dict = {k: v for k, v in top_journals}
                st.bar_chart(journal_dict)
            else:
                st.info("Tidak ada data jurnal.")
        
        st.divider()
        st.write("### 💡 Rekomendasi")
        recommendations = []
        
        doi_pct = (with_doi / len(records) * 100) if records else 0
        if doi_pct < 70:
            recommendations.append(f"⚠️ Hanya {doi_pct:.0f}% referensi memiliki DOI. Tambahkan DOI untuk kelengkapan metadata.")
        
        if sum(1 for r in records if "Needs verification" in r.get("indexing_status", "")) > len(records) * 0.5:
            recommendations.append("⚠️ Lebih dari 50% referensi belum terverifikasi indeksnya. Validasi manual di Scopus/WoS.")
        
        abstract_pct = (with_abstract / len(records) * 100) if records else 0
        if abstract_pct < 50:
            recommendations.append(f"💡 Lengkapi abstrak ({abstract_pct:.0f}%) untuk analisis lebih mendalam.")
        
        if recommendations:
            for rec in recommendations:
                st.info(rec)
        else:
            st.success("✅ Dataset Anda sudah bagus! Lanjutkan dengan validasi indeks resmi.")

with    col3.metric("⭐ High-Impact", high_impact)
        col4.metric("✅ Terverifikasi", sum(1 for r in records if r.get("indexing_status") and r.get("indexing_status") != "Needs verification"))
        
        st.divider()
        
        # Filters and sorting
        col_filter1, col_filter2, col_filter3 = st.columns([2, 1, 1])
        
        with col_filter1:
            keyword = st.text_input("🔍 Cari (judul, penulis, jurnal...)")
        
        with col_filter2:
            sort_option = st.selectbox("Urutkan", 
                ["Terbaru dulu", "Terlama dulu", "Judul A-Z", "Database"],
                key="sort_select")
        
        with col_filter3:
            status_filter = st.selectbox("Status", 
                ["Semua", "Verified", "Needs Verify"],
                key="status_filter")
        
        # Apply filters
        shown = records
        
        # Keyword filter
        if keyword.strip():
            q = keyword.lower()
            shown = [r for r in shown if q in json.dumps(r, ensure_ascii=False).lower()]
        
        # Status filter
        if status_filter == "Verified":
            shown = [r for r in shown if "candidate" in r.get("indexing_status", "").lower() or "impact" in r.get("indexing_status", "").lower()]
        elif status_filter == "Needs Verify":
            shown = [r for r in shown if r.get("indexing_status", "") == "Needs verification"]
        
        # Apply sorting
        if sort_option == "Terbaru dulu":
            shown = sorted(shown, key=lambda x: (x.get("year", "0") or "0"), reverse=True)
        elif sort_option == "Terlama dulu":
            shown = sorted(shown, key=lambda x: (x.get("year", "0") or "0"))
        elif sort_option == "Judul A-Z":
            shown = sorted(shown, key=lambda x: x.get("title", "").lower())
        elif sort_option == "Database":
            shown = sorted(shown, key=lambda x: x.get("database", ""))
        
        st.write(f"Menampilkan **{len(shown)} dari {len(records)}** referensi")
        
        # Display table with better formatting
        if shown:
            display_cols = ["title", "authors", "year", "journal", "database", "indexing_status"]
            display_records = []
            for r in shown:
                display_records.append({
                    "Judul": r.get("title", "")[:60] + ("..." if len(r.get("title", "")) > 60 else ""),
                    "Penulis": r.get("authors", "")[:40] + ("..." if len(r.get("authors", "")) > 40 else ""),
                    "Tahun": r.get("year", ""),
                    "Jurnal": r.get("journal", "")[:30] + ("..." if len(r.get("journal", "")) > 30 else ""),
                    "Database": r.get("database", ""),
                    "Status": r.get("indexing_status", "").split(";")[0] if r.get("indexing_status") else "—"
                })
            
            st.dataframe(display_records, use_container_width=True, height=500)
        
        # Detail view option
        st.divider()
        if st.checkbox("🔍 Lihat detail referensi"):
            col_detail1, col_detail2 = st.columns([1, 3])
            with col_detail1:
                idx = st.selectbox("Pilih referensi", range(len(shown)), format_func=lambda i: shown[i].get("title", f"Ref {i+1}")[:50])
            
            if idx is not None and idx < len(shown):
                record = shown[idx]
                with col_detail2:
                    st.write("### Detail Lengkap")
                    
                    detail_cols = st.columns(2)
                    with detail_cols[0]:
                        st.write(f"**Judul:** {record.get('title', '—')}")
                        st.write(f"**Penulis:** {record.get('authors', '—')}")
                        st.write(f"**Tahun:** {record.get('year', '—')}")
                        st.write(f"**Jurnal:** {record.get('journal', '—')}")
                    
                    with detail_cols[1]:
                        st.write(f"**Database:** {record.get('database', '—')}")
                        st.write(f"**DOI:** {record.get('doi', '—')}")
                        st.write(f"**Impact Factor:** {record.get('impact_factor', '—')}")
                        st.write(f"**Status:** {record.get('indexing_status', '—')}")
                    
                    if record.get("abstract"):
                        st.write("**Abstrak:**")
                        st.write(record.get("abstract"))
                    
                    if record.get("keywords"):
                        st.write("**Keywords:** " + record.get("keywords", ""))

with export_tab:
    st.subheader("📤 Ekspor Data")
    records = st.session_state.records
    
    if not records:
        st.info("Belum ada data untuk diekspor.")
    else:
        st.write(f"**Total referensi:** {len(records)}")
        
        # Filter option before export
        export_filter = st.radio("Ekspor:", ["Semua", "Hanya terverifikasi", "Hanya perlu verifikasi"], horizontal=True)
        
        export_records = records
        if export_filter == "Hanya terverifikasi":
            export_records = [r for r in records if "candidate" in r.get("indexing_status", "").lower() or "impact" in r.get("indexing_status", "").lower()]
            st.write(f"🔄 Diekspor: {len(export_records)} dari {len(records)}")
        elif export_filter == "Hanya perlu verifikasi":
            export_records = [r for r in records if r.get("indexing_status", "") == "Needs verification"]
            st.write(f"🔄 Diekspor: {len(export_records)} dari {len(records)}")
        
        st.divider()
        
        if export_records:
            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                st.download_button("📥 CSV", data=to_csv(export_records), file_name="bibliografi_riset.csv", mime="text/csv", use_container_width=True)
                st.download_button("📥 BibTeX", data=to_bibtex(export_records).encode("utf-8"), file_name="bibliografi_riset.bib", mime="text/plain", use_container_width=True)
            
            with col_exp2:
                st.download_button("📥 RIS", data=to_ris(export_records).encode("utf-8"), file_name="bibliografi_riset.ris", mime="text/plain", use_container_width=True)
                st.download_button("📥 JSON", data=json.dumps(export_records, ensure_ascii=False, indent=2).encode("utf-8"), file_name="bibliografi_riset.json", mime="application/json", use_container_width=True)
        else:
            st.warning("Tidak ada referensi sesuai filter untuk diekspor.")

with guide_tab:
    st.subheader("🚀 Panduan Penggunaan & Deploy")
    
    tab_usage, tab_deploy, tab_tips = st.tabs(["📖 Cara Pakai", "☁️ Deploy Cloud", "💡 Tips"])
    
    with tab_usage:
        st.write("""
### 1️⃣ Cari Referensi
- Gunakan **tab Cari** untuk mencari ke Crossref & OpenAlex
- Masukkan keyword topik penelitian
- Pilih sumber data yang diinginkan
- Sistem otomatis mendeduplikasi dan mengklasifikasi

### 2️⃣ Upload File
- Dukung format: **CSV, BibTeX (.bib), RIS (.ris)**
- CSV untuk ekspor dari Scopus/WoS (lebih stabil di Cloud)
- Sistem otomatis ekstrak metadata dan identifikasi DOI

### 3️⃣ Input Manual
- Tambah referensi satu per satu
- Isi minimal: Judul + tahun
- Pilih database asal (Manual, Scopus, WoS, SINTA, dll)

### 4️⃣ Analisis Data
- **Tab Data**: View & filter dengan sorting terbaru dulu
- **Tab Insight**: Dashboard dengan grafik distribusi, penulis terbanyak, rekomendasi
- Lihat detail lengkap setiap referensi

### 5️⃣ Ekspor
- Pilih format: CSV, BibTeX, RIS, JSON
- Pilih yang diekspor: Semua / Terverifikasi / Perlu verifikasi
        """)
    
    with tab_deploy:
        st.write("""
### Langkah Deploy ke Streamlit Cloud

**Persiapan:**
1. Upload semua file ke GitHub repo:
   - `app.py` (file utama)
   - `requirements.txt` 
   - `.streamlit/config.toml` (jika ada)
   - `data/sample_references.csv`

**Deploy:**
1. Masuk ke https://share.streamlit.io/
2. Klik "Create app"
3. Pilih repo, branch `main`, dan main file `app.py`
4. ⚠️ **PENTING**: Di Advanced settings, pilih Python **3.11** atau **3.12**
   - Jangan gunakan Python 3.14 untuk app ini
5. Klik Deploy/Reboot
6. Tunggu proses selesai (~3-5 menit)

**Troubleshooting:**
- Jika error, hapus deployment lama dan deploy ulang
- Pastikan `requirements.txt` dengan versi yang tepat
- Jangan gunakan Python terlalu baru
        """)
    
    with tab_tips:
        st.write("""
### 💡 Tips Optimal Penggunaan

**Untuk Pencarian:**
- Gunakan keyword spesifik: misal "machine learning education" bukan hanya "learning"
- Kombinasi database Crossref + OpenAlex untuk hasil lebih lengkap
- Set email di pengaturan untuk API rate limit lebih tinggi

**Untuk Upload:**
- CSV dari Scopus/WoS: **lebih aman** di Streamlit Cloud dibanding format lain
- Buat backup lokal sebelum upload
- File BibTeX dari Zotero/Mendeley biasanya bersih dan terbaca

**Untuk Analisis:**
- **Sortir Terbaru Dulu** untuk mengetahui publikasi terkini
- Lihat **Status Verifikasi** untuk mengidentifikasi publikasi yang sudah terbukti di indeks resmi
- Gunakan **Detail Viewer** untuk membaca abstrak lengkap

**Best Practice:**
- Tambahkan DOI sebanyak mungkin untuk data quality
- Validasi manual di Scopus/WoS untuk publikasi kritikal
- Gunakan keywords yang konsisten untuk searching
- Export berkala sebagai backup

### ❓ FAQ

**Q: Dapatkah saya upload ke Streamlit Cloud langsung dari app?**
A: Tidak, data hanya tersimpan di session. Upload file ke GitHub untuk persistence di Cloud.

**Q: Apakah ada limit jumlah referensi?**
A: Tidak ada limit teknis, tapi performa tergantung browser & koneksi internet.

**Q: Bagaimana cara backup data saya?**
A: Ekspor ke CSV/JSON setiap selesai session, atau upload file tersebut ke GitHub.
        """)
