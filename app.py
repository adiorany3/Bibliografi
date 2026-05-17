
from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
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
    "ieee transactions", "acm transactions", "acm computing surveys",
    "review of educational research", "springer nature", "elsevier",
    "wiley", "taylor & francis", "sage", "oxford university press",
    "cambridge university press", "mit press", "bmj", "plos biology",
    "annual reviews"
]

SCOPUS_HINTS = [
    "scopus", "elsevier", "eid", "source-id", "source id",
    "citescore", "sciencedirect"
]

WOS_HINTS = [
    "web of science", "wos", "clarivate", "sci-expanded", "ssci",
    "ahci", "esci", "journal citation reports", "jcr", "isi"
]

SOURCE_HELP = {
    "Crossref": "Metadata DOI lintas publisher akademik.",
    "OpenAlex": "Database open bibliographic besar untuk karya ilmiah.",
    "PubMed": "Literatur biomedis dari NCBI/NLM.",
    "Semantic Scholar": "Indeks AI2 untuk paper dan metadata akademik.",
    "DOAJ": "Directory of Open Access Journals.",
    "arXiv": "Preprint kredibel untuk CS, matematika, fisika, statistik, dan bidang terkait.",
    "Europe PMC": "Literatur biomedis dan life sciences.",
    "CORE": "Agregator open access repositories. Kadang membutuhkan API key/akses tertentu.",
}


# =========================
# Utility
# =========================
def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
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


def year_from_text(text: object) -> str:
    match = re.search(r"(?:19|20)\d{2}", clean(text))
    return match.group(0) if match else clean(text)


def authors_to_text(authors: object) -> str:
    if isinstance(authors, list):
        cleaned = []
        for a in authors:
            if isinstance(a, dict):
                name = a.get("name") or a.get("display_name") or a.get("full_name") or ""
                cleaned.append(clean(name))
            else:
                cleaned.append(clean(a))
        return "; ".join(a for a in cleaned if a)
    text = clean(authors)
    text = re.sub(r"\s+and\s+", "; ", text, flags=re.I)
    return text.replace("|", ";")


def classify(row: Dict[str, str]) -> tuple[str, str]:
    joined = " ".join(
        row.get(k, "") for k in ["journal", "publisher", "database", "notes", "url", "keywords"]
    ).lower()

    tags: List[str] = []
    reasons: List[str] = []

    if any(h in joined for h in SCOPUS_HINTS):
        tags.append("Scopus candidate")
        reasons.append("metadata mengandung indikator Scopus/Elsevier/EID/CiteScore")

    if any(h in joined for h in WOS_HINTS):
        tags.append("Web of Science candidate")
        reasons.append("metadata mengandung indikator WoS/Clarivate/JCR/SCI/SSCI/AHCI/ESCI")

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
        title = first(raw, ["title", "article title", "document title", "judul", "dc:title", "ti", "name"])
        doi = doi_from_text(first(raw, ["doi", "prism:doi", "di", "url", "link", "DOI", "externalids"]))
        journal = first(raw, [
            "journal", "source title", "publication name", "container title",
            "source", "booktitle", "so", "journal/book", "venue"
        ])

        row = {
            "title": title,
            "authors": authors_to_text(first(raw, [
                "authors", "author", "creators", "penulis", "dc:creator", "au", "authorstring"
            ])),
            "year": year_from_text(first(raw, [
                "year", "publication year", "published year", "cover date",
                "date", "publication date", "py", "published", "published_date"
            ])),
            "journal": journal,
            "publisher": first(raw, ["publisher", "publisher name", "host organization name"]),
            "doi": doi,
            "url": first(raw, ["url", "link", "links", "record url"]),
            "database": first(raw, ["database", "source database", "index", "web of science index"]),
            "impact_factor": first(raw, ["impact factor", "impact_factor", "jif", "citescore", "sjr"]),
            "abstract": first(raw, ["abstract", "description", "ab"]),
            "keywords": first(raw, ["keywords", "author keywords", "index keywords", "keyword", "de"]),
            "notes": first(raw, ["notes", "eid", "ut", "accession number", "document type", "type"]),
        }

        if not row["title"] and not row["doi"]:
            continue

        row["indexing_status"], row["verification_reason"] = classify(row)

        key = row["doi"] or re.sub(
            r"\W+", " ", (row["title"] + row["journal"] + row["year"]).lower()
        ).strip()

        if key and key not in seen:
            seen.add(key)
            output.append({col: row.get(col, "") for col in COLUMNS})

    return output


# =========================
# Parsers
# =========================
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
    keymap = {
        "TI": "title", "T1": "title", "AU": "authors", "A1": "authors",
        "PY": "year", "Y1": "year", "JO": "journal", "JF": "journal",
        "JA": "journal", "T2": "journal", "DO": "doi", "UR": "url",
        "AB": "abstract", "N2": "abstract", "KW": "keywords", "PB": "publisher"
    }
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
        old_value = clean(current.get(field, ""))
        current[field] = old_value + ("; " if old_value else "") + value

    if current:
        records.append(current)

    return standardize(records)


