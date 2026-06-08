import os
import hashlib
import zlib
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from config import PBKDF2_ITERATIONS, SALT_SIZE, NONCE_SIZE


class CryptoManager:
    # ... (keep existing methods from earlier) ...

    @staticmethod
    def load_rsa_public_key(pem_base64: str):
        """Load RSA public key from base64 string."""
        pem_data = "-----BEGIN PUBLIC KEY-----\n" + pem_base64 + "\n-----END PUBLIC KEY-----"
        key = serialization.load_pem_public_key(pem_data.encode())
        return key

    @staticmethod
    def encrypt_file_asymmetric(data: bytes, rsa_pub_key_pem: str) -> dict:
        """
        Encrypt a file encryption key using RSA public key.
        This wraps the symmetric key so only someone with the private key can decrypt.
        """
        rsa_key = CryptoManager.load_rsa_public_key(rsa_pub_key_pem)

        # Generate a random AES-256 key for the file
        file_key = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(NONCE_SIZE)

        # Encrypt the file with the random AES key
        aesgcm = AESGCM(file_key)
        ciphertext = aesgcm.encrypt(nonce, data, None)

        # Encrypt the file key with RSA public key
        encrypted_key = rsa_key.encrypt(
            file_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        return {
            'ciphertext': ciphertext,
            'nonce': nonce,
            'encrypted_key': encrypted_key,  # RSA-encrypted AES key
            'checksum': hashlib.sha256(ciphertext).hexdigest(),
            'algorithm': 'AES-256-GCM + RSA-2048-OAEP'
        }
