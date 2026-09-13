import gzip
import subprocess
from datetime import date
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth import require_admin
from app.config import settings

router = APIRouter(prefix="/backup", tags=["backup"])


def _run_pg_dump() -> bytes:
    u = urlparse(settings.database_url)
    env = {
        "PGPASSWORD": u.password or "",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    result = subprocess.run(
        ["pg_dump", "-h", u.hostname, "-p", str(u.port or 5432), "-U", u.username, u.path.lstrip("/")],
        capture_output=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump error: {result.stderr.decode()}")
    return gzip.compress(result.stdout)


def send_backup_email(override_to: str | None = None):
    import resend
    recipient = override_to or settings.backup_email
    if not recipient or not settings.resend_api_key:
        return

    compressed = _run_pg_dump()
    filename = f"ilsa-crm-backup-{date.today()}.sql.gz"
    size_kb = len(compressed) // 1024

    resend.api_key = settings.resend_api_key
    resend.Emails.send({
        "from": settings.resend_from,
        "to": [recipient],
        "subject": "Backup CRM automatico",
        "text": f"Backup automatico del database ILSA CRM del {date.today().strftime('%d/%m/%Y')}.\n\nFile: {filename}\nDimensione: {size_kb} KB\n\nILSA CRM",
        "attachments": [{"filename": filename, "content": list(compressed)}],
    })


@router.get("/dump")
def download_dump(current_user=Depends(require_admin)):
    try:
        compressed = _run_pg_dump()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    filename = f"ilsa-crm-backup-{date.today()}.sql.gz"
    return Response(
        content=compressed,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/send")
def send_dump_email(current_user=Depends(require_admin), to: str | None = None):
    try:
        send_backup_email(override_to=to)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "to": to or settings.backup_email}
