import logging
import threading
import tkinter as tk
from tkinter import Label, Toplevel, filedialog, messagebox, scrolledtext, ttk

from models.card import Card
from services.card_collection import CardCollection
from services.card_lookup import CardLookup
from services.excel_exporter import CollectionExporter
from services.excel_importer import ExcelImporter
from ui.card_list import FastCardList

logger = logging.getLogger(__name__)


def load_database_background(database, on_complete_callback):
    def worker():
        try:
            database.load_cards()
            on_complete_callback(success=True)
        except Exception as e:
            logger.error(f"Greška u pozadinskoj niti: {e}")
            on_complete_callback(success=False, error=str(e))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


class ScryfallApp:

    def __init__(self, root: tk.Tk, database: CardLookup, collection: CardCollection):
        self.root = root
        self.db = database
        self.collection = collection
        self.search_timer = None

        self._configure_root_window()
        self._build_notebook()
        self._load_initial_data()

    def _configure_root_window(self):
        self.root.title("Card Manager & Collection")
        self.root.geometry("1600x900")

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_all = ttk.Frame(self.notebook)
        self.tab_collection = ttk.Frame(self.notebook)
        self.tab_import = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_all, text="Sve Kartice")
        self.notebook.add(self.tab_collection, text="Moja Kolekcija")
        self.notebook.add(self.tab_import, text="Import Lista")

        self._setup_tab_all()
        self._setup_tab_collection()
        self._setup_tab_import()

    def _setup_tab_all(self):
        top_frame = ttk.Frame(self.tab_all)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(top_frame, text="Pretraga:").pack(side=tk.LEFT, padx=5)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)

        search_entry = ttk.Entry(top_frame, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=5)

        btn_update = ttk.Button(top_frame, text="Osveži bazu", command=self._update_database_from_scryfall)
        btn_update.pack(side=tk.RIGHT, padx=5)

        self.list_all = FastCardList(
            self.tab_all,
            action_btn_text="Dodaj",
            action_callback=self._add_to_collection,
            cards_per_page=10,
            is_collection_view=False,
        )
        self.list_all.pack(fill="both", expand=True)

    def _setup_tab_collection(self):
        file_frame = ttk.Frame(self.tab_collection)
        file_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(file_frame, text="Naziv fajla kolekcije:", font=("Helvetica", 9, "bold")).pack(side=tk.LEFT, padx=5)

        self.collection_filename_var = tk.StringVar(value="")
        entry_file = ttk.Entry(file_frame, textvariable=self.collection_filename_var, width=25)
        entry_file.pack(side=tk.LEFT, padx=5)

        btn_save_json = ttk.Button(file_frame, text="Sačuvaj u JSON", command=self._manual_save_collection_json)
        btn_save_json.pack(side=tk.LEFT, padx=5)

        btn_save_excel = ttk.Button(file_frame, text="Sačuvaj u Excel", command=self._manual_save_collection_excel)
        btn_save_excel.pack(side=tk.LEFT, padx=5)

        self.summary_box = ttk.LabelFrame(self.tab_collection, text="Ukupan Saldo Kolekcije ", padding=(12, 8))
        self.summary_box.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=8)

        self.lbl_stat_count = ttk.Label(self.summary_box, text="Primeraka: 0", font=("Helvetica", 10, "bold"))
        self.lbl_stat_count.pack(side=tk.LEFT, padx=15)

        self.lbl_stat_unique = ttk.Label(self.summary_box, text="Unikatnih: 0", font=("Helvetica", 10))
        self.lbl_stat_unique.pack(side=tk.LEFT, padx=15)

        self.lbl_stat_types = ttk.Label(self.summary_box, text="Non-Foil: 0 | Foil: 0", font=("Helvetica", 10))
        self.lbl_stat_types.pack(side=tk.LEFT, padx=15)

        self.lbl_stat_value = ttk.Label(
            self.summary_box,
            text="Ukupna Vrednost: €0.00 (~0 RSD)",
            font=("Helvetica", 11, "bold"),
            foreground="#1b5e20",
        )
        self.lbl_stat_value.pack(side=tk.RIGHT, padx=15)

        self.list_col = FastCardList(
            self.tab_collection,
            action_btn_text="Ukloni",
            action_callback=self._remove_from_collection,
            cards_per_page=10,
            is_collection_view=True,
        )
        self.list_col.pack(fill="both", expand=True)

    def _setup_tab_import(self):
        container = ttk.Frame(self.tab_import)
        container.pack(fill="both", expand=True, padx=15, pady=10)

        lbl_info = ttk.Label(
            container,
            text="Unesite tekstualnu listu kartica ILI uvezite Excel (.xlsx) fajl:\n(Excel tabela treba da sadrži kolonu sa nazivom kartice)",
            font=("Helvetica", 10, "bold"),
        )
        lbl_info.pack(anchor="w", pady=(0, 5))

        self.txt_import_input = scrolledtext.ScrolledText(container, height=12, wrap="word")
        self.txt_import_input.pack(fill="both", expand=True, pady=5)

        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill="x", pady=10)

        btn_import_text = ttk.Button(btn_frame, text="Uvezi iz teksta", command=self._import_universal_list)
        btn_import_text.pack(side="left", padx=5)

        btn_import_excel = ttk.Button(btn_frame, text="Uvezi iz Excel fajla (.xlsx)", command=self._import_from_excel_file)
        btn_import_excel.pack(side="left", padx=5)

        btn_clear = ttk.Button(
            btn_frame,
            text="Očisti tekst",
            command=lambda: self.txt_import_input.delete("1.0", tk.END),
        )
        btn_clear.pack(side="right", padx=5)

    def _load_initial_data(self):
        self.start_loading_process()

    def refresh_card_display(self):
        self.list_all.populate(self.db.all_cards())
        self._load_collection_from_input()

    def start_loading_process(self):
        self.loading_win = Toplevel(self.root)
        self.loading_win.title("Učitavanje baze")
        self.loading_win.geometry("600x400")
        self.loading_win.resizable(False, False)
        
        Label(self.loading_win, text="Učitavam Scryfall bazu karata,\nmolimo sačekajte...", pady=10).pack()
        
        progress = ttk.Progressbar(self.loading_win, mode="indeterminate", length=250)
        progress.pack(pady=5)
        progress.start(10)

        # 2. Definišemo šta se dešava kada se nit završi
        def on_loading_finished(success, error=None):
            self.loading_win.destroy()
            if success:
                self.refresh_card_display()
            else:
                messagebox.showerror("Greška", f"Došlo je do greške pri učitavanju baze:\n{error}")

        # 3. Pokrećemo pozadinsku nit
        load_database_background(self.db, on_loading_finished)

    def _add_to_collection(self, card: Card):
        self.collection.add_card(card)
        self._auto_save_collection()
        self.list_col.populate(self.collection.items)
        self._update_collection_stats()

    def _remove_from_collection(self, card: Card):
        self.collection.remove_card(card)
        self._auto_save_collection()
        self.list_col.populate(self.collection.items)
        self._update_collection_stats()

    def _on_search_changed(self, *args):
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)

        self.search_timer = self.root.after(300, self._filter_cards)

    def _filter_cards(self):
        query = self.search_var.get()
        results = self.db.search(query)
        self.list_all.populate(results)

    def _update_database_from_scryfall(self):
        confirm = messagebox.askyesno(
            "Potvrda",
            "Preuzimanje najnovijih podataka sa Scryfall-a može potrajati par minuta.\nDa li želite da nastavite?",
        )

        if not confirm:
            return

        self.loading_win = Toplevel(self.root)
        self.loading_win.title("Ažuriranje baze")
        self.loading_win.geometry("600x400")
        self.loading_win.resizable(False, False)
        
        Label(self.loading_win, text="Preuzimam sveže podatke sa Scryfall-a...", pady=10).pack()
        progress = ttk.Progressbar(self.loading_win, mode="indeterminate", length=250)
        progress.pack(pady=5)
        progress.start(10)

        def update_worker():
            try:
                success = self.db.update_from_scryfall()
                self.root.after(0, lambda: on_update_finished(success))
            except Exception as exc:
                # `exc` nestaje na kraju except bloka, pa poruku vezujemo odmah.
                message = str(exc)
                self.root.after(0, lambda: on_update_finished(False, message))

        def on_update_finished(success, error=None):
            self.loading_win.destroy()
            if success:
                messagebox.showinfo("Uspeh", "Baza je uspešno osvežena! Ponovo učitavam podatke...")
                self.refresh_card_display()
            else:
                messagebox.showerror("Greška", f"Ažuriranje baze nije uspelo: {error or 'Proverite internet konekciju.'}")

        threading.Thread(target=update_worker, daemon=True).start()

    def _import_from_excel_file(self):
        file_path = filedialog.askopenfilename(
            title="Izaberite Excel fajl sa karticama",
            filetypes=[("Excel Files", "*.xlsx *.xls"), ("All Files", "*.*")],
        )

        if not file_path:
            return

        try:
            added_count, unmatched = ExcelImporter.import_file(file_path, self.db, self.collection)

            if added_count == 0:
                messagebox.showwarning(
                    "Upozorenje",
                    "Nijedna kartica iz Excel-a nije pronađena u bazi.\n\n"
                    "Prvih nekoliko neuspešnih stavki:\n" + "\n".join(unmatched[:5]),
                )
                return

            self._auto_save_collection()
            self.list_col.populate(self.collection.items)
            self._update_collection_stats()

            msg = f"Uspešno uvezeno {added_count} kartica iz Excel fajla!"

            if unmatched:
                msg += f"\n\nNismo uspeli da pronađemo sledeće kartice ({len(unmatched)}):\n" + "\n".join(unmatched[:10])

                if len(unmatched) > 10:
                    msg += f"\n... i još {len(unmatched) - 10} drugih."

            messagebox.showinfo("Rezultat Uvoza", msg)
            self.notebook.select(self.tab_collection)

        except Exception as exc:
            messagebox.showerror("Greška", f"Došlo je do greške pri uvozu Excel fajla:\n{exc}")

    def _import_universal_list(self):
        raw_text = self.txt_import_input.get("1.0", tk.END)
        count_added, unmatched = self.collection.import_from_text(raw_text, self.db)

        if count_added == 0 and not unmatched:
            messagebox.showwarning("Upozorenje", "Nije pronađena nijedna kartica u unetom tekstu.")
            return

        self._auto_save_collection()
        self.list_col.populate(self.collection.items)
        self._update_collection_stats()

        msg = f"Uspešno dodato {count_added} kartica u kolekciju!"

        if unmatched:
            msg += f"\n\nNismo uspeli da pronađemo sledeće kartice ({len(unmatched)}):\n" + "\n".join(unmatched[:10])

            if len(unmatched) > 10:
                msg += f"\n... i još {len(unmatched) - 10} drugih."

        messagebox.showinfo("Rezultat Uvoza", msg)
        self.notebook.select(self.tab_collection)

    def _load_collection_from_input(self):
        filename = self.collection_filename_var.get().strip()

        if not filename:
            filename = "my_collection.json"
            self.collection_filename_var.set(filename)

        if not filename.endswith(".json"):
            filename += ".json"

        self.collection.load(self.db, filename)
        self.list_col.populate(self.collection.items)
        self._update_collection_stats()

    def _auto_save_collection(self):
        filename = self.collection_filename_var.get().strip()

        if not filename:
            filename = "my_collection.json"

        if not filename.endswith(".json"):
            filename += ".json"

        self.collection.save(filename)

    def _manual_save_collection_json(self):
        filename = self.collection_filename_var.get().strip()

        if not filename:
            messagebox.showwarning("Upozorenje", "Unesite naziv JSON fajla u polje!")
            return

        if not filename.endswith(".json"):
            filename += ".json"

        success, final_name = self.collection.save(filename)

        if success:
            messagebox.showinfo("Uspeh", f"Kolekcija je uspešno sačuvana u '{final_name}'!")
        else:
            messagebox.showerror("Greška", "Čuvanje kolekcije nije uspelo.")

    def _manual_save_collection_excel(self):
        user_filename = self.collection_filename_var.get().strip()

        if not user_filename.endswith(".xlsx"):
            user_filename += ".xlsx"

        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel Files", "*.xlsx")],
            initialfile=user_filename,
            title="Sačuvaj kolekciju u Excel",
        )

        if not file_path:
            return

        success, msg = CollectionExporter.export_to_excel(self.collection.items, file_path)

        if success:
            messagebox.showinfo("Uspeh", f"Kolekcija je uspešno eksportovana u Excel:\n{msg}")
        else:
            messagebox.showerror("Greška", f"Eksport u Excel nije uspeo:\n{msg}")

    def _update_collection_stats(self):
        total_cards = self.collection.get_total_count()
        unique_cards = self.collection.get_unique_count()
        normal_cards = self.collection.get_normal_count()
        foil_cards = self.collection.get_foil_count()
        total_eur = self.collection.get_total_value_eur()
        total_rsd = self.collection.get_total_value_rsd()

        self.lbl_stat_count.config(text=f"Ukupno primeraka: {total_cards}")
        self.lbl_stat_unique.config(text=f"Unikatnih kartica: {unique_cards}")
        self.lbl_stat_types.config(text=f"Non-Foil: {normal_cards} | Foil: {foil_cards}")
        self.lbl_stat_value.config(text=f"Ukupna Vrednost: €{total_eur:.2f} (~{total_rsd:,} RSD)")