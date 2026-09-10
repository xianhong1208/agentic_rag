
"""配置管理模組

負責讀取和解析 YAML 配置文件，提供配置驅動的應用程序啟動功能。
使用 Pydantic 模型提供類型安全的配置訪問。
"""

import os
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, List
import yaml
from loguru import logger  # M4: 錯誤走 log sink,不再只 print_exc 到 stderr

from .model import (
    ServerConfig,
    DatabaseConfig,
    AuthConfig,
    LoggingConfig,
    AppConfig,
    ModuleConfig,
    ModulesConfig,
    ConfigModel,
)

# 定義允許的配置檔目錄（白名單）
ALLOWED_CONFIG_DIRS: List[str] = [
    "config",
    ".",
]


class Config:
    _config: Dict[str, Any] = {}
    _config_model: Optional[ConfigModel] = None
    _module_configs: Dict[str, ModuleConfig] = {}  # 安全的模組配置儲存（使用字典避免 setattr 注入）
    _config_path: Optional[str] = None  # 原始 yaml 路徑(runtime settings reset 讀原值用)
    
    @classmethod
    def _validate_config_path(cls, config_path: str) -> Path:
        """驗證配置檔路徑，防止路徑穿越攻擊
        
        Args:
            config_path: 使用者指定的配置檔路徑
            
        Returns:
            驗證後的安全 Path 物件
            
        Raises:
            ValueError: 如果路徑不安全或不在允許的目錄中
        """
        # 取得基礎目錄（當前工作目錄）
        base_dir = os.path.realpath(os.getcwd())
        
        # 將配置檔路徑轉為絕對路徑並正規化
        if not os.path.isabs(config_path):
            full_path = os.path.realpath(os.path.join(base_dir, config_path))
        else:
            full_path = os.path.realpath(config_path)
        
        # 檢查正規化後的路徑是否在基礎目錄內
        if not full_path.startswith(base_dir + os.sep) and full_path != base_dir:
            raise ValueError(
                f"Security Error: config_path '{config_path}' resolves to '{full_path}' "
                f"which is outside the allowed base directory '{base_dir}'"
            )
        
        # 取得相對於基礎目錄的路徑
        rel_path = os.path.relpath(full_path, base_dir)
        
        # 檢查是否在允許的目錄中
        path_parts = Path(rel_path).parts
        if path_parts:
            first_dir = path_parts[0]
            # 允許在根目錄的配置檔或在白名單目錄中的配置檔
            is_allowed = (
                first_dir in ALLOWED_CONFIG_DIRS or
                len(path_parts) == 1 or  # 根目錄下的檔案
                "." in ALLOWED_CONFIG_DIRS  # 如果允許當前目錄，則允許所有子路徑
            )
            if not is_allowed:
                raise ValueError(
                    f"Security Error: config file must be in allowed directories: {ALLOWED_CONFIG_DIRS}"
                )
        
        # 驗證檔案副檔名（只允許 .yaml 或 .yml）
        config_file = Path(full_path)
        if config_file.suffix.lower() not in ['.yaml', '.yml']:
            raise ValueError(
                f"Security Error: config file must have .yaml or .yml extension, got '{config_file.suffix}'"
            )
        
        return config_file
    
    @classmethod
    def set_config(cls, config_path: str):
        """載入並設定全域 config。

        三步驟:讀 YAML → Pydantic 解析驗證 → 把已啟用模組詳細配置塞進安全字典。

        Args:
            config_path: config.yaml 的絕對路徑。
        """
        cls._load_config(config_path)
        cls._config_path = config_path
        try:
            config_data = dict(cls._config)
            modules_data = config_data.get('modules', {}) or {}
            enabled_modules = modules_data.get('enabled', [])

            # 簡化 modules 以便 Pydantic 驗證
            config_data['modules'] = {'enabled': enabled_modules}

            cls._config_model = ConfigModel(**config_data)

            # 使用安全的字典儲存模組配置，避免使用 setattr
            # 字典存取不會影響物件內部結構，因此是安全的
            cls._module_configs: Dict[str, ModuleConfig] = {}
            
            for module_name in enabled_modules:
                if module_name in modules_data and module_name != 'enabled':
                    try:
                        module_config = ModuleConfig(**modules_data[module_name])
                        # 使用字典儲存而非 setattr，阻斷不安全的資料流
                        cls._module_configs[module_name] = module_config
                    except Exception:
                        # M4: 別靜默 drop 整個模組(如 rag_indexing 消失 → 該端點
                        # 靜默 404)。走 log sink 讓 ops 一眼看到。
                        logger.exception(
                            f"Module config '{module_name}' failed to parse — "
                            f"this module will be UNAVAILABLE"
                        )
        except Exception:
            # M4: config model 驗證失敗原本只 print_exc 到 stderr 就吞掉、_config_model=None
            # → 服務照常啟動但 API 全 404。改走 log sink 記完整 traceback(含欄位級細節)。
            # 註:目前仍維持「降級啟動」契約(不 raise);若要改 fail-fast 是獨立決策。
            logger.exception("Config model validation failed — starting in DEGRADED mode (no config model)")
            cls._config_model = None
    
    @classmethod
    def _load_config(cls, config_path: str):
        """載入配置文件
        
        Args:
            config_path: 配置檔路徑
            
        Raises:
            ValueError: 如果路徑不安全
            FileNotFoundError: 如果配置文件不存在
        """
        # 驗證路徑安全性，防止路徑穿越攻擊
        config_file_path = cls._validate_config_path(config_path)
        
        try:
            if config_file_path.exists():
                with open(config_file_path, 'r', encoding='utf-8') as file:
                    cls._config = yaml.safe_load(file) or {}
            else:
                raise FileNotFoundError(f"配置文件不存在: {config_path}")
                
        except ValueError:
            # 重新拋出安全驗證錯誤
            raise
        except Exception as e:
            print(f"載入配置文件失敗: {e}")
            traceback.print_exc()
            cls._config = {}
    
    @classmethod
    def get_config(cls) -> Dict[str, Any]:
        """獲取完整配置字典"""
        return cls._config


    @classmethod
    def get_config_model(cls) -> Optional[ConfigModel]:
        """回傳已解析的 Pydantic ConfigModel（若存在）"""
        return cls._config_model

    # --- Pydantic model getters ---
    @classmethod
    def get_server_config(cls) -> Optional[ServerConfig]:
        if cls._config_model is None:
            return None
        return cls._config_model.server

    @classmethod
    def get_database_config(cls) -> Optional[DatabaseConfig]:
        if cls._config_model is None:
            return None
        return cls._config_model.database

    @classmethod
    def get_auth_config(cls) -> Optional[AuthConfig]:
        if cls._config_model is None:
            return None
        return cls._config_model.auth

    @classmethod
    def get_logging_config(cls) -> Optional[LoggingConfig]:
        if cls._config_model is None:
            return None
        return cls._config_model.logging

    @classmethod
    def get_app_config_model(cls) -> Optional[AppConfig]:
        if cls._config_model is None:
            return None
        return cls._config_model.app

    @classmethod
    def get_modules_config(cls) -> Optional[ModulesConfig]:
        if cls._config_model is None:
            return None
        return cls._config_model.modules

    @classmethod
    def get_module_model(cls, module_name: str) -> Optional[ModuleConfig]:
        """取得單一模組的 ModuleConfig(走安全字典存取,避開屬性注入)。

        Args:
            module_name: config.modules.enabled 內的 key。

        Returns:
            ModuleConfig 或 None(模組沒啟用 / config 還沒載入)。
        """
        if cls._config_model is None:
            return None
        # 使用字典安全存取
        return cls._module_configs.get(module_name, None)


def get_config(config_path: str) -> Optional[ConfigModel]:
    """便利函數：載入配置並回傳解析後的 ConfigModel（若解析成功）。"""
    Config.set_config(config_path)
    return Config.get_config_model()