# =========================
# Credible metadata sources
# =========================
def search_crossref(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    headers = {
        "User-Agent": f"BibliografiStreamlit/6.0 (mailto:{email or 'example@example.com'})"
    }
    params = {"query.bibliographic": query, "rows": min(rows, 100), "sort": "relevance"}
    r = requests.get("https://api.crossref.org/works", params=params, headers=headers, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("message", {}).get("items", []):
        year = ""
        for date_key in ["published-print", "published-online", "published", "created"]:
            date_obj = item.get(date_key)
            parts = date_obj.get("date-parts", []) if isinstance(date_obj, dict) else []
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

    r = requests.get("https://api.openalex.org/works", params=params, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("results", []):
        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in item.get("authorships", [])
        ]

        doi = item.get("doi", "")
        doi = doi.replace("https://doi.org/", "") if isinstance(doi, str) else ""

        records.append({
            "title": item.get("title", ""),
            "authors": authors,
            "year": item.get("publication_year", ""),
            "journal": source.get("display_name", ""),
            "publisher": source.get("host_organization_name", ""),
            "doi": doi,
            "url": item.get("id", ""),
            "database": "OpenAlex",
            "keywords": "; ".join(c.get("display_name", "") for c in item.get("concepts", [])[:8]),
        })

    return standardize(records)


def search_pubmed(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": min(rows, 100),
        "retmode": "json",
        "sort": "relevance",
    }
    if email:
        params["email"] = email

    s = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params=params, timeout=25)
    s.raise_for_status()
    ids = s.json().get("esearchresult", {}).get("idlist", [])

    if not ids:
        return []

    summary_params = {
        "db": "pubmed",
        "id": ",".join(ids[: min(rows, 100)]),
        "retmode": "json",
    }
    if email:
        summary_params["email"] = email

    r = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", params=summary_params, timeout=25)
    r.raise_for_status()

    result = r.json().get("result", {})
    records = []

    for pmid in result.get("uids", []):
        item = result.get(pmid, {})
        authors = [a.get("name", "") for a in item.get("authors", [])]
        article_ids = item.get("articleids", [])
        doi = ""
        for aid in article_ids:
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
                break

        records.append({
            "title": item.get("title", ""),
            "authors": authors,
            "year": year_from_text(item.get("pubdate", "")),
            "journal": item.get("fulljournalname", "") or item.get("source", ""),
            "publisher": "NCBI/NLM",
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "database": "PubMed",
            "notes": item.get("pubtype", ""),
        })

    return standardize(records)


def search_semantic_scholar(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    params = {
        "query": query,
        "limit": min(rows, 100),
        "fields": "title,authors,year,venue,publicationVenue,externalIds,url,abstract,fieldsOfStudy,publicationTypes"
    }
    headers = {"User-Agent": "BibliografiStreamlit/6.0"}
    r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search", params=params, headers=headers, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("data", []):
        external = item.get("externalIds") or {}
        authors = [a.get("name", "") for a in item.get("authors", [])]
        pub_venue = item.get("publicationVenue") or {}

        records.append({
            "title": item.get("title", ""),
            "authors": authors,
            "year": item.get("year", ""),
            "journal": pub_venue.get("name", "") or item.get("venue", ""),
            "publisher": "Semantic Scholar / AI2",
            "doi": external.get("DOI", ""),
            "url": item.get("url", ""),
            "database": "Semantic Scholar",
            "abstract": item.get("abstract", ""),
            "keywords": "; ".join(item.get("fieldsOfStudy") or []),
            "notes": "; ".join(item.get("publicationTypes") or []),
        })

    return standardize(records)


def search_doaj(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    params = {"pageSize": min(rows, 100)}
    url = f"https://doaj.org/api/search/articles/{requests.utils.quote(query)}"
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("results", []):
        bib = item.get("bibjson", {})
        authors = [a.get("name", "") for a in bib.get("author", [])]
        journal = bib.get("journal", {}) or {}
        links = bib.get("link", []) or []
        url_value = ""
        for link in links:
            if isinstance(link, dict) and link.get("url"):
                url_value = link.get("url")
                break

        records.append({
            "title": bib.get("title", ""),
            "authors": authors,
            "year": bib.get("year", ""),
            "journal": journal.get("title", ""),
            "publisher": bib.get("publisher", "") or journal.get("publisher", ""),
            "doi": bib.get("identifier", [{}])[0].get("id", "") if bib.get("identifier") else "",
            "url": url_value,
            "database": "DOAJ",
            "abstract": bib.get("abstract", ""),
            "keywords": "; ".join(bib.get("keywords", []) or []),
            "notes": "Open Access Journal",
        })

    return standardize(records)


def search_arxiv(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": min(rows, 100),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    r = requests.get("https://export.arxiv.org/api/query", params=params, timeout=25)
    r.raise_for_status()

    root = ET.fromstring(r.content)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    records = []
    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", default="", namespaces=ns)
        published = entry.findtext("atom:published", default="", namespaces=ns)
        summary = entry.findtext("atom:summary", default="", namespaces=ns)
        arxiv_url = entry.findtext("atom:id", default="", namespaces=ns)
        journal_ref = entry.findtext("arxiv:journal_ref", default="", namespaces=ns)
        doi = entry.findtext("arxiv:doi", default="", namespaces=ns)

        authors = []
        for author in entry.findall("atom:author", ns):
            name = author.findtext("atom:name", default="", namespaces=ns)
            if name:
                authors.append(name)

        categories = [cat.attrib.get("term", "") for cat in entry.findall("atom:category", ns)]

        records.append({
            "title": clean(title),
            "authors": authors,
            "year": year_from_text(published),
            "journal": journal_ref or "arXiv",
            "publisher": "arXiv",
            "doi": doi,
            "url": arxiv_url,
            "database": "arXiv",
            "abstract": clean(summary),
            "keywords": "; ".join(categories),
            "notes": "Preprint",
        })

    return standardize(records)


def search_europe_pmc(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    params = {
        "query": query,
        "pageSize": min(rows, 100),
        "format": "json",
        "resultType": "core",
    }
    r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params=params, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("resultList", {}).get("result", []):
        records.append({
            "title": item.get("title", ""),
            "authors": item.get("authorString", ""),
            "year": item.get("pubYear", ""),
            "journal": item.get("journalTitle", ""),
            "publisher": "Europe PMC",
            "doi": item.get("doi", ""),
            "url": item.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url", "") if item.get("fullTextUrlList") else "",
            "database": "Europe PMC",
            "abstract": item.get("abstractText", ""),
            "keywords": item.get("meshHeadingList", ""),
            "notes": item.get("pubType", ""),
        })

    return standardize(records)


def search_core(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    """CORE can reject calls without API access. This function fails gracefully."""
    params = {"q": query, "limit": min(rows, 100)}
    r = requests.get("https://api.core.ac.uk/v3/search/works", params=params, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("results", []):
        authors = []
        for a in item.get("authors", []) or []:
            if isinstance(a, dict):
                authors.append(a.get("name", ""))
            else:
                authors.append(str(a))

        links = item.get("links") or []
        url_value = ""
        if links and isinstance(links[0], dict):
            url_value = links[0].get("url", "")

        journal = item.get("journal")
        if isinstance(journal, dict):
            journal = journal.get("title", "")

        records.append({
            "title": item.get("title", ""),
            "authors": authors,
            "year": year_from_text(item.get("publishedDate", "")),
            "journal": journal or "",
            "publisher": item.get("publisher", ""),
            "doi": item.get("doi", ""),
            "url": url_value,
            "database": "CORE",
            "abstract": item.get("abstract", ""),
            "keywords": "; ".join(item.get("topics", []) or []),
            "notes": "Open access repository",
        })

    return standardize(records)


SOURCE_FUNCTIONS = {
    "Crossref": search_crossref,
    "OpenAlex": search_openalex,
    "PubMed": search_pubmed,
    "Semantic Scholar": search_semantic_scholar,
    "DOAJ": search_doaj,
    "arXiv": search_arxiv,
    "Europe PMC": search_europe_pmc,
    "CORE": search_core,
}


# =========================
# Exporters
# =========================
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
        first_author = r.get("authors", "ref").split(";")[0]
        key = re.sub(r"\W+", "", first_author + r.get("year", "") + str(i)) or f"ref{i}"
        chunks.append(
            "@article{" + key + ",\n" + "\n".join([
                f"  title = {{{escape_bib(r.get('title', ''))}}},",
                f"  author = {{{escape_bib(r.get('authors', '').replace(';', ' and '))}}},",
                f"  year = {{{escape_bib(r.get('year', ''))}}},",
                f"  journal = {{{escape_bib(r.get('journal', ''))}}},",
                f"  publisher = {{{escape_bib(r.get('publisher', ''))}}},",
                f"  doi = {{{escape_bib(r.get('doi', ''))}}},",
                f"  url = {{{escape_bib(r.get('url', ''))}}}",
            ]) + "\n}"
        )
    return "\n\n".join(chunks)


def to_ris(records: List[Dict[str, str]]) -> str:
    lines = []
    for r in records:
        lines += ["TY  - JOUR", f"TI  - {r.get('title', '')}"]
        for author in [a.strip() for a in r.get("authors", "").split(";") if a.strip()]:
            lines.append(f"AU  - {author}")
        lines += [
            f"PY  - {r.get('year', '')}",
            f"JO  - {r.get('journal', '')}",
            f"DO  - {r.get('doi', '')}",
            f"UR  - {r.get('url', '')}",
            "ER  - "
        ]
    return "\n".join(lines)


def to_vosviewer_net(records: List[Dict[str, str]]) -> str:
    authors = {}
    edges = Counter()

    for r in records:
        author_list = [a.strip() for a in r.get("authors", "").split(";") if a.strip()]
        for a in author_list:
            if a not in authors:
                authors[a] = len(authors) + 1

        for i in range(len(author_list)):
            for j in range(i + 1, len(author_list)):
                pair = tuple(sorted([author_list[i], author_list[j]]))
                edges[pair] += 1

    lines = [f"*Vertices {len(authors)}"]
    for author, idx in authors.items():
        lines.append(f'{idx} "{author}" 1.0')

    lines.append("*Edges")
    for (a, b), weight in edges.items():
        lines.append(f"{authors[a]} {authors[b]} {weight}")

    return "\n".join(lines)


# =========================
# Analysis
# =========================
def add_records(new_records: List[Dict[str, str]]) -> None:
    st.session_state.records = standardize(st.session_state.records + new_records)


def filter_records(records: List[Dict[str, str]], keyword: str, status_filter: str, sort_option: str) -> List[Dict[str, str]]:
    shown = records

    if keyword.strip():
        q = keyword.lower()
        shown = [r for r in shown if q in json.dumps(r, ensure_ascii=False).lower()]

    if status_filter == "Terverifikasi/Kandidat":
        shown = [
            r for r in shown
            if "candidate" in r.get("indexing_status", "").lower()
            or "impact" in r.get("indexing_status", "").lower()
        ]
    elif status_filter == "Perlu Verifikasi":
        shown = [r for r in shown if r.get("indexing_status", "") == "Needs verification"]

    if sort_option == "Terbaru dulu":
        shown = sorted(shown, key=lambda x: x.get("year", "") or "0", reverse=True)
    elif sort_option == "Terlama dulu":
        shown = sorted(shown, key=lambda x: x.get("year", "") or "9999")
    elif sort_option == "Judul A-Z":
        shown = sorted(shown, key=lambda x: x.get("title", "").lower())
    elif sort_option == "Database":
        shown = sorted(shown, key=lambda x: x.get("database", ""))

    return shown


def get_basic_metrics(records: List[Dict[str, str]]) -> Dict[str, object]:
    total = len(records)
    with_doi = sum(1 for r in records if r.get("doi"))
    with_abstract = sum(1 for r in records if r.get("abstract"))
    with_keywords = sum(1 for r in records if r.get("keywords"))
    scopus = sum(1 for r in records if "Scopus" in r.get("indexing_status", ""))
    wos = sum(1 for r in records if "Web of Science" in r.get("indexing_status", ""))
    high = sum(1 for r in records if "High" in r.get("indexing_status", ""))
    need = sum(1 for r in records if r.get("indexing_status", "") == "Needs verification")

    authors = []
    multi_author = 0
    for r in records:
        names = [a.strip() for a in r.get("authors", "").split(";") if a.strip()]
        authors.extend(names)
        if len(names) > 1:
            multi_author += 1

    return {
        "total": total,
        "with_doi": with_doi,
        "with_abstract": with_abstract,
        "with_keywords": with_keywords,
        "scopus": scopus,
        "wos": wos,
        "high": high,
        "need": need,
        "authors_total": len(authors),
        "authors_unique": len(set(authors)),
        "collab_rate": (multi_author / total * 100) if total else 0,
        "avg_authors": (len(authors) / total) if total else 0,
    }


def count_by(records: List[Dict[str, str]], field: str, limit: int = 15) -> Dict[str, int]:
    counter = Counter()
    for r in records:
        val = clean(r.get(field, "")) or "Unknown"
        if field == "journal" and len(val) > 45:
            val = val[:45] + "..."
        counter[val] += 1
    return dict(counter.most_common(limit))


def year_distribution(records: List[Dict[str, str]]) -> Dict[str, int]:
    years = Counter()
    for r in records:
        year = r.get("year", "")
        if year and year.isdigit():
            years[year] += 1
    return dict(sorted(years.items()))


def author_distribution(records: List[Dict[str, str]], limit: int = 15) -> Dict[str, int]:
    counter = Counter()
    for r in records:
        for a in [x.strip() for x in r.get("authors", "").split(";") if x.strip()]:
            counter[a] += 1
    return dict(counter.most_common(limit))


def keyword_distribution(records: List[Dict[str, str]], limit: int = 20) -> Dict[str, int]:
    counter = Counter()
    for r in records:
        parts = re.split(r";|,", r.get("keywords", ""))
        for kw in [clean(x).lower() for x in parts if clean(x)]:
            counter[kw] += 1
    return dict(counter.most_common(limit))


def coauthorship_summary(records: List[Dict[str, str]]) -> Dict[str, object]:
    author_papers = Counter()
    edges = Counter()

    for r in records:
        authors = [a.strip() for a in r.get("authors", "").split(";") if a.strip()]
        for a in authors:
            author_papers[a] += 1
        for i in range(len(authors)):
            for j in range(i + 1, len(authors)):
                edges[tuple(sorted([authors[i], authors[j]]))] += 1

    possible_edges = len(author_papers) * (len(author_papers) - 1) / 2
    density = (len(edges) / possible_edges) if possible_edges else 0

    return {
        "num_authors": len(author_papers),
        "num_collaborations": len(edges),
        "density": density,
        "top_authors": author_papers.most_common(10),
        "top_edges": edges.most_common(10),
    }


def build_report(records: List[Dict[str, str]]) -> str:
    m = get_basic_metrics(records)
    years = year_distribution(records)
    top_authors = author_distribution(records, 10)
    top_journals = count_by(records, "journal", 10)
    top_keywords = keyword_distribution(records, 10)
    top_db = count_by(records, "database", 20)

    period = "N/A"
    if years:
        period = f"{min(years.keys())} - {max(years.keys())}"

    return f"""LAPORAN ANALISIS BIBLIOMETRIK

Ringkasan:
- Total dokumen: {m['total']}
- Periode publikasi: {period}
- DOI tersedia: {m['with_doi']}
- Abstrak tersedia: {m['with_abstract']}
- Keywords tersedia: {m['with_keywords']}

Sumber data:
{chr(10).join([f"- {k}: {v}" for k, v in top_db.items()]) or "-"}

Kualitas dan indeksasi:
- Kandidat Scopus: {m['scopus']}
- Kandidat Web of Science: {m['wos']}
- Kandidat high impact: {m['high']}
- Perlu verifikasi: {m['need']}

Kolaborasi:
- Total penulis: {m['authors_total']}
- Penulis unik: {m['authors_unique']}
- Rata-rata penulis per dokumen: {m['avg_authors']:.2f}
- Persentase dokumen kolaboratif: {m['collab_rate']:.1f}%

Top penulis:
{chr(10).join([f"- {k}: {v}" for k, v in top_authors.items()]) or "-"}

Top jurnal:
{chr(10).join([f"- {k}: {v}" for k, v in top_journals.items()]) or "-"}

Top keyword:
{chr(10).join([f"- {k}: {v}" for k, v in top_keywords.items()]) or "-"}

Catatan:
Status Scopus/WoS/high impact pada aplikasi ini bersifat kandidat berbasis metadata.
Validasi akhir tetap perlu dilakukan manual melalui Scopus, Web of Science, JCR, SJR, atau laman resmi jurnal.
"""


# =========================
# Streamlit UI
# =========================
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "records" not in st.session_state:
    st.session_state.records = []

st.title("📚 Sistem Bibliografi Riset")
st.caption(
    "Kelola bibliografi dari banyak sumber kredibel: Crossref, OpenAlex, PubMed, Semantic Scholar, DOAJ, arXiv, Europe PMC, CORE, dan file ekspor Scopus/WoS."
)

with st.sidebar:
    st.header("⚙️ Pengaturan")
    email = st.text_input("Email opsional untuk API publik", placeholder="nama@email.com")
    rows = st.slider("Jumlah hasil per sumber", 5, 100, 20, 5)

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 Baru", use_container_width=True):
            st.session_state.records = []
            st.success("Data dikosongkan.")

    with col_b:
        if st.button("📥 Sample", use_container_width=True):
            try:
                from pathlib import Path
                sample_path = Path(__file__).parent / "data" / "sample_references.csv"
                with sample_path.open("rb") as f:
                    parsed = parse_csv_bytes(f.read())
                add_records(parsed)
                st.success(f"Dimuat {len(parsed)} referensi.")
            except Exception as exc:
                st.error(f"Sample gagal dimuat: {exc}")

search_tab, upload_tab, manual_tab, data_tab, insights_tab, export_tab, source_tab, guide_tab = st.tabs([
    "🔎 Cari", "⬆️ Upload", "✍️ Manual", "📊 Data", "📈 Insight", "📤 Ekspor", "🌐 Sumber", "🚀 Panduan"
])

with search_tab:
    st.subheader("🔎 Cari Metadata Bibliografi dari Banyak Sumber")
    query = st.text_input("Topik/keyword riset", placeholder="Contoh: artificial intelligence education bibliometric")

    default_sources = ["Crossref", "OpenAlex", "PubMed", "Semantic Scholar", "DOAJ", "arXiv", "Europe PMC"]
    sources = st.multiselect(
        "Pilih sumber kredibel",
        list(SOURCE_FUNCTIONS.keys()),
        default=default_sources,
        help="Semakin banyak sumber dipilih, hasil makin banyak tetapi proses lebih lama."
    )

    with st.expander("Keterangan sumber"):
        for src, desc in SOURCE_HELP.items():
            st.write(f"**{src}:** {desc}")

    if st.button("Cari & gabungkan semua sumber", type="primary", use_container_width=True):
        if not query.strip():
            st.warning("Keyword masih kosong.")
        elif not sources:
            st.warning("Pilih minimal satu sumber.")
        else:
            found = []
            errors = []

            progress = st.progress(0)
            status_box = st.empty()

            for i, source in enumerate(sources, start=1):
                status_box.info(f"Mengambil data dari {source}...")
                try:
                    results = SOURCE_FUNCTIONS[source](query, rows, email)
                    found += results
                    st.write(f"✅ {source}: {len(results)} record")
                except Exception as exc:
                    errors.append(f"{source}: {exc}")
                    st.write(f"⚠️ {source}: gagal/terbatas")
                progress.progress(i / len(sources))

            add_records(found)
            status_box.success(f"Selesai. Data baru terbaca: {len(found)}. Total record unik: {len(st.session_state.records)}")

            if errors:
                with st.expander("Detail sumber yang gagal"):
                    for e in errors:
                        st.write(f"- {e}")

with upload_tab:
    st.subheader("⬆️ Upload File Bibliografi")
    st.write("Format yang didukung: CSV, BibTeX `.bib`, RIS `.ris`, dan `.txt` berisi BibTeX/RIS.")
    st.info("Untuk Scopus, Web of Science, Dimensions, Lens, Zotero, atau Mendeley, ekspor sebagai CSV/BibTeX/RIS.")

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
        except Exception as exc:
            st.error(f"Gagal memproses file: {exc}")

with manual_tab:
    st.subheader("✍️ Tambah Referensi Manual")

    with st.form("manual_reference_form"):
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
            database = st.selectbox(
                "Database",
                ["Manual", "Scopus", "Web of Science", "SINTA", "Google Scholar", "Crossref", "OpenAlex", "PubMed", "Semantic Scholar", "DOAJ", "arXiv", "Europe PMC", "CORE", "Lainnya"]
            )
            impact = st.text_input("Impact Factor/JIF/CiteScore")

        abstract = st.text_area("Abstrak/catatan")
        keywords = st.text_input("Keywords", placeholder="keyword 1; keyword 2")
        submit_manual = st.form_submit_button("Tambahkan", type="primary")

    if submit_manual:
        new_item = {
            "title": title,
            "authors": authors,
            "year": year,
            "journal": journal,
            "publisher": publisher,
            "doi": doi,
            "url": url,
            "database": database,
            "impact_factor": impact,
            "abstract": abstract,
            "keywords": keywords,
        }
        add_records(standardize([new_item]))
        st.success("Data ditambahkan.")

with data_tab:
    st.subheader("📊 Data Bibliografi")
    records = st.session_state.records

    if not records:
        st.info("Belum ada data. Gunakan tab Cari, Upload, atau Manual.")
    else:
        metrics = get_basic_metrics(records)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📚 Total", metrics["total"])
        col2.metric("🔗 Dengan DOI", metrics["with_doi"])
        col3.metric("⭐ Kandidat High Impact", metrics["high"])
        col4.metric("✅ Kandidat Terindeks", metrics["scopus"] + metrics["wos"])

        st.divider()

        f1, f2, f3 = st.columns([2, 1, 1])
        with f1:
            keyword = st.text_input("🔍 Cari judul, penulis, jurnal, DOI, keyword")
        with f2:
            sort_option = st.selectbox("Urutkan", ["Terbaru dulu", "Terlama dulu", "Judul A-Z", "Database"])
        with f3:
            status_filter = st.selectbox("Status", ["Semua", "Terverifikasi/Kandidat", "Perlu Verifikasi"])

        shown = filter_records(records, keyword, status_filter, sort_option)
        st.write(f"Menampilkan **{len(shown)} dari {len(records)}** referensi")

        display_records = []
        for r in shown:
            display_records.append({
                "Judul": r.get("title", "")[:70] + ("..." if len(r.get("title", "")) > 70 else ""),
                "Penulis": r.get("authors", "")[:45] + ("..." if len(r.get("authors", "")) > 45 else ""),
                "Tahun": r.get("year", ""),
                "Jurnal": r.get("journal", "")[:40] + ("..." if len(r.get("journal", "")) > 40 else ""),
                "Database": r.get("database", ""),
                "Status": r.get("indexing_status", "").split(";")[0] if r.get("indexing_status") else "—",
            })

        st.dataframe(display_records, use_container_width=True, height=480)

        st.divider()

        if st.checkbox("🔍 Lihat detail referensi"):
            if shown:
                idx = st.selectbox(
                    "Pilih referensi",
                    range(len(shown)),
                    format_func=lambda i: shown[i].get("title", f"Referensi {i + 1}")[:80]
                )

                record = shown[idx]
                left, right = st.columns(2)

                with left:
                    st.write(f"**Judul:** {record.get('title', '—')}")
                    st.write(f"**Penulis:** {record.get('authors', '—')}")
                    st.write(f"**Tahun:** {record.get('year', '—')}")
                    st.write(f"**Jurnal:** {record.get('journal', '—')}")
                    st.write(f"**Publisher:** {record.get('publisher', '—')}")

                with right:
                    st.write(f"**Database:** {record.get('database', '—')}")
                    st.write(f"**DOI:** {record.get('doi', '—')}")
                    st.write(f"**URL:** {record.get('url', '—')}")
                    st.write(f"**Impact Factor/CiteScore:** {record.get('impact_factor', '—')}")
                    st.write(f"**Status:** {record.get('indexing_status', '—')}")
                    st.write(f"**Alasan:** {record.get('verification_reason', '—')}")

                if record.get("abstract"):
                    st.write("**Abstrak:**")
                    st.write(record.get("abstract"))

                if record.get("keywords"):
                    st.write("**Keywords:**")
                    st.write(record.get("keywords"))
            else:
                st.warning("Tidak ada referensi sesuai filter.")

with insights_tab:
    st.subheader("📈 Analisis & Insight")
    records = st.session_state.records

    if not records:
        st.info("Belum ada data untuk dianalisis.")
    else:
        metrics = get_basic_metrics(records)

        st.write("### Ringkasan Bibliometrik")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total dokumen", metrics["total"])
        c2.metric("Penulis unik", metrics["authors_unique"])
        c3.metric("Rata-rata penulis/doc", f"{metrics['avg_authors']:.2f}")
        c4.metric("Kolaborasi", f"{metrics['collab_rate']:.1f}%")

        st.divider()

        meta1, meta2, meta3, meta4 = st.columns(4)
        doi_pct = (metrics["with_doi"] / metrics["total"] * 100) if metrics["total"] else 0
        abs_pct = (metrics["with_abstract"] / metrics["total"] * 100) if metrics["total"] else 0
        kw_pct = (metrics["with_keywords"] / metrics["total"] * 100) if metrics["total"] else 0

        meta1.metric("DOI", f"{metrics['with_doi']} ({doi_pct:.0f}%)")
        meta2.metric("Abstrak", f"{metrics['with_abstract']} ({abs_pct:.0f}%)")
        meta3.metric("Keywords", f"{metrics['with_keywords']} ({kw_pct:.0f}%)")
        meta4.metric("Perlu verifikasi", metrics["need"])

        st.divider()

        left, right = st.columns(2)

        with left:
            st.write("### Distribusi Publikasi per Tahun")
            years = year_distribution(records)
            if years:
                st.bar_chart(years)
            else:
                st.info("Tidak ada data tahun.")

        with right:
            st.write("### Distribusi Database")
            dbs = count_by(records, "database", 20)
            if dbs:
                st.bar_chart(dbs)
            else:
                st.info("Tidak ada data database.")

        st.divider()

        left2, right2 = st.columns(2)

        with left2:
            st.write("### Penulis Terbanyak")
            authors = author_distribution(records, 15)
            if authors:
                st.bar_chart(authors)
            else:
                st.info("Tidak ada data penulis.")

        with right2:
            st.write("### Jurnal Terbanyak")
            journals = count_by(records, "journal", 15)
            if journals:
                st.bar_chart(journals)
            else:
                st.info("Tidak ada data jurnal.")

        st.divider()

        left3, right3 = st.columns(2)

        with left3:
            st.write("### Keyword Terbanyak")
            keywords = keyword_distribution(records, 20)
            if keywords:
                st.bar_chart(keywords)
            else:
                st.info("Tidak ada data keyword.")

        with right3:
            st.write("### Status Indeksasi")
            status_data = {
                "Scopus candidate": metrics["scopus"],
                "WoS candidate": metrics["wos"],
                "High impact": metrics["high"],
                "Needs verification": metrics["need"],
            }
            st.bar_chart(status_data)

        st.divider()

        st.write("### Jaringan Kolaborasi Penulis")
        coauth = coauthorship_summary(records)
        n1, n2, n3 = st.columns(3)
        n1.metric("Total penulis", coauth["num_authors"])
        n2.metric("Relasi kolaborasi", coauth["num_collaborations"])
        n3.metric("Network density", f"{coauth['density']:.3f}")

        ctop1, ctop2 = st.columns(2)

        with ctop1:
            st.write("**Penulis paling produktif:**")
            if coauth["top_authors"]:
                for author, count in coauth["top_authors"]:
                    st.write(f"- {author}: {count} publikasi")
            else:
                st.info("Belum ada data penulis.")

        with ctop2:
            st.write("**Kolaborasi terkuat:**")
            if coauth["top_edges"]:
                for (a, b), count in coauth["top_edges"]:
                    st.write(f"- {a} ↔ {b}: {count} kali")
            else:
                st.info("Belum ada pasangan kolaborasi.")

        st.divider()

        st.write("### Rekomendasi")
        recommendations = []

        if doi_pct < 70:
            recommendations.append(f"⚠️ DOI coverage masih {doi_pct:.0f}%. Tambahkan DOI agar metadata lebih kuat.")
        if abs_pct < 50:
            recommendations.append(f"💡 Abstrak baru {abs_pct:.0f}%. Lengkapi abstrak untuk analisis isi yang lebih baik.")
        if metrics["need"] > metrics["total"] * 0.5:
            recommendations.append("⚠️ Lebih dari 50% referensi perlu verifikasi indeks. Cek manual di Scopus/WoS/JCR/SJR.")
        if metrics["collab_rate"] < 30:
            recommendations.append("💡 Tingkat kolaborasi relatif rendah. Pertimbangkan literatur multi-author untuk pemetaan jaringan.")
        if not recommendations:
            recommendations.append("✅ Dataset sudah cukup baik. Lanjutkan validasi indeks resmi dan ekspor data.")

        for rec in recommendations:
            st.info(rec)

        st.divider()

        report_text = build_report(records)
        st.download_button(
            "📥 Download Laporan TXT",
            data=report_text.encode("utf-8"),
            file_name="laporan_bibliometrik.txt",
            mime="text/plain",
            use_container_width=True,
        )

with export_tab:
    st.subheader("📤 Ekspor Data")
    records = st.session_state.records

    if not records:
        st.info("Belum ada data untuk diekspor.")
    else:
        st.write(f"**Total referensi:** {len(records)}")

        export_filter = st.radio(
            "Ekspor:",
            ["Semua", "Hanya kandidat terverifikasi", "Hanya perlu verifikasi"],
            horizontal=True,
        )

        export_records = records
        if export_filter == "Hanya kandidat terverifikasi":
            export_records = [
                r for r in records
                if "candidate" in r.get("indexing_status", "").lower()
                or "impact" in r.get("indexing_status", "").lower()
            ]
        elif export_filter == "Hanya perlu verifikasi":
            export_records = [r for r in records if r.get("indexing_status", "") == "Needs verification"]

        st.write(f"Diekspor: **{len(export_records)}** referensi")
        st.divider()

        if export_records:
            exp1, exp2 = st.columns(2)

            with exp1:
                st.download_button(
                    "📥 CSV",
                    data=to_csv(export_records),
                    file_name="bibliografi_riset.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
                st.download_button(
                    "📥 BibTeX",
                    data=to_bibtex(export_records).encode("utf-8"),
                    file_name="bibliografi_riset.bib",
                    mime="text/plain",
                    use_container_width=True,
                )

            with exp2:
                st.download_button(
                    "📥 RIS",
                    data=to_ris(export_records).encode("utf-8"),
                    file_name="bibliografi_riset.ris",
                    mime="text/plain",
                    use_container_width=True,
                )
                st.download_button(
                    "📥 JSON",
                    data=json.dumps(export_records, ensure_ascii=False, indent=2).encode("utf-8"),
                    file_name="bibliografi_riset.json",
                    mime="application/json",
                    use_container_width=True,
                )

            st.download_button(
                "📥 VOSviewer Network (.net)",
                data=to_vosviewer_net(export_records).encode("utf-8"),
                file_name="coauthorship_vosviewer.net",
                mime="text/plain",
                use_container_width=True,
            )
        else:
            st.warning("Tidak ada referensi sesuai filter untuk diekspor.")

with source_tab:
    st.subheader("🌐 Daftar Sumber Kredibel")
    st.write("Aplikasi ini memakai sumber terbuka/kredibel yang relatif aman untuk Streamlit Cloud tanpa library berat.")
    for src, desc in SOURCE_HELP.items():
        st.markdown(f"- **{src}**: {desc}")

    st.divider()
    st.write("### Sumber berbayar/berlangganan")
    st.markdown("""
- **Scopus**: gunakan ekspor CSV/RIS/BibTeX dari akun institusi, lalu upload ke tab Upload.
- **Web of Science**: gunakan ekspor CSV/RIS/BibTeX dari akun institusi, lalu upload ke tab Upload.
- **Journal Citation Reports/JCR**: gunakan untuk validasi Impact Factor resmi.
- **Scimago/SJR**: gunakan untuk validasi quartile dan SJR.
- **Dimensions/Lens**: bisa digunakan lewat ekspor CSV/RIS/BibTeX.
""")

    st.warning("Catatan: status Scopus/WoS/high impact di aplikasi ini adalah kandidat berbasis metadata, bukan verifikasi resmi.")

with guide_tab:
    st.subheader("🚀 Panduan Penggunaan & Deploy")

    usage_tab, deploy_tab, tips_tab = st.tabs(["📖 Cara Pakai", "☁️ Deploy Cloud", "💡 Tips"])

    with usage_tab:
        st.markdown("""
### Cara Pakai
1. **Cari** referensi dari banyak sumber kredibel.
2. **Upload** file bibliografi dari Scopus/WoS/Zotero/Mendeley dalam format CSV, BibTeX, atau RIS.
3. **Manual** untuk menambahkan referensi satu per satu.
4. **Data** untuk melihat, memfilter, dan mengecek detail referensi.
5. **Insight** untuk melihat ringkasan bibliometrik, distribusi tahun, jurnal, penulis, keyword, dan kolaborasi.
6. **Ekspor** ke CSV, BibTeX, RIS, JSON, atau VOSviewer `.net`.
""")

    with deploy_tab:
        st.markdown("""
### Deploy ke Streamlit Cloud
1. Upload isi folder ke repository GitHub.
2. Pastikan file utama bernama `app.py`.
3. Pastikan `requirements.txt` ada di root repository.
4. Di Streamlit Cloud, pilih repo dan branch `main`.
5. Main file path: `app.py`.
6. Disarankan pakai Python 3.11 atau 3.12.

### Struktur Folder
```text
app.py
requirements.txt
.streamlit/config.toml
data/sample_references.csv
README.md
```
""")

    with tips_tab:
        st.markdown("""
### Tips
- Untuk Scopus/WoS, ekspor sebagai **CSV/RIS/BibTeX**.
- Semakin banyak sumber dipilih, hasil makin banyak tetapi proses pencarian lebih lama.
- Jika satu sumber gagal, aplikasi tetap melanjutkan sumber lain.
- Masukkan DOI sebanyak mungkin agar deduplikasi lebih akurat.
- Status Scopus/WoS/high impact di aplikasi ini adalah **kandidat berbasis metadata**, bukan validasi resmi.
- Validasi akhir tetap lakukan melalui Scopus, Web of Science, JCR, SJR, atau laman resmi jurnal.
- Ekspor data secara berkala agar tidak hilang ketika session Streamlit selesai.
""")
