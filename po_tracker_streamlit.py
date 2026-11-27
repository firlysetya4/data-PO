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
        # Hapus tabel lama dulu (jika ada)
        conn.execute("DROP TABLE IF EXISTS purchase_orders")
        # Buat tabel baru dengan skema terbaru
        conn.execute("""
            CREATE TABLE purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_num TEXT NOT NULL,
                doc_group TEXT,
                bp TEXT,
                status TEXT NOT NULL,
                date TEXT NOT NULL,
                ref_num TEXT,
                doc_total TEXT,
                user TEXT,
                reated_date TEXT,
                control TEXT,
                eta_start TEXT,
                eta_end TEXT,
                reminder_date TEXT,
                notes TEXT
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
            ("Doc_Num", "Doc_Group", "BP", "Status", "Date", "Ref_Num",
            "Doc_Total", "User", "Created Date", "Control",
             "eta_start", "eta_end", "reminder_date", "notes")
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, values)
        conn.commit()

def update_status(order_id, status):
    with connect_db() as conn:
        conn.execute(
            'UPDATE purchase_orders SET "Status"=? WHERE id=?',
            (status, int(order_id))
        )
        conn.commit()

def delete_order(order_id):
    with connect_db() as conn:
        conn.execute('DELETE FROM purchase_orders WHERE id=?', (int(order_id),))
        conn.commit()

def date_from_text(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None

def get_alert(row, today):
    if row["Status"] == "Dibatalkan":
        return "Dibatalkan"
    if row["Status"] == "Sudah Datang":
        return "Barang sudah datang"
    start = date_from_text(row.get("eta_start"))
    end = date_from_text(row.get("eta_end"))
    reminder = date_from_text(row.get("reminder_date"))

    if start is None or end is None or reminder is None:
        return "Data tanggal tidak valid"

    if today > end:
        return "Terlambat — follow up segera"
    if start <= today <= end:
        return "Perkiraan datang — cek supplier"
    if today >= reminder:
        return "Reminder supplier"
    return "Dalam proses"

# Initialize DB
init_db()
today = date.today()

st.title("📦 PO Tracker & Supplier Reminder")
st.caption("Catat PO, estimasi kedatangan, reminder supplier, dan status barang.")

df = fetch_orders()

# Dashboard ringkas
if not df.empty:
    active = df[df["Status"] == "Menunggu"].copy()
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
    
    with st.form("po_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            po_number = st.text_input("Nomor PO *", placeholder="Contoh: PO-2026-001")
            doc_group = st.text_input("Doc_Group")
            supplier = st.text_input("Nama supplier *")
            quantity = st.number_input("Qty *", min_value=0.01, value=1.0, step=1.0)
            unit = st.text_input("Satuan", value="Kg")
        with col2:
            po_date = st.date_input("Tanggal PO *", value=today)
            urgency = st.radio("Prioritas", ["Urgent", "Normal"], horizontal=True)
            notes = st.text_area("Catatan")
            ref_num = st.text_input("Ref_Num")
            doc_total = st.text_input("Doc_Total")
            user = st.text_input("User")
            control = st.text_input("Control")

        if urgency == "Urgent":
            eta_start = po_date + timedelta(days=10)
            eta_end = po_date + timedelta(days=14)
            reminder_date = po_date + timedelta(days=8)
        else:
            eta_start = po_date + timedelta(days=14)
            eta_end = po_date + timedelta(days=21)
            reminder_date = po_date + timedelta(days=12)

        submitted = st.form_submit_button("Simpan PO")
        if submitted:
            if not po_number.strip() or not supplier.strip():
                st.error("Nomor PO dan supplier wajib diisi.")
            else:
                add_order((
                    po_number.strip(), 
                    doc_group.strip(),
                    supplier.strip(),
                    "Menunggu",
                    po_date.isoformat(),
                    ref_num.strip(),
                    doc_total.strip(),
                    user.strip(),
                    datetime.now().isoformat(timespec="seconds"),
                    control.strip(),
                    eta_start.isoformat(),
                    eta_end.isoformat(),
                    reminder_date.isoformat(),
                    notes.strip()
                ))
                st.success("PO berhasil disimpan.")
                st.rerun()

    st.markdown("---")
    st.subheader("📁 Upload data PO dari file Excel (.xls / .xlsx)")
    uploaded_file = st.file_uploader("Pilih file Excel", type=["xls", "xlsx"])

    if uploaded_file:
        try:
            df_excel = pd.read_excel(uploaded_file)
            # Normalisasi kolom
            df_excel.columns = df_excel.columns.str.strip()

            mandatory_cols = ["Doc_Num", "Doc_Group", "BP", "Status", "Date", "Ref_Num",
                              "Doc_Total", "User", "Created Date", "Control"]


            missing_cols = [col for col in mandatory_cols if col not in df_excel.columns]
            if missing_cols:
                st.error(f"File Excel harus mengandung kolom: {', '.join(mandatory_cols)}. Kolom hilang: {', '.join(missing_cols)}")
            else:
                success_count = 0
                error_rows = []

                for i, row in df_excel.iterrows():
                    try:
                        po_number = str(row["Doc_Num"]).strip()
                        doc_group = str(row["Doc_Group"]).strip()
                        supplier = str(row["BP"]).strip()
                        status = str(row["Status"]).strip()
                        ref_num = str(row["Ref_Num"]).strip()
                        doc_total = str(row["Doc_Total"]).strip()
                        user = str(row["User"]).strip()
                        control = str(row["Control"]).strip()
                        notes = ""  # Kalau kolom notes tidak ada, beri kosong
                        
                        # Parsing tanggal Date
                        date_val = row["Date"]
                        if pd.isna(date_val):
                            raise ValueError("Tanggal PO kosong/tidak valid")
                        elif isinstance(date_val, (datetime, pd.Timestamp)):
                            po_date = date_val.date()
                        else:
                            po_date_parsed = pd.to_datetime(date_val, errors="coerce", dayfirst=True)
                            if pd.isna(po_date_parsed):
                                raise ValueError("Tanggal PO tidak valid")
                            po_date = po_date_parsed.date()
                        
                        # Parsing Created Date (optional)
                        created_date_val = row["Created Date"]
                        if pd.isna(created_date_val):
                            created_date_iso = datetime.now().isoformat()
                        else:
                            created_date_iso = pd.to_datetime(created_date_val).isoformat()
                        
                        # Hitung ETA dll berdasarkan status (atau urgency jika mau)
                        if status.lower() == "urgent":
                            eta_start = po_date + timedelta(days=10)
                            eta_end = po_date + timedelta(days=14)
                            reminder_date = po_date + timedelta(days=8)
                        else:
                            eta_start = po_date + timedelta(days=14)
                            eta_end = po_date + timedelta(days=21)
                            reminder_date = po_date + timedelta(days=12)
                        
                        add_order((
                            po_number, doc_group, supplier, status, po_date.isoformat(),
                            ref_num, doc_total, user, created_date_iso,
                            control, eta_start.isoformat(), eta_end.isoformat(), reminder_date.isoformat(), notes
                        ))

                        success_count += 1

                    except Exception as e:
                        error_rows.append((i + 2, str(e)))

                if success_count:
                    st.success(f"Berhasil menambahkan {success_count} PO dari file Excel.")
                if error_rows:
                    st.error("Beberapa baris gagal diproses:")
                    for err in error_rows:
                        st.write(f"- Baris {err[0]}: {err[1]}")

                st.rerun()

        except Exception as err:
            st.error(f"Gagal membaca file Excel: {err}")

with tab_monitor:
    st.subheader("Daftar PO dan Reminder")
    if df.empty:
        st.info("Belum ada data PO.")
    else:
        df_display = df.copy()
        df_display["alert"] = df_display.apply(lambda r: get_alert(r, today), axis=1)
        st.dataframe(df_display[['Doc_Num', 'BP', 'Date', 'Status', 'alert']].sort_values(by=['Date', 'Doc_Num'], ascending=False))

with tab_manage:
    st.subheader("Kelola PO")
    
    if df.empty:
        st.info("Belum ada data PO untuk dikelola.")
    else:
        selected_id = st.selectbox("Pilih PO berdasarkan ID", df["id"].tolist())
        if selected_id is not None:
            order = df[df["id"] == selected_id].iloc[0]

            # contoh di tab_manage
            st.write(f"** Num:** {order['Doc_Num']}")
            st.write(f"**Doc. Group:** {order['Doc_Group']}")
            st.write(f"**BP (Supplier):** {order['BP']}")
            st.write(f"**Status:** {order['Status']}")
            st.write(f"**Date (Tanggal PO):** {order['Date']}")
            st.write(f"**Ref. Num:** {order['Ref_Num']}")
            st.write(f"**Doc. Total:** {order['Doc_Total']}")
            st.write(f"**User:** {order['User']}")
            st.write(f"**Created Date:** {order['Created Date']}")
            st.write(f"**Control:** {order['Control']}")
            st.write(f"**Notes:** {order['notes']}")


            new_status = st.selectbox("Update status PO", ["Menunggu", "Sudah Datang", "Dibatalkan"],
                                      index=["Menunggu", "Sudah Datang", "Dibatalkan"].index(order["Status"]))

            if st.button("Simpan perubahan status"):
                update_status(selected_id, new_status)
                st.success("Status berhasil diperbarui.")
                st.rerun()

            if st.button("Hapus PO ini"):
                delete_order(selected_id)
                st.success("PO berhasil dihapus.")
                st.rerun()
