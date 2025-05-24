import sys
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox,
    QProgressBar, QHBoxLayout, QSpinBox
)
from PyQt5.QtCore import pyqtSignal
import os
import concurrent.futures
import threading

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DATA_DIR = APP_DIR
DEFAULT_INDEX_DIR = os.path.join(DEFAULT_DATA_DIR, "indexdir")
index_dir = DEFAULT_INDEX_DIR


class PDFProcessingDialog(QDialog):
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

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
        self.stop_requested = False

        # ربط الإشارات
        self.progress_signal.connect(self.progress_bar.setValue)
        self.status_signal.connect(self.label.setText)
        self.finished_signal.connect(self.on_finished)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "اختر مجلد PDF")
        if folder:
            self.folder_path = folder
            self.label.setText(f"📂 المجلد المحدد:\n{folder}")
            self.process_btn.setEnabled(True)

    def start_processing(self):
        self.stop_requested = False
        self.process_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_signal.emit("🔄 جاري المعالجة...")
        self.progress_signal.emit(0)
        threading.Thread(target=self.process_pdfs).start()
        self.showMinimized()

    def stop_processing(self):
        self.stop_requested = True
        self.status_signal.emit("⏹ تم طلب إيقاف المعالجة...")
        self.stop_btn.setEnabled(False)

    def on_finished(self, completed):
        if completed:
            self.status_signal.emit("✅ تم الانتهاء من المعالجة.")
        else:
            self.status_signal.emit("⛔ تم إيقاف المعالجة قبل الانتهاء.")
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def process_pdfs(self):
        from main_pdf_script import process_pdf
        try:
            pdf_files = [
                os.path.join(root, file)
                for root, _, files in os.walk(self.folder_path)
                for file in files if file.lower().endswith(".pdf")
            ]
            total = len(pdf_files)
            processed = 0
            max_workers = self.workers_spinbox.value()

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(process_pdf, fp, index_dir): fp
                    for fp in pdf_files
                }
                for future in concurrent.futures.as_completed(futures):
                    if self.stop_requested:
                        self.finished_signal.emit(False)
                        return
                    future.result()
                    processed += 1
                    progress = int((processed / total) * 100)
                    self.progress_signal.emit(progress)

            self.finished_signal.emit(True)
        except Exception as e:
            self.status_signal.emit("❌ حدث خطأ أثناء المعالجة.")
            QMessageBox.critical(self, "خطأ", str(e))
            self.finished_signal.emit(False)