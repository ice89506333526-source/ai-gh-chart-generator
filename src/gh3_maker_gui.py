"""AI GH Chart Generator - desktop GUI.

Buttons: choose an MP3 -> convert -> listen to the two previews -> confirm,
plus "Open folder" and "Thank the author" (QR window).

The conversion runs make_song.py (the proven pipeline) inside this process on
a background thread, so the window stays responsive and the log streams live.

Run from source (same venv as the pipeline):
    D:\\ai-gh\\ai-gh-stage3\\.venv\\Scripts\\python.exe D:\\ai-gh\\pipeline\\gh3_maker_gui.py
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import Toplevel, Tk, StringVar, BooleanVar, filedialog, messagebox, ttk

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR))
import make_song  # noqa: E402  (the proven pipeline, imported as a module)

APP_TITLE = "AI Guitar Hero Chart Generator"
DEFAULT_OUT_ROOT = r"D:\ai-gh\pipeline\out"
DEFAULT_WORK_ROOT = r"D:\ai-gh\pipeline\work"
SONG_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
SEPARATION_PYTHON = Path(r"D:\ai-gh\ai-gh-stage2\.venv\Scripts\python.exe")

try:  # bundled into the exe; optional when running from source
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

TON_USDT_ADDRESS = "UQDFdVjxx81PCZFTiH8P9DKk89f48jccmBKbEjtMoWaAFvyb"
RU_CARD = "2204320615123140"

# ---------------------------------------------------------------- i18n
STRINGS = {
    "en": {
        "title": "AI Guitar Hero Chart Generator",
        "song_frame": "1. Song",
        "mp3": "MP3:",
        "open": "Open…",
        "song_id": "Song ID (latin letters):",
        "name_label": "Title:",
        "artist_label": "Artist:",
        "settings_frame": "2. Settings (usually not needed)",
        "bpm_label": "Tempo BPM (empty = auto):",
        "easier": "Make easier (sparser attacks)",
        "hardkore": "Hardkore mode (DragonForce-style: dense, repeats kept, expert-only challenge)",
        "hardkore_hint": (
            "Notes down to ~60 ms, repeated attacks stay on one lane, min gap 40 ms. "
            "Expert becomes deliberately brutal; the Hard track stays normal."
        ),
        "hard_track": "Add the Hard track",
        "with_vocals": "Full song with vocals (separate the guitar)",
        "separation_hint": (
            "Notes are built from the guitar stem without vocals (1-3 min on a GPU); "
            "the in-game audio keeps the original song with guitar forward, vocals quieter."
        ),
        "convert": "3. Convert",
        "status_idle": "Pick an mp3 and press Convert",
        "log_frame": "Conversion log",
        "check_frame": "4. Check and result",
        "listen_grid": "▶ Listen: tempo clicks",
        "listen_notes": "▶ Listen: detected notes",
        "confirm": "✔ Confirm",
        "open_out": "Open the GHTCP folder",
        "out_hint": "Import folder: out\\<ID>  (notes.chart + song.wav)",
        "donate": "♥ Thank the author",
        "lang_button": "RU",
        "file_dialog_title": "Pick a song",
        "filetype_audio": "Audio",
        "filetype_mp3": "MP3",
        "filetype_all": "All files",
        "err_no_file": "Pick an mp3 file first.",
        "err_not_found": "File not found: ",
        "err_bad_id": (
            "Song ID is required: latin letters/digits/dashes, no spaces (e.g. mysong)."
        ),
        "err_bad_bpm": "BPM must be a number between 40 and 240.",
        "err_bpm_nan": "BPM must be a number (e.g. 132).",
        "converting": "Converting…",
        "status_sep": "Separating the guitar (Demucs)…",
        "status_grid": "Tempo grid…",
        "status_transcribe": "Transcribing (Basic Pitch)…",
        "status_filters": "Filters (squeal/hum/clicks)…",
        "status_map": "Fret mapping…",
        "status_revise": "<80 ms revision + validation…",
        "status_audio": "song.wav audio…",
        "status_export": "Exporting notes.chart…",
        "status_hard": "Hard track…",
        "status_preview": "Listening previews…",
        "done_status": "Done. Listen to both previews, then press Confirm.",
        "done_title": "Done!",
        "done_body": (
            "Done!\n\nImport package:\n{out}\n\nNow listen to both previews "
            "(buttons above) and press Confirm."
        ),
        "failed_status": "Error — details in the log.",
        "failed_title": "Conversion failed:\n",
        "file_missing": "File not found: ",
        "open_manually": "Open the file in a player manually:\n",
        "confirm_question": (
            "Did you listen to both previews and want to confirm the result?\n"
            "(The confirmation is written into the result folder.)"
        ),
        "confirmed_status": "Confirmed. Ready to import into GHTCP.",
        "confirmed_body": (
            "Confirmed!\n\nNext: GHTCP → create a song with ID {sid}\n"
            "chart: notes.chart from the result folder\naudio: song.wav"
        ),
        "donation_window_title": "Thank the author",
        "donation_text": (
            "If you like this program, you can thank the author\n"
            "with any comfortable amount.\n\n"
            "International — USDT (TON network):\n"
            + TON_USDT_ADDRESS + "\n\n"
            "Scan the QR below with any wallet app:"  # image goes right under this
        ),
        "donation_qr_missing": "(QR not found — the address is above)",
        "close": "Close",
        "log_error": "ERROR: ",
        "log_stages": "Stages: grid → transcription → filters → mapping → revision → export",
        "log_file": "File: ",
        "log_sep": (
            "Separation: splitting into stems (htdemucs_6s); notes follow the "
            "guitar, the game mix has guitar forward and vocals quieter"
        ),
        "log_guitar": "    guitar: ",
        "log_bpm": "    BPM {bpm:.3f} | first point {first:.3f} s",
        "log_notes": "    notes found: {n}",
        "log_groups": "    onset groups: {n} (clicks removed: {c})",
        "log_valid": "    validation: 0 errors",
        "log_hard": "    Hard: {n} events",
        "err_demucs_missing": (
            "Demucs environment not found: " + str(SEPARATION_PYTHON)
            + " — guitar separation is unavailable on this machine."
        ),
        "err_demucs_failed": "Demucs could not split the song. Details: ",
        "err_no_demucs_output": "no output",
        "err_validation": "Validation failed: ",
    },
    "ru": {
        "title": "AI Guitar Hero Chart Generator",
        "song_frame": "1. Песня",
        "mp3": "MP3:",
        "open": "Открыть…",
        "song_id": "ID песни (латиница):",
        "name_label": "Название:",
        "artist_label": "Исполнитель:",
        "settings_frame": "2. Настройки (обычно не нужны)",
        "bpm_label": "Темп BPM (пусто = авто):",
        "easier": "Сделать легче (реже атаки)",
        "hard_track": "Добавить дорожку Hard",
        "with_vocals": "Это песня с вокалом (отделить гитару)",
        "hardkore": "Хардкор-режим (в стиле DragonForce: плотно, с повторами, только для эксперта)",
        "hardkore_hint": (
            "Ноты до ~60 мс, повторы остаются на одном ладу, минимальный интервал 40 мс. "
            "Expert становится специально зверским; дорожка Hard остаётся обычной."
        ),
        "separation_hint": (
            "Ноты строятся по гитаре без вокала (1–3 мин на видеокарте); "
            "аудио в игре остаётся оригинальной песней: гитара громче, вокал тише."
        ),
        "convert": "3. Конвертировать",
        "status_idle": "Выберите mp3 и нажмите «Конвертировать»",
        "log_frame": "Журнал конвертации",
        "check_frame": "4. Проверка и результат",
        "listen_grid": "▶ Прослушать: клики темпа",
        "listen_notes": "▶ Прослушать: найденные ноты",
        "confirm": "✔ Подтвердить",
        "open_out": "Открыть папку для GHTCP",
        "out_hint": "Папка для игры: out\\<ID>  (notes.chart + song.wav)",
        "donate": "♥ Поблагодарить автора",
        "lang_button": "EN",
        "file_dialog_title": "Выберите песню",
        "filetype_audio": "Аудио",
        "filetype_mp3": "MP3",
        "filetype_all": "Все файлы",
        "err_no_file": "Выберите mp3-файл.",
        "err_not_found": "Файл не найден: ",
        "err_bad_id": "ID песни обязателен: латиница/цифры/дефис, без пробелов (например mysong).",
        "err_bad_bpm": "BPM должен быть числом от 40 до 240.",
        "err_bpm_nan": "BPM должен быть числом (например 132).",
        "converting": "Конвертация…",
        "status_sep": "Отделение гитары (Demucs)…",
        "status_grid": "Сетка темпа…",
        "status_transcribe": "Транскрипция (Basic Pitch)…",
        "status_filters": "Фильтры (писк/гул/щелчки)…",
        "status_map": "Маппинг на лады…",
        "status_revise": "Ревизия <80 мс + валидация…",
        "status_audio": "Аудио song.wav…",
        "status_export": "Экспорт notes.chart…",
        "status_hard": "Дорожка Hard…",
        "status_preview": "Превью для прослушивания…",
        "done_status": "Готово. Прослушайте превью и нажмите «Подтвердить».",
        "done_title": "Готово!",
        "done_body": (
            "Готово!\n\nПакет для GHTCP:\n{out}\n\nТеперь прослушайте два превью "
            "(кнопки выше) и нажмите «Подтвердить»."
        ),
        "failed_status": "Ошибка — подробности в журнале.",
        "failed_title": "Конвертация не удалась:\n",
        "file_missing": "Файл не найден: ",
        "open_manually": "Откройте файл в плеере вручную:\n",
        "confirm_question": (
            "Вы прослушали оба превью и подтверждаете результат?\n"
            "(Подтверждение записывается в папку результата.)"
        ),
        "confirmed_status": "Подтверждено. Можно импортировать в GHTCP.",
        "confirmed_body": (
            "Подтверждено!\n\nДальше: GHTCP → создать песню с ID {sid}\n"
            "chart: notes.chart из папки результата\naudio: song.wav"
        ),
        "donation_window_title": "Поблагодарить автора",
        "donation_text": (
            "Если вам понравилась программа, можете поблагодарить автора\n"
            "любой комфортной суммой.\n\n"
            "Международно — USDT (сеть TON):\n"
            + TON_USDT_ADDRESS + "\n\n"
            "Наведите камеру кошелька на QR-код ниже:"
        ),
        "donation_qr_missing": "(QR-код не найден — адрес выше)",
        "close": "Закрыть",
        "log_error": "ОШИБКА: ",
        "log_stages": "Этапы: сетка → транскрипция → фильтры → маппинг → ревизия → экспорт",
        "log_file": "Файл: ",
        "log_sep": (
            "Сепарация: делю песню на стемы (htdemucs_6s); "
            "ноты — по гитаре, в миксе гитара громче, вокал тише"
        ),
        "log_guitar": "    гитара: ",
        "log_bpm": "    BPM {bpm:.3f} | первая точка {first:.3f} с",
        "log_notes": "    найдено нот: {n}",
        "log_groups": "    групп онсетов: {n} (щелчков убрано: {c})",
        "log_valid": "    валидация: 0 ошибок",
        "log_hard": "    Hard: {n} событий",
        "err_demucs_missing": (
            "Не найдено окружение Demucs: " + str(SEPARATION_PYTHON)
            + " — отделение гитары недоступно на этой машине."
        ),
        "err_demucs_failed": "Demucs не смог разделить песню. Подробности: ",
        "err_no_demucs_output": "нет вывода",
        "err_validation": "Валидация не прошла: ",
    },
}


def resource_path(relative: str) -> Path:
    """Absolute path to a bundled resource (works both from source and PyInstaller).

    Guard: if PyInstaller turned the data entry into a folder of the same
    name (dest without a dot), fall back to the file inside it.
    """
    base = getattr(sys, "_MEIPASS", None)
    path = (Path(base) / relative) if base else (PIPELINE_DIR / relative)
    if path.is_dir():
        inner = path / relative
        if inner.is_file():
            return inner
    return path


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer", str(path)])


def play_in_default_player(path: Path) -> bool:
    """Open a wav in the default player: os.startfile, shell "open", fallback explorer."""
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]  # Windows only
        return True
    except Exception:
        pass
    try:
        if subprocess.run(
            ["cmd", "/c", "start", "", str(path)],
            capture_output=True,
            timeout=10,
        ).returncode == 0:
            return True
    except Exception:
        pass
    try:
        subprocess.Popen(["explorer", "/select,", str(path)])
        return True
    except Exception:
        return False


def bundled_config_path() -> Path:
    """Readable path to config.json.

    In a onefile exe the _MEIPASS extraction is sometimes read-protected by
    antivirus, so prefer a config.json copied next to the exe (written once,
    if missing) and fall back to the bundled copy.
    """
    bundled = resource_path("config.json")
    external = Path(sys.executable).resolve().parent / "config.json"
    if getattr(sys, "frozen", False) and bundled.exists() and not external.exists():
        try:
            shutil.copyfile(bundled, external)
            return external
        except OSError:
            pass
    if external.exists():
        return external
    return bundled


def load_qr_image(filename: str, size: int = 280):
    """Return a Tkinter PhotoImage of a bundled QR image, or None if unavailable."""
    qr_path = resource_path(filename)
    if not qr_path.exists() or Image is None:
        return None
    try:
        image = Image.open(qr_path).convert("RGB")
        image.thumbnail((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(image)
    except Exception:
        return None





def separate_guitar(source: Path, work: Path, lang: str = "ru") -> dict:
    """Split the song into stems with the proven Stage 2 Demucs setup.

    Full 6-stem separation (not two-stems): the guitar stem feeds the
    transcription, while the game mix keeps the song intact with guitar
    pushed forward and vocals pulled back. Returns a dict with both paths.
    """
    if not SEPARATION_PYTHON.exists():
        raise RuntimeError(STRINGS[lang]["err_demucs_missing"])
    out_dir = work / "stems"
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = None
    for device in ("cuda", "cpu"):
        cmd = [
            str(SEPARATION_PYTHON), "-m", "demucs.separate",
            "-n", "htdemucs_6s", "-d", device,
            "-o", str(out_dir), str(source),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, errors="replace",
                timeout=1800 if device == "cpu" else 900,
            )
        except subprocess.TimeoutExpired:
            continue
        if proc.returncode == 0:
            break
    stem_dir = None
    guitar = None
    if proc is not None and proc.returncode == 0:
        # Demucs nests results as <out>/<model_name>/<track>/; find the actual
        # folder instead of hard-coding the model name.
        found = sorted(out_dir.rglob("guitar.wav"))
        if found:
            guitar = found[0]
            stem_dir = guitar.parent
    if guitar is None:
        output = (STRINGS[lang]["err_no_demucs_output"]
                  if proc is None else (proc.stderr or proc.stdout or ""))
        raise RuntimeError(STRINGS[lang]["err_demucs_failed"] + output[-600:])

    import soundfile as sf
    import numpy as np
    vocals, sr_v = sf.read(str(stem_dir / "vocals.wav"), dtype="float32", always_2d=True)
    other, sr_o = sf.read(str(stem_dir / "other.wav"), dtype="float32", always_2d=True)
    bass, sr_b = sf.read(str(stem_dir / "bass.wav"), dtype="float32", always_2d=True)
    drums, sr_d = sf.read(str(stem_dir / "drums.wav"), dtype="float32", always_2d=True)
    guitar_audio, sr_g = sf.read(str(guitar), dtype="float32", always_2d=True)
    length = min(len(vocals), len(other), len(bass), len(drums), len(guitar_audio))

    # Game mix: guitar pushed forward, vocals pulled back, the rest as-is.
    game_mix = (
        1.5 * guitar_audio[:length]
        + other[:length] + bass[:length] + drums[:length]
        + 0.6 * vocals[:length]
    )
    peak = float(np.max(np.abs(game_mix))) if len(game_mix) else 0.0
    if peak > 0.999:
        game_mix *= 0.999 / peak
    mix_path = stem_dir / "game_mix.wav"
    sf.write(str(mix_path), game_mix, sr_v, subtype="PCM_16")
    return {"guitar": guitar, "game_mix": mix_path}


class GuiLog:
    """File-like redirector: everything the pipeline prints goes to the GUI log."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, append) -> None:
        self.append = append
        self.buffer = io.BytesIO()  # some libraries call .buffer
        self.closed = False

    def write(self, text):
        written = len(str(text))
        for line in str(text).splitlines():
            if line.strip():
                self.append(line)
        return written

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return -1

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def close(self) -> None:
        pass


