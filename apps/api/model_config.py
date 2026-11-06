"""Shared naming contract for product/baseline model settings; reads current process only."""
from dataclasses import dataclass,field
import os
@dataclass(frozen=True)
class ModelSettings:
    endpoint:str=''
    key:str=field(default='',repr=False)
    model:str=''
    enabled:bool=False
    max_seconds:float|None=None
    max_tokens:int|None=None
    @classmethod
    def from_env(cls):
        seconds=os.getenv('RFQ_MODEL_MAX_SECONDS');tokens=os.getenv('RFQ_MODEL_MAX_TOKENS')
        seconds=float(seconds) if seconds else None;tokens=int(tokens) if tokens else None
        if seconds is not None and not 1<=seconds<=90:raise ValueError('模型单次超时配置须在1至90秒内')
        if tokens is not None and not 1000<=tokens<=20000:raise ValueError('模型单次token配置须在1000至20000内')
        return cls(os.getenv('RFQ_MODEL_URL',''),os.getenv('RFQ_MODEL_KEY',''),os.getenv('RFQ_MODEL_NAME',''),os.getenv('RFQ_ENABLE_MODEL_REQUESTS')=='1',seconds,tokens)
    @property
    def configured(self):return bool(self.endpoint and self.key and self.model)
    @classmethod
    def routes(cls):
        """The primary service, then the fallback if one is configured (RFQ_MODEL_FALLBACK_URL / _KEY / _NAME)."""
        primary=cls.from_env()
        fallback=cls(os.getenv('RFQ_MODEL_FALLBACK_URL',''),os.getenv('RFQ_MODEL_FALLBACK_KEY',''),os.getenv('RFQ_MODEL_FALLBACK_NAME',''),primary.enabled,primary.max_seconds,primary.max_tokens)
        return [s for s in (primary,fallback) if s.configured]
