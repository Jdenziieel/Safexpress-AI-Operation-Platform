"""Helper: rewrite any UTF-16 LE files (Windows PowerShell artefact of the
agent's Write tool) as UTF-8. Usage: python _fix_utf8.py path1 path2 ..."""
import os, sys

def is_utf16_le(b: bytes) -> bool:
    if not b:
        return False
    sample = b[:512]
    if len(sample) < 4:
        return False
    return sample.count(b"\x00") > len(sample) * 0.3

def convert(path: str) -> bool:
    with open(path, "rb") as f:
        raw = f.read()
    if not is_utf16_le(raw):
        return False
    text = raw.decode("utf-16-le", errors="replace").lstrip("\ufeff")
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))
    return True

if __name__ == "__main__":
    converted = []
    for p in sys.argv[1:]:
        if os.path.isfile(p) and convert(p):
            converted.append(p)
    print(f"Converted {len(converted)} file(s):")
    for p in converted:
        print(" -", p)
