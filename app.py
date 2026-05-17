from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.bibliography import (
    COLUMNS,
    dataframe_to_bibtex,
    dataframe_to_ris,
    parse_uploaded_file,
    search_crossref,
    search_openalex,
    search_scopus,
    search_wos,
    standardize_records,
)

st.set_page_config(
    page_title="Sistem Bibliografi Riset",
    page_icon="📚",
    layout="wide",
)


def safe_secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def reset_data() -> None:
    st.session_state.df = standardize_records([])


if "df" not in st.session_state:
    reset_data()

st.title("📚 Sistem Bibliografi Riset Scopus, WoS & High Impact Journal")
st.caption(
    "Aplikasi untuk mengumpulkan, membersihkan, memfilter, dan mengekspor data bibliografi. "
    "Validasi Scopus/WoS/impact factor tetap perlu dicek ulang melalui sumber resmi karena sebagian database berlisensi."
)

with st.sidebar:
    st.header("Pengaturan")
    email = st.text_input("Email untuk request API publik", value="", placeholder="nama@email.com")
    max_rows = st.slider("Jumlah hasil per sumber", 5, 100, 25, step=5)
    st.divider()
    st.subheader("API Opsional")
    scopus_key = st.text_input("Scopus API Key", type="password", value=safe_secret("SCOPUS_API_KEY"))
    wos_key = st.text_input("WoS Starter API Key", type="password", value=safe_secret("WOS_API_KEY"))
    st.info("Tanpa API key, gunakan Crossref/OpenAlex atau upload hasil ekspor Scopus/WoS.")
    if st.button("Kosongkan Semua Data", use_container_width=True):
        reset_data()
        st.success("Data dikosongkan.")

search_tab, upload_tab, manual_tab, dashboard_tab, export_tab, guide_tab = st.tabs(
    ["🔎 Cari Literatur", "⬆️ Upload Ekspor", "✍️ Input Manual", "📊 Dashboard", "📤 Ekspor", "🚀 Deploy Guide"]
)

with search_tab:
    st.subheader("Cari metadata bibliografi")
    query = st.text_input("Topik / keyword riset", placeholder="Contoh: artificial intelligence education bibliometric")
    sources = st.multiselect(
        "Sumber data",
        ["Crossref", "OpenAlex", "Scopus API", "Web of Science API"],
        default=["Crossref", "OpenAlex"],
    )
    run_search = st.button("Cari & Gabungkan", type="primary", use_container_width=True)

    if run_search:
        if not query.strip():
            st.warning("Masukkan keyword riset terlebih dahulu.")
        elif not sources:
            st.warning("Pilih minimal satu sumber data.")
        else:
            frames = []
            errors = []
            with st.spinner("Mengambil metadata bibliografi..."):
                jobs = [
                    ("Crossref", lambda: search_crossref(query, max_rows, email)),
                    ("OpenAlex", lambda: search_openalex(query, max_rows, email)),
                    ("Scopus API", lambda: search_scopus(query, scopus_key, max_rows)),
                    ("Web of Science API", lambda: search_wos(query, wos_key, max_rows)),
                ]
                for name, fn in jobs:
                    if name not in sources:
                        continue
                    try:
                        result = fn()
                        if not result.empty:
                            frames.append(result)
                    except Exception as exc:
                        errors.append(f"{name}: {exc}")

            if frames:
                combined = pd.concat([st.session_state.df] + frames, ignore_index=True)
                st.session_state.df = standardize_records(combined)
                st.success(f"Berhasil menggabungkan {len(st.session_state.df)} record unik.")
            else:
                st.warning("Belum ada data yang berhasil diambil. Coba keyword lain atau upload file ekspor.")

            if errors:
                st.error("Beberapa sumber gagal diakses:\n" + "\n".join(f"- {e}" for e in errors))

with upload_tab:
    st.subheader("Upload data dari Scopus / WoS / Zotero / Mendeley")
    st.write("Format didukung: CSV, XLSX, BibTeX (.bib), dan RIS (.ris).")
    uploaded = st.file_uploader("Pilih file ekspor bibliografi", type=["csv", "xlsx", "bib", "ris"])
    if uploaded and st.button("Proses File", type="primary", use_container_width=True):
        try:
            upload_df = parse_uploaded_file(uploaded)
            if upload_df.empty:
                st.warning("File terbaca, tetapi tidak ditemukan kolom judul/DOI yang valid.")
            else:
                combined = pd.concat([st.session_state.df, upload_df], ignore_index=True)
                st.session_state.df = standardize_records(combined)
                st.success(f"File diproses. Total record unik sekarang: {len(st.session_state.df)}")
                st.dataframe(upload_df, use_container_width=True, height=260)
        except Exception as exc:
            st.error(f"Gagal memproses file: {exc}")

