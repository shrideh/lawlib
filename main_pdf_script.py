import os
import uuid
import logging
import hashlib
import json
import gc
import re
import warnings

from pdf2image import convert_from_path, pdfinfo_from_path
import pytesseract as tess
from PIL import Image
import cv2
from functools import lru_cache


from whoosh.index import open_dir
from whoosh.qparser import QueryParser
from pyarabic.araby import strip_tashkeel, strip_tatweel

from sklearn.feature_extraction.text import TfidfVectorizer
from nltk.tokenize import word_tokenize

from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline

# إعدادات تيسراكت ومسارات الأدوات
tess.pytesseract.tesseract_cmd = os.path.join(os.getcwd(), "nlp", "tesseract-portable", "tesseract.exe")

logging.basicConfig(
    filename="log/pdf_processing_errors.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

warnings.simplefilter("ignore")
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("transformers.modeling_utils").setLevel(logging.CRITICAL)

@lru_cache()
def get_ner_pipeline():
    model_name = "nlp/models/models--CAMeL-Lab--bert-base-arabic-camelbert-mix-ner"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForTokenClassification.from_pretrained(model_name)
    return pipeline("ner", model=model, tokenizer=tokenizer, aggregation_strategy="simple"), tokenizer

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
    with open("nlp/arabic-stop-words.txt", "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def load_quran_words():
    with open("nlp/quran.txt", "r", encoding="utf-8") as f:
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

def ensure_pdf_directory_structure(base_dir="PDF_JSON", max_files_per_folder=200):
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    subs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    if not subs:
        os.makedirs(os.path.join(base_dir, "1"))
        return os.path.join(base_dir, "1"), 1
    subs.sort(key=lambda x: int(x))
    latest = subs[-1]
    path = os.path.join(base_dir, latest)
    count = len([f for f in os.listdir(path) if f.endswith((".pdf", ".json"))]) // 2
    if count >= max_files_per_folder:
        new_folder = str(int(latest) + 1)
        os.makedirs(os.path.join(base_dir, new_folder))
        return os.path.join(base_dir, new_folder), 1
    return path, count + 1

def save_pdf_thumbnail(pdf_path, output_folder, width=600):
    try:
        imgs = convert_from_path(
            pdf_path,
            poppler_path="nlp/poppler/bin",
            fmt="JPEG",
            use_pdftocairo=True,
            dpi=300,
            thread_count=1,
            first_page=1,
            last_page=1,
        )
        if imgs:
            img = imgs[0]
            ar = img.height / img.width
            thumb = img.resize((width, int(width * ar)))
            num = os.path.splitext(os.path.basename(pdf_path))[0]
            thumb_path = os.path.join(output_folder, f"{num}.jpg")
            thumb.save(thumb_path, "JPEG", quality=100)
            img.close()
            return thumb_path
    except Exception as e:
        logging.error(f"❌ خطأ أثناء استخراج الصورة من {pdf_path}: {e}")
    return None

def extract_text_from_json(json_file_path):
    all_text = ""
    if os.path.isfile(json_file_path) and json_file_path.endswith('.json'):
        with open(json_file_path, 'r', encoding='utf-8') as json_file:
            data = json.load(json_file)
            for page in data.get("contents", []):
                all_text += page.get("text", "") + " "
    return all_text.strip()

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

def load_json_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as json_file:
            content = json_file.read().strip()
            if not content:
                raise ValueError("Empty file")
            data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        logging.warning(f"⚠️ الملف {file_path} معطوب أو فارغ، تم إصلاحه!")
        data = {"contents": []}
        with open(file_path, 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)
    return data

def extract_text_from_json_data(json_data, max_pages=200):
    return " ".join(page.get("text", "") for page in json_data.get("contents", [])[:max_pages]).strip()

def split_text_into_chunks(text, tokenizer, max_length=512):
    tokens = tokenizer.tokenize(text)
    chunks = []
    for i in range(0, len(tokens), max_length - 10):
        chunk_tokens = tokens[i:i + max_length - 10]
        chunk_text = tokenizer.convert_tokens_to_string(chunk_tokens)
        chunks.append(chunk_text)
    return chunks

def extract_named_entities(text, max_entities=5, min_word_length=4):
    if not text.strip():
        return []
    ner_pipeline, tokenizer = get_ner_pipeline()
    chunks = split_text_into_chunks(text, tokenizer, max_length=512)
    extracted_entities = []
    for chunk in chunks:
        entities = ner_pipeline(chunk[:512])
        for entity in entities:
            word = entity["word"].strip()
            if len(word) >= min_word_length:
                extracted_entities.append({
                    "text": word,
                    "type": entity["entity_group"],
                    "score": round(float(entity["score"]), 3)
                })
            if len(extracted_entities) >= max_entities:
                return extracted_entities
    return extracted_entities[:max_entities]


# --- دالة استخراج عنوان الكتاب ---
def extract_book_title(wordcloud_data, book_info):
    """ استخراج عنوان مناسب للكتاب باستخدام بيانات wordcloud_data و book_info """
    sorted_words = sorted(wordcloud_data.items(), key=lambda x: x[1], reverse=True)
    top_keywords = [word for word, _ in sorted_words[:3]]  # أهم 3 كلمات
    authors = [entry["text"] for entry in book_info if entry["type"] == "PERS"]
    organizations = [entry["text"] for entry in book_info if entry["type"] == "ORG"]
    
    title_parts = []
    if authors:
        title_parts.append("، ".join(authors))
    if top_keywords:
        title_parts.append(" - ".join(top_keywords))
    if organizations:
        title_parts.append(f"إعداد {organizations[0]}")
    return " | ".join(title_parts)

# --- الدالة الرئيسية المدمجة لمعالجة ملف PDF مع إضافة استخراج العنوان ---
def process_pdf(filepath, index_dir):
    try:
        sha = calculate_sha512(filepath)
        if sha512_exists_in_index(index_dir, sha):
            logging.error(f"تم تخطي الملف المكرر بناءً على SHA512: {filepath}")
            return
        
        info = pdfinfo_from_path(filepath, poppler_path="nlp/poppler/bin")
        num_pages = info.get("Pages", 0)
        contents = []
        all_text = ""

        for page in range(1, num_pages + 1):
            imgs = convert_from_path(
                filepath,
                poppler_path="nlp/poppler/bin",
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
            temp_path = os.path.join("tmp", f"{uuid.uuid4()}.jpg")
            os.makedirs("tmp", exist_ok=True)
            img.save(temp_path, "JPEG")
            img.close()

            text = img_to_txt(temp_path)
            all_text += text + " "
            contents.append({"page": page, "text": text})
            os.remove(temp_path)

            del imgs
            gc.collect()

        folder, num = ensure_pdf_directory_structure(base_dir="PDF_JSON")
        new_pdf = os.path.join(folder, f"{num}.pdf")
        os.rename(filepath, new_pdf)

        json_path = os.path.join(folder, f"{num}.json")
        data = {"sha512": sha, "contents": contents}
        with open(json_path, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)

        wordcloud_data = generate_wordcloud(all_text, min_word_length=3, max_words=10)
        book_info = extract_named_entities(all_text, max_entities=5, min_word_length=4)
        book_title = extract_book_title(wordcloud_data, book_info)

        # تحديث ملف JSON بإضافة عنوان الكتاب
        data["book_name"] = book_title
        with open(json_path, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)

        # حفظ الصورة المصغرة
        save_pdf_thumbnail(new_pdf, folder)

        logging.info(f"✅ تم معالجة الملف: {new_pdf}، عنوان الكتاب: {book_title}")

    except Exception as e:
        logging.error(f"❌ خطأ أثناء معالجة {filepath}: {e}")


