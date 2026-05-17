
from __future__ import annotations

import csv
import io
import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Tuple

import requests
import streamlit as st


APP_TITLE = "Sistem Bibliografi & Meta-Analisis"
COLUMNS = [
    "title", "authors", "year", "journal", "publisher", "doi", "url",
    "database", "impact_factor", "indexing_status", "verification_reason",
    "abstract", "keywords", "notes", "theme_relevance_score"
]

META_EXTRACTION_COLUMNS = [
    "include", "study_id", "authors", "year", "title", "journal", "doi", "group",
    "effect_type", "effect_size", "standard_error",
    "n_t", "mean_t", "sd_t", "n_c", "mean_c", "sd_c",
    "event_t", "total_t", "event_c", "total_c",
    "non_event_t", "non_event_c", "r", "n",
    "outcome", "population", "intervention", "comparison", "notes"
]

SCREENING_COLUMNS = [
    "title", "authors", "year", "journal", "doi", "database",
    "screening_status", "screening_reason", "theme_relevance_score"
]

ROB_COLUMNS = [
    "study_id", "randomization", "blinding", "incomplete_data",
    "selective_reporting", "confounding_control", "sample_size_adequate",
    "overall_risk", "notes"
]

HIGH_IMPACT_HINTS = [
    "nature", "science", "cell", "lancet", "jama", "new england journal",
    "ieee transactions", "acm transactions", "acm computing surveys",
    "review of educational research", "springer nature", "elsevier",
    "wiley", "taylor & francis", "sage", "oxford university press",
    "cambridge university press", "mit press", "bmj", "annual reviews"
]
SCOPUS_HINTS = ["scopus", "elsevier", "eid", "source-id", "source id", "citescore", "sciencedirect"]
WOS_HINTS = ["web of science", "wos", "clarivate", "sci-expanded", "ssci", "ahci", "esci", "jcr", "isi"]

SOURCE_HELP = {
    "Crossref": "Metadata DOI lintas publisher akademik.",
    "OpenAlex": "Database open bibliographic besar untuk karya ilmiah.",
    "PubMed": "Literatur biomedis dari NCBI/NLM.",
    "Semantic Scholar": "Metadata paper dari Allen Institute for AI.",
    "DOAJ": "Directory of Open Access Journals.",
    "arXiv": "Preprint kredibel untuk CS, matematika, fisika, statistik, dan bidang terkait.",
    "Europe PMC": "Literatur biomedis dan life sciences.",
    "DataCite": "Metadata DOI untuk dataset, report, preprint, software, dan output riset lain.",
    "PLOS": "Open-access journal articles from the PLOS public search API.",
    "OpenAIRE": "Open European scholarly communication graph for publications and research outputs.",
}


# =========================================================
# Basic utilities
# =========================================================
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


def safe_float(value, default=None):
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def doi_from_text(text: str) -> str:
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", clean(text), re.I)
    return match.group(0).strip(".,;) ").lower() if match else ""


def year_from_text(text: object) -> str:
    match = re.search(r"(?:19|20)\d{2}", clean(text))
    return match.group(0) if match else clean(text)


def authors_to_text(authors: object) -> str:
    if isinstance(authors, list):
        names = []
        for a in authors:
            if isinstance(a, dict):
                names.append(clean(a.get("name") or a.get("display_name") or a.get("full_name") or ""))
            else:
                names.append(clean(a))
        return "; ".join(a for a in names if a)
    text = clean(authors)
    text = re.sub(r"\s+and\s+", "; ", text, flags=re.I)
    return text.replace("|", ";")


def classify(row: Dict[str, str]) -> Tuple[str, str]:
    joined = " ".join(row.get(k, "") for k in ["journal", "publisher", "database", "notes", "url", "keywords"]).lower()
    tags, reasons = [], []

    if any(h in joined for h in SCOPUS_HINTS):
        tags.append("Scopus candidate")
        reasons.append("metadata mengandung indikator Scopus/Elsevier/CiteScore")

    if any(h in joined for h in WOS_HINTS):
        tags.append("Web of Science candidate")
        reasons.append("metadata mengandung indikator WoS/Clarivate/JCR/SCI/SSCI/AHCI/ESCI")

    if any(h in joined for h in HIGH_IMPACT_HINTS):
        tags.append("High-impact candidate")
        reasons.append("nama jurnal/publisher terdeteksi sebagai kandidat bereputasi tinggi")

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
    output, seen = [], set()
    for raw in records:
        title = first(raw, ["title", "article title", "document title", "judul", "dc:title", "ti", "name"])
        doi = doi_from_text(first(raw, ["doi", "prism:doi", "di", "url", "link", "DOI", "externalids"]))
        journal = first(raw, ["journal", "source title", "publication name", "container title", "source", "booktitle", "so", "venue"])

        row = {
            "title": title,
            "authors": authors_to_text(first(raw, ["authors", "author", "creators", "penulis", "dc:creator", "au", "authorstring"])),
            "year": year_from_text(first(raw, ["year", "publication year", "published year", "cover date", "date", "publication date", "py", "published", "published_date"])),
            "journal": journal,
            "publisher": first(raw, ["publisher", "publisher name", "host organization name"]),
            "doi": doi,
            "url": first(raw, ["url", "link", "links", "record url"]),
            "database": first(raw, ["database", "source database", "index", "web of science index"]),
            "impact_factor": first(raw, ["impact factor", "impact_factor", "jif", "citescore", "sjr"]),
            "abstract": first(raw, ["abstract", "description", "ab"]),
            "keywords": first(raw, ["keywords", "author keywords", "index keywords", "keyword", "de"]),
            "notes": first(raw, ["notes", "eid", "ut", "accession number", "document type", "type"]),
            "theme_relevance_score": first(raw, ["theme_relevance_score", "relevance", "score"]),
        }

        if not row["title"] and not row["doi"]:
            continue

        row["indexing_status"], row["verification_reason"] = classify(row)
        key = row["doi"] or re.sub(r"\W+", " ", (row["title"] + row["journal"] + row["year"]).lower()).strip()

        if key and key not in seen:
            seen.add(key)
            output.append({col: row.get(col, "") for col in COLUMNS})

    return output


def safe_csv(rows: List[Dict[str, object]], fieldnames: List[str]) -> bytes:
    buf = io.StringIO()
    extra = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames and key not in extra:
                extra.append(key)
    final_fields = fieldnames + extra
    writer = csv.DictWriter(buf, fieldnames=final_fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in final_fields})
    return buf.getvalue().encode("utf-8-sig")


