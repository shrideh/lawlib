# pyinstaller --noconfirm --onefile --windowed --icon=ico.ico pdf_processor_gui.py
import sys
import os
from pathlib import Path
import json
import logging
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QHBoxLayout, QSpinBox, QWidget,
    QFormLayout, QLineEdit, QMessageBox, QTabWidget, QPlainTextEdit
)
from PyQt5.QtCore import pyqtSignal, QThread, QObject, Qt
import concurrent.futures

# ---- Determine Base Directory ----
# If frozen by PyInstaller, use the executable's folder, else use script's folder
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# ---- Logging Configuration ----
LOG_DIR = BASE_DIR / 'log'
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / 'pdf_processing_errors.log'
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

# ---- Config Management ----
# Store config.json next to the executable/script (writable in frozen app) or
# optionally move to user directory (e.g., Path.home()/'.myapp')
CONFIG_FILE = BASE_DIR / 'config.json'


def load_config():
    default = {
        "data_dir": str(BASE_DIR),
        "index_dir": str(BASE_DIR / 'indexdir'),
        "nlp_dir": str(BASE_DIR / 'nlp'),
        "pdf_json_dir": str(BASE_DIR / 'PDF_JSON')
    }
    if not CONFIG_FILE.exists():
        save_config(default)
        return default
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        # ensure all keys exist
        for k, v in default.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception as e:
        logging.error(f"Failed loading config: {e}")
        save_config(default)
        return default


def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Failed saving config: {e}")

# Load and prepare directories
CONFIG = load_config()
for key in ('index_dir', 'pdf_json_dir'):
    try:
        Path(CONFIG[key]).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logging.error(f"Failed creating directory for {key}: {e}")


# ---- PDF Filtering Function ----
def filter_unique_pdfs(folder_path, index_dir, log_func=lambda msg: None):
    from main_pdf_processor import calculate_sha512, sha512_exists_in_index
    seen_shas = set()
    unique_files = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            if not file.lower().endswith(".pdf"):
                continue
            fp = os.path.join(root, file)
            sha = calculate_sha512(fp)
            if sha in seen_shas or sha512_exists_in_index(index_dir, sha):
                log_func(f"⚠️ تخطي مكرر: {fp}")
                continue
            seen_shas.add(sha)
            unique_files.append(fp)
    return unique_files

# ---- Worker ----
class Worker(QObject):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, folder_path, index_dir, max_workers, pdf_json_dir):
        super().__init__()
        self.folder_path = folder_path
        self.index_dir = index_dir
        self.pdf_json_dir = pdf_json_dir
        self.max_workers = max_workers
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def run(self):
        from main_pdf_processor import process_pdf
        try:
            files = filter_unique_pdfs(self.folder_path, self.index_dir, log_func=self.status.emit)
            total = len(files)
            if total == 0:
                self.status.emit("لا توجد ملفات جديدة للمعالجة.")
                self.finished.emit(True)
                return
            done = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                futures = {ex.submit(process_pdf, f, self.index_dir): f for f in files}
                for fut in concurrent.futures.as_completed(futures):
                    if self.stop_requested:
                        self.finished.emit(False)
                        return
                    fut.result()
                    done += 1
                    pct = int(done / total * 100)
                    self.progress.emit(pct)
                    self.status.emit(f"{pct}% مكتمل...")
            self.finished.emit(True)
        except Exception as e:
            self.status.emit(f"❌ خطأ أثناء المعالجة: {e}")
            logging.error(f"Worker run error: {e}")
            self.finished.emit(False)

# ---- Settings Dialog ----
class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إعدادات التطبيق")
        self.cfg = cfg.copy()
        layout = QFormLayout()
        self.inputs = {}
        for key in ('data_dir', 'index_dir', 'nlp_dir', 'pdf_json_dir'):
            line = QLineEdit(self.cfg[key])
            btn = QPushButton("...")
            btn.clicked.connect(lambda _, k=key, w=line: self.select_dir(k, w))
            hl = QHBoxLayout(); hl.addWidget(line); hl.addWidget(btn)
            layout.addRow(QLabel(key), hl)
            self.inputs[key] = line
        btn_save = QPushButton("حفظ"); btn_save.clicked.connect(self.save)
        layout.addRow(btn_save)
        self.setLayout(layout)

    def select_dir(self, key, widget):
        d = QFileDialog.getExistingDirectory(self, f"اختر {key}")
        if d: widget.setText(d)

    def save(self):
        for key, widget in self.inputs.items():
            if not Path(widget.text()).is_dir():
                QMessageBox.warning(self, "خطأ", f"المسار غير صالح: {widget.text()}")
                return
            self.cfg[key] = widget.text()
        save_config(self.cfg)
        QMessageBox.information(self, "تم الحفظ", "تم تحديث الإعدادات بنجاح.")
        self.accept()

