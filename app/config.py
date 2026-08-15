from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///:memory:"
    public_base_url: str = "https://rigshare.onrender.com"
    internal_settle_secret: str = "change-me"

    linq_api_key: str = ""
    linq_from_number: str = ""
    linq_webhook_secret: str = ""

    stripe_secret_key: str = ""
    stripe_mode: str = "live"

    lender_phone: str = "+14159909839"
    test_borrower_phone: str = "+17034051525"

    default_deposit_cents: int = 2500
    default_rental_cents: int = 500
    default_platform_fee_cents: int = 200
    demo_deposit_cents: int = 800
    demo_rental_cents: int = 200
    demo_platform_fee_cents: int = 100

    render_workflow_slug: str = ""
    require_clerk_settle: bool = False
    # Encoder models each carry their own key and are absent from GET /v1/models.
    # gliner2-base-v1 does not exist on this account; large-v1 is the real one.
    pioneer_api_key: str = ""
    pioneer_decoder_model_id: str = "claude-haiku-4-5"
    pioneer_ner_base_model: str = "fastino/gliner2-large-v1"
    pioneer_ner_model_id: str = "fastino/gliner2-large-v1"
    pioneer_ner_api_key: str = ""
    pioneer_guard_model_id: str = "fastino/gliguard-LLMGuardrails-300M"
    pioneer_guard_api_key: str = ""
    pioneer_pii_model_id: str = "fastino/gliner2-privacy-filter-PII-multi"
    pioneer_pii_api_key: str = ""
    terac_api_key: str = ""
    terac_project_id: str = ""
    superserve_api_key: str = ""
    band_human_api_key: str = ""
    band_matcher_agent_id: str = ""
    band_matcher_api_key: str = ""
    band_condition_agent_id: str = ""
    band_condition_api_key: str = ""
    band_clerk_agent_id: str = ""
    band_clerk_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
