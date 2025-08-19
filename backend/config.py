import os

class Settings:
    CLASH_API_URL: str = "http://127.0.0.1:9090"
    CLASH_API_SECRET: str = os.getenv("CLASH_API_SECRET", "511622")
    CLASH_CORE_NAME: str = "/usr/bin/mihomo"
    API_TEST_URL: str = os.getenv("API_TEST_URL", "http://cp.cloudflare.com/generate_204")
    API_TEST_TIMEOUT: int = int(os.getenv("API_TEST_TIMEOUT", "5000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    PORT: int = int(os.getenv("PORT", "8000"))

settings = Settings()
