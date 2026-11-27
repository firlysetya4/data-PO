import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

with st.expander("📁 Upload data PO dari file Excel (.xls / .xlsx)"):
    uploaded_file = st.file_uploader("Pilih file Excel", type=["xls", "xlsx"])
    if uploaded_file:
        try:
            df_excel = pd.read_excel(uploaded_file)

            mandatory_cols = ["po_number", "supplier", "item_name", "quantity", "unit", "po_date", "urgency"]
            missing_cols = [col for col in mandatory_cols if col not in df_excel.columns.str.lower()]
            if missing_cols:
                st.error(f"File Excel harus mengandung kolom: {', '.join(mandatory_cols)}. Kolom hilang: {', '.join(missing_cols)}")
            else:
                # Lakukan normalisasi nama kolom menjadi lowercase untuk kemudahan akses
                df_excel.columns = df_excel.columns.str.lower()

                # Proses tiap baris untuk dimasukkan ke DB
                success_count = 0
                error_rows = []
                for i, row in df_excel.iterrows():
                    try:
                        # Baca dan validasi data penting
                        po_number = str(row["po_number"]).strip()
                        supplier = str(row["supplier"]).strip()
                        item_name = str(row["item_name"]).strip()
                        quantity = float(row["quantity"])
                        unit = str(row["unit"]).strip() or "Unit"
                        # Pastikan tanggal PO di-convert ke date
                        po_date_val = row["po_date"]
                        if isinstance(po_date_val, pd.Timestamp):
                            po_date = po_date_val.date()
                        elif isinstance(po_date_val, str):
                            po_date = datetime.strptime(po_date_val[:10], "%Y-%m-%d").date()
                        else:
                            po_date = date_from_text(po_date_val)

                        urgency = str(row["urgency"]).strip()
                        notes = str(row.get("notes", "") or "")

                        # Hitung ETA dan reminder sesuai urgensi
                        if urgency.lower() == "urgent":
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
                        error_rows.append((i + 2, str(e)))  # +2 untuk menyesuaikan dengan baris Excel (header+1)

                st.success(f"Berhasil menambahkan {success_count} PO dari file Excel.")
                if error_rows:
                    st.error(f"Gagal memproses baris berikut (nomor baris Excel):")
                    for err in error_rows:
                        st.write(f"- Baris {err[0]}: {err[1]}")
                st.experimental_rerun()
        except Exception as e:
            st.error(f"Gagal membaca file Excel: {e}")

st.set_page_config(page_title="PO Tracker & Reminder", page_icon="📦", layout="wide")

# Database tersimpan di folder aplikasi. Cocok untuk penggunaan lokal.
# Catatan: penyimpanan lokal Streamlit Cloud tidak dijamin permanen.
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
                po_number TEXT NOT NULL,
                supplier TEXT NOT NULL,
                item_name TEXT NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL,
                po_date TEXT NOT NULL,
                urgency TEXT NOT NULL,
                eta_start TEXT NOT NULL,
                eta_end TEXT NOT NULL,
                reminder_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Menunggu',
                arrived_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
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
            (po_number, supplier, item_name, quantity, unit, po_date, urgency,
             eta_start, eta_end, reminder_date, status, arrived_date, notes, created_at)
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
                st.rerun()

