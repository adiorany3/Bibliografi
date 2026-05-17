# Sistem Bibliografi Riset - Complete Bibliometric Analysis

Aplikasi Streamlit untuk proses bibliografi dan bibliometric analysis yang dibuat mengikuti struktur umum pada Donthu et al. (2021), *How to conduct a bibliometric analysis: An overview and guidelines*.

## Fitur Utama

### Sumber Kredibel
- Crossref
- OpenAlex
- PubMed
- Semantic Scholar
- DOAJ
- arXiv
- Europe PMC
- CORE
- Upload Scopus/Web of Science/Dimensions/Lens/Zotero/Mendeley via CSV, RIS, atau BibTeX

### Analisis Bibliometrik
- Performance analysis: TP, NCA, SA, CA, NAY, PAY, TC, AC, CI, CC, NCP, PCP, CCP, h-index, g-index, i10
- Citation analysis
- Co-citation analysis
- Bibliographic coupling
- Co-word analysis
- Co-authorship analysis
- Network metrics ringan: degree centrality, weighted degree, density, approximate prestige/eigen
- Methodology builder: aim & scope, search string, checklist procedure
- Export laporan TXT

### Ekspor
- CSV
- BibTeX
- RIS
- JSON
- VOSviewer `.net`
- CiteSpace/plain text `.txt`

## Cara Menjalankan Lokal

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy Streamlit Cloud

1. Upload isi folder ini ke GitHub.
2. Buka Streamlit Cloud.
3. Pilih repository dan branch `main`.
4. Main file path: `app.py`.
5. Disarankan Python 3.11 atau 3.12.
6. Deploy.

## Catatan

Status Scopus/WoS/high impact di aplikasi ini adalah kandidat berbasis metadata. Validasi resmi tetap perlu dilakukan melalui Scopus, Web of Science, JCR, SJR, atau laman resmi jurnal.