with manual_tab:
    st.subheader("Tambah referensi manual")
    with st.form("manual_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            title = st.text_area("Judul artikel", height=90)
            authors = st.text_input("Penulis", placeholder="Nama 1; Nama 2; Nama 3")
            year = st.text_input("Tahun", placeholder="2024")
            journal = st.text_input("Nama jurnal/prosiding")
        with c2:
            publisher = st.text_input("Publisher")
            doi = st.text_input("DOI")
            url = st.text_input("URL")
            database = st.selectbox("Database", ["Manual", "Scopus", "Web of Science", "SINTA", "Google Scholar", "Lainnya"])
            impact_factor = st.text_input("Impact Factor / JIF / CiteScore", placeholder="Opsional, contoh: 7.2")
        abstract = st.text_area("Abstrak / catatan", height=90)
        submitted = st.form_submit_button("Tambahkan Referensi")

    if submitted:
        new_df = standardize_records([{
            "title": title,
            "authors": authors,
            "year": year,
            "journal": journal,
            "publisher": publisher,
            "doi": doi,
            "url": url,
            "database": database,
            "impact_factor": impact_factor,
            "abstract": abstract,
        }])
        if new_df.empty:
            st.warning("Minimal isi judul atau DOI.")
        else:
            st.session_state.df = standardize_records(pd.concat([st.session_state.df, new_df], ignore_index=True))
            st.success("Referensi manual berhasil ditambahkan.")

with dashboard_tab:
    st.subheader("Dashboard Bibliografi")
    df = st.session_state.df.copy()
    if df.empty:
        st.info("Belum ada data. Gunakan pencarian, upload file ekspor, atau input manual.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Referensi", len(df))
        k2.metric("Dengan DOI", int((df["doi"].astype(str).str.len() > 0).sum()))
        k3.metric("Scopus/WoS Candidate", int(df["indexing_status"].str.contains("Scopus|Web of Science", case=False, na=False).sum()))
        k4.metric("High-impact Candidate", int(df["indexing_status"].str.contains("High", case=False, na=False).sum()))

        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            years = sorted([y for y in df["year"].dropna().astype(str).unique() if y])
            selected_years = st.multiselect("Filter tahun", years, default=years)
        with fc2:
            status_options = sorted(df["indexing_status"].dropna().unique())
            selected_status = st.multiselect("Filter status indeks", status_options, default=status_options)
        with fc3:
            keyword_filter = st.text_input("Cari di judul/jurnal/penulis")

        filtered = df.copy()
        if selected_years:
            filtered = filtered[filtered["year"].astype(str).isin(selected_years)]
        if selected_status:
            filtered = filtered[filtered["indexing_status"].isin(selected_status)]
        if keyword_filter.strip():
            mask = (
                filtered["title"].str.contains(keyword_filter, case=False, na=False)
                | filtered["journal"].str.contains(keyword_filter, case=False, na=False)
                | filtered["authors"].str.contains(keyword_filter, case=False, na=False)
            )
            filtered = filtered[mask]

        st.dataframe(filtered[COLUMNS], use_container_width=True, height=430)

        c_left, c_right = st.columns(2)
        with c_left:
            by_year = filtered.groupby("year", dropna=False).size().reset_index(name="jumlah")
            by_year = by_year[by_year["year"].astype(str).str.len() > 0]
            if not by_year.empty:
                fig = px.bar(by_year.sort_values("year"), x="year", y="jumlah", title="Distribusi Tahun Publikasi")
                st.plotly_chart(fig, use_container_width=True)
        with c_right:
            by_status = filtered.groupby("indexing_status").size().reset_index(name="jumlah")
            if not by_status.empty:
                fig2 = px.pie(by_status, names="indexing_status", values="jumlah", title="Komposisi Status Indeks")
                st.plotly_chart(fig2, use_container_width=True)

with export_tab:
    st.subheader("Ekspor bibliografi")
    df_export = st.session_state.df.copy()
    if df_export.empty:
        st.info("Belum ada data untuk diekspor.")
    else:
        st.write(f"Siap mengekspor {len(df_export)} referensi.")
        csv = df_export.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Download CSV", data=csv, file_name="bibliografi_riset.csv", mime="text/csv")

        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            df_export.to_excel(writer, index=False, sheet_name="Bibliografi")
        st.download_button(
            "Download Excel",
            data=excel_buffer.getvalue(),
            file_name="bibliografi_riset.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        bib = dataframe_to_bibtex(df_export).encode("utf-8")
        st.download_button("Download BibTeX", data=bib, file_name="bibliografi_riset.bib", mime="text/plain")

        ris = dataframe_to_ris(df_export).encode("utf-8")
        st.download_button("Download RIS", data=ris, file_name="bibliografi_riset.ris", mime="text/plain")

with guide_tab:
    st.subheader("Panduan deploy ke Streamlit Cloud")
    st.markdown(
        """
1. Upload folder proyek ini ke repository GitHub.
2. Buka Streamlit Cloud, pilih **New app**.
3. Pilih repository dan branch.
4. Isi main file path: `app.py`.
5. Jika memakai API resmi, isi **App settings → Secrets** dengan format:

```toml
SCOPUS_API_KEY = "isi_api_key_scopus"
WOS_API_KEY = "isi_api_key_wos"
```

6. Klik **Deploy**.

Catatan penting:
- Crossref dan OpenAlex bisa berjalan tanpa API key.
- Scopus dan Web of Science membutuhkan API resmi/akses institusi.
- Label Scopus/WoS/High Impact pada aplikasi ini adalah **candidate/indikasi awal**, bukan pengganti validasi resmi dari Scopus Sources, Web of Science Master Journal List, atau Journal Citation Reports.
        """
    )

st.caption(f"Terakhir dijalankan: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")
