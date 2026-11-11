import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


APP_ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "ses_e420f1c63ffesu6ymnjfYfrdcG"
MODEL = "qwen3.8-omni-flash"
PROMPT_VERSION = "voc-2026-11-09-v1"
THEMES = ["服务体验", "产品质量", "设施环境", "价格费用", "等待效率", "预订订单", "退款售后", "卫生安全", "员工态度", "其他反馈"]


@dataclass
class Settings:
    root: Path
    api_key: str
    base_url: str
    region: str
    model: str = MODEL
    chunk_seconds: int = 120
    max_bytes: int = 512 * 1024 * 1024
    max_seconds: int = 10800
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

    @property
    def model_config_path(self):
        return self.root / "model-config.json"

    @property
    def db_path(self):
        return self.root / "voc.sqlite3"


def load_settings():
    credentials = {}
    credentials_file = os.environ.get("VOC_CREDENTIALS_FILE")
    path = Path(credentials_file) if credentials_file else None
    if path and path.is_file():
        try:
            credentials = json.loads(path.read_text(encoding="utf-8-sig")).get("dashscope", {})
        except (OSError, ValueError):
            pass
    root = Path(os.environ.get("VOC_DATA_DIR", APP_ROOT / "runtime")).resolve()
    saved = {}
    local_config = root / "model-config.json"
    if local_config.is_file():
        try:
            saved = json.loads(local_config.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, ValueError):
            pass
    return Settings(
        root=root,
        api_key=saved.get("api_key", os.environ.get("QWEN_API_KEY") or credentials.get("api_key") or os.environ.get("DASHSCOPE_API_KEY", "")),
        base_url=saved.get("base_url", os.environ.get("QWEN_BASE_URL") or credentials.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"),
        region=saved.get("region", os.environ.get("QWEN_REGION") or credentials.get("region", "cn-beijing")),
        model=saved.get("model", os.environ.get("QWEN_MODEL", MODEL)),
        ffmpeg=shutil.which("ffmpeg") or "ffmpeg",
        ffprobe=shutil.which("ffprobe") or "ffprobe",
    )


def validate_base_url(value):
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise ValueError("请填写有效的模型API地址") from exc
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API地址必须是无用户名、密码、查询参数或片段的HTTP(S)基础地址")
    if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("非本机模型服务必须使用HTTPS，避免明文传输密钥")
    if value.endswith("/chat/completions"):
        raise ValueError("请填写基础地址（通常以/v1结尾），不要包含/chat/completions")
    return value


def save_model_config(settings, candidate):
    settings.root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".model-config-", dir=settings.root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump({key: getattr(candidate, key) for key in ("base_url", "model", "api_key", "region")}, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, settings.model_config_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    for key in ("base_url", "model", "api_key", "region"):
        setattr(settings, key, getattr(candidate, key))
