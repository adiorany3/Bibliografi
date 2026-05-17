
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
    "database", "impact_factor", "global_citations", "local_citations",
    "references", "affiliations", "countries", "document_type",
    "indexing_status", "verification_reason",
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
    "Crossref": "Metadata DOI lintas publisher akademik; stabil untuk pencarian umum.",
    "OpenAlex": "Database open bibliographic besar untuk karya ilmiah; kuat untuk multi-disiplin.",
    "PubMed": "Literatur biomedis dari NCBI/NLM; sangat kredibel untuk kesehatan dan life sciences.",
    "Semantic Scholar": "Indeks AI2 untuk paper dan metadata akademik; kadang rate-limited, aplikasi akan skip otomatis jika gagal.",
    "DOAJ": "Directory of Open Access Journals; cocok untuk open access dan jurnal terkurasi.",
    "arXiv": "Preprint kredibel untuk CS, matematika, fisika, statistik, dan bidang terkait.",
    "Europe PMC": "Literatur biomedis dan life sciences; pelengkap PubMed/PMC.",
    "DataCite": "Metadata DOI untuk dataset, preprint, software, report, dan output riset non-jurnal.",
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
            "global_citations": first(raw, ["global citations", "global_citations", "citations", "citation count", "cited_by_count", "is-referenced-by-count", "times cited", "tc"]),
            "local_citations": first(raw, ["local citations", "local_citations", "lc"]),
            "references": first(raw, ["references", "cited references", "cr", "bibliography", "reference list"]),
            "affiliations": first(raw, ["affiliations", "affiliation", "institutions", "institution"]),
            "countries": first(raw, ["countries", "country", "author countries"]),
            "document_type": first(raw, ["document type", "publication type", "type", "subtype"]),
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
            "global_citations": item.get("is-referenced-by-count", ""),
            "references": "; ".join(str(ref.get("DOI", ref.get("article-title", ""))) for ref in item.get("reference", [])[:100] if isinstance(ref, dict)),
            "document_type": item.get("type", ""),
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
            "global_citations": item.get("cited_by_count", ""),
            "document_type": item.get("type", ""),
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
        "fields": "title,authors,year,venue,publicationVenue,externalIds,url,abstract,fieldsOfStudy,publicationTypes,citationCount"
    }
    headers = {"User-Agent": "BibliografiStreamlit/6.0"}
    r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search", params=params, headers=headers, timeout=25)
    if r.status_code in (403, 429, 500, 502, 503):
        return []
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
            "global_citations": item.get("citationCount", ""),
            "abstract": item.get("abstract", ""),
            "keywords": "; ".join(item.get("fieldsOfStudy") or []),
            "notes": "; ".join(item.get("publicationTypes") or []),
        })

    return standardize(records)


