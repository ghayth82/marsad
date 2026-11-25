"""يرفع نماذج Tesseract المنسوخة إلى حساب غيث على Hugging Face (يستدعيه mirror-deps.yml).

المدخلات: مجلد الملفات (deps) في الوسيط الأول، والمفتاح في HF_TOKEN، ورقم إيداع المصدر في TSHA.
"""

import os
import sys
from pathlib import Path

from huggingface_hub import HfApi

REPO = "GhaythMahadin/tesseract-tessdata-fast"
FILES = {"ara.traineddata": "ara.traineddata", "eng.traineddata": "eng.traineddata", "osd.traineddata": "osd.traineddata",
         "tessdata-LICENSE.txt": "LICENSE", "deps.lock.json": "deps.lock.json", "README.md": "README.md"}


def main(folder: str) -> None:
    src = Path(folder)
    api = HfApi(token=os.environ["HF_TOKEN"])
    api.create_repo(REPO, exist_ok=True, private=False)
    msg = f"tessdata_fast {os.environ.get('TSHA', '')[:12]}"
    for local, remote in FILES.items():
        api.upload_file(path_or_fileobj=str(src / local), path_in_repo=remote, repo_id=REPO, commit_message=msg)
    print(f"https://huggingface.co/{REPO}")


if __name__ == "__main__":
    main(sys.argv[1])
