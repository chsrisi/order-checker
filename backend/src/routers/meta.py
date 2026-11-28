"""``GET /meta`` (IMPLEMENTATION_PLAN T4.7, delta A-5/A-5a): public, non-sensitive build facts
so frontends can adapt (KNOWN_LIMITATIONS #3). No secrets, hostnames or user data."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import config

router = APIRouter(tags=["meta"])


class ContractRange(BaseModel):
    min: int
    max: int


class MetaResponse(BaseModel):
    server_version: str = Field(
        description="Backend release version (SemVer). Not the contract: see client_contract."
    )
    api_version: str = Field(
        deprecated=True,
        description=(
            "Deprecated: the same value as server_version, kept for compatibility. "
            "Removed when v1 is sunset."
        ),
    )
    client_contract: ContractRange
    app_env: str
    stock_location_mode: str
    features: dict[str, bool]


@router.get(
    "/meta",
    response_model=MetaResponse,
    summary="Server metadata",
    description=(
        "Public. Server version, supported operator-client contract range, environment, stock "
        "location mode and feature flags. Contains no secrets or hostnames."
    ),
)
def get_meta() -> MetaResponse:
    return MetaResponse(
        server_version=config.SERVER_VERSION,
        api_version=config.SERVER_VERSION,
        client_contract=ContractRange(
            min=config.CLIENT_CONTRACT_MIN, max=config.CLIENT_CONTRACT_MAX
        ),
        app_env=config.APP_ENV,
        stock_location_mode=config.stock_location_mode(),
        features={
            "self_registration": config.ALLOW_REGISTRATION,
            "pick_stock_restore": True,
            "utc_datetimes": True,
            "strict_stock": config.strict_stock(),
        },
    )
