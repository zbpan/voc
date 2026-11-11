from dataclasses import replace

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .config import save_model_config, validate_base_url
from .provider import ProviderError, QwenClient


class ModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    api_key: SecretStr | None = Field(default=None)
    clear_api_key: bool = False
    region: str = Field(default="custom", min_length=1, max_length=80)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        return validate_base_url(value)

    @field_validator("model", "region")
    @classmethod
    def safe_text(cls, value):
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("名称不能为空或包含控制字符")
        return value.strip()

    @field_validator("api_key")
    @classmethod
    def safe_key(cls, value):
        if value is not None:
            raw = value.get_secret_value()
            if len(raw) > 2048 or any(character.isspace() or ord(character) < 32 for character in raw):
                raise ValueError("密钥不能超过2048字符或包含空白及控制字符")
        return value


def public_config(settings):
    return {"base_url": settings.base_url, "model": settings.model, "region": settings.region,
            "configured": bool(settings.api_key), "saved_locally": settings.model_config_path.is_file(),
            "protocol": "openai-chat-completions", "secret_storage": "local-file"}


def local_request(request):
    hosts = {"127.0.0.1", "localhost", "::1"}
    if request.url.hostname not in hosts or not request.client or request.client.host not in hosts:
        raise HTTPException(403, "模型配置仅允许通过本机回环地址访问")
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "模型配置不接受跨源请求，请使用后端提供的工作台页面")
    if request.method != "GET" and (request.headers.get("x-voc-settings") != "1" or not request.headers.get("content-type", "").startswith("application/json")):
        raise HTTPException(403, "模型配置请求缺少本机页面校验标记")


def candidate_config(settings, body):
    supplied = body.api_key.get_secret_value() if body.api_key else ""
    if supplied and body.clear_api_key:
        raise HTTPException(422, "不能同时填写和清除密钥")
    endpoint_changed = body.base_url != settings.base_url
    if endpoint_changed and settings.api_key and not supplied and not body.clear_api_key:
        raise HTTPException(422, "更换API地址时必须重新填写密钥或明确清除，避免把现有密钥发送给另一服务")
    key = "" if body.clear_api_key else supplied or settings.api_key
    return replace(settings, base_url=body.base_url, model=body.model, region=body.region, api_key=key)


def model_router(settings, worker):
    router = APIRouter(prefix="/api/settings/model", dependencies=[])

    @router.get("")
    def read_config(request: Request):
        local_request(request)
        return public_config(settings)

    @router.put("")
    def update_config(request: Request, body: ModelInput):
        local_request(request)
        if not worker.configuration_lock.acquire(blocking=False):
            raise HTTPException(409, "模型正在处理任务，请完成后再保存配置")
        try:
            candidate = candidate_config(settings, body)
            try:
                save_model_config(settings, candidate)
            except OSError as exc:
                raise HTTPException(500, "无法写入本机模型配置，请检查数据目录权限") from exc
            worker.wake.set()
            return public_config(settings)
        finally:
            worker.configuration_lock.release()

    @router.post("/test")
    def test_config(request: Request, body: ModelInput):
        local_request(request)
        if not worker.configuration_lock.acquire(blocking=False):
            raise HTTPException(409, "模型正在处理任务，请完成后再测试配置")
        try:
            candidate = candidate_config(settings, body)
        finally:
            worker.configuration_lock.release()
        try:
            _, usage = QwenClient(candidate).complete("Reply with OK only.", max_tokens=32, timeout_seconds=20, attempts=1)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, "模型返回了不兼容的响应，请检查流式Chat Completions协议") from exc
        return {"ok": True, "response_model": candidate.model, "scope": "text-only"}

    return router
