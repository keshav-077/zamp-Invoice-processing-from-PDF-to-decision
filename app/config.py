"""
InvoiceFlow AI — Application Configuration

Loads settings from environment variables / .env file.
Contains all configurable thresholds, provider settings, and paths.
"""

from pathlib import Path
import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application-wide configuration loaded from environment variables."""

    # --- LLM Provider API Keys ---
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""

    # --- Provider Configuration ---
    provider_priority: str = "gemini,groq,openrouter"
    gemini_model: str = "gemini-flash-latest"
    groq_model: str = "qwen/qwen3.6-27b"
    openrouter_model: str = "google/gemini-2.5-flash"

    # --- Application Paths ---
    upload_dir: str = "uploads"
    database_path: str = "invoiceflow.db"
    database_url: str = ""  # Neon Postgres URL; empty = local SQLite

    # --- Vercel Blob ---
    blob_read_write_token: str = ""

    # --- Inngest ---
    inngest_event_key: str = ""
    inngest_signing_key: str = ""
    inngest_app_id: str = "invoiceflow-ai"

    # --- Clerk Auth ---
    clerk_jwt_issuer: str = ""

    # --- Upstash Rate Limiting ---
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # --- Resend Inbound Email ---
    resend_webhook_secret: str = ""

    # --- Seed control ---
    auto_seed_on_startup: bool = False

    # --- File Constraints ---
    max_file_size_mb: int = 50
    max_pages: int = 50
    supported_extensions: list[str] = Field(
        default=[".pdf", ".png", ".jpg", ".jpeg"]
    )

    # --- Processing ---
    max_retries: int = 1
    arithmetic_tolerance: float = 0.01
    llm_request_timeout_seconds: int = 45
    upload_api_timeout_seconds: int = 300

    # --- Server ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # --- Confidence Thresholds (per field) ---
    # Critical fields — higher thresholds
    threshold_total_amount: float = 0.97
    threshold_tax_amount: float = 0.95
    threshold_currency: float = 0.85
    threshold_invoice_number: float = 0.90
    threshold_vendor_name: float = 0.85
    threshold_invoice_date: float = 0.90
    # Non-critical fields — lower thresholds
    threshold_po_reference: float = 0.70
    threshold_due_date: float = 0.70
    threshold_line_items: float = 0.75

    # Critical fields that MUST be present and above threshold
    critical_fields: list[str] = Field(
        default=[
            "total_amount",
            "invoice_number",
            "vendor_name",
            "invoice_date",
            "currency",
        ]
    )

    # --- Stage 4: Decision Policy ---
    auto_approve_limit: float = 5000.0
    manager_approve_limit: float = 50000.0
    director_approve_limit: float = 500000.0
    validation_freshness_hours: int = 24
    new_vendor_review_threshold: float = 10000.0

    # --- Stage 3: Tax policy (US demo default) ---
    expected_tax_rate: float = 0.08
    tax_tolerance_pct: float = 0.12
    use_invoice_tax_rate: bool = False

    @property
    def provider_list(self) -> list[str]:
        """Parse comma-separated provider priority string."""
        return [p.strip() for p in self.provider_priority.split(",") if p.strip()]

    @property
    def is_vercel(self) -> bool:
        return bool(os.environ.get("VERCEL"))

    @property
    def vercel_env(self) -> str:
        return os.environ.get("VERCEL_ENV", "")

    @property
    def upload_path(self) -> Path:
        """Absolute path to the upload directory."""
        if self.is_vercel and not self.blob_read_write_token:
            return Path("/tmp/invoiceflow-uploads")
        return Path(__file__).parent.parent / self.upload_dir

    @property
    def db_path(self) -> Path:
        """Absolute path to the SQLite database."""
        if self.is_vercel and not self.database_url:
            return Path("/tmp/invoiceflow.db")
        return Path(__file__).parent.parent / self.database_path

    def get_threshold(self, field_name: str) -> float:
        """Get the confidence threshold for a given field name."""
        attr = f"threshold_{field_name}"
        return getattr(self, attr, 0.70)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Singleton settings instance
settings = Settings()
