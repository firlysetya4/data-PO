import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

st.set_page_config(page_title="PO Tracker & Reminder", page_icon="📦", layout="wide")

# Database disimpan di folder yang sama dengan script. Jangan DROP tabel karena data harus tetap ada.
DB_PATH = Path(__file__).resolve().parent / "po_tracker.db"

STATUSES = ["Menunggu", "Sudah Datang", "Dibatalkan"]


def connect_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_num TEXT NOT NULL,
                doc_group TEXT DEFAULT '',
                bp TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Menunggu',
                date TEXT NOT NULL,
                ref_num TEXT DEFAULT '',
                currency TEXT DEFAULT '',
                doc_total TEXT DEFAULT '',
                user TEXT DEFAULT '',
                created_date TEXT DEFAULT '',
                control TEXT DEFAULT '',
                eta_start TEXT DEFAULT '',
                eta_end TEXT DEFAULT '',
                reminder_date TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            )
        """)
        # Migrasi ringan untuk database dari versi script sebelumnya.
        existing_columns = {row[1].lower() for row in conn.execute("PRAGMA table_info(purchase_orders)").fetchall()}
        if "currency" not in existing_columns:
            conn.execute("ALTER TABLE purchase_orders ADD COLUMN currency TEXT DEFAULT ''")
        conn.commit()


def fetch_orders():
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM purchase_orders ORDER BY date DESC, id DESC").fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def add_order(values):
    with connect_db() as conn:
        conn.execute("""
            INSERT INTO purchase_orders
            (doc_num, doc_group, bp, status, date, ref_num, currency, doc_total,
             user, created_date, control, eta_start, eta_end, reminder_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, values)
        conn.commit()


def update_status(order_id, status):
    with connect_db() as conn:
        conn.execute("UPDATE purchase_orders SET status=? WHERE id=?", (status, int(order_id)))
        conn.commit()


def delete_order(order_id):
    with connect_db() as conn:
        conn.execute("DELETE FROM purchase_orders WHERE id=?", (int(order_id),))
        conn.commit()


def date_from_text(value):
    try:
        if pd.isna(value) or not str(value).strip():
            return None
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def get_alert(row, today):
    status = str(row.get("status", row.get("Status", ""))).strip()
    if status == "Dibatalkan":
        return "Dibatalkan"
    if status == "Sudah Datang":
        return "Barang sudah datang"

    start = date_from_text(row.get("eta_start", row.get("ETA Start")))
    end = date_from_text(row.get("eta_end", row.get("ETA End")))
    reminder = date_from_text(row.get("reminder_date", row.get("Reminder Date")))

    if start is None or end is None or reminder is None:
        return "Data tanggal tidak valid"
    if today > end:
        return "Terlambat — follow up segera"
    if start <= today <= end:
        return "Perkiraan datang — cek supplier"
    if today >= reminder:
        return "Reminder supplier"
    return "Dalam proses"


