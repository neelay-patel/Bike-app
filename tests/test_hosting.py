"""The hosted server's image (Dockerfile) has every file the server reads from outside its own code: on 23 Nov 2026
the card's design tokens were left out and every card was a server error."""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_files_the_server_reads_are_in_the_image():
    docker = open(os.path.join(ROOT, "Dockerfile")).read()
    copied = re.findall(r"^COPY\s+(\S+)", docker, re.M)
    needed = set()
    for top in ("rideengine", "backend"):
        for dirpath, _, files in os.walk(os.path.join(ROOT, top)):
            for name in files:
                if not name.endswith(".py"):
                    continue
                src = open(os.path.join(dirpath, name)).read()
                # Paths built up out of the package: os.path.join(..., "..", "..", "design", "tokens.json")
                for m in re.finditer(r'"\.\.",\s*"\.\.",\s*((?:"[^"]+",?\s*)+)\)', src):
                    parts = re.findall(r'"([^"]+)"', m.group(1))
                    if parts and parts[0] != "data":          # data/ is the disk, not the image
                        needed.add("/".join(parts))
    assert needed, "expected to find at least the design tokens"
    for path in needed:
        assert any(path == c or path.startswith(c.rstrip("/") + "/") for c in copied), f"{path} isn't in the image"
