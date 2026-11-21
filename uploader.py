"""
uploader.py - High-Performance Telegram Video Uploader.

Part of the "ytdl-telegram" project.
Redirects to uploader_v4.py.
"""
from uploader_v4 import (
    TelegramUploader,
    UploadResult,
    UPLOAD_MODE,
    CRYPTG_STATUS,
    CRYPTG_AVAILABLE,
    check_required_uploader_tools,
    get_video_metadata,
    generate_thumbnail,
    split_video_into_parts,
)

__all__ = [
    "TelegramUploader",
    "UploadResult",
    "UPLOAD_MODE",
    "CRYPTG_STATUS",
    "CRYPTG_AVAILABLE",
    "check_required_uploader_tools",
    "get_video_metadata",
    "generate_thumbnail",
    "split_video_into_parts",
]
