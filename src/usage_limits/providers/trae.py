"""Trae usage limits provider."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import TypedDict, cast

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow

# ByteCrypto constants
BYTE_CRYPTO_HEADER_LEN = 6
BYTE_CRYPTO_SHA512_LEN = 64
BYTE_CRYPTO_RANDOM_KEY_LEN = 32
BYTE_CRYPTO_PREFIX_AES = bytes([116, 99, 5, 16, 0, 0])

# Salt arrays from Rust source
BYTE_CRYPTO_AES_A = bytes([
    82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
    124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
    84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
    8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37,
])
BYTE_CRYPTO_AES_B = bytes([
    31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
    96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
    160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
    23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125,
])


def byte_crypto_decrypt(encrypted_b64: str) -> str:
    """Decrypt ByteCrypto-encrypted value (AES-128-CBC with SHA-512 integrity).

    Format: base64(header[6] + key_material[32] + ciphertext)
    Key derivation: SHA-512(key_material) + SHA-512(salt_A XOR salt_B) -> SHA-512
    Integrity: decrypted data = SHA512(plaintext)[64] + plaintext
    """
    encrypted_data = base64.b64decode(encrypted_b64)

    # Verify header
    if not encrypted_data.startswith(BYTE_CRYPTO_PREFIX_AES):
        raise ValueError("Invalid ByteCrypto header")

    if len(encrypted_data) <= BYTE_CRYPTO_HEADER_LEN + BYTE_CRYPTO_RANDOM_KEY_LEN:
        raise ValueError("ByteCrypto data too short")

    # Extract key material and ciphertext
    key_material = encrypted_data[
        BYTE_CRYPTO_HEADER_LEN : BYTE_CRYPTO_HEADER_LEN + BYTE_CRYPTO_RANDOM_KEY_LEN
    ]
    ciphertext = encrypted_data[BYTE_CRYPTO_HEADER_LEN + BYTE_CRYPTO_RANDOM_KEY_LEN :]

    if len(ciphertext) == 0 or len(ciphertext) % 16 != 0:
        raise ValueError("Invalid ciphertext length")

    # Derive AES key and IV
    # Step 1: SHA-512 of key_material
    key_hash = hashlib.sha512(key_material).digest()

    # Step 2: Compute salt = AES_A XOR AES_B
    salt = bytes(a ^ b for a, b in zip(BYTE_CRYPTO_AES_A, BYTE_CRYPTO_AES_B, strict=True))

    # Step 3: Merge key_hash + salt, then SHA-512 again
    merge = key_hash + salt
    merged_hash = hashlib.sha512(merge).digest()

    # Step 4: Extract AES key (first 16 bytes) and IV (next 16 bytes)
    aes_key = merged_hash[:16]
    iv = merged_hash[16:32]

    # Decrypt
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()

    # Unpad PKCS7
    unpadder = PKCS7(128).unpadder()
    decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()

    # Verify integrity: first 64 bytes are SHA-512 of plaintext
    if len(decrypted) < BYTE_CRYPTO_SHA512_LEN:
        raise ValueError("Decrypted data too short")

    stored_hash = decrypted[:BYTE_CRYPTO_SHA512_LEN]
    plaintext = decrypted[BYTE_CRYPTO_SHA512_LEN:]

    computed_hash = hashlib.sha512(plaintext).digest()
    if stored_hash != computed_hash:
        raise ValueError("ByteCrypto integrity check failed")

    return plaintext.decode("utf-8")


class TraeQuota(TypedDict):
    basic_usage_limit: float
    bonus_usage_limit: float


class TraeProductExtra(TypedDict):
    subscription_extra: dict[str, object] | None


class TraeEntitlementBaseInfo(TypedDict):
    product_type: int
    quota: TraeQuota
    end_time: int
    product_extra: TraeProductExtra


class TraeUsage(TypedDict):
    basic_usage_amount: float
    bonus_usage_amount: float
    is_flash_consuming: bool
    pay_go_amount: float


class TraeEntitlementPack(TypedDict):
    product_type: int
    status: int
    entitlement_base_info: TraeEntitlementBaseInfo
    usage: TraeUsage
    next_billing_time: int


class TraeUsageResponse(TypedDict):
    code: int
    user_entitlement_pack_list: list[TraeEntitlementPack]


# Product type priorities (higher index = higher tier)
PRODUCT_TIER_ORDER = [0, 8, 9, 1, 4, 6]  # Free, Lite, Trial, Pro, Pro+, Ultra
PRODUCT_NAMES = {
    0: "Free",
    1: "Pro",
    2: "Package",
    3: "PromoCode",
    4: "Pro+",
    6: "Ultra",
    7: "PayGo",
    8: "Lite",
    9: "Trial",
}

# Region origins
REGION_ORIGINS = {
    "CN": "https://grow-normal.trae.ai",
    "SG": "https://growsg-normal.trae.ai",
    "US": "https://growva-normal.trae.ai",
    "USTTP": "https://grow-normal.traeapi.us",
}


class TraeProvider(UsageProvider):
    """Trae usage checker (per-plan quota tracking)."""

    slug = "trae"
    name = "Trae"
    state_dir = "trae_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()
        self.state_db = (
            Path.home()
            / ".config"
            / "Trae"
            / "User"
            / "globalStorage"
            / "storage.json"
        )

    def provider_name(self) -> str:
        return "Trae"

    def get_access_token(self) -> str:
        with open(self.state_db) as f:
            storage = json.load(f)
        auth_info_b64 = storage["iCubeAuthInfo://icube.cloudide"]
        auth_data: dict[str, object] = json.loads(byte_crypto_decrypt(auth_info_b64))
        token = auth_data["token"]
        assert isinstance(token, str)
        return token

    def get_api_origin(self) -> str:
        """Determine API origin from stored auth or default to CN."""
        try:
            with open(self.state_db) as f:
                storage = json.load(f)
            auth_info_b64 = storage["iCubeAuthInfo://icube.cloudide"]
            auth_data = json.loads(byte_crypto_decrypt(auth_info_b64))
            login_host = auth_data.get("loginHost", "")
            if "traeapi.us" in login_host:
                return REGION_ORIGINS["USTTP"]
            if "growsg" in login_host:
                return REGION_ORIGINS["SG"]
            if "growva" in login_host:
                return REGION_ORIGINS["US"]
        except (KeyError, json.JSONDecodeError, ValueError):
            pass
        return REGION_ORIGINS["CN"]

    def fetch_raw(self) -> TraeUsageResponse:
        access_token = self.get_access_token()
        origin = self.get_api_origin()
        usage_url = f"{origin}/trae/api/v1/pay/ide_user_ent_usage"

        resp = requests.post(
            usage_url,
            headers={
                "Authorization": f"Cloud-IDE-JWT {access_token}",
                "Content-Type": "application/json",
            },
            json={"require_usage": True},
            timeout=30,
        )
        resp.raise_for_status()
        return cast(TraeUsageResponse, resp.json())

    def to_rows(self, raw: TraeUsageResponse) -> list[UsageRow]:
        rows: list[UsageRow] = []

        packs = raw["user_entitlement_pack_list"]

        if not packs:
            return rows

        # Find highest-tier pack
        def tier_priority(pack: TraeEntitlementPack) -> int:
            pt = pack["entitlement_base_info"]["product_type"]
            if pt in PRODUCT_TIER_ORDER:
                return PRODUCT_TIER_ORDER.index(pt)
            return -1

        best_pack = max(packs, key=tier_priority)

        base_info = best_pack["entitlement_base_info"]
        product_type = base_info["product_type"]
        identity = PRODUCT_NAMES.get(product_type, f"Unknown({product_type})")

        usage = best_pack["usage"]

        # Quota is nested in product_extra.subscription_extra.quota
        extra = base_info.get("product_extra", {}).get("subscription_extra")
        quota: dict[str, object] = {}
        if extra:
            quota = cast(dict[str, object], extra.get("quota", {}))

        basic_limit = quota.get("basic_usage_limit", 0)
        basic_used = usage["basic_usage_amount"]

        if isinstance(basic_limit, (int, float)) and basic_limit > 0:
            pct_used = (basic_used / basic_limit) * 100
            rows.append(
                UsageRow(
                    identifier=f"Trae ({identity} - basic)",
                    pct_used=pct_used,
                    reset_at=None,
                )
            )

        # Also report bonus quota if present
        bonus_limit = quota.get("bonus_usage_limit", 0)
        bonus_used = usage["bonus_usage_amount"]

        if isinstance(bonus_limit, (int, float)) and bonus_limit > 0:
            pct_used = (bonus_used / bonus_limit) * 100
            rows.append(
                UsageRow(
                    identifier=f"Trae ({identity} - bonus)",
                    pct_used=pct_used,
                    reset_at=None,
                )
            )

        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        if self.should_anchor(rows):
            self.send_ntfy(
                "Trae Window Open",
                "Trae credits available!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str] | None:
        return None