def search_doaj(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    """Search DOAJ articles. Fails gracefully if DOAJ endpoint is unavailable."""
    params = {"pageSize": min(rows, 100)}
    url = f"https://doaj.org/api/search/articles/{requests.utils.quote(query)}"
    r = requests.get(url, params=params, timeout=25)
    if r.status_code in (403, 404, 429, 500, 502, 503):
        return []
    r.raise_for_status()

    records = []
    for item in r.json().get("results", []):
        bib = item.get("bibjson", {})
        authors = [a.get("name", "") for a in bib.get("author", [])]
        journal = bib.get("journal", {}) or {}

        url_value = ""
        for link in bib.get("link", []) or []:
            if isinstance(link, dict) and link.get("url"):
                url_value = link.get("url")
                break

        doi = ""
        for ident in bib.get("identifier", []) or []:
            if isinstance(ident, dict):
                ident_type = str(ident.get("type", "")).lower()
                ident_value = ident.get("id", "")
                if ident_type == "doi" or doi_from_text(ident_value):
                    doi = doi_from_text(ident_value) or ident_value
                    break

        records.append({
            "title": bib.get("title", ""),
            "authors": authors,
            "year": bib.get("year", ""),
            "journal": journal.get("title", ""),
            "publisher": bib.get("publisher", "") or journal.get("publisher", ""),
            "doi": doi,
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



def search_datacite(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    """Search DataCite DOI metadata for datasets, reports, preprints, software, and other research outputs."""
    params = {"query": query, "page[size]": min(rows, 100)}
    headers = {"User-Agent": f"BibliografiStreamlit/AutoComplete (mailto:{email or 'example@example.com'})"}
    r = requests.get("https://api.datacite.org/dois", params=params, headers=headers, timeout=25)
    if r.status_code in (403, 429, 500, 502, 503):
        return []
    r.raise_for_status()

    records = []
    for item in r.json().get("data", []):
        attr = item.get("attributes", {}) or {}

        titles = attr.get("titles") or []
        title = ""
        if titles and isinstance(titles[0], dict):
            title = titles[0].get("title", "")

        creators = []
        for c in attr.get("creators", []) or []:
            name = c.get("name") or " ".join(filter(None, [c.get("givenName", ""), c.get("familyName", "")]))
            if name:
                creators.append(name)

        subjects = []
        for s in attr.get("subjects", []) or []:
            if isinstance(s, dict) and s.get("subject"):
                subjects.append(s.get("subject"))

        container = ""
        if attr.get("container"):
            container = attr.get("container", {}).get("title", "")

        records.append({
            "title": title,
            "authors": creators,
            "year": attr.get("publicationYear", ""),
            "journal": container or attr.get("types", {}).get("resourceTypeGeneral", ""),
            "publisher": attr.get("publisher", ""),
            "doi": attr.get("doi", ""),
            "url": attr.get("url", ""),
            "database": "DataCite",
            "abstract": clean(attr.get("descriptions", [{}])[0].get("description", "")) if attr.get("descriptions") else "",
            "keywords": "; ".join(subjects[:10]),
            "document_type": attr.get("types", {}).get("resourceTypeGeneral", ""),
            "notes": "DataCite DOI metadata",
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
    "DataCite": search_datacite,
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



def safe_int(value: object) -> int:
    try:
        return int(float(str(value).replace(",", ".").strip()))
    except Exception:
        return 0


def split_multi(value: str) -> List[str]:
    parts = re.split(r";|\||\n", clean(value))
    return [p.strip() for p in parts if p.strip()]


def citation_metrics(records: List[Dict[str, str]]) -> Dict[str, object]:
    citations = [safe_int(r.get("global_citations", 0)) for r in records]
    cited = [c for c in citations if c > 0]
    sorted_cites = sorted(citations, reverse=True)
    h_index = sum(1 for i, c in enumerate(sorted_cites, 1) if c >= i)
    g_index = 0
    total_so_far = 0
    for i, c in enumerate(sorted_cites, 1):
        total_so_far += c
        if total_so_far >= i * i:
            g_index = i
    return {
        "TC": sum(citations),
        "AC": (sum(citations) / len(records)) if records else 0,
        "NCP": len(cited),
        "PCP": (len(cited) / len(records)) if records else 0,
        "CCP": (sum(cited) / len(cited)) if cited else 0,
        "h_index": h_index,
        "g_index": g_index,
        "i10": sum(1 for c in citations if c >= 10),
        "top_cited": sorted(records, key=lambda r: safe_int(r.get("global_citations", 0)), reverse=True)[:15],
    }


def performance_table(records: List[Dict[str, str]], unit: str) -> List[Dict[str, object]]:
    groups: Dict[str, List[Dict[str, str]]] = {}
    if unit == "authors":
        for r in records:
            for a in split_multi(r.get("authors", "")):
                groups.setdefault(a, []).append(r)
    elif unit == "journals":
        for r in records:
            groups.setdefault(clean(r.get("journal", "Unknown")) or "Unknown", []).append(r)
    elif unit == "countries":
        for r in records:
            for c in split_multi(r.get("countries", "")):
                groups.setdefault(c, []).append(r)
    else:
        for r in records:
            groups.setdefault(clean(r.get("database", "Unknown")) or "Unknown", []).append(r)

    rows = []
    for name, items in groups.items():
        years = sorted({safe_int(x.get("year")) for x in items if safe_int(x.get("year"))})
        citations = [safe_int(x.get("global_citations", 0)) for x in items]
        nca = sum(len(split_multi(x.get("authors", ""))) for x in items)
        tp = len(items)
        sa = sum(1 for x in items if len(split_multi(x.get("authors", ""))) == 1)
        ca = sum(1 for x in items if len(split_multi(x.get("authors", ""))) > 1)
        nay = len(years)
        tc = sum(citations)
        ncp = sum(1 for c in citations if c > 0)
        rows.append({
            "Unit": name[:90], "TP": tp, "NCA": nca, "SA": sa, "CA": ca,
            "NAY": nay, "PAY": round(tp / nay, 2) if nay else 0,
            "TC": tc, "AC": round(tc / tp, 2) if tp else 0,
            "NCP": ncp, "PCP": round(ncp / tp, 2) if tp else 0,
            "CCP": round(tc / ncp, 2) if ncp else 0,
            "CI": round((nca / tp) / tp, 3) if tp else 0,
            "CC": round(1 - (tp / nca), 3) if nca else 0,
        })
    return sorted(rows, key=lambda x: (x["TP"], x["TC"]), reverse=True)[:50]


def co_word_network(records: List[Dict[str, str]], limit: int = 30) -> Dict[str, object]:
    kw_counter = Counter()
    edges = Counter()
    for r in records:
        text_keywords = split_multi(r.get("keywords", ""))
        if not text_keywords:
            raw = (r.get("title", "") + " " + r.get("abstract", "")).lower()
            words = re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", raw)
            stop = {"this","that","with","from","have","were","been","analysis","study","research","paper","using","based","results","method","methods"}
            text_keywords = [w for w in words if w not in stop][:12]
        kws = list(dict.fromkeys([clean(k).lower() for k in text_keywords if clean(k)]))[:15]
        for k in kws:
            kw_counter[k] += 1
        for i in range(len(kws)):
            for j in range(i + 1, len(kws)):
                edges[tuple(sorted([kws[i], kws[j]]))] += 1
    return {"nodes": kw_counter.most_common(limit), "edges": edges.most_common(limit)}


def bibliographic_coupling(records: List[Dict[str, str]], limit: int = 20) -> List[Dict[str, object]]:
    pairs = []
    ref_sets = []
    for r in records:
        refs = {x.lower() for x in split_multi(r.get("references", "")) if len(x) > 3}
        ref_sets.append(refs)
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            shared = ref_sets[i] & ref_sets[j]
            if shared:
                pairs.append({
                    "Paper 1": records[i].get("title", "")[:70],
                    "Paper 2": records[j].get("title", "")[:70],
                    "Shared references": len(shared),
                    "Strength": len(shared),
                })
    return sorted(pairs, key=lambda x: x["Strength"], reverse=True)[:limit]


def co_citation_analysis(records: List[Dict[str, str]], limit: int = 30) -> Dict[str, object]:
    ref_count = Counter()
    co_edges = Counter()
    for r in records:
        refs = list(dict.fromkeys([x.lower() for x in split_multi(r.get("references", "")) if len(x) > 3]))[:50]
        for ref in refs:
            ref_count[ref] += 1
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                co_edges[tuple(sorted([refs[i], refs[j]]))] += 1
    return {"top_references": ref_count.most_common(limit), "co_cited_pairs": co_edges.most_common(limit)}


def citation_relationships(records: List[Dict[str, str]], limit: int = 20) -> List[Dict[str, object]]:
    rows = []
    for r in sorted(records, key=lambda x: safe_int(x.get("global_citations", 0)), reverse=True)[:limit]:
        rows.append({
            "Title": r.get("title", "")[:85],
            "Year": r.get("year", ""),
            "Journal": r.get("journal", "")[:45],
            "Global citations": safe_int(r.get("global_citations", 0)),
            "Local citations": safe_int(r.get("local_citations", 0)),
            "DOI": r.get("doi", ""),
        })
    return rows


def network_metrics_summary(records: List[Dict[str, str]]) -> List[Dict[str, object]]:
    author_papers = Counter()
    degree = Counter()
    weighted_degree = Counter()
    edges = Counter()
    for r in records:
        authors = split_multi(r.get("authors", ""))
        for a in authors:
            author_papers[a] += 1
        for i in range(len(authors)):
            for j in range(i + 1, len(authors)):
                pair = tuple(sorted([authors[i], authors[j]]))
                edges[pair] += 1
    for (a,b), w in edges.items():
        degree[a] += 1; degree[b] += 1
        weighted_degree[a] += w; weighted_degree[b] += w
    rows=[]
    for a, tp in author_papers.most_common(50):
        rows.append({
            "Author": a, "TP": tp,
            "Degree centrality": degree[a],
            "Weighted degree": weighted_degree[a],
            "Approx. eigen/prestige": round((degree[a] * max(1, weighted_degree[a])) ** 0.5, 3),
        })
    return rows


def methodology_checklist(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    m = get_basic_metrics(records)
    return [
        {"Step": "1. Define aims and scope", "Output in app": "Formulasi tujuan, scope, keyword, periode, dan database pada tab Metodologi.", "Status": "Siap" if records else "Isi data dulu"},
        {"Step": "2. Choose techniques", "Output in app": "Performance analysis, citation analysis, co-citation, bibliographic coupling, co-word, co-authorship.", "Status": "Siap"},
        {"Step": "3. Collect and clean data", "Output in app": f"{m['total']} dokumen, DOI {m['with_doi']}, abstrak {m['with_abstract']}, keyword {m['with_keywords']}.", "Status": "Perlu validasi manual" if m['need'] else "Cukup baik"},
        {"Step": "4. Run analysis and report", "Output in app": "Tab Insight, Science Mapping, laporan TXT, dan ekspor VOSviewer/CiteSpace.", "Status": "Siap" if records else "Belum ada data"},
    ]


def to_citespace(records: List[Dict[str, str]]) -> str:
    lines = []
    for r in records:
        lines.append("%0 Journal Article")
        lines.append(f"%T {r.get('title','')}")
        for a in split_multi(r.get("authors", ""))[:20]:
            lines.append(f"%A {a}")
        lines.append(f"%J {r.get('journal','')}")
        lines.append(f"%D {r.get('year','')}")
        if r.get("doi"):
            lines.append(f"%R {r.get('doi')}")
        if r.get("url"):
            lines.append(f"%U {r.get('url')}")
        if r.get("abstract"):
            lines.append(f"%X {r.get('abstract')[:1000]}")
        if r.get("keywords"):
            lines.append(f"%K {r.get('keywords')}")
        if r.get("references"):
            for ref in split_multi(r.get("references", ""))[:100]:
                lines.append(f"%Z REF: {ref}")
        lines.append("")
    return "\n".join(lines)

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
# Meta-Analytic Analysis Utilities
# =========================
META_COLUMNS = [
    "study_id", "year", "group", "effect_size", "standard_error", "variance",
    "weight_fixed", "weight_random", "lower_ci", "upper_ci", "notes"
]


def _safe_float(value, default=None):
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def _normal_cdf(x: float) -> float:
    # Standard normal CDF using math.erf to avoid scipy dependency.
    import math
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def compute_smd(n_t, mean_t, sd_t, n_c, mean_c, sd_c):
    """Hedges g and SE from two independent groups."""
    import math
    n_t = _safe_float(n_t)
    mean_t = _safe_float(mean_t)
    sd_t = _safe_float(sd_t)
    n_c = _safe_float(n_c)
    mean_c = _safe_float(mean_c)
    sd_c = _safe_float(sd_c)
    if not all(v is not None for v in [n_t, mean_t, sd_t, n_c, mean_c, sd_c]) or n_t <= 1 or n_c <= 1 or sd_t <= 0 or sd_c <= 0:
        return None, None
    pooled = math.sqrt(((n_t - 1) * sd_t ** 2 + (n_c - 1) * sd_c ** 2) / (n_t + n_c - 2))
    if pooled <= 0:
        return None, None
    d = (mean_t - mean_c) / pooled
    correction = 1 - (3 / (4 * (n_t + n_c) - 9))
    g = correction * d
    var_g = ((n_t + n_c) / (n_t * n_c)) + (g ** 2 / (2 * (n_t + n_c - 2)))
    return g, math.sqrt(var_g)


def compute_log_or(a, b, c, d):
    """Log odds ratio and SE from 2x2 table: event_t, non_event_t, event_c, non_event_c."""
    import math
    a = _safe_float(a)
    b = _safe_float(b)
    c = _safe_float(c)
    d = _safe_float(d)
    if not all(v is not None for v in [a, b, c, d]):
        return None, None
    # Haldane-Anscombe correction for zeros.
    if min(a, b, c, d) == 0:
        a += 0.5
        b += 0.5
        c += 0.5
        d += 0.5
    if min(a, b, c, d) <= 0:
        return None, None
    lor = math.log((a * d) / (b * c))
    se = math.sqrt(1/a + 1/b + 1/c + 1/d)
    return lor, se


def compute_log_rr(event_t, total_t, event_c, total_c):
    """Log risk ratio and SE."""
    import math
    event_t = _safe_float(event_t)
    total_t = _safe_float(total_t)
    event_c = _safe_float(event_c)
    total_c = _safe_float(total_c)
    if not all(v is not None for v in [event_t, total_t, event_c, total_c]):
        return None, None
    non_event_t = total_t - event_t
    non_event_c = total_c - event_c
    if min(event_t, non_event_t, event_c, non_event_c) == 0:
        event_t += 0.5
        non_event_t += 0.5
        event_c += 0.5
        non_event_c += 0.5
        total_t = event_t + non_event_t
        total_c = event_c + non_event_c
    if min(event_t, event_c, total_t, total_c) <= 0:
        return None, None
    lrr = math.log((event_t / total_t) / (event_c / total_c))
    se = math.sqrt((1/event_t) - (1/total_t) + (1/event_c) - (1/total_c))
    return lrr, se


def compute_fisher_z(r, n):
    """Fisher z transformation for correlation meta-analysis."""
    import math
    r = _safe_float(r)
    n = _safe_float(n)
    if r is None or n is None or n <= 3 or r <= -1 or r >= 1:
        return None, None
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = math.sqrt(1 / (n - 3))
    return z, se


def parse_meta_csv_bytes(data: bytes):
    """Parse meta-analysis CSV. Supports generic yi/sei and raw study columns."""
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = list(reader)
    return standardize_meta_rows(rows)


def standardize_meta_rows(rows):
    studies = []
    for i, row in enumerate(rows, 1):
        lower = {str(k).strip().lower(): v for k, v in row.items()}
        study_id = clean(
            lower.get("study_id") or lower.get("study") or lower.get("author") or lower.get("title") or f"Study {i}"
        )
        year = year_from_text(
            lower.get("year") or lower.get("publication_year") or lower.get("date") or ""
        )
        group = clean(lower.get("group") or lower.get("subgroup") or lower.get("moderator") or "Overall")
        notes = clean(lower.get("notes") or lower.get("note") or "")

        yi = _safe_float(lower.get("effect_size") or lower.get("yi") or lower.get("effect") or lower.get("g") or lower.get("d") or lower.get("logor") or lower.get("logrr") or lower.get("z"))
        sei = _safe_float(lower.get("standard_error") or lower.get("se") or lower.get("sei"))
        vi = _safe_float(lower.get("variance") or lower.get("var") or lower.get("vi"))

        if yi is None or (sei is None and vi is None):
            effect_type = clean(lower.get("effect_type") or lower.get("type") or "").lower()

            if effect_type in ["smd", "hedges", "hedges_g", "cohen_d", "d", "g"] or any(k in lower for k in ["mean_t", "mean_control"]):
                yi, sei = compute_smd(
                    lower.get("n_t") or lower.get("n_treatment") or lower.get("nt"),
                    lower.get("mean_t") or lower.get("mean_treatment") or lower.get("mt"),
                    lower.get("sd_t") or lower.get("sd_treatment") or lower.get("sdt"),
                    lower.get("n_c") or lower.get("n_control") or lower.get("nc"),
                    lower.get("mean_c") or lower.get("mean_control") or lower.get("mc"),
                    lower.get("sd_c") or lower.get("sd_control") or lower.get("sdc"),
                )

            elif effect_type in ["or", "log_or", "odds_ratio", "logor"] or any(k in lower for k in ["event_t", "non_event_t"]):
                yi, sei = compute_log_or(
                    lower.get("event_t") or lower.get("a"),
                    lower.get("non_event_t") or lower.get("b"),
                    lower.get("event_c") or lower.get("c"),
                    lower.get("non_event_c") or lower.get("d"),
                )

            elif effect_type in ["rr", "risk_ratio", "log_rr", "logrr"] or any(k in lower for k in ["total_t", "total_c"]):
                yi, sei = compute_log_rr(
                    lower.get("event_t") or lower.get("events_treatment"),
                    lower.get("total_t") or lower.get("n_t") or lower.get("n_treatment"),
                    lower.get("event_c") or lower.get("events_control"),
                    lower.get("total_c") or lower.get("n_c") or lower.get("n_control"),
                )

            elif effect_type in ["correlation", "r", "fisher_z"] or "r" in lower:
                yi, sei = compute_fisher_z(lower.get("r"), lower.get("n"))

        if yi is None:
            continue
        if sei is None and vi is not None and vi > 0:
            import math
            sei = math.sqrt(vi)
        if sei is None or sei <= 0:
            continue

        vi = sei ** 2
        studies.append({
            "study_id": study_id,
            "year": year,
            "group": group or "Overall",
            "effect_size": yi,
            "standard_error": sei,
            "variance": vi,
            "notes": notes,
        })
    return studies


def meta_analysis(studies):
    import math
    clean_studies = []
    for s in studies:
        yi = _safe_float(s.get("effect_size"))
        sei = _safe_float(s.get("standard_error"))
        vi = _safe_float(s.get("variance"))
        if yi is None:
            continue
        if sei is None and vi is not None and vi > 0:
            sei = math.sqrt(vi)
        if sei is None or sei <= 0:
            continue
        vi = sei ** 2
        clean_studies.append({**s, "effect_size": yi, "standard_error": sei, "variance": vi})

    k = len(clean_studies)
    if k == 0:
        return {"k": 0, "studies": []}

    weights_fe = [1 / s["variance"] for s in clean_studies]
    sum_w = sum(weights_fe)
    pooled_fe = sum(w * s["effect_size"] for w, s in zip(weights_fe, clean_studies)) / sum_w
    se_fe = math.sqrt(1 / sum_w)
    ci_fe = (pooled_fe - 1.96 * se_fe, pooled_fe + 1.96 * se_fe)
    z_fe = pooled_fe / se_fe if se_fe else 0
    p_fe = 2 * (1 - _normal_cdf(abs(z_fe)))

    q = sum(w * (s["effect_size"] - pooled_fe) ** 2 for w, s in zip(weights_fe, clean_studies))
    df = k - 1
    c = sum_w - (sum(w ** 2 for w in weights_fe) / sum_w) if sum_w else 0
    tau2 = max(0, (q - df) / c) if c > 0 and k > 1 else 0
    i2 = max(0, ((q - df) / q) * 100) if q > 0 and k > 1 else 0

    weights_re = [1 / (s["variance"] + tau2) for s in clean_studies]
    sum_wr = sum(weights_re)
    pooled_re = sum(w * s["effect_size"] for w, s in zip(weights_re, clean_studies)) / sum_wr
    se_re = math.sqrt(1 / sum_wr)
    ci_re = (pooled_re - 1.96 * se_re, pooled_re + 1.96 * se_re)
    z_re = pooled_re / se_re if se_re else 0
    p_re = 2 * (1 - _normal_cdf(abs(z_re)))

    enriched = []
    for s, wf, wr in zip(clean_studies, weights_fe, weights_re):
        yi = s["effect_size"]
        se = s["standard_error"]
        enriched.append({
            **s,
            "weight_fixed": wf / sum_w * 100 if sum_w else 0,
            "weight_random": wr / sum_wr * 100 if sum_wr else 0,
            "lower_ci": yi - 1.96 * se,
            "upper_ci": yi + 1.96 * se,
        })

    return {
        "k": k,
        "studies": enriched,
        "fixed": {"pooled": pooled_fe, "se": se_fe, "ci": ci_fe, "z": z_fe, "p": p_fe},
        "random": {"pooled": pooled_re, "se": se_re, "ci": ci_re, "z": z_re, "p": p_re},
        "heterogeneity": {"Q": q, "df": df, "tau2": tau2, "I2": i2},
    }


def subgroup_meta_analysis(studies):
    groups = {}
    for s in studies:
        g = clean(s.get("group", "Overall")) or "Overall"
        groups.setdefault(g, []).append(s)
    return {g: meta_analysis(items) for g, items in groups.items()}


def meta_to_csv(studies):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=META_COLUMNS)
    writer.writeheader()
    for s in studies:
        writer.writerow({col: s.get(col, "") for col in META_COLUMNS})
    return buf.getvalue().encode("utf-8-sig")


def build_meta_report(result, subgroup_results=None, model_name="Random-effects"):
    if not result or result.get("k", 0) == 0:
        return "Belum ada data meta-analysis yang valid."

    m = result["random"] if model_name.startswith("Random") else result["fixed"]
    h = result["heterogeneity"]
    lines = [
        "LAPORAN META-ANALYSIS",
        "",
        "Ringkasan:",
        f"- Jumlah studi: {result['k']}",
        f"- Model utama: {model_name}",
        f"- Pooled effect: {m['pooled']:.4f}",
        f"- 95% CI: {m['ci'][0]:.4f} sampai {m['ci'][1]:.4f}",
        f"- z-value: {m['z']:.4f}",
        f"- p-value: {m['p']:.6f}",
        "",
        "Heterogeneity:",
        f"- Q: {h['Q']:.4f}",
        f"- df: {h['df']}",
        f"- tau²: {h['tau2']:.4f}",
        f"- I²: {h['I2']:.2f}%",
        "",
        "Interpretasi singkat:",
    ]
    if h["I2"] < 30:
        lines.append("- Heterogenitas rendah.")
    elif h["I2"] < 60:
        lines.append("- Heterogenitas sedang.")
    else:
        lines.append("- Heterogenitas tinggi; pertimbangkan subgroup analysis, moderator, atau sensitivity analysis.")

    if subgroup_results:
        lines += ["", "Subgroup analysis:"]
        for g, res in subgroup_results.items():
            if res.get("k", 0):
                rm = res["random"]
                lines.append(f"- {g}: k={res['k']}, pooled={rm['pooled']:.4f}, 95% CI={rm['ci'][0]:.4f} sampai {rm['ci'][1]:.4f}, I²={res['heterogeneity']['I2']:.2f}%")

    lines += [
        "",
        "Catatan metodologis:",
        "- Meta-analysis merangkum bukti empiris melalui ukuran efek dan hubungan antarvariabel.",
        "- Pastikan studi cukup homogen secara desain, populasi, intervensi/eksposur, dan outcome.",
        "- Periksa risiko bias, kriteria inklusi-eksklusi, dan konsistensi definisi outcome sebelum menarik kesimpulan.",
    ]
    return "\n".join(lines)


def sample_meta_csv():
    return """study_id,year,group,effect_size,standard_error,notes
Smith 2020,2020,Education,0.35,0.12,Generic effect size
Lee 2021,2021,Education,0.52,0.15,Generic effect size
Garcia 2022,2022,Health,0.28,0.10,Generic effect size
Chen 2023,2023,Health,0.61,0.20,Generic effect size
Rahman 2024,2024,Technology,0.44,0.13,Generic effect size
"""


def sample_meta_raw_csv():
    return """study_id,year,group,effect_type,n_t,mean_t,sd_t,n_c,mean_c,sd_c,notes
Study A,2020,Education,smd,45,82.4,10.5,43,77.1,11.2,Raw SMD data
Study B,2021,Education,smd,60,75.0,9.8,58,71.3,10.1,Raw SMD data
Study C,2022,Education,smd,38,68.2,8.9,40,65.4,9.2,Raw SMD data
"""


def render_meta_analysis_tab():
    st.subheader("🧪 Meta-Analytic Analysis")
    st.caption("Analisis ini melengkapi bibliometric analysis dengan ringkasan bukti empiris berbasis effect size.")

    if "meta_studies" not in st.session_state:
        st.session_state.meta_studies = []

    st.info(
        "Gunakan tab ini jika data studi memiliki effect size, standard error, atau data mentah "
        "seperti mean/SD dua kelompok, odds ratio, risk ratio, atau korelasi."
    )

    meta_input_tab, meta_result_tab, meta_guide_tab = st.tabs([
        "📥 Input Data", "📊 Hasil Meta-Analysis", "📘 Panduan"
    ])

    with meta_input_tab:
        st.write("### Upload Data Meta-Analysis")
        uploaded_meta = st.file_uploader(
            "Upload CSV meta-analysis",
            type=["csv"],
            key="meta_upload",
            help="Kolom minimal: study_id,effect_size,standard_error. Bisa juga memakai data mentah SMD/OR/RR/korelasi."
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            st.download_button(
                "📄 Template effect size",
                data=sample_meta_csv().encode("utf-8"),
                file_name="template_meta_effect_size.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with c2:
            st.download_button(
                "📄 Template raw SMD",
                data=sample_meta_raw_csv().encode("utf-8"),
                file_name="template_meta_raw_smd.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with c3:
            if st.button("🧪 Muat sample meta", use_container_width=True):
                st.session_state.meta_studies = parse_meta_csv_bytes(sample_meta_csv().encode("utf-8"))
                st.success("Sample meta-analysis dimuat.")

        if uploaded_meta and st.button("Proses CSV Meta-Analysis", type="primary", use_container_width=True):
            try:
                parsed = parse_meta_csv_bytes(uploaded_meta.getvalue())
                st.session_state.meta_studies = parsed
                st.success(f"Berhasil membaca {len(parsed)} studi valid.")
            except Exception as exc:
                st.error(f"Gagal membaca CSV meta-analysis: {exc}")

        st.divider()
        st.write("### Tambah Studi Manual")
        with st.form("manual_meta_form"):
            mode = st.selectbox(
                "Jenis input",
                ["Effect size + SE", "SMD dari mean/SD dua kelompok", "Log Odds Ratio dari 2x2", "Log Risk Ratio", "Korelasi Fisher z"]
            )
            study_id = st.text_input("Study ID", placeholder="Contoh: Smith 2022")
            year = st.text_input("Tahun")
            group = st.text_input("Subgroup/moderator", value="Overall")

            yi = sei = None
            notes = ""

            if mode == "Effect size + SE":
                effect_size = st.number_input("Effect size / yi", value=0.0, step=0.01, format="%.4f")
                standard_error = st.number_input("Standard error / SE", min_value=0.0001, value=0.10, step=0.01, format="%.4f")
                yi = effect_size
                sei = standard_error
                notes = "Generic effect size"

            elif mode == "SMD dari mean/SD dua kelompok":
                a, b, c = st.columns(3)
                with a:
                    n_t = st.number_input("n treatment", min_value=2, value=50)
                    mean_t = st.number_input("mean treatment", value=75.0)
                    sd_t = st.number_input("SD treatment", min_value=0.0001, value=10.0)
                with b:
                    n_c = st.number_input("n control", min_value=2, value=50)
                    mean_c = st.number_input("mean control", value=70.0)
                    sd_c = st.number_input("SD control", min_value=0.0001, value=10.0)
                yi, sei = compute_smd(n_t, mean_t, sd_t, n_c, mean_c, sd_c)
                notes = "Hedges g from two independent groups"
                with c:
                    st.metric("Hedges g", f"{yi:.4f}" if yi is not None else "Invalid")
                    st.metric("SE", f"{sei:.4f}" if sei is not None else "Invalid")

            elif mode == "Log Odds Ratio dari 2x2":
                a1, a2, a3, a4 = st.columns(4)
                with a1:
                    event_t = st.number_input("event treatment", min_value=0, value=20)
                with a2:
                    non_event_t = st.number_input("non-event treatment", min_value=0, value=30)
                with a3:
                    event_c = st.number_input("event control", min_value=0, value=12)
                with a4:
                    non_event_c = st.number_input("non-event control", min_value=0, value=38)
                yi, sei = compute_log_or(event_t, non_event_t, event_c, non_event_c)
                notes = "Log odds ratio from 2x2 table"
                st.metric("log(OR)", f"{yi:.4f}" if yi is not None else "Invalid")
                st.metric("SE", f"{sei:.4f}" if sei is not None else "Invalid")

            elif mode == "Log Risk Ratio":
                a1, a2, a3, a4 = st.columns(4)
                with a1:
                    event_t = st.number_input("events treatment", min_value=0, value=20)
                with a2:
                    total_t = st.number_input("total treatment", min_value=1, value=50)
                with a3:
                    event_c = st.number_input("events control", min_value=0, value=12)
                with a4:
                    total_c = st.number_input("total control", min_value=1, value=50)
                yi, sei = compute_log_rr(event_t, total_t, event_c, total_c)
                notes = "Log risk ratio"
                st.metric("log(RR)", f"{yi:.4f}" if yi is not None else "Invalid")
                st.metric("SE", f"{sei:.4f}" if sei is not None else "Invalid")

            else:
                a1, a2 = st.columns(2)
                with a1:
                    r_value = st.number_input("Correlation r", min_value=-0.999, max_value=0.999, value=0.30, step=0.01)
                with a2:
                    n_value = st.number_input("Sample size n", min_value=4, value=100)
                yi, sei = compute_fisher_z(r_value, n_value)
                notes = "Fisher z from correlation"
                st.metric("Fisher z", f"{yi:.4f}" if yi is not None else "Invalid")
                st.metric("SE", f"{sei:.4f}" if sei is not None else "Invalid")

            submitted = st.form_submit_button("Tambahkan studi", type="primary")

        if submitted:
            if yi is None or sei is None or sei <= 0:
                st.error("Data studi tidak valid.")
            else:
                st.session_state.meta_studies.append({
                    "study_id": study_id or f"Study {len(st.session_state.meta_studies)+1}",
                    "year": year,
                    "group": group or "Overall",
                    "effect_size": yi,
                    "standard_error": sei,
                    "variance": sei ** 2,
                    "notes": notes,
                })
                st.success("Studi ditambahkan.")

        if st.session_state.meta_studies:
            st.divider()
            if st.button("🗑️ Kosongkan data meta-analysis"):
                st.session_state.meta_studies = []
                st.success("Data meta-analysis dikosongkan.")

    with meta_result_tab:
        studies = st.session_state.meta_studies
        if not studies:
            st.info("Belum ada data meta-analysis. Upload CSV, tambah manual, atau muat sample.")
        else:
            result = meta_analysis(studies)
            subgroup_results = subgroup_meta_analysis(studies)

            model_choice = st.radio("Model utama", ["Random-effects (DerSimonian-Laird)", "Fixed-effect"], horizontal=True)
            main = result["random"] if model_choice.startswith("Random") else result["fixed"]
            h = result["heterogeneity"]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Jumlah studi", result["k"])
            m2.metric("Pooled effect", f"{main['pooled']:.4f}")
            m3.metric("95% CI", f"{main['ci'][0]:.3f} – {main['ci'][1]:.3f}")
            m4.metric("p-value", f"{main['p']:.4f}")

            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Q", f"{h['Q']:.3f}")
            h2.metric("df", h["df"])
            h3.metric("tau²", f"{h['tau2']:.4f}")
            h4.metric("I²", f"{h['I2']:.1f}%")

            if h["I2"] >= 60:
                st.warning("Heterogenitas tinggi. Pertimbangkan subgroup analysis, moderator, atau sensitivity analysis.")
            elif h["I2"] >= 30:
                st.info("Heterogenitas sedang. Interpretasi pooled effect perlu hati-hati.")
            else:
                st.success("Heterogenitas rendah.")

            st.divider()
            st.write("### Tabel Studi dan Bobot")
            display = []
            for s in result["studies"]:
                display.append({
                    "Study": s.get("study_id", ""),
                    "Year": s.get("year", ""),
                    "Group": s.get("group", ""),
                    "Effect": round(s.get("effect_size", 0), 4),
                    "SE": round(s.get("standard_error", 0), 4),
                    "95% CI": f"{s.get('lower_ci', 0):.3f} – {s.get('upper_ci', 0):.3f}",
                    "Weight FE %": round(s.get("weight_fixed", 0), 2),
                    "Weight RE %": round(s.get("weight_random", 0), 2),
                })
            st.dataframe(display, use_container_width=True, height=360)

            st.write("### Forest Plot Sederhana")
            st.caption("Visualisasi ringan tanpa matplotlib/plotly. Garis menunjukkan 95% CI; titik menunjukkan effect size.")
            for s in result["studies"]:
                yi = s["effect_size"]
                lo = s["lower_ci"]
                hi = s["upper_ci"]
                label = f"{s.get('study_id','Study')} ({s.get('year','')})"
                st.write(f"**{label}**: {yi:.3f} [{lo:.3f}, {hi:.3f}]")
                st.progress(min(1.0, max(0.0, (yi + 2) / 4)))

            st.write(f"**Pooled ({model_choice})**: {main['pooled']:.3f} [{main['ci'][0]:.3f}, {main['ci'][1]:.3f}]")

            st.divider()
            st.write("### Subgroup Analysis")
            subgroup_display = []
            for g, res in subgroup_results.items():
                if res.get("k", 0):
                    rm = res["random"]
                    subgroup_display.append({
                        "Group": g,
                        "k": res["k"],
                        "Pooled RE": round(rm["pooled"], 4),
                        "95% CI": f"{rm['ci'][0]:.3f} – {rm['ci'][1]:.3f}",
                        "I²": f"{res['heterogeneity']['I2']:.1f}%",
                    })
            st.dataframe(subgroup_display, use_container_width=True)

            st.divider()
            report = build_meta_report(result, subgroup_results, model_choice)
            d1, d2 = st.columns(2)
            with d1:
                st.download_button(
                    "📥 Download Data Meta CSV",
                    data=meta_to_csv(result["studies"]),
                    file_name="meta_analysis_data.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with d2:
                st.download_button(
                    "📥 Download Laporan Meta TXT",
                    data=report.encode("utf-8"),
                    file_name="laporan_meta_analysis.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

    with meta_guide_tab:
        st.markdown("""
### Format CSV yang didukung

**1. Generic effect size**
```csv
study_id,year,group,effect_size,standard_error
Smith 2020,2020,Education,0.35,0.12
```

**2. SMD / Hedges g dari dua kelompok**
```csv
study_id,year,group,effect_type,n_t,mean_t,sd_t,n_c,mean_c,sd_c
Study A,2020,Education,smd,45,82.4,10.5,43,77.1,11.2
```

**3. Odds Ratio dari tabel 2x2**
```csv
study_id,effect_type,event_t,non_event_t,event_c,non_event_c
Study A,or,20,30,12,38
```

**4. Risk Ratio**
```csv
study_id,effect_type,event_t,total_t,event_c,total_c
Study A,rr,20,50,12,50
```

**5. Korelasi**
```csv
study_id,effect_type,r,n
Study A,correlation,0.32,120
```

### Output
- Fixed-effect pooled estimate
- Random-effects pooled estimate
- Q statistic
- tau²
- I²
- subgroup analysis
- forest plot sederhana
- ekspor data dan laporan
""")



# =========================
# Automatic Cleaning, Source Selection, and Insight
# =========================
def source_recommendations_for_query(query: str) -> List[str]:
    q = (query or "").lower()
    biomedical_terms = [
        "health", "medical", "medicine", "clinical", "patient", "covid", "disease",
        "therapy", "hospital", "nursing", "biomedical", "pharmacy", "public health"
    ]
    cs_terms = [
        "artificial intelligence", "machine learning", "deep learning", "algorithm",
        "computer", "software", "data mining", "neural", "nlp", "robot"
    ]
    open_access_terms = ["open access", "journal", "publication", "bibliometric"]
    dataset_terms = ["dataset", "data", "repository", "software", "preprint"]

    sources = ["Crossref", "OpenAlex", "Semantic Scholar"]
    if any(t in q for t in biomedical_terms):
        sources += ["PubMed", "Europe PMC"]
    if any(t in q for t in cs_terms):
        sources += ["arXiv"]
    if any(t in q for t in open_access_terms):
        sources += ["DOAJ"]
    if any(t in q for t in dataset_terms):
        sources += ["DataCite"]

    # Add stable broad sources as fallback
    for s in ["PubMed", "DOAJ", "arXiv", "Europe PMC", "DataCite"]:
        if s not in sources:
            sources.append(s)

    return [s for s in sources if s in SOURCE_FUNCTIONS]


def metadata_quality_score(records: List[Dict[str, str]]) -> Dict[str, object]:
    if not records:
        return {"score": 0, "grade": "N/A", "items": []}

    total = len(records)
    checks = {
        "DOI": sum(1 for r in records if r.get("doi")) / total,
        "Tahun": sum(1 for r in records if r.get("year")) / total,
        "Penulis": sum(1 for r in records if r.get("authors")) / total,
        "Jurnal/Sumber": sum(1 for r in records if r.get("journal")) / total,
        "Abstrak": sum(1 for r in records if r.get("abstract")) / total,
        "Keywords": sum(1 for r in records if r.get("keywords")) / total,
    }
    weights = {"DOI": 20, "Tahun": 15, "Penulis": 15, "Jurnal/Sumber": 15, "Abstrak": 20, "Keywords": 15}
    score = sum(checks[k] * weights[k] for k in checks)
    if score >= 85:
        grade = "Sangat baik"
    elif score >= 70:
        grade = "Baik"
    elif score >= 55:
        grade = "Cukup"
    else:
        grade = "Perlu dilengkapi"
    return {
        "score": round(score, 1),
        "grade": grade,
        "items": [(k, round(v * 100, 1)) for k, v in checks.items()],
    }


def generate_automatic_insights(records: List[Dict[str, str]]) -> Dict[str, object]:
    if not records:
        return {"summary": "Belum ada data.", "bullets": [], "actions": []}

    metrics = get_basic_metrics(records)
    years = year_distribution(records)
    authors = author_distribution(records, 10)
    journals = count_by(records, "journal", 10)
    keywords = keyword_distribution(records, 10)
    dbs = count_by(records, "database", 20)
    quality = metadata_quality_score(records)
    coauth = coauthorship_summary(records)

    period = "belum diketahui"
    if years:
        period = f"{min(years.keys())}–{max(years.keys())}"

    top_source = next(iter(dbs.items()), ("Unknown", 0))
    top_author = next(iter(authors.items()), ("Belum ada", 0))
    top_journal = next(iter(journals.items()), ("Belum ada", 0))
    top_keyword = next(iter(keywords.items()), ("Belum ada", 0))

    bullets = [
        f"Dataset berisi {metrics['total']} dokumen dengan rentang publikasi {period}.",
        f"Sumber dominan adalah {top_source[0]} ({top_source[1]} dokumen).",
        f"Penulis paling sering muncul: {top_author[0]} ({top_author[1]} publikasi).",
        f"Jurnal/sumber paling dominan: {top_journal[0]} ({top_journal[1]} publikasi).",
        f"Keyword paling sering muncul: {top_keyword[0]} ({top_keyword[1]} kali).",
        f"Kualitas metadata: {quality['grade']} ({quality['score']}/100).",
        f"Kolaborasi penulis: {metrics['collab_rate']:.1f}% dokumen multi-author; network density {coauth['density']:.3f}.",
    ]

    actions = []
    doi_pct = (metrics["with_doi"] / metrics["total"] * 100) if metrics["total"] else 0
    abs_pct = (metrics["with_abstract"] / metrics["total"] * 100) if metrics["total"] else 0
    kw_pct = (metrics["with_keywords"] / metrics["total"] * 100) if metrics["total"] else 0

    if doi_pct < 70:
        actions.append("Lengkapi DOI agar deduplikasi, citation tracking, dan ekspor bibliografi lebih akurat.")
    if abs_pct < 60:
        actions.append("Tambahkan abstrak untuk memperkuat co-word analysis dan thematic interpretation.")
    if kw_pct < 60:
        actions.append("Lengkapi keyword supaya pemetaan tema dan emerging topic lebih jelas.")
    if metrics["need"] > metrics["total"] * 0.4:
        actions.append("Validasi indeks Scopus/WoS/JCR/SJR karena banyak metadata masih berstatus Needs verification.")
    if len(records) < 100:
        actions.append("Untuk bibliometric analysis yang kuat, kumpulkan lebih banyak data; jurnal menyarankan dataset besar ketika scope kajian luas.")
    if not actions:
        actions.append("Dataset sudah cukup rapi; lanjutkan performance analysis, science mapping, dan interpretasi klaster.")

    return {
        "summary": f"Analisis otomatis menunjukkan dataset {quality['grade'].lower()} dengan fokus utama pada {top_keyword[0]}.",
        "bullets": bullets,
        "actions": actions,
        "quality": quality,
        "source_distribution": dbs,
    }


def render_automatic_insight_panel(records: List[Dict[str, str]]) -> None:
    insight = generate_automatic_insights(records)
    st.write("### 🤖 Insight Otomatis")
    st.success(insight["summary"])

    left, right = st.columns(2)
    with left:
        st.write("**Temuan utama:**")
        for item in insight["bullets"]:
            st.write(f"- {item}")

    with right:
        st.write("**Rekomendasi otomatis:**")
        for item in insight["actions"]:
            st.info(item)

    if "quality" in insight:
        st.write("**Kelengkapan metadata:**")
        qdata = {name: pct for name, pct in insight["quality"]["items"]}
        st.bar_chart(qdata)


def run_sources_automatically(query: str, rows: int, email: str, selected_sources: List[str]) -> tuple[List[Dict[str, str]], List[str], Dict[str, int]]:
    found = []
    errors = []
    counts = {}
    for source in selected_sources:
        try:
            results = SOURCE_FUNCTIONS[source](query, rows, email)
            found += results
            counts[source] = len(results)
        except Exception as exc:
            # Source is skipped automatically, not breaking the whole system.
            errors.append(f"{source}: {str(exc)[:160]}")
            counts[source] = 0
    return found, errors, counts



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

search_tab, upload_tab, manual_tab, data_tab, insights_tab, mapping_tab, method_tab, meta_tab, export_tab, source_tab, guide_tab = st.tabs([
    "🔎 Cari", "⬆️ Upload", "✍️ Manual", "📊 Data", "📈 Insight", "🧭 Science Mapping", "🧪 Metodologi", "🧪 Meta-Analytic", "📤 Ekspor", "🌐 Sumber", "🚀 Panduan"
])

with search_tab:
    st.subheader("🔎 Cari Metadata Bibliografi Otomatis")
    query = st.text_input("Topik/keyword riset", placeholder="Contoh: artificial intelligence education bibliometric")

    auto_mode = st.checkbox("🤖 Mode otomatis: pilih sumber paling relevan dan skip sumber yang gagal", value=True)
    default_sources = ["Crossref", "OpenAlex", "PubMed", "Semantic Scholar", "DOAJ", "arXiv", "Europe PMC", "DataCite"]

    recommended_sources = source_recommendations_for_query(query) if query.strip() else default_sources

    if auto_mode:
        sources = st.multiselect(
            "Sumber yang akan digunakan otomatis",
            list(SOURCE_FUNCTIONS.keys()),
            default=[s for s in recommended_sources if s in SOURCE_FUNCTIONS],
            help="Aplikasi memilih sumber kredibel, menjalankan pencarian, dan melewati sumber yang error/rate limit."
        )
    else:
        sources = st.multiselect(
            "Pilih sumber manual",
            list(SOURCE_FUNCTIONS.keys()),
            default=default_sources,
            help="Semakin banyak sumber dipilih, hasil makin banyak tetapi proses lebih lama."
        )

    with st.expander("Keterangan sumber kredibel"):
        for src, desc in SOURCE_HELP.items():
            st.write(f"**{src}:** {desc}")
        st.warning("Sumber yang sering error/bermasalah seperti CORE API dihapus dari pencarian otomatis. Scopus/WoS tetap melalui upload ekspor resmi.")

    col_search1, col_search2 = st.columns(2)

    with col_search1:
        run_button = st.button("🤖 Cari otomatis & gabungkan", type="primary", use_container_width=True)

    with col_search2:
        if st.button("🧹 Bersihkan/deduplikasi ulang data", use_container_width=True):
            st.session_state.records = standardize(st.session_state.records)
            st.success(f"Data dibersihkan. Total unik: {len(st.session_state.records)}")

    if run_button:
        if not query.strip():
            st.warning("Keyword masih kosong.")
        elif not sources:
            st.warning("Pilih minimal satu sumber.")
        else:
            found = []
            errors = []
            counts = {}

            progress = st.progress(0)
            status_box = st.empty()

            for i, source in enumerate(sources, start=1):
                status_box.info(f"Mengambil data dari {source}...")
                try:
                    results = SOURCE_FUNCTIONS[source](query, rows, email)
                    found += results
                    counts[source] = len(results)
                    st.write(f"✅ {source}: {len(results)} record")
                except Exception as exc:
                    errors.append(f"{source}: {str(exc)[:160]}")
                    counts[source] = 0
                    st.write(f"⏭️ {source}: dilewati otomatis karena gagal/rate limit")
                progress.progress(i / len(sources))

            add_records(found)
            status_box.success(f"Selesai. Data baru terbaca: {len(found)}. Total record unik: {len(st.session_state.records)}")

            if counts:
                st.write("### Ringkasan hasil per sumber")
                st.bar_chart(counts)

            if errors:
                with st.expander("Sumber yang dilewati otomatis"):
                    st.write("Sumber berikut tidak menghentikan aplikasi dan otomatis dilewati:")
                    for e in errors:
                        st.write(f"- {e}")

            if st.session_state.records:
                render_automatic_insight_panel(st.session_state.records)


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
                ["Manual", "Scopus", "Web of Science", "SINTA", "Google Scholar", "Crossref", "OpenAlex", "PubMed", "Semantic Scholar", "DOAJ", "arXiv", "Europe PMC", "DataCite", "Dimensions/Lens", "Lainnya"]
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

        render_automatic_insight_panel(records)

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


with mapping_tab:
    st.subheader("🧭 Science Mapping Lengkap")
    records = st.session_state.records
    if not records:
        st.info("Belum ada data untuk science mapping.")
    else:
        st.write("Science mapping mengikuti toolbox bibliometrik: citation analysis, co-citation, bibliographic coupling, co-word, dan co-authorship.")
        map_tabs = st.tabs(["Citation", "Co-citation", "Bibliographic Coupling", "Co-word", "Co-authorship", "Network Metrics"])
        with map_tabs[0]:
            st.write("### Citation Analysis")
            st.write("Menampilkan publikasi paling berpengaruh berdasarkan global citations jika metadata tersedia.")
            st.dataframe(citation_relationships(records), use_container_width=True)
        with map_tabs[1]:
            st.write("### Co-citation Analysis")
            cc = co_citation_analysis(records)
            if cc["top_references"]:
                st.write("**Referensi paling sering muncul:**")
                st.dataframe([{"Reference": k[:120], "Frequency": v} for k,v in cc["top_references"]], use_container_width=True)
                st.write("**Pasangan referensi yang sering dikutip bersama:**")
                st.dataframe([{"Reference 1": a[:80], "Reference 2": b[:80], "Strength": w} for (a,b),w in cc["co_cited_pairs"]], use_container_width=True)
            else:
                st.info("Co-citation membutuhkan kolom references/cited references dari Scopus/WoS/Crossref.")
        with map_tabs[2]:
            st.write("### Bibliographic Coupling")
            bc = bibliographic_coupling(records)
            if bc:
                st.dataframe(bc, use_container_width=True)
            else:
                st.info("Bibliographic coupling membutuhkan data referensi. Upload CSV/RIS/BibTeX dengan cited references untuk hasil maksimal.")
        with map_tabs[3]:
            st.write("### Co-word Analysis")
            cw = co_word_network(records)
            left, right = st.columns(2)
            with left:
                st.write("**Keyword/term paling sering:**")
                if cw["nodes"]:
                    st.bar_chart(dict(cw["nodes"]))
                else:
                    st.info("Belum ada keyword/abstrak/judul yang cukup.")
            with right:
                st.write("**Pasangan kata/keyword:**")
                st.dataframe([{"Term 1": a, "Term 2": b, "Co-occurrence": w} for (a,b),w in cw["edges"]], use_container_width=True)
        with map_tabs[4]:
            st.write("### Co-authorship Analysis")
            coauth = coauthorship_summary(records)
            c1, c2, c3 = st.columns(3)
            c1.metric("Authors", coauth["num_authors"])
            c2.metric("Collaboration links", coauth["num_collaborations"])
            c3.metric("Density", f"{coauth['density']:.3f}")
            st.write("**Kolaborasi terkuat:**")
            st.dataframe([{"Author 1": a, "Author 2": b, "Strength": w} for (a,b),w in coauth["top_edges"]], use_container_width=True)
        with map_tabs[5]:
            st.write("### Network Metrics")
            st.write("Metrik ringan tanpa NetworkX: degree centrality, weighted degree, dan aproksimasi prestige/eigen.")
            st.dataframe(network_metrics_summary(records), use_container_width=True)

with method_tab:
    st.subheader("🧪 Metodologi Bibliometric Analysis")
    records = st.session_state.records
    st.write("Tab ini dibuat mengikuti alur jurnal Donthu et al. (2021): menentukan aim & scope, memilih teknik, mengumpulkan/membersihkan data, menjalankan analisis, lalu melaporkan temuan.")
    setup_tabs = st.tabs(["Aim & Scope", "Technique Toolbox", "Performance Metrics", "Procedure Checklist", "Limitations"])
    with setup_tabs[0]:
        st.write("### 1. Define aims and scope")
        aim = st.text_area("Tujuan studi bibliometrik", value="Mengidentifikasi perkembangan, aktor utama, jurnal utama, struktur intelektual, dan tema riset terkini pada topik yang dikaji.")
        scope = st.text_area("Scope/kriteria inklusi", value="Artikel jurnal/prosiding relevan, periode tahun tertentu, bersumber dari database kredibel seperti Scopus, WoS, Crossref, OpenAlex, PubMed, Semantic Scholar, DOAJ, arXiv, Europe PMC.")
        keyword_plan = st.text_area("Rencana search string", value='("bibliometric analysis" OR bibliometrics) AND (topic utama)')
        st.download_button("📥 Download rancangan metodologi", data=f"AIM:\n{aim}\n\nSCOPE:\n{scope}\n\nSEARCH STRING:\n{keyword_plan}".encode("utf-8"), file_name="rancangan_metodologi_bibliometrik.txt", mime="text/plain")
    with setup_tabs[1]:
        st.write("### 2. Bibliometric Analysis Technique Toolbox")
        st.markdown("""
| Kategori | Teknik | Output di aplikasi |
|---|---|---|
| Performance analysis | TP, NCA, SA, CA, NAY, PAY, TC, AC, CI, CC, NCP, PCP, CCP, h-index, g-index, i10 | Tab Insight & Performance Metrics |
| Science mapping | Citation analysis | Publikasi paling berpengaruh |
| Science mapping | Co-citation analysis | Fondasi intelektual dari referensi yang sering dikutip bersama |
| Science mapping | Bibliographic coupling | Tema saat ini berdasarkan referensi yang sama |
| Science mapping | Co-word analysis | Tema/topik dari keyword, judul, dan abstrak |
| Science mapping | Co-authorship analysis | Jaringan kolaborasi penulis |
| Enrichment | Network metrics, clustering, visualization | Degree, weighted degree, density, ekspor VOSviewer/CiteSpace |
""")
    with setup_tabs[2]:
        st.write("### Performance Analysis Metrics")
        if records:
            unit = st.selectbox("Unit analisis", ["authors", "journals", "countries", "database"])
            st.dataframe(performance_table(records, unit), use_container_width=True)
            cm = citation_metrics(records)
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("TC", cm["TC"])
            c2.metric("AC", f"{cm['AC']:.2f}")
            c3.metric("h-index", cm["h_index"])
            c4.metric("g-index", cm["g_index"])
            c5.metric("i10", cm["i10"])
        else:
            st.info("Tambahkan data terlebih dahulu.")
    with setup_tabs[3]:
        st.write("### 4-Step Procedure Checklist")
        st.dataframe(methodology_checklist(records), use_container_width=True)
    with setup_tabs[4]:
        st.write("### Limitasi dan validasi")
        st.markdown("""
- Data dari database ilmiah dapat mengandung duplikasi, metadata kosong, atau format referensi yang berbeda.
- Status Scopus/WoS/high impact di aplikasi adalah kandidat berbasis metadata, bukan validasi resmi.
- Co-citation dan bibliographic coupling membutuhkan kolom references/cited references agar akurat.
- Interpretasi cluster tetap perlu dibaca secara substantif, tidak cukup hanya melihat angka.
- Untuk visualisasi lanjutan, ekspor ke VOSviewer, Gephi, Bibliometrix, atau CiteSpace.
""")

with meta_tab:
    render_meta_analysis_tab()

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
            st.download_button(
                "📥 CiteSpace/Plain Text (.txt)",
                data=to_citespace(export_records).encode("utf-8"),
                file_name="citespace_export.txt",
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
- **CORE API**: dihapus dari pencarian otomatis karena sering membutuhkan akses/API key dan dapat memicu error di Streamlit Cloud.
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
