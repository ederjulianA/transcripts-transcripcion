# transcribir_gui.py
"""
Interfaz gráfica (Tkinter) para el transcriptor de audio/video.

- Selección de archivo y carpeta de salida con diálogos nativos.
- Configuración de todos los parámetros del script.
- Persistencia: guarda la última configuración usada en `gui_config.json`
  y la restaura al abrir la aplicación.
- Ejecuta la transcripción en un hilo aparte para no congelar la ventana,
  mostrando progreso y log en vivo.

Uso:
    python transcribir_gui.py
"""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import transcribir_controlt as core

CONFIG_FILE = Path(__file__).parent / "gui_config.json"

MODELS = ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"]

DEFAULT_CONFIG = {
    "input_file": "",
    "model": "gpt-4o-mini-transcribe",
    "chunk_seconds": "",          # vacío = automático
    "out_dir": "salida_transcripcion",
    "max_workers": 5,
    "use_cache": True,
    "keep_chunks": False,
    "language": "es",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass  # config corrupta: usar defaults
    return cfg


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def open_in_explorer(path: str):
    """Abre una carpeta en el explorador del sistema (Windows/macOS/Linux)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
    except Exception:
        pass


class TranscriptorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Transcriptor de Audio/Video")
        self.root.geometry("720x620")
        self.root.minsize(640, 560)

        self.cfg = load_config()
        self.log_queue: "queue.Queue[tuple]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.last_out_dir: str | None = None

        self._build_widgets()
        self._poll_queue()
        # Guardar config al cerrar
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- UI ----------------
    def _build_widgets(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        row = 0
        # Archivo de entrada
        ttk.Label(frm, text="Archivo de video/audio:").grid(row=row, column=0, sticky="w", **pad)
        self.var_input = tk.StringVar(value=self.cfg["input_file"])
        ttk.Entry(frm, textvariable=self.var_input).grid(row=row, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Examinar…", command=self._pick_file).grid(row=row, column=2, **pad)

        row += 1
        # Carpeta de salida
        ttk.Label(frm, text="Carpeta de salida:").grid(row=row, column=0, sticky="w", **pad)
        self.var_outdir = tk.StringVar(value=self.cfg["out_dir"])
        ttk.Entry(frm, textvariable=self.var_outdir).grid(row=row, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Examinar…", command=self._pick_outdir).grid(row=row, column=2, **pad)

        row += 1
        # Modelo
        ttk.Label(frm, text="Modelo:").grid(row=row, column=0, sticky="w", **pad)
        self.var_model = tk.StringVar(value=self.cfg["model"])
        ttk.Combobox(frm, textvariable=self.var_model, values=MODELS,
                     state="readonly").grid(row=row, column=1, sticky="ew", **pad)

        row += 1
        # Chunk seconds
        ttk.Label(frm, text="Segundos por chunk\n(vacío = automático):").grid(row=row, column=0, sticky="w", **pad)
        self.var_chunk = tk.StringVar(value=str(self.cfg["chunk_seconds"]))
        ttk.Entry(frm, textvariable=self.var_chunk, width=12).grid(row=row, column=1, sticky="w", **pad)

        row += 1
        # Max workers
        ttk.Label(frm, text="Workers paralelos:").grid(row=row, column=0, sticky="w", **pad)
        self.var_workers = tk.IntVar(value=int(self.cfg["max_workers"]))
        ttk.Spinbox(frm, from_=1, to=16, textvariable=self.var_workers,
                    width=10).grid(row=row, column=1, sticky="w", **pad)

        row += 1
        # Idioma
        ttk.Label(frm, text="Idioma:").grid(row=row, column=0, sticky="w", **pad)
        self.var_lang = tk.StringVar(value=self.cfg["language"])
        ttk.Combobox(frm, textvariable=self.var_lang, values=["es", "en", "pt", "fr", "it"],
                     state="readonly", width=10).grid(row=row, column=1, sticky="w", **pad)

        row += 1
        # Checkboxes
        self.var_cache = tk.BooleanVar(value=bool(self.cfg["use_cache"]))
        ttk.Checkbutton(frm, text="Usar caché de metadatos",
                        variable=self.var_cache).grid(row=row, column=1, sticky="w", **pad)
        row += 1
        self.var_keep = tk.BooleanVar(value=bool(self.cfg["keep_chunks"]))
        ttk.Checkbutton(frm, text="Conservar chunks tras la transcripción",
                        variable=self.var_keep).grid(row=row, column=1, sticky="w", **pad)

        row += 1
        # Botones de acción
        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        self.btn_start = ttk.Button(btns, text="▶ Transcribir", command=self._start)
        self.btn_start.pack(side="left", padx=4)
        self.btn_open = ttk.Button(btns, text="📂 Abrir carpeta de salida",
                                   command=self._open_output, state="disabled")
        self.btn_open.pack(side="left", padx=4)

        row += 1
        # Barra de progreso
        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        self.var_status = tk.StringVar(value="Listo.")
        ttk.Label(frm, textvariable=self.var_status).grid(row=row + 1, column=0, columnspan=3, sticky="w", **pad)

        row += 2
        # Log
        ttk.Label(frm, text="Registro:").grid(row=row, column=0, sticky="w", **pad)
        row += 1
        self.txt_log = tk.Text(frm, height=12, wrap="word", state="disabled")
        self.txt_log.grid(row=row, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(row, weight=1)
        scroll = ttk.Scrollbar(frm, command=self.txt_log.yview)
        scroll.grid(row=row, column=3, sticky="ns")
        self.txt_log["yscrollcommand"] = scroll.set

    # ---------------- Acciones ----------------
    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Selecciona un archivo de video/audio",
            filetypes=[
                ("Audio/Video", "*.mp4 *.mkv *.mov *.avi *.m4a *.wav *.mp3 *.flac *.ogg"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if path:
            self.var_input.set(path)

    def _pick_outdir(self):
        path = filedialog.askdirectory(title="Selecciona la carpeta de salida")
        if path:
            self.var_outdir.set(path)

    def _current_config(self) -> dict:
        return {
            "input_file": self.var_input.get().strip(),
            "model": self.var_model.get(),
            "chunk_seconds": self.var_chunk.get().strip(),
            "out_dir": self.var_outdir.get().strip(),
            "max_workers": int(self.var_workers.get()),
            "use_cache": bool(self.var_cache.get()),
            "keep_chunks": bool(self.var_keep.get()),
            "language": self.var_lang.get(),
        }

    def _start(self):
        if self.worker and self.worker.is_alive():
            return

        cfg = self._current_config()
        if not cfg["input_file"]:
            messagebox.showwarning("Falta el archivo", "Selecciona un archivo de video/audio.")
            return
        if not Path(cfg["input_file"]).exists():
            messagebox.showerror("Archivo no encontrado", f"No existe:\n{cfg['input_file']}")
            return

        # Parsear chunk_seconds (vacío = None = automático)
        chunk_seconds = None
        if cfg["chunk_seconds"]:
            try:
                chunk_seconds = int(cfg["chunk_seconds"])
            except ValueError:
                messagebox.showerror("Valor inválido", "Segundos por chunk debe ser un número entero o estar vacío.")
                return

        save_config(cfg)  # persistir antes de arrancar

        # Resetear UI
        self._clear_log()
        self.progress["value"] = 0
        self.btn_start["state"] = "disabled"
        self.btn_open["state"] = "disabled"
        self.var_status.set("Procesando…")
        self.last_out_dir = None

        def on_log(msg):
            self.log_queue.put(("log", msg))

        def on_progress(done, total):
            self.log_queue.put(("progress", (done, total)))

        def run():
            try:
                result = core.transcribe(
                    input_file=cfg["input_file"],
                    model=cfg["model"],
                    chunk_seconds=chunk_seconds,
                    out_dir=cfg["out_dir"],
                    max_workers=cfg["max_workers"],
                    use_cache=cfg["use_cache"],
                    keep_chunks=cfg["keep_chunks"],
                    language=cfg["language"],
                    on_log=on_log,
                    on_progress=on_progress,
                )
                self.log_queue.put(("done", result))
            except Exception as e:
                self.log_queue.put(("error", str(e)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _open_output(self):
        if self.last_out_dir:
            open_in_explorer(self.last_out_dir)

    # ---------------- Cola / actualización de UI ----------------
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "progress":
                    done, total = payload
                    self.progress["maximum"] = total
                    self.progress["value"] = done
                    self.var_status.set(f"Procesando chunk {done}/{total}…")
                elif kind == "done":
                    self._on_finish(payload)
                elif kind == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _on_finish(self, result: dict):
        self.last_out_dir = result["out_dir"]
        self.var_status.set(
            f"✅ Listo: {result['successful_chunks']}/{result['total_chunks']} chunks. "
            f"TXT: {Path(result['txt']).name}"
        )
        self.btn_start["state"] = "normal"
        self.btn_open["state"] = "normal"

    def _on_error(self, msg: str):
        self.var_status.set("❌ Error.")
        self.btn_start["state"] = "normal"
        self._append_log(f"❌ ERROR: {msg}")
        messagebox.showerror("Error en la transcripción", msg)

    # ---------------- Log helpers ----------------
    def _append_log(self, msg: str):
        self.txt_log["state"] = "normal"
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log["state"] = "disabled"

    def _clear_log(self):
        self.txt_log["state"] = "normal"
        self.txt_log.delete("1.0", "end")
        self.txt_log["state"] = "disabled"

    def _on_close(self):
        save_config(self._current_config())
        self.root.destroy()


def main():
    root = tk.Tk()
    # Tema más moderno si está disponible
    try:
        ttk.Style().theme_use("vista" if sys.platform.startswith("win") else "clam")
    except Exception:
        pass
    TranscriptorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
