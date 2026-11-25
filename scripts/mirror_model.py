"""ينسخ نموذجًا محليًا واحدًا من مصدره إلى حساب غيث على Hugging Face، ويتحقق من بصمته (يستدعيه mirror-models.yml).

python scripts/mirror_model.py <id> <مجلد العمل> <ملف الإخراج.json>
- يُنزَّل الملف من المصدر، وتُحسب بصمته SHA-256، وتُقارَن ببصمة المصدر المنشورة (LFS).
- يُنشأ مستودع النسخة (عام) إن لم يوجد، ويُرفع الملف وصفحة تعريف بالمصدر والترخيص والبصمة.
- إن كانت النسخة موجودة ببصمة مطابقة يُتخطّى الرفع.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

CATALOG = Path(__file__).resolve().parents[1] / "backend" / "marsad" / "engines" / "local_models.json"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lfs_sha(api: HfApi, repo: str, file: str) -> str | None:
    try:
        info = api.get_paths_info(repo, [file], expand=True)
        return info[0].lfs.sha256 if info and info[0].lfs else None
    except Exception:  # noqa: BLE001
        return None


def main(mid: str, work: str, out: str) -> None:
    m = next(x for x in json.loads(CATALOG.read_text(encoding="utf-8"))["models"] if x["id"] == mid)
    api = HfApi(token=os.environ["HF_TOKEN"])
    src_sha = lfs_sha(api, m["source"], m["file"])
    have = lfs_sha(api, m["mirror"], m["file"])
    if have and src_sha and have == src_sha:
        print(f"النسخة موجودة ومطابقة: {m['mirror']}")
        size = api.get_paths_info(m["mirror"], [m["file"]])[0].size
        Path(out).write_text(json.dumps({"id": mid, "file": m["file"], "mirror": m["mirror"], "sha256": have, "bytes": size,
                                         "source": m["source"]}), encoding="utf-8")
        return
    local = Path(hf_hub_download(m["source"], m["file"], local_dir=work))
    digest = sha256(local)
    if src_sha and digest != src_sha:
        raise SystemExit(f"بصمة {m['file']} لا تطابق بصمة المصدر: {digest} ≠ {src_sha}")
    api.create_repo(m["mirror"], exist_ok=True, private=False)
    readme = f"""---
license: {m['license'].lower()}
base_model: {m['source']}
tags: [gguf, llama.cpp, marsad]
---
# {m['name']} (GGUF، {m['file'].split('-')[-1].removesuffix('.gguf')})

نسخة احتياطية يستعملها «مرصد التحقق» محركًا محليًا مجانيًا.

- المصدر: https://huggingface.co/{m['source']}
- الترخيص: {m['license']}. {m['license_note']}
- الملف: `{m['file']}` — SHA-256: `{digest}`
"""
    api.upload_file(path_or_fileobj=readme.encode(), path_in_repo="README.md", repo_id=m["mirror"], commit_message="README")
    api.upload_file(path_or_fileobj=str(local), path_in_repo=m["file"], repo_id=m["mirror"], commit_message=f"نسخة من {m['source']}")
    Path(out).write_text(json.dumps({"id": mid, "file": m["file"], "mirror": m["mirror"], "sha256": digest,
                                     "bytes": local.stat().st_size, "source": m["source"]}), encoding="utf-8")
    local.unlink()
    print(f"https://huggingface.co/{m['mirror']}  {digest}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
