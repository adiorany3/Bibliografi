# Sistem Bibliografi Riset Streamlit Cloud

Aplikasi ini dibuat untuk mengelola bibliografi riset dari:
- Crossref
- OpenAlex
- file ekspor Scopus/WoS berbentuk CSV
- file BibTeX/RIS dari Zotero, Mendeley, Publish or Perish, dan reference manager lain

## Fitur

- Pencarian metadata bibliografi berdasarkan keyword/topik riset
- Upload CSV, BibTeX, dan RIS
- Input referensi manual
- Deduplikasi berdasarkan DOI atau kombinasi judul-jurnal-tahun
- Penandaan kandidat Scopus, Web of Science, dan high-impact journal
- Ekspor CSV, BibTeX, RIS, dan JSON

## Cara deploy ke Streamlit Community Cloud

1. Upload isi folder ini ke GitHub.
2. Pastikan file utama bernama `app.py`.
3. Masuk ke Streamlit Community Cloud.
4. Pilih repository, branch `main`, dan main file path `app.py`.
5. Pada **Advanced settings**, pilih Python **3.12** atau **3.11**.
6. Klik Deploy.

## Catatan penting

Dari log yang dikirim, Streamlit Cloud memakai Python 3.14.4. Beberapa package Python masih rawan error pada versi terlalu baru. Karena itu versi ini dibuat sangat ringan dan hanya memakai:

```txt
streamlit>=1.40,<2
requests>=2.31,<3
```

Jika deployment lama masih memakai Python 3.14, hapus aplikasi di Streamlit Cloud lalu deploy ulang dan pilih Python 3.12/3.11 di Advanced settings.

## Struktur file

```txt
app.py
requirements.txt
.streamlit/config.toml
data/sample_references.csv
README.md
```
