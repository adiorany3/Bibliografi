# Sistem Bibliografi & Meta-Analisis Final Clean

Aplikasi Streamlit untuk workflow penelitian:
tema → bibliografi → PRISMA screening → risk of bias → meta-analysis → sensitivity/publication bias → laporan.

## Fitur
- Pencarian sumber kredibel: Crossref, OpenAlex, PubMed, Semantic Scholar, DOAJ, arXiv, Europe PMC, DataCite
- Upload CSV, BibTeX, RIS
- Deduplikasi bibliografi
- Skor relevansi tema
- Screening inklusi-eksklusi
- PRISMA counts
- Format ekstraksi meta-analysis otomatis dari bibliografi
- Meta-analysis fixed-effect dan random-effects DerSimonian-Laird
- SMD/Hedges g, log OR, log RR, Fisher z
- Risk of bias/quality assessment
- Leave-one-out sensitivity analysis
- Egger test approximate
- Export CSV, BibTeX, dan laporan TXT

## Jalankan Lokal
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy Streamlit Cloud
- Upload semua file ke GitHub
- Main file: `app.py`
- Gunakan Python 3.11 atau 3.12 jika tersedia

## Penyempurnaan Insight Akhir

Ditambahkan tab **Insight Akhir**:
- Skor kualitas bibliografi
- Skor kesiapan meta-analysis
- Level kekuatan bukti
- Ringkasan PRISMA
- Ringkasan risk of bias
- Rekomendasi tindakan otomatis
- Insight naratif siap pakai untuk laporan

## Excel XLSX

Versi ini mengubah format utama dari CSV menjadi Excel `.xlsx` agar lebih mudah dibuka, dibaca, diedit, dan ditambahkan di Microsoft Excel/Google Sheets/WPS Office.

Yang tersedia dalam `.xlsx`:
- Bibliografi
- Screening PRISMA
- Risk of Bias
- Format Meta-Analysis
- Contoh Meta-Analysis Terisi
- Hasil Meta-Analysis

Upload juga sudah mendukung `.xlsx` untuk bibliografi dan meta-analysis.

## Fix Excel Export

Perbaikan:
- Menambahkan `import zipfile` ke `app.py`.
- Error `NameError: name 'zipfile' is not defined` sudah diperbaiki.
- Export/import Excel `.xlsx` tetap berjalan tanpa dependency tambahan.

## Bahan Penelitian

Ditambahkan tab **Bahan Penelitian** yang menghasilkan:
- Alternatif judul
- Rumusan masalah
- Tujuan penelitian
- Search string
- Kriteria inklusi-eksklusi
- Protokol ekstraksi data
- Gap penelitian
- Novelty/kebaruan
- Poin pembahasan
- Keterbatasan
- Draft kesimpulan
- Insight lengkap siap laporan

## Jurnal Review Builder

Ditambahkan tab **Jurnal Review Builder** untuk mempermudah penyusunan artikel review:
- Outline artikel review
- Alternatif judul
- Rumusan masalah
- Draft abstrak
- Draft pendahuluan
- Draft metode PRISMA
- Draft hasil bibliografi dan meta-analysis
- Draft pembahasan
- Implikasi
- Keterbatasan
- Kesimpulan
- Rencana tabel dan figure
- Template karakteristik studi
- Checklist kesiapan naskah

## Q-Level Journal Toolkit

Ditambahkan tab **Q-Level Toolkit** untuk membantu naskah sesuai kaidah jurnal bereputasi:
- Skor kesiapan Q-level
- Checklist naskah review
- Struktur artikel Q-level
- Contribution/novelty statement
- Language and reporting polish checklist
- Cover letter template
- Response to reviewer template
- Q-Level readiness report

## Sumber Relevan

Ditambahkan:
- Sumber API baru: PLOS
- Tab **Sumber Relevan**
- Rekomendasi database aktif dan import manual
- Query variants otomatis untuk tema seperti precision livestock farming
- Daftar sumber penting: AGRIS/FAO, USDA PubAg, CAB Abstracts, IEEE Xplore, ScienceDirect, SpringerLink, MDPI, Frontiers, Taylor & Francis, Wiley
- Export daftar sumber relevan

## Fix PLOS Source Order

Perbaikan:
- Fungsi `search_plos()` sekarang diletakkan sebelum `SOURCE_FUNCTIONS`.
- Error `NameError: name 'search_plos' is not defined` sudah diperbaiki.
- `app.py` sudah dicek compile.
