import os
import sys
import threading
import traceback
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
from PIL import Image
import pytesseract


APP_NAME = "PDF OCR"
LANG = "rus+eng"


def resource_path(*parts):
    """Path to files bundled by PyInstaller --onefile."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def find_tesseract():
    candidates = [
        resource_path("tesseract", "tesseract.exe"),
        Path(os.environ.get("TESSERACT_PATH", "")) if os.environ.get("TESSERACT_PATH") else None,
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for p in candidates:
        if p and p.exists():
            return str(p)
    return None


def find_font():
    """TTF с поддержкой кириллицы: невидимый слой должен уметь хранить русский текст.
    Встроенные PDF-шрифты (helv и др.) кириллицу не содержат."""
    candidates = [
        resource_path("fonts", "DejaVuSans.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\calibri.ttf"),
        Path(r"C:\Windows\Fonts\tahoma.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for p in candidates:
        if p and p.exists():
            return str(p)
    return None


TESSERACT = find_tesseract()
if TESSERACT:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT
    tessdata = resource_path("tesseract", "tessdata")
    if tessdata.exists():
        os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))

FONT_FILE = find_font()
OCR_FONTNAME = "ocr-invisible"


def add_invisible_text(page, data, scale_x, scale_y, font):
    """OCR-координаты приходят в пикселях картинки, PDF работает в пунктах.

    Размер шрифта подбирается по ШИРИНЕ распознанного слова, а вставка идёт
    через insert_text по базовой линии: insert_text никогда не отбрасывает
    текст, в отличие от insert_textbox, который молча пропускает слово,
    если оно не помещается в прямоугольник.
    """
    inserted = 0
    derot = page.derotation_matrix   # OCR видит страницу в «видимых» координатах,
    rot = page.rotation % 360        # а insert_textbox работает в неповёрнутых

    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue

        x = float(data["left"][i]) * scale_x
        y = float(data["top"][i]) * scale_y
        w = float(data["width"][i]) * scale_x
        h = float(data["height"][i]) * scale_y
        if w <= 0 or h <= 0:
            continue

        # ширина слова этим шрифтом при размере 1pt
        unit_len = font.text_length(text, fontsize=1)
        if unit_len <= 0:
            continue
        fontsize = min(w / unit_len, h * 1.2)
        fontsize = max(fontsize, 1.0)

        # Прямоугольник берём с запасом, чтобы одна строка гарантированно
        # помещалась и слово не было отброшено (insert_textbox при нехватке
        # места молча не вставляет текст и возвращает отрицательное число)
        try:
            for attempt_fs in (fontsize, fontsize * 0.85):
                rect = fitz.Rect(
                    x, y,
                    x + w * 1.02 + 1,
                    y + max(h, attempt_fs * 1.4) + 2,
                )
                rect = rect * derot   # перевод в неповёрнутые координаты страницы
                rect.normalize()
                rv = page.insert_textbox(
                    rect,
                    text,
                    fontsize=attempt_fs,
                    fontname=OCR_FONTNAME,
                    fontfile=FONT_FILE,
                    render_mode=3,  # невидимый текст
                    overlay=True,
                    rotate=rot,       # текст идёт вдоль видимой горизонтали
                )
                if rv >= 0:
                    inserted += 1
                    break
        except Exception:
            # Одно проблемное слово не должно останавливать документ.
            pass
    return inserted


def process_pdf(src, dst, dpi, progress_cb):
    if not FONT_FILE:
        raise RuntimeError(
            "Не найден TTF-шрифт с поддержкой кириллицы "
            "(искали Arial/Calibri/Tahoma в C:\\Windows\\Fonts)."
        )
    font = fitz.Font(fontfile=FONT_FILE)
    doc = fitz.open(src)
    total = len(doc)
    inserted_total = 0

    for page_index, page in enumerate(doc):
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # PSM 3 works well for ordinary document pages.
        data = pytesseract.image_to_data(
            img,
            lang=LANG,
            config="--oem 3 --psm 3",
            output_type=pytesseract.Output.DICT,
        )

        scale_x = page.rect.width / img.width
        scale_y = page.rect.height / img.height
        inserted_total += add_invisible_text(page, data, scale_x, scale_y, font)

        progress_cb(page_index + 1, total)

    try:
        doc.subset_fonts()  # оставляем в файле только использованные глифы
    except Exception:
        pass
    doc.save(dst, garbage=4, deflate=True)
    doc.close()
    return inserted_total


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF OCR — распознавание сканов")
        self.geometry("620x360")
        self.minsize(620, 360)

        self.src = tk.StringVar()
        self.lang = tk.StringVar(value="Русский + English")
        self.dpi = tk.IntVar(value=250)
        self.status = tk.StringVar(value="Выберите сканированный PDF.")
        self.progress = tk.DoubleVar(value=0)

        self._build()

    def _build(self):
        pad = {"padx": 22, "pady": 10}

        ttk.Label(
            self,
            text="PDF OCR",
            font=("Segoe UI", 22, "bold")
        ).pack(anchor="w", **pad)

        ttk.Label(
            self,
            text="Добавляет в сканированный PDF невидимый текстовый слой.\n"
                 "После обработки текст можно выделять, копировать и искать.",
            font=("Segoe UI", 10)
        ).pack(anchor="w", padx=22)

        frm = ttk.Frame(self)
        frm.pack(fill="x", padx=22, pady=18)

        ttk.Entry(frm, textvariable=self.src).pack(side="left", fill="x", expand=True)
        ttk.Button(frm, text="Выбрать PDF…", command=self.choose).pack(side="left", padx=(10, 0))

        opts = ttk.Frame(self)
        opts.pack(fill="x", padx=22)

        ttk.Label(opts, text="Язык:").pack(side="left")
        ttk.Label(opts, textvariable=self.lang).pack(side="left", padx=(6, 30))
        ttk.Label(opts, text="Качество:").pack(side="left")

        ttk.Combobox(
            opts,
            textvariable=self.dpi,
            values=(200, 250, 300),
            width=6,
            state="readonly"
        ).pack(side="left", padx=6)

        self.btn = ttk.Button(
            self,
            text="РАСПОЗНАТЬ",
            command=self.start
        )
        self.btn.pack(pady=20, ipadx=28, ipady=8)

        self.pb = ttk.Progressbar(
            self,
            variable=self.progress,
            maximum=100,
            mode="determinate"
        )
        self.pb.pack(fill="x", padx=22)

        ttk.Label(
            self,
            textvariable=self.status,
            font=("Segoe UI", 10)
        ).pack(anchor="w", padx=22, pady=12)

        ttk.Label(
            self,
            text="Все операции выполняются локально. Интернет не нужен.",
            foreground="#666666"
        ).pack(anchor="w", padx=22)

    def choose(self):
        path = filedialog.askopenfilename(
            title="Выберите сканированный PDF",
            filetypes=[("PDF files", "*.pdf")]
        )
        if path:
            self.src.set(path)
            self.status.set("Файл выбран. Нажмите «РАСПОЗНАТЬ».")

    def start(self):
        src = self.src.get().strip()
        if not src or not Path(src).exists():
            messagebox.showwarning("PDF OCR", "Сначала выберите PDF-файл.")
            return

        if not TESSERACT:
            messagebox.showerror(
                "Не найден OCR-движок",
                "Tesseract не встроен в эту сборку. "
                "Пересоберите программу по инструкции в README."
            )
            return

        src_path = Path(src)
        dst = src_path.with_name(src_path.stem + "_OCR.pdf")

        self.btn.config(state="disabled")
        self.progress.set(0)
        self.status.set("Подготовка…")

        threading.Thread(
            target=self.worker,
            args=(src_path, dst),
            daemon=True
        ).start()

    def worker(self, src, dst):
        try:
            def cb(done, total):
                self.after(
                    0,
                    lambda: (
                        self.progress.set(done / total * 100),
                        self.status.set(f"Распознано страниц: {done} из {total}")
                    )
                )

            inserted = process_pdf(str(src), str(dst), self.dpi.get(), cb)

            self.after(
                0,
                lambda: self.finish_ok(dst, inserted)
            )
        except Exception as e:
            traceback.print_exc()
            msg = str(e) or type(e).__name__
            self.after(0, lambda m=msg: self.finish_error(m))

    def finish_ok(self, dst, inserted):
        self.btn.config(state="normal")
        self.progress.set(100)
        self.status.set(f"Готово: {dst.name} (слов в текстовом слое: {inserted})")

        if inserted == 0:
            messagebox.showwarning(
                "Текст не распознан",
                "В документе не удалось распознать ни одного слова.\n"
                "Возможно, качество скана слишком низкое — попробуйте другое значение «Качество»."
            )
            return

        if messagebox.askyesno(
            "Готово",
            f"Распознавание завершено.\n\n{dst}\n\nОткрыть результат?"
        ):
            try:
                os.startfile(dst)  # Windows
            except AttributeError:
                import subprocess
                subprocess.Popen(["xdg-open", str(dst)])

    def finish_error(self, error):
        self.btn.config(state="normal")
        self.status.set("Ошибка обработки.")
        messagebox.showerror("Ошибка", error)


if __name__ == "__main__":
    App().mainloop()
