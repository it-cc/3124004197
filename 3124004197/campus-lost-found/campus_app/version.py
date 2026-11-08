from pathlib import Path
import hashlib


def backend_version():
    package=Path(__file__).resolve().parent
    digest=hashlib.sha256()
    for path in sorted(package.glob('*.py')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]
