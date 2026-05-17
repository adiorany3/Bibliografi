"""Utility functions for the Streamlit bibliography app.

The module intentionally avoids uncommon dependencies so the app is easier to
run on Streamlit Cloud. CSV/XLSX parsing uses pandas; BibTeX/RIS parsing is a
small pragmatic parser that handles common exports from Zotero, Mendeley,
Scopus, WoS, and Google Scholar.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

COLUMNS = [
    "title",
    "authors",
    "year",
    "journal",
    "publisher",
    "doi",
    "url",
    "abstract",
    "keywords",
    "database",
    "impact_factor",
    "notes",
    "indexing_status",
    "verification_reason",
]

IF_HINTS = {
    "nature": "nama jurnal/publisher termasuk kelompok jurnal flagship/high-impact",
    "science": "nama jurnal/publisher termasuk kelompok jurnal flagship/high-impact",
    "cell": "nama jurnal termasuk kelompok jurnal flagship/high-impact",
    "lancet": "nama jurnal termasuk kelompok jurnal medis bereputasi tinggi",
    "new england journal": "nama jurnal termasuk kelompok jurnal medis bereputasi tinggi",
    "nejm": "nama jurnal termasuk kelompok jurnal medis bereputasi tinggi",
    "jama": "nama jurnal termasuk kelompok jurnal medis bereputasi tinggi",
    "ieee transactions": "seri jurnal IEEE Transactions umumnya bereputasi dan banyak terindeks",
    "acm transactions": "seri jurnal ACM Transactions umumnya bereputasi dan banyak terindeks",
}

SCOPUS_HINTS = ["scopus", "elsevier", "source-id", "eid", "scopus source"]
WOS_HINTS = ["web of science", "wos", "clarivate", "science citation index", "ssci", "ahci", "esci", "ut "]
MAJOR_PUBLISHERS = ["elsevier", "springer", "wiley", "taylor", "sage", "emerald", "ieee", "acm", "mdpi", "frontiers"]


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def clean_title(title: object) -> str:
    return normalize_text(title).strip(" .:-\"'")


def parse_doi(text: object) -> str:
    text = normalize_text(text)
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, flags=re.I)
    return match.group(0).rstrip(".,;) ").lower() if match else ""


def first_present(item: Dict[str, object], keys: Iterable[str]) -> str:
    for key in keys:
        val = normalize_text(item.get(key, ""))
        if val:
            return val
    return ""


def first_raw(item: Dict[str, object], keys: Iterable[str]) -> object:
    for key in keys:
        val = item.get(key, "")
        if isinstance(val, list) and val:
            return val
        if normalize_text(val):
            return val
    return ""


def normalize_authors(authors: object) -> str:
    if isinstance(authors, list):
        return "; ".join(normalize_text(a) for a in authors if normalize_text(a))
    text = normalize_text(authors)
    text = re.sub(r"\s+and\s+", "; ", text, flags=re.I)
    text = text.replace("|", ";")
    return text


def normalize_year(value: object) -> str:
    text = normalize_text(value)
    match = re.search(r"(19|20)\d{2}", text)
    return match.group(0) if match else text


def classify_indexing(row: Dict[str, object]) -> Tuple[str, str]:
    source_text = " ".join(
        normalize_text(row.get(k, "")) for k in ["journal", "publisher", "database", "notes", "keywords", "url"]
    ).lower()
    tags: List[str] = []
    reasons: List[str] = []

    if any(h in source_text for h in SCOPUS_HINTS):
        tags.append("Scopus candidate")
        reasons.append("metadata mengandung indikator Scopus/Elsevier/EID")
    if any(h in source_text for h in WOS_HINTS):
        tags.append("Web of Science candidate")
        reasons.append("metadata mengandung indikator WoS/Clarivate/SCI/SSCI/AHCI/ESCI")

    for key, reason in IF_HINTS.items():
        if key in source_text:
            tags.append("High-impact candidate")
            reasons.append(reason)
            break

    if any(pub in source_text for pub in MAJOR_PUBLISHERS):
        reasons.append("publisher/jurnal berasal dari penerbit besar; tetap perlu verifikasi indeks resmi")

    impact_factor = normalize_text(row.get("impact_factor", "")).replace(",", ".")
    try:
        if impact_factor and float(impact_factor) >= 5:
            tags.append("High impact factor")
            reasons.append("impact factor/JIF/CiteScore ≥ 5 berdasarkan input pengguna")
    except ValueError:
        pass

    if not tags:
        tags.append("Needs verification")
        reasons.append("belum ada bukti indeks/impact factor pada metadata")

    return "; ".join(dict.fromkeys(tags)), "; ".join(dict.fromkeys(reasons))


def standardize_records(records: Iterable[Dict[str, object]] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(records, pd.DataFrame):
        records = records.to_dict("records")

    rows: List[Dict[str, str]] = []
    for item in records:
        if not isinstance(item, dict):
            continue

        title = clean_title(first_present(item, ["title", "article_title", "document_title", "judul", "dc:title"]))
        authors = normalize_authors(first_raw(item, ["authors", "author", "creators", "penulis", "dc:creator"]))
        year = normalize_year(first_present(item, ["year", "publication_year", "published_year", "cover_date", "date", "publication_date", "py"]))
        journal = first_present(item, ["journal", "source_title", "publication_name", "container_title", "source", "booktitle", "so", "source_titles"])
        publisher = first_present(item, ["publisher", "host_organization_name", "publisher_name"])
        doi = parse_doi(first_present(item, ["doi", "prism:doi", "di"])) or parse_doi(first_present(item, ["url", "link", "links"]))
        url = first_present(item, ["url", "link", "links", "record_url"])
        abstract = first_present(item, ["abstract", "description", "ab"])
        keywords = first_present(item, ["keywords", "author_keywords", "index_keywords", "keyword", "de"])
        database = first_present(item, ["database", "source_database", "index", "web_of_science_index"])
        impact_factor = first_present(item, ["impact_factor", "jif", "citescore", "sjr"])
        notes = first_present(item, ["notes", "eid", "ut", "accession_number", "document_type"])

        if not title and not doi:
            continue

        row = {
            "title": title,
            "authors": authors,
            "year": year,
            "journal": journal,
            "publisher": publisher,
            "doi": doi,
            "url": url,
            "abstract": abstract,
            "keywords": keywords,
            "database": database,
            "impact_factor": impact_factor,
            "notes": notes,
        }
        row["indexing_status"], row["verification_reason"] = classify_indexing(row)
        rows.append(row)

    df = pd.DataFrame(rows, columns=COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)

    # Safer deduplication: DOI first; title+journal+year fallback for empty DOI.
    df["_doi_key"] = df["doi"].fillna("").str.lower().str.strip()
    df["_title_key"] = (
        df["title"].fillna("").str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
        + "|" + df["journal"].fillna("").str.lower().str.strip()
        + "|" + df["year"].fillna("").astype(str).str.strip()
    )
    with_doi = df[df["_doi_key"] != ""].drop_duplicates("_doi_key", keep="first")
    no_doi = df[df["_doi_key"] == ""].drop_duplicates("_title_key", keep="first")
    out = pd.concat([with_doi, no_doi], ignore_index=True).drop(columns=["_doi_key", "_title_key"])
    return out[COLUMNS]


def search_crossref(query: str, rows: int = 20, mailto: str = "") -> pd.DataFrame:
    if not query.strip():
        return standardize_records([])
    headers = {"User-Agent": f"StreamlitBibliography/2.0 (mailto:{mailto or 'bibliography@example.com'})"}
    params = {"query.bibliographic": query, "rows": min(int(rows), 100), "sort": "relevance"}
    response = requests.get("https://api.crossref.org/works", params=params, headers=headers, timeout=25)
    response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])
    records: List[Dict[str, object]] = []
    for item in items:
        authors = []
        for a in item.get("author", []) or []:
            name = " ".join([normalize_text(a.get("given", "")), normalize_text(a.get("family", ""))]).strip()
            if name:
                authors.append(name)
        year = ""
        for key in ["published-print", "published-online", "published", "created"]:
            parts = item.get(key, {}).get("date-parts", []) if isinstance(item.get(key), dict) else []
            if parts and parts[0]:
                year = str(parts[0][0])
                break
        records.append({
            "title": (item.get("title") or [""])[0],
            "authors": authors,
            "year": year,
            "journal": (item.get("container-title") or [""])[0],
            "publisher": item.get("publisher", ""),
            "doi": item.get("DOI", ""),
            "url": item.get("URL", ""),
            "abstract": item.get("abstract", ""),
            "database": "Crossref",
            "notes": item.get("type", ""),
        })
    return standardize_records(records)


def search_openalex(query: str, rows: int = 20, mailto: str = "") -> pd.DataFrame:
    if not query.strip():
        return standardize_records([])
    params = {"search": query, "per-page": min(int(rows), 200)}
    if mailto:
        params["mailto"] = mailto
    response = requests.get("https://api.openalex.org/works", params=params, timeout=25)
    response.raise_for_status()
    items = response.json().get("results", [])
    records: List[Dict[str, object]] = []
    for item in items:
        authors = [a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])]
        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
        concepts = item.get("concepts") or []
        records.append({
            "title": item.get("title", ""),
            "authors": authors,
            "year": item.get("publication_year", ""),
            "journal": source.get("display_name", ""),
            "publisher": source.get("host_organization_name", ""),
            "doi": item.get("doi", ""),
            "url": item.get("id", ""),
            "abstract": "",
            "database": "OpenAlex",
            "keywords": "; ".join(c.get("display_name", "") for c in concepts[:5]),
            "notes": "openalex",
        })
    return standardize_records(records)


def search_scopus(query: str, api_key: str, rows: int = 20) -> pd.DataFrame:
    if not api_key or not query.strip():
        return standardize_records([])
    headers = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
    params = {"query": f"TITLE-ABS-KEY({query})", "count": min(int(rows), 25)}
    response = requests.get("https://api.elsevier.com/content/search/scopus", params=params, headers=headers, timeout=30)
    response.raise_for_status()
    entries = response.json().get("search-results", {}).get("entry", [])
    records: List[Dict[str, object]] = []
    for item in entries:
        records.append({
            "title": item.get("dc:title", ""),
            "authors": item.get("dc:creator", ""),
            "year": str(item.get("prism:coverDate", ""))[:4],
            "journal": item.get("prism:publicationName", ""),
            "publisher": "Elsevier/Scopus",
            "doi": item.get("prism:doi", ""),
            "url": item.get("prism:url", ""),
            "database": "Scopus",
            "notes": item.get("eid", ""),
        })
    return standardize_records(records)


def search_wos(query: str, api_key: str, rows: int = 20) -> pd.DataFrame:
    if not api_key or not query.strip():
        return standardize_records([])
    headers = {"X-ApiKey": api_key, "Accept": "application/json"}
    params = {"databaseId": "WOS", "usrQuery": f"TS=({query})", "count": min(int(rows), 100), "firstRecord": 1}
    response = requests.get("https://api.clarivate.com/apis/wos-starter/v1/documents", params=params, headers=headers, timeout=30)
    response.raise_for_status()
    items = response.json().get("hits", [])
    records: List[Dict[str, object]] = []
    for item in items:
        source = item.get("source", {}) or {}
        names = item.get("names", {}) or {}
        identifiers = item.get("identifiers", {}) or {}
        records.append({
            "title": item.get("title", ""),
            "authors": names.get("authors", []) if isinstance(names.get("authors", []), list) else "",
            "year": source.get("publishYear", ""),
            "journal": source.get("sourceTitle", ""),
            "publisher": "Clarivate/Web of Science",
            "doi": identifiers.get("doi", ""),
            "url": (item.get("links", {}) or {}).get("record", ""),
            "database": "Web of Science",
            "notes": item.get("uid", ""),
        })
    return standardize_records(records)


def _read_text_file(uploaded_file) -> str:
    data = uploaded_file.read()
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="ignore")


def parse_bibtex(text: str) -> pd.DataFrame:
    entries: List[Dict[str, str]] = []
    chunks = re.split(r"\n?@", text)
    for chunk in chunks:
        if not chunk.strip() or "{" not in chunk:
            continue
        body = chunk[chunk.find("{") + 1:]
        fields: Dict[str, str] = {"database": "BibTeX Upload"}
        for match in re.finditer(r"(?ims)\b(\w+)\s*=\s*[\{\"](.*?)[\}\"]\s*,", body + ","):
            key = match.group(1).lower().strip()
            val = normalize_text(match.group(2))
            fields[key] = val
        entries.append({
            "title": fields.get("title", ""),
            "authors": fields.get("author", ""),
            "year": fields.get("year", ""),
            "journal": fields.get("journal", fields.get("booktitle", "")),
            "publisher": fields.get("publisher", ""),
            "doi": fields.get("doi", ""),
            "url": fields.get("url", ""),
            "abstract": fields.get("abstract", ""),
            "keywords": fields.get("keywords", ""),
            "database": "BibTeX Upload",
        })
    return standardize_records(entries)


def parse_ris(text: str) -> pd.DataFrame:
    entries: List[Dict[str, object]] = []
    current: Dict[str, object] = {}
    authors: List[str] = []
    keywords: List[str] = []
    code_map = {"TI": "title", "T1": "title", "PY": "year", "Y1": "year", "JO": "journal", "JF": "journal", "T2": "journal", "DO": "doi", "UR": "url", "AB": "abstract", "PB": "publisher"}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        code = line[:2].strip().upper()
        value = line[6:].strip() if len(line) > 6 and line[2:6] == "  - " else line[3:].strip()
        if code == "TY":
            current = {"database": "RIS Upload"}
            authors = []
            keywords = []
        elif code == "AU":
            authors.append(value)
        elif code == "KW":
            keywords.append(value)
        elif code == "ER":
            current["authors"] = authors
            current["keywords"] = "; ".join(keywords)
            entries.append(current)
            current = {}
        elif code in code_map:
            current[code_map[code]] = value
    if current:
        current["authors"] = authors
        current["keywords"] = "; ".join(keywords)
        entries.append(current)
    return standardize_records(entries)


def parse_uploaded_file(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        try:
            df = pd.read_csv(uploaded_file)
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, encoding="latin-1")
    elif name.endswith(".xlsx"):
        df = pd.read_excel(uploaded_file, engine="openpyxl")
    elif name.endswith(".bib"):
        return parse_bibtex(_read_text_file(uploaded_file))
    elif name.endswith(".ris"):
        return parse_ris(_read_text_file(uploaded_file))
    else:
        raise ValueError("Format file belum didukung. Gunakan CSV, XLSX, BibTeX, atau RIS.")

    rename = {c: normalize_text(c).lower().replace(" ", "_").replace("-", "_").replace("/", "_") for c in df.columns}
    df = df.rename(columns=rename)
    mapping = {
        "article_title": "title",
        "document_title": "title",
        "source_title": "journal",
        "source_titles": "journal",
        "publication_name": "journal",
        "container_title": "journal",
        "author_keywords": "keywords",
        "index_keywords": "keywords",
        "web_of_science_index": "database",
        "publication_year": "year",
        "published_year": "year",
        "cover_date": "year",
        "link": "url",
        "links": "url",
        "eid": "notes",
        "accession_number": "notes",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    return standardize_records(df)


def dataframe_to_bibtex(df: pd.DataFrame) -> str:
    lines: List[str] = []
    for i, row in df.iterrows():
        first_author = str(row.get("authors", "Anon")).split(";")[0].split(",")[0]
        key = re.sub(r"[^A-Za-z0-9]+", "", first_author + str(row.get("year", ""))) or f"ref{i + 1}"
        lines.append(f"@article{{{key},")
        fields = {
            "title": row.get("title", ""),
            "author": str(row.get("authors", "")).replace(";", " and"),
            "year": row.get("year", ""),
            "journal": row.get("journal", ""),
            "doi": row.get("doi", ""),
            "url": row.get("url", ""),
            "publisher": row.get("publisher", ""),
        }
        for k, v in fields.items():
            val = normalize_text(v).replace("{", "").replace("}", "")
            if val:
                lines.append(f"  {k} = {{{val}}},")
        lines.append("}\n")
    return "\n".join(lines)


def dataframe_to_ris(df: pd.DataFrame) -> str:
    lines: List[str] = []
    for _, row in df.iterrows():
        lines.append("TY  - JOUR")
        for author in str(row.get("authors", "")).split(";"):
            author = normalize_text(author)
            if author:
                lines.append(f"AU  - {author}")
        mapping = [("TI", "title"), ("PY", "year"), ("JO", "journal"), ("DO", "doi"), ("UR", "url"), ("AB", "abstract")]
        for code, col in mapping:
            val = normalize_text(row.get(col, ""))
            if val:
                lines.append(f"{code}  - {val}")
        lines.append("ER  -")
        lines.append("")
    return "\n".join(lines)
