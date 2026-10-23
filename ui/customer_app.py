"""Kupacka aplikacija: pretraga celog trzista, korpa i slanje porudzbine."""

import threading
import tkinter as tk
from collections.abc import Callable
from contextlib import suppress
from tkinter import messagebox, ttk

from services.card_lookup import CardCatalog
from services.shop_database import (
    MarketItem,
    MarketKey,
    ShopDatabase,
    card_key,
    condition_label,
    market_key,
)
from ui.dispatch import TkDispatcher
from ui.shop_widgets import (
    CardPreview,
    center_window,
    configure_treeview_style,
    fit_tree_columns,
    format_rsd,
)


class CustomerApp:
    """Odvojen program za kupca. Ne menja zalihe - samo salje porudzbine."""

    PAGE_SIZE = 200
    MAX_CART_QUANTITY = 999

    def __init__(self, root: tk.Tk, catalog: CardCatalog, shop: ShopDatabase):
        self.root = root
        self.catalog = catalog
        self.shop = shop
        self.cart: dict[MarketKey, int] = {}
        self.cart_items: dict[MarketKey, MarketItem] = {}
        self.market_by_index: dict[int, MarketItem] = {}
        self.visible_by_key: dict[MarketKey, MarketItem] = {}
        self._cart_keys: list[MarketKey] = []
        self._catalog_ready = False
        self._catalog_limit = self.PAGE_SIZE
        self._catalog_total = 0
        self._search_job: str | None = None
        self._dispatcher = TkDispatcher(self.root)
        self.root.bind("<Destroy>", self._on_root_destroy, add="+")

        self._configure_root()
        self._build_header()
        self._build_body()
        self._render_cart()
        self._start_catalog_load()

    # ------------------------------------------------------------------ setup

    def _on_root_destroy(self, event: tk.Event) -> None:
        if event.widget is self.root:
            self._dispatcher.close()

    def _configure_root(self):
        self.root.title("Card Tracker — Kupac")

        # 30% veci prozor od prvobitnog 1440x860, ali nikad veci od ekrana.
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(1872, max(1100, int(screen_width * 0.9)))
        height = min(1118, max(700, int(screen_height * 0.9)))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(1350, width), min(800, height))
        configure_treeview_style(self.root)

    def _build_header(self):
        header = ttk.Frame(self.root, padding=(16, 12, 16, 6))
        header.pack(fill=tk.X)

        title_box = ttk.Frame(header)
        title_box.pack(side=tk.LEFT)

        ttk.Label(title_box, text="Prodavnica karata", font=("Helvetica", 18, "bold")).pack(anchor="w")
        ttk.Label(
            title_box,
            text="Pretražite ceo katalog. Kartice kojih nema na stanju možete poručiti kod dobavljača.",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 0))

        self.catalog_status_var = tk.StringVar(value="Katalog: učitava se...")
        ttk.Label(header, textvariable=self.catalog_status_var, foreground="#555555").pack(side=tk.RIGHT, padx=8)
        ttk.Button(header, text="Osveži ponudu", command=self._refresh_clicked).pack(side=tk.RIGHT, padx=4)

    def _build_body(self):
        self.paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        left = ttk.Frame(self.paned)
        right = ttk.Frame(self.paned)
        self.paned.add(left, weight=3)
        self.paned.add(right, weight=2)

        self._build_market_panel(left)
        self._build_cart_panel(right)
        self.root.after(150, self._fit_initial_layout)

    def _fit_initial_layout(self):
        """Daje ponudi vise prostora od korpe pri prvom otvaranju."""
        if not self.paned.winfo_exists():
            return

        self.paned.update_idletasks()
        total = self.paned.winfo_width()
        if total <= 1:
            return
        with suppress(tk.TclError):
            self.paned.sashpos(0, int(total * 0.6))

    def _build_market_panel(self, parent):
        search_box = ttk.Frame(parent)
        search_box.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(search_box, text="Pretraga tržišta:", font=("Helvetica", 10, "bold")).pack(side=tk.LEFT, padx=(0, 6))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        self.search_entry = ttk.Entry(search_box, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        info_row = ttk.Frame(parent)
        info_row.pack(fill=tk.X, pady=(0, 4))

        self.market_info_var = tk.StringVar(value="Učitavam katalog...")
        ttk.Label(info_row, textvariable=self.market_info_var, foreground="#555555").pack(side=tk.LEFT)

        self.load_more_button = ttk.Button(
            info_row,
            text="Prikaži još",
            command=self._load_more,
            state="disabled",
        )
        self.load_more_button.pack(side=tk.RIGHT)

        content = ttk.Frame(parent)
        content.pack(fill=tk.BOTH, expand=True)

        tree_box = ttk.Frame(content)
        tree_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        columns = ("name", "set", "number", "foil", "condition", "price", "available")
        self.market_tree = ttk.Treeview(tree_box, columns=columns, show="headings", selectmode="browse")
        headings = {
            "name": ("Kartica", 200),
            "set": ("Set", 120),
            "number": ("Br.", 45),
            "foil": ("Verzija", 55),
            "condition": ("Stanje", 60),
            "price": ("Cena", 80),
            "available": ("Dostupno", 65),
        }
        for key, (label, width) in headings.items():
            self.market_tree.heading(key, text=label)
            anchor = tk.E if key in ("price", "available") else (tk.CENTER if key in ("number", "foil") else tk.W)
            self.market_tree.column(  # type: ignore[call-overload]
                key, width=width, anchor=anchor, stretch=key in ("name", "set")
            )

        self.market_tree.tag_configure("foil", foreground="#8e24aa")
        self.market_tree.tag_configure("out_of_stock", foreground="#9e9e9e")
        self.market_tree.bind("<<TreeviewSelect>>", self._on_market_select)
        self.market_tree.bind("<Double-1>", lambda _event: self._add_selected(quantity_limit=1))
        fit_tree_columns(
            self.market_tree,
            {
                "name": 32,
                "set": 12,
                "number": 5,
                "foil": 9,
                "condition": 7,
                "price": 17,
                "available": 18,
            },
        )
        self.market_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(tree_box, orient="vertical", command=self.market_tree.yview)
        self.market_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        preview_box = ttk.LabelFrame(content, text=" Pregled ", padding=4)
        preview_box.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self.preview = CardPreview(preview_box, size=(220, 307))
        self.preview.pack(fill=tk.BOTH, expand=True)

        add_box = ttk.Frame(parent)
        add_box.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(add_box, text="Količina:").pack(side=tk.LEFT, padx=(0, 4))
        self.quantity_var = tk.IntVar(value=1)
        ttk.Spinbox(add_box, from_=1, to=999, width=5, textvariable=self.quantity_var).pack(side=tk.LEFT)

        self.add_button = ttk.Button(
            add_box,
            text="Dodaj u porudžbinu",
            command=self._add_selected,
            state="disabled",
        )
        self.add_button.pack(side=tk.LEFT, padx=8)

        self.selected_var = tk.StringVar(value="")
        ttk.Label(add_box, textvariable=self.selected_var, foreground="#555555").pack(side=tk.LEFT, padx=8)

    def _build_cart_panel(self, parent):
        cart_box = ttk.LabelFrame(parent, text=" Vaša porudžbina ", padding=8)
        cart_box.pack(fill=tk.BOTH, expand=True)

        columns = ("name", "foil", "condition", "quantity", "availability", "price", "subtotal")
        self.cart_tree = ttk.Treeview(cart_box, columns=columns, show="headings", selectmode="browse")
        headings = {
            "name": ("Kartica", 145),
            "foil": ("Verzija", 62),
            "condition": ("Stanje", 52),
            "quantity": ("Kol.", 42),
            "availability": ("Dostupnost", 95),
            "price": ("Cena", 80),
            "subtotal": ("Ukupno", 85),
        }
        for key, (label, width) in headings.items():
            self.cart_tree.heading(key, text=label)
            anchor = tk.E if key in ("price", "subtotal") else (tk.CENTER if key in ("quantity", "foil") else tk.W)
            self.cart_tree.column(  # type: ignore[call-overload]
                key, width=width, anchor=anchor, stretch=key == "name"
            )

        self.cart_tree.tag_configure("backorder", foreground="#b26a00")
        fit_tree_columns(
            self.cart_tree,
            {
                "name": 38,
                "foil": 8,
                "condition": 7,
                "quantity": 6,
                "availability": 14,
                "price": 13,
                "subtotal": 14,
            },
        )

        self.cart_tree.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(cart_box)
        controls.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(controls, text="−", width=3, command=lambda: self._change_cart_quantity(-1)).pack(  # noqa: RUF001
            side=tk.LEFT
        )
        ttk.Button(controls, text="+", width=3, command=lambda: self._change_cart_quantity(1)).pack(
            side=tk.LEFT, padx=(4, 8)
        )
        ttk.Button(controls, text="Ukloni", command=self._remove_from_cart).pack(side=tk.LEFT)

        total_box = ttk.Frame(cart_box)
        total_box.pack(fill=tk.X, pady=(12, 0))

        ttk.Label(total_box, text="Ukupno za porudžbinu:", font=("Helvetica", 11, "bold")).pack(side=tk.LEFT)
        self.total_var = tk.StringVar(value=format_rsd(0))
        ttk.Label(
            total_box,
            textvariable=self.total_var,
            font=("Helvetica", 14, "bold"),
            foreground="#1b5e20",
        ).pack(side=tk.RIGHT)

        ttk.Button(cart_box, text="Nastavi na poručivanje", command=self._checkout).pack(fill=tk.X, pady=(12, 0))

        ttk.Label(
            cart_box,
            text="Cene su u dinarima. Kartice kojih trenutno nema na stanju biće\n"
            "poručene kod dobavljača. Prodavac vas kontaktira na podatke iz sledećeg koraka.",
            foreground="#666666",
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(8, 0))

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
        center_window(self.loading_window, self.root)

        self.search_entry.config(state="disabled")
        self.add_button.config(state="disabled")

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

        self.search_entry.config(state="normal")
        self.add_button.config(state="normal")
        if not success:
            self._catalog_ready = False
            self.catalog_status_var.set("Katalog nije učitan")
            self.market_info_var.set("Katalog nije učitan; prikazujem samo trenutne zalihe.")
            messagebox.showerror("Katalog", f"Katalog nije mogao da se učita:\n{error}")
            self.refresh_market(reset=True)
            return

        self._catalog_ready = True
        try:
            count = self.catalog.count()
        except Exception:
            count = 0
        self.catalog_status_var.set(f"Katalog: {count:,} kartica".replace(",", "."))
        self.refresh_market(reset=True)

    def _on_search_changed(self, *_args):
        if self._search_job is not None:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(300, lambda: self.refresh_market(reset=True))

    def _refresh_clicked(self):
        self.refresh_market(reset=True)

    def _load_more(self):
        if self._catalog_total <= self._catalog_limit:
            return
        self._catalog_limit += self.PAGE_SIZE
        self.refresh_market(reset=False)

    def refresh_market(self, *, reset: bool = False):
        if self._search_job is not None:
            with suppress(tk.TclError):
                self.root.after_cancel(self._search_job)
            self._search_job = None
        if reset:
            self._catalog_limit = self.PAGE_SIZE

        selected_key = self._selected_market_item_key()
        query = self.search_var.get().strip()

        try:
            stock_items = self.shop.list_stock()
        except Exception as exc:
            messagebox.showerror("Ponuda", f"Zalihe nisu mogle da se učitaju:\n{exc}")
            return

        cards = []
        total = 0
        if self._catalog_ready:
            try:
                result = self.catalog.search(query)
                total = len(result)
                cards = list(result[: self._catalog_limit])
            except Exception as exc:
                messagebox.showerror("Katalog", f"Pretraga kataloga nije uspela:\n{exc}")
                return

        stock_by_key: dict[MarketKey, MarketItem] = {}
        for stock in stock_items:
            market = MarketItem.from_stock(stock)
            stock_by_key[market.key] = market

        rows: list[MarketItem] = []
        seen: set[MarketKey] = set()
        catalog_card_keys = {card_key(card) for card in cards}
        for card in cards:
            for is_foil in (False, True):
                if (
                    is_foil
                    and getattr(card, "price_foil_rsd", 0) <= 0
                    and market_key(card, is_foil=True) not in stock_by_key
                ):
                    continue
                market = MarketItem.from_card(card, is_foil=is_foil)
                key = market.key
                if key in seen:
                    continue
                seen.add(key)
                rows.append(stock_by_key.pop(key, market))

        for item in stock_by_key.values():
            if item.card_key in catalog_card_keys or not query or self._stock_matches(item, query):
                rows.append(item)

        self.market_by_index = dict(enumerate(rows))
        self.visible_by_key = {item.key: item for item in rows}
        self._catalog_total = total

        self.market_tree.delete(*self.market_tree.get_children())
        for index, item in enumerate(rows):
            if item.stock_id is None or item.available <= 0:
                tags: tuple[str, ...] = ("out_of_stock",)
            elif item.is_foil:
                tags = ("foil",)
            else:
                tags = ()

            self.market_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    item.name,
                    item.set_name,
                    item.collector_number,
                    item.foil_label,
                    item.condition_code,
                    format_rsd(item.unit_price_rsd),
                    item.available,
                ),
                tags=tags,
            )

        shown = len(cards)
        if total:
            info = f"Prikazano {shown:,} od {total:,} kartica".replace(",", ".")
        else:
            info = "Katalog nije dostupan" if not self._catalog_ready else "Nema rezultata u katalogu"
        self.market_info_var.set(f"{info} · {len(rows):,} stavki u ponudi".replace(",", "."))
        self.load_more_button.config(state="normal" if total > shown else "disabled")

        for key in list(self.cart):
            if key in self.visible_by_key:
                self.cart_items[key] = self.visible_by_key[key]
        self._render_cart()

        if selected_key is not None:
            for index, item in enumerate(rows):
                if item.key == selected_key:
                    self.market_tree.selection_set(str(index))
                    self.market_tree.see(str(index))
                    self._on_market_select()
                    break
            else:
                self._clear_preview()
        else:
            self._clear_preview()

    # --------------------------------------------------------------- market

    @staticmethod
    def _stock_matches(item: MarketItem, query: str) -> bool:
        haystack = f"{item.name} {item.set_name} {item.set_code} {item.collector_number}".lower()
        return query.lower() in haystack

    def _selected_market_item(self) -> MarketItem | None:
        selection = self.market_tree.selection()
        if not selection:
            return None
        return self.market_by_index.get(int(selection[0]))

    def _selected_market_item_key(self) -> MarketKey | None:
        item = self._selected_market_item()
        return item.key if item else None

    def _on_market_select(self, _event=None):
        item = self._selected_market_item()
        if not item:
            self._clear_preview()
            return

        self.preview.show(item.image_url, "Slika nedostupna")
        availability = f"{item.available} dostupno" if item.available else "nema na stanju — po narudžbini"
        self.selected_var.set(
            f"{item.name} — {item.foil_label}, {condition_label(item.condition_code)}: "
            f"{format_rsd(item.unit_price_rsd)} · {availability}"
        )

    def _clear_preview(self):
        self.preview.show(None, "Izaberite karticu")
        self.selected_var.set("")

    def _add_selected(self, quantity_limit: int | None = None):
        item = self._selected_market_item()
        if not item:
            messagebox.showwarning("Izbor", "Prvo izaberite karticu sa liste.")
            return

        already = self.cart.get(item.key, 0)
        try:
            quantity = int(self.quantity_var.get())
        except (tk.TclError, ValueError):
            quantity = 1
        if quantity_limit is not None:
            quantity = quantity_limit
        quantity = max(1, quantity)

        remaining = self.MAX_CART_QUANTITY - already
        if remaining <= 0:
            messagebox.showinfo(
                "Količina",
                f"Najviše {self.MAX_CART_QUANTITY} primeraka iste kartice može biti u jednoj porudžbini.",
            )
            return
        quantity = min(quantity, remaining)

        self.cart[item.key] = already + quantity
        self.cart_items[item.key] = item
        self.quantity_var.set(1)
        self._render_cart()

    # ------------------------------------------------------------------- cart

    @staticmethod
    def _cart_order_key(item: MarketItem):
        return item.name.lower(), item.set_name.lower(), item.collector_number, item.is_foil, item.condition_code

    @staticmethod
    def _availability_label(item: MarketItem, quantity: int) -> str:
        if item.available <= 0:
            return "Po narudžbini"
        if quantity > item.available:
            return "Delimično"
        return "Na stanju"

    def _render_cart(self):
        self.cart_tree.delete(*self.cart_tree.get_children())
        self._cart_keys = sorted(self.cart, key=lambda key: self._cart_order_key(self.cart_items[key]))

        total = 0
        for index, key in enumerate(self._cart_keys):
            item = self.cart_items[key]
            quantity = self.cart[key]
            subtotal = item.unit_price_rsd * quantity
            availability = self._availability_label(item, quantity)
            total += subtotal
            self.cart_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    item.name,
                    item.foil_label,
                    item.condition_code,
                    quantity,
                    availability,
                    format_rsd(item.unit_price_rsd),
                    format_rsd(subtotal),
                ),
                tags=("backorder",) if availability != "Na stanju" else (),
            )

        self.total_var.set(format_rsd(total))

    def _selected_cart_item(self) -> tuple[MarketKey, MarketItem] | None:
        selection = self.cart_tree.selection()
        if not selection:
            messagebox.showwarning("Izbor", "Izaberite stavku u porudžbini.")
            return None
        index = int(selection[0])
        if not (0 <= index < len(self._cart_keys)):
            return None
        key = self._cart_keys[index]
        return key, self.cart_items[key]

    def _change_cart_quantity(self, delta: int):
        selected = self._selected_cart_item()
        if selected is None:
            return
        key, _item = selected

        current = self.cart.get(key, 0)
        new_quantity = current + delta

        if new_quantity <= 0:
            self.cart.pop(key, None)
            self.cart_items.pop(key, None)
        elif new_quantity > self.MAX_CART_QUANTITY:
            messagebox.showinfo(
                "Količina",
                f"Najviše {self.MAX_CART_QUANTITY} primeraka iste kartice može biti u jednoj porudžbini.",
            )
            return
        else:
            self.cart[key] = new_quantity

        self._render_cart()

    def _remove_from_cart(self):
        selected = self._selected_cart_item()
        if selected is None:
            return
        key, _item = selected
        self.cart.pop(key, None)
        self.cart_items.pop(key, None)
        self._render_cart()

    # --------------------------------------------------------------- checkout

    def _checkout(self):
        if not self.cart:
            messagebox.showwarning("Prazna porudžbina", "Dodajte bar jednu karticu u porudžbinu.")
            return

        CheckoutDialog(self.root, self._submit_order)

    def _submit_order(self, contact: dict[str, str]) -> tuple[bool, str]:
        ordered_items = [(self.cart_items[key], quantity) for key, quantity in self.cart.items()]
        has_backorder = any(quantity > item.available for item, quantity in ordered_items)
        try:
            order_id = self.shop.create_market_order(
                customer_name=contact["name"],
                email=contact["email"],
                phone=contact["phone"],
                note=contact["note"],
                items=ordered_items,
            )
        except Exception as exc:
            return False, str(exc)

        order = self.shop.get_order(order_id)
        total = format_rsd(order.total_rsd if order else 0)

        self.cart.clear()
        self.cart_items.clear()
        self._render_cart()
        self.refresh_market(reset=True)

        message = (
            f"Porudžbina #{order_id} je poslata prodavcu.\n\n"
            f"Ukupno: {total}\n"
            "Prodavac će vas kontaktirati na ostavljene podatke."
        )
        if has_backorder:
            message += "\n\nKartice kojih nije bilo na stanju biće poručene kod dobavljača."
        return True, message


