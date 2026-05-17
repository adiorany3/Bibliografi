# Sistem Bibliografi Riset

Aplikasi Streamlit untuk mengelola bibliografi riset dari Crossref, OpenAlex, file CSV Scopus/WoS, BibTeX, dan RIS.

## Fitur
- Cari metadata dari Crossref dan OpenAlex
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
