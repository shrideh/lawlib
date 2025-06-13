# pyinstaller --noconfirm --onefile --windowed LawLib.py --icon=ico.ico --splash=splash.jpg
# gh release create v1.0.9 output/LawLibInstaller.exe --title "الإصدار 1.0.9" --notes "دمج ميزة المفضلة، تحسين عرض نتائج البحث"
import base64
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
import certifi
import requests
from PyQt5.QtCore import QThread, QUrl, Qt, pyqtSignal, QSettings, QRunnable, QThreadPool
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QIcon, QPixmap, QTextCursor
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QCompleter,
)
from whoosh.analysis import StemmingAnalyzer
from whoosh.fields import ID, NUMERIC, Schema, TEXT
from whoosh.index import create_in, open_dir
from whoosh.qparser import QueryParser
from icon import icon_base64


CURRENT_VERSION = "v1.0.9"


icon_base64 = icon_base64

if getattr(sys, "frozen", False):
    # إذا البرنامج مجمع (مثل PyInstaller)
    APP_DIR = os.path.dirname(sys.executable)
else:
    # أثناء التطوير: مسار الملف الحالي
    APP_DIR = os.path.dirname(os.path.abspath(__file__))


DEFAULT_LOG_DIR = os.path.join(APP_DIR, "log")
os.makedirs(DEFAULT_LOG_DIR, exist_ok=True)

# جعل جميع الملفات والمجلدات بجانب ملف exe أو ملف السكربت
DEFAULT_PDF_JSON_DIR = os.path.join(APP_DIR, "PDF_JSON")
os.makedirs(DEFAULT_PDF_JSON_DIR, exist_ok=True)

DEFAULT_DATA_DIR = APP_DIR  # تم تعديل مسار البيانات ليكون بجانب exe
DEFAULT_INDEX_DIR = os.path.join(DEFAULT_DATA_DIR, "indexdir")
os.makedirs(DEFAULT_INDEX_DIR, exist_ok=True)

HISTORY_FILE_PATH = os.path.join(DEFAULT_DATA_DIR, "log/versions_history.json")

ERROR_LOG_PATH = os.path.join(DEFAULT_DATA_DIR, "log/error_log.txt")

logging.basicConfig(
    filename=ERROR_LOG_PATH,
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# استخدام HISTORY_FILE_PATH بدلًا من ثابت مباشر
LOCAL_HISTORY_FILE = HISTORY_FILE_PATH

FAVORITES_FILE = os.path.join(DEFAULT_DATA_DIR, "log/favorites.json")

def load_favorites():
    if os.path.exists(FAVORITES_FILE):
        with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_favorites(favs):
    # إنشاء مهمة الحفظ
    save_task = SaveFavoritesTask(favs)
    
    # إضافة المهمة إلى مجموعة الخيوط
    QThreadPool.globalInstance().start(save_task)

class SaveFavoritesTask(QRunnable):
    def __init__(self, favorites):
        super().__init__()
        self.favorites = favorites

    def run(self):
        try:
            with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"حدث خطأ أثناء حفظ المفضلة: {e}")

def initialize_index():
    try:
        source_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "indexdir"
        )
        target_dir = DEFAULT_INDEX_DIR

        if not os.path.exists(target_dir):
            shutil.copytree(source_dir, target_dir)
    except Exception as e:
        logging.error(
            "تعذر نسخ الفهرس من %s إلى %s: %s", source_dir, target_dir, str(e)
        )


# --- دالة فهرسة ملفات txt ---
def index_txt_files(base_dir, index_dir, progress_callback=None):
    arabic_analyzer = StemmingAnalyzer()  # يمكن استبداله بـ ArabicAnalyzer مخصص إن توفر

    schema = Schema(
        title=TEXT(stored=True, analyzer=arabic_analyzer),
        content=TEXT(stored=True, analyzer=arabic_analyzer),
        path=ID(stored=True, unique=True),
        pdf=ID(stored=True),
        page=NUMERIC(stored=True),
    )

    # محاولة فتح الفهرس أو إعادة إنشائه إذا كان تالفًا
    if not os.path.exists(index_dir):
        os.mkdir(index_dir)
        ix = create_in(index_dir, schema)
    else:
        try:
            ix = open_dir(index_dir)
        except Exception as e:
            logging.error(
                f"Error opening index directory {index_dir}, attempting to recreate: {e}"
            )
            import shutil

            try:
                shutil.rmtree(index_dir)
                os.mkdir(index_dir)
                ix = create_in(index_dir, schema)
            except Exception as rm_e:
                logging.error(f"Error recreating index directory: {rm_e}")
                raise

    # جمع جميع ملفات txt المؤهلة
    txt_files = []
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".txt"):
                txt_path = os.path.join(root, file)
                pdf_path = os.path.join(root, file.replace(".txt", ".pdf"))
                if os.path.exists(pdf_path):
                    txt_files.append((txt_path, pdf_path))

    total_files = len(txt_files)
    if total_files == 0 and progress_callback:
        progress_callback.emit(100)  # لا توجد ملفات

    with ix.writer(multisegment=True) as writer:
        for count, (txt_path, pdf_path) in enumerate(txt_files, start=1):
            file = os.path.basename(txt_path)
            try:
                with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                    sections = f.read().split("## ")
                    for section in sections:
                        if not section.strip():
                            continue
                        try:
                            header, *body = section.split("\n", 1)
                            page_str = header.strip()
                            if not page_str:
                                logging.warning(
                                    f"Skipping section with empty page header in {txt_path}"
                                )
                                continue
                            page = int(page_str)
                            content = body[0].strip() if body else ""
                            writer.update_document(
                                title=file,
                                content=content,
                                path=txt_path,
                                pdf=pdf_path,
                                page=page,
                            )
                            logging.info(f"Indexed {file} - Page {page}")
                        except ValueError:
                            logging.error(
                                f"Invalid page number '{header.strip()}' in section of {txt_path}",
                                exc_info=True,
                            )
                        except Exception:
                            logging.error(
                                f"Error parsing section in {txt_path}", exc_info=True
                            )
            except Exception as e_file:
                logging.error(f"Error reading file {txt_path}: {e_file}", exc_info=True)

            # تحديث التقدم
            if progress_callback and total_files > 0:
                progress_callback.emit(int((count / total_files) * 100))


