"""OTA update endpoints for the v2 operator app (IMPLEMENTATION_PLAN T6.5, V2_DELTA Q5, D1).

Public on purpose: the updater must keep working without a login (a release with broken
login must still be replaceable over the air, V2_SPEC §11.2), and the APK holds no secret.
A device credential is added in step 8 (T8.2). Not gated by ``X-Client-Version``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..services import client_releases

router = APIRouter(prefix="/v2/client", tags=["v2 · client release"])

APK_MEDIA_TYPE = "application/vnd.android.package-archive"


class ClientReleaseResponse(BaseModel):
    version_code: int = Field(description="Android versionCode of the newest published APK.")
    version_name: str
    apk_url: str = Field(
        description="Path of the APK on this server; resolve it against the address used."
    )
    sha256: str = Field(description="Hex SHA-256 of the APK; verify before installing.")
    size_bytes: Optional[int] = None
    min_supported_version_code: Optional[int] = Field(
        None, description="Older apps get 426 on every gated /v2 call and must update."
    )
    notes: Optional[str] = None
    published_at: Optional[str] = None


@router.get(
    "/latest",
    response_model=ClientReleaseResponse,
    summary="Newest operator-app release",
    description=(
        "Public. Metadata of the newest published APK, written by "
        "`scripts.publish_client_release`. 404 while nothing is published."
    ),
    responses={404: {"description": "No release published"}},
)
def latest_release() -> ClientReleaseResponse:
    release = client_releases.latest()
    if not release:
        raise HTTPException(status_code=404, detail="No client release published")
    return ClientReleaseResponse(
        version_code=release["version_code"],
        version_name=str(release.get("version_name", "")),
        apk_url=f"/v2/client/apk/{release['version_code']}",
        sha256=str(release.get("sha256", "")),
        size_bytes=release.get("size_bytes"),
        min_supported_version_code=release.get("min_supported_version_code"),
        notes=release.get("notes"),
        published_at=release.get("published_at"),
    )


@router.get(
    "/apk/{version_code}",
    summary="Download an operator-app APK",
    description="Public. The published APK with this versionCode.",
    response_class=FileResponse,
    responses={
        200: {"content": {APK_MEDIA_TYPE: {}}, "description": "The APK file"},
        404: {"description": "No APK with this versionCode"},
    },
)
def download_apk(version_code: int = Path(..., ge=1)):
    # An int path parameter cannot traverse directories.
    path = client_releases.releases_dir() / client_releases.apk_name(version_code)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="APK not found")
    return FileResponse(path, media_type=APK_MEDIA_TYPE, filename=path.name)
