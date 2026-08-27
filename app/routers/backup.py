import gzip
import subprocess
from datetime import date
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.auth import require_admin
from app.config import settings

router = APIRouter(prefix="/backup", tags=["backup"])


@router.get("/dump")
def download_dump(current_user=Depends(require_admin)):
    u = urlparse(settings.database_url)
    env = {
        "PGPASSWORD": u.password or "",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    result = subprocess.run(
        [
            "pg_dump",
            "-h", u.hostname,
            "-p", str(u.port or 5432),
            "-U", u.username,
            u.path.lstrip("/"),
        ],
        capture_output=True,
        env=env,
    )
    if result.returncode != 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"pg_dump error: {result.stderr.decode()}")

    compressed = gzip.compress(result.stdout)
    filename = f"ilsa-crm-backup-{date.today()}.sql.gz"
    return Response(
        content=compressed,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
