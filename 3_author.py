import os
import json
import warnings
import logging
from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline

# إخفاء التحذيرات والرسائل غير الضرورية
warnings.simplefilter("ignore")
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("transformers.modeling_utils").setLevel(logging.CRITICAL)

# تحميل النموذج والمعالج
model_name = "E:/mws_server/import_pdf_py_file/models/models--CAMeL-Lab--bert-base-arabic-camelbert-mix-ner"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForTokenClassification.from_pretrained(model_name)

# إنشاء pipeline لاستخراج الكيانات المسماة
ner_pipeline = pipeline(
    "ner",
    model=model,
    tokenizer=tokenizer,
    aggregation_strategy="simple"
)

def load_json_file(file_path):
    """ تحميل ملف JSON وإصلاحه إذا كان معطوبًا """
    try:
        with open(file_path, 'r', encoding='utf-8') as json_file:
            content = json_file.read().strip()
            if not content:
                raise ValueError("Empty file")
            data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        print(f"⚠️ تحذير: الملف {file_path} معطوب أو فارغ، سيتم إصلاحه!")
        data = {"contents": []}  # تعيين بيانات افتراضية
        with open(file_path, 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)
    return data

def extract_text_from_json(json_data, max_pages=200):
    """ استخراج النصوص من أول max_pages صفحات من JSON """
    extracted_text = " ".join(
        page.get("text", "") for page in json_data.get("contents", [])[:max_pages]
    )
    return extracted_text.strip()

def find_json_files(json_folder):
    """ البحث عن جميع ملفات JSON داخل المجلد والمجلدات الفرعية """
    json_files = []
    for root, _, files in os.walk(json_folder):
        for filename in files:
            if filename.endswith('.json'):
                json_files.append(os.path.join(root, filename))
    return json_files

def split_text_into_chunks(text, tokenizer, max_length=512):
    """تقسيم النص إلى أجزاء لا تتجاوز 512 توكن باستخدام tokenizer"""
    tokens = tokenizer.tokenize(text)
    chunks = []
    
    for i in range(0, len(tokens), max_length - 10):  # ترك مساحة صغيرة لتجنب تجاوز الحد الأقصى
        chunk_tokens = tokens[i:i + max_length - 10]
        chunk_text = tokenizer.convert_tokens_to_string(chunk_tokens)
        chunks.append(chunk_text)
    
    return chunks

def extract_named_entities(text, max_entities=5, min_word_length=4):
    """استخراج أول max_entities كيانًا مسمى، مع تصفية الكلمات الأقل من min_word_length"""
    if not text.strip():
        return []

    chunks = split_text_into_chunks(text, tokenizer, max_length=512)
    extracted_entities = []

    for chunk in chunks:
        entities = ner_pipeline(chunk[:512])  # التأكد من أن الإدخال لا يتجاوز الحد الأقصى
        for entity in entities:
            word = entity["word"].strip()
            if len(word) >= min_word_length:
                extracted_entities.append({
                    "text": word,
                    "type": entity["entity_group"],
                    "score": round(float(entity["score"]), 3)
                })
            
            # إذا وصلت إلى الحد الأقصى، توقف
            if len(extracted_entities) >= max_entities:
                return extracted_entities

    return extracted_entities[:max_entities]

json_folder = 'E:\\mws_server\\import_pdf_py_file\\PDF_JSON'
files = find_json_files(json_folder)

for file in files:
    data = load_json_file(file)  # تحميل بيانات JSON (مع الإصلاح إن لزم)
    
    text = extract_text_from_json(data, max_pages=5)
    book_info = extract_named_entities(text, max_entities=5, min_word_length=4)

    if "book_info" in data:
        print(f"📌 تحديث بيانات book_info في {file}")
    else:
        print(f"✅ إضافة book_info إلى {file}")

    # تحديث البيانات وإعادة حفظها
    data["book_info"] = book_info
    with open(file, 'w', encoding='utf-8') as json_file:
        json.dump(data, json_file, ensure_ascii=False, indent=4)

print("\n🎯 تمت معالجة جميع الملفات بنجاح!")

