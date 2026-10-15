from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.parse
from typing import Any

from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.hmac import HMAC


def random_urlsafe(byte_count: int = 32) -> str:
    return base64.urlsafe_b64encode(os.urandom(byte_count)).rstrip(b"=").decode()


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def encrypt_svc_param(payload: dict[str, Any], chk_do_num: int, public_key_b64: str) -> str:
    chk_text = str(chk_do_num)
    hashed = base64.b64encode(hashlib.sha256(chk_text.encode()).digest())
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", hashed, salt, chk_do_num, dklen=16)
    public_key = serialization.load_der_public_key(base64.b64decode(public_key_b64))
    encrypted_key = public_key.encrypt(base64.b64encode(derived), asym_padding.PKCS1v15())

    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    plaintext = json.dumps(payload, separators=(",", ":")).encode()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(derived), modes.CBC(iv)).encryptor()
    encrypted_payload = encryptor.update(padded) + encryptor.finalize()

    envelope = {
        "chkDoNum": chk_text,
        "svcEncParam": base64.b64encode(encrypted_payload).decode(),
        "svcEncKY": base64.b64encode(encrypted_key).decode(),
        "svcEncIV": iv.hex(),
    }
    encoded = base64.b64encode(json.dumps(envelope).encode()).decode()
    return urllib.parse.quote(encoded, safe="")


def decrypt_auth_value(value: str, key: str) -> str:
    key_bytes = key.encode()[:16].ljust(16, b"\0")
    decryptor = Cipher(algorithms.AES(key_bytes), modes.ECB()).decryptor()
    padded = decryptor.update(bytes.fromhex(value)) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode()


def _kdf2_sha1(seed: bytes, length: int) -> bytes:
    result = bytearray()
    counter = 1
    while len(result) < length:
        result.extend(hashlib.sha1(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(result[:length])


def _decrypt_private_key(private_key_b64: str, iv_b64: str, pin: str, user_id: str | None):
    use_v2 = private_key_b64.endswith("_v2")
    encoded = private_key_b64.removesuffix("_v2")
    encrypted_private = base64.b64decode(encoded)
    iv = base64.b64decode(iv_b64)
    pin_material = f"{pin}{user_id or ''}" if use_v2 else pin
    aes_key = hashlib.sha256(pin_material.encode()).digest()

    decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(encrypted_private) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    der = unpadder.update(padded) + unpadder.finalize()
    key = serialization.load_der_private_key(der, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("Samsung location key is not an EC private key")
    return key


def _bc_ecies_decrypt(value: str, private_key: ec.EllipticCurvePrivateKey) -> str:
    raw = base64.b64decode(value)
    coord_len = (private_key.curve.key_size + 7) // 8
    if not raw:
        raise ValueError("Empty ECIES payload")
    if raw[0] == 4:
        v_len = 1 + 2 * coord_len
    elif raw[0] in (2, 3):
        v_len = 1 + coord_len
    else:
        raise ValueError("Unsupported EC point encoding")

    mac_len = 20
    if len(raw) <= v_len + mac_len:
        raise ValueError("ECIES payload is too short")

    ephemeral_bytes = raw[:v_len]
    ciphertext = raw[v_len:-mac_len]
    received_mac = raw[-mac_len:]

    ephemeral_key = ec.EllipticCurvePublicKey.from_encoded_point(
        private_key.curve, ephemeral_bytes
    )
    shared_secret = private_key.exchange(ec.ECDH(), ephemeral_key)

    # BouncyCastle 1.78.1 ECIES defaults:
    # KDF2(SHA-1), HMAC-SHA1, 128-bit MAC key, no block cipher.
    derived = _kdf2_sha1(ephemeral_bytes + shared_secret, 16 + len(ciphertext))
    mac_key = derived[:16]
    stream_key = derived[16:]

    mac = HMAC(mac_key, hashes.SHA1())
    mac.update(ciphertext)
    mac.update(b"\0" * 8)
    calculated_mac = mac.finalize()
    if not hmac.compare_digest(received_mac, calculated_mac):
        raise ValueError("ECIES MAC verification failed")

    plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream_key, strict=True))
    return plaintext.decode()


def decrypt_coordinates(
    latitude: str,
    longitude: str,
    key_pair: dict[str, Any] | None,
    pin: str | None,
) -> tuple[float | None, float | None, bool, bool]:
    try:
        return float(latitude), float(longitude), False, False
    except (TypeError, ValueError):
        pass

    if not key_pair:
        return None, None, True, False
    if not pin:
        return None, None, True, True

    private_key_b64 = key_pair.get("privateKey")
    iv_b64 = key_pair.get("iv")
    if not private_key_b64 or not iv_b64:
        return None, None, True, False

    private_key = _decrypt_private_key(
        str(private_key_b64),
        str(iv_b64),
        pin,
        key_pair.get("userId"),
    )
    decrypted_lat = float(_bc_ecies_decrypt(str(latitude), private_key))
    decrypted_lon = float(_bc_ecies_decrypt(str(longitude), private_key))
    return decrypted_lat, decrypted_lon, True, False
