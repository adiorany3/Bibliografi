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


## Tambahan: Meta-Analytic Analysis

Aplikasi ini sekarang memiliki tab **Meta-Analytic** untuk menganalisis studi empiris berbasis effect size.

Fitur:
- Input generic effect size + standard error
- Hitung Hedges g/SMD dari mean, SD, dan n dua kelompok
- Hitung log odds ratio dari tabel 2x2
- Hitung log risk ratio
- Hitung Fisher z dari korelasi
- Fixed-effect model
- Random-effects model DerSimonian-Laird
- Heterogeneity: Q, tau², I²
- Subgroup analysis
- Forest plot sederhana
- Ekspor CSV dan laporan TXT

Catatan: fitur ini memakai Python standard library agar tetap ringan di Streamlit Cloud. Untuk publikasi akademik, validasi kembali hasil dengan software statistik khusus seperti R metafor/meta, RevMan, JASP, Jamovi, atau Stata.

## Fix v2 Meta-Analytic

Perbaikan:
- `meta_tab` sekarang sudah ikut dideklarasikan di `st.tabs()`.
- Error `NameError: name 'meta_tab' is not defined` sudah diperbaiki.
- `app.py` sudah dicek dengan Python compile.


## Auto Complete Insight v3

Perbaikan:
- Menambahkan mode pencarian otomatis.
- Menambahkan DataCite sebagai sumber kredibel.
- Menghapus CORE dari pencarian otomatis karena sering error/API restricted di Streamlit Cloud.
- Sumber yang gagal/rate-limited otomatis dilewati tanpa menghentikan aplikasi.
- Menambahkan insight otomatis: kualitas metadata, temuan utama, rekomendasi, distribusi sumber, dan kelengkapan data.
- Menambahkan tombol deduplikasi/cleaning ulang.
