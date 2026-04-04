import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Device, User

router = APIRouter(prefix="/api/connect", tags=["connect"])


@router.get("/{device_id}/rdp")
def download_rdp(
    device_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.ip_address:
        raise HTTPException(status_code=400, detail="Device has no IP address")

    raw_label = device.label or device.mac_address
    # Strip all characters that are not alphanumeric, hyphen, or underscore
    label = re.sub(r"[^\w\-]", "_", raw_label).strip("_") or "device"

    rdp_content = f"""full address:s:{device.ip_address}
username:s:
authentication level:i:2
prompt for credentials:i:1
negotiate security layer:i:1
"""

    filename = f"{label}.rdp"
    return Response(
        content=rdp_content,
        media_type="application/x-rdp",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
