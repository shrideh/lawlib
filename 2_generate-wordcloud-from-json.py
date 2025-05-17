import os
import json
from sklearn.feature_extraction.text import TfidfVectorizer
from nltk.tokenize import word_tokenize
from pyarabic.araby import strip_tashkeel, strip_tatweel
import re


def extract_text_from_json(json_file_path):
    """استخراج النص من ملف JSON"""
    all_text = ""
    if os.path.isfile(json_file_path) and json_file_path.endswith('.json'):
        with open(json_file_path, 'r', encoding='utf-8') as json_file:
            data = json.load(json_file)
            for page in data.get("contents", []):
                all_text += page.get("text", "") + " "
    return all_text.strip()


def find_json_files(json_folder):
    """العثور على جميع ملفات JSON في المجلد والمجلدات الفرعية"""
    json_files = []
    for root, _, files in os.walk(json_folder):
        for filename in files:
            if filename.endswith('.json'):
                json_files.append(os.path.join(root, filename))
    return json_files


def generate_wordcloud(text, min_word_length=3, max_words=10):
    """توليد أهم الكلمات باستخدام TF-IDF"""
    
    # تنظيف النص وإزالة الرموز غير العربية
    text = re.sub(r'[^\u0600-\u06FF\s]', '', text)
    
    # تقسيم النص إلى كلمات
    words = word_tokenize(text)
    
    # تصفية الكلمات القصيرة
    filtered_words = [word for word in words if len(word) >= min_word_length]
    
    if not filtered_words:
        return {}  # لا يوجد كلمات كافية، أعد dict فارغ

    # تحويل القائمة إلى نص واحد
    filtered_text = ' '.join(filtered_words)
    
    # حساب قيم TF-IDF
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform([filtered_text])
    tfidf_scores = dict(zip(vectorizer.get_feature_names_out(), tfidf_matrix.toarray()[0]))
    
    # ترتيب الكلمات حسب الأهمية واختيار الأعلى
    sorted_words = sorted(tfidf_scores.items(), key=lambda item: item[1], reverse=True)
    most_important_words = dict(sorted_words[:max_words])
    
    return most_important_words


json_folder = 'E:\\mws_server\\import_pdf_py_file\\PDF_JSON'
files = find_json_files(json_folder)

for file in files:
    with open(file, 'r', encoding='utf-8') as json_file:
        data = json.load(json_file)
    
    text = extract_text_from_json(file)
    wordcloud_data = generate_wordcloud(text)
    
    # إدراج wordcloud_data في السطر الثاني من الملف
    new_data = {"wordcloud_data": wordcloud_data, **data}

    with open(file, 'w', encoding='utf-8') as json_file:
        json.dump(new_data, json_file, ensure_ascii=False, indent=4)

    print(f"تم تحديث الملف: {file} وإضافة بيانات wordcloud_data")
