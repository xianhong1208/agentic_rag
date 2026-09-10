
"""文件存儲管理模組

提供文件在文件系統中的存儲、讀取和刪除功能。
文件存儲結構：storage/{folder_name}/{filename}
"""

import os
import re
import shutil
from pathlib import Path
from src.log import get_api_logger
from src.utils.runtime_paths import resolve_base_dir

logger = get_api_logger()


def _resolve_storage_root() -> Path:
    """決定 storage 根目錄。

    順序:
      1. `MIRAG_STORAGE_ROOT` env var — 顯式 override(escape hatch)
      2. `resolve_base_dir()` — 跟 config / assets 同套 onefile-aware 邏輯

    為什麼用 resolve_base_dir 而不是 cwd / __file__:
      - Nuitka --onefile 的 __file__ 落在 /tmp/onefile_*,storage 跟著 ephemeral
      - cwd 在 systemd / 異常啟動可能是 / 或不可預期
      - resolve_base_dir 同時考慮 NUITKA_ONEFILE_PARENT、/proc/self/exe、
        sys.executable、/app convention、dev_root 多層 fallback,任一場景都穩

    全部部署場景跑得起來,**MIRAG_STORAGE_ROOT 完全不必設**。env var 純作
    異常 escape hatch 留著。
    """
    env_root = os.getenv("MIRAG_STORAGE_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return resolve_base_dir(dev_root=Path(__file__).resolve().parents[2])


_PROJECT_ROOT = _resolve_storage_root()
logger.info(f"[INIT] Storage root resolved: {_PROJECT_ROOT}")

# Folder/token name 安全字元 — 字母 / 數字 / dash / underscore / dot / space / 中文
# 防止 ../etc/passwd 之類 path traversal 攻擊
_SAFE_NAME_PATTERN = re.compile(r'^[\w\-. 一-鿿]+$')


def _validate_safe_name(name: str, kind: str = "name") -> None:
    """驗證名稱安全(防 path traversal)。

    規則:非空 + 只含 alphanumeric / _ / - / . / space / CJK + 不開頭 ``.`` + 不含 ``..``。

    Args:
        name: 要驗的 token / folder / file 名稱。
        kind: log 用的名稱類別("token" / "folder" / "file")。

    Raises:
        ValueError: 違規。
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"{kind} cannot be empty")
    if '..' in name or name.startswith('.') or '/' in name or '\\' in name:
        raise ValueError(f"{kind} contains illegal path characters: {name!r}")
    if not _SAFE_NAME_PATTERN.match(name):
        raise ValueError(
            f"{kind} contains illegal characters (allowed: letters, digits, _-. and CJK): {name!r}"
        )


class FileStorage:
    """文件存儲管理類"""

    # 存儲根目錄,固定 project root 下的 storage/
    # 不再 Path.cwd() — 啟動 cwd 變動會讓 storage 跑掉
    STORAGE_ROOT = _PROJECT_ROOT / "storage"
    STORAGE_FILE_ROOT = _PROJECT_ROOT
    
    @classmethod
    def _ensure_storage_root(cls):
        """確保存儲根目錄存在"""
        cls.STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

    @classmethod
    def resolve_path(cls, file_path: str) -> Path:
        """把 DB 存的相對路徑(`storage/...` 開頭)解析成 STORAGE_FILE_ROOT 下的絕對路徑。

        消費端(HierarchicalIndexer 等)直接 ``open()`` 會踩 cwd 雷;
        走此 helper 確保跟 save_file 對得上。已絕對路徑時 Path 行為會丟棄左側,保險。

        Args:
            file_path: DB 內存的相對(或絕對)路徑字串。

        Returns:
            ``Path`` 絕對路徑。
        """
        return cls.STORAGE_FILE_ROOT / file_path
    
    @classmethod
    def _get_folder_storage_path(cls, user_token: str, folder_name: str) -> Path:
        """獲取資料夾的存儲路徑

        Args:
            user_token: 用戶令牌
            folder_name: 資料夾名稱

        Returns:
            資料夾存儲路徑

        Raises:
            ValueError: 如果 user_token 或 folder_name 含 path traversal 字元
        """
        _validate_safe_name(user_token, "user_token")
        _validate_safe_name(folder_name, "folder_name")
        cls._ensure_storage_root()
        folder_path = cls.STORAGE_ROOT / user_token / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path
    
    @classmethod
    def save_file(cls, user_token: str, folder_name: str, file_id: str, file_content: bytes) -> str:
        """保存文件到文件系統

        Args:
            user_token: 用戶令牌
            folder_name: 資料夾名稱
            file_id: 文件ID (UUID)
            file_content: 文件二進制內容

        Returns:
            相對於項目根目錄的文件路徑

        Raises:
            IOError: 文件保存失敗時拋出
        """
        try:
            folder_path = cls._get_folder_storage_path(user_token, folder_name)
            file_path = folder_path / file_id

            # 寫入文件
            with open(file_path, 'wb') as f:
                f.write(file_content)

            # 返回相對路徑
            relative_path = f"storage/{user_token}/{folder_name}/{file_id}"
            logger.info(f"File saved successfully: {relative_path}")
            return relative_path

        except Exception as e:
            logger.error(f"Failed to save file {file_id} to {folder_name}: {str(e)}")
            raise IOError(f"Failed to save file: {str(e)}")
    
    @classmethod
    def read_file(cls, file_path: str) -> bytes:
        """從文件系統讀取文件
        
        Args:
            file_path: 文件路徑（相對於項目根目錄）
            
        Returns:
            文件二進制內容
            
        Raises:
            FileNotFoundError: 文件不存在時拋出
            IOError: 文件讀取失敗時拋出
        """
        try:
            # 構建完整路徑
            full_path = cls.STORAGE_FILE_ROOT / file_path
            
            if not full_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            
            # 讀取文件
            with open(full_path, 'rb') as f:
                content = f.read()
            
            logger.info(f"File read successfully: {file_path}")
            return content
            
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {str(e)}")
            raise IOError(f"Failed to read file: {str(e)}")
    
    @classmethod
    def delete_file(cls, file_path: str) -> bool:
        """從文件系統刪除文件
        
        Args:
            file_path: 文件路徑（相對於項目根目錄）
            
        Returns:
            是否刪除成功
        """
        try:
            # 構建完整路徑
            full_path = cls.STORAGE_FILE_ROOT / file_path
            
            if not full_path.exists():
                logger.warning(f"File not found for deletion: {file_path}")
                return False
            
            # 刪除文件
            full_path.unlink()
            logger.info(f"File deleted successfully: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {str(e)}")
            return False
    
    @classmethod
    def delete_folder(cls, user_token: str, folder_name: str) -> bool:
        """刪除整個資料夾
        
        Args:
            user_token: 用戶令牌
            folder_name: 資料夾名稱
            
        Returns:
            是否刪除成功
        """
        try:
            _validate_safe_name(user_token, "user_token")
            _validate_safe_name(folder_name, "folder_name")
            folder_path = cls.STORAGE_ROOT / user_token / folder_name
            if not folder_path.exists():
                logger.warning(f"Folder not found for deletion: {user_token[:8] if user_token else 'N/A'}.../{folder_name}")
                return False

            shutil.rmtree(folder_path)
            logger.info(f"Folder deleted successfully: {user_token[:8] if user_token else 'N/A'}.../{folder_name}")
            return True

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete folder {user_token[:8] if user_token else 'N/A'}.../{folder_name}: {str(e)}")
            return False

    @classmethod
    def rename_folder(cls, user_token: str, old_folder_name: str, new_folder_name: str) -> bool:
        """重新命名資料夾
        
        Args:
            user_token: 用戶令牌
            old_folder_name: 舊的資料夾名稱
            new_folder_name: 新的資料夾名稱
            
        Returns:
            是否重新命名成功
        """
        try:
            _validate_safe_name(user_token, "user_token")
            _validate_safe_name(old_folder_name, "old_folder_name")
            _validate_safe_name(new_folder_name, "new_folder_name")
            old_path = cls.STORAGE_ROOT / user_token / old_folder_name
            new_path = cls.STORAGE_ROOT / user_token / new_folder_name

            if not old_path.exists():
                logger.warning(f"Folder not found for renaming: {user_token[:8] if user_token else 'N/A'}.../{old_folder_name}")
                return False

            if new_path.exists():
                logger.error(f"Target folder already exists: {user_token[:8] if user_token else 'N/A'}.../{new_folder_name}")
                return False

            old_path.rename(new_path)
            logger.info(f"Folder renamed successfully: {user_token[:8] if user_token else 'N/A'}.../{old_folder_name} -> {new_folder_name}")
            return True

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to rename folder {user_token[:8] if user_token else 'N/A'}.../{old_folder_name} to {new_folder_name}: {str(e)}")
            return False
