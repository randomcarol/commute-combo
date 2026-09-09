import os
from dataclasses import dataclass


@dataclass(slots=True)
class ProviderConfig:
    mode: str
    amap_key: str
    baidu_key: str
    qq_key: str

    @property
    def live_enabled(self):
        return self.mode == "live" and bool(self.available_provider_keys)

    @property
    def available_provider_keys(self):
        providers = {}
        if self.amap_key:
            providers["amap"] = self.amap_key
        if self.baidu_key:
            providers["baidu"] = self.baidu_key
        if self.qq_key:
            providers["qq"] = self.qq_key
        return providers


def load_config():
    return ProviderConfig(
        mode=os.getenv("COMMUTE_PROVIDER_MODE", "mock"),
        amap_key=os.getenv("AMAP_WEB_KEY", ""),
        baidu_key=os.getenv("BAIDU_WEB_KEY", ""),
        qq_key=os.getenv("QQ_MAP_KEY", ""),
    )
