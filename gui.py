import contextlib
import io
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import backend


class QueueWriter(io.TextIOBase):
    def __init__(self, log_queue):
        self.log_queue = log_queue

    def write(self, text):
        if text:
            self.log_queue.put(text)
        return len(text)

    def flush(self):
        return None


class AnimeDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Anime Downloader")
        self.root.geometry("860x560")
        self.root.minsize(720, 460)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.log_queue = queue.Queue()
        self.download_thread = None
        self.poll_job = None
        self.is_closing = False

        self.url_var = tk.StringVar()
        self.download_dir_var = tk.StringVar(value=str(backend.get_download_dir()))
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self._poll_log_queue()

    def _build_ui(self):
        self.root.configure(bg="#10141c")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("App.TFrame", background="#10141c")
        style.configure("Card.TFrame", background="#171c26")
        style.configure(
            "Title.TLabel",
            background="#10141c",
            foreground="#f4f7fb",
            font=("TkDefaultFont", 20, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background="#10141c",
            foreground="#b8c2d1",
            font=("TkDefaultFont", 10),
        )
        style.configure(
            "Status.TLabel",
            background="#171c26",
            foreground="#dbe4f0",
            font=("TkDefaultFont", 10, "bold"),
        )
        style.configure(
            "App.TButton",
            font=("TkDefaultFont", 10, "bold"),
            padding=(14, 10),
        )
        style.map(
            "App.TButton",
            background=[("active", "#2f75ff"), ("!disabled", "#2463eb")],
            foreground=[("!disabled", "#ffffff")],
        )

        outer = ttk.Frame(self.root, style="App.TFrame", padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x")

        ttk.Label(header, text="Anime Downloader", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text="Paste one Aniwatch episode link to download the whole season, or use a direct media page for a single video.",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        controls = ttk.Frame(outer, style="Card.TFrame", padding=18)
        controls.pack(fill="x", pady=(18, 14))

        url_label = tk.Label(
            controls,
            text="Episode / Season URL",
            bg="#171c26",
            fg="#f4f7fb",
            font=("TkDefaultFont", 10, "bold"),
        )
        url_label.pack(anchor="w")

        self.url_entry = tk.Entry(
            controls,
            textvariable=self.url_var,
            font=("TkDefaultFont", 11),
            bg="#0f141c",
            fg="#f4f7fb",
            insertbackground="#f4f7fb",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#334155",
            highlightcolor="#2463eb",
        )
        self.url_entry.pack(fill="x", pady=(8, 12), ipady=10)
        self.url_entry.focus_set()
        self.url_entry.bind("<Return>", self._start_download_event)

        folder_label = tk.Label(
            controls,
            text="Download Folder",
            bg="#171c26",
            fg="#f4f7fb",
            font=("TkDefaultFont", 10, "bold"),
        )
        folder_label.pack(anchor="w")

        folder_row = tk.Frame(controls, bg="#171c26")
        folder_row.pack(fill="x", pady=(8, 12))

        self.folder_entry = tk.Entry(
            folder_row,
            textvariable=self.download_dir_var,
            font=("TkDefaultFont", 11),
            bg="#0f141c",
            fg="#f4f7fb",
            insertbackground="#f4f7fb",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#334155",
            highlightcolor="#2463eb",
        )
        self.folder_entry.pack(side="left", fill="x", expand=True, ipady=10)

        browse_button = ttk.Button(
            folder_row,
            text="Browse",
            command=self.choose_download_dir,
        )
        browse_button.pack(side="left", padx=(10, 0))

        button_row = ttk.Frame(controls, style="Card.TFrame")
        button_row.pack(fill="x")

        self.download_button = ttk.Button(
            button_row,
            text="Download Video",
            style="App.TButton",
            command=self.start_download,
        )
        self.download_button.pack(side="left")

        clear_button = ttk.Button(
            button_row,
            text="Clear Log",
            command=self.clear_log,
        )
        clear_button.pack(side="left", padx=(10, 0))

        status_card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        status_card.pack(fill="x", pady=(0, 14))

        ttk.Label(status_card, text="Status", style="Status.TLabel").pack(anchor="w")
        self.status_value = tk.Label(
            status_card,
            textvariable=self.status_var,
            bg="#171c26",
            fg="#8ad4ff",
            font=("TkDefaultFont", 11),
        )
        self.status_value.pack(anchor="w", pady=(6, 0))

        log_card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        log_card.pack(fill="both", expand=True)

        log_label = tk.Label(
            log_card,
            text="Download Log",
            bg="#171c26",
            fg="#f4f7fb",
            font=("TkDefaultFont", 10, "bold"),
        )
        log_label.pack(anchor="w", pady=(0, 8))

        log_frame = tk.Frame(log_card, bg="#171c26")
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            bg="#0b0f15",
            fg="#dbe4f0",
            insertbackground="#dbe4f0",
            relief="flat",
            font=("Courier", 10),
            padx=12,
            pady=12,
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self._append_log("Ready. Paste a link and start the download.\n")

    def _start_download_event(self, _event):
        self.start_download()

    def start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Enter a URL to download first.")
            return

        if self.download_thread and self.download_thread.is_alive():
            messagebox.showinfo("Download Running", "A download is already in progress.")
            return

        download_dir = self.download_dir_var.get().strip()
        if not download_dir:
            messagebox.showwarning(
                "Missing Folder",
                "Choose a download folder before starting the download.",
            )
            return

        try:
            saved_path = backend.set_download_dir(download_dir)
        except OSError as exc:
            messagebox.showerror(
                "Folder Error",
                f"Could not use that download folder:\n{exc}",
            )
            return

        self.download_dir_var.set(str(saved_path))

        self._set_downloading_state(True)
        self.status_var.set("Downloading...")
        self._append_log(f"\nStarting download for: {url}\n")
        self._append_log(f"Saving into: {saved_path}\n")

        self.download_thread = threading.Thread(
            target=self._run_download,
            args=(url,),
            daemon=True,
        )
        self.download_thread.start()

    def _run_download(self, url):
        writer = QueueWriter(self.log_queue)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                backend.start_scraper(url)
        except Exception as exc:
            self.log_queue.put(f"\nUnexpected error: {exc}\n")
            if not self.is_closing:
                self.root.after(0, lambda: self.status_var.set("Failed"))
        else:
            if not self.is_closing:
                self.root.after(0, lambda: self.status_var.set("Finished"))
        finally:
            if not self.is_closing:
                self.root.after(0, lambda: self._set_downloading_state(False))

    def _set_downloading_state(self, is_downloading):
        state = "disabled" if is_downloading else "normal"
        self.download_button.configure(state=state)
        self.url_entry.configure(state=state)
        self.folder_entry.configure(state=state)

    def choose_download_dir(self):
        initial_dir = self.download_dir_var.get().strip() or os.getcwd()
        selected_dir = filedialog.askdirectory(
            title="Choose Download Folder",
            initialdir=initial_dir,
            mustexist=False,
        )
        if selected_dir:
            self.download_dir_var.set(selected_dir)

    def clear_log(self):
        self.log_text.delete("1.0", "end")
        self._append_log("Log cleared.\n")

    def _append_log(self, text):
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def _poll_log_queue(self):
        if self.is_closing:
            return

        while True:
            try:
                chunk = self.log_queue.get_nowait()
            except queue.Empty:
                break
            else:
                self._append_log(chunk)

        self.poll_job = self.root.after(100, self._poll_log_queue)

    def close(self):
        self.is_closing = True

        if self.poll_job is not None:
            try:
                self.root.after_cancel(self.poll_job)
            except tk.TclError:
                pass
            self.poll_job = None

        try:
            self.root.quit()
        except tk.TclError:
            pass

        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main():
    root = tk.Tk()
    app = AnimeDownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
