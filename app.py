
from __future__ import annotations

import csv
import io
import json
import math
import re
import xml.etree.ElementTree as ET
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
    sources = ["Crossref", "OpenAlex", "Semantic Scholar", "DOAJ", "DataCite"]
    if any(t in text for t in ["health", "medical", "clinical", "patient", "disease", "biomedical", "nursing", "public health", "kesehatan", "medis", "pasien"]):
        sources += ["PubMed", "Europe PMC"]
    if any(t in text for t in ["computer", "machine learning", "artificial intelligence", "ai", "deep learning", "algorithm", "software", "physics", "mathematics", "statistics", "quantum"]):
        sources += ["arXiv"]
    return list(dict.fromkeys([s for s in sources if s in SOURCE_FUNCTIONS]))


def add_records(records: List[Dict[str, str]]) -> None:
    existing = st.session_state.get("records", [])
    st.session_state.records = standardize(existing + records)


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
        "3. PRISMA & Screening",
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
    "🧪 Meta-Analysis",
    "⚖️ Risk of Bias",
    "📉 Sensitivity & Bias",
    "📌 Insight Akhir",
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
                    res = SOURCE_FUNCTIONS[source](theme, rows_per_source, email)
                    found += res
                    st.write(f"✅ {source}: {len(res)} record")
                except Exception as exc:
                    errors.append(f"{source}: {exc}")
                    st.write(f"⚠️ {source}: gagal/dilewati")
                progress.progress(i / len(selected_sources))

            unique_records = standardize(found)
            relevant = filter_relevant(unique_records, theme, min_score)
            st.session_state.found_total = len(found)
            st.session_state.theme_records = relevant
            st.session_state.records = standardize(st.session_state.records + relevant)
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
            database = st.selectbox("Database", ["Manual", "Scopus", "Web of Science", "Crossref", "OpenAlex", "PubMed", "DOAJ", "Lainnya"])
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

with tabs[4]:
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

with tabs[5]:
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

with tabs[6]:
    render_final_insight_tab()

with tabs[7]:
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
        st.download_button("📥 Laporan Akhir TXT", data=final_summary.encode("utf-8"), file_name="laporan_akhir_biblio_meta.txt", mime="text/plain", use_container_width=True)
        st.download_button("📥 Insight Akhir TXT", data=executive_insight.encode("utf-8"), file_name="insight_akhir_biblio_meta.txt", mime="text/plain", use_container_width=True)

with tabs[8]:
    st.subheader("📖 Panduan")
    st.markdown("""
### Alur yang disarankan
1. Buka tab **Workflow Tema**.
2. Masukkan tema penelitian.
3. Jalankan pencarian otomatis.
4. Cek hasil di **Bibliografi**.
5. Cek screening dan PRISMA di **PRISMA & Screening**.
6. Download format Excel meta-analysis dari tab **Meta-Analysis**.
7. Isi effect size/SE atau data mentah dari full-text artikel.
8. Upload kembali file tersebut ke tab **Meta-Analysis**.
9. Isi **Risk of Bias**.
10. Cek **Sensitivity & Bias**.
11. Export laporan dari tab **Export**.

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
Status Scopus/WoS/high impact adalah kandidat berbasis metadata, bukan validasi resmi. Validasi akhir tetap perlu dilakukan melalui Scopus, Web of Science, JCR, SJR, atau laman resmi jurnal.

Untuk meta-analysis, hasil otomatis harus divalidasi kembali dengan full-text dan software statistik khusus jika digunakan untuk publikasi akademik.
""")
