
import cv2
import pytesseract
import re
import numpy as np
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Setup
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
image_path = r'c:\Users\tarch\OneDrive\เดสก์ท็อป\qr\1765679961630.jpg'

# Import from main.py to test the ACTUAL logic
try:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from main import extract_info_from_image
except ImportError as e:
    print(f"Failed to import main.py: {e}")
    sys.exit(1)

def test_ocr(img_path):
    print(f"Testing image: {img_path}")
    
    # Handle unicode paths on Windows
    try:
        # Read file as byte array first
        with open(img_path, 'rb') as f:
            file_bytes = np.asarray(bytearray(f.read()), dtype=np.uint8)
            img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"Error reading file with unicode path: {e}")
        return

    if img is None:
        print("Failed to load image")
        return

    print("\n--- Testing extract_info_from_image ---")
    result = extract_info_from_image(img)
    print("Result:")
    # Pretty print dict
    for k, v in result.items():
        if k == "raw_text":
            print(f"{k}: <omitted for brevity>")
        else:
            print(f"{k}: {v}")
            
    if "ธ.ค." in str(result.get("date", "")):
        print("\nSUCCESS: Date found with Correct Thai Month!")
    elif result["date"] != "Not found":
         print(f"\nPARTIAL SUCCESS: Date found but maybe not fixed? {result['date']}")
    else:
        print("\nFAILURE: Date NOT found.")

    print("\n--- Experimenting with Advanced Preprocessing ---")
    
    # helper to run ocr
    def dry_run_ocr(image, name, config="--psm 6"):
        text = pytesseract.image_to_string(image, lang="tha+eng", config=config)
        # Check specifically for date part with Thai year 25xx
        match = re.search(r"(\d{1,2})\s+(\S+)\s+(25\d{2})", text)
        found = match.group(0) if match else "No date match"
        print(f"[{name}] Found: {found}")
        return text

    # Base Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. Morphological Dilation (Thicken text)
    kernel = np.ones((2,2), np.uint8)
    # Note: Erosion on white text/black bg makes it thinner. Dilation makes it thicker. 
    # But usually OCR images are black text on white bg.
    # So Erosion makes black text THICKER (erodes the white).
    eroded = cv2.erode(gray, kernel, iterations=1)
    dry_run_ocr(eroded, "Erosion (Thicken Black Text)")

    # 2. Scale 2x + Erosion
    scale = 2
    resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    eroded_2x = cv2.erode(resized, kernel, iterations=1)
    dry_run_ocr(eroded_2x, "Upscale 2x + Erosion")

    # 3. Adaptive Thresholding
    # adaptiveThreshold expects single channel
    file_bytes_again = np.asarray(bytearray(open(img_path, "rb").read()), dtype=np.uint8)
    img_fresh = cv2.imdecode(file_bytes_again, cv2.IMREAD_GRAYSCALE)
    
    adaptive = cv2.adaptiveThreshold(img_fresh, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11)
    dry_run_ocr(adaptive, "Adaptive Threshold")

    # 4. Otsu Threshold + Erosion (High Contrast + Thick)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    otsu_eroded = cv2.erode(otsu, kernel, iterations=1)
    dry_run_ocr(otsu_eroded, "Otsu + Erosion")

    # 5. Contrast Limited Adaptive Histogram Equalization (CLAHE) - enhance details
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    cl1 = clahe.apply(gray)
    dry_run_ocr(cl1, "CLAHE (Contrast Polish)")
    
    # 7. Force Thai Language ONLY (No English)
    # This forces Tesseract to match against Thai dictionary/glyphs only
    def dry_run_ocr_lang(image, name, lang="tha"):
        try:
            text = pytesseract.image_to_string(image, lang=lang, config="--psm 6")
            match = re.search(r"(\d{1,2})\s+(\S+)\s+(25\d{2})", text)
            found = match.group(0) if match else "No date match"
            print(f"[{name}] Found: {found}")
            return text
        except Exception as e:
            print(f"[{name}] Failed: {e}")
            return ""

    dry_run_ocr_lang(gray, "Original Gray (Thai Only)", lang="tha")
    
    # 8. Upscale 2x + Thai Only
    dry_run_ocr_lang(resized, "Upscale 2x (Thai Only)", lang="tha")
    
    # 9. Otsu + Thai Only
    dry_run_ocr_lang(otsu, "Otsu (Thai Only)", lang="tha")



if __name__ == "__main__":
    test_ocr(image_path)
