import os
import uuid
import logging
import hashlib
import json
import gc
import re
import shutil
import warnings
from pathlib import Path
import sys
import cv2
from PIL import Image
import pytesseract as tess
from pdf2image import convert_from_path, pdfinfo_from_path

from whoosh.index import open_dir
from whoosh.qparser import QueryParser
from pyarabic.araby import strip_tashkeel, strip_tatweel

# Load configuration
from pdf_processor_gui import load_config

# --- تحديد مجلد التطبيق سواء في الوضع العادي أو التنفيذي ---
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# تحميل الإعدادات
CONFIG = load_config()

# تحويل المسارات إلى pathlib.Path مع قيم افتراضية
NLP_DIR       = Path(CONFIG.get('nlp_dir', BASE_DIR / 'nlp'))
DATA_DIR      = Path(CONFIG.get('data_dir', BASE_DIR))
TESSERACT_CMD = NLP_DIR / 'tesseract-portable' / 'tesseract.exe'
POPPLER_PATH  = NLP_DIR / 'poppler' / 'bin'
PDF_JSON_DIR  = Path(CONFIG.get('pdf_json_dir', BASE_DIR / 'PDF_JSON'))
TMP_DIR       = DATA_DIR / 'tmp'

# إعدادات التحذيرات
warnings.filterwarnings("ignore", category=UserWarning)

# إعداد اللوجر
LOG_DIR = BASE_DIR / 'log'
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / 'pdf_processing_errors.log'
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# إعداد مسار tesseract الخاص بك
tess.pytesseract.tesseract_cmd = str(TESSERACT_CMD)


def sha512_exists_in_index(index_dir, sha_value):
    try:
        ix = open_dir(index_dir)
        with ix.searcher() as searcher:
            parser = QueryParser("sha512", schema=ix.schema)
            query = parser.parse(f'"{sha_value}"')
            return bool(searcher.search(query, limit=1))
    except Exception as e:
        logging.error(f"تعذر التحقق من SHA512 في الفهرس: {e}")
        return False


def load_stop_words():
    try:
        path = NLP_DIR / "arabic-stop-words.txt"
        return set(path.read_text(encoding="utf-8").splitlines())
    except Exception as e:
        logging.error(f"Failed loading stop words: {e}")
        return set()


def load_quran_words():
    try:
        path = NLP_DIR / "quran.txt"
        return set(path.read_text(encoding="utf-8").splitlines())
    except Exception as e:
        logging.error(f"Failed loading quran words: {e}")
        return set()


def clean_text(text):
    stop_words = load_stop_words()
    quran_words = load_quran_words()
    words_to_remove = stop_words | quran_words

    # إزالة علامات التشكيل والأرقام والرموز
    text = re.sub(r"[0-9٠-٩]", "", text)
    text = strip_tashkeel(text)
    text = strip_tatweel(text)
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)

    # تقسيم النص على الفراغات وتصفيته
    words = [w for w in text.split() if w not in words_to_remove and 3 <= len(w) <= 15]
    return " ".join(words)


def preprocess_image(image_path):
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    _, threshed = cv2.threshold(img, 150, 255, cv2.THRESH_BINARY)
    return Image.fromarray(threshed)


