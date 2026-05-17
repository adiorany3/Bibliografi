import io
import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.bibliography import (
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
    page_title="Bibliografi Riset Scopus/WoS/High Impact",
    page_icon="📚",
    layout="wide",
)

st.title("📚 Sistem Bibliografi Riset Scopus, WoS & Jurnal High Impact")
st.caption(
    "Aplikasi Streamlit Cloud untuk mengumpulkan, membersihkan, memverifikasi awal, "
    "memfilter, dan mengekspor data bibliografi riset."
)

with st.sidebar:
    st.header("Pengaturan")
    email = st.text_input("Email untuk polite API request", value="")
    max_rows = st.slider("Jumlah hasil per sumber", 5, 100, 25, step=5)
    st.divider()
    st.subheader("API Opsional")
    scopus_key = st.text_input("Scopus API Key", type="password", value=st.secrets.get("SCOPUS_API_KEY", "") if hasattr(st, "secrets") else "")
    wos_key = st.text_input("WoS Starter API Key", type="password", value=st.secrets.get("WOS_API_KEY", "") if hasattr(st, "secrets") else "")
    st.info("Scopus dan WoS membutuhkan akses institusi/API resmi. Tanpa key, gunakan Crossref/OpenAlex atau upload file ekspor.")

if "df" not in st.session_state:
    st.session_state.df = standardize_records([])

search_tab, upload_tab, manual_tab, export_tab, guide_tab = st.tabs([
    "🔎 Cari Literatur", "⬆️ Upload Ekspor", "✍️ Input Manual", "📤 Ekspor", "🚀 Deploy Guide"
])

with search_tab:
    st.subheader("Cari data bibliografi")
    query = st.text_input("Topik / keyword riset", placeholder="Contoh: artificial intelligence education bibliometric")
    sources = st.multiselect(
        "Sumber data",
        ["Crossref", "OpenAlex", "Scopus API", "Web of Science API"],
        default=["Crossref", "OpenAlex"],
    )
    col_a, col_b = st.columns([1, 3])
    with col_a:
        run_search = st.button("Cari & Gabungkan", type="primary", use_container_width=True)
    with col_b:
        st.write("Hasil dari tiap sumber akan digabung, dibersihkan, dan dideduplikasi berdasarkan DOI + judul.")

    if run_search:
        if not query.strip():
            st.warning("Masukkan keyword riset terlebih dahulu.")
        else:
            frames = []
            errors = []
            with st.spinner("Mengambil metadata bibliografi..."):
                if "Crossref" in sources:
                    try:
                        frames.append(search_crossref(query, max_rows, email))
                    except Exception as exc:
                        errors.append(f"Crossref: {exc}")
                if "OpenAlex" in sources:
                    try:
                        frames.append(search_openalex(query, max_rows, email))
                    except Exception as exc:
                        errors.append(f"OpenAlex: {exc}")
                if "Scopus API" in sources:
                    try:
                        frames.append(search_scopus(query, scopus_key, max_rows))
                    except Exception as exc:
                        errors.append(f"Scopus: {exc}")
                if "Web of Science API" in sources:
                    try:
                        frames.append(search_wos(query, wos_key, max_rows))
                    except Exception as exc:
                        errors.append(f"WoS: {exc}")

            if frames:
                combined = pd.concat([st.session_state.df] + frames, ignore_index=True)
                st.session_state.df = standardize_records(combined.to_dict("records"))
                st.success(f"Berhasil menggabungkan {len(st.session_state.df)} record unik.")
            if errors:
                st.error("Beberapa sumber gagal diakses:\n" + "\n".join(f"- {e}" for e in errors))

with upload_tab:
    st.subheader("Upload data dari Scopus / WoS / jurnal")
    st.write("Format yang didukung: CSV, XLSX, BibTeX (.bib), dan RIS (.ris).")
    uploaded = st.file_uploader("Pilih file ekspor bibliografi", type=["csv", "xlsx", "xls", "bib", "ris"])
    if uploaded and st.button("Proses File", type="primary"):
        try:
            upload_df = parse_uploaded_file(uploaded)
            combined = pd.concat([st.session_state.df, upload_df], ignore_index=True)
            st.session_state.df = standardize_records(combined.to_dict("records"))
            st.success(f"File diproses. Total record unik sekarang: {len(st.session_state.df)}")
        except Exception as exc:
            st.error(f"Gagal memproses file: {exc}")

with manual_tab:
    st.subheader("Tambah referensi manual")
    with st.form("manual_form"):
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
            database = st.selectbox("Database", ["Scopus", "Web of Science", "SINTA", "Google Scholar", "Manual", "Lainnya"])
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
        st.session_state.df = standardize_records(pd.concat([st.session_state.df, new_df], ignore_index=True).to_dict("records"))
        st.success("Referensi manual berhasil ditambahkan.")

# Main dashboard
st.divider()
df = st.session_state.df.copy()

st.subheader("Dashboard Bibliografi")
if df.empty:
    st.info("Belum ada data. Gunakan pencarian, upload file ekspor, atau input manual.")
else:
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Referensi", len(df))
    k2.metric("Dengan DOI", int((df["doi"].astype(str).str.len() > 0).sum()))
    k3.metric("Scopus/WoS", int(df["indexing_status"].str.contains("Scopus|Web of Science", case=False, na=False).sum()))
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

    left, right = st.columns([2, 1])
    with left:
        st.dataframe(filtered, use_container_width=True, height=420)
    with right:
        by_year = filtered.groupby("year", dropna=False).size().reset_index(name="jumlah")
        by_year = by_year[by_year["year"].astype(str).str.len() > 0]
        if not by_year.empty:
            fig = px.bar(by_year.sort_values("year"), x="year", y="jumlah", title="Distribusi Tahun Publikasi")
            st.plotly_chart(fig, use_container_width=True)
        by_status = filtered.groupby("indexing_status").size().reset_index(name="jumlah")
        fig2 = px.pie(by_status, names="indexing_status", values="jumlah", title="Komposisi Status Indeks")
        st.plotly_chart(fig2, use_container_width=True)

with export_tab:
    st.subheader("Ekspor bibliografi")
    df_export = st.session_state.df.copy()
    if df_export.empty:
        st.info("Belum ada data untuk diekspor.")
    else:
        st.write(f"Siap mengekspor {len(df_export)} referensi.")
        csv = df_export.to_csv(index=False).encode("utf-8")
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
1. Upload semua file proyek ini ke repository GitHub.
2. Buka Streamlit Cloud, pilih **New app**.
3. Pilih repository, branch, dan main file: `app.py`.
4. Jika memakai API resmi, tambahkan secret berikut pada menu **App settings → Secrets**:

```toml
SCOPUS_API_KEY = "isi_api_key_scopus"
WOS_API_KEY = "isi_api_key_wos"
```

5. Klik **Deploy**.

Catatan: validasi impact factor final tetap perlu dicek melalui sumber resmi seperti Journal Citation Reports, Scopus Sources, atau laman jurnal/publisher, karena sebagian data indeks membutuhkan akses berlisensi.
        """
    )

st.caption(f"Terakhir dijalankan: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")
