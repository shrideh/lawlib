
import sys
import os
import json
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QHBoxLayout, QSpinBox, QWidget,
    QFormLayout, QLineEdit, QMessageBox, QTabWidget
)
from PyQt5.QtCore import pyqtSignal, QThread, QObject, Qt
import concurrent.futures

# ---- Config Management ----
CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'config.json'
)
def load_config():
    default = {
        "data_dir": os.path.dirname(os.path.abspath(__file__)),
        "index_dir": os.path.join(os.getcwd(), 'indexdir'),
        "nlp_dir": os.path.join(os.getcwd(), 'nlp'),
        "pdf_json_dir": os.path.join(os.getcwd(), 'PDF_JSON')
    }
    if not os.path.exists(CONFIG_FILE):
        save_config(default)
        return default
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        # ensure keys
        for k, v in default.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        save_config(default)
        return default

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Failed saving config: {e}")

# Load config globally
CONFIG = load_config()

# Ensure directories from config
for key in ('index_dir', 'pdf_json_dir'):
    os.makedirs(CONFIG[key], exist_ok=True)

# ---- PDF Filtering Function ----
def filter_unique_pdfs(folder_path, index_dir, log_func=lambda msg: None):
    from main_pdf_processor import calculate_sha512, sha512_exists_in_index
    seen_shas = set()
    unique_files = []
    
    for root, _, files in os.walk(folder_path):
        for file in files:
            if not file.lower().endswith(".pdf"):
                continue
            filepath = os.path.join(root, file)
            sha = calculate_sha512(filepath)
            if sha in seen_shas:
                log_func(f"🚫 تخطي مكرر داخلي: {filepath}")
                continue
            if sha512_exists_in_index(index_dir, sha):
                log_func(f"⚠️ تخطي مكرر في الفهرس: {filepath}")
                continue
            seen_shas.add(sha)
            unique_files.append(filepath)
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
            pdf_files = filter_unique_pdfs(self.folder_path, self.index_dir, log_func=self.status.emit)
            total = len(pdf_files)
            if total == 0:
                self.status.emit("لا توجد ملفات جديدة للمعالجة.")
                self.finished.emit(True)
                return

            processed = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(process_pdf, fp, self.index_dir): fp for fp in pdf_files}
                for future in concurrent.futures.as_completed(futures):
                    if self.stop_requested:
                        self.finished.emit(False)
                        return
                    future.result()
                    processed += 1
                    self.progress.emit(int(processed/total*100))


        except Exception as e:
            self.status.emit(f"❌ خطأ أثناء المعالجة: {e}")
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
            line = QLineEdit(self.cfg.get(key, ''))
            btn = QPushButton("..." )
            def _select(path_key=key, widget=line):
                folder = QFileDialog.getExistingDirectory(self, f"اختر {path_key}")
                if folder:
                    widget.setText(folder)
            btn.clicked.connect(_select)
            hl = QHBoxLayout(); hl.addWidget(line); hl.addWidget(btn)
            layout.addRow(QLabel(key.replace('_',' ').title()), hl)
            self.inputs[key] = line
        save_btn = QPushButton("حفظ")
        save_btn.clicked.connect(self.save)
        layout.addRow(save_btn)
        self.setLayout(layout)

    def save(self):
        for key, widget in self.inputs.items():
            val = widget.text().strip()
            if not os.path.isdir(val):
                QMessageBox.warning(self, "خطأ", f"المسار غير صالح: {val}")
                return
            self.cfg[key] = val
        save_config(self.cfg)
        QMessageBox.information(self, "تم الحفظ", "تم تحديث الإعدادات بنجاح.")
        self.accept()

# ---- Main Dialog ----
class PDFProcessingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("معالجة ملفات PDF")
        self.setMinimumSize(450, 250)
        main_layout = QVBoxLayout()
        # Tabs
        tabs = QTabWidget()
        # Processing Tab
        proc_tab = QWidget(); proc_layout = QVBoxLayout()
        self.label = QLabel("اختر مجلد PDF:")
        proc_layout.addWidget(self.label)
        self.select_btn = QPushButton("📁 اختر المجلد")
        self.select_btn.clicked.connect(self.select_folder)
        proc_layout.addWidget(self.select_btn)
        workers_layout = QHBoxLayout()
        workers_layout.addWidget(QLabel("عدد العمال:"))
        self.workers_spinbox = QSpinBox(); self.workers_spinbox.setRange(1,32); self.workers_spinbox.setValue(5)
        workers_layout.addWidget(self.workers_spinbox); proc_layout.addLayout(workers_layout)
        btns = QHBoxLayout()
        self.process_btn = QPushButton("🚀 ابدأ")
        self.process_btn.setEnabled(False); self.process_btn.clicked.connect(self.start_processing)
        self.stop_btn = QPushButton("🛑 إيقاف")
        self.stop_btn.setEnabled(False); self.stop_btn.clicked.connect(self.stop_processing)
        btns.addWidget(self.process_btn); btns.addWidget(self.stop_btn); proc_layout.addLayout(btns)
        self.progress_bar = QProgressBar(); proc_layout.addWidget(self.progress_bar)
        proc_tab.setLayout(proc_layout)
        # Settings Tab
        settings_tab = QWidget(); settings_layout = QVBoxLayout()
        settings_btn = QPushButton("فتح إعدادات")
        settings_btn.clicked.connect(self.open_settings)
        settings_layout.addWidget(settings_btn); settings_tab.setLayout(settings_layout)
        # Add Tabs
        tabs.addTab(proc_tab, "معالجة")
        tabs.addTab(settings_tab, "إعدادات")
        main_layout.addWidget(tabs)
        self.setLayout(main_layout)
        # State
        self.folder_path = ''
        self.worker = None; self.worker_thread = None

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "اختر مجلد PDF")
        if folder:
            self.folder_path = folder; self.label.setText(f"📂 {folder}")
            self.process_btn.setEnabled(True)

    def start_processing(self):
        self.process_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0); self.label.setText("🔄 جاري المعالجة...")
        self.worker = Worker(self.folder_path, CONFIG['index_dir'], self.workers_spinbox.value(), CONFIG['pdf_json_dir'])
        self.worker_thread = QThread(); self.worker.moveToThread(self.worker_thread)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self.label.setText)
        self.worker.finished.connect(self.on_finished);
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()

    def stop_processing(self):
        if self.worker: self.worker.stop()
        self.label.setText("⏹ طلب إيقاف..."); self.stop_btn.setEnabled(False)

    def on_finished(self, completed):
        msg = "✅ انتهى بنجاح" if completed else "⛔ تم الإيقاف"
        self.label.setText(msg); self.process_btn.setEnabled(True); self.stop_btn.setEnabled(False)

    def open_settings(self):
        global CONFIG
        dlg = SettingsDialog(CONFIG, self)
        if dlg.exec_():
            CONFIG = load_config()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    window = PDFProcessingDialog()
    window.show()
    sys.exit(app.exec_())