# =========================================================
# File parsers
# =========================================================
def parse_csv_bytes(data: bytes) -> List[Dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return standardize(list(csv.DictReader(io.StringIO(text), dialect=dialect)))


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
    records, current = [], {}
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
        old = clean(current.get(field, ""))
        current[field] = old + ("; " if old else "") + value
    if current:
        records.append(current)
    return standardize(records)


# =========================================================
# Search sources
# =========================================================
def search_crossref(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    headers = {"User-Agent": f"BibliografiMeta/1.0 (mailto:{email or 'example@example.com'})"}
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
        authors = [clean((a.get("given", "") + " " + a.get("family", "")).strip()) for a in item.get("author", []) or []]
        records.append({
            "title": (item.get("title") or [""])[0],
            "authors": [a for a in authors if a],
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
        doi = item.get("doi", "")
        doi = doi.replace("https://doi.org/", "") if isinstance(doi, str) else ""
        records.append({
            "title": item.get("title", ""),
            "authors": [a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])],
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
    params = {"db": "pubmed", "term": query, "retmax": min(rows, 100), "retmode": "json", "sort": "relevance"}
    if email:
        params["email"] = email
    s = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params=params, timeout=25)
    s.raise_for_status()
    ids = s.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    params2 = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
    if email:
        params2["email"] = email
    r = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", params=params2, timeout=25)
    r.raise_for_status()

    result = r.json().get("result", {})
    records = []
    for pmid in result.get("uids", []):
        item = result.get(pmid, {})
        doi = ""
        for aid in item.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
                break
        records.append({
            "title": item.get("title", ""),
            "authors": [a.get("name", "") for a in item.get("authors", [])],
            "year": year_from_text(item.get("pubdate", "")),
            "journal": item.get("fulljournalname", "") or item.get("source", ""),
            "publisher": "NCBI/NLM",
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "database": "PubMed",
            "notes": "; ".join(item.get("pubtype", [])) if isinstance(item.get("pubtype"), list) else item.get("pubtype", ""),
        })
    return standardize(records)


def search_semantic_scholar(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    params = {
        "query": query,
        "limit": min(rows, 100),
        "fields": "title,authors,year,venue,publicationVenue,externalIds,url,abstract,fieldsOfStudy,publicationTypes"
    }
    r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search", params=params, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("data", []):
        ext = item.get("externalIds") or {}
        venue = item.get("publicationVenue") or {}
        records.append({
            "title": item.get("title", ""),
            "authors": [a.get("name", "") for a in item.get("authors", [])],
            "year": item.get("year", ""),
            "journal": venue.get("name", "") or item.get("venue", ""),
            "publisher": "Semantic Scholar / AI2",
            "doi": ext.get("DOI", ""),
            "url": item.get("url", ""),
            "database": "Semantic Scholar",
            "abstract": item.get("abstract", ""),
            "keywords": "; ".join(item.get("fieldsOfStudy") or []),
            "notes": "; ".join(item.get("publicationTypes") or []),
        })
    return standardize(records)


def search_doaj(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    url = f"https://doaj.org/api/search/articles/{requests.utils.quote(query)}"
    r = requests.get(url, params={"pageSize": min(rows, 100)}, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("results", []):
        bib = item.get("bibjson", {})
        journal = bib.get("journal", {}) or {}
        doi = ""
        for ident in bib.get("identifier", []) or []:
            if ident.get("type", "").lower() == "doi":
                doi = ident.get("id", "")
                break
        links = bib.get("link", []) or []
        url_value = ""
        for link in links:
            if isinstance(link, dict) and link.get("url"):
                url_value = link.get("url")
                break
        records.append({
            "title": bib.get("title", ""),
            "authors": [a.get("name", "") for a in bib.get("author", [])],
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
    params = {"search_query": f"all:{query}", "start": 0, "max_results": min(rows, 100), "sortBy": "relevance", "sortOrder": "descending"}
    r = requests.get("https://export.arxiv.org/api/query", params=params, timeout=25)
    r.raise_for_status()

    root = ET.fromstring(r.content)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    records = []
    for entry in root.findall("atom:entry", ns):
        authors = [a.findtext("atom:name", default="", namespaces=ns) for a in entry.findall("atom:author", ns)]
        categories = [cat.attrib.get("term", "") for cat in entry.findall("atom:category", ns)]
        records.append({
            "title": clean(entry.findtext("atom:title", default="", namespaces=ns)),
            "authors": authors,
            "year": year_from_text(entry.findtext("atom:published", default="", namespaces=ns)),
            "journal": entry.findtext("arxiv:journal_ref", default="", namespaces=ns) or "arXiv",
            "publisher": "arXiv",
            "doi": entry.findtext("arxiv:doi", default="", namespaces=ns),
            "url": entry.findtext("atom:id", default="", namespaces=ns),
            "database": "arXiv",
            "abstract": clean(entry.findtext("atom:summary", default="", namespaces=ns)),
            "keywords": "; ".join(categories),
            "notes": "Preprint",
        })
    return standardize(records)


def search_europe_pmc(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    params = {"query": query, "pageSize": min(rows, 100), "format": "json", "resultType": "core"}
    r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params=params, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("resultList", {}).get("result", []):
        full_urls = item.get("fullTextUrlList", {}).get("fullTextUrl", []) if item.get("fullTextUrlList") else []
        records.append({
            "title": item.get("title", ""),
            "authors": item.get("authorString", ""),
            "year": item.get("pubYear", ""),
            "journal": item.get("journalTitle", ""),
            "publisher": "Europe PMC",
            "doi": item.get("doi", ""),
            "url": full_urls[0].get("url", "") if full_urls else "",
            "database": "Europe PMC",
            "abstract": item.get("abstractText", ""),
            "keywords": clean(item.get("meshHeadingList", "")),
            "notes": item.get("pubType", ""),
        })
    return standardize(records)


def search_datacite(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    params = {"query": query, "page[size]": min(rows, 100)}
    r = requests.get("https://api.datacite.org/dois", params=params, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("data", []):
        a = item.get("attributes", {})
        titles = a.get("titles", []) or []
        creators = a.get("creators", []) or []
        descriptions = a.get("descriptions", []) or []
        subjects = a.get("subjects", []) or []
        records.append({
            "title": titles[0].get("title", "") if titles else "",
            "authors": [c.get("name", "") for c in creators],
            "year": a.get("publicationYear", ""),
            "journal": a.get("container", {}).get("title", "") if isinstance(a.get("container"), dict) else "",
            "publisher": a.get("publisher", ""),
            "doi": a.get("doi", ""),
            "url": a.get("url", ""),
            "database": "DataCite",
            "abstract": descriptions[0].get("description", "") if descriptions else "",
            "keywords": "; ".join(s.get("subject", "") for s in subjects[:8]),
            "notes": a.get("types", {}).get("resourceTypeGeneral", "") if isinstance(a.get("types"), dict) else "",
        })
    return standardize(records)


def search_plos(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    """Search PLOS public API. Useful for open-access empirical studies."""
    params = {
        "q": f'title:"{query}" OR abstract:"{query}" OR everything:"{query}"',
        "rows": min(rows, 100),
        "wt": "json",
        "fl": "id,title,author,journal,publication_date,abstract,subject"
    }
    r = requests.get("https://api.plos.org/search", params=params, timeout=25)
    r.raise_for_status()

    records = []
    for item in r.json().get("response", {}).get("docs", []):
        authors = item.get("author", [])
        if isinstance(authors, str):
            authors = [authors]
        abstract = item.get("abstract", "")
        if isinstance(abstract, list):
            abstract = " ".join(abstract)
        subjects = item.get("subject", [])
        if isinstance(subjects, str):
            subjects = [subjects]

        doi = item.get("id", "")
        records.append({
            "title": item.get("title", ""),
            "authors": authors,
            "year": year_from_text(item.get("publication_date", "")),
            "journal": item.get("journal", ""),
            "publisher": "PLOS",
            "doi": doi.replace("doi:", ""),
            "url": f"https://doi.org/{doi.replace('doi:', '')}" if doi else "",
            "database": "PLOS",
            "abstract": abstract,
            "keywords": "; ".join(subjects[:8]),
            "notes": "Open access PLOS API",
        })
    return standardize(records)

def search_openaire(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    """OpenAIRE publication search. Useful as an additional open scholarly source."""
    params = {
        "keywords": query,
        "format": "json",
        "size": min(rows, 100),
    }
    r = requests.get("https://api.openaire.eu/search/publications", params=params, timeout=25)
    r.raise_for_status()

    data = r.json()
    results = data.get("response", {}).get("results", {}).get("result", [])
    if isinstance(results, dict):
        results = [results]

    records = []
    for item in results:
        md = item.get("metadata", {}).get("oaf:entity", {}).get("oaf:result", {})
        title = ""
        titles = md.get("title", [])
        if isinstance(titles, dict):
            title = titles.get("$", "")
        elif isinstance(titles, list) and titles:
            title = titles[0].get("$", "") if isinstance(titles[0], dict) else str(titles[0])

        creators = md.get("creator", [])
        if isinstance(creators, dict):
            creators = [creators]
        authors = []
        for c in creators or []:
            if isinstance(c, dict):
                authors.append(c.get("$", ""))
            else:
                authors.append(str(c))

        journal = ""
        source = md.get("journal", "")
        if isinstance(source, dict):
            journal = source.get("$", "")
        elif isinstance(source, str):
            journal = source

        date = md.get("dateofacceptance", "") or md.get("dateofcollection", "")
        doi = ""
        pids = md.get("pid", [])
        if isinstance(pids, dict):
            pids = [pids]
        for p in pids or []:
            if isinstance(p, dict) and clean(p.get("@classid", "")).lower() == "doi":
                doi = clean(p.get("$", ""))
                break

        records.append({
            "title": title,
            "authors": authors,
            "year": year_from_text(date),
            "journal": journal,
            "publisher": "OpenAIRE",
            "doi": doi,
            "url": "",
            "database": "OpenAIRE",
            "abstract": "",
            "keywords": "",
            "notes": "OpenAIRE API",
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
    "PLOS": search_plos,
    "OpenAIRE": search_openaire,
}


# =========================================================
# Enhanced Sources + Automatic Deduplication
# =========================================================
def normalize_doi(value: str) -> str:
    text = clean(value).lower()
    text = text.replace("https://doi.org/", "").replace("http://doi.org/", "").replace("doi:", "")
    m = re.search(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", text, flags=re.I)
    return m.group(0).rstrip(".,;) ") if m else text.strip()


def normalize_title_for_dedup(title: str) -> str:
    text = clean(title).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\b(the|a|an|and|or|of|in|on|for|with|to|by|from|study|review|analysis)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def first_author_key(authors: str) -> str:
    first_author = clean(authors).split(";")[0].strip().lower()
    first_author = re.sub(r"[^a-z0-9\s]", " ", first_author)
    return re.sub(r"\s+", " ", first_author).strip()


def merge_record_values(old: Dict[str, str], new: Dict[str, str]) -> Dict[str, str]:
    merged = dict(old)
    for col in COLUMNS:
        ov = clean(merged.get(col, ""))
        nv = clean(new.get(col, ""))

        if col == "database":
            vals = []
            for val in re.split(r";|,", ov + ";" + nv):
                val = clean(val)
                if val and val not in vals:
                    vals.append(val)
            merged[col] = "; ".join(vals)
        elif col in ["abstract", "keywords", "notes", "verification_reason"]:
            if len(nv) > len(ov):
                merged[col] = nv
            elif not ov:
                merged[col] = nv
        elif col == "indexing_status":
            vals = []
            for val in re.split(r";|,", ov + ";" + nv):
                val = clean(val)
                if val and val not in vals:
                    vals.append(val)
            merged[col] = "; ".join(vals)
        elif not ov and nv:
            merged[col] = nv
        elif nv and len(nv) > len(ov) and col in ["title", "journal", "publisher", "url"]:
            merged[col] = nv

    merged["indexing_status"], merged["verification_reason"] = classify(merged)
    return {col: merged.get(col, "") for col in COLUMNS}


def enhanced_deduplicate_records(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Deduplicate automatically by DOI, normalized title, and title/year/first-author similarity."""
    cleaned = []
    for r in records:
        row = {col: clean(r.get(col, "")) for col in COLUMNS}
        if not row["title"] and not row["doi"]:
            continue
        row["doi"] = normalize_doi(row.get("doi", ""))
        row["indexing_status"], row["verification_reason"] = classify(row)
        cleaned.append(row)

    by_key: Dict[str, Dict[str, str]] = {}
    no_strong_key = []

    for r in cleaned:
        doi = normalize_doi(r.get("doi", ""))
        title_norm = normalize_title_for_dedup(r.get("title", ""))

        if doi and doi.startswith("10."):
            key = "doi:" + doi
        elif title_norm:
            key = "title:" + title_norm
        else:
            key = ""

        if key:
            if key in by_key:
                by_key[key] = merge_record_values(by_key[key], r)
            else:
                by_key[key] = r
        else:
            no_strong_key.append(r)

    result = list(by_key.values()) + no_strong_key

    # Fuzzy merge for records without DOI or with slightly different titles.
    final = []
    import difflib
    for r in result:
        r_title = normalize_title_for_dedup(r.get("title", ""))
        r_year = clean(r.get("year", ""))
        r_author = first_author_key(r.get("authors", ""))
        merged = False

        for i, existing in enumerate(final):
            e_title = normalize_title_for_dedup(existing.get("title", ""))
            e_year = clean(existing.get("year", ""))
            e_author = first_author_key(existing.get("authors", ""))

            if not r_title or not e_title:
                continue

            same_year = bool(r_year and e_year and r_year == e_year)
            same_author = bool(r_author and e_author and (r_author == e_author or r_author.split(" ")[-1:] == e_author.split(" ")[-1:]))
            sim = difflib.SequenceMatcher(None, r_title, e_title).ratio()

            if sim >= 0.94 or (sim >= 0.88 and same_year and same_author):
                final[i] = merge_record_values(existing, r)
                merged = True
                break

        if not merged:
            final.append(r)

    return final


def deduplicate_session_records() -> Tuple[int, int]:
    before = len(st.session_state.get("records", []))
    st.session_state.records = enhanced_deduplicate_records(st.session_state.get("records", []))
    after = len(st.session_state.records)

    if st.session_state.get("theme_records"):
        st.session_state.theme_records = enhanced_deduplicate_records(st.session_state.theme_records)

    return before, after




def search_openlibrary_noop(query: str, rows: int, email: str) -> List[Dict[str, str]]:
    # Placeholder intentionally returns no records; kept out of active SOURCE_FUNCTIONS.
    return []


def render_deduplication_panel():
    st.subheader("🧹 Deduplikasi Otomatis")
    records = st.session_state.get("records", [])
    theme_records = st.session_state.get("theme_records", [])

    c1, c2, c3 = st.columns(3)
    c1.metric("Total records", len(records))
    c2.metric("Theme records", len(theme_records))
    c3.metric("DOI tersedia", sum(1 for r in records if clean(r.get("doi", ""))))

    st.caption("Deduplikasi otomatis memakai DOI, normalisasi judul, tahun, dan author pertama. Metadata dari duplikat akan digabung.")

    if st.button("🧹 Jalankan Deduplikasi Sekarang", use_container_width=True):
        before, after = deduplicate_session_records()
        st.success(f"Deduplikasi selesai: {before} → {after} records. Duplikasi terhapus/tergabung: {before - after}.")

# =========================================================
# Bibliography analysis & relevance
# =========================================================
def keyword_tokens(theme: str) -> List[str]:
    stopwords = {
        "the", "and", "or", "of", "in", "on", "for", "to", "a", "an", "with", "by",
        "dan", "atau", "yang", "di", "ke", "dari", "untuk", "dengan", "pada", "dalam",
        "analysis", "analisis", "bibliometric", "bibliografi", "meta", "study", "research"
    }
    return [t for t in re.findall(r"[A-Za-zÀ-ÿ0-9]+", theme.lower()) if len(t) >= 3 and t not in stopwords]


def relevance_score(record: Dict[str, str], theme: str) -> float:
    tokens = keyword_tokens(theme)
    if not tokens:
        return 0.0
    title = record.get("title", "").lower()
    abstract = record.get("abstract", "").lower()
    keywords = record.get("keywords", "").lower()
    journal = record.get("journal", "").lower()
    score = 0.0
    for token in tokens:
        if token in title:
            score += 3.0
        if token in keywords:
            score += 2.0
        if token in abstract:
            score += 1.5
        if token in journal:
            score += 0.5
    phrase = theme.lower().strip()
    if phrase and phrase in title:
        score += 5
    if phrase and phrase in abstract:
        score += 3
    return score


def filter_relevant(records: List[Dict[str, str]], theme: str, min_score: float) -> List[Dict[str, str]]:
    out = []
    for r in records:
        score = relevance_score(r, theme)
        if score >= min_score:
            rr = dict(r)
            rr["theme_relevance_score"] = f"{score:.2f}"
            out.append(rr)
    return sorted(out, key=lambda x: safe_float(x.get("theme_relevance_score"), 0), reverse=True)


def select_sources(theme: str) -> List[str]:
    text = theme.lower()
    sources = ["Crossref", "OpenAlex", "Semantic Scholar", "PLOS", "OpenAIRE", "DOAJ", "DataCite"]
    if any(t in text for t in ["health", "medical", "clinical", "patient", "disease", "biomedical", "nursing", "public health", "kesehatan", "medis", "pasien"]):
        sources += ["PubMed", "Europe PMC"]
    if any(t in text for t in ["computer", "machine learning", "artificial intelligence", "ai", "deep learning", "algorithm", "software", "physics", "mathematics", "statistics", "quantum"]):
        sources += ["arXiv"]
    return list(dict.fromkeys([s for s in sources if s in SOURCE_FUNCTIONS]))


def add_records(records: List[Dict[str, str]]) -> None:
    existing = st.session_state.get("records", [])
    st.session_state.records = enhanced_deduplicate_records(standardize(existing + records))


def get_metrics(records: List[Dict[str, str]]) -> Dict[str, float]:
    total = len(records)
    authors = []
    multi = 0
    for r in records:
        names = [a.strip() for a in r.get("authors", "").split(";") if a.strip()]
        authors.extend(names)
        if len(names) > 1:
            multi += 1
    return {
        "total": total,
        "with_doi": sum(1 for r in records if r.get("doi")),
        "with_abstract": sum(1 for r in records if r.get("abstract")),
        "with_keywords": sum(1 for r in records if r.get("keywords")),
        "scopus": sum(1 for r in records if "Scopus" in r.get("indexing_status", "")),
        "wos": sum(1 for r in records if "Web of Science" in r.get("indexing_status", "")),
        "high": sum(1 for r in records if "High" in r.get("indexing_status", "")),
        "need": sum(1 for r in records if r.get("indexing_status") == "Needs verification"),
        "authors_unique": len(set(authors)),
        "avg_authors": len(authors) / total if total else 0,
        "collab_rate": multi / total * 100 if total else 0,
    }


def count_by(records: List[Dict[str, str]], field: str, limit: int = 15) -> Dict[str, int]:
    c = Counter()
    for r in records:
        val = clean(r.get(field, "")) or "Unknown"
        if len(val) > 45:
            val = val[:45] + "..."
        c[val] += 1
    return dict(c.most_common(limit))


def year_distribution(records: List[Dict[str, str]]) -> Dict[str, int]:
    c = Counter()
    for r in records:
        y = r.get("year", "")
        if y and str(y).isdigit():
            c[str(y)] += 1
    return dict(sorted(c.items()))


def author_distribution(records: List[Dict[str, str]], limit: int = 15) -> Dict[str, int]:
    c = Counter()
    for r in records:
        for a in [x.strip() for x in r.get("authors", "").split(";") if x.strip()]:
            c[a] += 1
    return dict(c.most_common(limit))


def keyword_distribution(records: List[Dict[str, str]], limit: int = 20) -> Dict[str, int]:
    c = Counter()
    for r in records:
        for kw in re.split(r";|,", r.get("keywords", "")):
            kw = clean(kw).lower()
            if kw:
                c[kw] += 1
    return dict(c.most_common(limit))


# =========================================================
# Screening, PRISMA, Risk of Bias
# =========================================================
def auto_screen(records: List[Dict[str, str]], criteria: Dict[str, object]) -> List[Dict[str, str]]:
    screened = []
    for r in records:
        reasons, status = [], "Included"
        year = safe_float(r.get("year"), None)
        min_year = criteria.get("min_year")
        max_year = criteria.get("max_year")

        if min_year and year and year < min_year:
            status = "Excluded"
            reasons.append(f"tahun < {int(min_year)}")
        if max_year and year and year > max_year:
            status = "Excluded"
            reasons.append(f"tahun > {int(max_year)}")
        if criteria.get("only_doi") and not r.get("doi"):
            status = "Excluded"
            reasons.append("DOI kosong")
        if criteria.get("only_indexed") and r.get("indexing_status") == "Needs verification":
            status = "Maybe" if status != "Excluded" else status
            reasons.append("indeks perlu verifikasi")
        if criteria.get("must_have_abstract") and not r.get("abstract"):
            status = "Maybe" if status != "Excluded" else status
            reasons.append("abstrak kosong")

        include_terms = [t.strip().lower() for t in criteria.get("include_terms", "").split(",") if t.strip()]
        exclude_terms = [t.strip().lower() for t in criteria.get("exclude_terms", "").split(",") if t.strip()]
        joined = json.dumps(r, ensure_ascii=False).lower()

        if include_terms and not any(t in joined for t in include_terms):
            status = "Maybe" if status != "Excluded" else status
            reasons.append("belum jelas memenuhi kata kunci inklusi")
        if exclude_terms and any(t in joined for t in exclude_terms):
            status = "Excluded"
            reasons.append("mengandung kata kunci eksklusi")

        row = {col: r.get(col, "") for col in SCREENING_COLUMNS}
        row["screening_status"] = status
        row["screening_reason"] = "; ".join(reasons) if reasons else "memenuhi kriteria awal"
        screened.append(row)
    return screened


def prisma_counts(found_total: int, unique_records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, str]]) -> Dict[str, int]:
    included = sum(1 for r in screened if r.get("screening_status") == "Included")
    maybe = sum(1 for r in screened if r.get("screening_status") == "Maybe")
    excluded = sum(1 for r in screened if r.get("screening_status") == "Excluded")
    return {
        "records_identified": found_total,
        "records_after_duplicates": len(unique_records),
        "records_screened": len(screened),
        "records_excluded": excluded,
        "full_text_assessed": included + maybe,
        "studies_included_review": included,
        "studies_included_meta": len(meta_studies),
    }


def build_rob_from_meta(studies: List[Dict[str, str]]) -> List[Dict[str, str]]:
    rows = []
    for s in studies:
        rows.append({
            "study_id": s.get("study_id", ""),
            "randomization": "Unclear",
            "blinding": "Unclear",
            "incomplete_data": "Unclear",
            "selective_reporting": "Unclear",
            "confounding_control": "Unclear",
            "sample_size_adequate": "Unclear",
            "overall_risk": "Unclear",
            "notes": "Isi manual berdasarkan full-text."
        })
    return rows


def score_rob(row: Dict[str, str]) -> str:
    fields = ["randomization", "blinding", "incomplete_data", "selective_reporting", "confounding_control", "sample_size_adequate"]
    vals = [clean(row.get(f, "Unclear")).lower() for f in fields]
    high = sum(1 for v in vals if "high" in v or "tidak" in v or "no" == v)
    low = sum(1 for v in vals if "low" in v or "ya" in v or "yes" == v)
    if high >= 2:
        return "High risk"
    if low >= 4 and high == 0:
        return "Low risk"
    return "Moderate/Unclear risk"


# =========================================================
# Meta-analysis
# =========================================================
def compute_smd(n_t, mean_t, sd_t, n_c, mean_c, sd_c):
    n_t, mean_t, sd_t = safe_float(n_t), safe_float(mean_t), safe_float(sd_t)
    n_c, mean_c, sd_c = safe_float(n_c), safe_float(mean_c), safe_float(sd_c)
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


def compute_log_or(event_t, non_event_t, event_c, non_event_c):
    a, b, c, d = safe_float(event_t), safe_float(non_event_t), safe_float(event_c), safe_float(non_event_c)
    if not all(v is not None for v in [a, b, c, d]):
        return None, None
    if min(a, b, c, d) == 0:
        a += 0.5; b += 0.5; c += 0.5; d += 0.5
    if min(a, b, c, d) <= 0:
        return None, None
    return math.log((a * d) / (b * c)), math.sqrt(1/a + 1/b + 1/c + 1/d)


def compute_log_rr(event_t, total_t, event_c, total_c):
    event_t, total_t, event_c, total_c = safe_float(event_t), safe_float(total_t), safe_float(event_c), safe_float(total_c)
    if not all(v is not None for v in [event_t, total_t, event_c, total_c]):
        return None, None
    non_t, non_c = total_t - event_t, total_c - event_c
    if min(event_t, non_t, event_c, non_c) == 0:
        event_t += 0.5; non_t += 0.5; event_c += 0.5; non_c += 0.5
        total_t, total_c = event_t + non_t, event_c + non_c
    if min(event_t, event_c, total_t, total_c) <= 0:
        return None, None
    return math.log((event_t / total_t) / (event_c / total_c)), math.sqrt((1/event_t) - (1/total_t) + (1/event_c) - (1/total_c))


def compute_fisher_z(r, n):
    r, n = safe_float(r), safe_float(n)
    if r is None or n is None or n <= 3 or r <= -1 or r >= 1:
        return None, None
    return 0.5 * math.log((1 + r) / (1 - r)), math.sqrt(1 / (n - 3))


def bibliographic_to_meta_format(records: List[Dict[str, str]], theme: str) -> List[Dict[str, str]]:
    rows = []
    for i, r in enumerate(records, 1):
        first_author = clean(r.get("authors", "")).split(";")[0].strip()
        rows.append({
            "include": "yes",
            "study_id": f"{first_author} {r.get('year', '')}".strip() or f"Study {i}",
            "authors": r.get("authors", ""),
            "year": r.get("year", ""),
            "title": r.get("title", ""),
            "journal": r.get("journal", ""),
            "doi": r.get("doi", ""),
            "group": theme or "Overall",
            "effect_type": "",
            "effect_size": "",
            "standard_error": "",
            "n_t": "", "mean_t": "", "sd_t": "", "n_c": "", "mean_c": "", "sd_c": "",
            "event_t": "", "total_t": "", "event_c": "", "total_c": "",
            "non_event_t": "", "non_event_c": "", "r": "", "n": "",
            "outcome": theme,
            "population": "",
            "intervention": "",
            "comparison": "",
            "notes": "Isi effect size/SE dari full-text atau isi data mentah sesuai effect_type."
        })
    return rows


def parse_meta_csv(data: bytes) -> Tuple[List[Dict[str, object]], int]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    studies, skipped = [], 0

    for i, row in enumerate(rows, 1):
        lower = {str(k).strip().lower(): v for k, v in row.items()}
        include = clean(lower.get("include", "yes")).lower()
        if include in ["no", "n", "0", "false", "exclude", "tidak"]:
            continue

        study_id = clean(lower.get("study_id") or lower.get("study") or lower.get("title") or f"Study {i}")
        year = year_from_text(lower.get("year", ""))
        group = clean(lower.get("group") or lower.get("subgroup") or "Overall") or "Overall"
        effect_type = clean(lower.get("effect_type") or lower.get("type") or "").lower()
        notes = clean(lower.get("notes") or "")

        yi = safe_float(lower.get("effect_size") or lower.get("yi") or lower.get("effect") or lower.get("g") or lower.get("d") or lower.get("logor") or lower.get("logrr") or lower.get("z"))
        se = safe_float(lower.get("standard_error") or lower.get("se") or lower.get("sei"))
        vi = safe_float(lower.get("variance") or lower.get("var") or lower.get("vi"))

        if yi is None or (se is None and vi is None):
            if effect_type in ["smd", "hedges", "hedges_g", "cohen_d", "d", "g"] or clean(lower.get("mean_t")):
                yi, se = compute_smd(lower.get("n_t"), lower.get("mean_t"), lower.get("sd_t"), lower.get("n_c"), lower.get("mean_c"), lower.get("sd_c"))
                effect_type = "SMD/Hedges g"
            elif effect_type in ["or", "log_or", "odds_ratio", "logor"] or clean(lower.get("non_event_t")):
                yi, se = compute_log_or(lower.get("event_t"), lower.get("non_event_t"), lower.get("event_c"), lower.get("non_event_c"))
                effect_type = "log(OR)"
            elif effect_type in ["rr", "risk_ratio", "log_rr", "logrr"] or (clean(lower.get("total_t")) and clean(lower.get("total_c"))):
                yi, se = compute_log_rr(lower.get("event_t"), lower.get("total_t"), lower.get("event_c"), lower.get("total_c"))
                effect_type = "log(RR)"
            elif effect_type in ["correlation", "r", "fisher_z"] or clean(lower.get("r")):
                yi, se = compute_fisher_z(lower.get("r"), lower.get("n"))
                effect_type = "Fisher z"

        if se is None and vi is not None and vi > 0:
            se = math.sqrt(vi)

        if yi is None or se is None or se <= 0:
            skipped += 1
            continue

        studies.append({
            "study_id": study_id,
            "year": year,
            "group": group,
            "effect_type": effect_type or "Generic",
            "effect_size": yi,
            "standard_error": se,
            "variance": se ** 2,
            "notes": notes,
        })

    return studies, skipped


def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def run_meta(studies: List[Dict[str, object]]) -> Dict[str, object]:
    valid = []
    for s in studies:
        yi, se = safe_float(s.get("effect_size")), safe_float(s.get("standard_error"))
        if yi is not None and se is not None and se > 0:
            valid.append({**s, "effect_size": yi, "standard_error": se, "variance": se ** 2})

    k = len(valid)
    if k == 0:
        return {"k": 0, "studies": []}

    wf = [1 / s["variance"] for s in valid]
    swf = sum(wf)
    pooled_fe = sum(w * s["effect_size"] for w, s in zip(wf, valid)) / swf
    se_fe = math.sqrt(1 / swf)
    ci_fe = (pooled_fe - 1.96 * se_fe, pooled_fe + 1.96 * se_fe)
    z_fe = pooled_fe / se_fe
    p_fe = 2 * (1 - normal_cdf(abs(z_fe)))

    q = sum(w * (s["effect_size"] - pooled_fe) ** 2 for w, s in zip(wf, valid))
    df = k - 1
    c_val = swf - (sum(w ** 2 for w in wf) / swf) if swf else 0
    tau2 = max(0, (q - df) / c_val) if c_val > 0 and k > 1 else 0
    i2 = max(0, (q - df) / q * 100) if q > 0 and k > 1 else 0

    wr = [1 / (s["variance"] + tau2) for s in valid]
    swr = sum(wr)
    pooled_re = sum(w * s["effect_size"] for w, s in zip(wr, valid)) / swr
    se_re = math.sqrt(1 / swr)
    ci_re = (pooled_re - 1.96 * se_re, pooled_re + 1.96 * se_re)
    z_re = pooled_re / se_re
    p_re = 2 * (1 - normal_cdf(abs(z_re)))

    enriched = []
    for s, a, b in zip(valid, wf, wr):
        yi, se = s["effect_size"], s["standard_error"]
        enriched.append({
            **s,
            "weight_fixed": a / swf * 100 if swf else 0,
            "weight_random": b / swr * 100 if swr else 0,
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


def subgroup_meta(studies: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    groups = defaultdict(list)
    for s in studies:
        groups[clean(s.get("group", "Overall")) or "Overall"].append(s)
    return {g: run_meta(items) for g, items in groups.items()}


def leave_one_out(studies: List[Dict[str, object]]) -> List[Dict[str, object]]:
    rows = []
    for i, s in enumerate(studies):
        rest = studies[:i] + studies[i+1:]
        res = run_meta(rest)
        if res.get("k", 0):
            main = res["random"]
            rows.append({
                "removed_study": s.get("study_id", f"Study {i+1}"),
                "k_remaining": res["k"],
                "pooled_random": main["pooled"],
                "lower_ci": main["ci"][0],
                "upper_ci": main["ci"][1],
                "I2": res["heterogeneity"]["I2"],
            })
    return rows


def egger_test_approx(studies: List[Dict[str, object]]) -> Dict[str, object]:
    valid = [s for s in studies if safe_float(s.get("standard_error")) and safe_float(s.get("effect_size")) is not None]
    k = len(valid)
    if k < 3:
        return {"available": False, "reason": "minimal 3 studi diperlukan"}
    x, y = [], []
    for s in valid:
        se = safe_float(s["standard_error"])
        yi = safe_float(s["effect_size"])
        precision = 1 / se
        snd = yi / se
        x.append(precision)
        y.append(snd)
    mx, my = sum(x)/k, sum(y)/k
    sxx = sum((v-mx)**2 for v in x)
    if sxx == 0:
        return {"available": False, "reason": "precision tidak bervariasi"}
    slope = sum((x[i]-mx)*(y[i]-my) for i in range(k)) / sxx
    intercept = my - slope * mx
    residuals = [y[i] - (intercept + slope*x[i]) for i in range(k)]
    df = k - 2
    if df <= 0:
        return {"available": False, "reason": "jumlah studi terlalu kecil"}
    mse = sum(e**2 for e in residuals) / df
    se_intercept = math.sqrt(mse * (1/k + mx**2/sxx))
    t = intercept / se_intercept if se_intercept else 0
    # normal approximation for simplicity
    p = 2 * (1 - normal_cdf(abs(t)))
    return {"available": True, "intercept": intercept, "se": se_intercept, "t": t, "p": p}


def extract_effect_from_metadata(record: Dict[str, str]):
    text = clean(" ".join([record.get("title", ""), record.get("abstract", ""), record.get("notes", "")]))
    patterns = [
        (r"(?:effect\s*size|hedges'?s?\s*g|cohen'?s?\s*d|smd)\s*(?:=|:|was|of)?\s*(-?\d+(?:\.\d+)?)", "Generic/SMD"),
        (r"(?:odds\s*ratio|or)\s*(?:=|:|was|of)?\s*(\d+(?:\.\d+)?)", "OR"),
        (r"(?:risk\s*ratio|relative\s*risk|rr)\s*(?:=|:|was|of)?\s*(\d+(?:\.\d+)?)", "RR"),
    ]
    ci_match = re.search(r"(?:95\s*%?\s*ci|confidence\s*interval)\s*(?:=|:)?\s*\[?\s*(-?\d+(?:\.\d+)?)\s*(?:,|to|-|–)\s*(-?\d+(?:\.\d+)?)", text, flags=re.I)

    for pattern, typ in patterns:
        m = re.search(pattern, text, flags=re.I)
        if not m:
            continue
        val = safe_float(m.group(1))
        if val is None:
            continue
        yi = math.log(val) if typ in ["OR", "RR"] and val > 0 else val
        se = None
        if ci_match:
            lo, hi = safe_float(ci_match.group(1)), safe_float(ci_match.group(2))
            if lo is not None and hi is not None and hi != lo:
                if typ in ["OR", "RR"] and lo > 0 and hi > 0:
                    lo, hi = math.log(lo), math.log(hi)
                se = abs(hi - lo) / 3.92
        if se and se > 0:
            return {
                "study_id": f"{record.get('authors', '').split(';')[0]} {record.get('year', '')}".strip() or record.get("title", "Study")[:40],
                "year": record.get("year", ""),
                "group": "Auto-extracted",
                "effect_type": typ,
                "effect_size": yi,
                "standard_error": se,
                "variance": se ** 2,
                "notes": "Auto-extracted from metadata. Verify with full-text."
            }
    return None



# =========================================================
# Excel XLSX utilities - no external dependency
# =========================================================
def excel_col_letter(n: int) -> str:
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def xml_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def sheet_name_safe(name: str) -> str:
    name = re.sub(r"[\[\]\:\*\?\/\\]", " ", clean(name))[:31].strip()
    return name or "Sheet1"


def rows_to_xlsx(rows: List[Dict[str, object]], fieldnames: List[str], sheet_name: str = "Data") -> bytes:
    # Create a simple Excel .xlsx workbook from rows using only stdlib.
    extra = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames and key not in extra:
                extra.append(key)
    headers = fieldnames + extra
    sheet_name = sheet_name_safe(sheet_name)

    data = [headers]
    for row in rows:
        data.append([row.get(h, "") for h in headers])

    string_index = {}
    strings = []

    def get_string_id(value: object) -> int:
        text = "" if value is None else str(value)
        if text not in string_index:
            string_index[text] = len(strings)
            strings.append(text)
        return string_index[text]

    sheet_rows = []
    for r_idx, row in enumerate(data, 1):
        cells = []
        for c_idx, value in enumerate(row, 1):
            ref = f"{excel_col_letter(c_idx)}{r_idx}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                sid = get_string_id(value)
                style = ' s="1"' if r_idx == 1 else ""
                cells.append(f'<c r="{ref}" t="s"{style}><v>{sid}</v></c>')
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    cols_xml = []
    sample_rows = data[: min(len(data), 101)]
    for c_idx, h in enumerate(headers, 1):
        max_len = len(str(h))
        for row in sample_rows[1:]:
            max_len = max(max_len, len(str(row[c_idx - 1] if c_idx - 1 < len(row) else "")))
        width = min(max(max_len + 2, 10), 42)
        cols_xml.append(f'<col min="{c_idx}" max="{c_idx}" width="{width}" customWidth="1"/>')

    sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
 <cols>{"".join(cols_xml)}</cols>
 <sheetData>{"".join(sheet_rows)}</sheetData>
 <autoFilter ref="A1:{excel_col_letter(len(headers))}{max(1, len(data))}"/>
</worksheet>"""

    shared_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(strings)}" uniqueCount="{len(strings)}">
{''.join(f'<si><t xml:space="preserve">{xml_escape(s)}</t></si>' for s in strings)}
</sst>"""

    workbook_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="{xml_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts>
 <fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill></fills>
 <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
 <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
 <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>
 <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    wb_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
 <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>"""

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="xml" ContentType="application/xml"/>
 <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
 <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
 <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
 <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types_xml)
        z.writestr("_rels/.rels", rels_xml)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        z.writestr("xl/styles.xml", styles_xml)
        z.writestr("xl/sharedStrings.xml", shared_xml)
    return out.getvalue()


def xlsx_to_rows(data: bytes) -> List[Dict[str, str]]:
    # Read first worksheet of a simple .xlsx workbook using stdlib.
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data), "r") as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                texts = []
                for t in si.findall(".//m:t", ns):
                    texts.append(t.text or "")
                shared.append("".join(texts))

        sheet_path = "xl/worksheets/sheet1.xml"
        if sheet_path not in z.namelist():
            candidates = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            if not candidates:
                return []
            sheet_path = sorted(candidates)[0]

        root = ET.fromstring(z.read(sheet_path))
        rows = []
        for row in root.findall(".//m:row", ns):
            row_values = {}
            max_col = 0
            for c in row.findall("m:c", ns):
                ref = c.attrib.get("r", "")
                col_letters = re.sub(r"\d+", "", ref)
                col_num = 0
                for ch in col_letters:
                    col_num = col_num * 26 + (ord(ch.upper()) - 64)
                max_col = max(max_col, col_num)
                v = c.find("m:v", ns)
                value = "" if v is None or v.text is None else v.text
                if c.attrib.get("t") == "s":
                    idx = int(value) if value.isdigit() else -1
                    value = shared[idx] if 0 <= idx < len(shared) else ""
                elif c.attrib.get("t") == "inlineStr":
                    t = c.find(".//m:t", ns)
                    value = "" if t is None or t.text is None else t.text
                row_values[col_num] = value
            if max_col:
                rows.append([row_values.get(i, "") for i in range(1, max_col + 1)])

    if not rows:
        return []
    headers = [clean(h) for h in rows[0]]
    result = []
    for row in rows[1:]:
        if not any(clean(x) for x in row):
            continue
        result.append({headers[i]: row[i] if i < len(row) else "" for i in range(len(headers)) if headers[i]})
    return result


def parse_meta_rows(rows: List[Dict[str, object]]) -> Tuple[List[Dict[str, object]], int]:
    # Same logic as parse_meta_csv, but accepts rows loaded from XLSX.
    studies, skipped = [], 0
    for i, row in enumerate(rows, 1):
        lower = {str(k).strip().lower(): v for k, v in row.items()}
        include = clean(lower.get("include", "yes")).lower()
        if include in ["no", "n", "0", "false", "exclude", "tidak"]:
            continue

        study_id = clean(lower.get("study_id") or lower.get("study") or lower.get("title") or f"Study {i}")
        year = year_from_text(lower.get("year", ""))
        group = clean(lower.get("group") or lower.get("subgroup") or "Overall") or "Overall"
        effect_type = clean(lower.get("effect_type") or lower.get("type") or "").lower()
        notes = clean(lower.get("notes") or "")

        yi = safe_float(lower.get("effect_size") or lower.get("yi") or lower.get("effect") or lower.get("g") or lower.get("d") or lower.get("logor") or lower.get("logrr") or lower.get("z"))
        se = safe_float(lower.get("standard_error") or lower.get("se") or lower.get("sei"))
        vi = safe_float(lower.get("variance") or lower.get("var") or lower.get("vi"))

        if yi is None or (se is None and vi is None):
            if effect_type in ["smd", "hedges", "hedges_g", "cohen_d", "d", "g"] or clean(lower.get("mean_t")):
                yi, se = compute_smd(lower.get("n_t"), lower.get("mean_t"), lower.get("sd_t"), lower.get("n_c"), lower.get("mean_c"), lower.get("sd_c"))
                effect_type = "SMD/Hedges g"
            elif effect_type in ["or", "log_or", "odds_ratio", "logor"] or clean(lower.get("non_event_t")):
                yi, se = compute_log_or(lower.get("event_t"), lower.get("non_event_t"), lower.get("event_c"), lower.get("non_event_c"))
                effect_type = "log(OR)"
            elif effect_type in ["rr", "risk_ratio", "log_rr", "logrr"] or (clean(lower.get("total_t")) and clean(lower.get("total_c"))):
                yi, se = compute_log_rr(lower.get("event_t"), lower.get("total_t"), lower.get("event_c"), lower.get("total_c"))
                effect_type = "log(RR)"
            elif effect_type in ["correlation", "r", "fisher_z"] or clean(lower.get("r")):
                yi, se = compute_fisher_z(lower.get("r"), lower.get("n"))
                effect_type = "Fisher z"

        if se is None and vi is not None and vi > 0:
            se = math.sqrt(vi)

        if yi is None or se is None or se <= 0:
            skipped += 1
            continue

        studies.append({
            "study_id": study_id,
            "year": year,
            "group": group,
            "effect_type": effect_type or "Generic",
            "effect_size": yi,
            "standard_error": se,
            "variance": se ** 2,
            "notes": notes,
        })
    return studies, skipped


def parse_bibliography_upload(data: bytes, name: str) -> List[Dict[str, str]]:
    name = name.lower()
    if name.endswith(".xlsx"):
        return standardize(xlsx_to_rows(data))
    if name.endswith(".csv"):
        return parse_csv_bytes(data)
    if name.endswith(".ris"):
        return parse_ris(data.decode("utf-8", errors="replace"))
    return parse_bibtex(data.decode("utf-8", errors="replace"))


def parse_meta_upload(data: bytes, name: str) -> Tuple[List[Dict[str, object]], int]:
    name = name.lower()
    if name.endswith(".xlsx"):
        return parse_meta_rows(xlsx_to_rows(data))
    return parse_meta_csv(data)


# =========================================================
# Exporters and reports
# =========================================================
def to_csv(records: List[Dict[str, str]]) -> bytes:
    return safe_csv(records, COLUMNS)


def escape_bib(value: str) -> str:
    return clean(value).replace("{", "").replace("}", "")


def to_bibtex(records: List[Dict[str, str]]) -> str:
    chunks = []
    for i, r in enumerate(records, 1):
        first_author = r.get("authors", "ref").split(";")[0]
        key = re.sub(r"\W+", "", first_author + r.get("year", "") + str(i)) or f"ref{i}"
        chunks.append("@article{" + key + ",\n" + "\n".join([
            f"  title = {{{escape_bib(r.get('title', ''))}}},",
            f"  author = {{{escape_bib(r.get('authors', '').replace(';', ' and '))}}},",
            f"  year = {{{escape_bib(r.get('year', ''))}}},",
            f"  journal = {{{escape_bib(r.get('journal', ''))}}},",
            f"  publisher = {{{escape_bib(r.get('publisher', ''))}}},",
            f"  doi = {{{escape_bib(r.get('doi', ''))}}},",
            f"  url = {{{escape_bib(r.get('url', ''))}}}",
        ]) + "\n}")
    return "\n\n".join(chunks)


def build_biblio_report(records: List[Dict[str, str]], theme: str) -> str:
    if not records:
        return "Belum ada data bibliografi."
    m = get_metrics(records)
    years = year_distribution(records)
    dbs = count_by(records, "database", 15)
    journals = count_by(records, "journal", 15)
    authors = author_distribution(records, 15)
    keywords = keyword_distribution(records, 15)
    period = f"{min(years.keys())}–{max(years.keys())}" if years else "tidak tersedia"
    doi_pct = m["with_doi"] / len(records) * 100 if records else 0
    abs_pct = m["with_abstract"] / len(records) * 100 if records else 0

    return f"""LAPORAN BIBLIOGRAFI

Tema:
{theme}

Ringkasan:
- Total referensi relevan: {len(records)}
- Periode publikasi: {period}
- DOI tersedia: {m['with_doi']} ({doi_pct:.1f}%)
- Abstrak tersedia: {m['with_abstract']} ({abs_pct:.1f}%)
- Penulis unik: {m['authors_unique']}
- Rata-rata penulis per dokumen: {m['avg_authors']:.2f}
- Tingkat kolaborasi: {m['collab_rate']:.1f}%
- Kandidat Scopus: {m['scopus']}
- Kandidat WoS: {m['wos']}
- Kandidat high impact: {m['high']}
- Perlu verifikasi: {m['need']}

Distribusi sumber:
{chr(10).join([f"- {k}: {v}" for k, v in dbs.items()]) or "-"}

Jurnal dominan:
{chr(10).join([f"- {k}: {v}" for k, v in journals.items()]) or "-"}

Penulis dominan:
{chr(10).join([f"- {k}: {v}" for k, v in authors.items()]) or "-"}

Keyword dominan:
{chr(10).join([f"- {k}: {v}" for k, v in keywords.items()]) or "-"}

Rekomendasi:
- Prioritaskan referensi dengan DOI, abstrak, dan relevansi tema tertinggi.
- Validasi Scopus/WoS/JCR/SJR secara manual untuk artikel utama.
- Untuk meta-analysis, lakukan full-text screening dan ekstraksi effect size/SE.
"""


def build_meta_report(result: Dict[str, object], subgroup: Dict[str, Dict[str, object]] | None = None, model: str = "Random-effects") -> str:
    if not result or result.get("k", 0) == 0:
        return "Belum ada hasil meta-analysis yang valid."
    main = result["random"] if model.startswith("Random") else result["fixed"]
    h = result["heterogeneity"]
    direction = "positif" if main["pooled"] > 0 else "negatif" if main["pooled"] < 0 else "netral"
    sig = "signifikan secara statistik" if main["p"] < 0.05 else "belum signifikan secara statistik"
    hetero = "tinggi" if h["I2"] >= 60 else "sedang" if h["I2"] >= 30 else "rendah"

    lines = [
        "LAPORAN META-ANALYSIS",
        "",
        f"- Jumlah studi: {result['k']}",
        f"- Model utama: {model}",
        f"- Pooled effect: {main['pooled']:.4f} ({direction})",
        f"- 95% CI: {main['ci'][0]:.4f} sampai {main['ci'][1]:.4f}",
        f"- p-value: {main['p']:.6f}; hasil {sig}",
        f"- Q: {h['Q']:.4f}",
        f"- df: {h['df']}",
        f"- tau²: {h['tau2']:.4f}",
        f"- I²: {h['I2']:.2f}% ({hetero})",
        "",
        "Interpretasi:",
    ]
    if h["I2"] >= 60:
        lines.append("- Heterogenitas tinggi. Gunakan subgroup, moderator, risk of bias, atau sensitivity analysis.")
    elif h["I2"] >= 30:
        lines.append("- Heterogenitas sedang. Interpretasi pooled effect perlu hati-hati.")
    else:
        lines.append("- Heterogenitas rendah. Hasil antarstudi relatif konsisten.")

    if subgroup:
        lines += ["", "Subgroup analysis:"]
        for g, res in subgroup.items():
            if res.get("k", 0):
                rm = res["random"]
                lines.append(f"- {g}: k={res['k']}, pooled={rm['pooled']:.4f}, 95% CI {rm['ci'][0]:.4f}–{rm['ci'][1]:.4f}, I²={res['heterogeneity']['I2']:.2f}%")

    lines += [
        "",
        "Catatan:",
        "- Validasi effect size/SE dengan full-text artikel sebelum digunakan pada publikasi ilmiah.",
        "- Untuk naskah final, bandingkan dengan software statistik seperti R metafor/meta, RevMan, JASP, Jamovi, atau Stata."
    ]
    return "\n".join(lines)


def build_final_summary(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_result: Dict[str, object], prisma: Dict[str, int]) -> str:
    lines = [
        "RINGKASAN AKHIR",
        "",
        f"Tema: {theme}",
        "",
        "PRISMA:",
    ]
    lines += [f"- {k}: {v}" for k, v in prisma.items()]
    lines += ["", build_biblio_report(records, theme)]
    if meta_result.get("k", 0):
        lines += ["", build_meta_report(meta_result, subgroup_meta(st.session_state.get("meta_studies", [])), "Random-effects")]
    else:
        lines += ["", "Meta-analysis belum dapat dihitung karena effect size/SE belum tersedia atau belum valid."]
    return "\n".join(lines)



# =========================================================
# Final Insight Engine
# =========================================================
def pct(part: float, total: float) -> float:
    return (part / total * 100) if total else 0.0


def classify_score(score: float) -> str:
    if score >= 80:
        return "Sangat baik"
    if score >= 60:
        return "Baik"
    if score >= 40:
        return "Cukup"
    return "Perlu ditingkatkan"


def bibliography_quality_score(records: List[Dict[str, str]]) -> Dict[str, object]:
    total = len(records)
    if total == 0:
        return {"score": 0, "label": "Belum ada data", "components": {}}

    m = get_metrics(records)
    doi_component = min(100, pct(m["with_doi"], total))
    abstract_component = min(100, pct(m["with_abstract"], total))
    keyword_component = min(100, pct(m["with_keywords"], total))
    indexed_component = min(100, pct(m["scopus"] + m["wos"] + m["high"], total))
    relevance_scores = [safe_float(r.get("theme_relevance_score"), 0) for r in records]
    relevance_avg = sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0
    relevance_component = min(100, relevance_avg * 12.5)

    score = (
        doi_component * 0.25
        + abstract_component * 0.20
        + keyword_component * 0.15
        + indexed_component * 0.25
        + relevance_component * 0.15
    )

    return {
        "score": round(score, 1),
        "label": classify_score(score),
        "components": {
            "DOI coverage": round(doi_component, 1),
            "Abstract coverage": round(abstract_component, 1),
            "Keyword coverage": round(keyword_component, 1),
            "Index/high-impact signal": round(indexed_component, 1),
            "Theme relevance": round(relevance_component, 1),
        }
    }


def meta_readiness_score(records: List[Dict[str, str]], meta_studies: List[Dict[str, object]]) -> Dict[str, object]:
    total_records = len(records)
    k = len(meta_studies)

    if total_records == 0:
        return {"score": 0, "label": "Belum siap", "reason": "Belum ada bibliografi relevan."}

    format_ready = 100 if total_records > 0 else 0
    effect_ready = min(100, pct(k, max(total_records, 1)) * 2)
    sample_ready = 100 if k >= 10 else 70 if k >= 5 else 40 if k >= 2 else 10 if k == 1 else 0

    score = format_ready * 0.25 + effect_ready * 0.35 + sample_ready * 0.40

    if k == 0:
        reason = "Bibliografi sudah siap diformat, tetapi effect size/SE belum tersedia."
    elif k < 3:
        reason = "Meta-analysis bisa diuji coba, tetapi jumlah studi masih sangat kecil."
    elif k < 10:
        reason = "Meta-analysis dapat dilakukan, tetapi interpretasi perlu hati-hati karena jumlah studi terbatas."
    else:
        reason = "Jumlah studi sudah lebih memadai untuk meta-analysis."

    return {"score": round(score, 1), "label": classify_score(score), "reason": reason}


def evidence_strength(records: List[Dict[str, str]], meta_result: Dict[str, object], rob_rows: List[Dict[str, str]]) -> Dict[str, str]:
    k = meta_result.get("k", 0) if meta_result else 0
    if k == 0:
        return {
            "level": "Belum dapat dinilai",
            "reason": "Belum ada data effect size/SE valid untuk menghitung meta-analysis."
        }

    h = meta_result.get("heterogeneity", {})
    i2 = h.get("I2", 0)

    risk_counts = Counter(r.get("overall_risk", "Unclear") for r in rob_rows)
    high_risk = risk_counts.get("High risk", 0)
    low_risk = risk_counts.get("Low risk", 0)

    if k >= 10 and i2 < 50 and high_risk <= k * 0.25:
        level = "Kuat"
        reason = "Jumlah studi cukup, heterogenitas tidak tinggi, dan proporsi high risk tidak dominan."
    elif k >= 5 and i2 < 75:
        level = "Sedang"
        reason = "Jumlah studi cukup untuk analisis awal, tetapi heterogenitas/risk of bias masih perlu diperhatikan."
    else:
        level = "Terbatas"
        reason = "Jumlah studi kecil, heterogenitas tinggi, atau risk of bias belum memadai."

    if low_risk == 0 and rob_rows:
        reason += " Belum ada studi yang dinilai low risk."

    return {"level": level, "reason": reason}


def final_recommendations(records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_result: Dict[str, object], rob_rows: List[Dict[str, str]]) -> List[str]:
    recs = []
    total = len(records)
    m = get_metrics(records) if records else {"with_doi": 0, "with_abstract": 0, "with_keywords": 0, "need": 0}

    if total == 0:
        return ["Jalankan Workflow Tema terlebih dahulu untuk mendapatkan bibliografi sesuai topik."]

    if pct(m["with_doi"], total) < 70:
        recs.append("Lengkapi DOI karena coverage DOI masih di bawah 70%. DOI membantu deduplikasi dan pelacakan sitasi.")
    if pct(m["with_abstract"], total) < 60:
        recs.append("Tambahkan abstrak/full metadata agar screening dan analisis tema lebih akurat.")
    if m["need"] > total * 0.4:
        recs.append("Validasi indeks jurnal secara manual di Scopus, Web of Science, JCR, atau SJR karena banyak record masih perlu verifikasi.")

    if screened:
        excluded = sum(1 for r in screened if r.get("screening_status") == "Excluded")
        maybe = sum(1 for r in screened if r.get("screening_status") == "Maybe")
        if maybe > len(screened) * 0.3:
            recs.append("Banyak artikel berstatus Maybe. Lakukan screening manual judul/abstrak dan full-text.")
        if excluded > len(screened) * 0.6:
            recs.append("Mayoritas artikel tereksklusi. Pertimbangkan revisi kata kunci atau perluas sumber pencarian.")

    k = meta_result.get("k", 0) if meta_result else 0
    if k == 0:
        recs.append("Meta-analysis belum menghasilkan pooled effect. Isi format ekstraksi effect size/SE dari full-text artikel.")
    elif k < 5:
        recs.append("Jumlah studi meta-analysis masih kecil. Tambahkan studi eligible agar hasil lebih stabil.")
    else:
        i2 = meta_result.get("heterogeneity", {}).get("I2", 0)
        if i2 >= 60:
            recs.append("Heterogenitas tinggi. Jalankan subgroup analysis, cek definisi outcome, dan lakukan sensitivity analysis.")
        elif i2 >= 30:
            recs.append("Heterogenitas sedang. Jelaskan kemungkinan sumber variasi antarstudi dalam pembahasan.")
        else:
            recs.append("Heterogenitas rendah. Hasil pooled effect relatif konsisten, tetapi tetap validasi risk of bias.")

    if rob_rows:
        high = sum(1 for r in rob_rows if r.get("overall_risk") == "High risk")
        unclear = sum(1 for r in rob_rows if "Unclear" in r.get("overall_risk", ""))
        if high > len(rob_rows) * 0.25:
            recs.append("Proporsi high risk cukup besar. Sajikan analisis sensitivitas dengan mengecualikan studi high risk.")
        if unclear > len(rob_rows) * 0.4:
            recs.append("Banyak risk of bias masih unclear. Lengkapi penilaian dari full-text.")

    return recs or ["Dataset sudah cukup baik. Lanjutkan validasi manual dan penyusunan laporan akhir."]


def build_executive_insight(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> str:
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    q = bibliography_quality_score(records)
    mr = meta_readiness_score(records, meta_studies)
    ev = evidence_strength(records, meta_result, rob_rows)
    prisma = prisma_counts(st.session_state.get("found_total", 0) or len(records), records, screened, meta_studies)
    recs = final_recommendations(records, screened, meta_result, rob_rows)

    m = get_metrics(records) if records else None
    years = year_distribution(records) if records else {}
    period = f"{min(years.keys())}–{max(years.keys())}" if years else "tidak tersedia"

    lines = [
        "INSIGHT AKHIR OTOMATIS",
        "",
        f"Tema: {theme or '-'}",
        "",
        "1. Status Dataset",
        f"- Total referensi relevan: {len(records)}.",
        f"- Periode publikasi: {period}.",
    ]

    if m:
        lines += [
            f"- DOI coverage: {m['with_doi']} dari {len(records)} ({pct(m['with_doi'], len(records)):.1f}%).",
            f"- Abstract coverage: {m['with_abstract']} dari {len(records)} ({pct(m['with_abstract'], len(records)):.1f}%).",
            f"- Kandidat Scopus/WoS/high-impact: {m['scopus'] + m['wos'] + m['high']}.",
            f"- Tingkat kolaborasi penulis: {m['collab_rate']:.1f}%.",
        ]

    lines += [
        "",
        "2. Kualitas Bibliografi",
        f"- Skor kualitas bibliografi: {q['score']}/100 ({q['label']}).",
    ]
    for k, v in q.get("components", {}).items():
        lines.append(f"- {k}: {v}/100.")

    lines += [
        "",
        "3. PRISMA & Screening, Systematic Review",
        f"- Records identified: {prisma['records_identified']}.",
        f"- After duplicates: {prisma['records_after_duplicates']}.",
        f"- Screened: {prisma['records_screened']}.",
        f"- Excluded: {prisma['records_excluded']}.",
        f"- Included review: {prisma['studies_included_review']}.",
        f"- Included meta-analysis: {prisma['studies_included_meta']}.",
        "",
        "4. Kesiapan Meta-Analysis",
        f"- Skor kesiapan meta-analysis: {mr['score']}/100 ({mr['label']}).",
        f"- Catatan: {mr['reason']}",
    ]

    if meta_result.get("k", 0):
        main = meta_result["random"]
        h = meta_result["heterogeneity"]
        lines += [
            f"- Pooled random effect: {main['pooled']:.4f}.",
            f"- 95% CI: {main['ci'][0]:.4f} sampai {main['ci'][1]:.4f}.",
            f"- p-value: {main['p']:.6f}.",
            f"- I²: {h['I2']:.2f}%.",
        ]
    else:
        lines.append("- Pooled effect belum tersedia karena effect size/SE belum cukup.")

    lines += [
        "",
        "5. Kekuatan Bukti",
        f"- Level bukti: {ev['level']}.",
        f"- Alasan: {ev['reason']}",
        "",
        "6. Rekomendasi Tindakan",
    ]
    lines += [f"- {r}" for r in recs]

    top_journals = count_by(records, "journal", 5) if records else {}
    top_keywords = keyword_distribution(records, 8) if records else {}
    if top_journals:
        lines += ["", "7. Jurnal Dominan"]
        lines += [f"- {k}: {v}" for k, v in top_journals.items()]
    if top_keywords:
        lines += ["", "8. Keyword Dominan"]
        lines += [f"- {k}: {v}" for k, v in top_keywords.items()]

    return "\n".join(lines)


def render_final_insight_tab():
    st.subheader("📌 Insight Akhir")
    records = st.session_state.theme_records or st.session_state.records
    screened = st.session_state.screened
    meta_studies = st.session_state.meta_studies
    rob_rows = st.session_state.rob_rows
    theme = st.session_state.last_theme

    if not records:
        st.info("Belum ada data. Jalankan Workflow Tema terlebih dahulu.")
        return

    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    q = bibliography_quality_score(records)
    mr = meta_readiness_score(records, meta_studies)
    ev = evidence_strength(records, meta_result, rob_rows)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Kualitas Bibliografi", f"{q['score']}/100", q["label"])
    c2.metric("Kesiapan Meta", f"{mr['score']}/100", mr["label"])
    c3.metric("Kekuatan Bukti", ev["level"])
    c4.metric("Studi Meta", meta_result.get("k", 0))

    st.divider()

    left, right = st.columns(2)
    with left:
        st.write("### Komponen Kualitas Bibliografi")
        if q.get("components"):
            st.bar_chart(q["components"])
        st.write("### Distribusi Tahun")
        years = year_distribution(records)
        if years:
            st.bar_chart(years)
        else:
            st.info("Data tahun belum tersedia.")

    with right:
        st.write("### Status Screening")
        if screened:
            st.bar_chart(dict(Counter(r.get("screening_status", "Unknown") for r in screened)))
        else:
            st.info("Screening belum dijalankan.")
        st.write("### Risk of Bias")
        if rob_rows:
            st.bar_chart(dict(Counter(r.get("overall_risk", "Unclear") for r in rob_rows)))
        else:
            st.info("Risk of bias belum diisi.")

    st.divider()
    insight = build_executive_insight(theme, records, screened, meta_studies, rob_rows)
    st.text_area("Insight naratif otomatis", value=insight, height=520)

    st.download_button(
        "📥 Download Insight Akhir TXT",
        data=insight.encode("utf-8"),
        file_name="insight_akhir_biblio_meta.txt",
        mime="text/plain",
        use_container_width=True,
    )



# =========================================================
# Research Materials Generator
# =========================================================
def normalize_theme(theme: str) -> str:
    return clean(theme).strip() or "tema penelitian"


def top_items_as_lines(items: Dict[str, int], limit: int = 8) -> str:
    if not items:
        return "-"
    return "\n".join([f"- {k}: {v}" for k, v in list(items.items())[:limit]])


def build_search_string(theme: str) -> Dict[str, str]:
    theme = normalize_theme(theme)
    tokens = keyword_tokens(theme)
    core_terms = " OR ".join([f'"{t}"' for t in tokens[:6]]) if tokens else f'"{theme}"'

    # Expanded terms are generic and intentionally editable by researcher.
    expanded = f'("{theme}" OR {core_terms})'
    method_terms = '("bibliometric analysis" OR bibliometric* OR "systematic review" OR "meta-analysis" OR "quantitative synthesis")'
    source_terms = '("Scopus" OR "Web of Science" OR PubMed OR Crossref OR OpenAlex OR "Semantic Scholar")'

    return {
        "basic": f'"{theme}"',
        "bibliometric": f'{expanded} AND ("bibliometric analysis" OR bibliometric* OR "science mapping" OR "performance analysis")',
        "meta_analysis": f'{expanded} AND ("meta-analysis" OR "effect size" OR "random effects" OR "standardized mean difference" OR "odds ratio" OR "risk ratio")',
        "combined": f'{expanded} AND {method_terms}',
        "database_note": f"Gunakan query inti pada database: {source_terms}. Sesuaikan syntax masing-masing database."
    }


def build_title_suggestions(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> List[str]:
    theme = normalize_theme(theme).title()
    has_meta = meta_result.get("k", 0) > 0
    titles = [
        f"Bibliometric and Meta-Analytic Review of {theme}",
        f"Research Trends and Evidence Synthesis on {theme}: A Bibliometric and Meta-Analytic Study",
        f"Mapping the Scientific Landscape of {theme}: Bibliometric Evidence and Meta-Analysis",
        f"Performance Analysis, Science Mapping, and Evidence Synthesis of {theme}",
    ]
    if not has_meta:
        titles.append(f"Bibliometric Mapping of {theme}: Trends, Knowledge Structure, and Future Research Agenda")
    return titles


def build_research_questions(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> List[str]:
    theme = normalize_theme(theme)
    questions = [
        f"Bagaimana perkembangan publikasi terkait {theme} berdasarkan tahun, sumber, jurnal, dan database?",
        f"Siapa penulis, jurnal, dan kata kunci dominan dalam penelitian {theme}?",
        f"Bagaimana struktur tema dan arah perkembangan penelitian {theme} berdasarkan keyword dan metadata bibliografi?",
        f"Seberapa kuat kualitas metadata dan kesiapan dataset untuk systematic review/meta-analysis?",
    ]
    if meta_result.get("k", 0):
        questions += [
            f"Berapa besar pooled effect dari studi empiris terkait {theme}?",
            f"Bagaimana tingkat heterogenitas antarstudi dan apa implikasinya terhadap interpretasi hasil?",
            f"Apakah hasil meta-analysis stabil berdasarkan sensitivity analysis dan risk of bias?"
        ]
    else:
        questions += [
            f"Studi mana yang layak masuk tahap full-text screening untuk ekstraksi effect size pada tema {theme}?",
            f"Data kuantitatif apa yang perlu diekstraksi agar meta-analysis pada tema {theme} dapat dilakukan?"
        ]
    return questions


def build_objectives(theme: str, meta_result: Dict[str, object]) -> List[str]:
    theme = normalize_theme(theme)
    objectives = [
        f"Mengidentifikasi perkembangan publikasi dan sumber utama pada tema {theme}.",
        f"Menganalisis kontribusi penulis, jurnal, database, keyword, dan pola kolaborasi pada tema {theme}.",
        f"Menyusun peta awal literatur dan gap penelitian berdasarkan hasil bibliografi dan screening.",
        f"Menyediakan dataset terstruktur untuk proses PRISMA, ekstraksi data, dan risk of bias.",
    ]
    if meta_result.get("k", 0):
        objectives += [
            f"Mengestimasi pooled effect dari studi empiris terkait {theme}.",
            "Menganalisis heterogenitas, subgroup, sensitivity, publication bias, dan kualitas bukti."
        ]
    else:
        objectives += [
            "Menyiapkan format ekstraksi effect size agar meta-analysis dapat dilakukan setelah full-text review."
        ]
    return objectives


def build_inclusion_exclusion(theme: str) -> Dict[str, List[str]]:
    theme = normalize_theme(theme)
    return {
        "inclusion": [
            f"Artikel membahas tema utama {theme}.",
            "Artikel berupa research article, conference paper empiris, atau studi kuantitatif yang relevan.",
            "Metadata minimal memuat judul, tahun, sumber/jurnal, dan penulis.",
            "Untuk meta-analysis: artikel menyediakan effect size/SE, confidence interval, mean-SD-n, event-total, odds ratio, risk ratio, korelasi, atau data yang bisa dihitung menjadi effect size.",
            "Artikel berada pada rentang tahun yang ditentukan peneliti.",
        ],
        "exclusion": [
            "Artikel tidak sesuai tema setelah screening judul/abstrak.",
            "Duplikasi berdasarkan DOI, judul, atau metadata lain.",
            "Editorial, letter, opinion, komentar, atau artikel konseptual tanpa data empiris jika tujuan meta-analysis.",
            "Artikel tanpa full-text atau tanpa data kuantitatif yang dapat diekstraksi untuk meta-analysis.",
            "Studi dengan outcome, populasi, atau metode yang tidak sebanding dengan fokus penelitian.",
        ]
    }


def build_extraction_protocol(theme: str) -> List[str]:
    theme = normalize_theme(theme)
    return [
        "Identitas studi: study_id, penulis, tahun, judul, jurnal, DOI, database.",
        "Konteks studi: negara/lokasi, populasi, sektor/objek, desain penelitian.",
        f"Kesesuaian tema: hubungan studi dengan {theme}.",
        "Outcome utama: variabel hasil yang dianalisis.",
        "Intervensi/eksposur/teknologi/variabel independen.",
        "Comparison/control group jika ada.",
        "Data effect size: effect_size dan standard_error jika sudah tersedia.",
        "Data SMD: n_t, mean_t, sd_t, n_c, mean_c, sd_c.",
        "Data rasio: event_t, total_t, event_c, total_c atau event/non-event.",
        "Data korelasi: r dan n.",
        "Risk of bias: randomization, blinding, incomplete data, selective reporting, confounding control, sample size.",
        "Catatan keputusan: included, excluded, maybe, dan alasan screening."
    ]


def build_gap_and_novelty(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> Dict[str, List[str]]:
    theme = normalize_theme(theme)
    m = get_metrics(records) if records else {"with_abstract": 0, "with_doi": 0, "need": 0}
    total = len(records)

    gaps = [
        f"Literatur {theme} tersebar di berbagai sumber sehingga memerlukan pemetaan bibliografi yang terstruktur.",
        "Sebagian metadata belum lengkap, terutama DOI, abstrak, keyword, atau indikator indeksasi.",
        "Tidak semua studi bibliografi menyediakan data kuantitatif yang siap digunakan untuk meta-analysis.",
        "Perbedaan outcome, populasi, metode, dan desain studi berpotensi menimbulkan heterogenitas.",
    ]

    if total and pct(m["with_abstract"], total) < 60:
        gaps.append("Keterbatasan abstrak mengurangi akurasi screening otomatis dan pemetaan tema.")
    if meta_result.get("k", 0) == 0:
        gaps.append("Belum ada cukup effect size/SE yang dapat dihitung otomatis dari metadata, sehingga full-text extraction menjadi kebutuhan utama.")
    elif meta_result.get("heterogeneity", {}).get("I2", 0) >= 60:
        gaps.append("Heterogenitas tinggi menunjukkan perlunya subgroup analysis dan klasifikasi studi yang lebih rinci.")

    novelty = [
        f"Penelitian ini menggabungkan bibliometric mapping dan kesiapan meta-analysis pada tema {theme}.",
        "Dataset disusun dengan alur PRISMA, screening otomatis, risk of bias, dan format ekstraksi effect size.",
        "Studi tidak hanya memetakan tren publikasi, tetapi juga menilai kesiapan bukti empiris untuk sintesis kuantitatif.",
        "Output penelitian menghasilkan insight bibliografi, gap penelitian, dan bahan sistematis untuk meta-analysis."
    ]

    return {"gaps": gaps, "novelty": novelty}


def build_discussion_points(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> List[str]:
    theme = normalize_theme(theme)
    dbs = count_by(records, "database", 5) if records else {}
    journals = count_by(records, "journal", 5) if records else {}
    keywords = keyword_distribution(records, 8) if records else {}

    points = [
        f"Perkembangan penelitian {theme} dapat dibahas dari jumlah publikasi, periode publikasi, dan sebaran sumber data.",
        "Dominasi database tertentu perlu dibahas karena dapat memengaruhi cakupan literatur dan potensi bias sumber.",
        "Jurnal dominan dapat digunakan untuk menunjukkan pusat publikasi dan bidang keilmuan utama.",
        "Keyword dominan dapat digunakan untuk menjelaskan klaster topik, arah riset, dan tema yang muncul.",
        "Kualitas metadata perlu dibahas karena memengaruhi deduplikasi, screening, dan ekstraksi data.",
    ]

    if dbs:
        points.append("Sumber data dominan: " + "; ".join([f"{k} ({v})" for k, v in dbs.items()]) + ".")
    if journals:
        points.append("Jurnal dominan: " + "; ".join([f"{k} ({v})" for k, v in journals.items()]) + ".")
    if keywords:
        points.append("Keyword penting: " + "; ".join([f"{k} ({v})" for k, v in keywords.items()]) + ".")

    if meta_result.get("k", 0):
        h = meta_result.get("heterogeneity", {})
        points.append(f"Hasil meta-analysis perlu dibahas melalui pooled effect, confidence interval, p-value, dan I² sebesar {h.get('I2', 0):.2f}%.")
        if h.get("I2", 0) >= 60:
            points.append("Heterogenitas tinggi dapat dijelaskan melalui perbedaan populasi, outcome, metode pengukuran, atau desain studi.")
    else:
        points.append("Jika meta-analysis belum menghasilkan pooled effect, pembahasan harus menekankan kebutuhan full-text extraction untuk effect size dan standard error.")

    return points


def build_limitations(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> List[str]:
    limitations = [
        "Validasi indeks Scopus/WoS/high impact masih perlu dilakukan manual karena aplikasi hanya membaca indikator metadata.",
        "Metadata dari database publik dapat tidak lengkap atau berbeda format antar sumber.",
        "Screening otomatis berbasis kata kunci tidak menggantikan keputusan peneliti saat membaca full-text.",
        "Risk of bias perlu dinilai manual berdasarkan isi artikel, bukan hanya metadata.",
        "Hasil meta-analysis otomatis harus divalidasi ulang dengan software statistik khusus sebelum publikasi ilmiah."
    ]
    if not meta_result.get("k", 0):
        limitations.append("Meta-analysis belum dapat disimpulkan apabila effect size/SE belum diekstraksi dari full-text.")
    return limitations


def build_conclusion_draft(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> str:
    theme = normalize_theme(theme)
    m = get_metrics(records) if records else None
    if not records:
        return f"Penelitian bertema {theme} belum memiliki dataset bibliografi yang cukup untuk disimpulkan."

    base = (
        f"Berdasarkan hasil pemetaan bibliografi, tema {theme} menunjukkan cakupan literatur yang dapat dianalisis "
        f"melalui distribusi publikasi, sumber data, jurnal dominan, penulis, keyword, dan kualitas metadata. "
    )

    if m:
        base += (
            f"Dataset yang diperoleh memuat {len(records)} referensi relevan, dengan {m['with_doi']} referensi memiliki DOI "
            f"dan {m['with_abstract']} referensi memiliki abstrak. "
        )

    if meta_result.get("k", 0):
        main = meta_result["random"]
        h = meta_result["heterogeneity"]
        base += (
            f"Hasil meta-analysis awal terhadap {meta_result['k']} studi menunjukkan pooled effect sebesar {main['pooled']:.4f} "
            f"dengan 95% CI {main['ci'][0]:.4f} sampai {main['ci'][1]:.4f}, serta I² sebesar {h['I2']:.2f}%. "
            f"Temuan ini perlu ditafsirkan dengan mempertimbangkan heterogenitas, risk of bias, dan hasil sensitivity analysis."
        )
    else:
        base += (
            "Namun, meta-analysis belum dapat disimpulkan secara kuantitatif karena data effect size dan standard error "
            "masih perlu diekstraksi dari full-text artikel."
        )

    return base


def build_research_materials_report(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme)
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    searches = build_search_string(theme)
    inc_exc = build_inclusion_exclusion(theme)
    gap_novelty = build_gap_and_novelty(theme, records, meta_result)

    lines = [
        "BAHAN PENELITIAN OTOMATIS",
        "",
        f"Tema: {theme}",
        "",
        "1. Alternatif Judul",
    ]
    lines += [f"- {x}" for x in build_title_suggestions(theme, records, meta_result)]

    lines += ["", "2. Rumusan Masalah"]
    lines += [f"- {x}" for x in build_research_questions(theme, records, meta_result)]

    lines += ["", "3. Tujuan Penelitian"]
    lines += [f"- {x}" for x in build_objectives(theme, meta_result)]

    lines += ["", "4. Search String"]
    for k, v in searches.items():
        lines.append(f"- {k}: {v}")

    lines += ["", "5. Kriteria Inklusi"]
    lines += [f"- {x}" for x in inc_exc["inclusion"]]

    lines += ["", "6. Kriteria Eksklusi"]
    lines += [f"- {x}" for x in inc_exc["exclusion"]]

    lines += ["", "7. Protokol Ekstraksi Data"]
    lines += [f"- {x}" for x in build_extraction_protocol(theme)]

    lines += ["", "8. Gap Penelitian"]
    lines += [f"- {x}" for x in gap_novelty["gaps"]]

    lines += ["", "9. Novelty/Kebaruan"]
    lines += [f"- {x}" for x in gap_novelty["novelty"]]

    lines += ["", "10. Poin Pembahasan"]
    lines += [f"- {x}" for x in build_discussion_points(theme, records, meta_result)]

    lines += ["", "11. Keterbatasan Penelitian"]
    lines += [f"- {x}" for x in build_limitations(theme, records, meta_result)]

    lines += ["", "12. Draft Kesimpulan"]
    lines.append(build_conclusion_draft(theme, records, meta_result))

    lines += ["", "13. Insight Akhir"]
    lines.append(build_executive_insight(theme, records, screened, meta_studies, rob_rows))

    return "\n".join(lines)


def render_research_materials_tab():
    st.subheader("🧩 Bahan Penelitian")
    records = st.session_state.theme_records or st.session_state.records
    screened = st.session_state.screened
    meta_studies = st.session_state.meta_studies
    rob_rows = st.session_state.rob_rows
    theme = st.session_state.last_theme or st.text_input("Tema manual untuk bahan penelitian", value="precision livestock farming")

    if not records:
        st.info("Belum ada dataset. Jalankan Workflow Tema terlebih dahulu agar bahan penelitian mengikuti hasil yang didapat.")
        # Still show general template based on manual theme
        meta_result = {"k": 0, "studies": []}
        st.write("### Template awal berdasarkan tema")
    else:
        meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}

    sections = st.multiselect(
        "Pilih bahan yang ingin ditampilkan",
        [
            "Alternatif Judul",
            "Rumusan Masalah",
            "Tujuan Penelitian",
            "Search String",
            "Inklusi-Eksklusi",
            "Protokol Ekstraksi",
            "Gap & Novelty",
            "Poin Pembahasan",
            "Keterbatasan",
            "Draft Kesimpulan",
            "Insight Lengkap"
        ],
        default=[
            "Alternatif Judul",
            "Rumusan Masalah",
            "Tujuan Penelitian",
            "Search String",
            "Inklusi-Eksklusi",
            "Gap & Novelty",
            "Draft Kesimpulan",
            "Insight Lengkap"
        ]
    )

    if "Alternatif Judul" in sections:
        st.write("### Alternatif Judul")
        for x in build_title_suggestions(theme, records, meta_result):
            st.write(f"- {x}")

    if "Rumusan Masalah" in sections:
        st.write("### Rumusan Masalah")
        for x in build_research_questions(theme, records, meta_result):
            st.write(f"- {x}")

    if "Tujuan Penelitian" in sections:
        st.write("### Tujuan Penelitian")
        for x in build_objectives(theme, meta_result):
            st.write(f"- {x}")

    if "Search String" in sections:
        st.write("### Search String")
        st.json(build_search_string(theme))

    if "Inklusi-Eksklusi" in sections:
        st.write("### Kriteria Inklusi-Eksklusi")
        inc_exc = build_inclusion_exclusion(theme)
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Inklusi**")
            for x in inc_exc["inclusion"]:
                st.write(f"- {x}")
        with c2:
            st.write("**Eksklusi**")
            for x in inc_exc["exclusion"]:
                st.write(f"- {x}")

    if "Protokol Ekstraksi" in sections:
        st.write("### Protokol Ekstraksi")
        for x in build_extraction_protocol(theme):
            st.write(f"- {x}")

    if "Gap & Novelty" in sections:
        st.write("### Gap & Novelty")
        gn = build_gap_and_novelty(theme, records, meta_result)
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Gap**")
            for x in gn["gaps"]:
                st.write(f"- {x}")
        with c2:
            st.write("**Novelty**")
            for x in gn["novelty"]:
                st.write(f"- {x}")

    if "Poin Pembahasan" in sections:
        st.write("### Poin Pembahasan")
        for x in build_discussion_points(theme, records, meta_result):
            st.write(f"- {x}")

    if "Keterbatasan" in sections:
        st.write("### Keterbatasan")
        for x in build_limitations(theme, records, meta_result):
            st.write(f"- {x}")

    if "Draft Kesimpulan" in sections:
        st.write("### Draft Kesimpulan")
        st.write(build_conclusion_draft(theme, records, meta_result))

    if "Insight Lengkap" in sections:
        st.write("### Insight Lengkap")
        st.text_area(
            "Bahan penelitian lengkap",
            value=build_research_materials_report(theme, records, screened, meta_studies, rob_rows),
            height=520
        )

    report = build_research_materials_report(theme, records, screened, meta_studies, rob_rows)
    st.download_button(
        "📥 Download Bahan Penelitian TXT",
        data=report.encode("utf-8"),
        file_name="bahan_penelitian_biblio_meta.txt",
        mime="text/plain",
        use_container_width=True,
    )



# =========================================================
# Journal Review Builder
# =========================================================
def format_bullets(items: List[str]) -> str:
    return "\n".join([f"- {x}" for x in items]) if items else "-"


def review_article_type(meta_result: Dict[str, object]) -> str:
    if meta_result.get("k", 0):
        return "systematic literature review with bibliometric mapping and meta-analysis"
    return "systematic bibliometric review with meta-analysis preparation"


def build_review_abstract(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_result: Dict[str, object]) -> str:
    theme = normalize_theme(theme)
    m = get_metrics(records) if records else {"with_doi": 0, "with_abstract": 0, "scopus": 0, "wos": 0, "high": 0}
    prisma = prisma_counts(st.session_state.get("found_total", 0) or len(records), records, screened, st.session_state.get("meta_studies", []))
    years = year_distribution(records) if records else {}
    period = f"{min(years.keys())}–{max(years.keys())}" if years else "the selected publication period"

    meta_sentence = (
        f"Meta-analysis was conducted on {meta_result['k']} eligible studies and produced a pooled random-effects estimate of "
        f"{meta_result['random']['pooled']:.4f} with 95% CI {meta_result['random']['ci'][0]:.4f} to {meta_result['random']['ci'][1]:.4f} "
        f"and I² of {meta_result['heterogeneity']['I2']:.2f}%."
        if meta_result.get("k", 0)
        else "The bibliographic dataset was prepared for meta-analysis, but quantitative pooling requires additional full-text extraction of effect sizes and standard errors."
    )

    return (
        f"This review examines the development, structure, and evidence base of research on {theme}. "
        f"A structured search was conducted across credible bibliographic sources and the records were screened using PRISMA-oriented criteria. "
        f"After deduplication and relevance filtering, {len(records)} relevant records from {period} were analyzed. "
        f"The bibliographic analysis summarized publication trends, dominant sources, journals, authors, keywords, metadata quality, and indexing signals. "
        f"The screening process identified {prisma['studies_included_review']} records for review and {prisma['studies_included_meta']} studies for quantitative synthesis. "
        f"{meta_sentence} "
        f"The findings provide a structured map of the literature, identify research gaps, and offer a reproducible basis for future systematic review and evidence synthesis."
    )


def build_review_introduction(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> str:
    theme = normalize_theme(theme)
    gap_novelty = build_gap_and_novelty(theme, records, meta_result)
    return (
        f"Research on {theme} has grown as scholars and practitioners increasingly seek evidence-based understanding of its concepts, applications, outcomes, and methodological development. "
        f"However, the literature is often distributed across multiple databases, journals, disciplines, and methodological traditions. "
        f"This condition makes it difficult to identify dominant research streams, influential publication sources, and the extent to which the existing evidence can be synthesized quantitatively. "
        f"A bibliometric review is useful for mapping the knowledge structure of the field, while a meta-analysis can estimate the magnitude and consistency of empirical effects when comparable quantitative data are available.\n\n"
        f"The present review responds to the following gaps: {', '.join(gap_novelty['gaps'])}. "
        f"The novelty of this study lies in its integrated workflow that combines bibliographic mapping, PRISMA-based screening, risk of bias assessment, meta-analysis preparation, and evidence-readiness evaluation. "
        f"Therefore, this review is designed not only to describe the literature landscape, but also to assess whether the available studies are sufficiently prepared for quantitative evidence synthesis."
    )


def build_review_methods(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_result: Dict[str, object]) -> str:
    theme = normalize_theme(theme)
    searches = build_search_string(theme)
    inc_exc = build_inclusion_exclusion(theme)
    prisma = prisma_counts(st.session_state.get("found_total", 0) or len(records), records, screened, st.session_state.get("meta_studies", []))
    article_type = review_article_type(meta_result)

    return (
        f"This study was designed as a {article_type}. The review workflow consisted of identification, deduplication, relevance screening, eligibility assessment, bibliographic analysis, and meta-analytic preparation or synthesis.\n\n"
        f"Search strategy. The main search string was: {searches['combined']}. Additional search strings were prepared for bibliometric mapping and meta-analysis: {searches['bibliometric']} and {searches['meta_analysis']}. "
        f"The search was conducted across available bibliographic sources such as Crossref, OpenAlex, PubMed, Semantic Scholar, DOAJ, arXiv, Europe PMC, and DataCite, depending on the relevance of the topic.\n\n"
        f"Inclusion criteria included: {', '.join(inc_exc['inclusion'])}. Exclusion criteria included: {', '.join(inc_exc['exclusion'])}. "
        f"Records were screened using title, abstract, DOI availability, publication year, indexing indicators, and theme relevance score. "
        f"The PRISMA-oriented flow produced {prisma['records_identified']} identified records, {prisma['records_after_duplicates']} records after deduplication, {prisma['records_screened']} screened records, {prisma['records_excluded']} excluded records, and {prisma['studies_included_review']} records included for review.\n\n"
        f"Bibliographic analysis. The bibliographic analysis summarized publication year distribution, source/database distribution, dominant journals, author productivity, keyword frequency, DOI coverage, abstract coverage, and indexing/high-impact candidate signals.\n\n"
        f"Meta-analysis. For quantitative synthesis, eligible studies were required to provide effect size and standard error or raw data that could be transformed into effect size, including mean, standard deviation, sample size, event counts, odds ratio, risk ratio, or correlation. "
        f"Fixed-effect and random-effects models were calculated, with heterogeneity assessed using Q, tau², and I². Sensitivity analysis used leave-one-out analysis, while publication bias was approximated using an Egger-type regression when sufficient studies were available.\n\n"
        f"Risk of bias. Study quality was evaluated using checklist domains including randomization, blinding, incomplete data, selective reporting, confounding control, and sample size adequacy."
    )


def build_review_results(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_result: Dict[str, object], rob_rows: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme)
    m = get_metrics(records) if records else {}
    years = year_distribution(records) if records else {}
    dbs = count_by(records, "database", 10) if records else {}
    journals = count_by(records, "journal", 10) if records else {}
    keywords = keyword_distribution(records, 10) if records else {}
    prisma = prisma_counts(st.session_state.get("found_total", 0) or len(records), records, screened, st.session_state.get("meta_studies", []))
    q = bibliography_quality_score(records)

    period = f"{min(years.keys())}–{max(years.keys())}" if years else "not available"
    risk_counts = Counter(r.get("overall_risk", "Unclear") for r in rob_rows)

    text = (
        f"The final bibliographic dataset consisted of {len(records)} records related to {theme}. "
        f"The publication period covered {period}. DOI coverage was {m.get('with_doi', 0)} records, while abstract coverage was {m.get('with_abstract', 0)} records. "
        f"The bibliographic quality score was {q['score']}/100, categorized as {q['label']}.\n\n"
        f"The PRISMA-oriented screening showed {prisma['records_identified']} identified records, {prisma['records_after_duplicates']} records after deduplication, "
        f"{prisma['records_screened']} screened records, {prisma['records_excluded']} excluded records, {prisma['full_text_assessed']} records assessed for eligibility, "
        f"{prisma['studies_included_review']} studies included in the review, and {prisma['studies_included_meta']} studies included in the meta-analysis.\n\n"
        f"The dominant data sources were: {', '.join([f'{k} ({v})' for k, v in dbs.items()]) if dbs else 'not available'}. "
        f"The dominant journals or publication venues were: {', '.join([f'{k} ({v})' for k, v in journals.items()]) if journals else 'not available'}. "
        f"The most frequent keywords were: {', '.join([f'{k} ({v})' for k, v in keywords.items()]) if keywords else 'not available'}.\n\n"
    )

    if meta_result.get("k", 0):
        main = meta_result["random"]
        h = meta_result["heterogeneity"]
        text += (
            f"The meta-analysis included {meta_result['k']} studies. The random-effects pooled estimate was {main['pooled']:.4f}, "
            f"with a 95% confidence interval from {main['ci'][0]:.4f} to {main['ci'][1]:.4f} and p-value of {main['p']:.6f}. "
            f"Heterogeneity statistics showed Q = {h['Q']:.4f}, tau² = {h['tau2']:.4f}, and I² = {h['I2']:.2f}%. "
        )
        if h["I2"] >= 60:
            text += "This indicates substantial heterogeneity, suggesting that differences in population, intervention, outcome, or study design should be explored through subgroup or sensitivity analysis.\n\n"
        elif h["I2"] >= 30:
            text += "This indicates moderate heterogeneity, requiring cautious interpretation of the pooled estimate.\n\n"
        else:
            text += "This indicates low heterogeneity, suggesting relatively consistent effects across included studies.\n\n"
    else:
        text += (
            "A quantitative pooled estimate could not yet be produced because the available bibliographic metadata did not contain sufficient effect size and standard error data. "
            "Therefore, full-text extraction is required before a final meta-analysis can be reported.\n\n"
        )

    if rob_rows:
        text += f"Risk of bias assessment produced the following distribution: {', '.join([f'{k} ({v})' for k, v in risk_counts.items()])}. "
        text += "This result should be considered when interpreting the strength and reliability of the synthesized evidence."
    else:
        text += "Risk of bias assessment has not yet been completed and should be performed using full-text information."

    return text


def build_review_discussion(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object], rob_rows: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme)
    points = build_discussion_points(theme, records, meta_result)
    gap_novelty = build_gap_and_novelty(theme, records, meta_result)
    ev = evidence_strength(records, meta_result, rob_rows)

    return (
        f"The findings indicate that {theme} is an identifiable and analyzable research area with literature distributed across several publication sources and databases. "
        f"The bibliographic results help clarify the publication structure, dominant venues, keyword emphasis, and evidence readiness of the field. "
        f"Several discussion points arise from the analysis: {', '.join(points)}.\n\n"
        f"The main research gaps include: {', '.join(gap_novelty['gaps'])}. These gaps suggest that future studies should improve metadata completeness, report quantitative outcomes more consistently, and provide sufficient statistical information for evidence synthesis. "
        f"The novelty of the present review lies in the combination of bibliographic mapping, systematic screening, risk of bias preparation, and meta-analysis readiness assessment.\n\n"
        f"The strength of evidence is currently categorized as {ev['level']}. {ev['reason']} "
        f"If a valid meta-analysis is available, the pooled estimate should be interpreted together with heterogeneity, risk of bias, and sensitivity analysis. "
        f"If meta-analysis is not yet available, the study should be reported as a bibliometric systematic review with a clear extraction plan for future quantitative synthesis."
    )


def build_review_implications(theme: str, meta_result: Dict[str, object]) -> str:
    theme = normalize_theme(theme)
    if meta_result.get("k", 0):
        return (
            f"The findings have implications for researchers, practitioners, and decision-makers working on {theme}. "
            f"For researchers, the results identify dominant topics, evidence gaps, and methodological limitations. "
            f"For practitioners, the pooled evidence can support decisions about whether the studied approach or intervention is likely to produce meaningful effects. "
            f"For future reviews, the results highlight the need for better standardized reporting of outcome data, effect sizes, and uncertainty estimates."
        )
    return (
        f"The findings provide a structured foundation for future research on {theme}. "
        f"For researchers, the bibliographic map identifies relevant sources, journals, keywords, and possible research gaps. "
        f"For future systematic review or meta-analysis, the output provides a ready-to-use extraction format and screening protocol. "
        f"Practical implications should be interpreted carefully until full-text extraction and quantitative synthesis are completed."
    )


def build_review_limitations_paragraph(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> str:
    limitations = build_limitations(theme, records, meta_result)
    return "This review has several limitations. " + " ".join(limitations)


def build_review_conclusion(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> str:
    return build_conclusion_draft(theme, records, meta_result)


def build_table_figure_plan(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> List[Dict[str, str]]:
    plan = [
        {"item": "Table 1", "title": "Search strategy and database sources", "content": "Database, query string, date, number of records."},
        {"item": "Table 2", "title": "Inclusion and exclusion criteria", "content": "Eligibility criteria for bibliographic review and meta-analysis."},
        {"item": "Table 3", "title": "Characteristics of included studies", "content": "Author, year, title, journal, country, population, outcome, DOI."},
        {"item": "Table 4", "title": "Top journals, authors, and keywords", "content": "Bibliographic performance indicators."},
        {"item": "Table 5", "title": "Risk of bias assessment", "content": "Risk domains and overall risk judgment."},
        {"item": "Figure 1", "title": "PRISMA flow diagram", "content": "Identification, screening, eligibility, included studies."},
        {"item": "Figure 2", "title": "Publication trend by year", "content": "Annual publication distribution."},
        {"item": "Figure 3", "title": "Keyword distribution or science mapping", "content": "Main research themes and keyword frequency."},
    ]
    if meta_result.get("k", 0):
        plan += [
            {"item": "Figure 4", "title": "Forest plot", "content": "Effect size, confidence interval, and pooled estimate."},
            {"item": "Figure 5", "title": "Funnel plot / publication bias", "content": "Effect size and standard error distribution."},
            {"item": "Table 6", "title": "Sensitivity analysis", "content": "Leave-one-out pooled estimates and heterogeneity."},
        ]
    return plan


def build_journal_review_draft(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme)
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    title = build_title_suggestions(theme, records, meta_result)[0]
    keywords = keyword_distribution(records, 8) if records else {}
    keyword_text = "; ".join(list(keywords.keys())[:6]) if keywords else theme

    draft = [
        title.upper(),
        "",
        "ABSTRACT",
        build_review_abstract(theme, records, screened, meta_result),
        "",
        f"Keywords: {keyword_text}",
        "",
        "1. INTRODUCTION",
        build_review_introduction(theme, records, meta_result),
        "",
        "2. METHODS",
        build_review_methods(theme, records, screened, meta_result),
        "",
        "3. RESULTS",
        build_review_results(theme, records, screened, meta_result, rob_rows),
        "",
        "4. DISCUSSION",
        build_review_discussion(theme, records, meta_result, rob_rows),
        "",
        "5. IMPLICATIONS",
        build_review_implications(theme, meta_result),
        "",
        "6. LIMITATIONS",
        build_review_limitations_paragraph(theme, records, meta_result),
        "",
        "7. CONCLUSION",
        build_review_conclusion(theme, records, meta_result),
        "",
        "TABLE AND FIGURE PLAN",
    ]
    for row in build_table_figure_plan(theme, records, meta_result):
        draft.append(f"- {row['item']}: {row['title']} — {row['content']}")

    draft += [
        "",
        "REPORTING CHECKLIST",
        "- State review objective and research questions.",
        "- Report databases and search strings.",
        "- Provide inclusion and exclusion criteria.",
        "- Present PRISMA flow counts.",
        "- Explain deduplication and screening process.",
        "- Describe bibliographic indicators.",
        "- Describe meta-analysis model and effect size calculation if applicable.",
        "- Report heterogeneity, sensitivity analysis, publication bias, and risk of bias if applicable.",
        "- Discuss limitations and implications.",
        "- Provide data extraction table as supplementary material."
    ]

    return "\n".join(draft)


def build_review_checklist(records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    checks = []
    checks.append({"section": "Search strategy", "status": "Ready" if records else "Missing", "note": "Run workflow and keep search strings."})
    checks.append({"section": "Bibliography dataset", "status": "Ready" if len(records) >= 10 else "Needs more data", "note": f"{len(records)} records available."})
    checks.append({"section": "PRISMA screening", "status": "Ready" if screened else "Missing", "note": "Run screening and export PRISMA table."})
    checks.append({"section": "Meta-analysis data", "status": "Ready" if len(meta_studies) >= 2 else "Needs extraction", "note": f"{len(meta_studies)} valid studies with effect size."})
    checks.append({"section": "Risk of bias", "status": "Ready" if rob_rows else "Missing", "note": "Assess risk of bias using full-text."})
    checks.append({"section": "Sensitivity analysis", "status": "Ready" if len(meta_studies) >= 2 else "Not enough studies", "note": "Leave-one-out requires at least 2 studies."})
    checks.append({"section": "Publication bias", "status": "Ready" if len(meta_studies) >= 3 else "Not enough studies", "note": "Egger approximation requires at least 3 studies."})
    checks.append({"section": "Discussion material", "status": "Ready" if records else "Missing", "note": "Generated from bibliographic and meta-analysis results."})
    return checks


def render_journal_review_builder_tab():
    st.subheader("📝 Jurnal Review Builder dan Q-Level Toolkit dan Sumber Relevan")
    records = st.session_state.theme_records or st.session_state.records
    screened = st.session_state.screened
    meta_studies = st.session_state.meta_studies
    rob_rows = st.session_state.rob_rows
    theme = st.session_state.last_theme or st.text_input("Tema manual", value="precision livestock farming", key="review_theme_manual")

    if not records:
        st.info("Belum ada data hasil workflow. Builder tetap bisa membuat kerangka umum, tetapi isi hasil akan jauh lebih kuat setelah Workflow Tema dijalankan.")

    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    article_type = review_article_type(meta_result)

    c1, c2, c3 = st.columns(3)
    c1.metric("Jenis Review", "Meta + Biblio" if meta_result.get("k", 0) else "Biblio Review")
    c2.metric("Referensi", len(records))
    c3.metric("Studi Meta", meta_result.get("k", 0))

    st.write("### Kesiapan Naskah")
    checklist = build_review_checklist(records, screened, meta_studies, rob_rows)
    st.dataframe(checklist, use_container_width=True)

    tab_outline, tab_draft, tab_tables, tab_export = st.tabs(["🧱 Outline", "📄 Draft Artikel", "📊 Tabel/Figure", "📤 Export"])

    with tab_outline:
        st.write("### Struktur Artikel Review")
        outline = [
            "Title",
            "Abstract",
            "Keywords",
            "1. Introduction",
            "2. Methods",
            "   2.1 Review design",
            "   2.2 Search strategy",
            "   2.3 Inclusion and exclusion criteria",
            "   2.4 Screening and PRISMA flow",
            "   2.5 Bibliographic analysis",
            "   2.6 Meta-analysis and risk of bias",
            "3. Results",
            "   3.1 PRISMA results",
            "   3.2 Publication trends",
            "   3.3 Dominant journals, authors, and keywords",
            "   3.4 Bibliographic insight",
            "   3.5 Meta-analysis results",
            "   3.6 Risk of bias and sensitivity analysis",
            "4. Discussion",
            "5. Implications",
            "6. Limitations",
            "7. Conclusion",
            "References",
            "Supplementary Materials"
        ]
        for x in outline:
            st.write(f"- {x}")

        st.write("### Alternatif Judul")
        for x in build_title_suggestions(theme, records, meta_result):
            st.write(f"- {x}")

        st.write("### Rumusan Masalah")
        for x in build_research_questions(theme, records, meta_result):
            st.write(f"- {x}")

    with tab_draft:
        draft = build_journal_review_draft(theme, records, screened, meta_studies, rob_rows)
        st.text_area("Draft artikel review", value=draft, height=650)

    with tab_tables:
        st.write("### Rencana Tabel dan Figure")
        plan = build_table_figure_plan(theme, records, meta_result)
        st.dataframe(plan, use_container_width=True)

        st.write("### Template Tabel Karakteristik Studi")
        study_rows = []
        for r in records[:50]:
            study_rows.append({
                "author_year": f"{r.get('authors','').split(';')[0]} {r.get('year','')}".strip(),
                "title": r.get("title", ""),
                "journal": r.get("journal", ""),
                "database": r.get("database", ""),
                "doi": r.get("doi", ""),
                "population": "",
                "intervention_exposure": "",
                "comparison": "",
                "outcome": "",
                "effect_data_available": "",
                "notes": "",
            })
        st.dataframe(study_rows, use_container_width=True, height=300)

        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download Template Karakteristik Studi Excel",
                data=rows_to_xlsx(study_rows, list(study_rows[0].keys()) if study_rows else ["author_year", "title", "journal", "database", "doi", "population", "intervention_exposure", "comparison", "outcome", "effect_data_available", "notes"], "Karakteristik Studi"),
                file_name="template_karakteristik_studi.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                disabled=not bool(study_rows),
            )
        else:
            st.download_button(
                "📥 Download Template Karakteristik Studi CSV",
                data=safe_csv(study_rows, list(study_rows[0].keys()) if study_rows else ["author_year", "title", "journal", "database", "doi", "population", "intervention_exposure", "comparison", "outcome", "effect_data_available", "notes"]),
                file_name="template_karakteristik_studi.csv",
                mime="text/csv",
                use_container_width=True,
                disabled=not bool(study_rows),
            )

    with tab_export:
        draft = build_journal_review_draft(theme, records, screened, meta_studies, rob_rows)
        st.download_button(
            "📥 Download Draft Artikel Review TXT",
            data=draft.encode("utf-8"),
            file_name="draft_artikel_review.txt",
            mime="text/plain",
            use_container_width=True,
        )
        st.download_button(
            "📥 Download Checklist Kesiapan Review CSV",
            data=safe_csv(checklist, ["section", "status", "note"]),
            file_name="checklist_kesiapan_review.csv",
            mime="text/csv",
            use_container_width=True,
        )



# =========================================================
# Q-Level Journal Toolkit
# =========================================================
def qlevel_readiness_score(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> Dict[str, object]:
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    bq = bibliography_quality_score(records)
    mr = meta_readiness_score(records, meta_studies)
    has_prisma = 100 if screened else 0
    has_rob = 100 if rob_rows else 0
    has_review_draft = 100 if records else 0
    has_sensitivity = 100 if len(meta_studies) >= 2 else 40 if len(meta_studies) == 1 else 0
    has_pub_bias = 100 if len(meta_studies) >= 3 else 40 if len(meta_studies) == 2 else 0
    data_size = min(100, len(records) * 2)
    q_evidence = 100 if meta_result.get("k", 0) >= 10 else 75 if meta_result.get("k", 0) >= 5 else 45 if meta_result.get("k", 0) >= 2 else 20 if records else 0

    score = (
        bq["score"] * 0.20
        + mr["score"] * 0.15
        + has_prisma * 0.12
        + has_rob * 0.10
        + has_sensitivity * 0.08
        + has_pub_bias * 0.05
        + data_size * 0.10
        + q_evidence * 0.10
        + has_review_draft * 0.10
    )

    label = "Q1/Q2 ready draft" if score >= 80 else "Q2/Q3 developing" if score >= 65 else "Q3/Q4 draft level" if score >= 45 else "Needs major preparation"

    missing = []
    if len(records) < 30:
        missing.append("Tambahkan jumlah literatur dan perluas database agar dataset lebih kuat.")
    if not screened:
        missing.append("Lengkapi PRISMA screening dan alasan eksklusi.")
    if not rob_rows:
        missing.append("Isi risk of bias/quality assessment dari full-text.")
    if len(meta_studies) == 0:
        missing.append("Isi effect size/SE dari full-text jika ingin meta-analysis.")
    if len(meta_studies) < 3:
        missing.append("Publication bias belum kuat karena jumlah studi meta-analysis kurang dari 3.")
    if bq["score"] < 70:
        missing.append("Perbaiki kualitas metadata: DOI, abstrak, keyword, dan validasi indeks jurnal.")

    return {
        "score": round(score, 1),
        "label": label,
        "components": {
            "Bibliography quality": round(bq["score"], 1),
            "Meta-analysis readiness": round(mr["score"], 1),
            "PRISMA screening": has_prisma,
            "Risk of bias": has_rob,
            "Sensitivity analysis": has_sensitivity,
            "Publication bias": has_pub_bias,
            "Dataset size": data_size,
            "Evidence strength": q_evidence,
            "Draft completeness": has_review_draft,
        },
        "missing": missing
    }


def build_qlevel_checklist(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    m = get_metrics(records) if records else {"with_doi": 0, "with_abstract": 0}
    total = len(records)

    checks = [
        {
            "area": "Title",
            "criterion": "Judul spesifik, memuat tema, metode review, dan jenis analisis.",
            "status": "Ready" if theme else "Needs work",
            "action": "Gunakan alternatif judul dari Jurnal Review Builder dan Q-Level Toolkit dan Sumber Relevan."
        },
        {
            "area": "Abstract",
            "criterion": "Abstrak terstruktur memuat background, objective, methods, results, conclusion.",
            "status": "Ready" if records else "Needs work",
            "action": "Gunakan draft abstract lalu edit sesuai target journal."
        },
        {
            "area": "Introduction",
            "criterion": "Pendahuluan menunjukkan gap, novelty, kontribusi, dan alasan review diperlukan.",
            "status": "Ready" if records else "Needs work",
            "action": "Gunakan bagian Gap & Novelty dan perkuat dengan referensi utama."
        },
        {
            "area": "Search strategy",
            "criterion": "Search string, database, rentang tahun, dan tanggal pencarian dilaporkan.",
            "status": "Ready" if records else "Needs work",
            "action": "Simpan search string dan cantumkan database yang digunakan."
        },
        {
            "area": "PRISMA",
            "criterion": "Alur identification, screening, eligibility, included jelas dan dapat direplikasi.",
            "status": "Ready" if screened else "Missing",
            "action": "Jalankan tab PRISMA & Screening, Systematic Review dan export tabel screening."
        },
        {
            "area": "Data quality",
            "criterion": "DOI dan abstrak cukup lengkap untuk screening dan sitasi.",
            "status": "Ready" if total and pct(m["with_doi"], total) >= 70 and pct(m["with_abstract"], total) >= 60 else "Needs work",
            "action": "Lengkapi DOI/abstrak dari database atau full-text."
        },
        {
            "area": "Bibliometric results",
            "criterion": "Tren tahun, sumber, jurnal, keyword, dan insight bibliografi tersedia.",
            "status": "Ready" if records else "Missing",
            "action": "Gunakan tab Bibliografi dan Insight Akhir."
        },
        {
            "area": "Meta-analysis",
            "criterion": "Effect size, standard error, model, CI, p-value, dan heterogeneity dilaporkan.",
            "status": "Ready" if meta_result.get("k", 0) >= 2 else "Optional/Needs extraction",
            "action": "Isi format Excel meta-analysis dari full-text."
        },
        {
            "area": "Risk of bias",
            "criterion": "Kualitas studi dinilai dengan domain yang jelas.",
            "status": "Ready" if rob_rows else "Missing",
            "action": "Isi tab Risk of Bias berdasarkan full-text."
        },
        {
            "area": "Sensitivity analysis",
            "criterion": "Leave-one-out atau robustness check tersedia.",
            "status": "Ready" if len(meta_studies) >= 2 else "Not enough studies",
            "action": "Butuh minimal 2 studi valid."
        },
        {
            "area": "Publication bias",
            "criterion": "Funnel/Egger atau alasan tidak dilakukan dijelaskan.",
            "status": "Ready" if len(meta_studies) >= 3 else "Explain limitation",
            "action": "Jika studi kurang dari 3, tulis sebagai keterbatasan."
        },
        {
            "area": "Discussion",
            "criterion": "Pembahasan mengaitkan hasil, gap, novelty, implikasi, dan keterbatasan.",
            "status": "Ready" if records else "Needs work",
            "action": "Gunakan Jurnal Review Builder dan Q-Level Toolkit dan Sumber Relevan lalu perkuat dengan argumen kritis."
        },
        {
            "area": "References",
            "criterion": "Referensi mayoritas mutakhir, relevan, dan berasal dari jurnal bereputasi.",
            "status": "Needs manual validation",
            "action": "Validasi Scopus/WoS/SJR/JCR dan cek gaya sitasi target journal."
        }
    ]
    return checks


def build_qlevel_article_structure(theme: str, meta_result: Dict[str, object]) -> str:
    theme = normalize_theme(theme)
    has_meta = meta_result.get("k", 0) > 0
    meta_part = """
3.5 Meta-analysis results
- Type of effect size
- Fixed-effect result
- Random-effects result
- Heterogeneity: Q, tau², I²
- Forest plot
- Subgroup analysis
- Sensitivity analysis
- Publication bias
""" if has_meta else """
3.5 Meta-analysis readiness
- Number of studies with extractable quantitative data
- Missing effect size information
- Recommended full-text extraction strategy
- Explanation why quantitative pooling is not yet performed
"""

    return f"""Q-Level Review Article Structure for: {theme}

TITLE
- Specific, concise, and method-oriented.
- Mention systematic review, bibliometric analysis, and meta-analysis if applicable.

ABSTRACT
- Background
- Objective
- Methods
- Results
- Conclusion
- Keywords

1. INTRODUCTION
1.1 Background and importance of the topic
1.2 Current state of research
1.3 Research gap
1.4 Novelty and contribution
1.5 Research questions/objectives

2. METHODS
2.1 Review design
2.2 Data sources and search strategy
2.3 Eligibility criteria
2.4 Screening and PRISMA flow
2.5 Data extraction
2.6 Bibliometric indicators
2.7 Meta-analysis model and effect size calculation
2.8 Risk of bias / quality assessment
2.9 Sensitivity analysis and publication bias

3. RESULTS
3.1 PRISMA flow results
3.2 Publication trend
3.3 Source, journal, author, and keyword distribution
3.4 Bibliographic quality and evidence readiness
{meta_part}
3.6 Risk of bias results

4. DISCUSSION
4.1 Main findings
4.2 Comparison with previous reviews
4.3 Interpretation of bibliographic patterns
4.4 Interpretation of meta-analysis or evidence readiness
4.5 Theoretical contribution
4.6 Practical implications
4.7 Future research agenda

5. LIMITATIONS
- Database limitation
- Metadata limitation
- Screening limitation
- Risk of bias limitation
- Meta-analysis limitation if effect size data are incomplete

6. CONCLUSION
- Concise synthesis of findings
- Contribution to the field
- Recommendation for future studies

SUPPLEMENTARY MATERIALS
- Search string
- Screening table
- Extracted data
- Risk of bias table
- Meta-analysis calculation table
"""


def build_contribution_statement(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> str:
    theme = normalize_theme(theme)
    if meta_result.get("k", 0):
        return (
            f"This review contributes to the literature on {theme} by integrating bibliometric mapping with quantitative evidence synthesis. "
            f"Unlike narrative reviews, this study provides a reproducible PRISMA-oriented workflow, structured bibliographic indicators, risk of bias assessment, "
            f"and pooled effect estimation. The study also identifies knowledge gaps, methodological limitations, and future directions based on both publication patterns and empirical effect estimates."
        )
    return (
        f"This review contributes to the literature on {theme} by providing a structured bibliometric and evidence-readiness map. "
        f"The study identifies publication trends, dominant journals, keywords, metadata quality, and gaps in quantitative reporting. "
        f"Although quantitative pooling is not yet available, this review prepares a full extraction framework for future meta-analysis and highlights the data required for stronger evidence synthesis."
    )


def build_cover_letter(theme: str, records: List[Dict[str, str]], meta_result: Dict[str, object]) -> str:
    theme = normalize_theme(theme)
    article_type = "systematic review, bibliometric analysis, and meta-analysis" if meta_result.get("k", 0) else "systematic bibliometric review with meta-analysis preparation"
    return f"""Dear Editor,

We are pleased to submit our manuscript entitled "{build_title_suggestions(theme, records, meta_result)[0]}" for consideration in your journal.

This manuscript presents a {article_type} on {theme}. The study applies a structured and reproducible workflow including database searching, PRISMA-oriented screening, bibliographic mapping, risk of bias preparation, evidence-readiness assessment, and quantitative synthesis where data are available.

The contribution of this manuscript lies in its integrated approach. It not only maps the development and structure of the research field, but also evaluates whether the existing evidence is sufficiently prepared for meta-analysis. The results are expected to be useful for researchers, practitioners, and future review authors interested in understanding the current state, gaps, and evidence strength of {theme}.

We confirm that this manuscript is original, has not been published elsewhere, and is not under consideration by another journal. All authors have approved the submission.

Thank you for considering our manuscript.

Sincerely,
[Author Name]
"""


def build_response_to_reviewer_template(theme: str) -> str:
    theme = normalize_theme(theme)
    return f"""Response to Reviewers Template

Manuscript topic: {theme}

Dear Editor and Reviewers,

We sincerely thank the editor and reviewers for their constructive comments. We have revised the manuscript carefully according to the suggestions. Below we provide a point-by-point response.

Reviewer 1

Comment 1:
[Paste reviewer comment here]

Response:
Thank you for this helpful comment. We have revised the manuscript accordingly by [describe revision]. The change can be found in Section [x], page [x], lines [x–x].

Comment 2:
[Paste reviewer comment here]

Response:
We agree with the reviewer. We have clarified [method/result/discussion] by adding [specific explanation]. This revision improves the clarity of the manuscript.

Reviewer 2

Comment 1:
[Paste reviewer comment here]

Response:
Thank you for raising this point. We have addressed it by [explain action]. In addition, we have added [new table/figure/reference/sensitivity analysis] to strengthen the manuscript.

Summary of major revisions:
1. Improved the explanation of search strategy and PRISMA screening.
2. Clarified inclusion and exclusion criteria.
3. Expanded the discussion of research gaps and novelty.
4. Added/updated risk of bias and sensitivity analysis.
5. Revised the conclusion to better reflect the results.

We hope the revised manuscript meets the expectations of the journal.

Sincerely,
[Author Name]
"""


def build_qlevel_language_polish_checklist() -> List[str]:
    return [
        "Gunakan kalimat akademik yang jelas, tidak terlalu panjang, dan langsung ke argumen.",
        "Hindari klaim terlalu kuat jika data meta-analysis belum cukup.",
        "Setiap temuan utama harus dikaitkan dengan tabel, figure, atau hasil analisis.",
        "Gunakan istilah konsisten: systematic review, bibliometric analysis, meta-analysis, screening, included studies.",
        "Pastikan abstract memuat angka utama: total record, included studies, pooled effect jika ada, dan I² jika ada.",
        "Discussion tidak hanya mengulang hasil, tetapi menjelaskan makna, gap, kontribusi, dan implikasi.",
        "Limitations harus jujur dan spesifik.",
        "Conclusion harus singkat, tidak menambah hasil baru.",
        "Sesuaikan style referensi dengan target journal.",
        "Cek plagiarism/similarity dan parafrase bagian yang terlalu generik."
    ]


def build_qlevel_report(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme)
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    readiness = qlevel_readiness_score(theme, records, screened, meta_studies, rob_rows)
    checklist = build_qlevel_checklist(theme, records, screened, meta_studies, rob_rows)

    lines = [
        "Q-LEVEL JOURNAL READINESS REPORT",
        "",
        f"Theme: {theme}",
        f"Readiness score: {readiness['score']}/100",
        f"Readiness label: {readiness['label']}",
        "",
        "1. Component Scores"
    ]
    lines += [f"- {k}: {v}/100" for k, v in readiness["components"].items()]

    lines += ["", "2. Missing / Weak Components"]
    lines += [f"- {x}" for x in readiness["missing"]] or ["- No major missing component detected."]

    lines += ["", "3. Q-Level Checklist"]
    for item in checklist:
        lines.append(f"- [{item['status']}] {item['area']}: {item['criterion']} Action: {item['action']}")

    lines += [
        "",
        "4. Recommended Article Structure",
        build_qlevel_article_structure(theme, meta_result),
        "",
        "5. Contribution Statement",
        build_contribution_statement(theme, records, meta_result),
        "",
        "6. Language and Reporting Checklist"
    ]
    lines += [f"- {x}" for x in build_qlevel_language_polish_checklist()]

    lines += [
        "",
        "7. Cover Letter Template",
        build_cover_letter(theme, records, meta_result),
        "",
        "8. Response to Reviewer Template",
        build_response_to_reviewer_template(theme)
    ]

    return "\n".join(lines)


def render_qlevel_toolkit_tab():
    st.subheader("🏆 Q-Level Journal Toolkit")
    records = st.session_state.theme_records or st.session_state.records
    screened = st.session_state.screened
    meta_studies = st.session_state.meta_studies
    rob_rows = st.session_state.rob_rows
    theme = st.session_state.last_theme or st.text_input("Tema manual Q-Level", value="precision livestock farming", key="qlevel_theme")

    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    readiness = qlevel_readiness_score(theme, records, screened, meta_studies, rob_rows)

    c1, c2, c3 = st.columns(3)
    c1.metric("Q-Level Readiness", f"{readiness['score']}/100")
    c2.metric("Status", readiness["label"])
    c3.metric("Studi Meta", meta_result.get("k", 0))

    st.write("### Komponen Skor")
    st.bar_chart(readiness["components"])

    if readiness["missing"]:
        st.warning("Komponen yang masih perlu diperkuat:")
        for item in readiness["missing"]:
            st.write(f"- {item}")

    tab_check, tab_structure, tab_submission, tab_export = st.tabs([
        "✅ Checklist", "🧱 Struktur Q-Level", "📨 Submission Kit", "📤 Export"
    ])

    with tab_check:
        st.write("### Checklist Kesiapan Naskah Q-Level")
        checklist = build_qlevel_checklist(theme, records, screened, meta_studies, rob_rows)
        st.dataframe(checklist, use_container_width=True, height=420)

        st.write("### Language & Reporting Polish")
        for x in build_qlevel_language_polish_checklist():
            st.write(f"- {x}")

    with tab_structure:
        st.write("### Struktur Artikel Q-Level")
        st.text_area(
            "Struktur artikel",
            value=build_qlevel_article_structure(theme, meta_result),
            height=520
        )

        st.write("### Contribution / Novelty Statement")
        st.text_area(
            "Contribution statement",
            value=build_contribution_statement(theme, records, meta_result),
            height=180
        )

    with tab_submission:
        st.write("### Cover Letter")
        st.text_area("Cover letter", value=build_cover_letter(theme, records, meta_result), height=320)

        st.write("### Response to Reviewer Template")
        st.text_area("Response template", value=build_response_to_reviewer_template(theme), height=420)

    with tab_export:
        report = build_qlevel_report(theme, records, screened, meta_studies, rob_rows)
        st.download_button(
            "📥 Download Q-Level Readiness Report TXT",
            data=report.encode("utf-8"),
            file_name="qlevel_journal_readiness_report.txt",
            mime="text/plain",
            use_container_width=True,
        )
        st.download_button(
            "📥 Download Q-Level Checklist CSV",
            data=safe_csv(build_qlevel_checklist(theme, records, screened, meta_studies, rob_rows), ["area", "criterion", "status", "action"]),
            file_name="qlevel_checklist.csv",
            mime="text/csv",
            use_container_width=True,
        )



# =========================================================
# Relevant Source Enhancer
# =========================================================


def relevant_source_catalog(theme: str = "") -> List[Dict[str, str]]:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    plf_note = "Sangat relevan untuk precision livestock farming, smart farming, sensor, IoT, animal welfare, dairy/cattle/poultry, dan computer vision."
    return [
        {"source": "Crossref", "type": "API aktif", "best_for": "DOI metadata lintas publisher", "use_in_app": "Ya", "note": "Sumber dasar untuk deduplikasi DOI."},
        {"source": "OpenAlex", "type": "API aktif", "best_for": "Open bibliographic index, konsep/topik, venue", "use_in_app": "Ya", "note": "Bagus untuk pemetaan umum dan discovery."},
        {"source": "Semantic Scholar", "type": "API aktif", "best_for": "Paper AI/ML, citation-oriented metadata", "use_in_app": "Ya", "note": "Relevan untuk computer vision, machine learning, sensor analytics."},
        {"source": "PLOS", "type": "API aktif", "best_for": "Open-access empirical papers", "use_in_app": "Ya", "note": "Tambahan sumber open access yang mudah dipakai."},
        {"source": "OpenAIRE", "type": "API aktif", "best_for": "European open scholarly outputs and publications", "use_in_app": "Ya", "note": "Tambahan sumber terbuka untuk memperluas coverage."},
        {"source": "PubMed", "type": "API aktif", "best_for": "Animal health, veterinary, biomedical, disease detection", "use_in_app": "Ya", "note": "Relevan untuk livestock health, welfare, veterinary outcomes."},
        {"source": "Europe PMC", "type": "API aktif", "best_for": "Life sciences, veterinary, biomedical full-text links", "use_in_app": "Ya", "note": "Pelengkap PubMed."},
        {"source": "DOAJ", "type": "API aktif", "best_for": "Open-access journals", "use_in_app": "Ya", "note": "Bagus untuk OA journal discovery."},
        {"source": "arXiv", "type": "API aktif", "best_for": "Preprint AI, computer vision, ML, sensor data", "use_in_app": "Ya", "note": "Gunakan untuk teknologi/AI, tapi validasi status peer-review."},
        {"source": "DataCite", "type": "API aktif", "best_for": "Dataset, software, report, preprint DOI", "use_in_app": "Ya", "note": "Berguna untuk data/supplementary material."},
        {"source": "Scopus", "type": "Import manual", "best_for": "Artikel Q-level, citation data, author affiliation", "use_in_app": "Upload Excel/RIS/BibTeX", "note": "Ekspor dari akun institusi lalu upload."},
        {"source": "Web of Science", "type": "Import manual", "best_for": "WoS Core Collection, citation report", "use_in_app": "Upload Excel/RIS/BibTeX", "note": "Ekspor dari akun institusi lalu upload."},
        {"source": "AGRIS / FAO", "type": "Search/import manual", "best_for": "Agriculture, livestock, agrifood systems", "use_in_app": "Cari lalu ekspor metadata jika tersedia", "note": plf_note},
        {"source": "USDA PubAg", "type": "Search/import manual", "best_for": "USDA-funded agricultural literature", "use_in_app": "Cari lalu ekspor metadata jika tersedia", "note": "Sangat relevan untuk animal science dan agriculture."},
        {"source": "CAB Abstracts / CABI", "type": "Import manual/berlangganan", "best_for": "Agriculture, veterinary, animal science", "use_in_app": "Upload hasil ekspor", "note": "Sangat relevan untuk review bidang peternakan."},
        {"source": "IEEE Xplore", "type": "Import manual/berlangganan", "best_for": "IoT, sensors, computer vision, embedded systems", "use_in_app": "Upload BibTeX/RIS", "note": "Relevan untuk teknologi precision farming."},
        {"source": "ScienceDirect", "type": "Import manual/berlangganan", "best_for": "Elsevier journals: Computers and Electronics in Agriculture, Biosystems Engineering", "use_in_app": "Upload BibTeX/RIS", "note": "Sangat relevan untuk smart agriculture."},
        {"source": "SpringerLink", "type": "Import manual/berlangganan/OA", "best_for": "AI, agriculture, animal science", "use_in_app": "Upload BibTeX/RIS", "note": "Pelengkap untuk literatur peer-reviewed."},
        {"source": "MDPI", "type": "Search/import manual", "best_for": "Sensors, Animals, Agriculture, Applied Sciences", "use_in_app": "Upload BibTeX/RIS", "note": "Relevan untuk PLF, tetapi validasi kualitas jurnal tetap perlu."},
        {"source": "Frontiers", "type": "Search/import manual", "best_for": "Veterinary science, animal science, digital agriculture", "use_in_app": "Upload BibTeX/RIS", "note": "Pelengkap literatur OA."},
        {"source": "Taylor & Francis / Wiley", "type": "Import manual/berlangganan", "best_for": "Animal science, agriculture, veterinary", "use_in_app": "Upload BibTeX/RIS", "note": "Gunakan untuk melengkapi literatur Q-level."},

        {"source": "Cochrane Library", "type": "Search/import manual", "best_for": "Systematic reviews, clinical and health evidence", "use_in_app": "Upload RIS/BibTeX jika tersedia", "note": "Relevan untuk review kesehatan/veterinary dengan pendekatan evidence-based."},
        {"source": "Google Scholar", "type": "Search manual", "best_for": "Grey literature discovery and citation chasing", "use_in_app": "Gunakan untuk snowballing, lalu input/upload metadata", "note": "Tidak ideal sebagai satu-satunya sumber karena hasil sulit direplikasi."},
        {"source": "Dimensions", "type": "Import manual/berlangganan", "best_for": "Citation, grants, patents, broad research outputs", "use_in_app": "Upload hasil ekspor", "note": "Alternatif/pelengkap Scopus-WoS jika tersedia."},
        {"source": "ProQuest Dissertations", "type": "Import manual/berlangganan", "best_for": "Theses/dissertations untuk grey literature", "use_in_app": "Upload hasil ekspor", "note": "Berguna untuk mengurangi publication bias."},
        {"source": "Research Rabbit / Connected Papers", "type": "Snowballing manual", "best_for": "Citation chasing dan paper discovery", "use_in_app": "Tambahkan artikel relevan secara manual", "note": "Gunakan sebagai pelengkap, bukan pengganti database utama."},

    ]


def build_query_variants(theme: str) -> List[str]:
    theme_clean = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    base = [theme_clean]
    lower = theme_clean.lower()
    if "precision livestock" in lower or "livestock" in lower:
        base += [
            "precision livestock farming",
            "smart livestock farming",
            "precision dairy farming",
            "livestock monitoring sensors",
            "animal welfare monitoring sensors",
            "IoT livestock monitoring",
            "machine learning livestock farming",
            "computer vision livestock monitoring",
            "wearable sensors cattle",
            "smart dairy cow monitoring",
            "poultry monitoring computer vision",
        ]
    elif "smart farming" in lower or "precision agriculture" in lower:
        base += [
            "smart farming IoT sensors",
            "precision agriculture machine learning",
            "digital agriculture monitoring",
            "agricultural sensors artificial intelligence",
        ]
    elif "animal welfare" in lower:
        base += [
            "animal welfare monitoring",
            "livestock welfare sensors",
            "animal behavior detection",
            "computer vision animal welfare",
        ]
    return list(dict.fromkeys([q for q in base if q]))[:8]


def source_specific_query(theme: str, source: str) -> str:
    variants = build_query_variants(theme)
    if source in ["Crossref", "OpenAlex", "Semantic Scholar", "PLOS", "OpenAIRE", "DOAJ", "DataCite"]:
        return variants[0]
    if source in ["PubMed", "Europe PMC"]:
        if "livestock" in theme.lower():
            return "(precision livestock farming) OR (livestock monitoring) OR (animal welfare monitoring) OR (veterinary sensors)"
        return variants[0]
    if source == "arXiv":
        if "livestock" in theme.lower():
            return "computer vision livestock monitoring OR machine learning agriculture sensors"
        return variants[0]
    return variants[0]


def render_relevant_sources_tab():
    st.subheader("🌐 Sumber Relevan")
    theme = st.session_state.get("last_theme", "") or st.text_input("Tema untuk rekomendasi sumber", value="precision livestock farming", key="source_theme_manual")
    catalog = relevant_source_catalog(theme)

    st.write("### Sumber API aktif di aplikasi")
    active = [r for r in catalog if r["type"] == "API aktif"]
    st.dataframe(active, use_container_width=True, height=330)

    st.write("### Sumber penting untuk ditambahkan lewat upload")
    manual = [r for r in catalog if r["type"] != "API aktif"]
    st.dataframe(manual, use_container_width=True, height=430)

    st.write("### Query variants yang disarankan")
    variants = build_query_variants(theme)
    for q in variants:
        st.code(q)

    st.write("### Search string siap pakai")
    if "precision livestock" in theme.lower() or "livestock" in theme.lower():
        st.text_area(
            "Boolean string PLF",
            value='("precision livestock farming" OR "smart livestock farming" OR "precision dairy farming" OR "livestock monitoring" OR "animal welfare monitoring" OR "IoT livestock" OR "computer vision livestock" OR "wearable sensors cattle") AND (sensor* OR "machine learning" OR "artificial intelligence" OR "computer vision" OR monitoring OR welfare OR health)',
            height=120,
        )
    else:
        st.text_area(
            "Boolean string umum",
            value=build_search_string(theme)["combined"] if "build_search_string" in globals() else theme,
            height=120,
        )

    st.info(
        "Untuk database berlangganan seperti Scopus, Web of Science, IEEE Xplore, ScienceDirect, CAB Abstracts, dan SpringerLink, "
        "gunakan search string di atas, ekspor hasil dalam Excel/RIS/BibTeX, lalu upload ke tab Bibliografi."
    )

    if "rows_to_xlsx" in globals():
        st.download_button(
            "📥 Download Daftar Sumber Relevan Excel",
            data=rows_to_xlsx(catalog, ["source", "type", "best_for", "use_in_app", "note"], "Sumber Relevan"),
            file_name="daftar_sumber_relevan.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
        st.download_button(
            "📥 Download Daftar Sumber Relevan CSV",
            data=safe_csv(catalog, ["source", "type", "best_for", "use_in_app", "note"]),
            file_name="daftar_sumber_relevan.csv",
            mime="text/csv",
            use_container_width=True,
        )



# =========================================================
# Systematic Review Module
# =========================================================
def infer_review_framework(theme: str) -> Dict[str, str]:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    lower = theme.lower()

    if any(x in lower for x in ["intervention", "treatment", "therapy", "program", "training", "education", "health", "clinical"]):
        framework = "PICO"
        fields = {
            "Population": "Populasi/subjek yang diteliti sesuai tema.",
            "Intervention": "Intervensi, teknologi, program, atau paparan utama.",
            "Comparison": "Kelompok pembanding, baseline, metode konvensional, atau kondisi kontrol.",
            "Outcome": "Outcome utama yang dapat diukur secara kuantitatif atau naratif.",
        }
    elif any(x in lower for x in ["experience", "perception", "qualitative", "barrier", "challenge", "attitude"]):
        framework = "SPIDER"
        fields = {
            "Sample": "Kelompok partisipan atau sumber data.",
            "Phenomenon of Interest": f"Fenomena utama terkait {theme}.",
            "Design": "Desain penelitian kualitatif/mixed-method.",
            "Evaluation": "Pengalaman, persepsi, hambatan, atau dampak yang dievaluasi.",
            "Research type": "Qualitative, mixed-method, atau survey.",
        }
    else:
        framework = "PECO/PICO fleksibel"
        fields = {
            "Population/Problem": f"Populasi, objek, atau masalah utama pada {theme}.",
            "Exposure/Intervention": "Teknologi, faktor, metode, atau variabel utama.",
            "Comparison": "Kelompok pembanding, kondisi lain, atau tidak ada pembanding.",
            "Outcome": "Outcome, indikator, performa, tren, atau dampak yang dianalisis.",
        }

    return {"framework": framework, "fields": fields}


def build_systematic_review_protocol(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    framework = infer_review_framework(theme)
    searches = build_search_string(theme) if "build_search_string" in globals() else {"combined": theme}
    inc_exc = build_inclusion_exclusion(theme) if "build_inclusion_exclusion" in globals() else {"inclusion": [], "exclusion": []}
    prisma = prisma_counts(st.session_state.get("found_total", 0) or len(records), records, screened, st.session_state.get("meta_studies", [])) if "prisma_counts" in globals() else {}

    lines = [
        "SYSTEMATIC REVIEW PROTOCOL",
        "",
        f"Review topic: {theme}",
        f"Framework: {framework['framework']}",
        "",
        "1. Review Question Framework",
    ]
    for k, v in framework["fields"].items():
        lines.append(f"- {k}: {v}")

    lines += [
        "",
        "2. Objective",
        f"- To systematically identify, screen, synthesize, and report available evidence related to {theme}.",
        "- To map the characteristics of included studies, methodological patterns, outcomes, and evidence gaps.",
        "- To prepare quantitative synthesis/meta-analysis when effect size data are available.",
        "",
        "3. Databases and Sources",
        "- API/active sources: Crossref, OpenAlex, Semantic Scholar, PLOS, DOAJ, PubMed, Europe PMC, arXiv, DataCite.",
        "- Recommended manual/import sources: Scopus, Web of Science, AGRIS/FAO, USDA PubAg, CAB Abstracts/CABI, IEEE Xplore, ScienceDirect, SpringerLink, MDPI, Frontiers, Taylor & Francis, Wiley.",
        "",
        "4. Search Strategy",
        f"- Basic query: {searches.get('basic', theme)}",
        f"- Combined query: {searches.get('combined', theme)}",
        f"- Bibliometric query: {searches.get('bibliometric', theme)}",
        f"- Meta-analysis query: {searches.get('meta_analysis', theme)}",
        "",
        "5. Inclusion Criteria",
    ]
    lines += [f"- {x}" for x in inc_exc.get("inclusion", [])]

    lines += ["", "6. Exclusion Criteria"]
    lines += [f"- {x}" for x in inc_exc.get("exclusion", [])]

    lines += [
        "",
        "7. Study Selection Procedure",
        "- Import all retrieved records into the application.",
        "- Remove duplicates using DOI and title-based matching.",
        "- Screen titles and abstracts using eligibility criteria.",
        "- Label each record as Included, Excluded, or Maybe.",
        "- Retrieve full text for Included and Maybe records.",
        "- Record exclusion reasons for transparency.",
        "",
        "8. Data Extraction Plan",
    ]
    lines += [f"- {x}" for x in build_extraction_protocol(theme)] if "build_extraction_protocol" in globals() else ["- Extract bibliographic and methodological data."]

    lines += [
        "",
        "9. Quality Assessment / Risk of Bias",
        "- Assess randomization or sampling appropriateness.",
        "- Assess blinding or outcome measurement objectivity where applicable.",
        "- Assess incomplete data and attrition.",
        "- Assess selective reporting.",
        "- Assess confounding control.",
        "- Assess whether sample size is adequate.",
        "",
        "10. Synthesis Plan",
        "- Conduct descriptive synthesis for all included studies.",
        "- Conduct bibliographic synthesis for publication trends, journals, authors, keywords, and sources.",
        "- Conduct meta-analysis only for studies with effect size and standard error or calculable raw data.",
        "- Use random-effects model as primary when heterogeneity is expected.",
        "- Report Q, tau², I², confidence interval, and p-value.",
        "- Conduct sensitivity analysis and publication bias assessment when study count is sufficient.",
        "",
        "11. PRISMA Flow Snapshot",
    ]
    for k, v in prisma.items():
        lines.append(f"- {k}: {v}")

    return "\n".join(lines)


def build_prisma_checklist() -> List[Dict[str, str]]:
    return [
        {"section": "Title", "item": "Identify the report as a systematic review, meta-analysis, or both.", "status": "To check"},
        {"section": "Abstract", "item": "Provide structured summary: background, objectives, sources, eligibility, synthesis, results, limitations.", "status": "To check"},
        {"section": "Rationale", "item": "Describe why the review is needed in light of existing knowledge.", "status": "To check"},
        {"section": "Objectives", "item": "State review questions using PICO/PECO/SPIDER or suitable framework.", "status": "To check"},
        {"section": "Eligibility", "item": "Specify inclusion and exclusion criteria clearly.", "status": "To check"},
        {"section": "Information sources", "item": "List databases, registers, websites, organizations, and last search date.", "status": "To check"},
        {"section": "Search strategy", "item": "Present full search strings for at least one database.", "status": "To check"},
        {"section": "Selection process", "item": "Explain screening method and number of reviewers if applicable.", "status": "To check"},
        {"section": "Data collection", "item": "Describe extraction process and variables collected.", "status": "To check"},
        {"section": "Data items", "item": "List all outcomes and variables sought.", "status": "To check"},
        {"section": "Risk of bias", "item": "Describe tool/domains used to assess quality.", "status": "To check"},
        {"section": "Synthesis methods", "item": "Describe narrative synthesis and meta-analysis methods.", "status": "To check"},
        {"section": "Study selection results", "item": "Report PRISMA flow counts.", "status": "To check"},
        {"section": "Study characteristics", "item": "Present characteristics of included studies.", "status": "To check"},
        {"section": "Risk of bias results", "item": "Present risk of bias for each included study.", "status": "To check"},
        {"section": "Results of syntheses", "item": "Report bibliographic synthesis and meta-analysis findings if available.", "status": "To check"},
        {"section": "Reporting bias", "item": "Report publication bias assessment or explain why not possible.", "status": "To check"},
        {"section": "Certainty", "item": "Discuss certainty or strength of evidence.", "status": "To check"},
        {"section": "Discussion", "item": "Summarize findings, limitations, implications, and future research.", "status": "To check"},
        {"section": "Registration", "item": "Report protocol registration if available, or state not registered.", "status": "To check"},
    ]


def build_systematic_review_results_narrative(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    prisma = prisma_counts(st.session_state.get("found_total", 0) or len(records), records, screened, meta_studies) if "prisma_counts" in globals() else {}
    m = get_metrics(records) if records else {}
    years = year_distribution(records) if records else {}
    period = f"{min(years.keys())}–{max(years.keys())}" if years else "not available"
    dbs = count_by(records, "database", 8) if records else {}
    journals = count_by(records, "journal", 8) if records else {}
    keywords = keyword_distribution(records, 10) if records else {}

    text = [
        f"The systematic review on {theme} identified {prisma.get('records_identified', len(records))} initial records. "
        f"After deduplication and relevance filtering, {len(records)} records were retained for screening. "
        f"The publication period covered {period}. "
        f"DOI information was available for {m.get('with_doi', 0)} records and abstracts were available for {m.get('with_abstract', 0)} records.",
        "",
        f"The dominant sources were {', '.join([f'{k} ({v})' for k, v in dbs.items()]) if dbs else 'not available'}. "
        f"The dominant journals or venues were {', '.join([f'{k} ({v})' for k, v in journals.items()]) if journals else 'not available'}. "
        f"The most frequent keywords were {', '.join([f'{k} ({v})' for k, v in keywords.items()]) if keywords else 'not available'}.",
        "",
        f"Screening resulted in {prisma.get('studies_included_review', 0)} included studies for review and {prisma.get('studies_included_meta', 0)} studies eligible for meta-analysis. "
    ]

    if meta_result.get("k", 0):
        main = meta_result["random"]
        h = meta_result["heterogeneity"]
        text.append(
            f"The quantitative synthesis included {meta_result['k']} studies. The random-effects pooled estimate was {main['pooled']:.4f} "
            f"with 95% CI {main['ci'][0]:.4f} to {main['ci'][1]:.4f}. Heterogeneity was I² = {h['I2']:.2f}%, tau² = {h['tau2']:.4f}, and Q = {h['Q']:.4f}."
        )
    else:
        text.append(
            "A quantitative meta-analysis could not yet be finalized because effect size and standard error data were not sufficiently available in the metadata. Full-text extraction is required."
        )

    if rob_rows:
        risk_counts = Counter(r.get("overall_risk", "Unclear") for r in rob_rows)
        text.append(f"Risk of bias distribution was: {', '.join([f'{k} ({v})' for k, v in risk_counts.items()])}.")
    else:
        text.append("Risk of bias assessment should be completed during full-text review.")

    return "\n".join(text)


def build_systematic_review_discussion(theme: str, records: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    gaps = build_gap_and_novelty(theme, records, meta_result)["gaps"] if "build_gap_and_novelty" in globals() else []
    ev = evidence_strength(records, meta_result, rob_rows) if "evidence_strength" in globals() else {"level": "Not assessed", "reason": ""}

    return (
        f"This systematic review shows that the evidence base on {theme} is developing but still requires careful interpretation. "
        f"The bibliographic results indicate the main publication sources, research themes, and metadata quality, while the screening results clarify which studies are eligible for deeper review. "
        f"The main gaps identified are: {', '.join(gaps) if gaps else 'limited reporting consistency and incomplete quantitative data'}. "
        f"The current evidence strength is categorized as {ev['level']}. {ev['reason']} "
        f"Future studies should improve transparent reporting of methods, sample characteristics, outcome measures, and quantitative statistics needed for meta-analysis."
    )


def build_systematic_review_draft(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    framework = infer_review_framework(theme)
    searches = build_search_string(theme) if "build_search_string" in globals() else {"combined": theme}

    title = f"Systematic Review of {theme.title()}: Evidence Mapping and Meta-Analytic Readiness"

    return f"""{title}

ABSTRACT
Background: Research on {theme} has expanded across multiple disciplines and databases, creating a need for structured evidence synthesis.
Objective: This systematic review aims to identify, screen, and synthesize studies related to {theme}, while assessing the readiness of the evidence base for meta-analysis.
Methods: A structured search was conducted using bibliographic sources available in the application and recommended manual databases. Records were deduplicated, screened using predefined eligibility criteria, and synthesized using bibliographic and systematic review procedures. The review framework used was {framework['framework']}. The main search string was: {searches.get('combined', theme)}.
Results: {build_systematic_review_results_narrative(theme, records, screened, meta_studies, rob_rows)}
Conclusion: The systematic review provides a structured overview of the evidence base, identifies key gaps, and prepares the foundation for quantitative synthesis where effect size data are available.

1. INTRODUCTION
Research on {theme} is increasingly important because it connects theoretical development, empirical evidence, and practical implementation. However, existing studies are often distributed across multiple databases and use different designs, populations, outcomes, and reporting standards. A systematic review is therefore needed to identify relevant studies, assess their eligibility, summarize their characteristics, and determine whether the evidence can support meta-analysis.

2. METHODS
2.1 Review Design
This study was designed as a systematic review with bibliographic mapping and meta-analysis preparation. The review followed a PRISMA-oriented workflow consisting of identification, screening, eligibility assessment, inclusion, data extraction, risk of bias assessment, and synthesis.

2.2 Review Framework
The review used the {framework['framework']} framework:
{format_bullets([f"{k}: {v}" for k, v in framework['fields'].items()])}

2.3 Search Strategy
The search strategy combined the main topic terms with methodological and evidence synthesis terms. The recommended search string was:
{searches.get('combined', theme)}

2.4 Eligibility Criteria
{format_bullets(build_inclusion_exclusion(theme)['inclusion'])}

Exclusion criteria:
{format_bullets(build_inclusion_exclusion(theme)['exclusion'])}

2.5 Study Selection
Records were screened based on title, abstract, DOI availability, year, indexing indicators, and relevance to the review question. Each record was categorized as Included, Excluded, or Maybe. Full-text review is recommended for all Included and Maybe studies.

2.6 Data Extraction
The extraction process covered bibliographic data, study characteristics, population, intervention/exposure, comparison, outcome, effect size data, and risk of bias domains.

2.7 Risk of Bias
Risk of bias was assessed using domains related to randomization/sampling, blinding/objective measurement, incomplete data, selective reporting, confounding control, and sample size adequacy.

2.8 Synthesis
A narrative synthesis was used for all included studies. Meta-analysis was conducted only when effect size and standard error or calculable raw data were available.

3. RESULTS
{build_systematic_review_results_narrative(theme, records, screened, meta_studies, rob_rows)}

4. DISCUSSION
{build_systematic_review_discussion(theme, records, meta_studies, rob_rows)}

5. LIMITATIONS
{format_bullets(build_limitations(theme, records, meta_result) if "build_limitations" in globals() else ["The review depends on database coverage and metadata completeness."])}

6. CONCLUSION
{build_conclusion_draft(theme, records, meta_result) if "build_conclusion_draft" in globals() else f"This systematic review summarizes the evidence base on {theme} and identifies directions for future research."}

PRISMA CHECKLIST
{format_bullets([f"{x['section']}: {x['item']}" for x in build_prisma_checklist()])}
"""


def render_systematic_review_tab():
    st.subheader("📋 Systematic Review")
    records = st.session_state.theme_records or st.session_state.records
    screened = st.session_state.screened
    meta_studies = st.session_state.meta_studies
    rob_rows = st.session_state.rob_rows
    theme = st.session_state.last_theme or st.text_input("Tema systematic review", value="precision livestock farming", key="sysrev_theme")

    framework = infer_review_framework(theme)
    st.write("### Framework Review")
    st.info(f"Framework yang disarankan: **{framework['framework']}**")
    st.dataframe([{"element": k, "description": v} for k, v in framework["fields"].items()], use_container_width=True)

    tab_protocol, tab_prisma, tab_draft, tab_export = st.tabs(["🧭 Protokol", "✅ PRISMA Checklist", "📄 Draft", "📤 Export"])

    with tab_protocol:
        protocol = build_systematic_review_protocol(theme, records, screened)
        st.text_area("Protokol systematic review", value=protocol, height=560)

    with tab_prisma:
        checklist = build_prisma_checklist()
        st.dataframe(checklist, use_container_width=True, height=520)
        st.info("Checklist ini adalah template praktis. Sesuaikan dengan pedoman PRISMA terbaru dan ketentuan jurnal tujuan.")

    with tab_draft:
        draft = build_systematic_review_draft(theme, records, screened, meta_studies, rob_rows)
        st.text_area("Draft systematic review", value=draft, height=700)

    with tab_export:
        protocol = build_systematic_review_protocol(theme, records, screened)
        draft = build_systematic_review_draft(theme, records, screened, meta_studies, rob_rows)
        checklist = build_prisma_checklist()
        st.download_button("📥 Download Protokol Systematic Review TXT", data=protocol.encode("utf-8"), file_name="protokol_systematic_review.txt", mime="text/plain", use_container_width=True)
        st.download_button("📥 Download Draft Systematic Review TXT", data=draft.encode("utf-8"), file_name="draft_systematic_review.txt", mime="text/plain", use_container_width=True)
        st.download_button("📥 Download PRISMA Checklist CSV", data=safe_csv(checklist, ["section", "item", "status"]), file_name="prisma_checklist.csv", mime="text/csv", use_container_width=True)
        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download PRISMA Checklist Excel",
                data=rows_to_xlsx(checklist, ["section", "item", "status"], "PRISMA Checklist"),
                file_name="prisma_checklist.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )



# =========================================================
# Q-Level Review Studio: collect, analyze, write, submit
# =========================================================
def calc_completeness_status(value: float) -> str:
    if value >= 80:
        return "Ready"
    if value >= 60:
        return "Almost ready"
    if value >= 40:
        return "Developing"
    return "Needs work"


def build_data_collection_plan(theme: str) -> List[Dict[str, str]]:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    variants = build_query_variants(theme) if "build_query_variants" in globals() else [theme]
    searches = build_search_string(theme) if "build_search_string" in globals() else {"combined": theme}
    return [
        {
            "step": "1. Define scope",
            "task": "Tetapkan population/problem, exposure/intervention, comparison, outcome, tahun, jenis publikasi, dan bahasa.",
            "output": "Review question + eligibility criteria",
            "tool_tab": "Systematic Review",
        },
        {
            "step": "2. Search public APIs",
            "task": f"Gunakan query utama: {variants[0] if variants else theme}",
            "output": "Dataset awal dari Crossref, OpenAlex, Semantic Scholar, PLOS, DOAJ, PubMed, Europe PMC, arXiv, DataCite",
            "tool_tab": "Workflow Tema",
        },
        {
            "step": "3. Search subscription databases",
            "task": "Gunakan Scopus, Web of Science, CAB Abstracts, IEEE Xplore, ScienceDirect, SpringerLink, AGRIS/FAO, PubAg/USDA sesuai tema.",
            "output": "Export Excel/RIS/BibTeX dari database berlangganan/manual",
            "tool_tab": "Sumber Relevan + Bibliografi",
        },
        {
            "step": "4. Import and deduplicate",
            "task": "Upload semua hasil ekspor ke aplikasi, lalu gabungkan dan deduplikasi berdasarkan DOI/judul.",
            "output": "Master bibliographic dataset",
            "tool_tab": "Bibliografi",
        },
        {
            "step": "5. Screen records",
            "task": "Screening title/abstract, beri status Included, Excluded, Maybe, dan alasan.",
            "output": "PRISMA screening table",
            "tool_tab": "PRISMA & Screening",
        },
        {
            "step": "6. Full-text extraction",
            "task": "Buka artikel eligible dan isi Excel ekstraksi: population, intervention/exposure, comparison, outcome, effect size/SE atau data mentah.",
            "output": "Data extraction + meta-analysis Excel",
            "tool_tab": "Meta-Analysis",
        },
        {
            "step": "7. Quality assessment",
            "task": "Nilai risk of bias/quality assessment berdasarkan full-text.",
            "output": "Risk of bias table",
            "tool_tab": "Risk of Bias",
        },
        {
            "step": "8. Synthesis and writing",
            "task": "Gunakan hasil bibliografi, systematic review, meta-analysis, dan insight akhir untuk membuat draft naskah.",
            "output": "Draft review article + Q-level checklist",
            "tool_tab": "Jurnal Review Builder + Q-Level Toolkit",
        },
    ]


def build_analysis_decision_tree(records: List[Dict[str, str]], meta_studies: List[Dict[str, object]]) -> List[Dict[str, str]]:
    n_records = len(records)
    k_meta = len(meta_studies)
    if k_meta >= 10:
        meta_action = "Lakukan random-effects meta-analysis, subgroup analysis, sensitivity analysis, dan publication bias."
        design = "Systematic review + bibliometric analysis + meta-analysis"
    elif k_meta >= 3:
        meta_action = "Lakukan meta-analysis eksploratif, laporkan heterogenitas, sensitivity, dan keterbatasan jumlah studi."
        design = "Systematic review + meta-analysis terbatas"
    elif k_meta >= 1:
        meta_action = "Jangan jadikan pooled effect sebagai temuan utama. Tambahkan studi eligible atau gunakan narrative synthesis."
        design = "Systematic review + narrative synthesis dengan meta-analysis readiness"
    else:
        meta_action = "Fokus pada systematic review, bibliometric mapping, dan evidence gap. Isi full-text extraction sebelum meta-analysis."
        design = "Systematic bibliometric review / scoping-systematic review"
    return [
        {"condition": f"Jumlah referensi relevan = {n_records}", "decision": "Gunakan untuk bibliographic mapping dan PRISMA screening.", "recommended_design": design},
        {"condition": f"Studi dengan effect size valid = {k_meta}", "decision": meta_action, "recommended_design": design},
        {"condition": "Heterogenitas tinggi", "decision": "Gunakan subgroup, moderator, atau sensitivity analysis; jelaskan sumber variasi.", "recommended_design": "Meta-analysis dengan cautious interpretation"},
        {"condition": "Risk of bias banyak high/unclear", "decision": "Turunkan strength of evidence; lakukan analisis sensitivitas tanpa studi high risk.", "recommended_design": "Systematic review dengan critical appraisal kuat"},
        {"condition": "Metadata DOI/abstract rendah", "decision": "Perkuat data dari Scopus/WoS/full-text sebelum submit Q-level.", "recommended_design": "Data cleaning and enrichment phase"},
    ]


def build_missing_inputs(records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    total = len(records)
    m = get_metrics(records) if records else {"with_doi": 0, "with_abstract": 0, "with_keywords": 0, "need": 0}
    missing = []

    def add(area, issue, impact, action, priority):
        missing.append({"area": area, "issue": issue, "impact": impact, "recommended_action": action, "priority": priority})

    if total == 0:
        add("Data collection", "Belum ada dataset bibliografi.", "Tidak bisa membuat review berbasis data.", "Jalankan Workflow Tema dan upload ekspor database manual.", "High")
        return missing

    if total < 30:
        add("Bibliography size", f"Referensi relevan baru {total}.", "Untuk jurnal Q-level, cakupan literatur mungkin dianggap kurang.", "Tambahkan Scopus, WoS, CAB Abstracts, AGRIS/PubAg, IEEE/ScienceDirect sesuai topik.", "High")

    if pct(m["with_doi"], total) < 70:
        add("DOI coverage", f"DOI coverage {pct(m['with_doi'], total):.1f}%.", "Deduplikasi dan pelacakan sitasi kurang kuat.", "Lengkapi DOI dari Crossref/OpenAlex/full-text.", "Medium")

    if pct(m["with_abstract"], total) < 60:
        add("Abstract coverage", f"Abstract coverage {pct(m['with_abstract'], total):.1f}%.", "Screening otomatis dan narrative synthesis kurang akurat.", "Lengkapi abstrak dari database/full-text.", "High")

    if not screened:
        add("PRISMA", "Screening belum dibuat.", "Tidak sesuai kaidah systematic review.", "Jalankan tab PRISMA & Screening.", "High")

    if not meta_studies:
        add("Meta-analysis", "Belum ada effect size/SE valid.", "Tidak bisa menghasilkan pooled effect.", "Download Excel meta-analysis, isi dari full-text, upload kembali.", "High")
    elif len(meta_studies) < 3:
        add("Meta-analysis", f"Hanya {len(meta_studies)} studi valid.", "Publication bias dan robustness belum kuat.", "Tambah studi eligible atau posisikan sebagai narrative synthesis.", "Medium")

    if not rob_rows:
        add("Risk of bias", "Risk of bias belum diisi.", "Kualitas bukti tidak dapat dinilai.", "Isi domain risk of bias berdasarkan full-text.", "High")
    else:
        unclear = sum(1 for r in rob_rows if "Unclear" in r.get("overall_risk", ""))
        if unclear > len(rob_rows) * 0.4:
            add("Risk of bias", "Banyak studi masih unclear.", "Reviewer Q-level dapat meminta critical appraisal lebih rinci.", "Lengkapi penilaian risk of bias dari metode artikel.", "Medium")

    return missing


def build_qjournal_target_fit(theme: str, records: List[Dict[str, str]], meta_studies: List[Dict[str, object]]) -> List[Dict[str, str]]:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    lower = theme.lower()
    candidates = []

    if "livestock" in lower or "animal" in lower or "veterinary" in lower:
        candidates += [
            {"journal_area": "Animal science / veterinary", "fit": "High", "example_scope": "Animals, animal welfare, livestock systems, veterinary science", "what_to_strengthen": "Risk of bias, animal species classification, welfare/health outcomes."},
            {"journal_area": "Precision agriculture / smart farming", "fit": "High", "example_scope": "Sensors, IoT, machine learning, digital agriculture", "what_to_strengthen": "Technology taxonomy, sensor types, AI models, outcome metrics."},
            {"journal_area": "Agricultural systems", "fit": "Medium-High", "example_scope": "Farm management, productivity, sustainability", "what_to_strengthen": "Practical implications, adoption barriers, economic/environmental outcomes."},
        ]

    candidates += [
        {"journal_area": "Systematic review / evidence synthesis", "fit": "Medium", "example_scope": "Systematic reviews, meta-analysis, evidence synthesis", "what_to_strengthen": "PRISMA, PROSPERO/registration statement, full search strategy, ROB."},
        {"journal_area": "Bibliometrics / scientometrics", "fit": "Medium", "example_scope": "Science mapping, bibliometric methods", "what_to_strengthen": "Network analysis, co-word/co-citation, VOSviewer/CiteSpace export."},
        {"journal_area": "Interdisciplinary applied science", "fit": "Medium", "example_scope": "Applied technology and cross-disciplinary evidence", "what_to_strengthen": "Clear novelty, broad implications, strong discussion."},
    ]

    return candidates


def build_manuscript_section_prompts(theme: str) -> List[Dict[str, str]]:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    return [
        {"section": "Abstract", "writing_prompt": f"Write a structured abstract for a systematic review and bibliometric/meta-analysis on {theme}. Include background, objective, methods, results, and conclusion with key numbers from the dataset."},
        {"section": "Introduction", "writing_prompt": f"Explain why {theme} is important, what previous studies have missed, and why an integrated systematic review, bibliometric analysis, and meta-analysis is needed."},
        {"section": "Methods", "writing_prompt": f"Describe databases, search strings, PRISMA screening, inclusion-exclusion criteria, data extraction, risk of bias, and synthesis methods for {theme}."},
        {"section": "Results", "writing_prompt": f"Report PRISMA flow, publication trends, source distribution, keyword patterns, bibliographic insight, meta-analysis results, heterogeneity, and risk of bias for {theme}."},
        {"section": "Discussion", "writing_prompt": f"Interpret the findings on {theme}; compare with prior literature; explain gaps, novelty, implications, heterogeneity, and limitations."},
        {"section": "Conclusion", "writing_prompt": f"Summarize the main findings and practical/research implications of the review on {theme} without introducing new results."},
    ]


def build_qlevel_improvement_report(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> str:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    readiness = qlevel_readiness_score(theme, records, screened, meta_studies, rob_rows) if "qlevel_readiness_score" in globals() else {"score": 0, "label": "Needs work", "components": {}, "missing": []}
    missing = build_missing_inputs(records, screened, meta_studies, rob_rows)
    target_fit = build_qjournal_target_fit(theme, records, meta_studies)

    lines = [
        "Q-LEVEL REVIEW STUDIO REPORT",
        "",
        f"Theme: {theme}",
        f"Q-level readiness: {readiness.get('score', 0)}/100 ({readiness.get('label', '-')})",
        "",
        "1. What is already strong",
    ]

    components = readiness.get("components", {})
    strong = [f"{k}: {v}/100" for k, v in components.items() if isinstance(v, (int, float)) and v >= 70]
    lines += [f"- {x}" for x in strong] if strong else ["- Belum ada komponen yang kuat secara skor; prioritaskan pengumpulan data dan screening."]

    lines += ["", "2. What is still missing / weak"]
    if missing:
        for item in missing:
            lines.append(f"- [{item['priority']}] {item['area']}: {item['issue']} Impact: {item['impact']} Action: {item['recommended_action']}")
    else:
        lines.append("- Tidak ada kekurangan besar terdeteksi. Lanjutkan polishing dan validasi manual.")

    lines += ["", "3. Recommended target journal fit"]
    for row in target_fit:
        lines.append(f"- {row['journal_area']} ({row['fit']}): {row['example_scope']}. Strengthen: {row['what_to_strengthen']}")

    lines += ["", "4. Data collection next steps"]
    for step in build_data_collection_plan(theme):
        lines.append(f"- {step['step']}: {step['task']} Output: {step['output']}")

    lines += ["", "5. Analysis decision tree"]
    for row in build_analysis_decision_tree(records, meta_studies):
        lines.append(f"- If {row['condition']}: {row['decision']} Recommended design: {row['recommended_design']}")

    lines += ["", "6. Manuscript writing prompts"]
    for row in build_manuscript_section_prompts(theme):
        lines.append(f"- {row['section']}: {row['writing_prompt']}")

    lines += ["", "7. Final recommendation"]
    if readiness.get("score", 0) >= 80:
        lines.append("- Naskah sudah mendekati standar Q-level. Fokus pada validasi manual, bahasa akademik, figure berkualitas, dan kesesuaian target jurnal.")
    elif readiness.get("score", 0) >= 60:
        lines.append("- Naskah sudah cukup kuat sebagai draft, tetapi perlu memperkuat PRISMA, risk of bias, metadata, dan/atau effect size sebelum submit ke Q1/Q2.")
    else:
        lines.append("- Jangan submit dulu ke jurnal Q-level. Perkuat dataset, screening, full-text extraction, ROB, dan draft naratif terlebih dahulu.")

    return "\n".join(lines)


def render_review_studio_tab():
    st.subheader("🚀 Q-Level Review Studio")
    st.caption("Pusat kerja untuk mengumpulkan data, menganalisis, menulis draft, dan mengecek kesiapan naskah jurnal Q-level.")

    records = st.session_state.get("theme_records", []) or st.session_state.get("records", [])
    screened = st.session_state.get("screened", [])
    meta_studies = st.session_state.get("meta_studies", [])
    rob_rows = st.session_state.get("rob_rows", [])
    default_theme = st.session_state.get("last_theme", "") or "precision livestock farming"

    theme = st.text_input(
        "Tema penelitian",
        value=default_theme,
        key="studio_theme_fixed",
        help="Isi tema di sini jika belum menjalankan Workflow Tema."
    )

    # Build fallback/demo context so the tab is never empty.
    demo_records = [
        {
            "title": f"Review-ready record template for {theme}",
            "authors": "Author Example",
            "year": "2024",
            "journal": "Target Journal",
            "publisher": "",
            "doi": "",
            "url": "",
            "database": "Manual",
            "impact_factor": "",
            "indexing_status": "Needs verification",
            "verification_reason": "Template record for planning",
            "abstract": f"This placeholder helps plan a systematic review on {theme}.",
            "keywords": theme,
            "notes": "Replace with real records from Workflow Tema or Upload.",
            "theme_relevance_score": "1.00",
        }
    ]

    analysis_records = records if records else demo_records
    analysis_screened = screened if screened else auto_screen(analysis_records, {
        "min_year": 2020,
        "max_year": 2026,
        "only_doi": False,
        "must_have_abstract": False,
        "only_indexed": False,
        "include_terms": "",
        "exclude_terms": "",
    })

    if "qlevel_readiness_score" in globals():
        readiness = qlevel_readiness_score(theme, records, screened, meta_studies, rob_rows)
    else:
        readiness = {"score": 0, "label": "Needs work", "components": {}}

    missing = build_missing_inputs(records, screened, meta_studies, rob_rows)

    if not records:
        st.warning(
            "Dataset asli belum ada. Review Studio tetap menampilkan template dan rencana kerja. "
            "Untuk hasil yang mengikuti data asli, jalankan tab Workflow Tema atau upload bibliografi terlebih dahulu."
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Readiness", f"{readiness.get('score', 0)}/100")
    c2.metric("Status", readiness.get("label", "-"))
    c3.metric("Referensi", len(records))
    c4.metric("Studi Meta", len(meta_studies))

    tab_collect, tab_analyze, tab_write, tab_qlevel, tab_export = st.tabs([
        "📥 Kumpulkan Data", "📊 Analisa Data", "✍️ Tulis Draft", "🏆 Q-Level Fit", "📤 Export"
    ])

    with tab_collect:
        st.write("### Rencana Pengumpulan Data")
        plan = build_data_collection_plan(theme)
        st.dataframe(plan, use_container_width=True, height=420)

        st.write("### Query yang Disarankan")
        if "build_query_variants" in globals():
            for q in build_query_variants(theme):
                st.code(q)
        elif "build_search_string" in globals():
            st.code(build_search_string(theme).get("combined", theme))
        else:
            st.code(theme)

        st.write("### Data yang Masih Kurang")
        if missing:
            st.dataframe(missing, use_container_width=True, height=360)
        else:
            st.success("Tidak ada kekurangan besar pada input data. Lanjutkan validasi manual dan polishing naskah.")

        st.info(
            "Untuk Q-level, usahakan data berasal dari sumber publik + database manual seperti Scopus, Web of Science, "
            "CAB Abstracts/CABI, AGRIS/FAO, PubAg/USDA, IEEE Xplore, ScienceDirect, dan SpringerLink jika tersedia."
        )

    with tab_analyze:
        st.write("### Decision Tree Analisis")
        st.dataframe(build_analysis_decision_tree(records, meta_studies), use_container_width=True, height=320)

        st.write("### Komponen Kesiapan")
        if readiness.get("components"):
            st.bar_chart(readiness["components"])
        else:
            st.info("Komponen kesiapan akan muncul setelah dataset tersedia.")

        st.write("### Masukan Analisis")
        if missing:
            for item in missing:
                st.write(f"- **{item['area']}**: {item['recommended_action']}")
        else:
            st.write("- Dataset sudah cukup baik untuk dilanjutkan ke drafting dan validasi manual.")

        if meta_studies:
            meta_result = run_meta(meta_studies)
            st.write("### Ringkasan Meta-Analysis")
            if meta_result.get("k", 0):
                main = meta_result["random"]
                h = meta_result["heterogeneity"]
                a, b, c = st.columns(3)
                a.metric("Pooled effect", f"{main['pooled']:.4f}")
                b.metric("95% CI", f"{main['ci'][0]:.3f} – {main['ci'][1]:.3f}")
                c.metric("I²", f"{h['I2']:.1f}%")
        else:
            st.info("Belum ada studi effect size valid. Isi Excel meta-analysis dari full-text jika ingin pooled effect.")

    with tab_write:
        st.write("### Writing Prompts per Bagian Naskah")
        prompts = build_manuscript_section_prompts(theme)
        st.dataframe(prompts, use_container_width=True, height=280)

        st.write("### Draft Cepat")
        draft_options = []
        if "build_journal_review_draft" in globals():
            draft_options.append("Journal Review Draft")
        if "build_systematic_review_draft" in globals():
            draft_options.append("Systematic Review Draft")
        if "build_research_materials_report" in globals():
            draft_options.append("Bahan Penelitian Lengkap")

        chosen = st.selectbox("Pilih draft", draft_options or ["Template umum"])

        if chosen == "Journal Review Draft" and "build_journal_review_draft" in globals():
            draft_text = build_journal_review_draft(theme, analysis_records, analysis_screened, meta_studies, rob_rows)
        elif chosen == "Systematic Review Draft" and "build_systematic_review_draft" in globals():
            draft_text = build_systematic_review_draft(theme, analysis_records, analysis_screened, meta_studies, rob_rows)
        elif chosen == "Bahan Penelitian Lengkap" and "build_research_materials_report" in globals():
            draft_text = build_research_materials_report(theme, analysis_records, analysis_screened, meta_studies, rob_rows)
        else:
            draft_text = f"""DRAFT REVIEW TEMPLATE

Title:
Systematic Review of {theme.title()}: Evidence Mapping and Q-Level Review Preparation

Abstract:
This review aims to map and synthesize literature on {theme}. The study follows a PRISMA-oriented systematic review workflow, combining bibliographic mapping, eligibility screening, risk of bias preparation, and meta-analysis readiness assessment.

Introduction:
Research on {theme} requires structured synthesis because the literature is distributed across databases, journals, and methodological traditions.

Methods:
The review should report data sources, search strings, inclusion-exclusion criteria, study selection, data extraction, risk of bias, and synthesis strategy.

Results:
Report PRISMA counts, publication trends, dominant sources, keywords, included studies, and meta-analysis results if available.

Discussion:
Discuss main findings, gap, novelty, implications, heterogeneity, limitations, and future research.

Conclusion:
Summarize the contribution and evidence readiness of the field.
"""
        st.text_area("Draft", value=draft_text, height=560)

    with tab_qlevel:
        st.write("### Target Journal Fit")
        st.dataframe(build_qjournal_target_fit(theme, records, meta_studies), use_container_width=True, height=300)

        st.write("### Strategi Agar Sesuai Jurnal Q-Level")
        strategies = [
            "Gunakan PRISMA sebagai backbone metode dan tampilkan flow diagram/counts.",
            "Cantumkan full search string, database, tanggal pencarian, dan kriteria eligibility.",
            "Pastikan data Scopus/WoS atau database domain utama ikut diimpor jika tersedia.",
            "Tambahkan tabel karakteristik studi dan risk of bias.",
            "Jangan memaksakan meta-analysis jika effect size belum cukup; gunakan narrative synthesis dan meta-analysis readiness.",
            "Perkuat novelty statement: bukan hanya mapping, tetapi evidence-readiness dan synthesis pipeline.",
            "Gunakan figure berkualitas: PRISMA flow, publication trend, keyword map, forest plot jika ada.",
            "Bahas heterogenitas, keterbatasan, dan implikasi secara kritis.",
            "Validasi ulang hasil meta-analysis dengan software statistik khusus sebelum submit.",
        ]
        for s in strategies:
            st.write(f"- {s}")

        if "build_qlevel_checklist" in globals():
            st.write("### Checklist Q-Level")
            st.dataframe(build_qlevel_checklist(theme, records, screened, meta_studies, rob_rows), use_container_width=True, height=360)

    with tab_export:
        report = build_qlevel_improvement_report(theme, records, screened, meta_studies, rob_rows)
        st.text_area("Laporan penyempurnaan Q-level", value=report, height=520)
        st.download_button(
            "📥 Download Q-Level Review Studio Report TXT",
            data=report.encode("utf-8"),
            file_name="qlevel_review_studio_report.txt",
            mime="text/plain",
            use_container_width=True,
        )
        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download Data Missing/Action Plan Excel",
                data=rows_to_xlsx(missing, ["area", "issue", "impact", "recommended_action", "priority"], "Action Plan"),
                file_name="qlevel_action_plan.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                disabled=not bool(missing),
            )
        else:
            st.download_button(
                "📥 Download Data Missing/Action Plan CSV",
                data=safe_csv(missing, ["area", "issue", "impact", "recommended_action", "priority"]),
                file_name="qlevel_action_plan.csv",
                mime="text/csv",
                use_container_width=True,
                disabled=not bool(missing),
            )




# =========================================================
# Practical Meta-Analysis Guide - Visible in Panduan
# =========================================================
def build_meta_analysis_steps_guide(theme: str) -> str:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    if "infer_review_framework" in globals():
        framework = infer_review_framework(theme)
    else:
        framework = {
            "framework": "PICO",
            "fields": {
                "Population": "Populasi/subjek penelitian.",
                "Intervention": "Intervensi, paparan, teknologi, atau perlakuan.",
                "Comparison": "Pembanding, kontrol, baseline, atau metode konvensional.",
                "Outcome": "Hasil akhir yang diukur."
            }
        }

    fields_text = "\n".join([f"- {k}: {v}" for k, v in framework.get("fields", {}).items()]) or "- Population, Intervention/Exposure, Comparison, Outcome"

    return f"""PANDUAN PRAKTIS META-ANALISIS

Tema:
{theme}

Meta-analisis adalah cara ilmiah untuk menggabungkan data dari berbagai penelitian independen guna mendapatkan satu kesimpulan statistik yang lebih kuat. Secara sederhana, meta-analisis seperti menyatukan kepingan puzzle dari berbagai studi agar terlihat gambaran besarnya.

1. MENENTUKAN PERTANYAAN PENELITIAN

Gunakan kerangka {framework.get('framework', 'PICO')}.

Elemen pertanyaan:
{fields_text}

Untuk PICO:
- P atau Population: siapa populasi/subjek yang diteliti.
- I atau Intervention/Exposure: intervensi, teknologi, perlakuan, atau paparan yang diuji.
- C atau Comparison: pembanding, kontrol, baseline, atau metode konvensional.
- O atau Outcome: hasil akhir yang ingin diukur.

Contoh untuk precision livestock farming:
- P: peternakan sapi perah, sapi potong, unggas, kambing, atau ternak lain.
- I: sensor, IoT, computer vision, machine learning, wearable device, automated monitoring.
- C: metode konvensional, tanpa sensor, manual monitoring, atau baseline.
- O: kesehatan ternak, animal welfare, deteksi penyakit, produktivitas, milk yield, feed efficiency, akurasi deteksi.

2. MELAKUKAN PENELUSURAN LITERATUR

Gunakan sumber akademik relevan:
- PubMed untuk veterinary/animal health.
- Scopus dan Web of Science untuk artikel Q-level.
- Crossref dan OpenAlex untuk metadata DOI.
- Semantic Scholar untuk AI, machine learning, dan computer vision.
- PLOS, DOAJ, Europe PMC untuk open-access/life sciences.
- CAB Abstracts/CABI, AGRIS/FAO, USDA PubAg untuk agriculture/livestock.
- IEEE Xplore untuk IoT, sensor, dan embedded system.
- ScienceDirect, SpringerLink, Wiley, Taylor & Francis untuk jurnal bereputasi.

Gunakan Boolean:
- AND untuk menggabungkan konsep.
- OR untuk sinonim.
- tanda kutip untuk frasa spesifik.

Contoh search string:
("precision livestock farming" OR "smart livestock farming" OR "precision dairy farming" OR "livestock monitoring" OR "animal welfare monitoring") AND (sensor* OR IoT OR "machine learning" OR "artificial intelligence" OR "computer vision" OR wearable)

Catat:
- database yang digunakan.
- tanggal pencarian.
- jumlah artikel dari tiap database.
- search string yang dipakai.
- jumlah duplikasi.

3. SELEKSI STUDI / SCREENING

Tidak semua artikel bibliografi bisa masuk meta-analisis. Gunakan kriteria inklusi-eksklusi.

Kriteria inklusi umum:
- artikel sesuai tema.
- studi empiris/kuantitatif.
- memiliki data outcome.
- memiliki effect size, standard error, confidence interval, mean-SD-n, event-total, OR/RR, atau korelasi.
- tahun sesuai batas penelitian.

Kriteria eksklusi umum:
- tidak sesuai tema.
- duplikasi.
- editorial/opinion/letter tanpa data empiris.
- review konseptual tanpa data kuantitatif.
- tidak tersedia full-text atau data effect size.
- outcome terlalu berbeda dan tidak bisa dibandingkan.

Gunakan PRISMA untuk melaporkan:
- records identified.
- records after duplicates removed.
- records screened.
- full-text assessed.
- records excluded with reasons.
- studies included in review.
- studies included in meta-analysis.

4. EKSTRAKSI DATA DAN PENILAIAN KUALITAS

Ekstraksi data minimal:
- nama penulis.
- tahun.
- judul.
- jurnal.
- negara/lokasi.
- populasi.
- intervensi/paparan.
- pembanding.
- outcome.
- jumlah sampel.
- mean, SD, n.
- event dan total.
- odds ratio atau risk ratio.
- korelasi r dan n.
- confidence interval.
- standard error.
- catatan metode.

Risk of bias / quality assessment:
- randomization atau sampling.
- blinding/objective measurement.
- incomplete data.
- selective reporting.
- confounding control.
- sample size adequacy.

Contoh alat:
- Cochrane Risk of Bias untuk RCT.
- Newcastle-Ottawa Scale untuk studi observasional.
- QUADAS-2 untuk studi akurasi diagnostik.
- ROBINS-I untuk non-randomized intervention studies.
- JBI Critical Appraisal untuk berbagai desain studi.

5. ANALISIS STATISTIK

Meta-analisis membutuhkan effect size dan standard error.

Jenis effect size:
- SMD/Hedges g untuk data mean dan SD dua kelompok.
- log Odds Ratio untuk data event/non-event.
- log Risk Ratio untuk data event/total.
- Fisher z untuk korelasi.
- effect_size + standard_error jika sudah tersedia di artikel.

Model analisis:
- Fixed-effect model: digunakan jika studi dianggap sangat mirip dan variasi hanya karena error sampling.
- Random-effects model: digunakan jika studi berbeda dalam populasi, metode, outcome, atau konteks. Ini lebih sering dipakai dalam systematic review lintas studi.

Heterogenitas:
- Q menunjukkan variasi antar studi.
- tau² menunjukkan varians antar studi.
- I² menunjukkan persentase variasi yang disebabkan heterogenitas.
- I² < 30%: rendah.
- I² 30–60%: sedang.
- I² > 60%: tinggi.

Jika I² tinggi:
- cek subgroup.
- cek desain studi.
- cek outcome.
- cek jenis populasi.
- lakukan sensitivity analysis.
- jelaskan heterogenitas dalam pembahasan.

6. FOREST PLOT

Forest plot menampilkan:
- effect size tiap studi.
- confidence interval tiap studi.
- bobot studi.
- pooled effect.
- garis no-effect.
- diamond sebagai hasil gabungan.

Interpretasi:
- jika CI pooled tidak melewati nol untuk SMD/log effect, hasil signifikan.
- jika CI pooled tidak melewati 1 untuk OR/RR pada skala asli, hasil signifikan.
- studi dengan CI lebar biasanya memiliki sampel kecil atau ketidakpastian tinggi.

7. PUBLICATION BIAS

Publication bias terjadi karena studi signifikan lebih mudah terbit daripada studi non-signifikan.

Cara menilai:
- Funnel plot.
- Egger test.
- trim-and-fill jika tersedia.
- cek grey literature atau preprint.
- cek apakah studi kecil cenderung menghasilkan efek besar.

Catatan:
- Funnel plot kurang kuat jika jumlah studi kecil.
- Egger test umumnya lebih bermakna jika studi cukup banyak.
- Jika studi kurang dari 10, jelaskan keterbatasan publication bias.

8. PELAPORAN HASIL

Laporan meta-analisis sebaiknya memuat:
- pertanyaan penelitian.
- database dan search string.
- PRISMA flow.
- kriteria inklusi-eksklusi.
- karakteristik studi.
- risk of bias.
- metode effect size.
- fixed-effect dan random-effects.
- pooled effect.
- 95% confidence interval.
- p-value.
- Q, tau², I².
- forest plot.
- publication bias.
- sensitivity analysis.
- keterbatasan.
- implikasi.
- kesimpulan.

9. CATATAN UNTUK JURNAL Q-LEVEL

Untuk jurnal Q-level:
- jangan hanya menampilkan hasil otomatis.
- validasi full-text wajib.
- risk of bias wajib jelas.
- PRISMA harus lengkap.
- search string harus transparan.
- alasan eksklusi harus tersedia.
- meta-analysis tidak boleh dipaksakan jika effect size tidak cukup.
- jika data effect size kurang, gunakan narrative synthesis dan meta-analysis readiness.
- gunakan software statistik khusus untuk validasi akhir seperti R metafor/meta, RevMan, Stata, JASP, atau Jamovi.
"""


def build_meta_analysis_checklist_table(theme: str) -> List[Dict[str, str]]:
    return [
        {"step": "1", "stage": "Pertanyaan penelitian", "required_output": "PICO/PECO/SPIDER + research question", "app_tab": "Systematic Review", "status": "Perlu dicek"},
        {"step": "2", "stage": "Literature search", "required_output": "Database, search string, tanggal pencarian, jumlah artikel", "app_tab": "Workflow Tema + Sumber Relevan", "status": "Perlu dicek"},
        {"step": "3", "stage": "Deduplication", "required_output": "Record unik setelah duplikasi dihapus", "app_tab": "Bibliografi", "status": "Perlu dicek"},
        {"step": "4", "stage": "Screening", "required_output": "Included, Excluded, Maybe + alasan", "app_tab": "PRISMA & Screening", "status": "Perlu dicek"},
        {"step": "5", "stage": "PRISMA flow", "required_output": "Records identified, screened, excluded, included", "app_tab": "PRISMA & Screening", "status": "Perlu dicek"},
        {"step": "6", "stage": "Data extraction", "required_output": "Excel ekstraksi full-text", "app_tab": "Meta-Analysis", "status": "Perlu dicek"},
        {"step": "7", "stage": "Risk of bias", "required_output": "ROB table + overall risk", "app_tab": "Risk of Bias", "status": "Perlu dicek"},
        {"step": "8", "stage": "Effect size", "required_output": "SMD/log OR/log RR/Fisher z/effect size + SE", "app_tab": "Meta-Analysis", "status": "Perlu dicek"},
        {"step": "9", "stage": "Model analysis", "required_output": "Fixed-effect + random-effects", "app_tab": "Meta-Analysis", "status": "Perlu dicek"},
        {"step": "10", "stage": "Heterogeneity", "required_output": "Q, tau², I²", "app_tab": "Meta-Analysis", "status": "Perlu dicek"},
        {"step": "11", "stage": "Forest plot", "required_output": "Forest plot / table effect per study", "app_tab": "Meta-Analysis", "status": "Perlu dicek"},
        {"step": "12", "stage": "Publication bias", "required_output": "Funnel plot/Egger atau limitation statement", "app_tab": "Sensitivity & Bias", "status": "Perlu dicek"},
        {"step": "13", "stage": "Sensitivity analysis", "required_output": "Leave-one-out / robustness check", "app_tab": "Sensitivity & Bias", "status": "Perlu dicek"},
        {"step": "14", "stage": "Discussion", "required_output": "Interpretasi pooled effect, heterogenitas, ROB, limitation", "app_tab": "Jurnal Review Builder", "status": "Perlu dicek"},
    ]


def render_meta_analysis_guide_inside_panduan():
    st.divider()
    st.subheader("📘 Panduan Meta-Analisis")
    theme_default = st.session_state.get("last_theme", "") or "precision livestock farming"
    theme = st.text_input("Tema untuk panduan meta-analisis", value=theme_default, key="meta_guide_inside_panduan")

    tab_steps, tab_check = st.tabs(["🧭 Langkah Meta-Analisis", "✅ Checklist Meta-Analisis"])

    with tab_steps:
        guide = build_meta_analysis_steps_guide(theme)
        st.text_area("Panduan lengkap meta-analisis", value=guide, height=650)
        st.download_button(
            "📥 Download Panduan Meta-Analisis TXT",
            data=guide.encode("utf-8"),
            file_name="panduan_meta_analisis.txt",
            mime="text/plain",
            use_container_width=True,
        )

    with tab_check:
        checklist = build_meta_analysis_checklist_table(theme)
        st.dataframe(checklist, use_container_width=True, height=520)
        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download Checklist Meta-Analisis Excel",
                data=rows_to_xlsx(checklist, ["step", "stage", "required_output", "app_tab", "status"], "Checklist Meta"),
                file_name="checklist_meta_analisis.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.download_button(
                "📥 Download Checklist Meta-Analisis CSV",
                data=safe_csv(checklist, ["step", "stage", "required_output", "app_tab", "status"]),
                file_name="checklist_meta_analisis.csv",
                mime="text/csv",
                use_container_width=True,
            )



# =========================================================
# Research Assistant Hub - Visible in Panduan
# =========================================================
def research_stage_status(records, screened, meta_studies, rob_rows) -> List[Dict[str, str]]:
    total_records = len(records)
    stages = []

    def add(stage, status, evidence, next_action):
        stages.append({
            "stage": stage,
            "status": status,
            "evidence": evidence,
            "next_action": next_action
        })

    add(
        "1. Ide & Fokus Riset",
        "Ready" if st.session_state.get("last_theme") else "Needs theme",
        st.session_state.get("last_theme", "Tema belum tersimpan"),
        "Tentukan tema spesifik, misalnya precision livestock farming, smart dairy farming, atau animal welfare monitoring."
    )

    add(
        "2. Penelusuran Literatur",
        "Ready" if total_records >= 30 else "Developing" if total_records > 0 else "Not started",
        f"{total_records} referensi relevan tersedia.",
        "Perluas database: Scopus, WoS, PubMed, OpenAlex, Crossref, CAB Abstracts, AGRIS/FAO, PubAg, IEEE Xplore, ScienceDirect."
    )

    add(
        "3. Screening PRISMA",
        "Ready" if screened else "Not started",
        f"{len(screened)} record sudah memiliki status screening." if screened else "Belum ada tabel screening.",
        "Jalankan PRISMA & Screening, lalu cek alasan Included/Excluded/Maybe."
    )

    add(
        "4. Ekstraksi Data",
        "Ready" if meta_studies else "Needs full-text extraction",
        f"{len(meta_studies)} studi punya effect size valid." if meta_studies else "Belum ada effect size/SE valid.",
        "Download format Excel meta-analysis, isi dari full-text artikel, lalu upload kembali."
    )

    add(
        "5. Quality Assessment",
        "Ready" if rob_rows else "Not started",
        f"{len(rob_rows)} studi punya risk of bias row." if rob_rows else "Risk of bias belum diisi.",
        "Isi Risk of Bias berdasarkan full-text, bukan hanya metadata."
    )

    add(
        "6. Analisis & Sintesis",
        "Ready" if meta_studies and len(meta_studies) >= 2 else "Narrative only / developing",
        f"{len(meta_studies)} studi valid untuk meta-analysis.",
        "Jika studi < 3, gunakan narrative synthesis dan jelaskan keterbatasan publication bias."
    )

    add(
        "7. Draft Artikel",
        "Ready to draft" if total_records else "Needs data",
        "Draft generator tersedia di Jurnal Review Builder/Systematic Review.",
        "Gunakan Review Builder untuk abstract, methods, results, discussion, dan conclusion."
    )

    add(
        "8. Kesiapan Q-Level",
        "Check required",
        "Gunakan Q-Level Toolkit dan Review Studio.",
        "Pastikan PRISMA, ROB, search strategy, novelty, limitations, dan data extraction lengkap."
    )

    return stages


def build_research_question_matrix(theme: str) -> List[Dict[str, str]]:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    return [
        {
            "component": "Main research question",
            "content": f"What are the publication trends, evidence structure, and synthesis readiness of research on {theme}?",
            "output": "Main objective and article title"
        },
        {
            "component": "Bibliometric question",
            "content": f"How has research on {theme} developed based on year, source, journal, author, and keyword distribution?",
            "output": "Publication trend, source distribution, keyword map"
        },
        {
            "component": "Systematic review question",
            "content": f"What types of studies, populations, methods, and outcomes are reported in the literature on {theme}?",
            "output": "Study characteristics table and narrative synthesis"
        },
        {
            "component": "Meta-analysis question",
            "content": f"What is the pooled effect of eligible empirical studies related to {theme}, if effect size data are available?",
            "output": "Pooled effect, CI, p-value, heterogeneity"
        },
        {
            "component": "Quality question",
            "content": "How reliable are the included studies based on risk of bias and reporting quality?",
            "output": "Risk of bias table and evidence strength"
        },
        {
            "component": "Gap question",
            "content": f"What research gaps, methodological limitations, and future research directions exist in {theme}?",
            "output": "Gap, novelty, future agenda"
        },
    ]


def build_data_collection_matrix(theme: str) -> List[Dict[str, str]]:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    return [
        {"data_type": "Bibliographic metadata", "fields": "title, authors, year, journal, DOI, database, abstract, keywords", "source": "Crossref, OpenAlex, Scopus, WoS, Semantic Scholar", "purpose": "Mapping, deduplication, citation readiness"},
        {"data_type": "Screening data", "fields": "include/exclude/maybe, reason, full-text availability", "source": "Title/abstract/full-text", "purpose": "PRISMA transparency"},
        {"data_type": "Study characteristics", "fields": "country, population, species/sample, design, intervention/exposure, comparison, outcome", "source": "Full-text article", "purpose": "Systematic review synthesis"},
        {"data_type": "Quantitative extraction", "fields": "effect_size, SE, CI, mean, SD, n, event, total, OR, RR, r", "source": "Results/table/supplementary file", "purpose": "Meta-analysis"},
        {"data_type": "Quality assessment", "fields": "randomization/sampling, blinding, incomplete data, selective reporting, confounding, sample adequacy", "source": "Methods/results section", "purpose": "Risk of bias/evidence strength"},
        {"data_type": "Publication readiness", "fields": "novelty, contribution, implications, limitations, target journal scope", "source": "Analysis + author judgment", "purpose": "Q-level manuscript preparation"},
    ]


def build_research_timeline() -> List[Dict[str, str]]:
    return [
        {"week": "Week 1", "activity": "Tentukan tema, framework PICO/PECO/SPIDER, search string, dan database.", "output": "Protocol draft + search strategy"},
        {"week": "Week 2", "activity": "Ambil data dari API publik dan database manual seperti Scopus/WoS/CAB/AGRIS.", "output": "Master bibliography dataset"},
        {"week": "Week 3", "activity": "Deduplikasi dan screening title/abstract.", "output": "PRISMA screening table"},
        {"week": "Week 4", "activity": "Full-text retrieval dan ekstraksi karakteristik studi.", "output": "Study characteristics table"},
        {"week": "Week 5", "activity": "Ekstraksi data effect size dan risk of bias.", "output": "Meta-analysis Excel + ROB table"},
        {"week": "Week 6", "activity": "Analisis bibliografi, systematic review, meta-analysis, sensitivity, publication bias.", "output": "Results tables and figures"},
        {"week": "Week 7", "activity": "Tulis draft artikel review.", "output": "Full manuscript draft"},
        {"week": "Week 8", "activity": "Q-level polishing: novelty, discussion, limitations, references, cover letter.", "output": "Submission-ready package"},
    ]


def build_qlevel_research_advice(theme, records, screened, meta_studies, rob_rows) -> List[Dict[str, str]]:
    advice = []
    total = len(records)
    m = get_metrics(records) if records else {"with_doi": 0, "with_abstract": 0, "need": 0}

    def add(priority, issue, advice_text):
        advice.append({"priority": priority, "issue": issue, "advice": advice_text})

    if not theme:
        add("High", "Tema belum jelas", "Tentukan tema spesifik dan tidak terlalu luas. Tema yang baik punya population/exposure/outcome yang jelas.")
    if total < 30:
        add("High", "Dataset kecil", "Untuk jurnal Q-level, perluas pencarian. Tambahkan Scopus/WoS/CAB/AGRIS/PubAg/IEEE/ScienceDirect bila relevan.")
    if records and pct(m.get("with_doi", 0), total) < 70:
        add("Medium", "DOI belum lengkap", "Lengkapi DOI agar deduplikasi dan sitasi lebih kuat.")
    if records and pct(m.get("with_abstract", 0), total) < 60:
        add("High", "Abstrak belum lengkap", "Tambahkan abstrak karena screening dan narrative synthesis membutuhkan abstrak/full-text.")
    if not screened:
        add("High", "PRISMA belum siap", "Jalankan screening dan simpan alasan eksklusi. Ini wajib untuk systematic review.")
    if not meta_studies:
        add("High", "Meta-analysis belum siap", "Isi effect size/SE dari full-text. Jika data tidak cukup, posisikan sebagai systematic review + evidence readiness.")
    elif len(meta_studies) < 5:
        add("Medium", "Studi meta sedikit", "Hasil meta-analysis sebaiknya disebut eksploratif dan dilengkapi narrative synthesis.")
    if not rob_rows:
        add("High", "Risk of bias belum dinilai", "Reviewer Q-level biasanya meminta quality assessment. Isi ROB dari full-text.")
    if not advice:
        add("Low", "Data cukup baik", "Lanjutkan polishing, validasi manual, dan sesuaikan dengan author guidelines jurnal target.")
    return advice


def build_research_assistant_report(theme, records, screened, meta_studies, rob_rows) -> str:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    lines = [
        "RESEARCH ASSISTANT HUB REPORT",
        "",
        f"Theme: {theme}",
        "",
        "1. Research Stage Status",
    ]
    for row in research_stage_status(records, screened, meta_studies, rob_rows):
        lines.append(f"- {row['stage']} | {row['status']} | Evidence: {row['evidence']} | Next: {row['next_action']}")

    lines += ["", "2. Research Question Matrix"]
    for row in build_research_question_matrix(theme):
        lines.append(f"- {row['component']}: {row['content']} Output: {row['output']}")

    lines += ["", "3. Data Collection Matrix"]
    for row in build_data_collection_matrix(theme):
        lines.append(f"- {row['data_type']}: {row['fields']} | Source: {row['source']} | Purpose: {row['purpose']}")

    lines += ["", "4. Q-Level Advice"]
    for row in build_qlevel_research_advice(theme, records, screened, meta_studies, rob_rows):
        lines.append(f"- [{row['priority']}] {row['issue']}: {row['advice']}")

    lines += ["", "5. Suggested Timeline"]
    for row in build_research_timeline():
        lines.append(f"- {row['week']}: {row['activity']} Output: {row['output']}")

    return "\n".join(lines)


def render_research_assistant_hub_inside_panduan():
    st.divider()
    st.subheader("🧠 Research Assistant Hub")
    st.caption("Modul ini membantu penulis mengumpulkan data, menganalisis data, menyusun draft, dan menyiapkan naskah sesuai standar jurnal Q-level.")

    records = st.session_state.get("theme_records", []) or st.session_state.get("records", [])
    screened = st.session_state.get("screened", [])
    meta_studies = st.session_state.get("meta_studies", [])
    rob_rows = st.session_state.get("rob_rows", [])
    theme_default = st.session_state.get("last_theme", "") or "precision livestock farming"
    theme = st.text_input("Tema riset", value=theme_default, key="research_hub_theme")

    tab_status, tab_collect, tab_write, tab_qlevel, tab_export = st.tabs([
        "📍 Status Riset", "📥 Data yang Dikumpulkan", "✍️ Bahan Draft", "🏆 Masukan Q-Level", "📤 Export"
    ])

    with tab_status:
        st.write("### Status Tahapan Riset")
        stages = research_stage_status(records, screened, meta_studies, rob_rows)
        st.dataframe(stages, use_container_width=True, height=360)

        st.write("### Matriks Pertanyaan Penelitian")
        st.dataframe(build_research_question_matrix(theme), use_container_width=True, height=320)

    with tab_collect:
        st.write("### Matriks Data yang Harus Dikumpulkan")
        data_matrix = build_data_collection_matrix(theme)
        st.dataframe(data_matrix, use_container_width=True, height=360)

        st.write("### Timeline Riset")
        st.dataframe(build_research_timeline(), use_container_width=True, height=300)

    with tab_write:
        st.write("### Bahan untuk Menulis Draft")
        prompts = build_manuscript_section_prompts(theme) if "build_manuscript_section_prompts" in globals() else [
            {"section": "Abstract", "writing_prompt": "Tuliskan ringkasan tujuan, metode, hasil, dan kesimpulan."},
            {"section": "Introduction", "writing_prompt": "Tuliskan urgensi, gap, dan novelty."},
            {"section": "Methods", "writing_prompt": "Tuliskan database, search string, PRISMA, ekstraksi, dan analisis."},
            {"section": "Results", "writing_prompt": "Tuliskan hasil bibliografi, systematic review, dan meta-analysis."},
            {"section": "Discussion", "writing_prompt": "Interpretasikan temuan, gap, implikasi, dan keterbatasan."},
        ]
        st.dataframe(prompts, use_container_width=True, height=300)

        if "build_conclusion_draft" in globals():
            st.write("### Draft Kesimpulan Awal")
            meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
            st.text_area("Draft kesimpulan", value=build_conclusion_draft(theme, records, meta_result), height=180)

    with tab_qlevel:
        st.write("### Masukan Otomatis untuk Kesiapan Jurnal Q-Level")
        advice = build_qlevel_research_advice(theme, records, screened, meta_studies, rob_rows)
        st.dataframe(advice, use_container_width=True, height=340)

        st.write("### Prinsip Utama Agar Layak Q-Level")
        q_points = [
            "Gunakan PRISMA untuk struktur systematic review.",
            "Jangan hanya mengandalkan metadata; lakukan full-text extraction.",
            "Laporkan search string, database, dan tanggal pencarian.",
            "Lengkapi tabel karakteristik studi.",
            "Isi risk of bias/quality assessment.",
            "Validasi hasil meta-analysis dengan software statistik bila untuk submit.",
            "Tulis novelty yang jelas: apa yang berbeda dari review sebelumnya.",
            "Bahas heterogenitas, keterbatasan, dan implikasi secara kritis.",
            "Gunakan referensi terbaru dan jurnal bereputasi.",
        ]
        for p in q_points:
            st.write(f"- {p}")

    with tab_export:
        report = build_research_assistant_report(theme, records, screened, meta_studies, rob_rows)
        st.text_area("Research Assistant Report", value=report, height=460)
        st.download_button(
            "📥 Download Research Assistant Report TXT",
            data=report.encode("utf-8"),
            file_name="research_assistant_report.txt",
            mime="text/plain",
            use_container_width=True,
        )

        data_matrix = build_data_collection_matrix(theme)
        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download Matriks Data Riset Excel",
                data=rows_to_xlsx(data_matrix, ["data_type", "fields", "source", "purpose"], "Matriks Data"),
                file_name="matriks_data_riset.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.download_button(
                "📥 Download Matriks Data Riset CSV",
                data=safe_csv(data_matrix, ["data_type", "fields", "source", "purpose"]),
                file_name="matriks_data_riset.csv",
                mime="text/csv",
                use_container_width=True,
            )




# =========================================================
# Quality Control & Validity Guard
# =========================================================
def build_quality_control_strategy(theme: str) -> str:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    return f"""QUALITY CONTROL & VALIDITY GUARD

Tema:
{theme}

Tujuan modul ini adalah memperketat kendali mutu agar systematic review dan meta-analisis lebih komprehensif, valid, transparan, dan dapat dipertanggungjawabkan.

1. Perluas dan Pertajam Search Strategy

Prinsip:
- Jangan hanya memakai satu database.
- Kombinasikan database multidisipliner, database domain, dan grey literature.
- Gunakan sinonim, istilah teknis, istilah domain, operator Boolean, dan controlled vocabulary seperti MeSH jika relevan.
- Catat search string dan jumlah hasil dari setiap database.

Database utama:
- Scopus
- Web of Science
- PubMed
- Cochrane Library
- Crossref
- OpenAlex
- Semantic Scholar
- PLOS
- DOAJ
- Europe PMC
- DataCite
- OpenAIRE

Database domain/pendukung:
- CAB Abstracts/CABI
- AGRIS/FAO
- USDA PubAg
- IEEE Xplore
- ScienceDirect
- SpringerLink
- Wiley
- Taylor & Francis
- MDPI
- Frontiers
- Dimensions

Grey literature:
- Google Scholar
- ProQuest Dissertations
- tesis/disertasi
- prosiding konferensi
- laporan pemerintah
- preprint
- policy report
- technical report

Contoh search string untuk precision livestock farming:
("precision livestock farming" OR "smart livestock farming" OR "precision dairy farming" OR "livestock monitoring" OR "animal welfare monitoring" OR "animal health monitoring") AND (sensor* OR IoT OR "machine learning" OR "artificial intelligence" OR "computer vision" OR wearable OR "automated monitoring")

2. Double-Blinded Screening

Prinsip:
- Screening judul/abstrak dilakukan minimal oleh dua reviewer secara independen.
- Reviewer tidak melihat keputusan reviewer lain saat tahap awal.
- Perbedaan keputusan dicatat sebagai discrepancy.
- Discrepancy diselesaikan melalui diskusi atau reviewer ketiga.
- Laporkan proses ini dalam metode.

Kategori keputusan:
- Include
- Exclude
- Maybe
- Conflict/Discrepancy

Alasan eksklusi harus spesifik:
- tidak sesuai tema
- bukan studi empiris
- tidak ada outcome
- tidak tersedia full-text
- duplikasi
- tidak ada data kuantitatif
- populasi/outcome tidak sesuai
- desain studi tidak sesuai

3. Risk of Bias dan Quality Assessment

Prinsip:
- Kualitas studi menentukan kekuatan kesimpulan.
- Studi high risk of bias jangan langsung dicampur tanpa analisis tambahan.
- Gunakan alat yang sesuai dengan desain studi.

Alat yang disarankan:
- Cochrane Risk of Bias 2 untuk RCT.
- ROBINS-I untuk non-randomized intervention studies.
- Newcastle-Ottawa Scale untuk studi observasional.
- QUADAS-2 untuk diagnostic accuracy studies.
- JBI Critical Appraisal Tools untuk desain campuran.
- AMSTAR-2 untuk menilai systematic review lain.

Penggunaan hasil ROB:
- Masukkan sebagai tabel.
- Gunakan untuk interpretasi strength of evidence.
- Jalankan sensitivity analysis dengan mengecualikan studi high risk.
- Jika high risk dominan, turunkan kekuatan kesimpulan.

4. Sensitivity Analysis

Tujuan:
Menguji apakah hasil meta-analisis tetap stabil jika studi tertentu dikeluarkan.

Metode:
- Leave-one-out analysis.
- Exclude high risk of bias studies.
- Exclude outlier studies.
- Exclude very large studies yang mendominasi bobot.
- Bandingkan fixed-effect dan random-effects.
- Bandingkan hasil berdasarkan jenis effect size atau outcome.

Interpretasi:
- Jika pooled effect tetap konsisten, hasil robust.
- Jika hasil berubah drastis, kesimpulan harus hati-hati.
- Jelaskan studi mana yang paling memengaruhi hasil.

5. Kendali Heterogenitas

Gunakan statistik:
- Q
- tau²
- I²

Interpretasi I²:
- <30%: heterogenitas rendah.
- 30–60%: heterogenitas sedang.
- >60%: heterogenitas tinggi.
- >75%: sangat tinggi dan perlu eksplorasi serius.

Jika I² tinggi:
- Jangan memaksakan kesimpulan global terlalu kuat.
- Lakukan subgroup analysis.
- Pertimbangkan meta-regression jika jumlah studi cukup.
- Cek perbedaan populasi, intervensi, outcome, wilayah, desain studi, teknologi, dosis, durasi, atau metode pengukuran.
- Bahas heterogenitas sebagai temuan penting.

Contoh subgroup untuk precision livestock farming:
- jenis ternak: dairy cattle, beef cattle, poultry, sheep/goat.
- teknologi: sensor wearable, computer vision, IoT, machine learning.
- outcome: animal welfare, disease detection, productivity, milk yield, feed efficiency.
- wilayah: Asia, Europe, Americas, Africa.
- desain: experimental, observational, validation study.

6. Publication Bias

Strategi:
- Gunakan funnel plot jika jumlah studi cukup.
- Gunakan Egger test jika jumlah studi memadai.
- Cari grey literature untuk mengurangi bias publikasi.
- Jelaskan jika publication bias tidak dapat diuji karena studi terlalu sedikit.
- Jangan menyimpulkan “tidak ada publication bias” jika jumlah studi kecil.

7. Audit Trail

Simpan:
- search string per database.
- tanggal pencarian.
- jumlah hasil awal.
- jumlah duplikasi.
- alasan eksklusi.
- keputusan reviewer 1 dan reviewer 2.
- discrepancy dan resolusi.
- data ekstraksi.
- risk of bias.
- versi dataset.
- catatan perubahan analisis.

8. Standar Q-Level

Agar lebih siap jurnal Q-level:
- gunakan PRISMA sebagai backbone.
- tampilkan flow diagram/count.
- lampirkan search string lengkap.
- gunakan multidatabase.
- sertakan grey literature bila relevan.
- gunakan double screening.
- gunakan risk-of-bias tool standar.
- laporkan sensitivity analysis.
- kontrol heterogenitas.
- hindari klaim berlebihan.
- sediakan supplementary material.
"""


def build_screening_reviewer_template(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    rows = []
    source_records = records[:200] if records else []
    if not source_records:
        source_records = [{
            "title": "Example title",
            "authors": "Author A",
            "year": "2024",
            "journal": "Journal",
            "doi": "",
            "database": "Manual",
            "abstract": "Example abstract"
        }]
    for i, r in enumerate(source_records, 1):
        rows.append({
            "record_id": str(i),
            "title": r.get("title", ""),
            "authors": r.get("authors", ""),
            "year": r.get("year", ""),
            "journal": r.get("journal", ""),
            "doi": r.get("doi", ""),
            "database": r.get("database", ""),
            "reviewer_1_decision": "",
            "reviewer_1_reason": "",
            "reviewer_2_decision": "",
            "reviewer_2_reason": "",
            "discrepancy": "",
            "final_decision": "",
            "final_reason": "",
            "third_reviewer_notes": "",
        })
    return rows


def build_rob_tool_selector(theme: str) -> List[Dict[str, str]]:
    return [
        {"study_design": "Randomized controlled trial / RCT", "recommended_tool": "Cochrane Risk of Bias 2", "use_when": "Intervention assigned randomly", "qlevel_note": "Laporkan domain ROB2 dan overall judgment."},
        {"study_design": "Non-randomized intervention", "recommended_tool": "ROBINS-I", "use_when": "Intervention/exposure not randomized", "qlevel_note": "Sangat penting untuk confounding."},
        {"study_design": "Observational cohort/case-control", "recommended_tool": "Newcastle-Ottawa Scale / NOS", "use_when": "Exposure-outcome observational studies", "qlevel_note": "Laporkan selection, comparability, outcome/exposure."},
        {"study_design": "Diagnostic/accuracy study", "recommended_tool": "QUADAS-2", "use_when": "Detection/prediction accuracy studies", "qlevel_note": "Cocok untuk computer vision/disease detection."},
        {"study_design": "Cross-sectional/survey", "recommended_tool": "JBI Critical Appraisal Checklist", "use_when": "Survey/prevalence/association studies", "qlevel_note": "Jelaskan sampling and measurement bias."},
        {"study_design": "Systematic review included as evidence", "recommended_tool": "AMSTAR-2", "use_when": "Umbrella review or review of reviews", "qlevel_note": "Gunakan bila menilai review lain."},
    ]


def build_heterogeneity_action_plan(meta_studies: List[Dict[str, object]]) -> List[Dict[str, str]]:
    if meta_studies:
        result = run_meta(meta_studies)
        i2 = result.get("heterogeneity", {}).get("I2", 0) if result.get("k", 0) else 0
    else:
        i2 = 0

    if not meta_studies:
        status = "Belum tersedia"
        action = "Isi effect size/SE dari full-text terlebih dahulu."
    elif i2 < 30:
        status = "Rendah"
        action = "Random-effects tetap dapat dilaporkan, tetapi heterogenitas bukan masalah utama."
    elif i2 < 60:
        status = "Sedang"
        action = "Bahas kemungkinan variasi metode, populasi, outcome, dan lakukan subgroup jika memungkinkan."
    else:
        status = "Tinggi"
        action = "Jangan memaksakan kesimpulan global. Lakukan subgroup/sensitivity dan jelaskan sumber heterogenitas."

    return [
        {"indicator": "I²", "current_status": status, "recommended_action": action},
        {"indicator": "Subgroup by population/species", "current_status": "Disarankan", "recommended_action": "Pisahkan analisis berdasarkan jenis populasi/spesies jika relevan."},
        {"indicator": "Subgroup by intervention/technology", "current_status": "Disarankan", "recommended_action": "Pisahkan berdasarkan teknologi/intervensi/metode."},
        {"indicator": "Subgroup by outcome", "current_status": "Disarankan", "recommended_action": "Jangan gabungkan outcome yang terlalu berbeda."},
        {"indicator": "Sensitivity high risk exclusion", "current_status": "Disarankan", "recommended_action": "Ulangi analisis setelah mengeluarkan studi high risk."},
        {"indicator": "Meta-regression", "current_status": "Opsional", "recommended_action": "Pertimbangkan jika jumlah studi cukup dan moderator tersedia."},
    ]


def build_qc_checklist(records, screened, meta_studies, rob_rows) -> List[Dict[str, str]]:
    total = len(records)
    m = get_metrics(records) if records else {"with_doi": 0, "with_abstract": 0}
    items = []

    def status(condition):
        return "OK" if condition else "Perlu diperbaiki"

    items.append({"area": "Multidatabase search", "criterion": "Menggunakan lebih dari satu database utama dan sumber domain.", "status": status(total >= 30), "action": "Tambahkan Scopus/WoS/PubMed/CAB/AGRIS/IEEE/ScienceDirect bila relevan."})
    items.append({"area": "Search string", "criterion": "Memakai sinonim, Boolean, dan istilah domain/MeSH bila relevan.", "status": "Perlu dicek manual", "action": "Simpan search string per database sebagai supplementary material."})
    items.append({"area": "Grey literature", "criterion": "Mempertimbangkan tesis, disertasi, prosiding, laporan, preprint.", "status": "Perlu dicek manual", "action": "Tambahkan grey literature untuk mengurangi publication bias."})
    items.append({"area": "DOI coverage", "criterion": "DOI coverage minimal 70%.", "status": status(total > 0 and pct(m.get("with_doi", 0), total) >= 70), "action": "Lengkapi DOI melalui Crossref/OpenAlex/full-text."})
    items.append({"area": "Abstract coverage", "criterion": "Abstract coverage minimal 60%.", "status": status(total > 0 and pct(m.get("with_abstract", 0), total) >= 60), "action": "Lengkapi abstrak untuk screening dan narrative synthesis."})
    items.append({"area": "Double screening", "criterion": "Reviewer 1 dan Reviewer 2 melakukan screening independen.", "status": "Perlu dicek manual", "action": "Gunakan template double screening."})
    items.append({"area": "PRISMA", "criterion": "Ada included/excluded/maybe dan alasan eksklusi.", "status": status(bool(screened)), "action": "Jalankan PRISMA & Screening."})
    items.append({"area": "Risk of Bias", "criterion": "ROB dinilai dengan tool sesuai desain studi.", "status": status(bool(rob_rows)), "action": "Isi ROB berdasarkan full-text."})
    items.append({"area": "Sensitivity analysis", "criterion": "Leave-one-out dan/atau exclude high risk tersedia.", "status": status(len(meta_studies) >= 2), "action": "Butuh minimal 2 studi valid."})
    items.append({"area": "Publication bias", "criterion": "Funnel/Egger atau limitation statement.", "status": status(len(meta_studies) >= 3), "action": "Jika studi sedikit, jelaskan tidak cukup untuk diuji."})
    items.append({"area": "Heterogeneity control", "criterion": "I² ditafsirkan dan subgroup/sensitivity dilakukan bila tinggi.", "status": status(len(meta_studies) >= 2), "action": "Gunakan action plan heterogenitas."})
    return items


def build_quality_control_report(theme, records, screened, meta_studies, rob_rows) -> str:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    lines = [
        "QUALITY CONTROL & VALIDITY REPORT",
        "",
        f"Theme: {theme}",
        "",
        "1. Strategy",
        build_quality_control_strategy(theme),
        "",
        "2. QC Checklist"
    ]
    for row in build_qc_checklist(records, screened, meta_studies, rob_rows):
        lines.append(f"- [{row['status']}] {row['area']}: {row['criterion']} Action: {row['action']}")

    lines += ["", "3. Risk of Bias Tool Selector"]
    for row in build_rob_tool_selector(theme):
        lines.append(f"- {row['study_design']}: {row['recommended_tool']} | Use: {row['use_when']} | Note: {row['qlevel_note']}")

    lines += ["", "4. Heterogeneity Action Plan"]
    for row in build_heterogeneity_action_plan(meta_studies):
        lines.append(f"- {row['indicator']}: {row['current_status']} | Action: {row['recommended_action']}")

    lines += ["", "5. Practical Recommendation"]
    if len(records) < 30:
        lines.append("- Perluas search strategy dan database sebelum submit ke jurnal Q-level.")
    if not screened:
        lines.append("- Jalankan double screening dan PRISMA.")
    if not rob_rows:
        lines.append("- Lengkapi risk of bias sebelum menulis kesimpulan kuat.")
    if len(meta_studies) < 3:
        lines.append("- Meta-analysis belum cukup kuat untuk publication bias. Gunakan narrative synthesis atau sebut eksploratif.")
    if len(records) >= 30 and screened and rob_rows:
        lines.append("- Workflow sudah cukup kuat; lanjutkan validasi manual, polishing draft, dan target journal fit.")

    return "\n".join(lines)


def render_quality_control_inside_panduan():
    st.divider()
    st.subheader("🛡️ Quality Control & Validity Guard")
    st.caption("Memperketat mutu metodologi: multidatabase search, double screening, risk of bias, sensitivity analysis, heterogeneity control, dan publication bias.")

    records = st.session_state.get("theme_records", []) or st.session_state.get("records", [])
    screened = st.session_state.get("screened", [])
    meta_studies = st.session_state.get("meta_studies", [])
    rob_rows = st.session_state.get("rob_rows", [])
    theme = st.session_state.get("last_theme", "") or "precision livestock farming"

    tab_strategy, tab_screen, tab_rob, tab_hetero, tab_export = st.tabs([
        "🔎 Search Strategy", "👥 Double Screening", "⚖️ ROB Tools", "📊 Heterogenitas", "📤 Export"
    ])

    with tab_strategy:
        st.text_area("Strategi kendali mutu", value=build_quality_control_strategy(theme), height=520)
        st.write("### QC Checklist")
        st.dataframe(build_qc_checklist(records, screened, meta_studies, rob_rows), use_container_width=True, height=360)

    with tab_screen:
        st.write("### Template Double-Blinded Screening")
        screen_rows = build_screening_reviewer_template(records)
        st.dataframe(screen_rows, use_container_width=True, height=360)
        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download Template Double Screening Excel",
                data=rows_to_xlsx(screen_rows, ["record_id", "title", "authors", "year", "journal", "doi", "database", "reviewer_1_decision", "reviewer_1_reason", "reviewer_2_decision", "reviewer_2_reason", "discrepancy", "final_decision", "final_reason", "third_reviewer_notes"], "Double Screening"),
                file_name="template_double_screening.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    with tab_rob:
        st.write("### Risk of Bias Tool Selector")
        st.dataframe(build_rob_tool_selector(theme), use_container_width=True, height=320)
        st.info("Pilih tool sesuai desain studi. Jangan memakai satu alat ROB untuk semua jenis studi jika desainnya berbeda.")

    with tab_hetero:
        st.write("### Heterogeneity & Sensitivity Action Plan")
        st.dataframe(build_heterogeneity_action_plan(meta_studies), use_container_width=True, height=320)
        st.info("Jika I² tinggi, prioritaskan subgroup analysis, sensitivity analysis, dan narasi kritis daripada memaksakan pooled conclusion.")

    with tab_export:
        report = build_quality_control_report(theme, records, screened, meta_studies, rob_rows)
        st.text_area("Quality Control Report", value=report, height=520)
        st.download_button(
            "📥 Download Quality Control Report TXT",
            data=report.encode("utf-8"),
            file_name="quality_control_validity_report.txt",
            mime="text/plain",
            use_container_width=True,
        )
        qc = build_qc_checklist(records, screened, meta_studies, rob_rows)
        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download QC Checklist Excel",
                data=rows_to_xlsx(qc, ["area", "criterion", "status", "action"], "QC Checklist"),
                file_name="quality_control_checklist.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )



# =========================================================
# Tables & Figures Plan for Review Article
# =========================================================
def build_review_table_figure_plan_enhanced() -> List[Dict[str, str]]:
    return [
        {
            "item": "Table 1",
            "title": "Search strategy and database sources",
            "description": "Database, query string, date, number of records.",
            "purpose": "Menunjukkan transparansi literature search dan replikasi pencarian.",
            "recommended_section": "Methods"
        },
        {
            "item": "Table 2",
            "title": "Inclusion and exclusion criteria",
            "description": "Eligibility criteria for bibliographic review and meta-analysis.",
            "purpose": "Menjelaskan batasan studi yang masuk dan keluar.",
            "recommended_section": "Methods"
        },
        {
            "item": "Table 3",
            "title": "Characteristics of included studies",
            "description": "Author, year, title, journal, country, population, outcome, DOI.",
            "purpose": "Menampilkan profil studi yang dianalisis.",
            "recommended_section": "Results"
        },
        {
            "item": "Table 4",
            "title": "Top journals, authors, and keywords",
            "description": "Bibliographic performance indicators.",
            "purpose": "Menampilkan indikator bibliografi utama.",
            "recommended_section": "Results"
        },
        {
            "item": "Table 5",
            "title": "Risk of bias assessment",
            "description": "Risk domains and overall risk judgment.",
            "purpose": "Menunjukkan kualitas dan reliabilitas studi.",
            "recommended_section": "Results / Quality Assessment"
        },
        {
            "item": "Figure 1",
            "title": "PRISMA flow diagram",
            "description": "Identification, screening, eligibility, included studies.",
            "purpose": "Memvisualisasikan alur seleksi studi.",
            "recommended_section": "Methods / Results"
        },
        {
            "item": "Figure 2",
            "title": "Publication trend by year",
            "description": "Annual publication distribution.",
            "purpose": "Menunjukkan perkembangan publikasi dari waktu ke waktu.",
            "recommended_section": "Results"
        },
        {
            "item": "Figure 3",
            "title": "Keyword distribution or science mapping",
            "description": "Main research themes and keyword frequency.",
            "purpose": "Menjelaskan tema riset dominan dan arah perkembangan bidang.",
            "recommended_section": "Results / Discussion"
        },
    ]


def build_table1_search_strategy(records: List[Dict[str, str]], theme: str) -> List[Dict[str, str]]:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    source_counts = Counter(clean(r.get("database", "Unknown")) or "Unknown" for r in records)
    if not source_counts:
        source_counts = Counter({"Crossref": 0, "OpenAlex": 0, "Scopus": 0, "Web of Science": 0, "PubMed": 0})
    search_string = build_search_string(theme)["combined"] if "build_search_string" in globals() else theme
    rows = []
    for db, count in source_counts.items():
        rows.append({
            "database": db,
            "query_string": search_string,
            "search_date": "",
            "number_of_records": count,
            "notes": "Lengkapi tanggal pencarian dan sesuaikan syntax database."
        })
    return rows


def build_table2_eligibility(theme: str) -> List[Dict[str, str]]:
    theme = normalize_theme(theme) if "normalize_theme" in globals() else clean(theme)
    inc_exc = build_inclusion_exclusion(theme) if "build_inclusion_exclusion" in globals() else {
        "inclusion": [f"Studies related to {theme}"],
        "exclusion": ["Studies not related to the topic"]
    }
    rows = []
    for x in inc_exc.get("inclusion", []):
        rows.append({"criteria_type": "Inclusion", "criterion": x, "rationale": ""})
    for x in inc_exc.get("exclusion", []):
        rows.append({"criteria_type": "Exclusion", "criterion": x, "rationale": ""})
    return rows


def build_table3_characteristics(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    rows = []
    for r in records[:300]:
        rows.append({
            "author": clean(r.get("authors", "")).split(";")[0],
            "year": r.get("year", ""),
            "title": r.get("title", ""),
            "journal": r.get("journal", ""),
            "country": "",
            "population": "",
            "intervention_exposure": "",
            "comparison": "",
            "outcome": "",
            "study_design": "",
            "doi": r.get("doi", ""),
            "notes": ""
        })
    if not rows:
        rows.append({
            "author": "",
            "year": "",
            "title": "",
            "journal": "",
            "country": "",
            "population": "",
            "intervention_exposure": "",
            "comparison": "",
            "outcome": "",
            "study_design": "",
            "doi": "",
            "notes": ""
        })
    return rows


def build_table4_biblio_indicators(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    rows = []
    journals = count_by(records, "journal", 10) if records else {}
    authors = Counter()
    for r in records:
        for a in split_authors(r.get("authors", "")):
            if a:
                authors[a] += 1
    keywords = keyword_distribution(records, 15) if records else {}

    for k, v in journals.items():
        rows.append({"indicator_type": "Top journal", "item": k, "frequency": v, "notes": ""})
    for k, v in authors.most_common(10):
        rows.append({"indicator_type": "Top author", "item": k, "frequency": v, "notes": ""})
    for k, v in keywords.items():
        rows.append({"indicator_type": "Top keyword", "item": k, "frequency": v, "notes": ""})

    if not rows:
        rows.append({"indicator_type": "Top journal/author/keyword", "item": "", "frequency": "", "notes": ""})
    return rows


def build_table5_risk_of_bias(rob_rows: List[Dict[str, str]], records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if rob_rows:
        rows = []
        for r in rob_rows:
            rows.append({
                "study_id": r.get("study_id", ""),
                "randomization_sampling": r.get("randomization", r.get("sampling", "")),
                "blinding_measurement": r.get("blinding", r.get("measurement", "")),
                "incomplete_data": r.get("incomplete_data", ""),
                "selective_reporting": r.get("selective_reporting", ""),
                "confounding_control": r.get("confounding", r.get("confounding_control", "")),
                "sample_size_adequacy": r.get("sample_size", r.get("sample_size_adequacy", "")),
                "overall_risk": r.get("overall_risk", ""),
                "notes": r.get("notes", "")
            })
        return rows

    rows = []
    for i, r in enumerate(records[:100], 1):
        rows.append({
            "study_id": f"{clean(r.get('authors','')).split(';')[0]} {r.get('year','')}".strip() or f"Study {i}",
            "randomization_sampling": "",
            "blinding_measurement": "",
            "incomplete_data": "",
            "selective_reporting": "",
            "confounding_control": "",
            "sample_size_adequacy": "",
            "overall_risk": "",
            "notes": ""
        })
    if not rows:
        rows.append({
            "study_id": "",
            "randomization_sampling": "",
            "blinding_measurement": "",
            "incomplete_data": "",
            "selective_reporting": "",
            "confounding_control": "",
            "sample_size_adequacy": "",
            "overall_risk": "",
            "notes": ""
        })
    return rows


def build_figure_plan_data(records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]]) -> List[Dict[str, str]]:
    prisma = prisma_counts(st.session_state.get("found_total", 0) or len(records), records, screened, meta_studies) if "prisma_counts" in globals() else {}
    rows = []
    for k, v in prisma.items():
        rows.append({"figure": "Figure 1 PRISMA flow diagram", "data_point": k, "value": v, "notes": ""})

    years = year_distribution(records) if records else {}
    for y, c in years.items():
        rows.append({"figure": "Figure 2 Publication trend by year", "data_point": str(y), "value": c, "notes": ""})

    keywords = keyword_distribution(records, 20) if records else {}
    for k, v in keywords.items():
        rows.append({"figure": "Figure 3 Keyword distribution / science mapping", "data_point": k, "value": v, "notes": ""})

    if not rows:
        rows.append({"figure": "Figure 1/2/3", "data_point": "", "value": "", "notes": ""})
    return rows


def build_tables_figures_report(theme: str, records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]], rob_rows: List[Dict[str, str]]) -> str:
    lines = [
        "TABLES AND FIGURES PLAN FOR REVIEW ARTICLE",
        "",
        f"Theme: {theme or '-'}",
        "",
        "1. Required Tables and Figures"
    ]
    for row in build_review_table_figure_plan_enhanced():
        lines.append(f"- {row['item']}: {row['title']} — {row['description']} Purpose: {row['purpose']} Section: {row['recommended_section']}")

    lines += [
        "",
        "2. Table Preparation Notes",
        "- Table 1 harus memuat database, search string, tanggal pencarian, dan jumlah record.",
        "- Table 2 harus memisahkan kriteria inklusi dan eksklusi.",
        "- Table 3 harus dilengkapi dari full-text, terutama country, population, intervention/exposure, comparison, outcome, dan design.",
        "- Table 4 dapat dihasilkan dari metadata bibliografi.",
        "- Table 5 harus diisi berdasarkan full-text dan tool risk of bias yang sesuai.",
        "",
        "3. Figure Preparation Notes",
        "- Figure 1 menggunakan data PRISMA counts.",
        "- Figure 2 menggunakan distribusi publikasi tahunan.",
        "- Figure 3 menggunakan keyword frequency atau hasil science mapping.",
        "- Untuk jurnal Q-level, semua figure sebaiknya resolusi tinggi dan memiliki caption yang menjelaskan insight, bukan hanya tampilan grafik.",
    ]
    return "\n".join(lines)


def render_tables_figures_inside_panduan():
    st.divider()
    st.subheader("📊 Tables & Figures Plan")
    st.caption("Rencana tabel dan figure utama untuk artikel systematic review, bibliometric review, dan meta-analysis.")

    records = st.session_state.get("theme_records", []) or st.session_state.get("records", [])
    screened = st.session_state.get("screened", [])
    meta_studies = st.session_state.get("meta_studies", [])
    rob_rows = st.session_state.get("rob_rows", [])
    theme = st.session_state.get("last_theme", "") or "precision livestock farming"

    tab_plan, tab_tables, tab_figures, tab_export = st.tabs([
        "🧾 Plan", "📋 Template Tables", "🖼️ Figure Data", "📤 Export"
    ])

    with tab_plan:
        plan = build_review_table_figure_plan_enhanced()
        st.dataframe(plan, use_container_width=True, height=360)
        st.info("Daftar ini mengikuti kebutuhan umum artikel review Q-level: search strategy, eligibility, characteristics, bibliographic indicators, risk of bias, PRISMA, publication trend, dan keyword mapping.")

    with tab_tables:
        selected = st.selectbox(
            "Pilih template tabel",
            [
                "Table 1 - Search strategy and database sources",
                "Table 2 - Inclusion and exclusion criteria",
                "Table 3 - Characteristics of included studies",
                "Table 4 - Top journals, authors, and keywords",
                "Table 5 - Risk of bias assessment",
            ],
            key="selected_review_table_template"
        )

        if selected.startswith("Table 1"):
            rows = build_table1_search_strategy(records, theme)
            fields = ["database", "query_string", "search_date", "number_of_records", "notes"]
        elif selected.startswith("Table 2"):
            rows = build_table2_eligibility(theme)
            fields = ["criteria_type", "criterion", "rationale"]
        elif selected.startswith("Table 3"):
            rows = build_table3_characteristics(records)
            fields = ["author", "year", "title", "journal", "country", "population", "intervention_exposure", "comparison", "outcome", "study_design", "doi", "notes"]
        elif selected.startswith("Table 4"):
            rows = build_table4_biblio_indicators(records)
            fields = ["indicator_type", "item", "frequency", "notes"]
        else:
            rows = build_table5_risk_of_bias(rob_rows, records)
            fields = ["study_id", "randomization_sampling", "blinding_measurement", "incomplete_data", "selective_reporting", "confounding_control", "sample_size_adequacy", "overall_risk", "notes"]

        st.dataframe(rows, use_container_width=True, height=420)

        filename = selected.lower().split(" - ")[0].replace(" ", "_") + ".xlsx"
        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download Template Excel",
                data=rows_to_xlsx(rows, fields, selected[:31]),
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.download_button(
                "📥 Download Template CSV",
                data=safe_csv(rows, fields),
                file_name=filename.replace(".xlsx", ".csv"),
                mime="text/csv",
                use_container_width=True,
            )

    with tab_figures:
        fig_rows = build_figure_plan_data(records, screened, meta_studies)
        st.dataframe(fig_rows, use_container_width=True, height=420)
        st.info("Gunakan data ini untuk membuat PRISMA flow, tren publikasi tahunan, dan keyword distribution/science mapping.")
        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download Figure Data Excel",
                data=rows_to_xlsx(fig_rows, ["figure", "data_point", "value", "notes"], "Figure Data"),
                file_name="figure_data_plan.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    with tab_export:
        report = build_tables_figures_report(theme, records, screened, meta_studies, rob_rows)
        st.text_area("Tables & Figures Report", value=report, height=420)
        st.download_button(
            "📥 Download Tables & Figures Report TXT",
            data=report.encode("utf-8"),
            file_name="tables_figures_plan_report.txt",
            mime="text/plain",
            use_container_width=True,
        )

        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download Tables & Figures Plan Excel",
                data=rows_to_xlsx(build_review_table_figure_plan_enhanced(), ["item", "title", "description", "purpose", "recommended_section"], "Table Figure Plan"),
                file_name="tables_figures_plan.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )



# =========================================================
# Enhanced Figure Templates & Captions
# =========================================================
def build_figure_templates(records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]]) -> List[Dict[str, str]]:
    theme = st.session_state.get("last_theme", "") or "the selected topic"
    prisma = prisma_counts(st.session_state.get("found_total", 0) or len(records), records, screened, meta_studies) if "prisma_counts" in globals() else {}
    years = year_distribution(records) if records else {}
    keywords = keyword_distribution(records, 15) if records else {}

    return [
        {
            "figure": "Figure 1",
            "title": "PRISMA flow diagram",
            "core_content": "Identification, screening, eligibility, included studies.",
            "data_needed": "records_identified, duplicates_removed, records_screened, records_excluded, full_text_assessed, studies_included_review, studies_included_meta",
            "auto_data_status": "Available" if prisma else "Need screening data",
            "caption_template": (
                "Figure 1. PRISMA flow diagram showing the identification, screening, eligibility assessment, "
                "and final inclusion of studies related to "
                f"{theme}. The diagram reports the number of records identified, duplicates removed, records screened, "
                "full-text articles assessed, excluded records with reasons, and studies included in the review/meta-analysis."
            ),
            "interpretation_template": (
                "The PRISMA flow clarifies the transparency of the study selection process. A large reduction from identified "
                "records to included studies is expected because bibliographic searches retrieve duplicates, unrelated records, "
                "non-empirical papers, and studies without extractable quantitative data."
            ),
            "qlevel_note": "For Q-level journals, include exclusion reasons and make the screening process reproducible."
        },
        {
            "figure": "Figure 2",
            "title": "Publication trend by year",
            "core_content": "Annual publication distribution.",
            "data_needed": "year and number_of_publications",
            "auto_data_status": "Available" if years else "Need valid publication years",
            "caption_template": (
                "Figure 2. Annual publication distribution of studies related to "
                f"{theme}. The figure shows the number of publications per year and indicates the development of research interest over time."
            ),
            "interpretation_template": (
                "An increasing trend suggests growing scholarly attention to the topic, whereas fluctuations may reflect changes in technology, "
                "database coverage, funding priorities, or publication practices. Recent growth should be interpreted together with database coverage."
            ),
            "qlevel_note": "Use this figure to justify research urgency and development of the field."
        },
        {
            "figure": "Figure 3",
            "title": "Keyword distribution or science mapping",
            "core_content": "Main research themes and keyword frequency.",
            "data_needed": "keywords, frequency, optional cluster/theme label",
            "auto_data_status": "Available" if keywords else "Need keyword metadata",
            "caption_template": (
                "Figure 3. Keyword distribution and thematic structure of studies related to "
                f"{theme}. The figure highlights the most frequent keywords and main research themes emerging from the bibliographic dataset."
            ),
            "interpretation_template": (
                "Dominant keywords indicate the conceptual focus of the field. Keyword clusters can reveal major themes, methodological approaches, "
                "technology groups, populations, outcomes, and potential gaps for future research."
            ),
            "qlevel_note": "For stronger Q-level presentation, complement keyword frequency with co-word network or thematic clustering when possible."
        },
    ]


def build_prisma_figure_data(records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]]) -> List[Dict[str, object]]:
    prisma = prisma_counts(st.session_state.get("found_total", 0) or len(records), records, screened, meta_studies) if "prisma_counts" in globals() else {}
    order = [
        ("Records identified", "records_identified"),
        ("Duplicates removed", "duplicates_removed"),
        ("Records after duplicates", "records_after_duplicates"),
        ("Records screened", "records_screened"),
        ("Records excluded", "records_excluded"),
        ("Full-text assessed", "full_text_assessed"),
        ("Studies included in review", "studies_included_review"),
        ("Studies included in meta-analysis", "studies_included_meta"),
    ]
    rows = []
    for label, key in order:
        rows.append({"stage": label, "value": prisma.get(key, 0), "notes": ""})
    return rows


def build_publication_trend_data(records: List[Dict[str, str]]) -> List[Dict[str, object]]:
    years = year_distribution(records) if records else {}
    if not years:
        return [{"year": "", "number_of_publications": "", "notes": "No valid year data yet."}]
    return [{"year": y, "number_of_publications": c, "notes": ""} for y, c in sorted(years.items())]


def build_keyword_mapping_data(records: List[Dict[str, str]]) -> List[Dict[str, object]]:
    keywords = keyword_distribution(records, 30) if records else {}
    if not keywords:
        return [{"keyword": "", "frequency": "", "theme_cluster": "", "notes": "No keyword metadata yet."}]
    rows = []
    for k, v in keywords.items():
        rows.append({"keyword": k, "frequency": v, "theme_cluster": "", "notes": ""})
    return rows


def build_figure_caption_report(records: List[Dict[str, str]], screened: List[Dict[str, str]], meta_studies: List[Dict[str, object]]) -> str:
    lines = ["FIGURE CAPTION AND INTERPRETATION REPORT", ""]
    for fig in build_figure_templates(records, screened, meta_studies):
        lines += [
            f"{fig['figure']}: {fig['title']}",
            f"Core content: {fig['core_content']}",
            f"Data needed: {fig['data_needed']}",
            f"Auto data status: {fig['auto_data_status']}",
            "",
            "Caption:",
            fig["caption_template"],
            "",
            "Interpretation:",
            fig["interpretation_template"],
            "",
            "Q-level note:",
            fig["qlevel_note"],
            "",
        ]
    return "\n".join(lines)


def render_enhanced_figure_templates_inside_panduan():
    st.divider()
    st.subheader("🖼️ Figure Templates")
    st.caption("Template figure untuk PRISMA flow, publication trend, dan keyword/science mapping.")

    records = st.session_state.get("theme_records", []) or st.session_state.get("records", [])
    screened = st.session_state.get("screened", [])
    meta_studies = st.session_state.get("meta_studies", [])

    tab_templates, tab_data, tab_caption = st.tabs(["🧾 Template Figure", "📊 Data Figure", "✍️ Caption & Interpretasi"])

    with tab_templates:
        templates = build_figure_templates(records, screened, meta_studies)
        st.dataframe(templates, use_container_width=True, height=420)

    with tab_data:
        selected = st.selectbox(
            "Pilih data figure",
            [
                "Figure 1 - PRISMA flow diagram",
                "Figure 2 - Publication trend by year",
                "Figure 3 - Keyword distribution or science mapping",
            ],
            key="selected_figure_data_template"
        )

        if selected.startswith("Figure 1"):
            rows = build_prisma_figure_data(records, screened, meta_studies)
            fields = ["stage", "value", "notes"]
            filename = "figure_1_prisma_flow_data.xlsx"
        elif selected.startswith("Figure 2"):
            rows = build_publication_trend_data(records)
            fields = ["year", "number_of_publications", "notes"]
            filename = "figure_2_publication_trend_data.xlsx"
        else:
            rows = build_keyword_mapping_data(records)
            fields = ["keyword", "frequency", "theme_cluster", "notes"]
            filename = "figure_3_keyword_mapping_data.xlsx"

        st.dataframe(rows, use_container_width=True, height=420)

        if "rows_to_xlsx" in globals():
            st.download_button(
                "📥 Download Data Figure Excel",
                data=rows_to_xlsx(rows, fields, selected[:31]),
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.download_button(
                "📥 Download Data Figure CSV",
                data=safe_csv(rows, fields),
                file_name=filename.replace(".xlsx", ".csv"),
                mime="text/csv",
                use_container_width=True,
            )

    with tab_caption:
        report = build_figure_caption_report(records, screened, meta_studies)
        st.text_area("Caption dan interpretasi figure", value=report, height=560)
        st.download_button(
            "📥 Download Figure Caption Report TXT",
            data=report.encode("utf-8"),
            file_name="figure_caption_interpretation_report.txt",
            mime="text/plain",
            use_container_width=True,
        )


# =========================================================
# Streamlit UI
# =========================================================
st.set_page_config(page_title=APP_TITLE, page_icon="📚", layout="wide", initial_sidebar_state="expanded")

for key, default in {
    "records": [],
    "theme_records": [],
    "found_total": 0,
    "screened": [],
    "meta_studies": [],
    "rob_rows": [],
    "last_theme": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

st.title("📚 Sistem Bibliografi & Meta-Analisis")
st.caption("Workflow rapi: tema → sumber kredibel → bibliografi → PRISMA screening → risk of bias → meta-analysis → sensitivity/publication bias → laporan.")

with st.sidebar:
    st.header("⚙️ Pengaturan")
    email = st.text_input("Email opsional untuk API publik", placeholder="nama@email.com")
    rows_per_source = st.slider("Hasil per sumber", 5, 100, 20, 5)
    st.divider()
    if st.button("🔄 Reset Semua Data", use_container_width=True):
        for key in ["records", "theme_records", "screened", "meta_studies", "rob_rows"]:
            st.session_state[key] = []
        st.session_state.found_total = 0
        st.success("Semua data dikosongkan.")

tabs = st.tabs([
    "🔬 Workflow Tema",
    "📚 Bibliografi",
    "✅ PRISMA & Screening",
    "📋 Systematic Review",
    "🧪 Meta-Analysis",
    "📘 Panduan Meta",
    "⚖️ Risk of Bias",
    "📉 Sensitivity & Bias",
    "📌 Insight Akhir",
    "🧩 Bahan Penelitian",
    "📝 Jurnal Review Builder",
    "🏆 Q-Level Toolkit",
    "🌐 Sumber Relevan",
    "🚀 Review Studio",
    "📤 Export",
    "📖 Panduan"
])

with tabs[0]:
    st.subheader("🔬 Workflow Tema → Bibliografi + Meta-Analisis")
    theme = st.text_input("Tema/topik penelitian", placeholder="Contoh: artificial intelligence in education", key="theme_input")
    source_mode = st.radio("Sumber", ["Otomatis sesuai tema", "Pilih manual"], horizontal=True)
    suggested_sources = select_sources(theme) if theme else ["Crossref", "OpenAlex", "Semantic Scholar", "DOAJ", "DataCite"]

    if source_mode == "Pilih manual":
        selected_sources = st.multiselect("Pilih sumber", list(SOURCE_FUNCTIONS.keys()), default=suggested_sources)
    else:
        selected_sources = suggested_sources
        st.write("Sumber otomatis:", ", ".join(selected_sources))

    min_score = st.slider("Batas relevansi tema", 0.0, 8.0, 1.0, 0.5)

    with st.expander("Kriteria screening awal"):
        c1, c2, c3 = st.columns(3)
        with c1:
            min_year = st.number_input("Tahun minimal", min_value=1900, max_value=2100, value=2020)
            max_year = st.number_input("Tahun maksimal", min_value=1900, max_value=2100, value=2026)
        with c2:
            only_doi = st.checkbox("Prioritaskan hanya DOI", value=False)
            must_have_abstract = st.checkbox("Wajib/utamakan abstrak", value=False)
            only_indexed = st.checkbox("Utamakan kandidat Scopus/WoS/High impact", value=False)
        with c3:
            include_terms = st.text_input("Kata kunci inklusi, pisahkan koma")
            exclude_terms = st.text_input("Kata kunci eksklusi, pisahkan koma")

    if st.button("🚀 Jalankan Workflow", type="primary", use_container_width=True):
        if not theme.strip():
            st.warning("Tema belum diisi.")
        else:
            found, errors = [], []
            progress = st.progress(0)
            status = st.empty()

            for i, source in enumerate(selected_sources, 1):
                status.info(f"Mencari dari {source}...")
                try:
                    res = SOURCE_FUNCTIONS[source](source_specific_query(theme, source), rows_per_source, email)
                    found += res
                    st.write(f"✅ {source}: {len(res)} record")
                except Exception as exc:
                    errors.append(f"{source}: {exc}")
                    st.write(f"⚠️ {source}: gagal/dilewati")
                progress.progress(i / len(selected_sources))

            unique_records = enhanced_deduplicate_records(standardize(found))
            relevant = filter_relevant(unique_records, theme, min_score)
            st.session_state.found_total = len(found)
            st.session_state.theme_records = enhanced_deduplicate_records(relevant)
            st.session_state.records = enhanced_deduplicate_records(standardize(st.session_state.records + relevant))
            st.session_state.last_theme = theme

            criteria = {
                "min_year": min_year,
                "max_year": max_year,
                "only_doi": only_doi,
                "must_have_abstract": must_have_abstract,
                "only_indexed": only_indexed,
                "include_terms": include_terms,
                "exclude_terms": exclude_terms,
            }
            st.session_state.screened = auto_screen(relevant, criteria)

            auto_meta = []
            for r in relevant:
                item = extract_effect_from_metadata(r)
                if item:
                    auto_meta.append(item)
            st.session_state.meta_studies = auto_meta
            st.session_state.rob_rows = build_rob_from_meta(auto_meta)

            status.success(f"Selesai: {len(unique_records)} unik, {len(relevant)} relevan, {len(auto_meta)} effect size terbaca otomatis.")
            if errors:
                with st.expander("Sumber yang gagal"):
                    for e in errors:
                        st.write(f"- {e}")
            if not auto_meta:
                st.info("Effect size biasanya tidak tersedia di metadata. Download format Excel meta-analysis di tab Meta-Analysis, isi dari full-text, lalu upload kembali.")

    st.divider()
    if st.session_state.theme_records:
        m = get_metrics(st.session_state.theme_records)
        a, b, c, d = st.columns(4)
        a.metric("Referensi relevan", len(st.session_state.theme_records))
        b.metric("Dengan DOI", m["with_doi"])
        c.metric("Dengan abstrak", m["with_abstract"])
        d.metric("Effect size otomatis", len(st.session_state.meta_studies))

with tabs[1]:
    st.subheader("📚 Bibliografi")
    upload_col, manual_col = st.columns(2)

    with upload_col:
        uploaded = st.file_uploader("Upload Excel/CSV/BibTeX/RIS", type=["xlsx", "csv", "bib", "ris", "txt"])
        if uploaded and st.button("Proses Upload Bibliografi"):
            data = uploaded.getvalue()
            name = uploaded.name.lower()
            try:
                parsed = parse_bibliography_upload(data, name)
                add_records(parsed)
                st.success(f"Berhasil membaca {len(parsed)} record.")
            except Exception as exc:
                st.error(f"Gagal memproses file: {exc}")

    with manual_col:
        with st.form("manual_reference"):
            st.write("Tambah manual")
            title = st.text_input("Judul")
            authors = st.text_input("Penulis", placeholder="Nama 1; Nama 2")
            year = st.text_input("Tahun")
            journal = st.text_input("Jurnal")
            doi = st.text_input("DOI")
            database = st.selectbox("Database", ["Manual", "Scopus", "Web of Science", "Crossref", "OpenAlex", "PubMed", "PLOS", "OpenAIRE", "DOAJ", "DataCite", "Lainnya"])
            submitted = st.form_submit_button("Tambah")
        if submitted:
            add_records(standardize([{"title": title, "authors": authors, "year": year, "journal": journal, "doi": doi, "database": database}]))
            st.success("Referensi ditambahkan.")

    records = st.session_state.theme_records or st.session_state.records
    if not records:
        st.info("Belum ada data bibliografi.")
    else:
        m = get_metrics(records)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", len(records))
        c2.metric("DOI", m["with_doi"])
        c3.metric("Abstrak", m["with_abstract"])
        c4.metric("Kandidat indeks", m["scopus"] + m["wos"] + m["high"])

        kw = st.text_input("Cari di bibliografi")
        shown = records
        if kw.strip():
            shown = [r for r in records if kw.lower() in json.dumps(r, ensure_ascii=False).lower()]

        display = []
        for r in shown:
            display.append({
                "Skor": r.get("theme_relevance_score", ""),
                "Judul": r.get("title", "")[:80] + ("..." if len(r.get("title", "")) > 80 else ""),
                "Penulis": r.get("authors", "")[:40],
                "Tahun": r.get("year", ""),
                "Jurnal": r.get("journal", "")[:40],
                "Database": r.get("database", ""),
                "Status": r.get("indexing_status", "").split(";")[0],
            })
        st.dataframe(display, use_container_width=True, height=420)

        st.write("### Insight Bibliografi")
        st.text_area("Laporan", value=build_biblio_report(records, st.session_state.last_theme), height=360)

with tabs[2]:
    st.subheader("✅ PRISMA Flow & Screening")
    records = st.session_state.theme_records or st.session_state.records

    if not records:
        st.info("Belum ada data untuk screening.")
    else:
        with st.form("screening_form"):
            c1, c2, c3 = st.columns(3)
            with c1:
                min_year2 = st.number_input("Tahun minimal", min_value=1900, max_value=2100, value=2020, key="screen_min")
                max_year2 = st.number_input("Tahun maksimal", min_value=1900, max_value=2100, value=2026, key="screen_max")
            with c2:
                only_doi2 = st.checkbox("Hanya DOI", value=False, key="screen_doi")
                must_abs2 = st.checkbox("Harus punya abstrak", value=False, key="screen_abs")
                only_indexed2 = st.checkbox("Utamakan kandidat terindeks", value=False, key="screen_index")
            with c3:
                include_terms2 = st.text_input("Kata inklusi", key="screen_inc")
                exclude_terms2 = st.text_input("Kata eksklusi", key="screen_exc")
            submit_screen = st.form_submit_button("Jalankan Screening")

        if submit_screen or not st.session_state.screened:
            criteria = {
                "min_year": min_year2, "max_year": max_year2, "only_doi": only_doi2,
                "must_have_abstract": must_abs2, "only_indexed": only_indexed2,
                "include_terms": include_terms2, "exclude_terms": exclude_terms2,
            }
            st.session_state.screened = auto_screen(records, criteria)

        screened = st.session_state.screened
        prisma = prisma_counts(st.session_state.found_total or len(records), records, screened, st.session_state.meta_studies)

        st.write("### PRISMA Counts")
        pcols = st.columns(4)
        for i, (k, v) in enumerate(prisma.items()):
            pcols[i % 4].metric(k.replace("_", " ").title(), v)

        st.write("### Tabel Screening")
        st.dataframe(screened, use_container_width=True, height=420)

with tabs[3]:
    render_systematic_review_tab()

with tabs[4]:
    st.subheader("🧪 Meta-Analysis")
    records = st.session_state.theme_records or st.session_state.records

    st.write("### Format Ekstraksi")
    meta_format = bibliographic_to_meta_format(records, st.session_state.last_theme)
    st.download_button(
        "📥 Download Format Meta-Analysis Excel",
        data=rows_to_xlsx(meta_format, META_EXTRACTION_COLUMNS, "Format Meta"),
        file_name="format_meta_analysis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=not bool(meta_format),
    )

    sample_rows = [
        {"include": "yes", "study_id": "Smith 2020", "authors": "Smith", "year": "2020", "title": "Sample A", "journal": "Journal A", "doi": "", "group": "Education", "effect_type": "smd", "effect_size": "", "standard_error": "", "n_t": "45", "mean_t": "82.4", "sd_t": "10.5", "n_c": "43", "mean_c": "77.1", "sd_c": "11.2", "event_t": "", "total_t": "", "event_c": "", "total_c": "", "non_event_t": "", "non_event_c": "", "r": "", "n": "", "outcome": "Learning", "population": "Students", "intervention": "AI", "comparison": "Traditional", "notes": "sample"},
        {"include": "yes", "study_id": "Lee 2021", "authors": "Lee", "year": "2021", "title": "Sample B", "journal": "Journal B", "doi": "", "group": "Education", "effect_type": "", "effect_size": "0.52", "standard_error": "0.15", "n_t": "", "mean_t": "", "sd_t": "", "n_c": "", "mean_c": "", "sd_c": "", "event_t": "", "total_t": "", "event_c": "", "total_c": "", "non_event_t": "", "non_event_c": "", "r": "", "n": "", "outcome": "Achievement", "population": "Students", "intervention": "AI", "comparison": "Control", "notes": "sample"},
    ]
    st.download_button(
        "📄 Download Contoh Terisi Excel",
        data=rows_to_xlsx(sample_rows, META_EXTRACTION_COLUMNS, "Contoh Meta"),
        file_name="contoh_meta_analysis_terisi.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    uploaded_meta = st.file_uploader("Upload Excel/CSV meta-analysis yang sudah diisi", type=["xlsx", "csv"])
    if uploaded_meta and st.button("Proses Meta-Analysis", type="primary"):
        studies, skipped = parse_meta_upload(uploaded_meta.getvalue(), uploaded_meta.name)
        st.session_state.meta_studies = studies
        st.session_state.rob_rows = build_rob_from_meta(studies)
        st.success(f"Studi valid: {len(studies)}. Dilewati: {skipped}.")

    if st.button("Gunakan Sample Meta-Analysis"):
        studies, skipped = parse_meta_rows(sample_rows)
        st.session_state.meta_studies = studies
        st.session_state.rob_rows = build_rob_from_meta(studies)
        st.success("Sample dimuat.")

    studies = st.session_state.meta_studies
    if not studies:
        st.info("Belum ada effect size/SE valid. Isi dan upload format Excel meta-analysis.")
    else:
        result = run_meta(studies)
        subgroup = subgroup_meta(studies)
        model = st.radio("Model utama", ["Random-effects", "Fixed-effect"], horizontal=True)
        main = result["random"] if model.startswith("Random") else result["fixed"]
        h = result["heterogeneity"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Studi", result["k"])
        c2.metric("Pooled effect", f"{main['pooled']:.4f}")
        c3.metric("95% CI", f"{main['ci'][0]:.3f} – {main['ci'][1]:.3f}")
        c4.metric("p-value", f"{main['p']:.4f}")

        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Q", f"{h['Q']:.3f}")
        h2.metric("df", h["df"])
        h3.metric("tau²", f"{h['tau2']:.4f}")
        h4.metric("I²", f"{h['I2']:.1f}%")

        display = []
        for s in result["studies"]:
            display.append({
                "Study": s.get("study_id", ""),
                "Year": s.get("year", ""),
                "Group": s.get("group", ""),
                "Type": s.get("effect_type", ""),
                "Effect": round(s.get("effect_size", 0), 4),
                "SE": round(s.get("standard_error", 0), 4),
                "95% CI": f"{s.get('lower_ci', 0):.3f} – {s.get('upper_ci', 0):.3f}",
                "Weight RE %": round(s.get("weight_random", 0), 2),
            })
        st.dataframe(display, use_container_width=True, height=320)

        st.write("### Forest Plot Sederhana")
        for s in result["studies"]:
            st.code(f"{s.get('study_id','Study')[:28]:28} {s['effect_size']: .3f} [{s['lower_ci']:.3f}, {s['upper_ci']:.3f}]")
        st.code(f"{'POOLED':28} {main['pooled']: .3f} [{main['ci'][0]:.3f}, {main['ci'][1]:.3f}]")

        st.write("### Insight")
        st.text_area("Laporan meta-analysis", value=build_meta_report(result, subgroup, model), height=360)

with tabs[6]:
    st.subheader("⚖️ Risk of Bias / Quality Assessment")
    if not st.session_state.meta_studies:
        st.info("Belum ada studi meta-analysis. Upload data meta-analysis dulu.")
    else:
        if not st.session_state.rob_rows:
            st.session_state.rob_rows = build_rob_from_meta(st.session_state.meta_studies)

        st.write("Isi penilaian manual berdasarkan full-text artikel.")
        edited_rows = []
        for i, row in enumerate(st.session_state.rob_rows):
            with st.expander(row.get("study_id", f"Study {i+1}")):
                edited = dict(row)
                cols = st.columns(3)
                options = ["Low risk", "Moderate/Unclear risk", "High risk"]
                edited["randomization"] = cols[0].selectbox("Randomization", options, index=1, key=f"rob_rand_{i}")
                edited["blinding"] = cols[1].selectbox("Blinding", options, index=1, key=f"rob_blind_{i}")
                edited["incomplete_data"] = cols[2].selectbox("Incomplete data", options, index=1, key=f"rob_inc_{i}")
                cols2 = st.columns(3)
                edited["selective_reporting"] = cols2[0].selectbox("Selective reporting", options, index=1, key=f"rob_sel_{i}")
                edited["confounding_control"] = cols2[1].selectbox("Confounding control", options, index=1, key=f"rob_conf_{i}")
                edited["sample_size_adequate"] = cols2[2].selectbox("Sample size adequate", options, index=1, key=f"rob_samp_{i}")
                edited["overall_risk"] = score_rob(edited)
                edited["notes"] = st.text_input("Catatan", value=edited.get("notes", ""), key=f"rob_note_{i}")
                st.write("Overall:", edited["overall_risk"])
                edited_rows.append(edited)

        st.session_state.rob_rows = edited_rows
        risk_counts = Counter(r.get("overall_risk", "Unclear") for r in edited_rows)
        st.write("### Ringkasan Risk of Bias")
        st.bar_chart(dict(risk_counts))
        st.dataframe(edited_rows, use_container_width=True)

with tabs[7]:
    st.subheader("📉 Sensitivity Analysis & Publication Bias")
    studies = st.session_state.meta_studies
    if len(studies) < 2:
        st.info("Minimal 2 studi diperlukan untuk sensitivity analysis.")
    else:
        loo = leave_one_out(studies)
        st.write("### Leave-One-Out Analysis")
        st.dataframe([
            {
                "Removed": r["removed_study"],
                "k": r["k_remaining"],
                "Pooled RE": round(r["pooled_random"], 4),
                "95% CI": f"{r['lower_ci']:.3f} – {r['upper_ci']:.3f}",
                "I²": f"{r['I2']:.1f}%"
            } for r in loo
        ], use_container_width=True)

        st.write("### Publication Bias")
        egger = egger_test_approx(studies)
        if not egger.get("available"):
            st.info(f"Egger test belum tersedia: {egger.get('reason')}")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Egger intercept", f"{egger['intercept']:.4f}")
            c2.metric("t/z approx", f"{egger['t']:.4f}")
            c3.metric("p approx", f"{egger['p']:.4f}")
            if egger["p"] < 0.05:
                st.warning("Ada indikasi asymmetry/publication bias. Validasi dengan funnel plot/software statistik.")
            else:
                st.success("Tidak ada indikasi kuat publication bias berdasarkan pendekatan sederhana ini.")

        st.write("### Funnel Plot Sederhana")
        for s in studies:
            yi, se = safe_float(s.get("effect_size")), safe_float(s.get("standard_error"))
            st.code(f"{s.get('study_id','Study')[:25]:25} effect={yi:.3f} se={se:.3f}")

with tabs[8]:
    render_final_insight_tab()

with tabs[9]:
    render_research_materials_tab()

with tabs[10]:
    render_journal_review_builder_tab()

with tabs[11]:
    render_qlevel_toolkit_tab()

with tabs[12]:
    render_relevant_sources_tab()

with tabs[13]:
    render_review_studio_tab()

with tabs[14]:
    st.subheader("📤 Export")
    records = st.session_state.theme_records or st.session_state.records
    screened = st.session_state.screened
    meta_studies = st.session_state.meta_studies
    meta_result = run_meta(meta_studies) if meta_studies else {"k": 0, "studies": []}
    prisma = prisma_counts(st.session_state.found_total or len(records), records, screened, meta_studies)
    final_summary = build_final_summary(st.session_state.last_theme, records, screened, meta_result, prisma)

    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 Bibliografi Excel", data=rows_to_xlsx(records, COLUMNS, "Bibliografi"), file_name="bibliografi.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, disabled=not bool(records))
        st.download_button("📥 Bibliografi BibTeX", data=to_bibtex(records).encode("utf-8"), file_name="bibliografi.bib", mime="text/plain", use_container_width=True, disabled=not bool(records))
        st.download_button("📥 Screening PRISMA Excel", data=rows_to_xlsx(screened, SCREENING_COLUMNS, "Screening PRISMA"), file_name="screening_prisma.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, disabled=not bool(screened))
        st.download_button("📥 Risk of Bias Excel", data=rows_to_xlsx(st.session_state.rob_rows, ROB_COLUMNS, "Risk of Bias"), file_name="risk_of_bias.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, disabled=not bool(st.session_state.rob_rows))
    with col2:
        meta_format = bibliographic_to_meta_format(records, st.session_state.last_theme)
        st.download_button("📥 Format Meta-Analysis Excel", data=rows_to_xlsx(meta_format, META_EXTRACTION_COLUMNS, "Format Meta"), file_name="format_meta_analysis.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, disabled=not bool(meta_format))
        st.download_button(
            "📥 Hasil Meta Excel",
            data=rows_to_xlsx(meta_result.get("studies", []), list(meta_result.get("studies", [{}])[0].keys()) if meta_result.get("studies") else META_EXTRACTION_COLUMNS, "Hasil Meta"),
            file_name="hasil_meta_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            disabled=not bool(meta_result.get("studies"))
        )
        st.download_button("📥 Laporan Bibliografi TXT", data=build_biblio_report(records, st.session_state.last_theme).encode("utf-8"), file_name="laporan_bibliografi.txt", mime="text/plain", use_container_width=True, disabled=not bool(records))
        executive_insight = build_executive_insight(st.session_state.last_theme, records, screened, meta_studies, st.session_state.rob_rows)
        research_materials = build_research_materials_report(st.session_state.last_theme, records, screened, meta_studies, st.session_state.rob_rows)
        st.download_button("📥 Laporan Akhir TXT", data=final_summary.encode("utf-8"), file_name="laporan_akhir_biblio_meta.txt", mime="text/plain", use_container_width=True)

        figure_caption_report = build_figure_caption_report(records, screened, meta_studies)
        st.download_button("📥 Figure Caption Report TXT", data=figure_caption_report.encode("utf-8"), file_name="figure_caption_interpretation_report.txt", mime="text/plain", use_container_width=True)

        tables_figures_report = build_tables_figures_report(st.session_state.last_theme or "precision livestock farming", records, screened, meta_studies, st.session_state.rob_rows)
        st.download_button("📥 Tables & Figures Plan Report TXT", data=tables_figures_report.encode("utf-8"), file_name="tables_figures_plan_report.txt", mime="text/plain", use_container_width=True)

        qc_report = build_quality_control_report(st.session_state.last_theme or "precision livestock farming", records, screened, meta_studies, st.session_state.rob_rows)
        st.download_button("📥 Quality Control Report TXT", data=qc_report.encode("utf-8"), file_name="quality_control_validity_report.txt", mime="text/plain", use_container_width=True)

        research_assistant_report = build_research_assistant_report(st.session_state.last_theme or "precision livestock farming", records, screened, meta_studies, st.session_state.rob_rows)
        st.download_button("📥 Research Assistant Report TXT", data=research_assistant_report.encode("utf-8"), file_name="research_assistant_report.txt", mime="text/plain", use_container_width=True)
        meta_guide_text = build_meta_analysis_steps_guide(st.session_state.last_theme or "precision livestock farming")
        st.download_button("📥 Panduan Meta-Analisis TXT", data=meta_guide_text.encode("utf-8"), file_name="panduan_meta_analisis.txt", mime="text/plain", use_container_width=True)

        studio_report = build_qlevel_improvement_report(st.session_state.last_theme, records, screened, meta_studies, st.session_state.rob_rows)
        st.download_button("📥 Q-Level Review Studio Report TXT", data=studio_report.encode("utf-8"), file_name="qlevel_review_studio_report.txt", mime="text/plain", use_container_width=True)

        systematic_protocol = build_systematic_review_protocol(st.session_state.last_theme, records, screened)
        systematic_draft = build_systematic_review_draft(st.session_state.last_theme, records, screened, meta_studies, st.session_state.rob_rows)
        st.download_button("📥 Protokol Systematic Review TXT", data=systematic_protocol.encode("utf-8"), file_name="protokol_systematic_review.txt", mime="text/plain", use_container_width=True)
        st.download_button("📥 Draft Systematic Review TXT", data=systematic_draft.encode("utf-8"), file_name="draft_systematic_review.txt", mime="text/plain", use_container_width=True)
        st.download_button("📥 Insight Akhir TXT", data=executive_insight.encode("utf-8"), file_name="insight_akhir_biblio_meta.txt", mime="text/plain", use_container_width=True)

        review_draft = build_journal_review_draft(st.session_state.last_theme, records, screened, meta_studies, st.session_state.rob_rows)
        st.download_button("📥 Draft Artikel Review TXT", data=review_draft.encode("utf-8"), file_name="draft_artikel_review.txt", mime="text/plain", use_container_width=True)

        qlevel_report = build_qlevel_report(st.session_state.last_theme, records, screened, meta_studies, st.session_state.rob_rows)
        st.download_button("📥 Q-Level Readiness Report TXT", data=qlevel_report.encode("utf-8"), file_name="qlevel_journal_readiness_report.txt", mime="text/plain", use_container_width=True)

        source_catalog = relevant_source_catalog(st.session_state.last_theme)
        if "rows_to_xlsx" in globals():
            st.download_button("📥 Daftar Sumber Relevan Excel", data=rows_to_xlsx(source_catalog, ["source", "type", "best_for", "use_in_app", "note"], "Sumber Relevan"), file_name="daftar_sumber_relevan.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        else:
            st.download_button("📥 Daftar Sumber Relevan CSV", data=safe_csv(source_catalog, ["source", "type", "best_for", "use_in_app", "note"]), file_name="daftar_sumber_relevan.csv", mime="text/csv", use_container_width=True)
        st.download_button("📥 Bahan Penelitian TXT", data=research_materials.encode("utf-8"), file_name="bahan_penelitian_biblio_meta.txt", mime="text/plain", use_container_width=True)

with tabs[15]:
    st.subheader("📖 Panduan")
    st.markdown("""
### Alur yang disarankan
1. Buka tab **Workflow Tema**.
2. Masukkan tema penelitian.
3. Jalankan pencarian otomatis.
4. Cek hasil di **Bibliografi**.
5. Cek screening dan PRISMA di **PRISMA & Screening, Systematic Review**.
6. Download format Excel meta-analysis dari tab **Meta-Analysis**.
7. Isi effect size/SE atau data mentah dari full-text artikel.
8. Upload kembali file tersebut ke tab **Meta-Analysis**.
9. Isi **Risk of Bias**.
10. Cek **Sensitivity & Bias**.
11. Buka **Bahan Penelitian** dan **Jurnal Review Builder dan Q-Level Toolkit dan Sumber Relevan** untuk mengambil judul, rumusan masalah, gap, novelty, pembahasan, kesimpulan, serta draft artikel review, checklist Q-level, cover letter, dan response-to-reviewer template.
12. Export laporan dari tab **Export**.

### Sumber kredibel
- Crossref
- OpenAlex
- PubMed
- Semantic Scholar
- DOAJ
- arXiv
- Europe PMC
- DataCite

### Catatan penting
Status Scopus/WoS/high impact adalah kandidat berbasis metadata, bukan validasi resmi. Validasi akhir tetap perlu dilakukan melalui Scopus, Web of Science, JCR, SJR, AGRIS/FAO, PubAg/USDA, CAB Abstracts, IEEE Xplore, ScienceDirect, SpringerLink, atau laman resmi jurnal.

Untuk meta-analysis, hasil otomatis harus divalidasi kembali dengan full-text dan software statistik khusus jika digunakan untuk publikasi akademik.
""")
