from flask import Flask, request, jsonify
from PIL import Image
import cv2
import numpy as np
import base64
import io
import pytesseract
import re

app = Flask(__name__)

import os

# If you don't have tesseract executable in your PATH, include the following:
if os.name == 'nt':
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_info_from_image(img):
   
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # เพิ่มความคม
    gray = cv2.GaussianBlur(gray, (3,3), 0)

    # Adaptive Thresholding looks too aggressive for some images causing noise
    # Let's try passing the grayscale image directly first, strictly as the original commented out code suggested
    # or use a simple threshold if needed. Tesseract does its own binarization internally usually.
    
    # Using grayscale directly for now to avoid 'frying' the image
    processed_img = gray
    
    # Debug: Uncomment to save image to check what tesseract sees
    # cv2.imwrite("debug_ocr_input.jpg", processed_img)

    # eng_text = pytesseract.image_to_string(
    #     processed_img,
    #     lang="eng",
    #     config="--psm 6"
    # )
    # print('eng_text',eng_text)
    
    
    ocr_text = pytesseract.image_to_string(
       processed_img, 
       lang="tha+eng",
        config="--oem 1 --psm 11"
    )

    # Extract Amount
    amount = re.search(r"\d{1,3}(,\d{3})*(\.\d{2})", ocr_text)
    amount_val = amount.group() if amount else "Not found"

    # Extract Date
    # Extract Date
    # Flexible pattern to handle OCR errors like "S.A." and time separators like ":"
    # Matches: dd Month yyyy - HH:MM or HH.MM (time optional)
    date_match = re.search(
        r"(\d{1,2})\s*(\S{2,})\s*(25\d{2}|20\d{2})(?:\s*[-–]?\s*(\d{2}[:\.]\d{2}))?",
        ocr_text
    )
    
    date_val = "Not found"
    if date_match:
        # Check if we need to fix the month part (group 2)
        day = date_match.group(1)
        month_raw = date_match.group(2)
        year = date_match.group(3)
        time = date_match.group(4) if date_match.group(4) else "00:00"
        
        # OCR Error Mapping
        # Map incorrect OCR readings to correct Thai months
        month_corrections = {
            "S.A.": "ธ.ค.",  # User reported S.A. -> ธ.ค.
            "5.A.": "ธ.ค.",  # Likely similar error
            "S.A": "ธ.ค.",   # Variant without dot
            "5.A": "ธ.ค.",
            "s.a.": "ธ.ค.",
            "s.a": "ธ.ค.",
        }
        
        month_fixed = month_corrections.get(month_raw, month_raw)
        
        # Reconstruct date string with fixed month
        date_val = f"{day} {month_fixed} {year} - {time}"

    # Extract Ref
    ref = re.search(r"(Ref|Reference|เลขที่อ้างอิง)\s*[:\-]?\s*(\w+)", ocr_text)
    ref_val = ref.group(2) if ref else "Not found"

    return {
        "amount": amount_val,
        "date": date_val,
        "ref": ref_val,
        "raw_text": ocr_text
    }

@app.route('/process_image', methods=['POST'])
def process_image_endpoint():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    print("Filename:", file.filename)
    print("Content-Type:", file.content_type)

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file:
        # Read file into numpy array for cv2
        in_memory_file = io.BytesIO(file.read())
        file_bytes = np.asarray(bytearray(in_memory_file.read()), dtype=np.uint8)
        # Note: io.BytesIO read cursor is at end, need to seek 0 or just use file.read() directly to bytes
        # Let's fix reading:
        in_memory_file.seek(0)
        file_bytes = np.frombuffer(in_memory_file.read(), np.uint8)
        img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

        if img is None:
             return jsonify({"error": "Invalid image file"}), 400

        result = extract_info_from_image(img)
        return jsonify(result)

def ocr_from_base64_logic(base64_str: str) -> str:
    # ลบ prefix ถ้ามี (เช่น data:image/jpeg;base64,)
    if "," in base64_str:
        base64_str = base64_str.split(",")[1]

    image_bytes = base64.b64decode(base64_str)
    image = Image.open(io.BytesIO(image_bytes))
    # Convert PIL to CV2 if we want to use the same pipeline, 
    # or just use Tesseract on PIL image as in original code.
    # For consistency let's stick to the requested extraction logic which used cv2 processing.
    img_np = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    return extract_info_from_image(img_np)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