# ---- Main Dialog ----
class PDFProcessingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("معالجة ملفات PDF")
        self.setMinimumSize(600, 400)
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget(); self.layout.addWidget(self.tabs)
        # Processing Tab
        proc = QWidget(); lp = QVBoxLayout(proc)
        self.lbl = QLabel("اختر مجلد PDF:"); lp.addWidget(self.lbl)
        btn_folder = QPushButton("📁 اختر المجلد"); btn_folder.clicked.connect(self.select_folder); lp.addWidget(btn_folder)
        h = QHBoxLayout(); h.addWidget(QLabel("عدد العمال:")); self.spin = QSpinBox(); self.spin.setRange(1,32); self.spin.setValue(5); h.addLayout(h); lp.addLayout(h)
        btns = QHBoxLayout(); self.btn_start=QPushButton("🚀 ابدأ"); self.btn_start.setEnabled(False); self.btn_start.clicked.connect(self.start); btns.addWidget(self.btn_start)
        self.btn_stop=QPushButton("🛑 إيقاف"); self.btn_stop.setEnabled(False); self.btn_stop.clicked.connect(self.stop); btns.addWidget(self.btn_stop); lp.addLayout(btns)
        self.bar = QProgressBar(); lp.addWidget(self.bar)
        self.console = QPlainTextEdit(); self.console.setReadOnly(True); self.console.setFixedHeight(150); lp.addWidget(self.console)
        proc.setLayout(lp); self.tabs.addTab(proc, "معالجة")
        sett = QWidget(); ls = QVBoxLayout(sett); b = QPushButton("فتح إعدادات"); b.clicked.connect(self.open_settings); ls.addWidget(b); sett.setLayout(ls); self.tabs.addTab(sett, "إعدادات")
        self.folder = None; self.worker=None; self.thread=None

    def select_folder(self):
        d = QFileDialog.getExistingDirectory(self, "اختر مجلد PDF")
        if d:
            self.folder=d; self.lbl.setText(f"📂 {d}"); self.btn_start.setEnabled(True)

    def start(self):
        self.console.clear()
        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True)
        self.bar.setValue(0); self.lbl.setText("🔄 جاري المعالجة...")
        self.worker = Worker(self.folder, CONFIG['index_dir'], self.spin.value(), CONFIG['pdf_json_dir'])
        self.thread = QThread();
        self.worker.moveToThread(self.thread)
        # Clean up thread after done
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)

        # Connect signals
        self.worker.progress.connect(self.bar.setValue)
        self.worker.status.connect(self.append_console)
        self.worker.status.connect(self.lbl.setText)
        self.worker.finished.connect(self.on_finished)

        self.thread.started.connect(self.worker.run)
        self.thread.start()

    def stop(self):
        if self.worker:
            self.worker.stop(); self.lbl.setText("⏹ طلب إيقاف...")
            self.btn_stop.setEnabled(False)
            # Ensure thread quits
            if self.thread:
                self.thread.quit()
                self.thread.wait()

    def on_finished(self, ok):
        msg = "✅ انتهى بنجاح" if ok else "⛔ تم الإيقاف"
        self.lbl.setText(msg)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        # Ensure thread is cleaned up
        if self.thread:
            self.thread.wait()
            self.thread = None
            self.worker = None

    def append_console(self, msg):
        self.console.appendPlainText(msg)

    def open_settings(self):
        dlg = SettingsDialog(CONFIG, self)
        if dlg.exec_(): self.reload_config()

    def reload_config(self):
        global CONFIG
        CONFIG = load_config()

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            self.worker.stop()
            self.thread.quit()
            self.thread.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    window = PDFProcessingDialog()
    window.show()
    sys.exit(app.exec_())