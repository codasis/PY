"""
Python Cafe Management System — Professional Edition
======================================================

A desktop point-of-sale style application for a cafe/small restaurant,
built with tkinter + ttkbootstrap and backed by a local SQLite database.

Features
--------
- Categorized, searchable menu (tabs for Beverages / Snacks / Main Course / Desserts)
- Quantity-aware cart with increase / decrease / remove controls
- Configurable discount % and tax % applied at checkout
- Persistent order history stored in SQLite (survives app restarts)
- Printable / savable text receipts
- Menu administration screen (add / edit / delete items) — no code editing needed
- Live clock, keyboard shortcuts, and a light/dark theme toggle

Requirements
------------
    pip install ttkbootstrap

Run
---
    python cafe_management_system.py

The app creates "cafe_data.db" next to this script on first run and reuses
it afterwards, so the menu and all past orders persist between sessions.
"""

import datetime
import sqlite3
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import ttkbootstrap as tb
from ttkbootstrap.constants import SUCCESS, DANGER, PRIMARY, INFO, SECONDARY, WARNING


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_TITLE = "Python Cafe Management System — Professional Edition"

try:
    DB_PATH = Path(__file__).resolve().parent / "cafe_data.db"
except NameError:  # e.g. run inside some interactive shells
    DB_PATH = Path.cwd() / "cafe_data.db"

CATEGORIES = ["Beverages", "Snacks", "Main Course", "Desserts"]

DEFAULT_MENU = [
    # (name, category, price)
    ("Coffee", "Beverages", 60),
    ("Tea", "Beverages", 20),
    ("Cappuccino", "Beverages", 120),
    ("Hot Chocolate", "Beverages", 160),
    ("Cold Drink", "Beverages", 80),
    ("Mineral Water", "Beverages", 30),
    ("Sandwich", "Snacks", 80),
    ("French Fries", "Snacks", 90),
    ("Veg Burger", "Main Course", 160),
    ("Chicken Burger", "Main Course", 200),
    ("Pizza", "Main Course", 220),
    ("Pasta", "Main Course", 185),
    ("Ice Cream", "Desserts", 100),
    ("Chocolate Cake", "Desserts", 140),
]

PAYMENT_MODES = ["Cash", "Card", "UPI"]
LIGHT_THEME = "flatly"
DARK_THEME = "darkly"


# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------
class Database:
    """Owns the SQLite connection and every query the app needs."""

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()
        self._seed_defaults()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS menu_items (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                price    REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                subtotal     REAL NOT NULL,
                discount_pct REAL NOT NULL,
                tax_pct      REAL NOT NULL,
                total        REAL NOT NULL,
                payment_mode TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                item_name  TEXT NOT NULL,
                qty        INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                line_total REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def _seed_defaults(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM menu_items")
        if cur.fetchone()[0] == 0:
            cur.executemany(
                "INSERT INTO menu_items (name, category, price) VALUES (?, ?, ?)",
                DEFAULT_MENU,
            )
        cur.execute("SELECT COUNT(*) FROM settings WHERE key = 'tax_pct'")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO settings (key, value) VALUES ('tax_pct', '5')")
        self.conn.commit()

    # -- Menu ----------------------------------------------------------
    def get_menu(self, category=None, search=None):
        query = "SELECT id, name, category, price FROM menu_items"
        clauses, params = [], []
        if category and category != "All":
            clauses.append("category = ?")
            params.append(category)
        if search:
            clauses.append("name LIKE ?")
            params.append(f"%{search}%")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY category, name"
        return self.conn.execute(query, params).fetchall()

    def add_menu_item(self, name, category, price):
        self.conn.execute(
            "INSERT INTO menu_items (name, category, price) VALUES (?, ?, ?)",
            (name, category, price),
        )
        self.conn.commit()

    def update_menu_item(self, item_id, name, category, price):
        self.conn.execute(
            "UPDATE menu_items SET name=?, category=?, price=? WHERE id=?",
            (name, category, price, item_id),
        )
        self.conn.commit()

    def delete_menu_item(self, item_id):
        self.conn.execute("DELETE FROM menu_items WHERE id=?", (item_id,))
        self.conn.commit()

    # -- Settings --------------------------------------------------------
    def get_setting(self, key, default=None):
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    # -- Orders ------------------------------------------------------------
    def save_order(self, cart, subtotal, discount_pct, tax_pct, total, payment_mode):
        cur = self.conn.cursor()
        order_number = self._next_order_number()
        cur.execute(
            "INSERT INTO orders (order_number, created_at, subtotal, discount_pct, "
            "tax_pct, total, payment_mode) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                order_number,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                subtotal,
                discount_pct,
                tax_pct,
                total,
                payment_mode,
            ),
        )
        order_id = cur.lastrowid
        for name, qty, price in cart:
            cur.execute(
                "INSERT INTO order_items (order_id, item_name, qty, unit_price, "
                "line_total) VALUES (?, ?, ?, ?, ?)",
                (order_id, name, qty, price, qty * price),
            )
        self.conn.commit()
        return order_number, order_id

    def _next_order_number(self):
        count = self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] + 1
        today = datetime.date.today().strftime("%Y%m%d")
        return f"CAFE-{today}-{count:04d}"

    def get_order_history(self, limit=300):
        return self.conn.execute(
            "SELECT id, order_number, created_at, total, payment_mode "
            "FROM orders ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def get_order(self, order_id):
        return self.conn.execute(
            "SELECT order_number, created_at, subtotal, discount_pct, tax_pct, "
            "total, payment_mode FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()

    def get_order_items(self, order_id):
        return self.conn.execute(
            "SELECT item_name, qty, unit_price, line_total FROM order_items "
            "WHERE order_id=?",
            (order_id,),
        ).fetchall()


# ---------------------------------------------------------------------------
# Small reusable helpers
# ---------------------------------------------------------------------------
def money(value: float) -> str:
    return f"\u20b9{value:,.2f}"


def parse_positive_float(value: str, field_name: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a number.")
    if number < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return number


# ---------------------------------------------------------------------------
# Menu administration dialog
# ---------------------------------------------------------------------------
class MenuManagerDialog(tb.Toplevel):
    """Lets staff add, edit, or remove menu items without touching code."""

    def __init__(self, master, db: Database, on_change):
        super().__init__(master)
        self.db = db
        self.on_change = on_change
        self.title("Manage Menu Items")
        self.geometry("560x480")
        self.resizable(False, False)
        self.selected_id = None
        self._build()
        self._refresh()

    def _build(self):
        columns = ("ID", "Name", "Category", "Price")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=12)
        for col, width in zip(columns, (40, 200, 140, 80)):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="center" if col != "Name" else "w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=(12, 8))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        form = tb.Frame(self)
        form.pack(fill="x", padx=12, pady=4)

        tb.Label(form, text="Name").grid(row=0, column=0, sticky="w", pady=4)
        self.name_var = tk.StringVar()
        tb.Entry(form, textvariable=self.name_var, width=28).grid(row=0, column=1, padx=8)

        tb.Label(form, text="Category").grid(row=1, column=0, sticky="w", pady=4)
        self.category_var = tk.StringVar(value=CATEGORIES[0])
        ttk.Combobox(
            form, textvariable=self.category_var, values=CATEGORIES,
            state="readonly", width=25,
        ).grid(row=1, column=1, padx=8)

        tb.Label(form, text="Price (\u20b9)").grid(row=2, column=0, sticky="w", pady=4)
        self.price_var = tk.StringVar()
        tb.Entry(form, textvariable=self.price_var, width=28).grid(row=2, column=1, padx=8)

        btns = tb.Frame(self)
        btns.pack(fill="x", padx=12, pady=10)
        tb.Button(btns, text="Add New", bootstyle=SUCCESS, command=self._add).pack(side="left", padx=4)
        tb.Button(btns, text="Save Changes", bootstyle=PRIMARY, command=self._update).pack(side="left", padx=4)
        tb.Button(btns, text="Delete Selected", bootstyle=DANGER, command=self._delete).pack(side="left", padx=4)
        tb.Button(btns, text="Clear Form", bootstyle=SECONDARY, command=self._clear_form).pack(side="left", padx=4)

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for item_id, name, category, price in self.db.get_menu():
            self.tree.insert("", tk.END, iid=str(item_id), values=(item_id, name, category, money(price)))

    def _on_select(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        item_id, name, category, price = self.tree.item(selection[0], "values")
        self.selected_id = int(item_id)
        self.name_var.set(name)
        self.category_var.set(category)
        self.price_var.set(price.replace("\u20b9", "").replace(",", ""))

    def _clear_form(self):
        self.selected_id = None
        self.name_var.set("")
        self.category_var.set(CATEGORIES[0])
        self.price_var.set("")
        self.tree.selection_remove(self.tree.selection())

    def _validated_fields(self):
        name = self.name_var.get().strip()
        category = self.category_var.get()
        if not name:
            raise ValueError("Item name cannot be empty.")
        price = parse_positive_float(self.price_var.get(), "Price")
        return name, category, price

    def _add(self):
        try:
            name, category, price = self._validated_fields()
            self.db.add_menu_item(name, category, price)
        except sqlite3.IntegrityError:
            messagebox.showerror("Duplicate Item", "An item with this name already exists.", parent=self)
            return
        except ValueError as exc:
            messagebox.showerror("Invalid Input", str(exc), parent=self)
            return
        self._refresh()
        self._clear_form()
        self.on_change()

    def _update(self):
        if self.selected_id is None:
            messagebox.showwarning("No Selection", "Select an item to edit first.", parent=self)
            return
        try:
            name, category, price = self._validated_fields()
            self.db.update_menu_item(self.selected_id, name, category, price)
        except sqlite3.IntegrityError:
            messagebox.showerror("Duplicate Item", "An item with this name already exists.", parent=self)
            return
        except ValueError as exc:
            messagebox.showerror("Invalid Input", str(exc), parent=self)
            return
        self._refresh()
        self._clear_form()
        self.on_change()

    def _delete(self):
        if self.selected_id is None:
            messagebox.showwarning("No Selection", "Select an item to delete first.", parent=self)
            return
        if messagebox.askyesno("Confirm Delete", "Remove this item from the menu?", parent=self):
            self.db.delete_menu_item(self.selected_id)
            self._refresh()
            self._clear_form()
            self.on_change()


# ---------------------------------------------------------------------------
# Order history dialog
# ---------------------------------------------------------------------------
class OrderHistoryDialog(tb.Toplevel):
    """Read-only browser for past orders, with a drill-down receipt view."""

    def __init__(self, master, db: Database):
        super().__init__(master)
        self.db = db
        self.title("Order History")
        self.geometry("640x480")
        self._build()

    def _build(self):
        columns = ("Order #", "Date & Time", "Total", "Payment")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=16)
        widths = (160, 160, 100, 100)
        for col, width in zip(columns, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=12, pady=12)
        self.tree.bind("<Double-1>", self._show_receipt)

        for order_id, number, created_at, total, payment in self.db.get_order_history():
            self.tree.insert("", tk.END, iid=str(order_id), values=(number, created_at, money(total), payment))

        tb.Label(self, text="Double-click an order to view its full receipt.", bootstyle=SECONDARY).pack(pady=(0, 10))

    def _show_receipt(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        order_id = int(selection[0])
        header = self.db.get_order(order_id)
        items = self.db.get_order_items(order_id)
        if not header:
            return
        number, created_at, subtotal, discount_pct, tax_pct, total, payment = header
        text = build_receipt_text(number, created_at, items, subtotal, discount_pct, tax_pct, total, payment)
        ReceiptWindow(self, text, number)


# ---------------------------------------------------------------------------
# Receipt rendering + window
# ---------------------------------------------------------------------------
def build_receipt_text(order_number, created_at, items, subtotal, discount_pct, tax_pct, total, payment_mode):
    lines = []
    lines.append("=" * 42)
    lines.append("        PYTHON CAFE — OFFICIAL RECEIPT")
    lines.append("=" * 42)
    lines.append(f"Order No.  : {order_number}")
    lines.append(f"Date/Time  : {created_at}")
    lines.append(f"Payment    : {payment_mode}")
    lines.append("-" * 42)
    lines.append(f"{'Item':<20}{'Qty':>5}{'Price':>8}{'Amount':>9}")
    lines.append("-" * 42)
    for name, qty, price, line_total in items:
        lines.append(f"{name:<20}{qty:>5}{price:>8.2f}{line_total:>9.2f}")
    lines.append("-" * 42)
    lines.append(f"{'Subtotal':<33}{subtotal:>9.2f}")
    if discount_pct:
        discount_amt = subtotal * discount_pct / 100
        lines.append(f"{'Discount (' + str(discount_pct) + '%)':<33}-{discount_amt:>8.2f}")
    if tax_pct:
        taxed_base = subtotal - (subtotal * discount_pct / 100)
        tax_amt = taxed_base * tax_pct / 100
        lines.append(f"{'Tax (' + str(tax_pct) + '%)':<33}{tax_amt:>9.2f}")
    lines.append("=" * 42)
    lines.append(f"{'TOTAL':<33}{total:>9.2f}")
    lines.append("=" * 42)
    lines.append("     Thank you for visiting Python Cafe!")
    return "\n".join(lines)


class ReceiptWindow(tb.Toplevel):
    """Shows a formatted receipt with a Save-to-file option."""

    def __init__(self, master, receipt_text, order_number):
        super().__init__(master)
        self.receipt_text = receipt_text
        self.order_number = order_number
        self.title(f"Receipt — {order_number}")
        self.geometry("420x520")
        self.resizable(False, False)

        text_widget = tk.Text(self, font=("Consolas", 11), wrap="none")
        text_widget.insert("1.0", receipt_text)
        text_widget.configure(state="disabled")
        text_widget.pack(fill="both", expand=True, padx=10, pady=10)

        btns = tb.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        tb.Button(btns, text="Save as .txt", bootstyle=PRIMARY, command=self._save).pack(side="left", padx=4)
        tb.Button(btns, text="Close", bootstyle=SECONDARY, command=self.destroy).pack(side="right", padx=4)

    def _save(self):
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".txt",
            initialfile=f"{self.order_number}.txt",
            filetypes=[("Text file", "*.txt")],
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as file:
            file.write(self.receipt_text)
        messagebox.showinfo("Saved", f"Receipt saved to:\n{path}", parent=self)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class CafeApp:
    def __init__(self):
        self.db = Database(DB_PATH)
        self.cart = {}  # name -> [qty, price]
        self.current_theme = LIGHT_THEME

        self.app = tb.Window(themename=self.current_theme)
        self.app.title(APP_TITLE)
        self.app.geometry("1180x680")
        self.app.minsize(1000, 620)

        self.tax_pct_var = tk.StringVar(value=self.db.get_setting("tax_pct", "5"))
        self.discount_pct_var = tk.StringVar(value="0")
        self.payment_var = tk.StringVar(value=PAYMENT_MODES[0])
        self.search_var = tk.StringVar()
        self.qty_var = tk.IntVar(value=1)
        self.clock_var = tk.StringVar()

        self._build_menubar()
        self._build_header()
        self._build_body()
        self._build_statusbar()
        self._bind_shortcuts()
        self._refresh_menu_tables()
        self._recalculate()
        self._tick_clock()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_menubar(self):
        menubar = tk.Menu(self.app)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Order", accelerator="Ctrl+N", command=self.clear_order)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.app.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        manage_menu = tk.Menu(menubar, tearoff=False)
        manage_menu.add_command(label="Menu Items...", command=self.open_menu_manager)
        manage_menu.add_command(label="Order History...", command=self.open_order_history)
        menubar.add_cascade(label="Manage", menu=manage_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Toggle Light / Dark Theme", command=self.toggle_theme)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.app.config(menu=menubar)

    def _build_header(self):
        header = tb.Frame(self.app)
        header.pack(fill="x", padx=20, pady=(15, 5))

        tb.Label(
            header, text="\u2615 PYTHON CAFE MANAGEMENT SYSTEM",
            font=("Segoe UI", 22, "bold"), bootstyle=SUCCESS,
        ).pack(side="left")

        tb.Label(header, textvariable=self.clock_var, font=("Segoe UI", 11), bootstyle=SECONDARY).pack(side="right")

    def _build_body(self):
        body = tb.Frame(self.app)
        body.pack(fill="both", expand=True, padx=20, pady=10)

        self._build_left_panel(body)
        self._build_right_panel(body)

    def _build_left_panel(self, parent):
        left = tb.Frame(parent)
        left.pack(side="left", fill="both", expand=True, padx=(0, 15))

        tb.Label(left, text="MENU CARD", font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(0, 6))

        search_row = tb.Frame(left)
        search_row.pack(fill="x", pady=(0, 8))
        tb.Label(search_row, text="Search:").pack(side="left")
        search_entry = tb.Entry(search_row, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.search_var.trace_add("write", lambda *_: self._refresh_menu_tables())

        self.notebook = ttk.Notebook(left)
        self.notebook.pack(fill="both", expand=True)

        self.category_trees = {}
        for category in ["All"] + CATEGORIES:
            tab = tb.Frame(self.notebook)
            self.notebook.add(tab, text=category)

            columns = ("Item", "Price")
            tree = ttk.Treeview(tab, columns=columns, show="headings", height=14)
            tree.heading("Item", text="Item")
            tree.heading("Price", text="Price (\u20b9)")
            tree.column("Item", width=260)
            tree.column("Price", width=100, anchor="center")
            tree.pack(fill="both", expand=True, side="left")
            tree.bind("<Double-1>", self._on_menu_double_click)

            scrollbar = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")

            self.category_trees[category] = tree

        add_row = tb.Frame(left)
        add_row.pack(fill="x", pady=10)
        tb.Label(add_row, text="Qty:").pack(side="left")
        tb.Spinbox(add_row, from_=1, to=50, width=5, textvariable=self.qty_var).pack(side="left", padx=8)
        tb.Button(add_row, text="\u2795 Add Selected to Order", bootstyle=SUCCESS, command=self.add_selected_item).pack(side="left", padx=8)

    def _build_right_panel(self, parent):
        right = tb.Frame(parent, width=420)
        right.pack(side="right", fill="both")
        right.pack_propagate(False)

        tb.Label(right, text="CUSTOMER ORDER", font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(0, 6))

        columns = ("Item", "Qty", "Price", "Subtotal")
        self.cart_tree = ttk.Treeview(right, columns=columns, show="headings", height=11)
        widths = (150, 45, 75, 90)
        for col, width in zip(columns, widths):
            self.cart_tree.heading(col, text=col)
            self.cart_tree.column(col, width=width, anchor="center" if col != "Item" else "w")
        self.cart_tree.pack(fill="both", expand=False)

        cart_btns = tb.Frame(right)
        cart_btns.pack(fill="x", pady=8)
        tb.Button(cart_btns, text="\u2795 Qty", bootstyle=INFO, width=8, command=lambda: self.change_qty(1)).pack(side="left", padx=3)
        tb.Button(cart_btns, text="\u2796 Qty", bootstyle=INFO, width=8, command=lambda: self.change_qty(-1)).pack(side="left", padx=3)
        tb.Button(cart_btns, text="Remove", bootstyle=WARNING, width=8, command=self.remove_selected).pack(side="left", padx=3)
        tb.Button(cart_btns, text="Clear All", bootstyle=DANGER, width=8, command=self.clear_order).pack(side="left", padx=3)

        totals = tb.Frame(right)
        totals.pack(fill="x", pady=(6, 4))

        tb.Label(totals, text="Discount %:").grid(row=0, column=0, sticky="w", pady=3)
        discount_entry = tb.Entry(totals, textvariable=self.discount_pct_var, width=8)
        discount_entry.grid(row=0, column=1, sticky="w", padx=6)
        self.discount_pct_var.trace_add("write", lambda *_: self._recalculate())

        tb.Label(totals, text="Tax %:").grid(row=1, column=0, sticky="w", pady=3)
        tax_entry = tb.Entry(totals, textvariable=self.tax_pct_var, width=8)
        tax_entry.grid(row=1, column=1, sticky="w", padx=6)
        self.tax_pct_var.trace_add("write", lambda *_: self._recalculate())

        tb.Label(totals, text="Payment:").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(
            totals, textvariable=self.payment_var, values=PAYMENT_MODES,
            state="readonly", width=10,
        ).grid(row=2, column=1, sticky="w", padx=6)

        self.subtotal_label = tb.Label(right, text="Subtotal: \u20b90.00", font=("Segoe UI", 11))
        self.subtotal_label.pack(anchor="e", pady=(8, 0))
        self.total_label = tb.Label(right, text="TOTAL: \u20b90.00", font=("Segoe UI", 18, "bold"), bootstyle=SUCCESS)
        self.total_label.pack(anchor="e", pady=(2, 10))

        tb.Button(right, text="\U0001f9fe Checkout & Print Bill", bootstyle=PRIMARY, command=self.checkout).pack(fill="x")

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="Ready")
        status = tb.Label(self.app, textvariable=self.status_var, anchor="w", bootstyle=SECONDARY)
        status.pack(fill="x", side="bottom", padx=10, pady=4)

    def _bind_shortcuts(self):
        self.app.bind("<Control-n>", lambda _e: self.clear_order())
        self.app.bind("<Delete>", lambda _e: self.remove_selected())

    # ------------------------------------------------------------------
    # Menu display
    # ------------------------------------------------------------------
    def _refresh_menu_tables(self):
        search = self.search_var.get().strip()
        for category, tree in self.category_trees.items():
            tree.delete(*tree.get_children())
            rows = self.db.get_menu(category=category, search=search)
            for item_id, name, cat, price in rows:
                tree.insert("", tk.END, iid=str(item_id), values=(name, money(price)))

    def _on_menu_double_click(self, event):
        self.add_selected_item(event=event)

    def _current_tab_tree(self):
        current_tab_index = self.notebook.index(self.notebook.select())
        category = (["All"] + CATEGORIES)[current_tab_index]
        return self.category_trees[category]

    # ------------------------------------------------------------------
    # Cart operations
    # ------------------------------------------------------------------
    def add_selected_item(self, event=None):
        tree = self._current_tab_tree()
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Select an item from the menu first.")
            return
        name, price_text = tree.item(selection[0], "values")
        price = float(price_text.replace("\u20b9", "").replace(",", ""))

        try:
            qty = int(self.qty_var.get())
        except (tk.TclError, ValueError):
            qty = 1
        if qty < 1:
            qty = 1

        if name in self.cart:
            self.cart[name][0] += qty
        else:
            self.cart[name] = [qty, price]

        self.status_var.set(f"Added {qty} x {name} to the order.")
        self._refresh_cart_table()
        self._recalculate()

    def change_qty(self, delta):
        selection = self.cart_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Select an item in the order first.")
            return
        name = selection[0]
        if name not in self.cart:
            return
        self.cart[name][0] += delta
        if self.cart[name][0] <= 0:
            del self.cart[name]
        self._refresh_cart_table()
        self._recalculate()

    def remove_selected(self):
        selection = self.cart_tree.selection()
        if not selection:
            return
        for name in selection:
            self.cart.pop(name, None)
        self._refresh_cart_table()
        self._recalculate()

    def clear_order(self):
        self.cart.clear()
        self.discount_pct_var.set("0")
        self._refresh_cart_table()
        self._recalculate()
        self.status_var.set("Order cleared. Ready for a new customer.")

    def _refresh_cart_table(self):
        self.cart_tree.delete(*self.cart_tree.get_children())
        for name, (qty, price) in self.cart.items():
            self.cart_tree.insert("", tk.END, iid=name, values=(name, qty, money(price), money(qty * price)))

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------
    def _safe_percent(self, raw_value, fallback=0.0):
        try:
            value = float(raw_value)
        except ValueError:
            return fallback
        return max(0.0, min(value, 100.0))

    def _recalculate(self):
        subtotal = sum(qty * price for qty, price in self.cart.values())
        discount_pct = self._safe_percent(self.discount_pct_var.get())
        tax_pct = self._safe_percent(self.tax_pct_var.get())

        discounted = subtotal - (subtotal * discount_pct / 100)
        total = discounted + (discounted * tax_pct / 100)

        self.subtotal_label.config(text=f"Subtotal: {money(subtotal)}")
        self.total_label.config(text=f"TOTAL: {money(total)}")
        return subtotal, discount_pct, tax_pct, total

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------
    def checkout(self):
        if not self.cart:
            messagebox.showinfo("Empty Order", "Add at least one item before checking out.")
            return

        subtotal, discount_pct, tax_pct, total = self._recalculate()
        payment_mode = self.payment_var.get()
        cart_rows = [(name, qty, price) for name, (qty, price) in self.cart.items()]

        self.db.set_setting("tax_pct", tax_pct)
        order_number, order_id = self.db.save_order(
            cart_rows, subtotal, discount_pct, tax_pct, total, payment_mode
        )

        items_for_receipt = self.db.get_order_items(order_id)
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        receipt_text = build_receipt_text(
            order_number, created_at, items_for_receipt, subtotal, discount_pct, tax_pct, total, payment_mode
        )

        ReceiptWindow(self.app, receipt_text, order_number)
        self.status_var.set(f"Order {order_number} saved successfully.")
        self.clear_order()

    # ------------------------------------------------------------------
    # UI Dialogs & Extras
    # ------------------------------------------------------------------
    def open_menu_manager(self):
        MenuManagerDialog(self.app, self.db, on_change=self._refresh_menu_tables)

    def open_order_history(self):
        OrderHistoryDialog(self.app, self.db)

    def toggle_theme(self):
        self.current_theme = DARK_THEME if self.current_theme == LIGHT_THEME else LIGHT_THEME
        self.app.style.theme_use(self.current_theme)

    def show_about(self):
        messagebox.showinfo(
            "About",
            f"{APP_TITLE}\n\nBuilt with Python, Tkinter, ttkbootstrap, and SQLite.",
            parent=self.app,
        )

    def _tick_clock(self):
        now = datetime.datetime.now().strftime("%a, %b %d %Y — %I:%M:%S %p")
        self.clock_var.set(now)
        self.app.after(1000, self._tick_clock)

    def run(self):
        self.app.mainloop()


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = CafeApp()
    app.run()
