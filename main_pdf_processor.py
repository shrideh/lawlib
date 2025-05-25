import os
import uuid
import logging
import hashlib
import json
import gc
import re
import shutil
import warnings

import cv2
from PIL import Image
import pytesseract as tess
from pdf2image import convert_from_path, pdfinfo_from_path

from whoosh.index import open_dir
from whoosh.qparser import QueryParser
from pyarabic.araby import strip_tashkeel, strip_tatweel

from sklearn.feature_extraction.text import TfidfVectorizer
from nltk.tokenize import word_tokenize

# Load configuration
from pdf_processor_gui import load_config
CONFIG = load_config()
TESSERACT_CMD = os.path.join(CONFIG['nlp_dir'], 'tesseract-portable', 'tesseract.exe')
POPPLER_PATH = os.path.join(CONFIG['nlp_dir'], 'poppler', 'bin')
PDF_JSON_DIR = CONFIG['pdf_json_dir']
TMP_DIR = os.path.join(CONFIG.get('data_dir', os.getcwd()), 'tmp')

# إعدادات التحذيرات واللوجر
warnings.filterwarnings("ignore", category=UserWarning)

logging.basicConfig(
    filename="log/pdf_processing_errors.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# إعداد مسار tesseract الخاص بك
tess.pytesseract.tesseract_cmd = TESSERACT_CMD


def sha512_exists_in_index(index_dir, sha_value):
    try:
        ix = open_dir(index_dir)
        with ix.searcher() as searcher:
            parser = QueryParser("sha512", schema=ix.schema)
            query = parser.parse(f'"{sha_value}"')
            results = searcher.search(query, limit=1)
            return len(results) > 0
    except Exception as e:
        logging.error(f"تعذر التحقق من SHA512 في الفهرس: {e}")
        return False


def load_stop_words():
    with open(os.path.join(CONFIG['nlp_dir'], "arabic-stop-words.txt"), "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)


def load_quran_words():
    with open(os.path.join(CONFIG['nlp_dir'], "quran.txt"), "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)


def clean_text(text):
    stop_words = load_stop_words()
    quran_words = load_quran_words()
    words_to_remove = stop_words | quran_words

    text = re.sub(r"[^\w\s\u0600-\u06FF]", "", text)
    text = re.sub(r"[0-9٠-٩]", "", text)
    text = strip_tashkeel(text)
    text = strip_tatweel(text)
    words = text.split()
    cleaned = [w for w in words if w not in words_to_remove and 3 <= len(w) <= 10]
    return re.sub(r"\s+", " ", " ".join(cleaned)).strip()


def preprocess_image(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    _, threshed = cv2.threshold(img, 150, 255, cv2.THRESH_BINARY)
    return Image.fromarray(threshed)


def img_to_txt(image_path):
    img = preprocess_image(image_path)
    if img.width > 2000:
        img = img.resize((img.width // 2, img.height // 2))
    text = tess.image_to_string(img, lang="ara", config="--psm 6")
    img.close()
    return clean_text(text)


def calculate_sha512(fp):
    sha = hashlib.sha512()
    with open(fp, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha.update(block)
    return sha.hexdigest()


def ensure_pdf_directory_structure(base_dir=PDF_JSON_DIR, max_files_per_folder=200):
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    subs = [
        d for d in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, d)) and d.isdigit()
    ]
    if not subs:
        first = os.path.join(base_dir, "1")
        os.makedirs(first)
        return first, 1

    subs.sort(key=lambda x: int(x))
    latest = subs[-1]
    folder_path = os.path.join(base_dir, latest)

    existing_nums = set()
    for fname in os.listdir(folder_path):
        name, ext = os.path.splitext(fname)
        if ext.lower() in (".pdf", ".json") and name.isdigit():
            existing_nums.add(int(name))

    if len(existing_nums) >= max_files_per_folder:
        new_folder = str(int(latest) + 1)
        new_path = os.path.join(base_dir, new_folder)
        os.makedirs(new_path)
        return new_path, 1

    next_index = max(existing_nums) + 1 if existing_nums else 1
    return folder_path, next_index


def save_pdf_thumbnail(pdf_path, output_folder, width=600):
    try:
        imgs = convert_from_path(
            pdf_path,
            poppler_path=POPPLER_PATH,
            fmt="JPEG",
            use_pdftocairo=True,
            dpi=300,
            thread_count=1,
            first_page=1,
            last_page=1,
        )
        if not imgs:
            logging.error(f"❌ لم يتم استخراج صورة من الصفحة الأولى في {pdf_path} - لا توجد صور.")
            return None

        img = imgs[0]
        ar = img.height / img.width
        thumb = img.resize((width, int(width * ar)))
        num = os.path.splitext(os.path.basename(pdf_path))[0]
        thumb_path = os.path.join(output_folder, f"{num}.jpg")
        thumb.save(thumb_path, "JPEG", quality=100)
        img.close()
        thumb.close()
        logging.info(f"✅ تم حفظ الصورة المصغرة بنجاح في {thumb_path}")
        return thumb_path

    except Exception as e:
        logging.error(f"❌ خطأ أثناء استخراج الصورة المصغرة من {pdf_path}: {e}")
        return None


def generate_wordcloud(text, min_word_length=3, max_words=10):
    text = re.sub(r'[^\u0600-\u06FF\s]', '', text)
    words = word_tokenize(text)
    filtered_words = [word for word in words if len(word) >= min_word_length]
    if not filtered_words:
        return {}
    filtered_text = ' '.join(filtered_words)
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform([filtered_text])
    tfidf_scores = dict(zip(vectorizer.get_feature_names_out(), tfidf_matrix.toarray()[0]))
    sorted_words = sorted(tfidf_scores.items(), key=lambda item: item[1], reverse=True)
    return dict(sorted_words[:max_words])


def extract_book_title_from_first_page(text, wordcloud_data):
    lines = text.strip().split("\n")
    lines = [line.strip() for line in lines if line.strip()]

    for line in lines[:5]:
        if len(line.split()) >= 3 and 10 <= len(line) <= 100:
            return line

    sorted_words = sorted(wordcloud_data.items(), key=lambda x: x[1], reverse=True)
    top_keywords = [word for word, _ in sorted_words[:5]]
    if top_keywords:
        return " - ".join(top_keywords)

    return "عنوان غير معروف"


def process_pdf(filepath, index_dir):
    try:
        sha = calculate_sha512(filepath)
        if sha512_exists_in_index(index_dir, sha):
            logging.error(f"تم تخطي الملف المكرر بناءً على SHA512: {filepath}")
            return

        info = pdfinfo_from_path(filepath, poppler_path=POPPLER_PATH)
        num_pages = info.get("Pages", 0)
        contents = []
        all_text = ""
        first_page_text = ""

        for page in range(1, num_pages + 1):
            imgs = convert_from_path(
                filepath,
                poppler_path=POPPLER_PATH,
                fmt="jpeg",
                use_pdftocairo=True,
                dpi=600,
                thread_count=1,
                first_page=page,
                last_page=page,
            )
            if not imgs:
                continue
            img = imgs[0]
            os.makedirs(TMP_DIR, exist_ok=True)
            temp_path = os.path.join(TMP_DIR, f"{uuid.uuid4()}.jpg")
            img.save(temp_path, "JPEG")
            img.close()

            text = img_to_txt(temp_path)
            if page == 1:
                first_page_text = text
            all_text += text + " "
            contents.append({"page": page, "text": text})
            os.remove(temp_path)

            del imgs
            gc.collect()

        folder, num = ensure_pdf_directory_structure()
        new_pdf = os.path.join(folder, f"{num}.pdf")
        shutil.move(filepath, new_pdf)

        json_path = os.path.join(folder, f"{num}.json")
        data = {"sha512": sha, "contents": contents}
        with open(json_path, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)

        wordcloud_data = generate_wordcloud(all_text, min_word_length=3, max_words=10)
        book_title = extract_book_title_from_first_page(first_page_text, wordcloud_data)

        data["book_name"] = book_title
        with open(json_path, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)

        save_pdf_thumbnail(new_pdf, folder)

        logging.info(f"✅ تم معالجة الملف: {new_pdf}، عنوان الكتاب: {book_title}")

    except Exception as e:
        logging.error(f"❌ خطأ أثناء معالجة {filepath}: {e}")

