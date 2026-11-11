import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from voc.config import load_settings
from voc.demo_import import download_demo, import_archive


def main():
    parser = argparse.ArgumentParser(description="Download, verify and import both complete synthetic hotel demo workspaces.")
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded official demo archive")
    args = parser.parse_args()
    settings = load_settings()
    if (settings.root / "server.pid").exists():
        parser.error("Stop VOC before importing the full demo.")
    descriptor = json.loads((ROOT / "examples/full-demo.json").read_text(encoding="utf-8"))
    archive = args.archive or download_demo(descriptor, settings.root / "downloads")
    result = import_archive(archive, settings.root, descriptor["sha256"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("DONE. Start VOC, then open http://127.0.0.1:8765/?workspace=full-demo-cxo")


if __name__ == "__main__":
    main()
