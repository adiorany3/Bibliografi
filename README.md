# Sistem Bibliografi Riset - Banyak Sumber Kredibel

Aplikasi Streamlit untuk mengelola bibliografi riset dari banyak sumber kredibel.

## Sumber yang tersedia
- Crossref
- OpenAlex
- PubMed
- Semantic Scholar
- DOAJ
- arXiv
- Europe PMC
- CORE
- Upload Scopus/Web of Science/Dimensions/Lens/Zotero/Mendeley via CSV, RIS, atau BibTeX

## Fitur
- Cari metadata dari banyak sumber
- Upload CSV, BibTeX, RIS
- Input referensi manual
- Deteksi kandidat Scopus/WoS/high impact berbasis metadata
- Insight bibliometrik sederhana
- Ekspor CSV, BibTeX, RIS, JSON, dan VOSviewer `.net`

## Cara Jalankan Lokal

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy Streamlit Cloud

1. Upload semua file ke GitHub.
2. Buat app baru di Streamlit Cloud.
3. Pilih repository dan branch `main`.
4. Main file path: `app.py`.
5. Gunakan Python 3.11 atau 3.12 jika tersedia.

## Catatan Penting

Status Scopus/WoS/high impact di aplikasi ini adalah kandidat berbasis metadata, bukan validasi resmi. Validasi akhir tetap perlu dilakukan di Scopus, Web of Science, JCR, SJR, atau laman resmi jurnal.
