import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

st.title("Sistem Tracking Kedatangan Barang PO")

uploaded_file = st.file_uploader("Upload file Excel PO", type=["xlsx", "xls"])

if uploaded_file:
    # Load data excel
    df = pd.read_excel(uploaded_file)

    # Pastikan kolom penting ada
    required_columns = ['Nomor PO', 'Tanggal PO', 'Status']
    if not all(col in df.columns for col in required_columns):
        st.error(f"File harus mengandung kolom: {', '.join(required_columns)}")
    else:
        # Konversi kolom tanggal jadi datetime
        df['Tanggal PO'] = pd.to_datetime(df['Tanggal PO'], errors='coerce')

        if df['Tanggal PO'].isnull().any():
            st.warning("Ada baris dengan tanggal PO tidak valid.")

        # Hitung tanggal kedatangan sesuai status
        def hitung_tanggal_kedatangan(row):
            if row['Status'].str.lower() == 'urgent':
                return row['Tanggal PO'] + timedelta(days=10)
            else:
                return row['Tanggal PO'] + timedelta(days=14)  # Bisa kamu ubah sesuai preferensi

        df['Tanggal Kedatangan'] = df.apply(lambda row: row['Tanggal PO'] + timedelta(days=10) if str(row['Status']).lower()=='urgent' else row['Tanggal PO'] + timedelta(days=14), axis=1)

        # Tentukan status reminder
        hari_ini = datetime.now().date()
        df['Tanggal Kedatangan Date'] = df['Tanggal Kedatangan'].dt.date

        def status_reminder(row):
            if 'Sudah Diterima' in row and row['Sudah Diterima']:
                return "Sudah Diterima"
            if row['Tanggal Kedatangan Date'] < hari_ini:
                return "Sudah Lewat, Follow-up Supplier"
            elif (row['Tanggal Kedatangan Date'] - hari_ini).days <= 2:
                return "Perlu Reminder"
            else:
                return "Normal"

        # Tambahkan kolom untuk user centang barang sudah datang
        if 'Sudah Diterima' not in df.columns:
            df['Sudah Diterima'] = False

        # Buat checkbox di tabel per baris untuk update status sudah diterima
        st.write("Centang jika barang sudah diterima:")

        for i, row in df.iterrows():
            checked = st.checkbox(f"PO: {row['Nomor PO']} - Barang sudah diterima?", key=i, value=row['Sudah Diterima'])
            df.at[i, 'Sudah Diterima'] = checked

        df['Status Reminder'] = df.apply(status_reminder, axis=1)

        # Tampilkan tabel hasil
        st.dataframe(df[['Nomor PO', 'Tanggal PO', 'Status', 'Tanggal Kedatangan', 'Status Reminder', 'Sudah Diterima']])
