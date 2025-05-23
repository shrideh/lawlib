###################################################
# استخراج كل الشا512 المكرر من ملفات جيسون وحفظهم #
###################################################

# import os
# import json
# from collections import defaultdict

# root_dir = r"E:\mws_server\import_pdf_py_file\PDF_JSON"
# sha_dict = defaultdict(list)

# # المرور على جميع ملفات JSON
# for dirpath, _, filenames in os.walk(root_dir):
#     for filename in filenames:
#         if filename.lower().endswith(".json"):
#             json_path = os.path.join(dirpath, filename)
#             try:
#                 with open(json_path, "r", encoding="utf-8") as jf:
#                     data = json.load(jf)
#                     sha = data.get("sha512")
#                     if sha:
#                         sha_dict[sha].append(json_path)
#             except Exception as e:
#                 print(f"Error reading {json_path}: {e}")

# # استخراج التكرارات فقط
# duplicates = {sha: paths for sha, paths in sha_dict.items() if len(paths) > 1}

# # حفظ التكرارات في ملف JSON
# output_path = os.path.join(root_dir, "duplicate_sha512_files.json")
# with open(output_path, "w", encoding="utf-8") as out_file:
#     json.dump(duplicates, out_file, indent=4, ensure_ascii=False)

# print(f"Done. Duplicate entries saved to {output_path}")

#######################################################################
# نقل الملفات المكررة مع اعادة التسمية وذلك بقراءة الملف الذي تم حفظه #
#                          في المرحلة الاولى                          #
#######################################################################

# import os
# import json
# import shutil
# import random
# import string

# def generate_random_string(length=6):
#     return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# root_dir = r"E:\mws_server\import_pdf_py_file\PDF_JSON"
# duplicate_file = os.path.join(root_dir, "duplicate_sha512_files.json")
# destination_dir = os.path.join(root_dir, "duplicates_moved")

# # إنشاء مجلد النسخ المنقولة إذا لم يكن موجودًا
# os.makedirs(destination_dir, exist_ok=True)

# # تحميل بيانات التكرار
# with open(duplicate_file, "r", encoding="utf-8") as f:
#     duplicates = json.load(f)

# # معالجة كل مجموعة SHA512 مكررة
# for sha, file_list in duplicates.items():
#     keep_file = file_list[0]
#     duplicate_files = file_list[1:]

#     for json_file in duplicate_files:
#         base_path = os.path.splitext(json_file)[0]
#         related_extensions = [".json", ".pdf", ".jpg"]
#         random_prefix = generate_random_string()

#         for ext in related_extensions:
#             full_path = base_path + ext
#             if os.path.exists(full_path):
#                 try:
#                     new_filename = f"{random_prefix}_{os.path.basename(full_path)}"
#                     dest_path = os.path.join(destination_dir, new_filename)
#                     shutil.move(full_path, dest_path)
#                     print(f"Moved and renamed: {full_path} -> {dest_path}")
#                 except Exception as e:
#                     print(f"Error moving {full_path}: {e}")
#             else:
#                 print(f"Not found: {full_path}")

# print("تم نقل وإعادة تسمية النسخ المكررة بنجاح.")

# ############################################
# # سكربت بايثون بسيط يمر على كل ملفات جيسون #
# #  داخل مجلد الروت (مع المجلدات الفرعية)،  #
# #       ويقرأ قيمة الشا512 من كل ملف       #
# ############################################

# import os
# import json
# from collections import defaultdict

# root_dir = r"E:\mws_server\import_pdf_py_file\PDF_JSON"
# sha_dict = defaultdict(list)

# for dirpath, _, filenames in os.walk(root_dir):
#     for filename in filenames:
#         if filename.lower().endswith(".json"):
#             json_path = os.path.join(dirpath, filename)
#             try:
#                 with open(json_path, "r", encoding="utf-8") as f:
#                     data = json.load(f)
#                     sha = data.get("sha512")
#                     if sha:
#                         sha_dict[sha].append(json_path)
#             except Exception as e:
#                 print(f"خطأ في قراءة أو تحليل الملف {json_path}: {e}")

# # تحويل القاموس إلى dict عادي (اختياري)
# sha_dict = dict(sha_dict)

# print(f"تم جمع {len(sha_dict)} قيمة SHA512 فريدة من ملفات JSON.")

# # لو حبيت تحفظهم في ملف JSON:
# output_path = os.path.join(root_dir, "sha512_dictionary.json")
# with open(output_path, "w", encoding="utf-8") as f:
#     json.dump(sha_dict, f, ensure_ascii=False, indent=4)

