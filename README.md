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

## Systematic Review

Ditambahkan tab **Systematic Review**:
- Framework PICO/PECO/SPIDER otomatis
- Protokol systematic review
- Search strategy dan eligibility criteria
- Study selection procedure
- Data extraction plan
- PRISMA checklist
- Draft systematic review
- Export protokol, draft, dan checklist

## Q-Level Review Studio

Ditambahkan modul **Review Studio** untuk mempermudah penulis:
- Mengumpulkan data: rencana database, query, upload manual, deduplikasi
- Menganalisa data: decision tree, missing data, readiness score
- Menulis draft: prompts tiap bagian naskah dan draft cepat
- Menyesuaikan Q-level: target journal fit, strategi perbaikan, action plan
- Export action plan dan Q-Level Review Studio Report

## Fix Review Studio Kosong

Perbaikan:
- Review Studio sekarang tetap menampilkan template meskipun dataset belum ada.
- Menambahkan input tema langsung di Review Studio.
- Menambahkan fallback draft, action plan, writing prompts, Q-level strategy, dan checklist.
- Render tab Review Studio dipastikan terpanggil sebelum tab Export.

## Panduan Meta-Analisis Praktis

Ditambahkan tab **Panduan Meta**:
- Langkah meta-analisis dari PICO sampai publication bias
- Checklist meta-analysis
- Template data meta-analysis Excel
- Catatan Q-level untuk pelaporan meta-analysis
- Export panduan meta-analysis

## Fix Panduan Meta Visible

Perbaikan:
- Panduan Meta sekarang ditampilkan langsung di dalam tab **📖 Panduan**.
- Tidak bergantung pada indeks tab baru, sehingga tidak hilang meskipun urutan tab berubah.
- Panduan tetap tampil walaupun dataset belum ada.
- Checklist meta-analysis dan export panduan ditambahkan.

## Research Assistant Hub

Ditambahkan modul **Research Assistant Hub** di tab Panduan:
- Status tahapan riset
- Matriks pertanyaan penelitian
- Matriks data yang harus dikumpulkan
- Timeline riset
- Bahan untuk menulis draft
- Masukan otomatis untuk kesiapan jurnal Q-level
- Export Research Assistant Report
- Export Matriks Data Riset

## Tambahan Sumber dan Deduplikasi Otomatis

Perbaikan:
- Menambahkan sumber API aktif: OpenAIRE.
- Menambahkan sumber manual/import: Cochrane Library, Google Scholar, Dimensions, ProQuest Dissertations, Research Rabbit/Connected Papers.
- Deduplikasi otomatis diperkuat menggunakan DOI, normalisasi judul, tahun, dan author pertama.
- Metadata dari duplikat digabung, termasuk database, abstract, keyword, notes, dan indexing status.
- Panel deduplikasi ditambahkan di tab Bibliografi.

## Fix OpenAIRE Source Order

Perbaikan:
- Fungsi `search_openaire()` sekarang diletakkan sebelum `SOURCE_FUNCTIONS`.
- Error `NameError: name 'search_openaire' is not defined` sudah diperbaiki.
- Deduplikasi otomatis tetap aktif.
- `app.py` sudah dicek compile.

## Quality Control & Validity Guard

Ditambahkan modul kendali mutu:
- Multidatabase search strategy
- Sinonim, MeSH/controlled vocabulary, Boolean search
- Grey literature strategy
- Double-blinded screening template
- Discrepancy resolution
- Risk of bias tool selector
- Sensitivity analysis guidance
- Heterogeneity action plan
- Subgroup/meta-regression notes
- QC checklist dan export report