def normalize_arabic(text):
    if not text:
        return ""
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ة": "ه",
        "ً": "",
        "ٌ": "",
        "ٍ": "",
        "َ": "",
        "ُ": "",
        "ِ": "",
        "ّ": "",
        "ْ": "",
        "ٓ": "",
        "ٔ": "",
        "ٱ": "ا",
    }
    for src, target in replacements.items():
        text = text.replace(src, target)
    return text


def index_json_books(base_dir, index_dir, progress_callback=None):
    arabic_analyzer = StemmingAnalyzer()

    schema = Schema(
        title=TEXT(stored=True, analyzer=arabic_analyzer),
        content=TEXT(stored=True, analyzer=arabic_analyzer),
        path=ID(stored=True, unique=True),
        pdf=ID(stored=True),
        image=ID(stored=True),  # تخزين المسار فقط
        sha512=ID(stored=True),
        page=NUMERIC(stored=True),
    )

    if not os.path.exists(index_dir):
        os.mkdir(index_dir)
        ix = create_in(index_dir, schema)
    else:
        try:
            ix = open_dir(index_dir)
        except Exception as e:
            logging.error(f"تعذر فتح فهرس {index_dir}، سيتم إعادة إنشائه: {e}")
            import shutil

            try:
                shutil.rmtree(index_dir)
                os.mkdir(index_dir)
                ix = create_in(index_dir, schema)
            except Exception as rm_e:
                logging.error(f"فشل حذف أو إعادة إنشاء الفهرس: {rm_e}")
                raise

    json_files = []
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".json"):
                json_path = os.path.join(root, file)
                pdf_path = os.path.join(root, file.replace(".json", ".pdf"))
                image_path = os.path.join(root, file.replace(".json", ".jpg"))
                if os.path.exists(pdf_path) and os.path.exists(image_path):
                    json_files.append((json_path, pdf_path, image_path))

    total_files = len(json_files)
    if total_files == 0 and progress_callback:
        progress_callback.emit(100)

    with ix.searcher() as searcher, ix.writer(multisegment=True) as writer:
        sha_query = QueryParser("sha512", schema=ix.schema)

        for count, (json_path, pdf_path, image_path) in enumerate(json_files, start=1):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                sha = data.get("sha512", "").strip()
                if not sha:
                    logging.warning(f"تخطي الملف لعدم وجود sha: {json_path}")
                    continue

                # التحقق مما إذا كان sha موجود مسبقًا
                query = sha_query.parse(f'"{sha}"')
                if searcher.search(query, limit=1):
                    logging.info(f"تم تخطي الكتاب (مفهرس مسبقًا): {json_path}")
                    continue

                title = data.get("book_name", os.path.basename(json_path))
                image_path_stored = image_path  # تخزين مسار الصورة فقط

                for entry in data.get("contents", []):
                    page = entry.get("page")
                    content = entry.get("text", "").strip()
                    if content:
                        writer.add_document(
                            title=normalize_arabic(title),
                            content=normalize_arabic(content),
                            path=json_path,
                            pdf=pdf_path,
                            image=image_path_stored,  # تخزين المسار هنا
                            sha512=sha,
                            page=page,
                        )
                        logging.info(f"تمت فهرسة {title} - صفحة {page}")
            except Exception as e_file:
                logging.error(
                    f"خطأ في قراءة أو تحليل {json_path}: {e_file}", exc_info=True
                )

            if progress_callback and total_files > 0:
                progress_callback.emit(int((count / total_files) * 100))


class IndexThread(QThread):
    progress = pyqtSignal(int)
    done = pyqtSignal(str)

    def __init__(self, base_dir, index_dir):
        super().__init__()
        self.base_dir = base_dir
        self.index_dir = index_dir

    def run(self):
        try:
            index_json_books(self.base_dir, self.index_dir, self.progress)
            self.done.emit("✅ تم فهرسة الملفات بنجاح.")
        except Exception as e:
            logging.error("Error during indexing thread execution", exc_info=True)
            self.done.emit(f"❌ فشلت الفهرسة: {str(e)}")


class IndexDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("فهرسة الملفات")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setGeometry(200, 200, 600, 200)
        self.init_ui()
        self.center_on_screen()

    def init_ui(self):
        layout = QVBoxLayout()

        # مجلد المصدر
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit(DEFAULT_PDF_JSON_DIR)
        self.path_input.setReadOnly(True)
        path_layout.addWidget(QLabel("📁 المجلد المصدر:"))
        path_layout.addWidget(self.path_input)

        # زر "فتح المجلد"
        open_folder_btn = QPushButton("فتح المجلد")
        open_folder_btn.clicked.connect(self.open_source_folder)
        path_layout.addWidget(open_folder_btn)

        # مجلد الفهرس
        index_path_layout = QHBoxLayout()
        self.index_path_input = QLineEdit(DEFAULT_INDEX_DIR)
        self.index_path_input.setReadOnly(True)
        index_path_layout.addWidget(QLabel("🗂️ مجلد الفهرس:"))
        index_path_layout.addWidget(self.index_path_input)

        browse_btn_index = QPushButton("استعراض...")
        browse_btn_index.setEnabled(False)
        browse_btn_index.setVisible(False)
        index_path_layout.addWidget(browse_btn_index)

        # شريط التقدم
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)

        # حالة العملية
        self.status_label = QLabel("جارٍ الفهرسة...")
        self.status_label.setAlignment(Qt.AlignCenter)

        # زر بدء الفهرسة
        self.index_btn = QPushButton("بدء الفهرسة")
        self.index_btn.clicked.connect(self.start_indexing)

        # أزرار فتح السجلات
        buttons_layout = QHBoxLayout()

        open_history_btn = QPushButton("فتح سجل التحديثات")
        open_history_btn.clicked.connect(self.open_history_file)
        buttons_layout.addWidget(open_history_btn)

        open_error_log_btn = QPushButton("فتح سجل الأخطاء")
        open_error_log_btn.clicked.connect(self.open_error_log_file)
        buttons_layout.addWidget(open_error_log_btn)

        # تجميع كل العناصر
        layout.addLayout(buttons_layout)
        layout.addLayout(path_layout)
        layout.addLayout(index_path_layout)
        layout.addWidget(self.progress)
        layout.addWidget(self.index_btn)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

    def open_source_folder(self):
        folder_path = self.path_input.text().strip()
        if os.path.isdir(folder_path):
            self.open_file_with_default_app(folder_path)
        else:
            QMessageBox.warning(self, "خطأ", f"المجلد غير موجود:\n{folder_path}")

    def open_history_file(self):
        path = LOCAL_HISTORY_FILE
        if os.path.isfile(path):
            self.open_file_with_default_app(path)
        else:
            QMessageBox.warning(self, "خطأ", f"ملف سجل التحديثات غير موجود:\n{path}")

    def open_error_log_file(self):
        path = ERROR_LOG_PATH
        if os.path.isfile(path):
            self.open_file_with_default_app(path)
        else:
            QMessageBox.warning(self, "خطأ", f"ملف سجل الأخطاء غير موجود:\n{path}")

    def open_file_with_default_app(self, filepath):
        if sys.platform == "win32":
            os.startfile(filepath)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", filepath])
        else:
            subprocess.Popen(["xdg-open", filepath])

    def center_on_screen(self):
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)

    def start_indexing(self):
        base = self.path_input.text().strip()
        idx = self.index_path_input.text().strip()

        if not os.path.isdir(base):
            QMessageBox.warning(self, "خطأ", f"مجلد المصدر غير موجود: {base}")
            return

        if not os.path.isdir(idx):
            QMessageBox.warning(self, "خطأ", f"مجلد الفهرس غير موجود: {idx}")
            return

        self.index_btn.setEnabled(False)
        self.status_label.setText("⏳ جارٍ الفهرسة...")
        self.progress.setValue(0)

        self.thread = IndexThread(base, idx)
        self.thread.progress.connect(self.progress.setValue)
        self.thread.done.connect(self.on_indexing_done)
        self.thread.start()

    def on_indexing_done(self, message):
        self.status_label.setText(message)
        self.index_btn.setEnabled(True)
        if "✅" in message:
            QMessageBox.information(self, "اكتملت الفهرسة", message)
        else:
            QMessageBox.critical(self, "خطأ في الفهرسة", message)


class SearchApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("المكتبة القانونية محرك بحث بالنص الكامل")
        self.setGeometry(
            100, 100, 800, 600
        )  # Adjusted window size as PDF viewer is gone
        self.setLayoutDirection(Qt.RightToLeft)  # For RTL layout
        icon_data = base64.b64decode(icon_base64)
        pixmap = QPixmap()
        pixmap.loadFromData(icon_data)
        self.setWindowIcon(QIcon(pixmap))
        self.index_dir = DEFAULT_INDEX_DIR
        self.settings = QSettings("Shari3aLawApp", "SearchApp")
        self.search_history = self.settings.value("search_history", [], type=list)
        self.completer = QCompleter(self.search_history)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.last_search_results_html = ""  # Initialize variable to store HTML results
        self.init_ui()
        self.favorites = load_favorites()
        self.center_on_screen()

        self.setStyleSheet(
            """
    QMainWindow {
        background-color: #f9f9f9;
    }
    QLabel {
        color: #2c3e50;
        font-size: 13pt;
    }
    QLineEdit {
        background-color: #ffffff;
        border: 1px solid #cccccc;
        padding: 5px;
        font-size: 11pt;
    }
    QPushButton {
        background-color: #00796b;
        color: white;
        border-radius: 5px;
        padding: 8px 12px;
        font-size: 11pt;
    }
    QPushButton:hover {
        background-color: #004d40;
    }
    QTextBrowser {
        background-color: #ffffff;
        border: 1px solid #cccccc;
        padding: 10px;
        font-size: 12pt;
        color: #333333;
    }
    QMenuBar {
    background-color: #ffffff;
    color: #2c3e50;
    font-size: 11pt;
}

QMenuBar {
    background-color: #ffffff;
    color: #2c3e50;
    font-size: 11pt;
}

QMenuBar::item {
    background-color: transparent;
    padding: 5px 15px;
}

QMenuBar::item:selected {
    background-color: #00796b;
    color: #ffffff;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #dddddd;
    font-size: 11pt;
    color: #2c3e50;
}

QMenu::item {
    padding: 6px 20px;
    padding-right: 40px;  /* تباعد مناسب للاختصارات */
}

QMenu::item:selected {
    background-color: #00796b;
    color: #ffffff;
}
"""
        )

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(
            main_widget
        )  # Changed to QVBoxLayout, no need for splitter if only one main area

        # جانب البحث
        search_group_widget = QWidget()  # Use a QWidget as a container for the layout
        search_layout = QVBoxLayout(
            search_group_widget
        )  # Apply layout to the container

        search_input_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setCompleter(self.completer)
        self.search_input.setPlaceholderText("أدخل كلمة البحث هنا...")
        self.search_input.returnPressed.connect(
            self.search_query
        )  # Search on Enter key
        self.use_or_checkbox = QCheckBox("او")
        self.use_or_checkbox.setToolTip(
            "إذا تم تفعيله، سيتم البحث باستخدام OR بين الكلمات المدخلة."
        )

        search_btn = QPushButton("🔍 بحث")
        search_btn.clicked.connect(self.search_query)
        search_input_layout.addWidget(self.search_input)
        search_input_layout.addWidget(self.use_or_checkbox)
        search_input_layout.addWidget(search_btn)

        self.results_browser = QTextBrowser()
        # Keep setOpenExternalLinks(False) to manually handle links and provide custom feedback
        self.results_browser.setOpenExternalLinks(False)
        self.results_browser.anchorClicked.connect(self.handle_link_click)

        search_layout.addLayout(search_input_layout)
        search_layout.addWidget(QLabel("📑 النتائج:"))
        search_layout.addWidget(self.results_browser)
        # No PDF viewer, so no splitter needed.
        main_layout.addWidget(search_group_widget)

        menubar = self.menuBar()
        file_menu = menubar.addMenu("ملف")
        show_fav_action = QAction("عرض المفضلة", self)
        show_fav_action.triggered.connect(self.show_favorites)
        show_fav_action.setShortcut("Ctrl+F")
        file_menu.addAction(show_fav_action) 
        converter_action = QAction("محول الكتب", self)
        converter_action.setToolTip("افتح الأداة الخارجية لتحويل ملفات PDF")
        converter_action.triggered.connect(self.open_pdf_converter)
        converter_action.setShortcut("Ctrl+N")  # إضافة اختصار
        file_menu.addAction(converter_action)
        file_menu.addSeparator()
        help_menu = menubar.addMenu("مساعدة")
        help_action = QAction("إرشادات البحث", self)
        update_action = QAction("تحديث البرنامج", self)
        update_action.setShortcut("Ctrl+U")  # إضافة اختصار
        update_action.triggered.connect(self.check_for_update)
        help_menu.addAction(update_action)
        howto_action = QAction("شرح محول الكتب", self)
        howto_action.setShortcut("Ctrl+H")
        howto_action.triggered.connect(self.open_how_to_use)
        help_menu.addAction(howto_action)
        help_action.setShortcut("F1")
        help_action.triggered.connect(self.show_help_dialog)
        help_menu.addAction(help_action)
        index_action = QAction(
            QIcon.fromTheme("document-properties", QIcon("")), "فهرسة جديدة...", self
        )  # Added icon hint
        index_action.setShortcut("Ctrl+I")
        index_action.triggered.connect(self.open_index_dialog)
        file_menu.addAction(index_action)
        clear_history_action = QAction("مسح سجل البحث", self)
        clear_history_action.setShortcut("Ctrl+Shift+Del")
        clear_history_action.setStatusTip("حذف سجل كلمات البحث السابقة.")
        clear_history_action.triggered.connect(self.clear_search_history)
        help_menu.addAction(clear_history_action)
        dev_mode_action = QAction("المطور", self)
        dev_mode_action.setShortcut("Ctrl+D")
        dev_mode_action.triggered.connect(self.open_developer_dialog)
        help_menu.addAction(dev_mode_action)
        exit_action = QAction(
            QIcon.fromTheme("application-exit", QIcon("")), "خروج", self
        )
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.statusBar().showMessage("جاهز.")

    def show_favorites(self):
        self.showing_favorites = True
        current_scroll_pos = self.results_browser.verticalScrollBar().value()
        if not self.favorites:
            QMessageBox.information(self, "المفضلة", "📭 لا توجد عناصر في المفضلة.")
            return

        html = "<h2>⭐ المفضلة:</h2><div style='display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 15px;'>"
        
        for i, fav in enumerate(self.favorites, 1):
            pdf_path = fav["pdf"]
            page = fav["page"]
            title = fav.get("title", "بدون عنوان")
            image = fav.get("image", "")
            
            # Properly encode the removal URL parameters
            encoded_path = QUrl.toPercentEncoding(pdf_path).data().decode()
            encoded_title = QUrl.toPercentEncoding(title).data().decode()
            encoded_image = QUrl.toPercentEncoding(image).data().decode() if image else ""
            SEP = "¤"
            remove_link = f"action:remove_fav{SEP}{encoded_title}{SEP}{encoded_image}{SEP}{encoded_path}{SEP}{page}"
            
            # Create the link to open PDF
            pdf_link = QUrl.fromLocalFile(pdf_path).toString() + f"#page={page}"
            
            card_html = (
                "<div style='border:1px solid #ddd; border-radius:10px; padding:14px; box-shadow:0 2px 6px rgba(0,0,0,0.05); display:flex; flex-direction:column; height:100%; font-family:Cairo,Amiri,sans-serif;'>"
                )
            
            if image:
                card_html += f"<div style='text-align:center; margin-bottom:10px;'><img src='{image}' style='max-width:70%; max-height:80px; border-radius:6px;'/></div>"
            
            
            card_html += (
                f"<h4 style='margin:0 0 8px 0; font-size: 1em; color:#0d47a1;'>{i}. {title}</h4>"
                f"<p style='font-size:0.8em; color:#666; margin:0 0 10px 0;'>المسار: {os.path.basename(pdf_path)}</p>"
                f'<a href="{pdf_link}" style="color: #1e7e34; text-decoration: none;">📂 افتح الملف (صفحة {page})</a>'
                f'<a href="{remove_link}" style="color: #e91e63; margin-top: 8px;">❌ إزالة من المفضلة</a>'
            )
            

                
            card_html += "</div><hr>"
            html += card_html
            
        html += "</div>"
        self.results_browser.setHtml(html)
        self.results_browser.verticalScrollBar().setValue(current_scroll_pos)

    def open_pdf_converter(self):
        # APP_DIR هنا لا يزال str، فنستخدم os.path.join
        exe_path = os.path.join(APP_DIR, "pdf_processor_gui.exe")
        if os.path.exists(exe_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(exe_path))
        else:
            QMessageBox.warning(
                self,
                "خطأ",
                f"لم يتم العثور على الأداة:\n{exe_path}"
            )
    def center_on_screen(self):
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)

    def clear_search_history(self):
        confirm = QMessageBox.question(
            self,
            "تأكيد الحذف",
            "هل أنت متأكد من أنك تريد مسح سجل البحث؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.search_history = []
            self.settings.setValue("search_history", self.search_history)
            self.completer.model().setStringList(self.search_history)
            QMessageBox.information(self, "تم", "تم مسح سجل البحث بنجاح.")

    def open_developer_dialog(self):
        dialog = DeveloperDialog(self)
        dialog.exec_()

    def open_how_to_use(self):
        try:
            # Create a new dialog window
            dialog = QDialog(self)
            dialog.setWindowTitle("تحديث كتب البرنامج")
            dialog.setLayoutDirection(Qt.RightToLeft)  # For RTL layout
            dialog.resize(800, 600)

            # Create a QTextBrowser to display the HTML content
            text_browser = QTextBrowser(dialog)
            text_browser.setHtml(
                """
                <!DOCTYPE html>
                <html lang="ar" dir="rtl">
                <head>
                    <meta charset="UTF-8">
                    <title>محول الكتب</title>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            font-size: 24px;
                            line-height: 1.8;
                            background-color: #f9f9f9;
                            color: #333;
                            padding: 20px;
                        }
                        h1, h2 {
                            color: #2c3e50;
                        }
                        .step {
                            background-color: #ffffff;
                            border-right: 4px solid #3498db;
                            padding: 15px;
                            margin: 10px 0;
                            border-radius: 8px;
                            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                        }
                        code {
                            background-color: #eee;
                            padding: 2px 6px;
                            border-radius: 4px;
                            font-family: Consolas, monospace;
                        }
                    </style>
                </head>
                <body>
                    <h1>محول الكتب</h1>
                    <div class="step">
                        <h2>خطوات تشغيل محول الكتب</h2>
                        <ul>
                            <li>في القائمة الرئيسية اختر <strong>ملف &raquo; محول الكتب</strong>.</li>
                            <li>سيفتح لك تطبيق تحويل ملفات PDF (pdf_processor_gui.exe).</li>
                            <li>في الواجهة الجديدة اضغط على زر <strong>📁 اختر المجلد</strong> واختر المجلد الذي يحتوي على ملفات PDF.</li>
                            <li>بعد اختيار المجلد، حدد عدد العمال (الـ Threads) ثم اضغط <strong>🚀 ابدأ</strong>.</li>
                            <li>سيبدأ التطبيق في فحص الملفات وتنفيذ الخطوات التالية لكل ملف:</li>
                            <ul>
                                <li>إزالة الملفات المكررة بالتحقق من قيمة SHA-512.</li>
                                <li>استخراج نص كل صفحة عبر OCR.</li>
                                <li>تنظيف النص وإزالة التشكيل والكلمات الشائعة.</li>
                                <li>حفظ محتوى الكتاب في ملف JSON داخل مجلد <code>PDF_JSON</code>.</li>
                                <li>توليد صورة مصغرة للملف.</li>
                            </ul>
                            <li>يمكنك إيقاف المعالجة في أي وقت بالضغط على <strong>🛑 إيقاف</strong>؛ سيقوم التطبيق بقتل كل العمليات الفرعية وينهي الخيوط فوراً.</li>
                            <li>بعد الانتهاء، اضغط <strong>خروج</strong> للعودة إلى التطبيق الرئيسي.</li>
                            <li><strong>بعد الانتهاء من تحويل الكتب</strong>، اذهب إلى قائمة <strong>ملف</strong> ثم اختر <strong>فهرسة جديدة</strong>، وانقر على زر <strong>بدء الفهرسة</strong>، وبعد انتهاء الفهرسة يمكنك البدء بالبحث في الكتب.</li>
                        </ul>
                    </div>
                </body>
                </html>
                """
            )
            text_browser.setReadOnly(True)

            # Add a layout to the dialog
            layout = QVBoxLayout(dialog)
            layout.addWidget(text_browser)

            # Show the dialog
            dialog.exec_()
        except Exception as e:
            logging.error("تعذر فتح نافذة التعليمات: %s", str(e))
            QMessageBox.critical(self, "خطأ", "تعذر فتح نافذة التعليمات.")

    def check_for_update(self):
        dialog = UpdateCheckerDialog()
        dialog.exec_()

    def show_help_dialog(self):
        dialog = HelpDialog(self)
        dialog.exec_()

    def open_index_dialog(self):
        dialog = IndexDialog(self)
        if dialog.exec_():
            self.statusBar().showMessage("تم إغلاق نافذة الفهرسة.")

    def search_query(self):
        self.showing_favorites = False
        query_text = self.search_input.text().strip()
        if not query_text:
            self.results_browser.setHtml(
                "<p style='color:orange;'>يرجى إدخال كلمة للبحث.</p>"
            )
            self.statusBar().showMessage("يرجى إدخال كلمة للبحث.")
            # Clear previous results if search input is empty
            self.last_search_results_html = ""
            return
        if query_text not in self.search_history:
            self.search_history.append(query_text)
            self.settings.setValue("search_history", self.search_history)
            self.completer.model().setStringList(self.search_history)
        self.results_browser.clear()
        self.statusBar().showMessage(f"⏳ جارٍ البحث عن: {query_text}...")

        try:
            from whoosh.index import open_dir, exists_in
            from whoosh.qparser import QueryParser

            if not exists_in(self.index_dir) or not os.listdir(
                self.index_dir
            ):  # Check if index dir exists and is not empty
                self.results_browser.setHtml(
                    "<p style='color:red;'>⚠️ الفهرس غير موجود أو فارغ. الرجاء فهرسة الملفات أولاً من قائمة 'ملف'.</p>"
                )
                self.statusBar().showMessage("الفهرس غير موجود أو فارغ.")
                QMessageBox.warning(
                    self,
                    "الفهرس غير موجود",
                    "الفهرس غير موجود أو فارغ. يرجى الذهاب إلى 'ملف' > 'فهرسة جديدة' لإنشاء الفهرس.",
                )
                # Clear previous results
                self.last_search_results_html = ""
                return

            ix = open_dir(self.index_dir)
            qp = QueryParser("content", schema=ix.schema)
            normalized_query = normalize_arabic(query_text)
            use_or = self.use_or_checkbox.isChecked()
            if use_or:
                # استخدم OR بين الكلمات
                words = normalized_query.split()
                joined_query = " OR ".join(words)
                q = qp.parse(joined_query)
            else:
                q = qp.parse(normalized_query)

            with ix.searcher() as searcher:
                results = searcher.search(q, limit=500)  # Increased limit
                if not results:
                    self.results_browser.setHtml(
                        f"<p style='color:darkorange;'>❗️لم يتم العثور على نتائج للبحث عن: '{query_text}'.</p>"
                    )
                    self.statusBar().showMessage(
                        f"لم يتم العثور على نتائج لـ '{query_text}'."
                    )
                    # Clear previous results
                    self.last_search_results_html = ""
                    return

                html_parts = [
                    """
                    <style>
                        body {
                            background-color: #000;
                            color: #2c3e50;
                            font-size: 17px;
                            line-height: 2.2;
                            direction: rtl;
                            text-align: right;
                            padding: 30px;
                        }
                    </style>
                    """
                ]
                num_results = len(results)
                self.statusBar().showMessage(
                    f"تم العثور على {num_results} نتيجة لـ '{query_text}'."
                )

                # قبل الحلقة، افتح حاوية الشبكة
                html_parts.append(
                    "<div style='"
                    "display: grid;"
                    "grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));"
                    "gap: 15px;"
                    "margin-top: 10px;"
                    "'>"
                )
                seen_pdfs = set()
                for i, r in enumerate(results):
                    file_title = r.get("title", "بدون عنوان")
                    pdf_path = r["pdf"]
                    if pdf_path in seen_pdfs:
                        continue
                    seen_pdfs.add(pdf_path)
                    page_num = r["page"]
                    image_base64 = r.get("image", "")

                    full_file_uri = (
                        QUrl.fromLocalFile(pdf_path).toString() + f"#page={page_num}"
                    )
                    external_link_href = full_file_uri

                    excerpt = r.highlights("content", top=2) or r["content"][:300]

                    # بطاقة نتيجة واحدة
                    card_html = (
                        "<div style='border:1px solid #ddd; border-radius:10px; padding:14px; box-shadow:0 2px 6px rgba(0,0,0,0.05); display:flex; flex-direction:column; height:100%; font-family:Cairo,Amiri,sans-serif;'>"
                    )
                    # الصورة (اعلى البطاقة)
                    if image_base64:
                        card_html += f"<div style='text-align:center; margin-bottom:10px;'><img src='{image_base64}' style='max-width:70%; max-height:80px; border-radius:6px;'/></div>"

                    is_fav = any(f["pdf"] == pdf_path and f["page"] == page_num for f in self.favorites)
                    fav_label = "⭐ إزالة من المفضلة" if is_fav else "☆ أضف إلى المفضلة"
                    fav_action = "remove_fav" if is_fav else "add_fav"
                    sep = "¤"
                    fav_button = f'<a href="action:{fav_action}{sep}{file_title}{sep}{image_base64}{sep}{pdf_path}{sep}{page_num}" style="color: #e91e63;">{fav_label}</a>'
                    # عنوان وتفاصيل البطاقة
                    card_html += (
                        f"<h4 style='margin:0 0 8px 0; font-size: 1em; color:#0d47a1;'>{i+1}. {file_title}</h4>"
                        f"<p style='flex-grow: 1; font-size: 0.9em; color: #2c3e50; margin:0 0 10px 0;'>{excerpt}...</p>"
                        "<p style='font-size: 0.8em; color: #666; margin:0 0 10px 0;'>"
                        f"المسار: {os.path.basename(pdf_path)}"
                        "</p>"
                        f'<a href="{external_link_href}" '
                        "style='align-self: flex-start; font-size: 0.9em; color: #1e7e34; text-decoration: none; font-weight: bold;' "
                        f'target="_blank">📂 افتح الملف (صفحة {page_num})</a>'
                        f"{fav_button}"
                    )
                   
                    # نهاية البطاقة
                    card_html += (
                        "</div>"
                        "<hr>"  
                    )

                    html_parts.append(card_html)

                # بعد الحلقة، أغلق حاوية الشبكة
                html_parts.append("</div>")

                # ثم اعرضها
                self.last_search_results_html = "".join(html_parts)
                self.results_browser.setHtml(self.last_search_results_html)
                self.results_browser.moveCursor(QTextCursor.Start)

        except Exception as e:
            logging.error("Exception in search_query", exc_info=True)
            self.results_browser.setHtml(
                f"<p style='color:red;'>❌ خطأ أثناء البحث: {str(e)}</p>"
            )
            self.statusBar().showMessage("حدث خطأ أثناء البحث.")
            QMessageBox.critical(
                self, "خطأ في البحث", f"حدث خطأ غير متوقع أثناء البحث:\n{str(e)}"
            )
            # Clear previous results on search error
            self.last_search_results_html = ""

    def handle_link_click(self, url: QUrl):
        full_file_uri = url.toString()
        url_str = QUrl.fromPercentEncoding(url.toEncoded())
        if url_str.startswith("action:add_fav") or url_str.startswith("action:remove_fav"):
            current_scroll_pos = self.results_browser.verticalScrollBar().value()
            if self.last_search_results_html:
                self.results_browser.setHtml(self.last_search_results_html)
            parts = url_str.split("¤")
            if len(parts) < 5:
                logging.error(f"رابط غير صالح: {url_str}")
                QMessageBox.warning(self, "خطأ", "الرابط غير صالح لإضافة أو حذف المفضلة.")
                return
            action = parts[0].split(":")[1]
            file_title = parts[1]
            image_base64 = parts[2]
            pdf_path = parts[3]
            try:
                page = int(parts[4])
            except ValueError:
                QMessageBox.warning(self, "خطأ", "رقم الصفحة غير صالح.")
                return

            if action == "add_fav":
                self.favorites.append({
                    "pdf": pdf_path, 
                    "page": page,
                    "title": file_title,
                    "image": image_base64
            })
            else:
                self.favorites = [
                    f for f in self.favorites if not (f["pdf"] == pdf_path and f["page"] == page)
                ]
            save_favorites(self.favorites)
            if hasattr(self, "showing_favorites") and self.showing_favorites:
                self.show_favorites()
            else:
                self.search_query()
            self.results_browser.verticalScrollBar().setValue(current_scroll_pos)
            return

        # استخراج المسار المحلي للملف ورقم الصفحة للعرض/التسجيل
        pdf_path = url.toLocalFile()
        page_fragment = url.fragment()
        page_num = None
        if page_fragment and page_fragment.startswith("page="):
            try:
                page_num = int(page_fragment.split("=")[1])
            except ValueError:
                logging.warning(
                    f"Could not parse page number from fragment: {page_fragment}"
                )


        self.statusBar().showMessage(
            f"محاولة فتح: {os.path.basename(pdf_path)}، صفحة: {page_num if page_num else 'غير محددة'}"
        )

        try:
            # Save current scroll position
            current_scroll_pos = self.results_browser.verticalScrollBar().value()

            if sys.platform.startswith("win"):
                os.startfile(full_file_uri)
                self.statusBar().showMessage(
                    f"تم طلب فتح {os.path.basename(pdf_path)} باستخدام os.startfile."
                )

            elif sys.platform.startswith("darwin"):
                subprocess.Popen(["open", full_file_uri])
                self.statusBar().showMessage(
                    f"تم طلب فتح {os.path.basename(pdf_path)} باستخدام أمر 'open'."
                )

            else:  # Linux and other Unix-like
                subprocess.Popen(["xdg-open", full_file_uri])
                self.statusBar().showMessage(
                    f"تم طلب فتح {os.path.basename(pdf_path)} باستخدام xdg-open."
                )

            # ----------------------------------------------------------------------
            # التغيير الجديد: الرجوع إلى نتائج البحث السابقة
            if (
                hasattr(self, "last_search_results_html")
                and self.last_search_results_html
            ):
                self.results_browser.setHtml(self.last_search_results_html)
                # Restore scroll position
                self.results_browser.verticalScrollBar().setValue(current_scroll_pos)
            else:
                # في حال عدم وجود نتائج سابقة (مثلاً إذا لم يتم البحث بعد)
                self.results_browser.setHtml(
                    "<p>تم فتح الملف بنجاح.</p><p>لا توجد نتائج سابقة لعرضها.</p>"
                )
            # ----------------------------------------------------------------------

        except Exception as e:
            logging.error(
                f"Error opening PDF using platform-specific command for {full_file_uri}: {e}",
                exc_info=True,
            )
            QMessageBox.critical(
                self,
                "خطأ في الفتح",
                f"حدث خطأ أثناء محاولة فتح الملف:\n{pdf_path}\n\n"
                f"الخطأ: {str(e)}\n\n"
                "الرجاء التأكد من وجود قارئ PDF افتراضي يعمل بشكل صحيح."
                "قد تحتاج إلى تثبيت قارئ PDF أو التحقق من إعدادات النظام."
                "\n\nملاحظة: إذا كان قارئ PDF الافتراضي لديك هو متصفح الويب، فقد لا يتم الانتقال إلى الصفحة المحددة بشكل صحيح.",
            )
            self.statusBar().showMessage("فشل فتح الملف.")


class DeveloperDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("المطور - مكتب معتز الشريدة للمحاماة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(400, 200)
        self.init_ui()
        self.center_on_screen()

    def init_ui(self):
        layout = QVBoxLayout()
        label = QLabel(
            "<h3 style='color:#2c3e50;'>مكتب معتز الشريدة للمحاماة</h3>"
            "<p>للتواصل: <a href='mailto:dev@mws.per.jo'>dev@mws.per.jo</a></p>"
        )
        label.setOpenExternalLinks(True)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)

        self.setLayout(layout)

    def center_on_screen(self):
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)


class UpdateCheckerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        icon_data = base64.b64decode(icon_base64)
        pixmap = QPixmap()
        pixmap.loadFromData(icon_data)
        self.setWindowIcon(QIcon(pixmap))
        self.setWindowTitle("التحقق من تحديث البرنامج")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(600, 400)
        self.setWindowFlags(Qt.Window)
        self.history = []
        self.cache_updates = []  # قائمة بجميع التحديثات القادمة من الخادم
        self.init_ui()
        self.load_history()
        self.refresh_table()
        self.check_for_update_on_start()

    def init_ui(self):
        layout = QVBoxLayout(self)

        self.version_table = QTableWidget()
        self.version_table.setColumnCount(5)
        self.version_table.setHorizontalHeaderLabels(
            ["الإصدار", "تاريخ الإصدار", "رابط التحديث", "الحالة", "الإجراء"]
        )
        self.version_table.horizontalHeader().setStretchLastSection(True)
        self.version_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.version_table.cellDoubleClicked.connect(self.open_url_from_table)
        self.version_table.verticalHeader().setVisible(False)

        self.status_label = QLabel("", alignment=Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        font = QFont()
        font.setPointSize(12)
        self.status_label.setFont(font)

        self.update_button = QPushButton("زيارة صفحة المشروع على GitHub")
        self.update_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/shrideh/lawlib/releases")))
        self.current_version_label = QLabel(f"الإصدار الحالي: {CURRENT_VERSION}", alignment=Qt.AlignRight)
        layout.addWidget(self.current_version_label)
        layout.addWidget(self.version_table)
        layout.addWidget(self.status_label)
        layout.addWidget(self.update_button)
        self.setLayout(layout)

    def format_date(self, iso_str):
        try:
            dt = datetime.fromisoformat(iso_str)
            months = [
                "يناير",
                "فبراير",
                "مارس",
                "أبريل",
                "مايو",
                "يونيو",
                "يوليو",
                "أغسطس",
                "سبتمبر",
                "أكتوبر",
                "نوفمبر",
                "ديسمبر",
            ]
            return f"{dt.day} {months[dt.month-1]} {dt.year} - {dt.hour:02d}:{dt.minute:02d}"
        except:
            return iso_str

    def load_history(self):
        if os.path.exists(LOCAL_HISTORY_FILE):
            try:
                with open(LOCAL_HISTORY_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    self.history = json.loads(content) if content else []
            except Exception as e:
                print(f"خطأ في تحميل سجل التحديثات: {e}")
                self.history = []
        else:
            self.history = []

    def save_history(self):
        with open(LOCAL_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def refresh_table(self):
        all_updates = self.history + self.cache_updates
        unique_versions = {rec["version"]: rec for rec in all_updates}
        rows = list(unique_versions.values())

        self.version_table.setRowCount(len(rows))
        installed_versions = {rec["version"] for rec in self.history}

        for row, rec in enumerate(rows):
            version = rec["version"]
            is_installed = version in installed_versions
            status = "مثبت" if is_installed else "غير مثبت"
            action_enabled = not is_installed and rec in self.cache_updates
            self._fill_row(row, rec, status, action_enabled)

    def _fill_row(self, row, rec, status, action_enabled):
        self.version_table.setItem(row, 0, QTableWidgetItem(str(rec["version"])))
        self.version_table.setItem(
            row, 1, QTableWidgetItem(self.format_date(rec["updated_at"]))
        )
        url_text = rec.get("updated_url", "") or "—"
        url_item = QTableWidgetItem(url_text)
        if url_text != "—":
            url_item.setForeground(QColor(0, 0, 200))
        self.version_table.setItem(row, 2, url_item)

        status_item = QTableWidgetItem(status)
        if status == "مثبت":
            status_item.setBackground(QColor(200, 255, 200))
        self.version_table.setItem(row, 3, status_item)

        btn = QPushButton("تحميل" if status == "غير مثبت" else "مثبت")
        btn.setEnabled(action_enabled)
        if action_enabled:
            btn.clicked.connect(lambda _, r=rec: self.download_update(r))
        self.version_table.setCellWidget(row, 4, btn)

    def open_url_from_table(self, row, col):
        if col == 2:
            url = self.version_table.item(row, col).text()
            if url and url != "—":
                QDesktopServices.openUrl(QUrl(url))

    def check_for_update_on_start(self):
        self.status_label.setText("جاري التحقق من تحديثات GitHub…")
        try:
            headers = {'Accept': 'application/vnd.github.v3+json'}
            r = requests.get(
                "https://api.github.com/repos/shrideh/lawlib/releases",
                headers=headers,
                verify=certifi.where(),
                timeout=5,
            )
            if r.status_code != 200:
                self.status_label.setText("❌ فشل الاتصال بـ GitHub.")
                return

            data = r.json()
            if not isinstance(data, list):
                self.status_label.setText("⚠️ البيانات المستلمة من GitHub غير صحيحة.")
                return

            installed_versions = {rec["version"] for rec in self.history}
            self.cache_updates = []

            for release in data:
                version = release.get("tag_name", "")
                if not version:
                    continue

                if version_greater(version, CURRENT_VERSION):
                    published_at = release.get("published_at", "")
                    assets = release.get("assets", [])
                    download_url = assets[0]["browser_download_url"] if assets else ""

                    if version not in installed_versions:
                        self.cache_updates.append(
                            {
                                "version": version,
                                "updated_at": published_at,
                                "updated_url": download_url,
                            }
                        )

            if self.cache_updates:
                self.status_label.setText(
                    f"📚 تم العثور على {len(self.cache_updates)} إصدار(ات) جديدة على GitHub."
                )
            else:
                self.status_label.setText("✅ لا توجد تحديثات جديدة على GitHub.")

            self.refresh_table()

        except Exception as e:
            self.status_label.setText(f"⚠️ فشل الاتصال بـ GitHub: {e}")

    def download_update(self, rec):
        url = rec.get("updated_url")
        if not url:
            QMessageBox.warning(self, "خطأ", "الرابط غير متوفر.")
            return

        QDesktopServices.openUrl(QUrl(url))
        self.status_label.setText(
            f"📥 جاري تحميل الإصدار {rec['version']} ... بعد الانتهاء اضغط على 'تم التثبيت'."
        )
        self.replace_download_button_with_installed_button(rec["version"])

    def replace_download_button_with_installed_button(self, version):
        for row in range(self.version_table.rowCount()):
            item = self.version_table.item(row, 0)
            if item and item.text() == str(version):
                btn = QPushButton("تم التثبيت")
                btn.clicked.connect(lambda _, v=version: self.mark_as_installed(v))
                self.version_table.setCellWidget(row, 4, btn)
                break

    def mark_as_installed(self, version):
        if any(rec["version"] == version for rec in self.history):
            QMessageBox.information(self, "معلومات", "هذا الإصدار مثبت مسبقًا.")
            return

        # إيجاد الإصدار من الكاش لإضافته
        match = next(
            (rec for rec in self.cache_updates if rec["version"] == version), None
        )
        if not match:
            QMessageBox.warning(self, "خطأ", "لم يتم العثور على تفاصيل هذا الإصدار.")
            return

        self.history.insert(0, match)
        self.save_history()
        self.cache_updates = [
            rec for rec in self.cache_updates if rec["version"] != version
        ]
        self.status_label.setText(f"✅ تم تثبيت الإصدار {version}.")
        self.refresh_table()


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إرشادات البحث المنطقي")
        self.setMinimumSize(550, 400)
        self.setLayoutDirection(Qt.RightToLeft)  # دعم RTL

        layout = QVBoxLayout(self)

        browser = QTextBrowser()
        browser.setLayoutDirection(Qt.RightToLeft)  # دعم RTL للنص داخل المتصفح
        browser.setHtml(
            """
            <style>
        body {
            font-family: 'Cairo', 'Amiri', 'Segoe UI', Tahoma, sans-serif;
            background-color: #f9f9f9;
            color: #2c3e50;
            font-size: 17px;
            line-height: 2.2;
            direction: rtl;
            text-align: right;
            padding: 30px;
        }
        ul {
            font-size: 24px;
            padding-right: 35px;
            margin: 0;
            list-style-type: disc;
        }
        li {
            font-size: 24px;
            margin-bottom: 20px;
        }
        </style>
            <div style="font-family:'Segoe UI', Tahoma, sans-serif; color: #2c3e50;">
                <h2>🔎 إرشادات البحث المنطقي والمتقدم</h2>
                <ul style="font-size: 14px; line-height: 1.8; padding-right: 20px;">
                    <li>
                        للبحث عن مستند يحتوي على <u>جميع</u> الكلمات:<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">حضانة AND نفقة</code>
                    </li>
                    <li>
                        للبحث عن مستند يحتوي على <u>أي</u> من الكلمات:<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">طلاق OR خلع</code>
                    </li>
                    <li>
                        لاستثناء كلمة من النتائج:<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">نفقة NOT حضانة</code>
                    </li>
                    <li>
                        الأقواس () لتجميع الشروط وتحديد أولوية التنفيذ:<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">(حضانة OR وصاية) AND أم</code>
                    </li>
                    <li>
                        إذا لم تُستخدم عوامل منطقية، يتم افتراض <b>AND</b>:<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">دعوى ميراث</code>
                        <span>(تعني: <code style="background:#f0f0f0; padding:2px 4px;">دعوى AND ميراث</code>)</span>
                    </li>
                    <li>
                        <b>"علامات التنصيص"</b> للبحث عن العبارة كما هي:<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">"النفقة الواجبة"</code>
                    </li>
                    <li>
                        استخدام <b>*</b> للبحث بجذر الكلمة (Truncation):<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">محكم*</code> <span>(يجد: محكمة، محكمين...)</span>
                    </li>
                    <li>
                        استخدام <b>?</b> للبحث مع حرف غير معروف:<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">ن?فقة</code>
                    </li>
                    <li>
                        البحث التقريبي Fuzzy Matching (للكلمات القريبة):<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">طلاق~</code> أو <code style="background:#f0f0f0; padding:2px 4px;">طلاق~2</code>
                    </li>
                    <li>
                        البحث بكلمات قريبة من بعضها (Proximity Search):<br/>
                        <code style="background:#f0f0f0; padding:2px 4px;">"نفقة حضانة"~5</code>
                        <span>(أي الكلمتان بفارق 5 كلمات كحد أقصى)</span>
                    </li>
                </ul>
            </div>
            """
        )
        layout.addWidget(browser)

        close_btn = QPushButton("إغلاق")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, alignment=Qt.AlignLeft)

def version_greater(v1, v2):
    # إزالة 'v' أو 'V' إن وجدت
    def clean(v):
        return v.lstrip('vV').split('.')
    
    parts1 = clean(v1)
    parts2 = clean(v2)

    # تحويل الأجزاء إلى أرقام، وتعامل مع الأجزاء الناقصة بإضافة أصفار
    max_len = max(len(parts1), len(parts2))
    parts1 += ['0'] * (max_len - len(parts1))
    parts2 += ['0'] * (max_len - len(parts2))

    for p1, p2 in zip(parts1, parts2):
        try:
            n1 = int(p1)
        except:
            n1 = 0
        try:
            n2 = int(p2)
        except:
            n2 = 0
        if n1 > n2:
            return True
        elif n1 < n2:
            return False
    return False  # متساوي أو أقل


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    try:
        import pyi_splash
        pyi_splash.close()
    except:
        pass

    window = SearchApp()
    window.show()
    initialize_index()
    sys.exit(app.exec_())