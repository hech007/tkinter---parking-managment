import csv
import json
import math
import os
import re
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

# Data file is stored next to this script, so it works from any folder.
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "parking_data.json")

# Default hourly charge per started hour (in rupees). Admin can change these.
DEFAULT_RATES = {"Car": 30, "SUV": 40, "Two-Wheeler": 15}
VEHICLE_TYPES = list(DEFAULT_RATES)

DEFAULT_CAPACITY = {"Car": 10, "Bike": 10}
SLOT_PREFIX = {"Car": "C", "Bike": "B"}
ZONE_OF = {"Car": "Car", "SUV": "Car", "Two-Wheeler": "Bike"}
ZONE_TITLE = {"Car": "CAR / SUV PARKING ZONE", "Bike": "TWO-WHEELER PARKING ZONE"}

MAX_SLOTS = 300

# Colours
BG = "#f3f5f9"
NAVY = "#1f2a44"
FREE_BG, FREE_BORDER = "#c9f1d2", "#2e9e4f"
OCC_BG, OCC_BORDER = "#f8b9b9", "#c0392b"


# ---------------------------------------------------------------- helpers

def parse_time(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return datetime.now()


def fmt_dt(dt):
    return dt.strftime("%d-%m-%Y %I:%M %p")


def fmt_duration(seconds):
    hours, rem = divmod(int(max(0, seconds)), 3600)
    return f"{hours}h {rem // 60:02d}m"


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable container (used so large zones never overflow)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=BG)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.inner,
                                                 anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(sequence, self._on_wheel, add="+")

    def _on_wheel(self, event):
        if not self.winfo_ismapped():      # only scroll while this tab is visible
            return
        if event.num == 4:
            step = -1
        elif event.num == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")


# -------------------------------------------------------------- main class

