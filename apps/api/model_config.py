"""Shared naming contract for product/baseline model settings; reads current process only."""
from dataclasses import dataclass,field
from urllib.parse import urlsplit
import os

LOCAL_MODEL_HOSTS = {'localhost', '127.0.0.1', '::1'}

def validate_endpoint(url: str) -> str:
    url = url.strip()
    if not url:
        return ''
    parsed = urlsplit(url)
    if parsed.username or parsed.password or not parsed.hostname:
        raise ValueError('模型接口地址格式无效，禁止在 URL 中包含凭证')
    if parsed.scheme == 'https':
        return url
    if parsed.scheme == 'http' and parsed.hostname.lower() in LOCAL_MODEL_HOSTS:
        return url
    raise ValueError('模型接口须使用 HTTPS（仅本机 localhost/127.0.0.1 测试允许 HTTP）')

@dataclass(frozen=True)
class ModelSettings:
    endpoint:str=''
    key:str=field(default='',repr=False)
    model:str=''
    enabled:bool=False
    max_seconds:float|None=None
    max_tokens:int|None=None
    # Thinking level sent as reasoning_effort to the primary service only; empty leaves the provider default.
    reasoning_effort:str=''
    @classmethod
    def from_env(cls):
        seconds=os.getenv('RFQ_MODEL_MAX_SECONDS');tokens=os.getenv('RFQ_MODEL_MAX_TOKENS')
        seconds=float(seconds) if seconds else None;tokens=int(tokens) if tokens else None
        if seconds is not None and not 1<=seconds<=90:raise ValueError('模型单次超时配置须在1至90秒内')
        if tokens is not None and not 1000<=tokens<=20000:raise ValueError('模型单次token配置须在1000至20000内')
        effort=os.getenv('RFQ_MODEL_REASONING_EFFORT','').strip().lower()
        if effort not in ('','low','medium','high'):raise ValueError('思考强度须为 low、medium 或 high')
        endpoint=validate_endpoint(os.getenv('RFQ_MODEL_URL',''))
        return cls(endpoint,os.getenv('RFQ_MODEL_KEY',''),os.getenv('RFQ_MODEL_NAME',''),os.getenv('RFQ_ENABLE_MODEL_REQUESTS')=='1',seconds,tokens,effort)
    @property
    def thinking(self):return {'reasoning_effort':self.reasoning_effort} if self.reasoning_effort else {}
    @property
    def no_thinking(self):
        # A thinking model (one with a level configured) otherwise thinks at length by default: switch it off for structured jobs.
        return {'thinking':{'type':'disabled'}} if self.reasoning_effort else {}
    @property
    def configured(self):return bool(self.endpoint and self.key and self.model)
    @classmethod
    def routes(cls):
        """The primary service, then the fallback if one is configured (RFQ_MODEL_FALLBACK_URL / _KEY / _NAME)."""
        primary=cls.from_env()
        fallback_url=validate_endpoint(os.getenv('RFQ_MODEL_FALLBACK_URL',''))
        fallback=cls(fallback_url,os.getenv('RFQ_MODEL_FALLBACK_KEY',''),os.getenv('RFQ_MODEL_FALLBACK_NAME',''),primary.enabled,primary.max_seconds,primary.max_tokens)
        if any((fallback.endpoint,fallback.key,fallback.model)) and not fallback.configured:
            raise ValueError('备用模型配置不完整，须同时提供 URL、KEY 和 NAME')
        return [s for s in (primary,fallback) if s.configured]
