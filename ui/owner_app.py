"""Vlasnicka aplikacija: upravljanje zalihama i porudzbinama."""

import threading
import tkinter as tk
from collections.abc import Callable
from contextlib import suppress
from functools import partial
from tkinter import messagebox, ttk

from models.card import Card
from services.card_lookup import CardCatalog
from services.shop_database import (
    ACTIVE_STATUSES,
    ALLOWED_TRANSITIONS,
    CONDITIONS,
    ORDER_STATUSES,
    OrderSummary,
    ShopDatabase,
    StockItem,
    condition_label,
    status_label,
    suggested_price_rsd,
)
from ui.dispatch import TkDispatcher
from ui.shop_widgets import (
    CardPreview,
    center_window,
    configure_treeview_style,
    fit_tree_columns,
    format_datetime,
    format_rsd,
)


class OwnerApp:
    """Odvojen program za vlasnika prodavnice."""

    def __init__(self, root: tk.Tk, catalog: CardCatalog, shop: ShopDatabase):
        self.root = root
        self.catalog = catalog
        self.shop = shop
        self.catalog_cards: list[Card] = []
        self.stock_by_id: dict[int, StockItem] = {}
        self.orders_by_id: dict[int, OrderSummary] = {}
        self.selected_order_id: int | None = None
        self._catalog_search_job: str | None = None
        self._catalog_ready = False
        self._dispatcher = TkDispatcher(self.root)
        self.root.bind("<Destroy>", self._on_root_destroy, add="+")

        self._configure_root()
        self._build_header()
        self._build_notebook()
        self._refresh_stock()
        self._refresh_orders()
        self._start_catalog_load()

    # ------------------------------------------------------------------ setup

    def _on_root_destroy(self, event: tk.Event) -> None:
        if event.widget is self.root:
            self._dispatcher.close()

    def _configure_root(self):
        self.root.title("Card Tracker — Vlasnik")

        # 30% veci prozor od prvobitnog 1500x900, ali nikad veci od ekrana.
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(1950, max(1100, int(screen_width * 0.9)))
        height = min(1170, max(700, int(screen_height * 0.9)))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(1400, width), min(900, height))
        configure_treeview_style(self.root)

    def _build_header(self):
        header = ttk.Frame(self.root, padding=(16, 12, 16, 6))
        header.pack(fill=tk.X)

        title_box = ttk.Frame(header)
        title_box.pack(side=tk.LEFT)
        ttk.Label(title_box, text="Upravljanje prodavnicom", font=("Helvetica", 18, "bold")).pack(anchor="w")
        ttk.Label(
            title_box,
            text="Zalihe, porudžbine i kontakti kupaca na jednom mestu.",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 0))

        self.stats_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.stats_var, font=("Helvetica", 10, "bold"), foreground="#1b5e20").pack(
            side=tk.RIGHT, padx=8
        )

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self.tab_stock = ttk.Frame(self.notebook)
        self.tab_orders = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_stock, text="Zalihe")
        self.notebook.add(self.tab_orders, text="Porudžbine")

        self._build_stock_tab()
        self._build_orders_tab()

    # ------------------------------------------------------------------ stock

    def _build_stock_tab(self):
        paned = ttk.Panedwindow(self.tab_stock, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, pady=6)
        self.stock_paned = paned

        catalog_box = ttk.LabelFrame(paned, text=" Katalog — dodaj karticu na stanje ", padding=8)
        stock_box = ttk.LabelFrame(paned, text=" Trenutno stanje ", padding=8)
        paned.add(catalog_box, weight=4)
        paned.add(stock_box, weight=4)

        # --- catalog search
        search_row = ttk.Frame(catalog_box)
        search_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(search_row, text="Pretraga kataloga:").pack(side=tk.LEFT, padx=(0, 6))
        self.catalog_search_var = tk.StringVar()
        self.catalog_search_var.trace_add("write", self._on_catalog_search_changed)
        self.catalog_search_entry = ttk.Entry(search_row, textvariable=self.catalog_search_var)
        self.catalog_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.catalog_search_button = ttk.Button(search_row, text="Traži", command=self._search_catalog)
        self.catalog_search_button.pack(side=tk.LEFT, padx=(6, 0))

        self.catalog_info_var = tk.StringVar(value="Učitavam katalog...")
        ttk.Label(catalog_box, textvariable=self.catalog_info_var, foreground="#555555").pack(anchor="w")

        catalog_tree_box = ttk.Frame(catalog_box)
        catalog_tree_box.pack(fill=tk.BOTH, expand=True, pady=(4, 6))

        catalog_columns = ("name", "set", "number", "rarity", "normal", "foil")
        self.catalog_tree = ttk.Treeview(
            catalog_tree_box, columns=catalog_columns, show="headings", selectmode="browse"
        )
        catalog_headings = {
            "name": ("Kartica", 190),
            "set": ("Set", 130),
            "number": ("Br.", 50),
            "rarity": ("Rarity", 75),
            "normal": ("Non-Foil", 85),
            "foil": ("Foil", 85),
        }
        for key, (label, width) in catalog_headings.items():
            self.catalog_tree.heading(key, text=label)
            anchor = tk.E if key in ("normal", "foil") else (tk.CENTER if key == "number" else tk.W)
            self.catalog_tree.column(  # type: ignore[call-overload]
                key, width=width, anchor=anchor, stretch=key in ("name", "set")
            )

        self.catalog_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fit_tree_columns(
            self.catalog_tree,
            {"name": 32, "set": 20, "number": 5, "rarity": 9, "normal": 17, "foil": 17},
        )
        catalog_scroll = ttk.Scrollbar(catalog_tree_box, orient="vertical", command=self.catalog_tree.yview)
        self.catalog_tree.configure(yscrollcommand=catalog_scroll.set)
        catalog_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.catalog_tree.bind("<Double-1>", lambda _event: self._add_catalog_card_to_stock())
        self.catalog_tree.bind("<<TreeviewSelect>>", self._on_catalog_select)

        catalog_actions = ttk.Frame(catalog_box)
        catalog_actions.pack(fill=tk.X)
        self.add_stock_button = ttk.Button(
            catalog_actions,
            text="Dodaj izabranu na stanje",
            command=self._add_catalog_card_to_stock,
            state="disabled",
        )
        self.add_stock_button.pack(side=tk.LEFT)
        ttk.Button(catalog_actions, text="Prikaži sve", command=lambda: self.catalog_search_var.set("")).pack(
            side=tk.LEFT, padx=6
        )

        # --- current stock
        stock_search_row = ttk.Frame(stock_box)
        stock_search_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(stock_search_row, text="Filter stanja:").pack(side=tk.LEFT, padx=(0, 6))
        self.stock_search_var = tk.StringVar()
        self.stock_search_var.trace_add("write", lambda *_args: self._refresh_stock())
        ttk.Entry(stock_search_row, textvariable=self.stock_search_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        stock_tree_box = ttk.Frame(stock_box)
        stock_tree_box.pack(fill=tk.BOTH, expand=True)

        stock_columns = (
            "name",
            "set",
            "number",
            "foil",
            "condition",
            "quantity",
            "reserved",
            "backordered",
            "available",
            "price",
        )
        self.stock_tree = ttk.Treeview(stock_tree_box, columns=stock_columns, show="headings", selectmode="browse")
        stock_headings = {
            "name": ("Kartica", 150),
            "set": ("Set", 95),
            "number": ("Br.", 38),
            "foil": ("Verzija", 58),
            "condition": ("Stanje", 48),
            "quantity": ("Na stanju", 62),
            "reserved": ("Rezerv.", 58),
            "backordered": ("Nedostaje", 64),
            "available": ("Slobodno", 62),
            "price": ("Cena", 80),
        }
        for key, (label, width) in stock_headings.items():
            self.stock_tree.heading(key, text=label)
            anchor = (
                tk.E
                if key in ("quantity", "reserved", "backordered", "available", "price")
                else (tk.CENTER if key in ("number", "foil", "condition") else tk.W)
            )
            self.stock_tree.column(  # type: ignore[call-overload]
                key, width=width, anchor=anchor, stretch=key in ("name", "set")
            )

        self.stock_tree.tag_configure("backorder", foreground="#c62828")
        self.stock_tree.tag_configure("reserved", foreground="#b26a00")
        self.stock_tree.tag_configure("empty", foreground="#999999")
        self.stock_tree.bind("<<TreeviewSelect>>", self._on_stock_select)
        self.stock_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fit_tree_columns(
            self.stock_tree,
            {
                "name": 25,
                "set": 11,
                "number": 4,
                "foil": 8,
                "condition": 7,
                "quantity": 8,
                "reserved": 8,
                "backordered": 8,
                "available": 9,
                "price": 12,
            },
        )

        stock_scroll = ttk.Scrollbar(stock_tree_box, orient="vertical", command=self.stock_tree.yview)
        self.stock_tree.configure(yscrollcommand=stock_scroll.set)
        stock_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        stock_actions = ttk.Frame(stock_box)
        stock_actions.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(stock_actions, text="Izmeni količinu / cenu", command=self._edit_selected_stock).pack(side=tk.LEFT)
        ttk.Button(stock_actions, text="Obriši stavku", command=self._remove_selected_stock).pack(side=tk.LEFT, padx=6)
        ttk.Button(stock_actions, text="Osveži", command=self._refresh_stock).pack(side=tk.LEFT)

        preview_box = ttk.LabelFrame(paned, text=" Pregled kartice ", padding=8)
        paned.add(preview_box, weight=3)

        self.stock_preview = CardPreview(preview_box, size=(320, 448), placeholder="Izaberite karticu")
        self.stock_preview.pack(fill=tk.BOTH, expand=True)

        self.preview_caption_var = tk.StringVar(value="Izaberite karticu iz kataloga ili stanja.")
        ttk.Label(
            preview_box,
            textvariable=self.preview_caption_var,
            justify=tk.CENTER,
            wraplength=330,
            foreground="#555555",
        ).pack(fill=tk.X, pady=(8, 0))

        self.root.after(250, self._fit_preview_pane)

    def _on_catalog_search_changed(self, *_args):
        if self._catalog_search_job is not None:
            self.root.after_cancel(self._catalog_search_job)
        self._catalog_search_job = self.root.after(350, self._search_catalog)

    def _search_catalog(self):
        self._catalog_search_job = None
        if not self._catalog_ready:
            return

        try:
            result = self.catalog.search(self.catalog_search_var.get())
            total = len(result)
            cards = list(result[:100])
        except Exception as exc:
            messagebox.showerror("Katalog", f"Pretraga kataloga nije uspela:\n{exc}")
            return

        self.catalog_cards = cards
        self.catalog_tree.delete(*self.catalog_tree.get_children())

        for index, card in enumerate(cards):
            self.catalog_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    card.name,
                    card.set_name,
                    card.collector_number,
                    card.rarity,
                    format_rsd(card.price_normal_rsd),
                    format_rsd(card.price_foil_rsd),
                ),
            )

        shown = f"Prikazano {len(cards)}" if total <= 100 else f"Prikazano prvih {len(cards)}"
        self.catalog_info_var.set(f"{shown} od {total} rezultata")
        self.add_stock_button.config(state="normal" if cards else "disabled")

        if self.stock_tree.selection():
            self._show_stock_item(int(self.stock_tree.selection()[0]))
        else:
            self._clear_preview()

    def _on_catalog_select(self, _event=None):
        selection = self.catalog_tree.selection()
        if selection:
            self._show_catalog_card(int(selection[0]))
        else:
            self._clear_preview()

    def _on_stock_select(self, _event=None):
        selection = self.stock_tree.selection()
        if selection:
            self._show_stock_item(int(selection[0]))
        else:
            self._clear_preview()

    def _show_catalog_card(self, index: int):
        if not (0 <= index < len(self.catalog_cards)):
            return

        card = self.catalog_cards[index]
        self.stock_preview.show(card.image_url, "Slika nedostupna")
        self.preview_caption_var.set(
            f"{card.name}\n{card.set_name} · #{card.collector_number}\n"
            f"Non-Foil {format_rsd(card.price_normal_rsd)}   |   Foil {format_rsd(card.price_foil_rsd)}"
        )

    def _show_stock_item(self, stock_id: int):
        item = self.stock_by_id.get(stock_id)
        if not item:
            return

        self.stock_preview.show(item.image_url, "Slika nedostupna")
        stock_state = f"Na stanju {item.quantity}, rezervisano {item.reserved}"
        if item.backordered:
            stock_state += f", nedostaje {item.backordered}"
        self.preview_caption_var.set(
            f"{item.name}\n{item.set_label} · #{item.collector_number}\n"
            f"{item.foil_label}, {condition_label(item.condition_code)} · {format_rsd(item.unit_price_rsd)}\n"
            f"{stock_state}"
        )

    def _clear_preview(self):
        self.stock_preview.show(None, "Izaberite karticu")
        self.preview_caption_var.set("Izaberite karticu iz kataloga ili stanja.")

    def _fit_preview_pane(self):
        """Daje dovoljno sirine pregledu slike, nezavisno od sirine tabela."""
        paned = getattr(self, "stock_paned", None)
        if paned is None or not paned.winfo_exists():
            return

        paned.update_idletasks()
        total = paned.winfo_width()
        if total <= 1:
            return

        preview_width = min(390, max(360, int(total * 0.2)))
        with suppress(tk.TclError):
            # Stariji Tk moze odbiti sashpos; tada ostaje automatski raspored.
            paned.sashpos(1, max(300, total - preview_width))

    def _add_catalog_card_to_stock(self):
        selection = self.catalog_tree.selection()
        if not selection:
            messagebox.showwarning("Izbor", "Izaberite karticu iz kataloga.")
            return

        index = int(selection[0])
        if not (0 <= index < len(self.catalog_cards)):
            return

        AddStockDialog(self.root, self.catalog_cards[index], self.shop, self._after_stock_change)

    def _refresh_stock(self):
        selected = self.stock_tree.selection()
        selected_id = int(selected[0]) if selected else None

        items = self.shop.list_stock(self.stock_search_var.get())
        self.stock_by_id = {item.stock_id: item for item in items}

        self.stock_tree.delete(*self.stock_tree.get_children())
        for item in items:
            if item.backordered:
                tag = "backorder"
            elif item.reserved:
                tag = "reserved"
            elif item.available <= 0:
                tag = "empty"
            else:
                tag = ""

            self.stock_tree.insert(
                "",
                tk.END,
                iid=str(item.stock_id),
                values=(
                    item.name,
                    item.set_name,
                    item.collector_number,
                    item.foil_label,
                    item.condition_code,
                    item.quantity,
                    item.reserved,
                    item.backordered,
                    item.available,
                    format_rsd(item.unit_price_rsd),
                ),
                tags=(tag,) if tag else (),
            )

        if selected_id is not None and self.stock_tree.exists(str(selected_id)):
            self.stock_tree.selection_set(str(selected_id))
            self.stock_tree.see(str(selected_id))
            self._show_stock_item(selected_id)
        elif self.catalog_tree.selection():
            self._show_catalog_card(int(self.catalog_tree.selection()[0]))
        else:
            self._clear_preview()

        self._update_header_stats()

    def _selected_stock_item(self) -> StockItem | None:
        selection = self.stock_tree.selection()
        if not selection:
            messagebox.showwarning("Izbor", "Izaberite stavku na stanju.")
            return None
        return self.stock_by_id.get(int(selection[0]))

    def _edit_selected_stock(self):
        item = self._selected_stock_item()
        if item:
            EditStockDialog(self.root, item, self.shop, self._after_stock_change)

    def _remove_selected_stock(self):
        item = self._selected_stock_item()
        if not item:
            return
        if not messagebox.askyesno(
            "Brisanje",
            f"Obrisati '{item.name}' ({item.foil_label}, {item.condition_code}) sa stanja?",
        ):
            return

        try:
            self.shop.remove_stock(item.stock_id)
        except Exception as exc:
            messagebox.showerror("Brisanje nije uspelo", str(exc))
            return

        self._refresh_stock()

    def _after_stock_change(self):
        self._refresh_stock()
        self._refresh_orders()

    def _update_header_stats(self):
        stock = self.shop.stock_stats()
        orders = self.shop.order_stats()
        backordered = f"Nedostaje: {stock['backordered']}   |   " if stock["backordered"] else ""
        self.stats_var.set(
            f"Na stanju: {stock['units']} primeraka ({stock['available']} slobodno)   |   "
            f"{backordered}Nove porudžbine: {orders['new']}   |   Vrednost zaliha: {format_rsd(stock['value_rsd'])}"
        )

    # ----------------------------------------------------------------- orders

    def _build_orders_tab(self):
        top = ttk.Frame(self.tab_orders, padding=(0, 8, 0, 4))
        top.pack(fill=tk.X)

        ttk.Label(top, text="Status:").pack(side=tk.LEFT, padx=(0, 6))
        self.status_filter_var = tk.StringVar(value="Sve")
        self.status_filter = ttk.Combobox(
            top,
            textvariable=self.status_filter_var,
            state="readonly",
            width=22,
            values=["Sve", *(status_label(code) for code in ORDER_STATUSES)],
        )
        self.status_filter.pack(side=tk.LEFT)
        self.status_filter.bind("<<ComboboxSelected>>", lambda _event: self._refresh_orders())

        ttk.Button(top, text="Osveži porudžbine", command=self._refresh_orders).pack(side=tk.LEFT, padx=8)

        self.orders_info_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.orders_info_var, foreground="#555555").pack(side=tk.RIGHT)

        paned = ttk.Panedwindow(self.tab_orders, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        orders_box = ttk.Frame(paned)
        detail_box = ttk.Frame(paned)
        paned.add(orders_box, weight=1)
        paned.add(detail_box, weight=1)

        orders_columns = ("id", "customer", "contact", "status", "total", "created")
        self.orders_tree = ttk.Treeview(orders_box, columns=orders_columns, show="headings", selectmode="browse")
        orders_headings = {
            "id": ("#", 45),
            "customer": ("Kupac", 145),
            "contact": ("Kontakt", 180),
            "status": ("Status", 110),
            "total": ("Ukupno", 90),
            "created": ("Primljena", 115),
        }
        for key, (label, width) in orders_headings.items():
            self.orders_tree.heading(key, text=label)
            anchor = tk.E if key == "total" else (tk.CENTER if key == "id" else tk.W)
            self.orders_tree.column(  # type: ignore[call-overload]
                key, width=width, anchor=anchor, stretch=key in ("customer", "contact")
            )

        self.orders_tree.tag_configure("new", background="#fff8e1")
        self.orders_tree.tag_configure("delivered", foreground="#2e7d32")
        self.orders_tree.tag_configure("cancelled", foreground="#9e9e9e")
        self.orders_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fit_tree_columns(
            self.orders_tree,
            {"id": 6, "customer": 24, "contact": 28, "status": 14, "total": 13, "created": 15},
        )
        self.orders_tree.bind("<<TreeviewSelect>>", self._on_order_select)

        orders_scroll = ttk.Scrollbar(orders_box, orient="vertical", command=self.orders_tree.yview)
        self.orders_tree.configure(yscrollcommand=orders_scroll.set)
        orders_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._build_order_detail(detail_box)

    def _build_order_detail(self, parent):
        contact_box = ttk.LabelFrame(parent, text=" Podaci o kupcu ", padding=8)
        contact_box.pack(fill=tk.X, pady=(0, 6))

        self.detail_vars = {
            "customer": tk.StringVar(value=""),
            "email": tk.StringVar(value=""),
            "phone": tk.StringVar(value=""),
            "status": tk.StringVar(value=""),
            "total": tk.StringVar(value=""),
            "created": tk.StringVar(value=""),
        }
        fields = [
            ("Kupac", "customer"),
            ("E-mail", "email"),
            ("Telefon", "phone"),
            ("Status", "status"),
            ("Ukupno", "total"),
            ("Primljena", "created"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(contact_box, text=f"{label}:").grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=2)
            ttk.Label(contact_box, textvariable=self.detail_vars[key], wraplength=520).grid(
                row=row, column=1, sticky="w", pady=2
            )

        ttk.Label(contact_box, text="Napomena:").grid(row=len(fields), column=0, sticky="nw", padx=(0, 8), pady=2)
        self.detail_note = ttk.Label(contact_box, text="", wraplength=520)
        self.detail_note.grid(row=len(fields), column=1, sticky="w", pady=2)

        lines_box = ttk.LabelFrame(parent, text=" Kartice u porudžbini ", padding=8)

        line_columns = ("name", "set", "number", "foil", "condition", "quantity", "missing", "price", "subtotal")
        self.order_lines_tree = ttk.Treeview(
            lines_box, columns=line_columns, show="headings", selectmode="none", height=9
        )
        line_headings = {
            "name": ("Kartica", 165),
            "set": ("Set", 115),
            "number": ("Br.", 42),
            "foil": ("Verzija", 62),
            "condition": ("Stanje", 52),
            "quantity": ("Kol.", 42),
            "missing": ("Nedostaje", 68),
            "price": ("Cena", 85),
            "subtotal": ("Ukupno", 90),
        }
        for key, (label, width) in line_headings.items():
            self.order_lines_tree.heading(key, text=label)
            anchor = (
                tk.E
                if key in ("price", "subtotal")
                else (tk.CENTER if key in ("number", "foil", "condition", "quantity", "missing") else tk.W)
            )
            self.order_lines_tree.column(  # type: ignore[call-overload]
                key, width=width, anchor=anchor, stretch=key in ("name", "set")
            )
        self.order_lines_tree.tag_configure("missing", foreground="#c62828")
        fit_tree_columns(
            self.order_lines_tree,
            {
                "name": 25,
                "set": 16,
                "number": 5,
                "foil": 7,
                "condition": 6,
                "quantity": 5,
                "missing": 8,
                "price": 13,
                "subtotal": 15,
            },
        )
        self.order_lines_tree.pack(fill=tk.BOTH, expand=True)

        # Dugmad se pakuju pre tabele da bi uvek ostala vidljiva, cak i kada
        # prozor nije dovoljno visok za sve redove porudžbine.
        actions = ttk.Frame(parent)
        actions.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

        self.order_action_buttons: dict[str, ttk.Button] = {}
        for code, text in (
            ("ORDERED", "Karte naručene"),
            ("FULFILLED", "Ispunjeno"),
            ("DELIVERED", "Isporučeno"),
            ("CANCELLED", "Otkaži"),
        ):
            button = ttk.Button(actions, text=text, command=partial(self._change_order_status, code))
            button.pack(side=tk.LEFT, padx=(0, 6))
            self.order_action_buttons[code] = button

        ttk.Button(actions, text="Osveži", command=self._refresh_orders).pack(side=tk.RIGHT)

        lines_box.pack(fill=tk.BOTH, expand=True)

    def _refresh_orders(self):
        selected_id = self.selected_order_id
        filter_text = self.status_filter_var.get()
        status = None
        if filter_text != "Sve":
            status = next((code for code, label in ORDER_STATUSES.items() if label == filter_text), None)

        orders = self.shop.list_orders(status)
        self.orders_by_id = {order.order_id: order for order in orders}

        self.orders_tree.delete(*self.orders_tree.get_children())
        for order in orders:
            contact = order.email or order.phone or "—"
            tag = ""
            if order.status == "NEW":
                tag = "new"
            elif order.status == "DELIVERED":
                tag = "delivered"
            elif order.status == "CANCELLED":
                tag = "cancelled"

            self.orders_tree.insert(
                "",
                tk.END,
                iid=str(order.order_id),
                values=(
                    order.order_id,
                    order.customer_name,
                    contact,
                    order.status_text,
                    format_rsd(order.total_rsd),
                    format_datetime(order.created_at),
                ),
                tags=(tag,) if tag else (),
            )

        self.orders_info_var.set(f"{len(orders)} porudžbina")

        if selected_id is not None and self.orders_tree.exists(str(selected_id)):
            self.orders_tree.selection_set(str(selected_id))
            self.orders_tree.see(str(selected_id))
            self._show_order(selected_id)
        else:
            self.selected_order_id = None
            self._clear_order_detail()

        self._update_header_stats()

    def _on_order_select(self, _event=None):
        selection = self.orders_tree.selection()
        if not selection:
            self.selected_order_id = None
            self._clear_order_detail()
            return
        self._show_order(int(selection[0]))

    def _show_order(self, order_id: int):
        order = self.shop.get_order(order_id)
        if order is None:
            self._clear_order_detail()
            return

        self.selected_order_id = order_id
        self.detail_vars["customer"].set(order.customer_name)
        self.detail_vars["email"].set(order.email or "—")
        self.detail_vars["phone"].set(order.phone or "—")
        self.detail_vars["status"].set(order.status_text)
        self.detail_vars["total"].set(format_rsd(order.total_rsd))
        self.detail_vars["created"].set(format_datetime(order.created_at))
        self.detail_note.config(text=order.note or "—")

        self.order_lines_tree.delete(*self.order_lines_tree.get_children())
        order_is_active = order.status in ACTIVE_STATUSES
        for line in self.shop.get_order_lines(order_id):
            missing = line.missing_quantity if order_is_active else 0
            self.order_lines_tree.insert(
                "",
                tk.END,
                values=(
                    line.name,
                    line.set_name,
                    line.collector_number,
                    line.foil_label,
                    line.condition_code,
                    line.quantity,
                    missing,
                    format_rsd(line.unit_price_rsd),
                    format_rsd(line.subtotal_rsd),
                ),
                tags=("missing",) if missing else (),
            )

        self._update_order_actions(order.status)

    def _clear_order_detail(self):
        for variable in self.detail_vars.values():
            variable.set("")
        self.detail_note.config(text="")
        self.order_lines_tree.delete(*self.order_lines_tree.get_children())
        self._update_order_actions(None)

    def _update_order_actions(self, current_status: str | None):
        allowed = ALLOWED_TRANSITIONS.get(current_status or "", set())
        for code, button in self.order_action_buttons.items():
            button.config(state="normal" if code in allowed else "disabled")

    def _change_order_status(self, new_status: str):
        if self.selected_order_id is None:
            messagebox.showwarning("Izbor", "Izaberite porudžbinu.")
            return

        order = self.shop.get_order(self.selected_order_id)
        if order is None:
            return

        if new_status == "DELIVERED":
            confirmed = messagebox.askyesno(
                "Isporuka",
                f"Isporučiti porudžbinu #{order.order_id}?\n\n"
                "Roba će biti skinuta sa stanja i ovo se ne može poništiti.",
            )
            if not confirmed:
                return
        elif new_status == "CANCELLED":
            if not messagebox.askyesno(
                "Otkazivanje",
                f"Otkazati porudžbinu #{order.order_id}? Rezervisana roba se oslobađa.",
            ):
                return

        try:
            self.shop.update_order_status(order.order_id, new_status)
        except Exception as exc:
            messagebox.showerror("Status nije promenjen", str(exc))
            return

        self._refresh_orders()
        self._refresh_stock()
        if self.orders_tree.exists(str(order.order_id)):
            self.orders_tree.selection_set(str(order.order_id))
            self._show_order(order.order_id)

    # --------------------------------------------------------------- catalog

    def _start_catalog_load(self):
        self.loading_window = tk.Toplevel(self.root)
        self.loading_window.title("Učitavanje kataloga")
        self.loading_window.geometry("520x170")
        self.loading_window.resizable(False, False)
        self.loading_window.transient(self.root)

        ttk.Label(
            self.loading_window,
            text="Učitavam Scryfall katalog karata...\nOvo traje duže samo pri prvom pokretanju.",
            justify=tk.CENTER,
        ).pack(pady=(24, 12))

        progress = ttk.Progressbar(self.loading_window, mode="indeterminate", length=280)
        progress.pack(pady=4)
        progress.start(10)

        self.catalog_search_entry.config(state="disabled")
        self.catalog_search_button.config(state="disabled")

        def worker():
            try:
                self.catalog.load_cards()
                self._dispatcher.post(0, lambda: self._catalog_loaded(True))
            except Exception as exc:
                # ``exc`` is cleared when the except block ends, so capture the
                # message before handing the callback to the main thread.
                message = str(exc)
                self._dispatcher.post(0, lambda: self._catalog_loaded(False, message))

        threading.Thread(target=worker, daemon=True).start()

    def _catalog_loaded(self, success: bool, error: str | None = None):
        if self.loading_window.winfo_exists():
            self.loading_window.destroy()
        if not success:
            self.catalog_info_var.set("Katalog nije učitan.")
            messagebox.showerror("Katalog", f"Katalog nije mogao da se učita:\n{error}")
            return

        self._catalog_ready = True
        self.catalog_search_entry.config(state="normal")
        self.catalog_search_button.config(state="normal")
        self._search_catalog()


# ------------------------------------------------------------------- dialogs


class AddStockDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        card: Card,
        shop: ShopDatabase,
        on_done: Callable[[], None],
    ):
        super().__init__(parent)
        self.card = card
        self.shop = shop
        self.on_done = on_done

        self.title(f"Dodaj na stanje — {card.name}")
        self.resizable(False, False)
        self.transient(parent)
        self._build()
        self.grab_set()
        self.bind("<Escape>", lambda _event: self.destroy())
        center_window(self, parent)

    def _build(self):
        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(body, text=self.card.name, font=("Helvetica", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            body,
            text=f"{self.card.set_name} ({self.card.set_code.upper()}) · #{self.card.collector_number}",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.foil_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Foil verzija", variable=self.foil_var, command=self._update_price).grid(
            row=2, column=1, sticky="w", pady=4
        )

        ttk.Label(body, text="Stanje kartice").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=4)
        self.condition_var = tk.StringVar(value=condition_label("NM"))
        self.condition_combo = ttk.Combobox(
            body,
            textvariable=self.condition_var,
            state="readonly",
            values=[condition_label(code) for code in CONDITIONS],
            width=28,
        )
        self.condition_combo.grid(row=3, column=1, sticky="ew", pady=4)
        self.condition_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_price())

        ttk.Label(body, text="Količina").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=4)
        self.quantity_var = tk.IntVar(value=1)
        ttk.Spinbox(body, from_=1, to=9999, textvariable=self.quantity_var, width=10).grid(
            row=4, column=1, sticky="w", pady=4
        )

        ttk.Label(body, text="Cena po komadu (RSD)").grid(row=5, column=0, sticky="w", padx=(0, 10), pady=4)
        self.price_var = tk.StringVar()
        ttk.Entry(body, textvariable=self.price_var, width=14).grid(row=5, column=1, sticky="w", pady=4)

        self.existing_info_var = tk.StringVar()
        ttk.Label(body, textvariable=self.existing_info_var, foreground="#555555", wraplength=360).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(2, 2)
        )

        ttk.Label(
            body,
            text="Predložena cena dolazi iz kataloga. Možete je promeniti pre dodavanja.",
            foreground="#666666",
            wraplength=360,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(2, 12))

        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Otkaži", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Dodaj na stanje", command=self._save).pack(side=tk.RIGHT, padx=(0, 8))

        body.columnconfigure(1, weight=1)
        self._update_price()

    def _condition_code(self) -> str:
        return self.condition_var.get().split(" - ", 1)[0]

    def _update_price(self):
        existing = self.shop.find_stock_for_card(
            self.card,
            is_foil=self.foil_var.get(),
            condition_code=self._condition_code(),
        )

        if existing:
            self.price_var.set(str(existing.unit_price_rsd))
            self.existing_info_var.set(
                f"Ova kombinacija je već na stanju: {existing.quantity} primeraka "
                f"({existing.reserved} rezervisano). Količina će biti dodata."
            )
        else:
            self.price_var.set(str(suggested_price_rsd(self.card, self.foil_var.get(), self._condition_code())))
            self.existing_info_var.set("Nova stavka na stanju.")

    def _save(self):
        try:
            quantity = int(self.quantity_var.get())
            price = int(self.price_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Neispravan unos", "Količina i cena moraju biti celi brojevi.", parent=self)
            return

        try:
            self.shop.add_stock(
                self.card,
                is_foil=self.foil_var.get(),
                condition_code=self._condition_code(),
                quantity=quantity,
                unit_price_rsd=price,
            )
        except Exception as exc:
            messagebox.showerror("Dodavanje nije uspelo", str(exc), parent=self)
            return

        messagebox.showinfo(
            "Dodato na stanje",
            f"{self.card.name} — {quantity} primeraka je dodato na stanje.",
            parent=self,
        )
        self.destroy()
        self.on_done()


class EditStockDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        item: StockItem,
        shop: ShopDatabase,
        on_done: Callable[[], None],
    ):
        super().__init__(parent)
        self.item = item
        self.shop = shop
        self.on_done = on_done

        self.title(f"Izmena stanja — {item.name}")
        self.resizable(False, False)
        self.transient(parent)
        self._build()
        self.grab_set()
        self.bind("<Escape>", lambda _event: self.destroy())
        center_window(self, parent)

    def _build(self):
        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(body, text=self.item.name, font=("Helvetica", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            body,
            text=f"{self.item.set_label} · #{self.item.collector_number} · "
            f"{self.item.foil_label} · {condition_label(self.item.condition_code)}",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        ttk.Label(body, text="Trenutno na stanju:").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=4)
        stock_state = f"{self.item.quantity} (rezervisano {self.item.reserved}"
        if self.item.backordered:
            stock_state += f", nedostaje {self.item.backordered}"
        stock_state += ")"
        ttk.Label(body, text=stock_state).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(body, text="Nova količina").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=4)
        self.quantity_var = tk.IntVar(value=self.item.quantity)
        ttk.Spinbox(body, from_=0, to=999999, textvariable=self.quantity_var, width=12).grid(
            row=3, column=1, sticky="w", pady=4
        )

        ttk.Label(body, text="Cena po komadu (RSD)").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=4)
        self.price_var = tk.StringVar(value=str(self.item.unit_price_rsd))
        ttk.Entry(body, textvariable=self.price_var, width=14).grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(
            body,
            text="Ne možete smanjiti količinu ispod broja rezervisanih primeraka.",
            foreground="#666666",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 12))

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Otkaži", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Sačuvaj", command=self._save).pack(side=tk.RIGHT, padx=(0, 8))

        body.columnconfigure(1, weight=1)

    def _save(self):
        try:
            quantity = int(self.quantity_var.get())
            price = int(self.price_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Neispravan unos", "Količina i cena moraju biti celi brojevi.", parent=self)
            return

        try:
            self.shop.set_stock(self.item.stock_id, quantity=quantity, unit_price_rsd=price)
        except Exception as exc:
            messagebox.showerror("Izmena nije uspela", str(exc), parent=self)
            return

        self.destroy()
        self.on_done()