def img_to_txt(image_path, page_num=None):
    img = preprocess_image(image_path)
    if img.width > 2000:
        img = img.resize((img.width // 2, img.height // 2))

    # استخراج النص الخام وتسجيله
    raw = tess.image_to_string(img, lang="ara", config="--psm 6")
    if page_num is not None:
        logging.debug(f"Raw OCR (page {page_num}): {raw!r}")
    else:
        logging.debug(f"Raw OCR: {raw!r}")

    img.close()
    return clean_text(raw)


def calculate_sha512(fp):
    sha = hashlib.sha512()
    with open(fp, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha.update(block)
    return sha.hexdigest()


def ensure_pdf_directory_structure(base_dir=PDF_JSON_DIR, max_files_per_folder=200):
    try:
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        subs = [p for p in base_dir.iterdir() if p.is_dir() and p.name.isdigit()]
        if not subs:
            new = base_dir / '1'
            new.mkdir()
            return new, 1

        latest = max(subs, key=lambda p: int(p.name))
        nums = [int(p.stem) for p in latest.iterdir() if p.suffix in ('.pdf', '.json') and p.stem.isdigit()]

        if len(nums) >= max_files_per_folder:
            new = base_dir / str(int(latest.name) + 1)
            new.mkdir()
            return new, 1

        idx = max(nums, default=0) + 1
        return latest, idx
    except Exception as e:
        logging.error(f"Error ensuring directory structure: {e}")
        return Path(base_dir), 1


def save_pdf_thumbnail(pdf_path, output_folder, width=600):
    try:
        imgs = convert_from_path(
            str(pdf_path),
            poppler_path=str(POPPLER_PATH),
            fmt="JPEG",
            use_pdftocairo=True,
            dpi=300,
            thread_count=1,
            first_page=1,
            last_page=1,
        )
        if not imgs:
            logging.error(f"❌ لم يتم استخراج صورة من الصفحة الأولى في {pdf_path}")
            return None

        img = imgs[0]
        thumb = img.resize((width, int(width * img.height / img.width)))
        dest = Path(output_folder) / f"{Path(pdf_path).stem}.jpg"
        thumb.save(dest, "JPEG", quality=85)
        img.close()
        thumb.close()
        logging.info(f"✅ حفظ الصورة المصغرة في {dest}")
        return str(dest)
    except Exception as e:
        logging.error(f"❌ خطأ في save_pdf_thumbnail: {e}")
        return None


def extract_book_title_from_first_page(text, filepath=None):
    try:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for line in lines[:3]:
            if 5 <= len(line.split()) <= 12:
                return line
        return Path(filepath).stem if filepath else "عنوان غير معروف"
    except Exception as e:
        logging.error(f"Error extracting title: {e}")
        return Path(filepath).stem if filepath else "عنوان غير معروف"


def process_pdf(filepath, index_dir):
    try:
        sha = calculate_sha512(filepath)
        if sha512_exists_in_index(index_dir, sha):
            logging.info(f"تخطي مكرر: {filepath}")
            return

        info = pdfinfo_from_path(str(filepath), poppler_path=str(POPPLER_PATH))
        total_pages = info.get("Pages", 0)
        contents = []
        first_page_text = ""

        TMP_DIR.mkdir(parents=True, exist_ok=True)
        for page in range(1, total_pages + 1):
            imgs = convert_from_path(
                str(filepath), poppler_path=str(POPPLER_PATH), fmt="JPEG",
                use_pdftocairo=True, dpi=300,
                first_page=page, last_page=page
            )
            if not imgs:
                continue
            tmp_img = TMP_DIR / f"{uuid.uuid4()}.jpg"
            imgs[0].save(tmp_img, "JPEG")
            # استخراج النص وتنظيفه
            text = img_to_txt(tmp_img, page_num=page)
            if page == 1:
                first_page_text = text
            # إضافة إلى القائمة
            contents.append({
                "page": page,
                "text": text
            })
            tmp_img.unlink()
            gc.collect()

        # نقل PDF وبناء JSON
        folder, idx = ensure_pdf_directory_structure()
        dest_pdf = folder / f"{idx}.pdf"
        shutil.move(filepath, dest_pdf)

        book_title = extract_book_title_from_first_page(first_page_text, filepath)
        json_data = {
            "sha512": sha,
            "book_name": book_title,
            "contents": contents
        }
        json_file = folder / f"{idx}.json"
        json_file.write_text(
            json.dumps(json_data, ensure_ascii=False, indent=4),
            encoding='utf-8'
        )

        save_pdf_thumbnail(dest_pdf, folder)
        logging.info(f"✅ processed: {dest_pdf}, title: {book_title}")
    except Exception as e:
        logging.error(f"❌ خطأ أثناء معالجة {filepath}: {e}")


