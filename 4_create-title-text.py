import os
import json

def extract_book_title(wordcloud_data, book_info):
    """ استخراج عنوان مناسب للكتاب باستخدام بيانات wordcloud_data و book_info """
    
    # ترتيب الكلمات الأكثر أهمية في سحابة الكلمات
    sorted_words = sorted(wordcloud_data.items(), key=lambda x: x[1], reverse=True)
    top_keywords = [word for word, _ in sorted_words[:3]]  # أخذ أهم 3 كلمات
    
    # استخراج الأسماء من book_info
    authors = [entry["text"] for entry in book_info if entry["type"] == "PERS"]
    organizations = [entry["text"] for entry in book_info if entry["type"] == "ORG"]
    
    # تكوين العنوان بناءً على الكلمات الأساسية والمؤلفين
    title_parts = []
    if authors:
        title_parts.append("، ".join(authors))  # إضافة المؤلفين أولًا
    if top_keywords:
        title_parts.append(" - ".join(top_keywords))  # إضافة الكلمات المفتاحية المهمة
    if organizations:
        title_parts.append(f"إعداد {organizations[0]}")  # إذا وُجدت منظمة، تُضاف
    
    return " | ".join(title_parts)  # دمج الأجزاء في عنوان واحد

def update_json_files(json_folder):
    """ تحديث ملفات JSON بإضافة book_name """
    for root, _, files in os.walk(json_folder):
        for filename in files:
            if filename.endswith('.json'):
                file_path = os.path.join(root, filename)
                
                with open(file_path, 'r', encoding='utf-8') as json_file:
                    data = json.load(json_file)
                
                # استخراج البيانات اللازمة
                wordcloud_data = data.get("wordcloud_data", {})
                book_info = data.get("book_info", [])

                if wordcloud_data and book_info:
                    book_name = extract_book_title(wordcloud_data, book_info)
                    data = {"book_name": book_name, **data}  # وضع العنوان كمفتاح أول
                
                    with open(file_path, 'w', encoding='utf-8') as json_file:
                        json.dump(data, json_file, ensure_ascii=False, indent=4)

                    print(f"✅ تم تحديث {file_path} وإضافة book_name: {book_name}")

# تشغيل التحديث على ملفات JSON داخل مجلد 'pdf'
update_json_files('E:\\mws_server\\import_pdf_py_file\\PDF_JSON')