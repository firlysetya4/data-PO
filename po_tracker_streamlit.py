import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

# Konfigurasi halaman (harus di awal)
st.set_page_config(page_title="PO Tracker & Reminder", page_icon="📦", layout="wide")

# Database path
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
                Doc. Num TEXT NOT NULL,
                Doc. Group TEXT NOT NULL,
                BP TEXT NOT NULL,
                Status	Date REAL NOT NULL,
                Ref. Num TEXT NOT NULL,
                Currency TEXT NOT NULL,
                Doc. Total TEXT NOT NULL,
                User TEXT NOT NULL,
                Created Date TEXT NOT NULL,
                Control TEXT NOT NULL,
            )
        """)
        conn.commit()

def fetch_orders():
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM purchase_orders ORDER BY po_date DESC, id DESC").fetchall()
    return pd.DataFrame([dict(r) for r in rows])

def add_order(values):
    with connect_db() as conn:
        conn.execute("""
            INSERT INTO purchase_orders
            (Doc. Num, Doc. Group, BP, Status, Date, Ref. Num, Currency, Doc. Total, User, Created Date, Controlt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Menunggu', NULL, ?, ?)
        """, (*values, datetime.now().isoformat(timespec="seconds")))
        conn.commit()

def update_status(order_id, status, arrived_date=None):
    with connect_db() as conn:
        conn.execute(
            "UPDATE purchase_orders SET status=?, arrived_date=? WHERE id=?",
            (status, arrived_date.isoformat() if arrived_date else None, int(order_id))
        )
        conn.commit()

def delete_order(order_id):
    with connect_db() as conn:
        conn.execute("DELETE FROM purchase_orders WHERE id=?", (int(order_id),))
        conn.commit()

def date_from_text(value):
    return date.fromisoformat(str(value)[:10])

def get_alert(row, today):
    if row["status"] == "Dibatalkan":
        return "Dibatalkan"
    if row["status"] == "Sudah Datang":
        return "Barang sudah datang"
    start = date_from_text(row["eta_start"])
    end = date_from_text(row["eta_end"])
    reminder = date_from_text(row["reminder_date"])

    if today > end:
        return "Terlambat — follow up segera"
    if start <= today <= end:
        return "Perkiraan datang — cek supplier"
    if today >= reminder:
        return "Reminder supplier"
    return "Dalam proses"

init_db()
today = date.today()

st.title("📦 PO Tracker & Supplier Reminder")
st.caption("Catat PO, estimasi kedatangan, reminder supplier, dan status barang.")

df = fetch_orders()

# Dashboard ringkas
if not df.empty:
    active = df[df["status"] == "Menunggu"].copy()
    late_count = sum(get_alert(row, today) == "Terlambat — follow up segera" for _, row in active.iterrows())
    reminder_count = sum(get_alert(row, today) == "Reminder supplier" for _, row in active.iterrows())
    arrival_count = sum(get_alert(row, today) == "Perkiraan datang — cek supplier" for _, row in active.iterrows())
else:
    active = pd.DataFrame()
    late_count = reminder_count = arrival_count = 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("PO aktif", len(active))
c2.metric("Perlu reminder", reminder_count)
c3.metric("Dalam rentang kedatangan", arrival_count)
c4.metric("Terlambat", late_count)

tab_add, tab_monitor, tab_manage = st.tabs(["➕ Input PO", "🔔 Monitoring & Reminder", "🗂️ Kelola PO"])

with tab_add:
    st.subheader("Input Purchase Order")
    
    # Form manual input PO
    with st.form("po_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            po_number = st.text_input("Nomor PO *", placeholder="Contoh: PO-2026-001")
            supplier = st.text_input("Nama supplier *")
            item_name = st.text_input("Nama barang / material *")
            quantity = st.number_input("Qty *", min_value=0.01, value=1.0, step=1.0)
            unit = st.text_input("Satuan", value="Kg")
        with col2:
            po_date = st.date_input("Tanggal PO *", value=today)
            urgency = st.radio("Prioritas", ["Urgent", "Normal"], horizontal=True)
            notes = st.text_area("Catatan", placeholder="Spesifikasi, kontak supplier, atau catatan lain")
        if urgency == "Urgent":
            eta_start = po_date + timedelta(days=10)
            eta_end = po_date + timedelta(days=14)
            reminder_date = po_date + timedelta(days=8)
            st.info(f"Urgent: target datang {eta_start:%d-%m-%Y}; rentang estimasi {eta_start:%d-%m-%Y} s.d. {eta_end:%d-%m-%Y}. Reminder supplier mulai {reminder_date:%d-%m-%Y}.")
        else:
            eta_start = po_date + timedelta(days=14)
            eta_end = po_date + timedelta(days=21)
            reminder_date = po_date + timedelta(days=12)
            st.info(f"Normal: estimasi datang {eta_start:%d-%m-%Y} s.d. {eta_end:%d-%m-%Y}. Reminder supplier mulai {reminder_date:%d-%m-%Y}.")

        submitted = st.form_submit_button("Simpan PO", type="primary")
        if submitted:
            if not po_number.strip() or not supplier.strip() or not item_name.strip():
                st.error("Nomor PO, supplier, dan nama barang wajib diisi.")
            else:
                add_order((
                    po_number.strip(), supplier.strip(), item_name.strip(),
                    float(quantity), unit.strip() or "Unit",
                    po_date.isoformat(), urgency,
                    eta_start.isoformat(), eta_end.isoformat(),
                    reminder_date.isoformat(), notes.strip()
                ))
                st.success("PO berhasil disimpan.")
                st.experimental_rerun()

    # Upload Excel file
    st.markdown("---")
    st.subheader("📁 Upload data PO dari file Excel (.xls / .xlsx)")
    uploaded_file = st.file_uploader("Pilih file Excel", type=["xls", "xlsx"], key="po_excel_upload")
    
    if uploaded_file:
        try:
            df_excel = pd.read_excel(uploaded_file)
            # Normalisasi header kolom ke lowercase tanpa spasi di kiri kanan
            df_excel.columns = df_excel.columns.str.strip().str.lower()

            # Kolom wajib yang sesuai kolommu, lowercase
            mandatory_cols = [
                "tgl", "nama marketing", "ket", "no. po sistem", "jenis plastik", "no pr", "no. po",
                "order-kg maksimal", "supplier", "harga/ / kg", "total",
                "noted nego /tidak", "urgent atau tidak", "noted", "rename"
            ]
            missing_cols = [col for col in mandatory_cols if col not in df_excel.columns]
            if missing_cols:
                st.error(f"File Excel harus mengandung kolom: {', '.join(mandatory_cols)}. Kolom hilang: {', '.join(missing_cols)}")
            else:
                success_count = 0
                error_rows = []

                for i, row in df_excel.iterrows():
                    try:
                        po_date_val = row["tgl"]

                        # Parsing tanggal
                        if pd.isna(po_date_val):
                            po_date = None
                        elif isinstance(po_date_val, pd.Timestamp):
                            po_date = po_date_val.date()
                        elif isinstance(po_date_val, datetime):
                            po_date = po_date_val.date()
                        elif isinstance(po_date_val, date):
                            po_date = po_date_val
                        else:
                            po_date_parsed = pd.to_datetime(po_date_val, errors="coerce", dayfirst=True)
                            po_date = po_date_parsed.date() if not pd.isna(po_date_parsed) else None

                        # Mapping kolom Excel ke variable
                        po_number = str(row.get("no. po", "") or "").strip()
                        supplier = str(row.get("supplier", "") or "").strip()
                        item_name = str(row.get("jenis plastik", "") or "").strip()
                        quantity = pd.to_numeric(row.get("order-kg maksimal", 0), errors="coerce")
                        quantity = float(quantity) if not pd.isna(quantity) and quantity > 0 else 0
                        unit = "Kg"

                        urgency_raw = str(row.get("urgent atau tidak", "") or "").strip().lower()
                        urgency = "Urgent" if "urgent" in urgency_raw else "Normal"
                        notes = str(row.get("noted", "") or "").strip()

                        # Validasi data penting
                        if not po_number:
                            raise ValueError("Nomor PO kosong")
                        if not supplier:
                            raise ValueError("Supplier kosong")
                        if quantity <= 0:
                            raise ValueError("Quantity harus > 0")
                        if not po_date:
                            raise ValueError("Tanggal PO tidak valid")

                        # Hitung tanggal ETA dan reminder sesuai urgensi
                        if urgency == "Urgent":
                            eta_start = po_date + timedelta(days=10)
                            eta_end = po_date + timedelta(days=14)
                            reminder_date = po_date + timedelta(days=8)
                        else:
                            eta_start = po_date + timedelta(days=14)
                            eta_end = po_date + timedelta(days=21)
                            reminder_date = po_date + timedelta(days=12)

                        add_order((
                            po_number, supplier, item_name, quantity, unit,
                            po_date.isoformat(), urgency,
                            eta_start.isoformat(), eta_end.isoformat(), reminder_date.isoformat(),
                            notes
                        ))
                        success_count += 1
                    except Exception as e:
                        error_rows.append((i + 2, str(e)))  # nomor baris Excel + header

                if success_count:
                    st.success(f"Berhasil menambahkan {success_count} PO dari file Excel.")
                if error_rows:
                    st.error("Beberapa baris gagal diproses:")
                    for err in error_rows:
                        st.write(f"- Baris {err[0]}: {err[1]}")

                st.experimental_rerun()

        except Exception as err:
            st.error(f"Gagal membaca file Excel: {err}")

# Selanjutnya dengan tab_monitor dan tab_manage seperti kode asli kamu...
