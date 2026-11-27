import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

# Set page config
st.set_page_config(page_title="PO Tracker & Reminder", page_icon="📦", layout="wide")

DB_PATH = Path(__file__).resolve().parent / "po_tracker.db"

def connect_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                "Doc. Num" TEXT NOT NULL,
                "Doc. Group" TEXT,
                "BP" TEXT,
                "Status" TEXT NOT NULL,
                "Date" TEXT NOT NULL,
                "Ref. Num" TEXT,
                "Currency" TEXT,
                "Doc. Total" TEXT,
                "User" TEXT,
                "Created Date" TEXT NOT NULL,
                "Control" TEXT
            )
        """)
        conn.commit()

def fetch_orders():
    with connect_db() as conn:
        rows = conn.execute('SELECT * FROM purchase_orders ORDER BY "Date" DESC, id DESC').fetchall()
    return pd.DataFrame([dict(r) for r in rows])

def add_order(values):
    with connect_db() as conn:
        conn.execute("""
            INSERT INTO purchase_orders
            ("Doc. Num", "Doc. Group", "BP", "Status", "Date", "Ref. Num", "Currency",
             "Doc. Total", "User", "Created Date", "Control")
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, values)
        conn.commit()

def update_status(order_id, status):
    with connect_db() as conn:
        conn.execute("""
            UPDATE purchase_orders SET "Status"=? WHERE id=?
        """, (status, int(order_id)))
        conn.commit()

def delete_order(order_id):
    with connect_db() as conn:
        conn.execute('DELETE FROM purchase_orders WHERE id=?', (int(order_id),))
        conn.commit()

# Inisialisasi database
init_db()

st.title("📦 PO Tracker & Reminder")

df = fetch_orders()

# Contoh input form sederhana — sesuaikan dengan field kolom
with st.form("input_po", clear_on_submit=True):
    doc_num = st.text_input("Nomor PO *")
    doc_group = st.text_input("Doc. Group")
    bp = st.text_input("Supplier (BP) *")
    doc_date = st.date_input("Tanggal PO *", date.today())
    ref_num = st.text_input("Ref. Num")
    currency = st.text_input("Currency", "IDR")
    doc_total = st.text_input("Total")
    user = st.text_input("User")
    control = st.text_input("Control")
    status = "Menunggu"  # default status
    submitted = st.form_submit_button("Simpan PO")

    if submitted:
        if not doc_num.strip() or not bp.strip():
            st.error("Nomor PO dan Supplier wajib diisi.")
        else:
            created_date = datetime.now().isoformat(timespec="seconds")
            add_order((
                doc_num.strip(),
                doc_group.strip(),
                bp.strip(),
                status,
                doc_date.isoformat(),
                ref_num.strip(),
                currency.strip(),
                doc_total.strip(),
                user.strip(),
                created_date,
                control.strip()
            ))
            st.success("PO berhasil disimpan.")
            st.experimental_rerun()

if not df.empty:
    st.subheader("Daftar PO Terakhir")
    st.dataframe(df)

    st.subheader("Kelola PO")
    selected_id = st.selectbox("Pilih PO berdasarkan ID", df["id"])

    if selected_id:
        order = df[df["id"] == selected_id].iloc[0]
        st.write(f"**Nomor PO:** {order['Doc. Num']}")
        st.write(f"**Supplier:** {order['BP']}")
        st.write(f"**Status:** {order['Status']}")

        new_status = st.selectbox("Ubah Status", ["Menunggu", "Sudah Datang", "Dibatalkan"], index=["Menunggu", "Sudah Datang", "Dibatalkan"].index(order["Status"]))
        if st.button("Update Status"):
            update_status(selected_id, new_status)
            st.success("Status PO berhasil diperbarui.")
            st.experimental_rerun()

        if st.button("Hapus PO"):
            delete_order(selected_id)
            st.success("PO berhasil dihapus.")
            st.experimental_rerun()
else:
    st.info("Belum ada data PO.")

