# utils/il_project/s3_il.py
"""
S3 manager scoped to Intralogistics Project Management module.
Pattern: lazy config import inside __init__() — no circular imports.
S3 folder: il-project-file/
"""

import logging
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime

logger = logging.getLogger(__name__)

S3_FOLDER = "il-project-file/"


class ILProjectS3Manager:
    """S3 operations for IL Project files. Config loaded lazily."""

    def __init__(self):
        try:
            from ..config import config as _cfg
            aws = _cfg.aws_config
        except Exception as e:
            raise RuntimeError(f"ILProjectS3Manager: cannot load AWS config — {e}") from e

        missing = [k for k in ("access_key_id", "secret_access_key", "region", "bucket_name")
                   if not aws.get(k)]
        if missing:
            raise ValueError(f"ILProjectS3Manager: missing AWS config keys: {missing}")

        try:
            import boto3
            self._s3 = boto3.client(
                "s3",
                aws_access_key_id=aws["access_key_id"],
                aws_secret_access_key=aws["secret_access_key"],
                region_name=aws["region"],
            )
        except ImportError as e:
            raise RuntimeError("boto3 is not installed. Run: pip install boto3") from e

        self.bucket = aws["bucket_name"]
        logger.info(f"ILProjectS3Manager ready — bucket: {self.bucket}")

    # ── Core ops ────────────────────────────────────────────────────────────────

    def upload_file(self, content: bytes, s3_key: str, content_type: str = "application/octet-stream") -> Tuple[bool, str]:
        try:
            self._s3.put_object(Bucket=self.bucket, Key=s3_key, Body=content, ContentType=content_type)
            logger.info(f"Uploaded: {s3_key}")
            return True, s3_key
        except Exception as e:
            err = f"Upload failed [{s3_key}]: {e}"
            logger.error(err)
            return False, err

    def download_file(self, s3_key: str) -> Optional[bytes]:
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=s3_key)
            return resp["Body"].read()
        except Exception as e:
            logger.error(f"Download failed [{s3_key}]: {e}")
            return None

    def delete_file(self, s3_key: str) -> bool:
        if not s3_key.startswith(S3_FOLDER):
            logger.warning(f"delete_file: key outside {S3_FOLDER} — refused ({s3_key})")
            return False
        try:
            self._s3.delete_object(Bucket=self.bucket, Key=s3_key)
            return True
        except Exception as e:
            logger.error(f"Delete failed [{s3_key}]: {e}")
            return False

    def get_presigned_url(self, s3_key: str, expiration: int = 3600) -> Optional[str]:
        try:
            return self._s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": s3_key},
                ExpiresIn=expiration,
            )
        except Exception as e:
            logger.error(f"Presigned URL error [{s3_key}]: {e}")
            return None

    def file_exists(self, s3_key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except Exception:
            return False

    # ── IL Project–specific helpers ─────────────────────────────────────────────

    def upload_project_file(self, content: bytes, filename: str, project_id: int) -> Tuple[bool, str]:
        """
        Upload project attachment.
        Key: il-project-file/<project_id>/<timestamp_ms>_<filename>
        """
        ts = int(datetime.now().timestamp() * 1000)
        safe = filename.replace(" ", "_")
        s3_key = f"{S3_FOLDER}{project_id}/{ts}_{safe}"
        return self.upload_file(content, s3_key, self._content_type(filename))

    def batch_upload(self, files: List[Tuple[bytes, str]], project_id: int) -> Dict[str, Any]:
        """Upload multiple files. Returns summary dict."""
        result: Dict[str, Any] = {
            "success": False, "uploaded": [], "failed": [],
            "total": len(files), "success_count": 0, "error_count": 0,
        }
        for content, filename in files:
            ok, out = self.upload_project_file(content, filename, project_id)
            if ok:
                result["uploaded"].append(out)
                result["success_count"] += 1
            else:
                result["failed"].append({"filename": filename, "error": out})
                result["error_count"] += 1
        result["success"] = result["error_count"] == 0
        return result

    def list_project_files(self, project_id: int) -> List[Dict]:
        """List all files for a project."""
        prefix = f"{S3_FOLDER}{project_id}/"
        try:
            resp = self._s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            files = []
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                files.append({
                    "key": key,
                    "name": key.split("/")[-1],
                    "size_mb": round(obj["Size"] / 1024 / 1024, 2),
                    "last_modified": obj["LastModified"],
                })
            return files
        except Exception as e:
            logger.error(f"list_project_files error: {e}")
            return []

    def upload_expense_attachment(self, content: bytes, filename: str, project_id: int, expense_id: int) -> Tuple[bool, str]:
        """
        Upload expense attachment (invoice, receipt, etc.).
        Key: il-project-file/<project_id>/expenses/<expense_id>/<timestamp_ms>_<filename>
        """
        ts = int(datetime.now().timestamp() * 1000)
        safe = filename.replace(" ", "_")
        s3_key = f"{S3_FOLDER}{project_id}/expenses/{expense_id}/{ts}_{safe}"
        return self.upload_file(content, s3_key, self._content_type(filename))

    def upload_labor_attachment(self, content: bytes, filename: str, project_id: int, log_id: int) -> Tuple[bool, str]:
        """
        Upload labor log attachment (timesheet, confirmation email, etc.).
        Key: il-project-file/<project_id>/labor/<log_id>/<timestamp_ms>_<filename>
        """
        ts = int(datetime.now().timestamp() * 1000)
        safe = filename.replace(" ", "_")
        s3_key = f"{S3_FOLDER}{project_id}/labor/{log_id}/{ts}_{safe}"
        return self.upload_file(content, s3_key, self._content_type(filename))

    def delete_expense_attachment(self, s3_key: str) -> bool:
        """Delete an expense attachment. Key must be inside il-project-file/."""
        return self.delete_file(s3_key)

    def delete_labor_attachment(self, s3_key: str) -> bool:
        """Delete a labor log attachment. Key must be inside il-project-file/."""
        return self.delete_file(s3_key)

    @staticmethod
    def _content_type(filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }.get(ext, "application/octet-stream")