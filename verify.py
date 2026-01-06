import cv2
from PIL import Image
import numpy as np
import binascii


def read_qr_opencv(image_path):
    img = Image.open(image_path).convert("RGB")
    img = np.array(img)

    detector = cv2.QRCodeDetector()
    data, bbox, _ = detector.detectAndDecode(img)

    if not data:
        raise ValueError("ไม่พบ QR code")
    return data


# ฟังก์ชัน parse EMV TLV แบบง่าย (ค่าทุกอย่างเป็นตัวอักษร hex-like length)
def parse_emv_qr(s):
    i = 0
    result = {}
    while i < len(s):
        tag = s[i:i+2]; i += 2
        length = int(s[i:i+2]); i += 2
        value = s[i:i+length]; i += length
        result[tag] = value
    return result

# ตรวจ CRC-16/CCITT เบื้องต้น โดยสมมติว่าในสตริงมี tag '63' เป็น CRC (ตาม EMVCo)
def check_crc(emv_string):
    # เอาส่วนก่อน tag 63 (รวม '63' และความยาวสองตัว '04' แตะต้องต้องมีตามสเปค)
    # วิธีง่าย: หาตำแหน่งของ '63' (CRC tag) แล้วคำนวณ CRC ของ substring ก่อนหน้า + '63'+'04' ตามสเปค
    idx = emv_string.find('63')
    if idx == -1:
        return False, "ไม่พบ tag 63 (CRC)"
    data_to_crc = emv_string[:idx] + '63' + '04'  # ตามสเปค จะคำนวณ CRC บนส่วนนี้
    # binascii.crc_hqx ใช้ CRC-CCITT (polynomial 0x1021) กับ seed
    crc = binascii.crc_hqx(data_to_crc.encode('utf-8'), 0xFFFF)
    crc_hex = format(crc, '04X')
    # ค่า CRC ที่อยู่ในสตริง (สมมติเก็บเป็น 4 ตัวอักษร hex)
    crc_in_qr = emv_string[idx+4:idx+8].upper()
    return crc_hex == crc_in_qr, (crc_hex, crc_in_qr)

def parse_tlv(data):
    i = 0
    result = []
    while i < len(data):
        tag = data[i:i+2]
        length = int(data[i+2:i+4])
        value = data[i+4:i+4+length]
        result.append((tag, value))
        i += 4 + length
    return result

def extract_promptpay_info(qr):
    tlvs = parse_tlv(qr)
    info = {}

    for tag, value in tlvs:
        if tag == "29":  # Merchant Account Info
            sub = parse_tlv(value)
            for st, sv in sub:
                if st == "01":
                    info["promptpay_id"] = sv
        elif tag == "54":
            info["amount"] = value
        elif tag == "53":
            info["currency"] = value
        elif tag == "58":
            info["country"] = value

    return info




if __name__ == "__main__":
    text = read_qr_opencv("1765679961630.jpg")
    print("QR text:", text)
    parsed = parse_emv_qr(text)
    print("Parsed tags:", parsed.keys())
    ok, info = check_crc(text)