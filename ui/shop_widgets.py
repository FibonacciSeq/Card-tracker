"""Mali zajednicki delovi korisnickog interfejsa za obe prodavnicke apps."""

import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import ttk

from services.image_loader import ImageLoader
from ui.dispatch import TkDispatcher


def configure_treeview_style(root: tk.Misc) -> int:
    """Podesava visinu redova prema stvarnoj velicini fonta.

    Tk-ov podrazumevani `rowheight` ne prati uvecan font na HiDPI ekranima,
    pa se tekst redova preklapa. Vracamo izracunatu visinu (za test/dijagnostiku).
    """
    style = ttk.Style(root)
    body_font = tkfont.Font(family="Helvetica", size=9)
    row_height = max(26, int(body_font.metrics("linespace")) + 10)

    style.configure("Treeview", rowheight=row_height, font=("Helvetica", 9))
    style.configure(
        "Treeview.Heading",
        font=("Helvetica", 9, "bold"),
        padding=(6, max(2, row_height // 8)),
    )
    return row_height


def fit_tree_columns(tree: ttk.Treeview, ratios: dict[str, int]) -> None:
    """Raspodeljuje sirinu kolona srazmerno, da nista ne bude odseceno desno.

    Treeview ne skuplja kolone automatski, pa na manjem prozoru poslednje
    kolone (cena, dostupno) mogu potpuno da nestanu. Ovim se sve kolone
    uvek uklapaju u trenutnu sirinu tabele.
    """
    total = sum(ratios.values()) or 1

    def on_configure(event):
        available = max(1, event.width - 4)
        for column, share in ratios.items():
            width = max(34, int(available * share / total))
            tree.column(column, width=width, stretch=False)

    tree.bind("<Configure>", on_configure, add="+")


def format_rsd(value: object) -> str:
    try:
        amount = round(float(str(value or 0)))
    except (TypeError, ValueError):
        amount = 0
    return f"{amount:,}".replace(",", ".") + " RSD"


def format_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def add_tree_scrollbar(parent, tree: ttk.Treeview) -> ttk.Scrollbar:
    scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    return scrollbar


class CardPreview(ttk.Frame):
    """Prikaz slike izabrane kartice, sa bezbednim ponistavanjem starih zahteva."""

    def __init__(self, parent, size=(220, 307), placeholder="Izaberite karticu"):
        super().__init__(parent)
        self._size = size
        self._request = 0
        self._dispatcher = TkDispatcher(self)
        self._label = ttk.Label(self, text=placeholder, anchor="center", justify="center", wraplength=200)
        self._label.pack(fill="both", expand=True, padx=4, pady=4)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_destroy(self, event: tk.Event) -> None:
        # Tk does not cancel widget.after callbacks on destroy; stop our timer
        # before the Tcl command disappears.
        if event.widget is self:
            self._dispatcher.close()

    def show(self, image_url: str | None, placeholder: str = "Slika nedostupna"):
        self._request += 1
        token = self._request
        self._label.configure(image="", text="Učitavam sliku..." if image_url else placeholder)
        self._label.image = None  # type: ignore[attr-defined]

        if not image_url:
            return

        def on_image(photo, _path):
            if token != self._request or not self.winfo_exists():
                return
            self._label.configure(image=photo, text="")
            # Tk does not keep a reference by itself; without this the image
            # can be garbage-collected and disappear from the label.
            self._label.image = photo  # type: ignore[attr-defined]

        def on_error(_exc=None):
            if token != self._request or not self.winfo_exists():
                return
            self._label.configure(image="", text=placeholder)
            self._label.image = None  # type: ignore[attr-defined]

        ImageLoader.load_card_image(
            image_url,
            on_image,
            size=self._size,
            on_error=on_error,
            schedule=self._dispatcher.post,
        )


def center_window(window: tk.Toplevel, parent: tk.Misc) -> None:
    """Postavlja dijalog priblizno u centar roditeljskog prozora."""
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
    window.geometry(f"+{x}+{y}")
