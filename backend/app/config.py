"""Runtime configuration, read from environment variables.

Every value has a safe local default so the platform boots with `uvicorn app.main:app`
and no extra setup. Production deployments override via env (see .env.example).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("MAKAO_DATABASE_URL", "sqlite:///./makao.db"))
    secret_key: str = field(default_factory=lambda: _env("MAKAO_SECRET_KEY", "dev-secret-change-me"))
    # "sandbox" simulates payment providers / WhatsApp sends; "live" calls real APIs.
    payments_mode: str = field(default_factory=lambda: _env("MAKAO_PAYMENTS_MODE", "sandbox"))
    messaging_mode: str = field(default_factory=lambda: _env("MAKAO_MESSAGING_MODE", "sandbox"))
    public_base_url: str = field(default_factory=lambda: _env("MAKAO_PUBLIC_BASE_URL", "http://localhost:5173"))
    cors_origins: str = field(default_factory=lambda: _env("MAKAO_CORS_ORIGINS", "http://localhost:5173"))

    # Commercials
    default_commission_rate: float = field(default_factory=lambda: float(_env("MAKAO_COMMISSION_RATE", "0.18")))
    full_service_ops_rate: float = field(default_factory=lambda: float(_env("MAKAO_FULL_SERVICE_RATE", "0.10")))
    guest_service_fee_rate: float = 0.05
    package_discount_rate: float = 0.05  # applied to itineraries with 3+ legs
    hold_minutes: int = 20  # how long dates are held while payment completes
    min_readiness_to_activate: int = 70
    insights_k_anonymity: int = 3  # suppress aggregate cells with fewer bookings than this

    # M-Pesa Daraja (Safaricom)
    mpesa_base_url: str = field(default_factory=lambda: _env("MPESA_BASE_URL", "https://sandbox.safaricom.co.ke"))
    mpesa_consumer_key: str = field(default_factory=lambda: _env("MPESA_CONSUMER_KEY", ""))
    mpesa_consumer_secret: str = field(default_factory=lambda: _env("MPESA_CONSUMER_SECRET", ""))
    mpesa_shortcode: str = field(default_factory=lambda: _env("MPESA_SHORTCODE", "174379"))
    mpesa_passkey: str = field(default_factory=lambda: _env("MPESA_PASSKEY", ""))
    mpesa_callback_url: str = field(
        default_factory=lambda: _env("MPESA_CALLBACK_URL", "https://example.com/api/payments/mpesa/callback")
    )

    # WhatsApp Cloud API (Meta)
    whatsapp_token: str = field(default_factory=lambda: _env("WHATSAPP_TOKEN", ""))
    whatsapp_phone_id: str = field(default_factory=lambda: _env("WHATSAPP_PHONE_ID", ""))
    whatsapp_verify_token: str = field(default_factory=lambda: _env("WHATSAPP_VERIFY_TOKEN", "makao-verify"))

    @property
    def is_sandbox_payments(self) -> bool:
        return self.payments_mode != "live"


settings = Settings()