def clean_cell(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def estimate_dates(po_date, priority):
    if str(priority).strip().lower() in ("urgent", "urgent/urgent", "urgent (10-14 hari)"):
        return po_date + timedelta(days=10), po_date + timedelta(days=14), po_date + timedelta(days=8)
    return po_date + timedelta(days=14), po_date + timedelta(days=21), po_date + timedelta(days=12)


def import_excel(uploaded_file):
    # Import Excel SAP/PO dengan header umum yang dipakai pada file PO.
    df_excel = pd.read_excel(uploaded_file)
    df_excel.columns = [str(c).strip() for c in df_excel.columns]

    # Nama kolom Excel -> nama internal. Terima beberapa variasi penamaan.
    aliases = {
        "doc_num": ["Doc_Num", "Doc Num", "Doc. Num", "DocNum", "Nomor PO", "No. PO"],
        "doc_group": ["Doc_Group", "Doc. Group", "Doc Group"],
        "bp": ["BP", "Supplier", "Vendor", "Nama Supplier"],
        "status": ["Status"],
        "date": ["Date", "Tanggal PO", "TGL"],
        "ref_num": ["Ref_Num", "Ref. Num", "Ref Num"],
        "currency": ["Currency", "Mata Uang"],
        "doc_total": ["Doc_Total", "Doc. Total", "Doc Total", "Total"],
        "user": ["User"],
        "created_date": ["Created_Date", "Created Date"],
        "control": ["Control"],
        "notes": ["Notes", "Catatan"]
    }
    normalized = {str(c).strip().lower(): c for c in df_excel.columns}
    chosen = {}
    for target, names in aliases.items():
        for name in names:
            if name.lower() in normalized:
                chosen[target] = normalized[name.lower()]
                break

    missing = [c for c in ["doc_num", "bp", "date"] if c not in chosen]
    if missing:
        raise ValueError(
            "Kolom wajib tidak ditemukan: " + ", ".join(missing) +
            ". Pastikan Excel memiliki kolom Nomor PO/Doc_Num, BP/Supplier, dan Date/Tanggal PO."
        )

    success = 0
    errors = []
    for idx, row in df_excel.iterrows():
        try:
            po_number = clean_cell(row[chosen["doc_num"]])
            supplier = clean_cell(row[chosen["bp"]])
            if not po_number:
                raise ValueError("Nomor PO kosong")
            if not supplier:
                raise ValueError("Supplier kosong")

            date_value = row[chosen["date"]]
            if pd.isna(date_value):
                raise ValueError("Tanggal PO kosong")
            po_date = pd.to_datetime(date_value, errors="raise").date()

            status_raw = clean_cell(row[chosen["status"]]) if "status" in chosen else "Menunggu"
            # Status Excel seperti Urgent/Normal dipakai untuk hitung ETA, bukan status barang.
            priority = status_raw if status_raw.lower() in ["urgent", "normal"] else "Normal"
            status = status_raw if status_raw in STATUSES else "Menunggu"
            eta_start, eta_end, reminder = estimate_dates(po_date, priority)

            created_value = row[chosen["created_date"]] if "created_date" in chosen else ""
            if pd.isna(created_value) or not str(created_value).strip():
                created_iso = datetime.now().isoformat(timespec="seconds")
            else:
                created_iso = pd.to_datetime(created_value, errors="coerce")
                created_iso = datetime.now().isoformat(timespec="seconds") if pd.isna(created_iso) else created_iso.isoformat(timespec="seconds")

            def val(key):
                return clean_cell(row[chosen[key]]) if key in chosen else ""

            add_order((
                po_number, val("doc_group"), supplier, status, po_date.isoformat(),
                val("ref_num"), val("currency"), val("doc_total"), val("user"),
                created_iso, val("control"), eta_start.isoformat(), eta_end.isoformat(),
                reminder.isoformat(), val("notes")
            ))
            success += 1
        except Exception as exc:
            errors.append(f"Baris Excel {idx + 2}: {exc}")
    return success, errors


init_db()
today = date.today()
st.title("📦 PO Tracker & Supplier Reminder")
st.caption("Catat PO, estimasi kedatangan, reminder supplier, dan status barang.")

df = fetch_orders()

if not df.empty:
    active = df[df["status"] == "Menunggu"].copy()
    alerts = active.apply(lambda r: get_alert(r, today), axis=1)
    late_count = int((alerts == "Terlambat — follow up segera").sum())
    reminder_count = int((alerts == "Reminder supplier").sum())
    arrival_count = int((alerts == "Perkiraan datang — cek supplier").sum())
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
            doc_group = st.text_input("Doc. Group")
            supplier = st.text_input("Nama supplier *")
            currency = st.text_input("Currency", value="IDR")
            doc_total = st.text_input("Doc. Total")
            ref_num = st.text_input("Ref. Num")
        with col2:
            po_date = st.date_input("Tanggal PO *", value=today)
            urgency = st.radio("Prioritas", ["Urgent", "Normal"], horizontal=True)
            user = st.text_input("User")
            control = st.text_input("Control")
            notes = st.text_area("Catatan")

        eta_start, eta_end, reminder_date = estimate_dates(po_date, urgency)
        st.caption(f"Estimasi datang: {eta_start:%d-%m-%Y} s.d. {eta_end:%d-%m-%Y} | Reminder supplier: {reminder_date:%d-%m-%Y}")
        submitted = st.form_submit_button("Simpan PO")
        if submitted:
            if not po_number.strip() or not supplier.strip():
                st.error("Nomor PO dan supplier wajib diisi.")
            else:
                add_order((
                    po_number.strip(), doc_group.strip(), supplier.strip(), "Menunggu",
                    po_date.isoformat(), ref_num.strip(), currency.strip(), doc_total.strip(),
                    user.strip(), datetime.now().isoformat(timespec="seconds"), control.strip(),
                    eta_start.isoformat(), eta_end.isoformat(), reminder_date.isoformat(), notes.strip()
                ))
                st.success("PO berhasil disimpan.")
                st.rerun()

    st.divider()
    st.subheader("📁 Upload data PO dari Excel (.xls / .xlsx)")
    uploaded_file = st.file_uploader("Pilih file Excel", type=["xls", "xlsx"], key="po_excel_upload")
    if uploaded_file is not None:
        if st.button("Import PO dari Excel", key="import_po_button"):
            try:
                count, errors = import_excel(uploaded_file)
                if count:
                    st.success(f"Berhasil mengimpor {count} PO.")
                if errors:
                    st.warning("Ada baris yang tidak berhasil diimpor:")
                    for error in errors[:50]:
                        st.write("- " + error)
                    if len(errors) > 50:
                        st.caption(f"Dan {len(errors) - 50} error lainnya.")
                st.rerun()
            except Exception as exc:
                st.error(f"Gagal membaca/import Excel: {exc}")

with tab_monitor:
    st.subheader("Daftar PO dan Reminder")
    if df.empty:
        st.info("Belum ada data PO.")
    else:
        display = df.copy()
        display["alert"] = display.apply(lambda r: get_alert(r, today), axis=1)
        display = display.rename(columns={
            "doc_num": "Nomor PO", "doc_group": "Doc. Group", "bp": "Supplier",
            "status": "Status", "date": "Tanggal PO", "eta_start": "ETA Mulai",
            "eta_end": "ETA Akhir", "reminder_date": "Tanggal Reminder", "alert": "Reminder"
        })
        st.dataframe(display[["id", "Nomor PO", "Supplier", "Tanggal PO", "Status", "ETA Mulai", "ETA Akhir", "Tanggal Reminder", "Reminder"]], use_container_width=True)

with tab_manage:
    st.subheader("Kelola PO")
    if df.empty:
        st.info("Belum ada data PO untuk dikelola.")
    else:
        options = df["id"].tolist()
        selected_id = st.selectbox("Pilih PO berdasarkan ID", options, format_func=lambda x: f"ID {x} — {df.loc[df['id'] == x, 'doc_num'].iloc[0]}")
        order = df[df["id"] == selected_id].iloc[0]
        st.write(f"**Nomor PO:** {order['doc_num']}")
        st.write(f"**Doc. Group:** {order['doc_group']}")
        st.write(f"**Supplier:** {order['bp']}")
        st.write(f"**Status:** {order['status']}")
        st.write(f"**Tanggal PO:** {order['date']}")
        st.write(f"**Ref. Num:** {order['ref_num']}")
        st.write(f"**Currency:** {order['currency']}")
        st.write(f"**Doc. Total:** {order['doc_total']}")
        st.write(f"**User:** {order['user']}")
        st.write(f"**Created Date:** {order['created_date']}")
        st.write(f"**Control:** {order['control']}")
        st.write(f"**Catatan:** {order['notes']}")

        current_status = order["status"] if order["status"] in STATUSES else "Menunggu"
        new_status = st.selectbox("Update status PO", STATUSES, index=STATUSES.index(current_status))
        if st.button("Simpan perubahan status", key="update_status_button"):
            update_status(selected_id, new_status)
            st.success("Status berhasil diperbarui.")
            st.rerun()
        if st.button("Hapus PO ini", type="secondary", key="delete_po_button"):
            delete_order(selected_id)
            st.success("PO berhasil dihapus.")
            st.rerun()
