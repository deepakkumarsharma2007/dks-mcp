from pydantic_settings import BaseSettings


class ServerSettings(BaseSettings):
    """
    Setting to be used for Authentication
    """
    host: str = "localhost"
    port: int = 8000