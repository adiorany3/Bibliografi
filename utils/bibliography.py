import re
import time
from typing import Dict, List, Optional, Tuple

import bibtexparser
import pandas as pd
import requests
import rispy


IF_HINTS = {
    "nature": "High impact / flagship journal",
    "science": "High impact / flagship journal",
    "cell": "High impact / flagship journal",
    "lancet": "High impact / medical journal",
    "nejm": "High impact / medical journal",
    "new england journal": "High impact / medical journal",
    "jama": "High impact / medical journal",
    "ieee transactions": "Reputable indexed journal series",
    "acm transactions": "Reputable indexed journal series",
    "elsevier": "Major publisher journal",
    "springer": "Major publisher journal",
    "wiley": "Major publisher journal",
    "taylor & francis": "Major publisher journal",
    "sage": "Major publisher journal",
    "emerald": "Major publisher journal",
}

SCOPUS_HINTS = ["scopus", "elsevier", "source-id", "eid"]
WOS_HINTS = ["web of science", "wos", "clarivate", "ut"]


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_doi(text: str) -> Optional[str]:
    text = normalize_text(text)
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, flags=re.I)
    return match.group(0).rstrip(".,;) ") if match else None


def clean_title(title: str) -> str:
    title = normalize_text(title)
    return title.strip(" .:-")


def classify_indexing(row: Dict[str, object]) -> Tuple[str, str]:
    source_text = " ".join(normalize_text(row.get(k, "")) for k in [
        "source", "journal", "publisher", "database", "notes", "keywords"
    ]).lower()
    tags: List[str] = []
    reasons: List[str] = []

    if any(h in source_text for h in SCOPUS_HINTS):
        tags.append("Scopus")
        reasons.append("metadata mengandung indikator Scopus/Elsevier")
    if any(h in source_text for h in WOS_HINTS):
        tags.append("Web of Science")
        reasons.append("metadata mengandung indikator WoS/Clarivate")

    journal = normalize_text(row.get("journal", row.get("source", ""))).lower()
    for key, reason in IF_HINTS.items():
        if key in journal or key in source_text:
            tags.append("High-impact candidate")
            reasons.append(reason)
            break

    impact_factor = normalize_text(row.get("impact_factor", ""))
    try:
        if impact_factor and float(impact_factor.replace(",", ".")) >= 5:
            tags.append("High impact factor")
            reasons.append("impact factor ≥ 5 berdasarkan input pengguna")
    except ValueError:
        pass

    if not tags:
        tags.append("Needs verification")
        reasons.append("belum ada bukti indeks/impact factor pada metadata")

    # Remove duplicates while preserving order
    tags = list(dict.fromkeys(tags))
    reasons = list(dict.fromkeys(reasons))
    return "; ".join(tags), "; ".join(reasons)


def standardize_records(records: List[Dict[str, object]]) -> pd.DataFrame:
    rows = []
    for item in records:
        title = clean_title(item.get("title", ""))
        doi = parse_doi(item.get("doi", "")) or parse_doi(item.get("url", ""))
        authors = item.get("authors", "")
        if isinstance(authors, list):
            authors = "; ".join([normalize_text(a) for a in authors if normalize_text(a)])
        year = normalize_text(item.get("year", ""))
        journal = normalize_text(item.get("journal", item.get("source", "")))
        publisher = normalize_text(item.get("publisher", ""))
        url = normalize_text(item.get("url", ""))
        abstract = normalize_text(item.get("abstract", ""))
        keywords = normalize_text(item.get("keywords", ""))
        database = normalize_text(item.get("database", ""))
        impact_factor = normalize_text(item.get("impact_factor", ""))
        notes = normalize_text(item.get("notes", ""))

        row = {
            "title": title,
            "authors": normalize_text(authors),
            "year": year,
            "journal": journal,
            "publisher": publisher,
            "doi": doi or "",
            "url": url,
            "abstract": abstract,
            "keywords": keywords,
            "database": database,
            "impact_factor": impact_factor,
            "notes": notes,
        }
        row["indexing_status"], row["verification_reason"] = classify_indexing(row)
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[
            "title", "authors", "year", "journal", "publisher", "doi", "url",
            "abstract", "keywords", "database", "impact_factor", "notes",
            "indexing_status", "verification_reason"
        ])

    df = df.drop_duplicates(subset=["doi", "title"], keep="first")
    return df


def search_crossref(query: str, rows: int = 20, mailto: str = "") -> pd.DataFrame:
    if not query.strip():
        return standardize_records([])
    headers = {"User-Agent": f"StreamlitBibliography/1.0 (mailto:{mailto or 'example@example.com'})"}
    params = {"query.bibliographic": query, "rows": min(rows, 100), "sort": "relevance"}
    response = requests.get("https://api.crossref.org/works", params=params, headers=headers, timeout=20)
    response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])
    records = []
    for item in items:
        authors = []
        for a in item.get("author", []):
            name = " ".join([normalize_text(a.get("given", "")), normalize_text(a.get("family", ""))]).strip()
            if name:
                authors.append(name)
        year = ""
        for key in ["published-print", "published-online", "created"]:
            parts = item.get(key, {}).get("date-parts", [])
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
        })
    return standardize_records(records)


