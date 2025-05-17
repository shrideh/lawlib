import os
import uuid
import logging
import hashlib
import json
import gc
from pdf2image import convert_from_path, pdfinfo_from_path
import pytesseract as tess
from PIL import Image
import concurrent.futures
from pdf2image.exceptions import (
    PDFPageCountError,
    PDFSyntaxError,
    PDFInfoNotInstalledError,
)
from pyarabic.araby import strip_tashkeel, strip_tatweel
import re
from tqdm import tqdm
import cv2

# إعداد مسار تيسراكت
tesseract_path = (
    "C:\\Users\\user\\AppData\\Local\\Programs\\Tesseract-OCR\\tesseract.exe"
)
tess.pytesseract.tesseract_cmd = tesseract_path

# إعدادات اللوق
logging.basicConfig(
    filename="E:\\mws_server\\import_pdf_py_file\\logs\\pdf_processing_errors.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def load_stop_words():
    with open(
        "E:\\mws_server\\import_pdf_py_file\\arabic-stop-words.txt",
        "r",
        encoding="utf-8",
    ) as f:
        return set(line.strip() for line in f)


def load_quran_words():
    with open(
        "E:\\mws_server\\import_pdf_py_file\\quran.txt", "r", encoding="utf-8"
    ) as f:
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
    # تقليل دقة الصورة لتحسين استهلاك الذاكرة
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


def ensure_pdf_directory_structure(base_dir="pdf", max_files_per_folder=200):
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
            poppler_path="C:\\poppler-0.68.0\\bin",
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
            print(f"✅ تم حفظ الصورة المصغرة: {thumb_path}")
            return thumb_path
    except Exception as e:
        logging.error(f"❌ خطأ أثناء استخراج الصورة من {pdf_path}: {e}")
    return None


def process_pdf(filepath):
    try:
        # تحديد عدد الصفحات أولاً
        info = pdfinfo_from_path(filepath, poppler_path="C:\\poppler-0.68.0\\bin")
        num_pages = info.get("Pages", 0)
        all_text = ""
        contents = []

        print(f"📄 معالجة الملف: {os.path.basename(filepath)} ({num_pages} صفحات)")
        for page in tqdm(
            range(1, num_pages + 1), desc="📊 معالجة الصفحات", unit="صفحة", ncols=100
        ):
            # تحويل صفحة واحدة فقط في كل مرة
            imgs = convert_from_path(
                filepath,
                poppler_path="C:\\poppler-0.68.0\\bin",
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
            temp_path = f"E:/mws_server/import_pdf_py_file/tmp/{uuid.uuid4()}.jpg"
            img.save(temp_path, "JPEG")
            img.close()

            text = img_to_txt(temp_path)
            all_text += text
            contents.append({"page": page, "text": text})
            os.remove(temp_path)

            # تحرير الذاكرة
            del imgs
            gc.collect()

        # تنظيم المجلدات وحفظ الملفات
        folder, num = ensure_pdf_directory_structure(
            base_dir="E:\\mws_server\\import_pdf_py_file\\PDF_JSON"
        )
        new_pdf = os.path.join(folder, f"{num}.pdf")
        os.rename(filepath, new_pdf)

        data = {
            "pdf_filename": f"{num}.pdf",
            "sha512": calculate_sha512(new_pdf),
            "contents": contents,
        }
        json_path = os.path.join(folder, f"{num}.json")
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(data, jf, ensure_ascii=False, indent=4)

        logging.info(f"✅ تم معالجة {new_pdf}، JSON احفظ في {json_path}")
        thumb = save_pdf_thumbnail(new_pdf, folder)
        if thumb:
            print(f"📷 مصغرة: {thumb}")

    except (PDFPageCountError, PDFSyntaxError, PDFInfoNotInstalledError) as e:
        logging.error(f"❌ خطأ في معالجة {filepath}: {e}")
    except Exception as e:
        logging.error(f"❌ خطأ غير متوقع في {filepath}: {e}")


if __name__ == "__main__":
    pdf_untidy = "E:\\mws_server\\import_pdf_py_file\\my_pdf\\new_pdf\\59"
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for root, _, files in os.walk(pdf_untidy):
            for fn in files:
                if fn.lower().endswith(".pdf"):
                    path = os.path.join(root, fn)
                    futures[executor.submit(process_pdf, path)] = fn
        for future in concurrent.futures.as_completed(futures):
            fn = futures[future]
            try:
                future.result()
            except Exception as e:
                logging.error(f"❌ خطأ في ملف {fn}: {e}")
