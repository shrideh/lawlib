import sys
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox,
    QProgressBar, QHBoxLayout, QSpinBox
)
from PyQt5.QtCore import pyqtSignal, QThread, QObject
import os
import concurrent.futures

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DATA_DIR = APP_DIR
DEFAULT_INDEX_DIR = os.path.join(DEFAULT_DATA_DIR, "indexdir")
index_dir = DEFAULT_INDEX_DIR

def filter_unique_pdfs(folder_path, index_dir, log_func=lambda msg: None):
    from main_pdf_script import calculate_sha512, sha512_exists_in_index
    seen_shas = set()
    unique_files = []

    for root, _, files in os.walk(folder_path):
        for file in files:
            if not file.lower().endswith(".pdf"):
                continue

            filepath = os.path.join(root, file)
            sha = calculate_sha512(filepath)

            if sha in seen_shas:
                log_func(f"🚫 تخطي ملف مكرر داخليًا: {filepath}")
                continue

            if sha512_exists_in_index(index_dir, sha):
                log_func(f"⚠️ تخطي ملف مكرر في الفهرس: {filepath}")
                continue

            seen_shas.add(sha)
            unique_files.append(filepath)

    return unique_files

class Worker(QObject):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, folder_path, index_dir, max_workers):
        super().__init__()
        self.folder_path = folder_path
        self.index_dir = index_dir
        self.max_workers = max_workers
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def run(self):
        from main_pdf_script import process_pdf
        from LawLib import IndexThread
        try:
            pdf_files = filter_unique_pdfs(self.folder_path, self.index_dir, log_func=self.status.emit)
            total = len(pdf_files)
            if total == 0:
                self.status.emit("لا توجد ملفات جديدة للمعالجة.")
                self.finished.emit(True)
                return

            processed = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(process_pdf, fp, self.index_dir): fp
                    for fp in pdf_files
                }
                for future in concurrent.futures.as_completed(futures):
                    if self.stop_requested:
                        self.finished.emit(False)
                        return
                    future.result()
                    processed += 1
                    progress = int((processed / total) * 100)
                    self.progress.emit(progress)

            self.status.emit("⏳ جاري الفهرسة النهائية...")
            index_thread = IndexThread("PDF_JSON", self.index_dir)
            index_thread.progress.connect(self.progress.emit)
            index_thread.done.connect(lambda success: self.finished.emit(True))
            index_thread.start()

        except Exception as e:
            self.status.emit("❌ حدث خطأ أثناء المعالجة.")
            self.finished.emit(False)

class PDFProcessingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("معالجة ملفات PDF")
        self.setMinimumSize(400, 200)
        self.layout = QVBoxLayout()
        self.label = QLabel("اختر مجلد يحتوي على ملفات PDF:")
        self.layout.addWidget(self.label)

        self.select_btn = QPushButton("📁 اختر المجلد")
        self.select_btn.clicked.connect(self.select_folder)
        self.layout.addWidget(self.select_btn)

        workers_layout = QHBoxLayout()
        workers_label = QLabel("عدد العمال:")
        self.workers_spinbox = QSpinBox()
        self.workers_spinbox.setRange(1, 32)
        self.workers_spinbox.setValue(5)
        workers_layout.addWidget(workers_label)
        workers_layout.addWidget(self.workers_spinbox)
        self.layout.addLayout(workers_layout)

        self.process_btn = QPushButton("🚀 ابدأ المعالجة")
        self.process_btn.setEnabled(False)
        self.process_btn.clicked.connect(self.start_processing)

        self.stop_btn = QPushButton("🛑 إيقاف")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_processing)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.process_btn)
        buttons_layout.addWidget(self.stop_btn)
        self.layout.addLayout(buttons_layout)

        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)

        self.setLayout(self.layout)

        self.folder_path = ""
        self.worker_thread = None
        self.worker = None

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "اختر مجلد PDF")
        if folder:
            self.folder_path = folder
            self.label.setText(f"📂 المجلد المحدد:\n{folder}")
            self.process_btn.setEnabled(True)

    def start_processing(self):
        self.process_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.label.setText("🔄 جاري المعالجة...")

        self.worker = Worker(
            self.folder_path,
            index_dir,
            self.workers_spinbox.value()
        )
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)

        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self.label.setText)
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.started.connect(self.worker.run)

        self.worker_thread.start()

    def stop_processing(self):
        if self.worker:
            self.worker.stop()
        self.label.setText("⏹ تم طلب إيقاف المعالجة...")
        self.stop_btn.setEnabled(False)

    def on_finished(self, completed):
        if completed:
            self.label.setText("✅ تم الانتهاء من المعالجة.")
        else:
            self.label.setText("⛔ تم إيقاف المعالجة قبل الانتهاء.")
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