def search_openalex(query: str, rows: int = 20, mailto: str = "") -> pd.DataFrame:
    if not query.strip():
        return standardize_records([])
    params = {"search": query, "per-page": min(rows, 200)}
    if mailto:
        params["mailto"] = mailto
    response = requests.get("https://api.openalex.org/works", params=params, timeout=20)
    response.raise_for_status()
    items = response.json().get("results", [])
    records = []
    for item in items:
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in item.get("authorships", [])
        ]
        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
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
            "notes": ", ".join(item.get("concepts", [{}])[i].get("display_name", "") for i in range(min(3, len(item.get("concepts", [])))))
        })
    return standardize_records(records)


def search_scopus(query: str, api_key: str, rows: int = 20) -> pd.DataFrame:
    if not api_key or not query.strip():
        return standardize_records([])
    headers = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
    params = {"query": f"TITLE-ABS-KEY({query})", "count": min(rows, 25)}
    response = requests.get("https://api.elsevier.com/content/search/scopus", params=params, headers=headers, timeout=25)
    response.raise_for_status()
    entries = response.json().get("search-results", {}).get("entry", [])
    records = []
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
    params = {"databaseId": "WOS", "usrQuery": f"TS=({query})", "count": min(rows, 100), "firstRecord": 1}
    response = requests.get("https://api.clarivate.com/apis/wos-starter/v1/documents", params=params, headers=headers, timeout=25)
    response.raise_for_status()
    items = response.json().get("hits", [])
    records = []
    for item in items:
        source = item.get("source", {}) or {}
        names = item.get("names", {}) or {}
        records.append({
            "title": item.get("title", ""),
            "authors": "; ".join(names.get("authors", [])) if isinstance(names.get("authors", []), list) else "",
            "year": item.get("source", {}).get("publishYear", ""),
            "journal": source.get("sourceTitle", ""),
            "publisher": "Clarivate/Web of Science",
            "doi": item.get("identifiers", {}).get("doi", ""),
            "url": item.get("links", {}).get("record", ""),
            "database": "Web of Science",
            "notes": item.get("uid", ""),
        })
    return standardize_records(records)


def parse_uploaded_file(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    elif name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(uploaded_file)
    elif name.endswith(".bib"):
        text = uploaded_file.read().decode("utf-8", errors="ignore")
        db = bibtexparser.loads(text)
        records = []
        for e in db.entries:
            records.append({
                "title": e.get("title", ""),
                "authors": e.get("author", ""),
                "year": e.get("year", ""),
                "journal": e.get("journal", e.get("booktitle", "")),
                "publisher": e.get("publisher", ""),
                "doi": e.get("doi", ""),
                "url": e.get("url", ""),
                "abstract": e.get("abstract", ""),
                "keywords": e.get("keywords", ""),
                "database": "BibTeX Upload",
            })
        return standardize_records(records)
    elif name.endswith(".ris"):
        text = uploaded_file.read().decode("utf-8", errors="ignore")
        entries = rispy.loads(text)
        records = []
        for e in entries:
            records.append({
                "title": e.get("title", ""),
                "authors": e.get("authors", []),
                "year": e.get("year", ""),
                "journal": e.get("journal_name", e.get("secondary_title", "")),
                "doi": e.get("doi", ""),
                "url": e.get("url", ""),
                "abstract": e.get("abstract", ""),
                "keywords": "; ".join(e.get("keywords", [])) if isinstance(e.get("keywords", []), list) else e.get("keywords", ""),
                "database": "RIS Upload",
            })
        return standardize_records(records)
    else:
        raise ValueError("Format file belum didukung. Gunakan CSV, XLSX, BibTeX, atau RIS.")

    rename = {c: c.strip().lower().replace(" ", "_") for c in df.columns}
    df = df.rename(columns=rename)
    mapping = {
        "source_title": "journal",
        "publication_name": "journal",
        "container_title": "journal",
        "author": "authors",
        "creator": "authors",
        "publication_year": "year",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    return standardize_records(df.to_dict("records"))


def dataframe_to_bibtex(df: pd.DataFrame) -> str:
    lines = []
    for i, row in df.iterrows():
        key = re.sub(r"[^A-Za-z0-9]+", "", (str(row.get("authors", "Anon")).split(";")[0] + str(row.get("year", "")))) or f"ref{i+1}"
        lines.append(f"@article{{{key},")
        fields = {
            "title": row.get("title", ""),
            "author": row.get("authors", "").replace(";", " and"),
            "year": row.get("year", ""),
            "journal": row.get("journal", ""),
            "doi": row.get("doi", ""),
            "url": row.get("url", ""),
            "publisher": row.get("publisher", ""),
        }
        for k, v in fields.items():
            v = normalize_text(v)
            if v:
                lines.append(f"  {k} = {{{v}}},")
        lines.append("}\n")
    return "\n".join(lines)


def dataframe_to_ris(df: pd.DataFrame) -> str:
    lines = []
    for _, row in df.iterrows():
        lines.append("TY  - JOUR")
        for a in str(row.get("authors", "")).split(";"):
            a = normalize_text(a)
            if a:
                lines.append(f"AU  - {a}")
        mapping = [("TI", "title"), ("PY", "year"), ("JO", "journal"), ("DO", "doi"), ("UR", "url"), ("AB", "abstract")]
        for code, col in mapping:
            val = normalize_text(row.get(col, ""))
            if val:
                lines.append(f"{code}  - {val}")
        lines.append("ER  - \n")
    return "\n".join(lines)