# print(f"تم حفظ القاموس في الملف: {output_path}")

#############################
# حساب شا512 للمفات الجديدة #
#############################

# import os
# import hashlib
# import json
# from collections import defaultdict

# def calculate_sha512(fp):
#     sha = hashlib.sha512()
#     with open(fp, "rb") as f:
#         for block in iter(lambda: f.read(4096), b""):
#             sha.update(block)
#     return sha.hexdigest()

# root_dir = r"E:\mws_server\import_pdf_py_file\my_pdf\new_pdf"
# sha_dict = defaultdict(list)

# # المرور على كل ملفات PDF
# for dirpath, _, filenames in os.walk(root_dir):
#     for filename in filenames:
#         if filename.lower().endswith(".pdf"):
#             pdf_path = os.path.join(dirpath, filename)
#             try:
#                 sha = calculate_sha512(pdf_path)
#                 sha_dict[sha].append(pdf_path)
#                 print(f"SHA512: {sha} -> {pdf_path}")
#             except Exception as e:
#                 print(f"Error processing {pdf_path}: {e}")

# # تحويل القاموس إلى dict عادي
# sha_dict = dict(sha_dict)

# # حفظ القاموس في ملف JSON (اختياري)
# output_path = os.path.join(root_dir, "new_pdf_sha512_dictionary.json")
# with open(output_path, "w", encoding="utf-8") as f:
#     json.dump(sha_dict, f, ensure_ascii=False, indent=4)

# print(f"تم حفظ قاموس SHA512 في: {output_path}")


###########################################
# مقارنة القاموس القديم مع القاموس الجديد #
###########################################

# import json
# import os

# # المسارات إلى القواميس السابقة
# pdf_json_sha_file = r"E:\mws_server\import_pdf_py_file\PDF_JSON\sha512_dictionary.json"
# new_pdf_sha_file = r"E:\mws_server\import_pdf_py_file\my_pdf\new_pdf\new_pdf_sha512_dictionary.json"

# # تحميل القواميس
# with open(pdf_json_sha_file, "r", encoding="utf-8") as f:
#     old_sha_dict = json.load(f)

# with open(new_pdf_sha_file, "r", encoding="utf-8") as f:
#     new_sha_dict = json.load(f)

# # إنشاء قاموس الملفات المكررة
# duplicate_files = {}

# for sha, new_paths in new_sha_dict.items():
#     if sha in old_sha_dict:
#         duplicate_files[sha] = new_paths

# # حفظ الملفات المكررة في ملف جديد
# output_path = r"E:\mws_server\import_pdf_py_file\my_pdf\new_pdf\duplicate_from_old.json"
# with open(output_path, "w", encoding="utf-8") as f:
#     json.dump(duplicate_files, f, ensure_ascii=False, indent=4)

# print(f"تم العثور على {len(duplicate_files)} ملفات مكررة. تم حفظها في:")
# print(output_path)


######################################
# نقل هذه الملفات المكررة من NEW_PDF #
######################################

# import os
# import json
# import shutil
# import random
# import string

# def generate_random_string(length=6):
#     return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# # المسارات
# base_dir = r"E:\mws_server\import_pdf_py_file\my_pdf\new_pdf"
# duplicate_file = os.path.join(base_dir, "duplicate_from_old.json")
# destination_dir = os.path.join(base_dir, "duplicates_moved")

# # إنشاء مجلد النقل إذا لم يكن موجودًا
# os.makedirs(destination_dir, exist_ok=True)

# # تحميل الملفات المكررة
# with open(duplicate_file, "r", encoding="utf-8") as f:
#     duplicates = json.load(f)

# # نقل ملفات PDF فقط مع إعادة التسمية
# for sha, file_list in duplicates.items():
#     for pdf_path in file_list:
#         if os.path.exists(pdf_path):
#             random_prefix = generate_random_string()
#             new_filename = f"{random_prefix}_{os.path.basename(pdf_path)}"
#             dest_path = os.path.join(destination_dir, new_filename)
#             try:
#                 shutil.move(pdf_path, dest_path)
#                 print(f"Moved and renamed: {pdf_path} -> {dest_path}")
#             except Exception as e:
#                 print(f"Error moving {pdf_path}: {e}")
#         else:
#             print(f"Not found: {pdf_path}")

# print("✅ تم نقل وإعادة تسمية ملفات PDF المكررة بنجاح.")