class CheckoutDialog(tk.Toplevel):
    """Prikuplja kontakt pre nego sto se porudzbina posalje."""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        on_submit: Callable[[dict[str, str]], tuple[bool, str]],
    ):
        super().__init__(parent)
        self.on_submit = on_submit
        self.title("Podaci za kontakt")
        self.resizable(False, False)
        self.transient(parent)

        self._build()
        self.grab_set()
        self.bind("<Escape>", lambda _event: self.destroy())
        center_window(self, parent)

    def _build(self):
        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(body, text="Kako da vas prodavac kontaktira?", font=("Helvetica", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            body,
            text="Ime je obavezno, a ostavite bar e-mail ili telefon.",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.name_var = tk.StringVar()
        self.email_var = tk.StringVar()
        self.phone_var = tk.StringVar()

        self.name_entry = self._field(body, 2, "Ime i prezime *", self.name_var)
        self._field(body, 3, "E-mail", self.email_var)
        self._field(body, 4, "Telefon", self.phone_var)

        ttk.Label(body, text="Napomena").grid(row=5, column=0, sticky="nw", padx=(0, 10), pady=6)
        self.note_text = tk.Text(body, height=4, width=42, wrap="word")
        self.note_text.grid(row=5, column=1, sticky="ew", pady=6)

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Otkaži", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Pošalji porudžbinu", command=self._submit).pack(side=tk.RIGHT, padx=(0, 8))

        body.columnconfigure(1, weight=1)
        self.name_var.set("")
        self.after(50, self.name_entry.focus_set)

    @staticmethod
    def _field(parent: tk.Misc, row: int, label: str, variable: tk.StringVar) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6)
        entry = ttk.Entry(parent, textvariable=variable, width=44)
        entry.grid(row=row, column=1, sticky="ew", pady=6)
        return entry

    def _submit(self):
        contact = {
            "name": self.name_var.get().strip(),
            "email": self.email_var.get().strip(),
            "phone": self.phone_var.get().strip(),
            "note": self.note_text.get("1.0", tk.END).strip(),
        }

        success, message = self.on_submit(contact)
        if success:
            messagebox.showinfo("Porudžbina poslata", message, parent=self)
            self.destroy()
        else:
            messagebox.showerror("Porudžbina nije poslata", message, parent=self)
