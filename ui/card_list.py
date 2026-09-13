import logging
import tkinter as tk
from tkinter import ttk

from models.card import Card
from services.image_loader import ImageLoader

logger = logging.getLogger(__name__)


class FastCardList(ttk.Frame):

    def __init__(self, parent, action_btn_text: str, action_callback, cards_per_page: int = 10, is_collection_view: bool = False):
        super().__init__(parent)
        self.action_btn_text = action_btn_text
        self.action_callback = action_callback
        self.cards_per_page = cards_per_page
        self.is_collection_view = is_collection_view
        self.current_page = 0
        self.current_cards: list[Card] = []
        
        self.preview_window = None
        self.preview_image_cache = {}

        self._build_ui()

    def _build_ui(self):
        self.nav_frame = ttk.Frame(self)
        self.nav_frame.pack(fill="x", padx=10, pady=5)

        self.btn_prev = ttk.Button(self.nav_frame, text="Prethodna", command=self._prev_page)
        self.btn_prev.pack(side="left")

        self.lbl_page = ttk.Label(self.nav_frame, text="Stranica 1", font=("Helvetica", 10, "bold"))
        self.lbl_page.pack(side="left", expand=True)

        self.btn_next = ttk.Button(self.nav_frame, text="Sledeća", command=self._next_page)
        self.btn_next.pack(side="right")

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.card_widgets = [self._create_card_widget() for _ in range(self.cards_per_page)]

    def _create_card_widget(self):
        card_frame = ttk.Frame(self.scrollable_frame, relief="ridge", borderwidth=1)

        lbl_title = ttk.Label(card_frame, font=("Helvetica", 10, "bold"), anchor="w", wraplength=750)
        lbl_title.pack(fill="x", padx=8, pady=(5, 2))

        lbl_type = ttk.Label(card_frame, font=("Helvetica", 9, "italic"), anchor="w", wraplength=750)
        lbl_type.pack(fill="x", padx=8, pady=2)

        lbl_meta = ttk.Label(card_frame, font=("Helvetica", 9), anchor="w", wraplength=750)
        lbl_meta.pack(fill="x", padx=8, pady=2)

        variants_container = ttk.Frame(card_frame)
        variants_container.pack(fill="x", padx=8, pady=5)

        box_normal = ttk.LabelFrame(variants_container, text=" Non-Foil Verzija ", padding=(8, 4))
        lbl_price_normal = ttk.Label(box_normal, font=("Helvetica", 9, "bold"), foreground="#2b5b84")
        lbl_price_normal.pack(side="left", padx=5)

        btn_normal = ttk.Button(box_normal, text=f"{self.action_btn_text} Non-Foil")
        btn_normal.pack(side="right", padx=5)

        box_foil = ttk.LabelFrame(variants_container, text="Foil Verzija", padding=(8, 4))
        lbl_price_foil = ttk.Label(box_foil, font=("Helvetica", 9, "bold"), foreground="#8e24aa")
        lbl_price_foil.pack(side="left", padx=5)

        btn_foil = ttk.Button(box_foil, text=f"{self.action_btn_text} Foil")
        btn_foil.pack(side="right", padx=5)

        return {
            "frame": card_frame,
            "title": lbl_title,
            "type": lbl_type,
            "meta": lbl_meta,
            "box_normal": box_normal,
            "lbl_price_normal": lbl_price_normal,
            "btn_normal": btn_normal,
            "box_foil": box_foil,
            "lbl_price_foil": lbl_price_foil,
            "btn_foil": btn_foil,
        }

    def _bind_hover_events(self, widget_dict, card: Card):
        def on_enter(event):
            self._show_card_preview(event, card)

        def on_leave(event):
            self._hide_card_preview()

        elements = [widget_dict["frame"], widget_dict["title"], widget_dict["type"], widget_dict["meta"]]
        for el in elements:
            el.bind("<Enter>", on_enter)
            el.bind("<Leave>", on_leave)

    def _show_card_preview(self, event, card: Card):
        image_url = getattr(card, "image_url", None)
        if not image_url:
            logger.warning(f"Kartica {getattr(card, 'name', 'Nepoznato')} nema definisan image_url.")
            return

        self._hide_card_preview()

        self.preview_window = tk.Toplevel(self)
        self.preview_window.overrideredirect(True)
        self.preview_window.attributes("-topmost", True)

        x = event.x_root + 15
        y = event.y_root + 15
        self.preview_window.geometry(f"+{x}+{y}")

        lbl_status = ttk.Label(self.preview_window, text="Učitavam sliku...", padding=10)
        lbl_status.pack()

        def set_image(photo_image, path):
            if self.preview_window and self.preview_window.winfo_exists():
                self._update_preview_image(photo_image)

        def set_error(exc=None):
            if self.preview_window and self.preview_window.winfo_exists():
                self._update_preview_error()

        # ImageLoader vraca rezultat preko self.after, pa smo vec na glavnoj niti.
        ImageLoader.load_card_image(
            image_url,
            set_image,
            size=(400, 560),
            on_error=set_error,
            schedule=self.after,
        )


    def _update_preview_image(self, photo):
        if not self.preview_window or not self.preview_window.winfo_exists():
            return
        
        for widget in self.preview_window.winfo_children():
            widget.destroy()

        if photo:
            lbl_img = ttk.Label(self.preview_window, image=photo)
            lbl_img.image = photo
            lbl_img.pack()
        else:
            self._update_preview_error()

    def _update_preview_error(self):
        if not self.preview_window or not self.preview_window.winfo_exists():
            return
        for widget in self.preview_window.winfo_children():
            widget.destroy()
        lbl_err = ttk.Label(self.preview_window, text="Slika nedostupna", padding=10)
        lbl_err.pack()

    def _hide_card_preview(self):
        if self.preview_window:
            self.preview_window.destroy()
            self.preview_window = None

    def populate(self, cards_list: list[Card]):
        self.current_cards = cards_list
        self.current_page = 0
        self._render_page()

    def _render_page(self):
        total_cards = len(self.current_cards)
        max_pages = max(1, (total_cards + self.cards_per_page - 1) // self.cards_per_page)
        start_idx = self.current_page * self.cards_per_page
        end_idx = min(start_idx + self.cards_per_page, total_cards)
        page_items = self.current_cards[start_idx:end_idx]

        self.lbl_page.config(text=f"Stranica {self.current_page + 1} od {max_pages} (Ukupno na listi: {total_cards})")
        self.btn_prev.config(state="normal" if self.current_page > 0 else "disabled")
        self.btn_next.config(state="normal" if self.current_page < max_pages - 1 else "disabled")

        for i, widget in enumerate(self.card_widgets):
            if i < len(page_items):
                card = page_items[i]
                qty = getattr(card, "quantity", 1)
                qty_text = f" (x{qty})" if qty > 0 else ""

                if self.is_collection_view:
                    foil_label = " [FOIL]" if card.is_foil else " [NON-FOIL]"
                    widget["title"].config(text=f"{card.name}{qty_text}{foil_label} (CMC: {card.cmc} | Color: {card.colors})")
                else:
                    widget["title"].config(text=f"{card.name} (CMC: {card.cmc} | Color: {card.colors})")

                widget["type"].config(text=f"Type: {card.type_line}")
                widget["meta"].config(text=f"Set: {card.set_name} | Rarity: {card.rarity} | Collector #: {card.collector_number}")

                widget["box_normal"].pack_forget()
                widget["box_foil"].pack_forget()

                if self.is_collection_view:
                    if card.is_foil:
                        widget["box_foil"].config(text=f" Foil Verzija (x{qty}) ")
                        widget["lbl_price_foil"].config(text=f"Cena: {card.price_foil}  ➔  {card.price_foil_rsd} RSD")
                        widget["btn_foil"].config(text=self.action_btn_text, command=lambda c=card: self.action_callback(c))
                        widget["box_foil"].pack(fill="x", expand=True, pady=2)
                    else:
                        widget["box_normal"].config(text=f" Non-Foil Verzija (x{qty}) ")
                        widget["lbl_price_normal"].config(text=f"Cena: {card.price_normal}  ➔  {card.price_normal_rsd} RSD")
                        widget["btn_normal"].config(text=self.action_btn_text, command=lambda c=card: self.action_callback(c))
                        widget["box_normal"].pack(fill="x", expand=True, pady=2)
                else:
                    widget["box_normal"].config(text=" Non-Foil Verzija ")
                    widget["box_foil"].config(text=" Foil Verzija ")

                    if card.price_normal_val > 0:
                        widget["lbl_price_normal"].config(text=f"Cena: {card.price_normal}  ➔  {card.price_normal_rsd} RSD")
                        widget["btn_normal"].config(text="Dodaj Non-Foil", command=lambda c=card: self.action_callback(c.clone(is_foil=False)))
                        widget["box_normal"].pack(fill="x", expand=True, pady=2)

                    if card.price_foil_val > 0:
                        widget["lbl_price_foil"].config(text=f"Cena: {card.price_foil}  ➔  {card.price_foil_rsd} RSD")
                        widget["btn_foil"].config(text="Dodaj Foil", command=lambda c=card: self.action_callback(c.clone(is_foil=True)))
                        widget["box_foil"].pack(fill="x", expand=True, pady=2)

                self._bind_hover_events(widget, card)

                widget["frame"].pack(fill="x", expand=True, padx=10, pady=5)
            else:
                widget["frame"].pack_forget()

        self.canvas.yview_moveto(0)

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._render_page()

    def _next_page(self):
        total_cards = len(self.current_cards)
        max_pages = (total_cards + self.cards_per_page - 1) // self.cards_per_page

        if self.current_page < max_pages - 1:
            self.current_page += 1
            self._render_page()