class SmartParkingSystem:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Parking Management System")
        self.root.geometry("1100x780")
        self.root.minsize(950, 650)
        self.root.configure(bg=BG)

        self.slots = {}
        self.vehicles = {}
        self.rates = dict(DEFAULT_RATES)
        self.history = []
        self.pending_checkout = None
        self.selected_slot = None

        self.load_data()
        self.setup_style()
        self.build_interface()
        self.refresh_all()
        self.tick_clock()
        self.periodic_refresh()

    # ------------------------------------------------------------- style

    def setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BG, font=("Arial", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG)
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG,
                        font=("Arial", 11, "bold"), foreground=NAVY)
        style.configure("Title.TLabel", font=("Arial", 20, "bold"),
                        foreground="white", background=NAVY)
        style.configure("Clock.TLabel", font=("Arial", 10),
                        foreground="#c9d3ea", background=NAVY)
        style.configure("Heading.TLabel", font=("Arial", 13, "bold"),
                        foreground=NAVY)
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("TButton", padding=7)
        style.configure("Accent.TButton", padding=8, font=("Arial", 10, "bold"),
                        background="#2563eb", foreground="white")
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])
        style.configure("Danger.TButton", padding=7,
                        background="#dc2626", foreground="white")
        style.map("Danger.TButton", background=[("active", "#b91c1c")])
        style.configure("TNotebook.Tab", padding=(16, 8),
                        font=("Arial", 10, "bold"))
        style.configure("Treeview", rowheight=28, font=("Arial", 10))
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"))

    # ------------------------------------------------------ data storage

    def load_data(self):
        self.slots = {
            zone: [f"{SLOT_PREFIX[zone]}{i:02d}"
                   for i in range(1, DEFAULT_CAPACITY[zone] + 1)]
            for zone in SLOT_PREFIX
        }
        self.vehicles = {}
        self.rates = dict(DEFAULT_RATES)
        self.history = []

        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, "r") as file:
                data = json.load(file)

            saved_slots = data.get("slots", {})
            for zone in self.slots:
                if isinstance(saved_slots.get(zone), list):
                    self.slots[zone] = saved_slots[zone]

            if isinstance(data.get("vehicles"), dict):
                self.vehicles = data["vehicles"]

            saved_rates = data.get("rates", {})
            for vtype in self.rates:
                try:
                    value = int(saved_rates[vtype])
                    if value > 0:
                        self.rates[vtype] = value
                except (KeyError, TypeError, ValueError):
                    pass

            if isinstance(data.get("history"), list):
                self.history = data["history"]
        except (json.JSONDecodeError, OSError, AttributeError):
            # Keep the unreadable file instead of silently overwriting it.
            try:
                os.replace(DATA_FILE, DATA_FILE + ".corrupt")
            except OSError:
                pass
            messagebox.showwarning(
                "Data File Problem",
                "The saved data file could not be read. It was renamed to "
                "'parking_data.json.corrupt' and a fresh start was made.")

    def save_data(self):
        data = {
            "slots": self.slots,
            "vehicles": self.vehicles,
            "rates": self.rates,
            "history": self.history,
        }
        temp_file = DATA_FILE + ".tmp"
        try:
            with open(temp_file, "w") as file:
                json.dump(data, file, indent=4)
            os.replace(temp_file, DATA_FILE)      # atomic: never a half-written file
        except OSError as error:
            messagebox.showerror("Save Error", f"Could not save data:\n{error}")

    # ------------------------------------------------------ small helpers

    @staticmethod
    def normalise(text):
        return re.sub(r"[\s\-]", "", text).upper()

    def occupied_map(self):
        """slot id -> vehicle number. (Vehicles are keyed by number, not slot.)"""
        return {d["slot"]: number for number, d in self.vehicles.items()}

    def compute_charge(self, details, end_time):
        entry = parse_time(details["entry_time"])
        seconds = max(0, (end_time - entry).total_seconds())
        hours = max(1, math.ceil(seconds / 3600))
        rate = self.rates.get(details["vehicle_type"],
                              DEFAULT_RATES.get(details["vehicle_type"], 0))
        return entry, seconds, hours, rate, hours * rate

    def set_status(self, message):
        self.status_var.set(message)

    def today_revenue(self):
        today = datetime.now().date()
        return sum(r.get("amount", 0) for r in self.history
                   if parse_time(r.get("exit_time")).date() == today)

    def refresh_all(self):
        self.refresh_dashboard()
        self.refresh_entry_info()
        self.refresh_history()

    # ------------------------------------------------------- main window

    def build_interface(self):
        header = tk.Frame(self.root, bg=NAVY, padx=16, pady=10)
        header.pack(fill="x")
        ttk.Label(header, text="SMART PARKING MANAGEMENT SYSTEM",
                  style="Title.TLabel").pack(side="left")
        self.clock_label = ttk.Label(header, text="", style="Clock.TLabel")
        self.clock_label.pack(side="right")

        self.status_var = tk.StringVar(value="Ready.")
        status = ttk.Label(self.root, textvariable=self.status_var,
                           relief="sunken", anchor="w", padding=(10, 4))
        status.pack(side="bottom", fill="x")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=8)

        self.dashboard_tab = ttk.Frame(self.notebook, padding=12)
        self.entry_tab = ttk.Frame(self.notebook, padding=18)
        self.exit_tab = ttk.Frame(self.notebook, padding=18)
        self.history_tab = ttk.Frame(self.notebook, padding=12)
        self.admin_tab = ttk.Frame(self.notebook, padding=18)

        self.notebook.add(self.dashboard_tab, text="Live Slot Dashboard")
        self.notebook.add(self.entry_tab, text="Vehicle Entry")
        self.notebook.add(self.exit_tab, text="Vehicle Exit")
        self.notebook.add(self.history_tab, text="History & Revenue")
        self.notebook.add(self.admin_tab, text="Admin Settings")

        self.build_dashboard()
        self.build_entry_tab()
        self.build_exit_tab()
        self.build_history_tab()
        self.build_admin_tab()

    def tick_clock(self):
        self.clock_label.config(
            text=datetime.now().strftime("%A, %d %B %Y   %I:%M:%S %p"))
        self.root.after(1000, self.tick_clock)

    def periodic_refresh(self):
        """Keeps the selected slot's duration and charge up to date."""
        if self.selected_slot:
            self.show_slot_details(self.selected_slot)
        self.root.after(30000, self.periodic_refresh)

    # --------------------------------------------------------- dashboard

    def make_card(self, parent, title, colour):
        card = tk.Frame(parent, bg=colour, padx=18, pady=8)
        card.pack(side="left", padx=(0, 10))
        value = tk.Label(card, text="0", font=("Arial", 20, "bold"),
                         bg=colour, fg="white")
        value.pack()
        tk.Label(card, text=title, font=("Arial", 9), bg=colour,
                 fg="white").pack()
        return value

    def build_dashboard(self):
        cards = ttk.Frame(self.dashboard_tab)
        cards.pack(fill="x", pady=(0, 10))
        self.total_value = self.make_card(cards, "TOTAL SLOTS", "#475569")
        self.occupied_value = self.make_card(cards, "OCCUPIED", "#dc2626")
        self.available_value = self.make_card(cards, "AVAILABLE", "#16a34a")
        self.revenue_value = self.make_card(cards, "TODAY'S REVENUE", "#2563eb")

        legend = ttk.Frame(self.dashboard_tab)
        legend.pack(fill="x", pady=(0, 6))
        tk.Label(legend, text="  FREE  ", bg=FREE_BG, relief="solid", bd=1,
                 font=("Arial", 9, "bold")).pack(side="left", padx=(0, 6))
        tk.Label(legend, text="  OCCUPIED  ", bg=OCC_BG, relief="solid", bd=1,
                 font=("Arial", 9, "bold")).pack(side="left", padx=(0, 12))
        ttk.Label(legend, text="Click a slot for details. Double-click an "
                               "occupied slot to check it out.",
                  style="Hint.TLabel").pack(side="left")

        scroller = ScrollableFrame(self.dashboard_tab)
        scroller.pack(fill="both", expand=True)

        self.zone_widgets = {}
        for zone in ("Car", "Bike"):
            frame = ttk.LabelFrame(scroller.inner, text=ZONE_TITLE[zone],
                                   padding=10)
            frame.pack(fill="x", pady=6, padx=(0, 6))

            top = ttk.Frame(frame)
            top.pack(fill="x", pady=(0, 8))
            bar = ttk.Progressbar(top, length=260, maximum=100)
            bar.pack(side="left")
            label = ttk.Label(top, text="")
            label.pack(side="left", padx=10)

            grid = ttk.Frame(frame)
            grid.pack(anchor="w")
            self.zone_widgets[zone] = {"bar": bar, "label": label, "grid": grid}

        self.slot_info = tk.StringVar(value="No slot selected.")
        info = ttk.Label(self.dashboard_tab, textvariable=self.slot_info,
                         relief="groove", anchor="w", padding=8)
        info.pack(fill="x", pady=(8, 0))

    def draw_slot_grid(self, zone):
        parent = self.zone_widgets[zone]["grid"]
        for widget in parent.winfo_children():
            widget.destroy()

        occupied = self.occupied_map()
        columns = 6
        for index, slot_id in enumerate(self.slots[zone]):
            number = occupied.get(slot_id)
            if number:
                bg, border = OCC_BG, OCC_BORDER
                text = f"{slot_id}\n{number}"
            else:
                bg, border = FREE_BG, FREE_BORDER
                text = f"{slot_id}\nFREE"

            tile = tk.Label(
                parent, text=text, width=14, height=3, bg=bg, fg="black",
                relief="raised", bd=2, highlightthickness=2,
                highlightbackground=border, font=("Arial", 9, "bold"),
                cursor="hand2")
            tile.grid(row=index // columns, column=index % columns,
                      padx=5, pady=5)
            tile.bind("<Button-1>",
                      lambda e, s=slot_id: self.show_slot_details(s))
            tile.bind("<Double-Button-1>",
                      lambda e, s=slot_id: self.slot_double_click(s))

    def show_slot_details(self, slot_id):
        self.selected_slot = slot_id
        number = self.occupied_map().get(slot_id)
        if number is None:
            self.slot_info.set(f"Slot {slot_id} is free.")
            return
        details = self.vehicles[number]
        entry, seconds, hours, rate, amount = self.compute_charge(
            details, datetime.now())
        self.slot_info.set(
            f"Slot {slot_id}  |  {number}  |  {details['vehicle_type']}  |  "
            f"In: {fmt_dt(entry)}  |  Parked: {fmt_duration(seconds)}  |  "
            f"Charge so far: Rs. {amount}")

    def slot_double_click(self, slot_id):
        number = self.occupied_map().get(slot_id)
        if number:
            self.go_to_checkout(number)

    def refresh_dashboard(self):
        total = sum(len(v) for v in self.slots.values())
        occupied = len(self.vehicles)
        self.total_value.config(text=str(total))
        self.occupied_value.config(text=str(occupied))
        self.available_value.config(text=str(max(0, total - occupied)))
        self.revenue_value.config(text=f"Rs. {self.today_revenue()}")

        occupied_slots = self.occupied_map()
        for zone in ("Car", "Bike"):
            slots = self.slots[zone]
            used = sum(1 for s in slots if s in occupied_slots)
            widgets = self.zone_widgets[zone]
            widgets["bar"]["value"] = (used / len(slots) * 100) if slots else 0
            widgets["label"].config(
                text=f"{used} occupied / {len(slots)} total "
                     f"({len(slots) - used} free)")
            self.draw_slot_grid(zone)

        if self.selected_slot:
            self.show_slot_details(self.selected_slot)

    # ----------------------------------------------------- vehicle entry

    def build_entry_tab(self):
        ttk.Label(self.entry_tab, text="VEHICLE CHECK-IN",
                  style="Heading.TLabel").pack(anchor="w", pady=(0, 15))

        form = ttk.Frame(self.entry_tab)
        form.pack(anchor="w")

        ttk.Label(form, text="Vehicle Number:").grid(
            row=0, column=0, sticky="w", padx=8, pady=10)
        self.entry_number = ttk.Entry(form, width=28)
        self.entry_number.grid(row=0, column=1, padx=8, pady=10)
        self.entry_number.bind("<Return>", lambda e: self.check_in())

        ttk.Label(form, text="Vehicle Type:").grid(
            row=1, column=0, sticky="w", padx=8, pady=10)
        self.entry_type = ttk.Combobox(form, values=VEHICLE_TYPES,
                                       state="readonly", width=25)
        self.entry_type.current(0)
        self.entry_type.grid(row=1, column=1, padx=8, pady=10)
        self.entry_type.bind("<<ComboboxSelected>>",
                             lambda e: self.refresh_entry_info())

        self.rate_hint = ttk.Label(form, text="", style="Hint.TLabel")
        self.rate_hint.grid(row=2, column=1, sticky="w", padx=8)

        ttk.Button(form, text="Check In Vehicle", style="Accent.TButton",
                   command=self.check_in).grid(
            row=3, column=1, sticky="w", padx=8, pady=18)

        self.zone_status = ttk.Label(self.entry_tab, text="",
                                     font=("Arial", 10, "bold"))
        self.zone_status.pack(anchor="w", pady=(10, 4))

        ttk.Label(
            self.entry_tab,
            text=("Cars and SUVs are assigned to the Car Zone. Two-Wheelers "
                  "are assigned to the Bike Zone.\nThe system assigns the "
                  "first available slot in that zone. Spaces and hyphens in "
                  "the vehicle number are ignored."),
            wraplength=750, style="Hint.TLabel").pack(anchor="w", pady=8)

        self.entry_result = ttk.Label(self.entry_tab, text="",
                                      font=("Arial", 11, "bold"))
        self.entry_result.pack(anchor="w", pady=10)

    def refresh_entry_info(self):
        vtype = self.entry_type.get()
        rate = self.rates.get(vtype, 0)
        self.rate_hint.config(
            text=f"Rate: Rs. {rate} per started hour "
                 f"({ZONE_OF[vtype]} Zone)")
        occupied = self.occupied_map()
        parts = []
        for zone in ("Car", "Bike"):
            free = sum(1 for s in self.slots[zone] if s not in occupied)
            parts.append(f"{zone} Zone: {free} free of {len(self.slots[zone])}")
        self.zone_status.config(text="     |     ".join(parts))

    def check_in(self):
        number = self.normalise(self.entry_number.get())
        vehicle_type = self.entry_type.get()

        if not number:
            messagebox.showerror("Input Error", "Enter the vehicle number.")
            return
        if number in self.vehicles:
            messagebox.showerror(
                "Already Parked",
                f"{number} is already checked in at slot "
                f"{self.vehicles[number]['slot']}.")
            return

        zone = ZONE_OF[vehicle_type]
        occupied = self.occupied_map()
        slot = next((s for s in self.slots[zone] if s not in occupied), None)
        if slot is None:
            messagebox.showwarning("Parking Full",
                                   f"No available slots in the {zone} Zone.")
            return

        now = datetime.now()
        self.vehicles[number] = {
            "vehicle_type": vehicle_type,
            "slot": slot,
            "entry_time": now.isoformat(timespec="seconds"),
        }
        self.save_data()
        self.refresh_all()

        message = f"{number} assigned to slot {slot} at {fmt_dt(now)}."
        self.entry_result.config(text="SUCCESS! " + message, foreground="green")
        self.set_status("Checked in: " + message)
        self.entry_number.delete(0, tk.END)
        self.entry_number.focus_set()

    # ------------------------------------------------------ vehicle exit

    def build_exit_tab(self):
        ttk.Label(self.exit_tab, text="VEHICLE CHECK-OUT",
                  style="Heading.TLabel").pack(anchor="w", pady=(0, 15))

        form = ttk.Frame(self.exit_tab)
        form.pack(anchor="w")

        ttk.Label(form, text="Vehicle Number or Slot ID:").grid(
            row=0, column=0, sticky="w", padx=8, pady=10)
        self.exit_var = tk.StringVar()
        self.exit_var.trace_add("write", lambda *a: self.reset_pending())
        self.exit_search = ttk.Entry(form, width=28, textvariable=self.exit_var)
        self.exit_search.grid(row=0, column=1, padx=8, pady=10)
        self.exit_search.bind("<Return>", lambda e: self.calculate_bill())

        buttons = ttk.Frame(form)
        buttons.grid(row=1, column=1, sticky="w", padx=8, pady=14)
        ttk.Button(buttons, text="1. Calculate Bill",
                   command=self.calculate_bill).pack(side="left")
        self.confirm_btn = ttk.Button(buttons, text="2. Confirm Payment & Check Out",
                                      style="Accent.TButton", state="disabled",
                                      command=self.confirm_checkout)
        self.confirm_btn.pack(side="left", padx=10)

        self.receipt_box = tk.Text(self.exit_tab, width=75, height=17,
                                   font=("Consolas", 10), state="disabled",
                                   bg="white", relief="solid", bd=1)
        self.receipt_box.pack(fill="both", expand=True, pady=12)

    def find_vehicle(self, text):
        value = self.normalise(text)
        if value in self.vehicles:
            return value
        for number, details in self.vehicles.items():
            if details["slot"].upper() == value:
                return number
        return None

    def reset_pending(self):
        self.pending_checkout = None
        self.confirm_btn.config(state="disabled")

    def show_receipt(self, text):
        self.receipt_box.config(state="normal")
        self.receipt_box.delete("1.0", tk.END)
        self.receipt_box.insert(tk.END, text)
        self.receipt_box.config(state="disabled")

    @staticmethod
    def build_receipt(p, title, footer):
        line = "-" * 50
        return (
            f"{title:^50}\n{line}\n"
            f"Vehicle Number : {p['number']}\n"
            f"Vehicle Type   : {p['vehicle_type']}\n"
            f"Parking Slot   : {p['slot']}\n"
            f"Entry Time     : {fmt_dt(p['entry'])}\n"
            f"Exit Time      : {fmt_dt(p['exit'])}\n"
            f"Time Parked    : {fmt_duration(p['seconds'])}\n"
            f"Hours Charged  : {p['hours']} hour(s)\n"
            f"Hourly Rate    : Rs. {p['rate']}\n"
            f"{line}\n"
            f"TOTAL AMOUNT   : Rs. {p['amount']}\n"
            f"{line}\n{footer}\n")

    def calculate_bill(self):
        if not self.exit_var.get().strip():
            messagebox.showerror("Input Error",
                                 "Enter a vehicle number or slot ID.")
            return
        number = self.find_vehicle(self.exit_var.get())
        if number is None:
            self.reset_pending()
            messagebox.showerror(
                "Not Found", "No parked vehicle matches that number or slot.")
            return

        details = self.vehicles[number]
        exit_time = datetime.now()
        entry, seconds, hours, rate, amount = self.compute_charge(details,
                                                                  exit_time)
        self.pending_checkout = {
            "number": number, "vehicle_type": details["vehicle_type"],
            "slot": details["slot"], "entry": entry, "exit": exit_time,
            "seconds": seconds, "hours": hours, "rate": rate, "amount": amount,
        }
        self.show_receipt(self.build_receipt(
            self.pending_checkout, "BILL PREVIEW",
            "Press 'Confirm Payment & Check Out' once payment is received."))
        self.confirm_btn.config(state="normal")
        self.set_status(f"Bill calculated for {number}: Rs. {amount}")

    def confirm_checkout(self):
        p = self.pending_checkout
        if not p or p["number"] not in self.vehicles:
            messagebox.showerror("Error", "Please calculate the bill again.")
            self.reset_pending()
            return

        del self.vehicles[p["number"]]
        self.history.append({
            "vehicle_number": p["number"],
            "vehicle_type": p["vehicle_type"],
            "slot": p["slot"],
            "entry_time": p["entry"].isoformat(timespec="seconds"),
            "exit_time": p["exit"].isoformat(timespec="seconds"),
            "hours": p["hours"],
            "rate": p["rate"],
            "amount": p["amount"],
        })
        self.save_data()

        receipt = self.build_receipt(p, "SMART PARKING - PAYMENT RECEIPT",
                                     "PAID. Thank you. Have a safe journey!")
        self.exit_var.set("")            # also resets the pending checkout
        self.show_receipt(receipt)
        self.refresh_all()
        self.set_status(f"Checked out {p['number']} - Rs. {p['amount']} collected.")

    def go_to_checkout(self, number):
        self.notebook.select(self.exit_tab)
        self.exit_var.set(number)
        self.calculate_bill()

    # ------------------------------------------------- history & revenue

    def build_history_tab(self):
        top = ttk.Frame(self.history_tab)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="HISTORY & REVENUE",
                  style="Heading.TLabel").pack(side="left")
        ttk.Button(top, text="Clear History", style="Danger.TButton",
                   command=self.clear_history).pack(side="right")
        ttk.Button(top, text="Export to CSV",
                   command=self.export_history).pack(side="right", padx=8)

        self.history_summary = ttk.Label(self.history_tab, text="",
                                         font=("Arial", 10, "bold"))
        self.history_summary.pack(anchor="w", pady=(0, 8))

        columns = ("vehicle", "type", "slot", "entry", "exit", "hours", "amount")
        headings = ("Vehicle No.", "Type", "Slot", "Entry", "Exit",
                    "Hours", "Amount")
        widths = (130, 100, 60, 160, 160, 70, 100)
        frame = ttk.Frame(self.history_tab)
        frame.pack(fill="both", expand=True)
        self.history_tree = ttk.Treeview(frame, columns=columns,
                                         show="headings")
        for col, head, width in zip(columns, headings, widths):
            self.history_tree.heading(col, text=head)
            self.history_tree.column(col, width=width, anchor="center")
        bar = ttk.Scrollbar(frame, orient="vertical",
                            command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=bar.set)
        self.history_tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

    def refresh_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        for r in reversed(self.history):         # newest first
            self.history_tree.insert("", "end", values=(
                r.get("vehicle_number", ""), r.get("vehicle_type", ""),
                r.get("slot", ""), fmt_dt(parse_time(r.get("entry_time"))),
                fmt_dt(parse_time(r.get("exit_time"))), r.get("hours", ""),
                f"Rs. {r.get('amount', 0)}"))
        total = sum(r.get("amount", 0) for r in self.history)
        self.history_summary.config(
            text=f"Today's revenue: Rs. {self.today_revenue()}      "
                 f"Total revenue: Rs. {total}      "
                 f"Vehicles served: {len(self.history)}")

    def export_history(self):
        if not self.history:
            messagebox.showinfo("Nothing to Export", "No history yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="parking_history.csv",
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        fields = ["vehicle_number", "vehicle_type", "slot", "entry_time",
                  "exit_time", "hours", "rate", "amount"]
        try:
            with open(path, "w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fields,
                                        extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self.history)
            self.set_status(f"History exported to {path}")
        except OSError as error:
            messagebox.showerror("Export Error", str(error))

    def clear_history(self):
        if not self.history:
            return
        if messagebox.askyesno("Clear History",
                               "Permanently delete all history and revenue "
                               "records?"):
            self.history = []
            self.save_data()
            self.refresh_all()
            self.set_status("History cleared.")

    # ------------------------------------------------------------- admin

    def build_admin_tab(self):
        ttk.Label(self.admin_tab, text="ADMIN PARKING CONFIGURATION",
                  style="Heading.TLabel").pack(anchor="w", pady=(0, 12))

        # --- capacity
        cap = ttk.LabelFrame(self.admin_tab, text="Slot Capacity", padding=14)
        cap.pack(fill="x", pady=6)

        ttk.Label(cap, text="Number of Car / SUV Slots:").grid(
            row=0, column=0, sticky="w", padx=8, pady=8)
        self.car_count = ttk.Entry(cap, width=15)
        self.car_count.insert(0, str(len(self.slots["Car"])))
        self.car_count.grid(row=0, column=1, padx=8, pady=8)

        ttk.Label(cap, text="Number of Two-Wheeler Slots:").grid(
            row=1, column=0, sticky="w", padx=8, pady=8)
        self.bike_count = ttk.Entry(cap, width=15)
        self.bike_count.insert(0, str(len(self.slots["Bike"])))
        self.bike_count.grid(row=1, column=1, padx=8, pady=8)

        ttk.Button(cap, text="Update Parking Capacity", style="Accent.TButton",
                   command=self.update_capacity).grid(
            row=2, column=1, sticky="w", padx=8, pady=10)
        ttk.Label(cap, text=("Capacity cannot be reduced below the highest "
                             "occupied slot number in a zone."),
                  style="Hint.TLabel").grid(row=3, column=0, columnspan=2,
                                            sticky="w", padx=8)

        # --- rates
        rate_frame = ttk.LabelFrame(self.admin_tab,
                                    text="Hourly Rates (Rs. per started hour)",
                                    padding=14)
        rate_frame.pack(fill="x", pady=10)

        self.rate_entries = {}
        for row, vtype in enumerate(VEHICLE_TYPES):
            ttk.Label(rate_frame, text=f"{vtype}:").grid(
                row=row, column=0, sticky="w", padx=8, pady=8)
            entry = ttk.Entry(rate_frame, width=15)
            entry.insert(0, str(self.rates[vtype]))
            entry.grid(row=row, column=1, padx=8, pady=8)
            self.rate_entries[vtype] = entry

        ttk.Button(rate_frame, text="Update Hourly Rates",
                   style="Accent.TButton",
                   command=self.update_rates).grid(
            row=len(VEHICLE_TYPES), column=1, sticky="w", padx=8, pady=10)
        ttk.Label(rate_frame,
                  text=("New rates apply to every bill from now on, including "
                        "vehicles that are already parked."),
                  style="Hint.TLabel").grid(row=len(VEHICLE_TYPES) + 1,
                                            column=0, columnspan=2,
                                            sticky="w", padx=8)

    def highest_occupied_index(self, zone):
        prefix, highest = SLOT_PREFIX[zone], 0
        for details in self.vehicles.values():
            slot = details["slot"]
            if slot.startswith(prefix):
                try:
                    highest = max(highest, int(slot[len(prefix):]))
                except ValueError:
                    pass
        return highest

    def update_capacity(self):
        try:
            car_total = int(self.car_count.get())
            bike_total = int(self.bike_count.get())
            if not (0 <= car_total <= MAX_SLOTS and 0 <= bike_total <= MAX_SLOTS):
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid Capacity",
                f"Enter whole numbers between 0 and {MAX_SLOTS}.")
            return

        for zone, new_total in (("Car", car_total), ("Bike", bike_total)):
            needed = self.highest_occupied_index(zone)
            if new_total < needed:
                messagebox.showerror(
                    "Capacity Too Small",
                    f"A vehicle is parked in slot "
                    f"{SLOT_PREFIX[zone]}{needed:02d}, so the {zone} Zone "
                    f"needs at least {needed} slots.")
                return

        self.slots["Car"] = [f"C{i:02d}" for i in range(1, car_total + 1)]
        self.slots["Bike"] = [f"B{i:02d}" for i in range(1, bike_total + 1)]
        self.save_data()
        self.refresh_all()
        self.set_status("Parking capacity updated.")
        messagebox.showinfo("Updated",
                            "Parking capacity has been updated successfully.")

    def update_rates(self):
        new_rates = {}
        for vtype, entry in self.rate_entries.items():
            try:
                value = int(entry.get())
                if not 1 <= value <= 100000:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Invalid Rate",
                    f"The rate for {vtype} must be a whole number of rupees "
                    "greater than 0.")
                return
            new_rates[vtype] = value

        self.rates = new_rates
        self.save_data()
        self.refresh_entry_info()
        self.reset_pending()               # an old bill preview is now outdated
        self.set_status("Hourly rates updated.")
        messagebox.showinfo("Updated", "Hourly rates have been updated.")


if __name__ == "__main__":
    root = tk.Tk()
    app = SmartParkingSystem(root)
    root.mainloop()
