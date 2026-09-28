from pydantic_settings import BaseSettings, SettingsConfigDict

class AppConfig(BaseSettings):
    """Settings for the whole service, the same for every source."""
    
    model_config = SettingsConfigDict(env_file=".env", env_prefix="EMOTEIQ_", extra="ignore")
    
    # infrastructure
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "EmoteIQ"
    kafka_bootstrap: str = "localhost:9092"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    
    # batching for agents 
    default_batch_size: int = 50
    min_batch_size: int = 1
    max_batch_size: int = 200
    fetch_ahead_pages: int = 2 # fetch the next page while fewer than 2 pages of reviews are unread
    get_batch_wait_s: float = 20.0
    
    # retention (days after a job finishes)
    jobs_ttl_days: int = 90
    batches_ttl_days: int = 7
    raw_pages_ttl_days: int = 7
     
class SourceConfig(BaseSettings):
    """Fields every source has. Each source subclasses this with its own prefix."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    page_size: int
    request_timeout_s: float = 15.0
    max_retries: int = 3    

    