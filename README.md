# Sistem Bibliografi Riset Scopus, WoS & Jurnal High Impact

Aplikasi ini dibuat dengan Streamlit untuk membantu proses bibliografi riset dari sumber metadata terbuka maupun file ekspor Scopus, Web of Science, dan jurnal bereputasi.

## Fitur

- Pencarian metadata artikel via Crossref dan OpenAlex.
- Integrasi opsional Scopus API dan Web of Science Starter API jika memiliki API key resmi.
- Upload file ekspor bibliografi: CSV, Excel, BibTeX, RIS.
- Input referensi manual.
- Normalisasi metadata: judul, penulis, tahun, jurnal, publisher, DOI, URL, abstrak.
- Deteksi awal status indeks: Scopus, Web of Science, high-impact candidate, atau needs verification.
- Filter berdasarkan tahun, status indeks, dan keyword.
- Dashboard ringkas dengan metrik dan visualisasi.
- Ekspor hasil ke CSV, Excel, BibTeX, dan RIS.

## Struktur Folder

```text
biblio_streamlit_app/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
└── utils/
    └── bibliography.py
```

## Cara Menjalankan Lokal

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy ke Streamlit Cloud

1. Upload folder ini ke GitHub.
2. Masuk ke Streamlit Cloud.
3. Klik **New app**.
4. Pilih repository dan branch.
5. Isi main file dengan:

```text
app.py
```

6. Klik **Deploy**.

## Konfigurasi API Key Opsional

Jika ingin memakai Scopus API atau Web of Science API, tambahkan secrets di Streamlit Cloud:

```toml
SCOPUS_API_KEY = "isi_api_key_scopus"
WOS_API_KEY = "isi_api_key_wos"
```

API resmi Scopus dan Web of Science biasanya membutuhkan akses institusi atau langganan.

## Format Kolom yang Disarankan untuk Upload CSV/XLSX

Aplikasi akan mencoba mengenali beberapa variasi nama kolom. Format paling aman:

| Kolom | Keterangan |
|---|---|
| title | Judul artikel |
| authors | Penulis, pisahkan dengan titik koma |
| year | Tahun publikasi |
| journal | Nama jurnal/prosiding |
| publisher | Penerbit |
| doi | DOI artikel |
| url | Link artikel |
| abstract | Abstrak |
| keywords | Kata kunci |
| database | Sumber database, contoh Scopus/WoS |
| impact_factor | Impact factor/JIF/CiteScore jika tersedia |
| notes | Catatan tambahan |

## Catatan Penting

Fitur deteksi Scopus, WoS, dan high-impact pada aplikasi ini bersifat verifikasi awal berdasarkan metadata. Untuk kebutuhan akademik final, tetap lakukan pengecekan manual melalui sumber resmi seperti Scopus Sources, Web of Science Master Journal List, Journal Citation Reports, atau laman resmi jurnal/publisher.
