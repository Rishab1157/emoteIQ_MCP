from pydantic_settings import SettingsConfigDict
from .BaseConfig import SourceConfig


class GooglePlayConfig(SourceConfig):
    
    model_config = SettingsConfigDict(env_prefix="EMOTEIQ_GOOGLE_PLAY_")
    
    base_url: str = "https://play.google.com"
    page_size: int = 150              # Google's maximum per request
    impersonate: str = "chrome120"       # curl_cffi browser profile for AsyncSession