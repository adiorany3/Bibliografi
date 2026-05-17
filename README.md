# Sistem Bibliografi Riset Streamlit

Aplikasi Streamlit untuk mengelola bibliografi riset dari Crossref, OpenAlex, upload ekspor Scopus/WoS, BibTeX, dan RIS.

## Fitur

- Pencarian metadata dari Crossref dan OpenAlex tanpa API key.
- Integrasi opsional Scopus API dan Web of Science Starter API.
- Upload CSV/XLSX/BibTeX/RIS.
- Standarisasi kolom bibliografi.
- Deduplication berdasarkan DOI atau judul+jurnal+tahun.
- Klasifikasi awal: Scopus candidate, Web of Science candidate, high-impact candidate, dan needs verification.
- Dashboard ringkas dan grafik distribusi tahun/status.
- Ekspor CSV, Excel, BibTeX, dan RIS.

## Cara menjalankan lokal

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Cara deploy ke Streamlit Cloud

1. Upload semua file ke GitHub.
2. Buka Streamlit Cloud.
3. Pilih **New app**.
4. Pilih repository dan branch.
5. Isi main file path: `app.py`.
6. Klik **Deploy**.

## Secrets opsional

Tambahkan di **App settings → Secrets** jika ingin memakai API resmi:

```toml
SCOPUS_API_KEY = "isi_api_key_scopus"
WOS_API_KEY = "isi_api_key_wos"
```

## Catatan validasi

Aplikasi ini membantu proses bibliografi dan memberi indikasi awal. Status Scopus/WoS/high impact tetap harus diverifikasi melalui sumber resmi seperti Scopus Sources, Web of Science Master Journal List, dan Journal Citation Reports.
