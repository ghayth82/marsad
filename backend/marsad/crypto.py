"""تشفير الأسرار المحفوظة في قاعدة البيانات (مفاتيح المحركات).

المفتاح الرئيسي: MARSAD_SECRET_KEY (الخادم: .env، الجهاز: config/secrets.json يمرّره الغلاف).
إن لم يُضبط (التطوير)، يُولَّد مرة واحدة في config/secret.key.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken

from marsad.config import get_settings


def _master() -> bytes:
    key = get_settings().secret_key
    if not key:
        from marsad.core.paths import config_dir

        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / "secret.key"
        if not f.exists():
            f.write_text(secrets.token_hex(32))
            try:
                f.chmod(0o600)
            except OSError:
                pass
        key = f.read_text().strip()
    return base64.urlsafe_b64encode(hashlib.sha256(("marsad:" + key).encode()).digest())


def encrypt(plain: str) -> str:
    return Fernet(_master()).encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return Fernet(_master()).decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("تعذّر فك تشفير المفتاح: تغيّر مفتاح التشفير الرئيسي؟ أدخل مفتاح المحرك من جديد.") from None


def mask(plain: str) -> str:
    return "…" + plain[-4:] if len(plain) > 8 else "مُدخل"