with tab_monitor:
    st.subheader("Daftar notifikasi")
    current = fetch_orders()
    if current.empty:
        st.info("Belum ada data PO. Input PO terlebih dahulu.")
    else:
        current = current[current["status"] == "Menunggu"].copy()
        if current.empty:
            st.success("Tidak ada PO yang masih menunggu.")
        else:
            current["Notifikasi"] = current.apply(lambda r: get_alert(r, today), axis=1)
            current["ETA"] = current.apply(
                lambda r: f'{date_from_text(r["eta_start"]):%d-%m-%Y} – {date_from_text(r["eta_end"]):%d-%m-%Y}', axis=1
            )
            current["Reminder supplier"] = current["reminder_date"].apply(lambda x: date_from_text(x).strftime("%d-%m-%Y"))
            current["Tanggal PO"] = current["po_date"].apply(lambda x: date_from_text(x).strftime("%d-%m-%Y"))
            priority_order = {
                "Terlambat — follow up segera": 0,
                "Perkiraan datang — cek supplier": 1,
                "Reminder supplier": 2,
                "Dalam proses": 3
            }
            current["_sort"] = current["Notifikasi"].map(priority_order)
            current = current.sort_values(["_sort", "eta_start"])
            show_cols = ["po_number", "supplier", "item_name", "urgency", "Tanggal PO", "ETA", "Reminder supplier", "Notifikasi"]
            st.dataframe(current[show_cols].rename(columns={
                "po_number": "Nomor PO", "supplier": "Supplier", "item_name": "Barang",
                "urgency": "Prioritas"
            }), use_container_width=True, hide_index=True)

            st.markdown("#### Tandai barang sudah datang")
            options = {
                f'PO {r["po_number"]} | {r["supplier"]} | {r["item_name"]}': int(r["id"])
                for _, r in current.iterrows()
            }
            if options:
                selected_label = st.selectbox("Pilih PO yang sudah diterima", list(options.keys()))
                arrival_date = st.date_input("Tanggal barang datang", value=today, key="arrival_date")
                if st.button("✅ Tandai sudah datang"):
                    update_status(options[selected_label], "Sudah Datang", arrival_date)
                    st.success("Status PO diperbarui menjadi Sudah Datang.")
                    st.rerun()

            st.markdown("#### Reminder yang bisa dikirim ke supplier")
            due = current[current["Notifikasi"].isin([
                "Reminder supplier", "Perkiraan datang — cek supplier", "Terlambat — follow up segera"
            ])]
            if not due.empty:
                for _, r in due.iterrows():
                    message = (
                        f"Halo, kami ingin follow up PO {r['po_number']} untuk {r['item_name']} "
                        f"sebanyak {r['quantity']} {r['unit']}. Tanggal PO {r['po_date']}. "
                        f"Mohon konfirmasi estimasi pengiriman dan tanggal barang sampai. Terima kasih."
                    )
                    with st.expander(f'{r["po_number"]} — {r["supplier"]} ({r["Notifikasi"]})'):
                        st.write(message)
                        st.caption("Salin pesan ini dan kirim melalui WhatsApp/email supplier.")
                        st.code(message, language=None)
            else:
                st.success("Belum ada PO yang perlu di-reminder saat ini.")

with tab_manage:
    st.subheader("Riwayat dan pengelolaan PO")
    all_orders = fetch_orders()
    if all_orders.empty:
        st.info("Belum ada PO.")
    else:
        status_filter = st.selectbox("Filter status", ["Semua", "Menunggu", "Sudah Datang", "Dibatalkan"])
        view = all_orders.copy()
        if status_filter != "Semua":
            view = view[view["status"] == status_filter]
        view["ETA"] = view.apply(
            lambda r: f'{date_from_text(r["eta_start"]):%d-%m-%Y} – {date_from_text(r["eta_end"]):%d-%m-%Y}', axis=1
        )
        view["Notifikasi"] = view.apply(lambda r: get_alert(r, today), axis=1)
        st.dataframe(view[[
            "id", "po_number", "supplier", "item_name", "quantity", "unit",
            "po_date", "urgency", "ETA", "status", "arrived_date", "Notifikasi", "notes"
        ]].rename(columns={
            "id": "ID", "po_number": "Nomor PO", "supplier": "Supplier",
            "item_name": "Barang", "quantity": "Qty", "unit": "Satuan",
            "po_date": "Tanggal PO", "urgency": "Prioritas",
            "arrived_date": "Tanggal Datang", "notes": "Catatan"
        }), use_container_width=True, hide_index=True)

        st.markdown("#### Ubah status / hapus PO")
        ids = all_orders["id"].astype(int).tolist()
        selected_id = st.selectbox("Pilih ID PO", ids)
        selected_row = all_orders[all_orders["id"] == selected_id].iloc[0]
        new_status = st.selectbox(
            "Status baru", ["Menunggu", "Sudah Datang", "Dibatalkan"],
            index=["Menunggu", "Sudah Datang", "Dibatalkan"].index(selected_row["status"])
        )
        manual_arrival = st.date_input("Tanggal datang (jika sudah datang)", value=today, key="manual_arrival")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Simpan perubahan status"):
                update_status(selected_id, new_status, manual_arrival if new_status == "Sudah Datang" else None)
                st.success("Status berhasil diperbarui.")
                st.rerun()
        with col_b:
            confirm_delete = st.checkbox("Saya yakin ingin menghapus PO ini")
            if st.button("🗑️ Hapus PO", disabled=not confirm_delete):
                delete_order(selected_id)
                st.success("PO dihapus.")
                st.rerun()

        csv = all_orders.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Download data PO (CSV)", csv, file_name="data_po.csv", mime="text/csv")

st.divider()
st.caption("Aturan default: Urgent = estimasi 10–14 hari (target hari ke-10), reminder hari ke-8. Normal = estimasi 14–21 hari, reminder hari ke-12. Aturan reminder dapat diubah di bagian kode.")