class App(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.lang = "en"  # English by default; RU via the toggle button
        self.title(APP_TITLE)
        self.geometry("860x640")
        self.minsize(760, 480)

        self.source = StringVar()
        self.song_id = StringVar()
        self.song_name = StringVar()
        self.artist = StringVar()
        self.bpm = StringVar()
        self.easier = BooleanVar(value=False)
        self.hardkore = BooleanVar(value=False)
        self.include_hard = BooleanVar(value=True)
        self.separate = BooleanVar(value=False)

        self.pipeline_thread = None
        self.results = None
        self.abort = False

        self._build_ui()

    def tr(self, key: str, **kwargs) -> str:
        template = STRINGS[self.lang][key]
        return template.format(**kwargs) if kwargs else template

    def retext(self) -> None:
        """Re-apply every static label after a language switch."""
        for widget, key in self._i18n_widgets:
            widget.configure(text=self.tr(key))
        self.title(self.tr("title"))
        self.set_status(self.tr("status_idle"))

    # ------------------------------------------------------------ UI layout
    def _build_ui(self) -> None:
        self._i18n_widgets: list[tuple[ttk.Widget, str]] = []

        def widget_with_text(factory, key, **kwargs):
            """Create a ttk widget and register its text for language switching."""
            w = factory(text=self.tr(key), **kwargs)
            self._i18n_widgets.append((w, key))
            return w

        pad = dict(padx=8, pady=4)
        top = ttk.LabelFrame(self, text=self.tr("song_frame"))
        self._i18n_widgets.append((top, "song_frame"))
        top.pack(fill="x", **pad)
        ttk.Label(top, text=self.tr("mp3")).grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.source).grid(row=0, column=1, sticky="ew", **pad)
        widget_with_text(
            lambda **kw: ttk.Button(top, command=self.pick_file, **kw), "open",
        ).grid(row=0, column=2, **pad)
        ttk.Label(top, text=self.tr("song_id")).grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.song_id, width=24).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(top, text=self.tr("name_label")).grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.song_name, width=32).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(top, text=self.tr("artist_label")).grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.artist, width=32).grid(row=3, column=1, sticky="w", **pad)
        top.columnconfigure(1, weight=1)

        adv = ttk.LabelFrame(self, text=self.tr("settings_frame"))
        self._i18n_widgets.append((adv, "settings_frame"))
        adv.pack(fill="x", **pad)
        ttk.Label(adv, text=self.tr("bpm_label")).grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(adv, textvariable=self.bpm, width=8).grid(row=0, column=1, sticky="w", **pad)
        widget_with_text(
            lambda **kw: ttk.Checkbutton(adv, variable=self.easier, **kw), "easier",
        ).grid(row=0, column=2, sticky="w", **pad)
        widget_with_text(
            lambda **kw: ttk.Checkbutton(adv, variable=self.include_hard, **kw), "hard_track",
        ).grid(row=0, column=3, sticky="w", **pad)
        widget_with_text(
            lambda **kw: ttk.Checkbutton(adv, variable=self.separate, **kw), "with_vocals",
        ).grid(row=1, column=0, columnspan=4, sticky="w", **pad)
        widget_with_text(
            lambda **kw: ttk.Checkbutton(adv, variable=self.hardkore, **kw), "hardkore",
        ).grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        hk_hint = ttk.Label(adv, text=self.tr("hardkore_hint"), wraplength=780, justify="left")
        hk_hint.grid(row=3, column=0, columnspan=4, sticky="w")
        self._i18n_widgets.append((hk_hint, "hardkore_hint"))
        sep_hint = ttk.Label(adv, text=self.tr("separation_hint"), wraplength=780, justify="left")
        sep_hint.grid(row=4, column=0, columnspan=4, sticky="w")
        self._i18n_widgets.append((sep_hint, "separation_hint"))

        run = ttk.Frame(self)
        run.pack(fill="x", **pad)
        self.convert_button = widget_with_text(
            lambda **kw: ttk.Button(run, command=self.start_pipeline, **kw), "convert",
        )
        self.convert_button.pack(side="left", **pad)
        self.progress = ttk.Progressbar(run, mode="indeterminate", length=220)
        self.progress.pack(side="left", padx=8)
        self.status = ttk.Label(run, text=self.tr("status_idle"))
        self.status.pack(side="left")

        logf = ttk.LabelFrame(self, text=self.tr("log_frame"))
        self._i18n_widgets.append((logf, "log_frame"))
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk_text = ttk.Frame(logf)
        self.log.pack(fill="both", expand=True)
        import tkinter.scrolledtext as st

        self.log_text = st.ScrolledText(self.log, height=6, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        post = ttk.LabelFrame(self, text=self.tr("check_frame"))
        self._i18n_widgets.append((post, "check_frame"))
        post.pack(fill="x", **pad)
        self.listen_grid = widget_with_text(
            lambda **kw: ttk.Button(
                post, state="disabled",
                command=lambda: self.open_preview("grid_preview.wav"), **kw,
            ), "listen_grid",
        )
        self.listen_grid.grid(row=0, column=0, **pad)
        self.listen_notes = widget_with_text(
            lambda **kw: ttk.Button(
                post, state="disabled",
                command=lambda: self.open_preview("notes_preview.wav"), **kw,
            ), "listen_notes",
        )
        self.listen_notes.grid(row=0, column=1, **pad)
        self.confirm_button = widget_with_text(
            lambda **kw: ttk.Button(post, command=self.confirm, **kw), "confirm",
        )
        self.confirm_button.grid(row=0, column=2, **pad)
        self.open_out = widget_with_text(
            lambda **kw: ttk.Button(
                post, state="disabled",
                command=lambda: open_folder(Path(self.results["out"])), **kw,
            ), "open_out",
        )
        self.open_out.grid(row=0, column=3, **pad)
        out_hint = ttk.Label(post, text=self.tr("out_hint"))
        out_hint.grid(row=1, column=0, columnspan=4, sticky="w", **pad)
        self._i18n_widgets.append((out_hint, "out_hint"))

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", **pad)
        self.lang_button = ttk.Button(
            bottom, text=self.tr("lang_button"), width=6,
            command=self.toggle_language,
        )
        self.lang_button.pack(side="left", padx=6, pady=2)
        donate = widget_with_text(
            lambda **kw: ttk.Button(bottom, command=self.show_donation,
                                    padding=(18, 10), **kw),
            "donate",
        )
        # ttk.Buttons don't take a font directly; style the text bold+large.
        style = ttk.Style()
        style.configure("Donate.TButton", font=("Segoe UI", 11, "bold"))
        donate.configure(style="Donate.TButton")
        donate.pack(side="right", padx=6, pady=2)
        self.confirm_button.state([])  # always available

    def toggle_language(self) -> None:
        self.lang = "ru" if self.lang == "en" else "en"
        self.lang_button.configure(text=self.tr("lang_button"))
        self.retext()

    # ----------------------------------------------------------- actions
    def log_line(self, text: str) -> None:
        def append() -> None:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", text + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        self.after(0, append)

    def set_status(self, text: str) -> None:
        self.after(0, lambda: self.status.configure(text=text))

    def pick_file(self) -> None:
        path = filedialog.askopenfilename(
            title=self.tr("file_dialog_title"),
            filetypes=[
                (self.tr("filetype_audio"), "*.mp3 *.wav *.flac *.ogg"),
                (self.tr("filetype_mp3"), "*.mp3"),
                (self.tr("filetype_all"), "*.*"),
            ],
        )
        if path:
            self.source.set(path)

    def validate_inputs(self) -> str | None:
        if not self.source.get().strip():
            return self.tr("err_no_file")
        if not Path(self.source.get().strip()).exists():
            return self.tr("err_not_found") + self.source.get()
        song_id = self.song_id.get().strip()
        if not SONG_ID_RE.fullmatch(song_id):
            return self.tr("err_bad_id")
        if self.bpm.get().strip():
            try:
                value = float(self.bpm.get().replace(",", "."))
                if not 40 <= value <= 240:
                    return self.tr("err_bad_bpm")
            except ValueError:
                return self.tr("err_bpm_nan")
        return None

    def start_pipeline(self) -> None:
        error = self.validate_inputs()
        if error:
            messagebox.showwarning(APP_TITLE, error)
            return
        self.convert_button.configure(state="disabled")
        self.listen_grid.configure(state="disabled")
        self.listen_notes.configure(state="disabled")
        self.open_out.configure(state="disabled")
        self.results = None
        self.progress.start(12)
        self.set_status(self.tr("converting"))
        self.pipeline_thread = threading.Thread(target=self.run_pipeline, daemon=True)
        self.pipeline_thread.start()

    def run_pipeline(self) -> None:
        original_out, original_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = GuiLog(self.log_line)
        try:
            source = Path(self.source.get().strip())
            song_id = self.song_id.get().strip()
            out_root = Path(DEFAULT_OUT_ROOT)
            work_root = Path(DEFAULT_WORK_ROOT)
            out = out_root / song_id
            work = work_root / song_id
            out.mkdir(parents=True, exist_ok=True)
            work.mkdir(parents=True, exist_ok=True)

            stems = None
            source_file = source  # original file: game audio stays the real song
            if self.separate.get():
                self.set_status(self.tr("status_sep"))
                self.log_line(self.tr("log_sep"))
                stems = separate_guitar(source, work, self.lang)
                self.log_line(self.tr("log_guitar") + str(stems["guitar"]))
                source = stems["guitar"]  # transcription and grid run on the stem

            self.log_line(f"=== {APP_TITLE} ===")
            self.log_line(self.tr("log_file") + str(source))
            self.log_line(f"ID: {song_id}")
            self.log_line(self.tr("log_stages"))
            self.set_status(self.tr("status_grid"))

            config = make_song.load_config(bundled_config_path())
            if self.easier.get():
                config["expert"]["min_gap_seconds"] = 0.114
            if self.hardkore.get():
                self.log_line("Hardkore mode: dense transcription, lane repeats kept, 40 ms min gap")
                config["expert"].update({
                    "min_gap_seconds": 0.040,
                    "validate_min_gap_seconds": 0.040,
                })
                config["transcription"]["minimum_note_length_ms"] = 60.0
                config["expert"]["hardkore_keep_repeats"] = True
            if self.bpm.get().strip():
                config["expert"]["user_bpm"] = float(self.bpm.get().replace(",", "."))

            stage = make_song.Stage()
            grid = stage.run("grid", make_song.stage_grid, source, work, config)
            user_bpm = config["expert"].pop("user_bpm", None)
            if user_bpm:
                grid["bpm"] = user_bpm
                grid["status"] = "constant_grid_user_override"
            self.log_line(self.tr("log_bpm", bpm=grid["bpm"], first=grid["first_grid_point_seconds"]))
            self.set_status(self.tr("status_transcribe"))

            transcription = stage.run("transcribe", make_song.stage_transcribe, source, work, config)
            self.log_line(self.tr("log_notes", n=transcription["note_count"]))
            self.set_status(self.tr("status_filters"))

            filtered = stage.run("filter", make_song.stage_filter, transcription, work, config)
            groups = stage.run("group", make_song.stage_group, filtered, work, config)
            self.log_line(self.tr("log_groups", n=len(groups["groups"]), c=groups["clicks_removed"]))
            self.set_status(self.tr("status_map"))

            mapping = stage.run("map", make_song.stage_map, groups, work, config)
            gameplay = stage.run("gameplay", make_song.stage_gameplay, mapping, groups, grid, work, config)
            gameplay["_group_list"] = groups["groups"]
            self.set_status(self.tr("status_revise"))

            revised = stage.run("revise", make_song.stage_revise, gameplay, work, config)
            validation = stage.run("validate", make_song.stage_validate, revised,
                                   grid["duration_seconds"], config)
            make_song.write_json(work / "validation.json", validation)
            if validation["status"] != "pass":
                raise RuntimeError(
                    self.tr("err_validation") + "; ".join(validation["errors"][:5])
                )
            self.log_line(self.tr("log_valid"))
            self.set_status(self.tr("status_audio"))

            audio = stage.run(
                "audio", make_song.stage_audio,
                stems["game_mix"] if stems else source_file, out, config,
            )
            self.set_status(self.tr("status_export"))

            name = self.song_name.get().strip() or song_id
            artist = self.artist.get().strip() or "Unknown Artist"
            report = stage.run(
                "export", make_song.stage_export, revised, grid, audio, out,
                config, song_id, name, artist,
            )
            if self.include_hard.get():
                self.set_status(self.tr("status_hard"))
                hard = stage.run("hard", make_song.stage_hard, gameplay, groups, grid, work, config)
                hard_report = stage.run(
                    "export-hard", make_song.export_hard_track, hard, grid, audio,
                    out, config, song_id, name, artist,
                )
                report["hard_track"] = hard_report
                self.log_line(self.tr("log_hard", n=hard_report["gameplay_events"]))
            self.set_status(self.tr("status_preview"))

            make_song.write_json(work / "pipeline_summary.json", {
                "song_id": song_id,
                "grid": {k: grid[k] for k in ("bpm", "first_grid_point_seconds", "status")},
                "counts": {
                    "notes_raw": transcription["note_count"],
                    "notes_filtered": filtered["output"],
                    "clicks_removed": groups["clicks_removed"],
                    "events_final": len(revised["events"]),
                },
                "validation": validation["status"],
                "export": report,
            })
            make_notes_preview(source, revised, groups, work)

            self.results = {"out": str(out), "work": str(work), "song_id": song_id}
            self.after(0, self.pipeline_done)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            self.log_line(self.tr("log_error") + message)
            self.log_line(traceback.format_exc(limit=6))
            self.after(0, lambda err=message: self.pipeline_failed(err))
        finally:
            sys.stdout, sys.stderr = original_out, original_err

    def pipeline_done(self) -> None:
        self.progress.stop()
        self.convert_button.configure(state="normal")
        self.listen_grid.configure(state="normal")
        self.listen_notes.configure(state="normal")
        self.open_out.configure(state="normal")
        self.set_status(self.tr("done_status"))
        messagebox.showinfo(
            self.tr("done_title"),
            self.tr("done_body", out=self.results["out"]),
        )

    def pipeline_failed(self, message: str) -> None:
        self.progress.stop()
        self.convert_button.configure(state="normal")
        self.set_status(self.tr("failed_status"))
        messagebox.showerror(APP_TITLE, self.tr("failed_title") + message)

    def open_preview(self, filename: str) -> None:
        if not self.results:
            return
        path = Path(self.results["work"]) / filename
        if not path.exists():
            messagebox.showwarning(APP_TITLE, self.tr("file_missing") + str(path))
            return
        if not play_in_default_player(path):
            messagebox.showinfo(
                APP_TITLE,
                self.tr("open_manually") + str(path),
            )


    def confirm(self) -> None:
        if not self.results:
            return
        if not messagebox.askyesno(APP_TITLE, self.tr("confirm_question")):
            return
        out = Path(self.results["out"])
        (out / "previews_confirmed.json").write_text(
            json.dumps(
                {
                    "song_id": self.results["song_id"],
                    "confirmed_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.set_status(self.tr("confirmed_status"))
        messagebox.showinfo(
            APP_TITLE,
            self.tr("confirmed_body", sid=self.results["song_id"]),
        )

    def show_donation(self) -> None:
        # Child window of the app (Toplevel, NOT a second Tk()): a PhotoImage
        # belongs to the main interpreter and will not render in an
        # independent Tk() — that is why the QR was blank before.
        win = Toplevel(self)
        win.title(self.tr("donation_window_title"))
        win.resizable(False, False)
        ttk.Label(
            win, text=self.tr("donation_text"), justify="center",
            font=("Segoe UI", 10, "bold"),
        ).pack(padx=20, pady=(16, 8))
        photo = None
        for qr_name in ("ton_qr.png", "donation_qr.jpg"):
            photo = load_qr_image(qr_name, 380)
            if photo is not None:
                break
        if photo is not None:
            ttk.Label(win, image=photo).pack(pady=6)
            win._qr_keepalive = photo  # prevent garbage collection of the image
        else:
            ttk.Label(
                win,
                text=self.tr("donation_qr_missing"),
                justify="center",
            ).pack(pady=10)
        ttk.Button(win, text=self.tr("close"), command=win.destroy).pack(pady=(6, 14))
        # Size the window to its contents now that everything is laid out.
        win.update_idletasks()
        win.geometry(f"+{self.winfo_rootx() + 60}+{self.winfo_rooty() + 40}")


def make_notes_preview(source: Path, revised: dict, groups: dict, work: Path) -> None:
    """Synthesize the found notes as clean tones (the second listening check)."""
    import numpy as np
    import soundfile as sf

    audio_data, sr = sf.read(str(source), dtype="float32", always_2d=True)
    reference = audio_data.mean(axis=1)
    synth = np.zeros(len(reference), dtype=np.float64)
    group_list = groups["groups"]
    for event in revised["events"]:
        group = group_list[event["source_group_index"]]
        for note in group["notes"]:
            start = max(0, round(note["start_seconds"] * sr))
            end = min(len(synth), round(note["end_seconds"] * sr))
            length = end - start
            if length <= 0:
                continue
            frequency = 440 * 2 ** ((note["midi_pitch"] - 69) / 12)
            t = np.arange(length) / sr
            tone = np.sin(2 * np.pi * frequency * t)
            envelope = np.ones(length)
            attack = min(round(0.005 * sr), length // 2)
            release = min(round(0.020 * sr), length // 2)
            if attack:
                envelope[:attack] = np.linspace(0, 1, attack)
            if release:
                envelope[-release:] = np.linspace(1, 0, release)
            synth[start:end] += tone * envelope * float(note["amplitude"])
    ref_rms = float(np.sqrt(np.mean(reference.astype(np.float64) ** 2)))
    syn_rms = float(np.sqrt(np.mean(synth ** 2)))
    if min(ref_rms, syn_rms) > 1e-8:
        reference = reference / ref_rms
        synth = synth / syn_rms
        peak = max(float(np.max(np.abs(reference))), float(np.max(np.abs(synth))))
        scale = min(0.1, 0.95 / peak)
        sf.write(str(work / "notes_preview.wav"), synth * scale, sr, subtype="PCM_16")


def run_selftest() -> int:
    """Hidden mode: `exe --selftest <mp3> <song_id>` converts headless and
    writes D:\ai-gh\pipeline\selftest_result.txt. Used to verify the frozen
    exe end-to-end without touching the UI."""
    result_path = Path(r"D:\ai-gh\pipeline\selftest_result.txt")  # NOT _MEIPASS
    mp3 = sys.argv[2] if len(sys.argv) > 2 else ""
    song_id = sys.argv[3] if len(sys.argv) > 3 else "selftest"
    status, detail = "FAIL", "unknown"
    result_path.write_text("RUNNING\n", encoding="utf-8")
    log_lines: list[str] = []
    probe: list[str] = []  # diagnose _MEIPASS readability in the frozen exe
    try:
        import os as _os
        base = Path(getattr(sys, "_MEIPASS", "."))
        probe.append(f"_MEIPASS={base} frozen={getattr(sys, 'frozen', False)}")
        entries = sorted(_os.listdir(base))[:40]
        probe.append("root entries: " + ", ".join(entries))
        for rel in ("config.json", "donation_qr.jpg", "ton_qr.png"):
            p = base / rel
            kind = "DIR" if p.is_dir() else ("FILE" if p.is_file() else "MISSING")
            inner = sorted(_os.listdir(p))[:10] if p.is_dir() else "-"
            head = "-"
            if p.is_file():
                try:
                    with open(p, "rb") as fh:
                        head = fh.read(8).hex()
                except Exception as e:
                    head = f"READ_FAIL:{type(e).__name__}"
            probe.append(f"{rel}: {kind} inner={inner} read8={head}")
        bp = base / "basic_pitch" / "saved_models" / "icassp_2022" / "nmp"
        probe.append(f"nmp: exists={bp.exists()} inner={sorted(_os.listdir(bp))[:8] if bp.exists() else '-'}")
    except Exception as e:
        probe.append(f"probe failed: {type(e).__name__}: {e}")
    try:
        messagebox.showinfo = lambda *a, **k: None
        messagebox.showerror = lambda *a, **k: None
        messagebox.showwarning = lambda *a, **k: None
        app = App()
        app.withdraw()
        app.log_line = log_lines.append  # collect synchronously (no mainloop)
        app.source.set(mp3)
        app.song_id.set(song_id)
        if len(sys.argv) > 4 and sys.argv[4] == "separate":
            app.separate.set(True)  # exercise the Demucs path too
        if "--hardkore" in sys.argv[4:]:
            app.hardkore.set(True)  # exercise the hardkore path too
        app.run_pipeline()  # synchronous in selftest
        if app.results and (Path(app.results["out"]) / "notes.chart").exists():
            status, detail = "OK", app.results["out"]
        app.destroy()
    except Exception:  # noqa: BLE001
        detail = traceback.format_exc(limit=10)
    if status == "OK":
        result_path.write_text(f"{status}\n{detail}\n", encoding="utf-8")
    else:
        result_path.write_text(
            f"{status}\n{detail}\n\n--- PROBE ---\n" + "\n".join(probe)
            + "\n\n--- GUI LOG TAIL ---\n"
            + "\n".join(log_lines[-60:]) + "\n",
            encoding="utf-8",
        )
    return 0 if status == "OK" else 1


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())
    main()
