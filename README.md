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
