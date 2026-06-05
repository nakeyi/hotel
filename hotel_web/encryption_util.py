from cryptography.fernet import Fernet
import os

KEY_FILE = "secret.key"

def load_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, 'rb') as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(KEY_FILE, 'wb') as f:
            f.write(key)
        return key

cipher = Fernet(load_or_create_key())

def encrypt_phone(phone: str) -> bytes:
    return cipher.encrypt(phone.encode())

def decrypt_phone(encrypted: bytes) -> str:
    return cipher.decrypt(encrypted).decode()