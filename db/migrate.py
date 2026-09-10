#!/usr/bin/env python3

"""
Core Database Migration Utility using Alembic Python API
Pure Python implementation - no CLI dependency

This module provides complete database migration functionality:
- Auto migration (check and apply)
- Apply pending migrations
- Rollback migrations
- Status checking
- Database initialization

Usage:
    python -m db.migrate [command] [options]
    
Commands:
    auto                        Auto-apply migrations (default)
    migrate                     Apply pending migrations
    rollback [revision]         Rollback to previous or specific revision
    status                      Show detailed migration status
    current                     Show current database revision
    init                        Initialize database to current model state
"""
import sys
import re
import sqlalchemy
import traceback
from pathlib import Path
from typing import Tuple, Optional, List

# Alembic Python API imports
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from alembic.config import Config as AlembicConfig
from alembic import command

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.log import get_server_logger
from src.config.config_manager import Config
from src.utils.runtime_paths import resolve_external_dir

logger = get_server_logger()

# 跨實例的 migration 全域鎖 key(pg_advisory_lock)。任意固定 64-bit 值,
# 所有 instance 一致即可;防多 worker / 滾動部署同時 auto_migrate 並發跑
# 同一條 migration(DROP TABLE 類的並發跑會一邊成功一邊炸)。
_PG_MIGRATE_LOCK_KEY = 74_112_358


class MigrationChainError(RuntimeError):
    """migration 檔案解析 / 鏈完整性失敗 — 一律大聲失敗,絕不靜默跳過。

    背景:revision 用 regex 解析(只認 [a-f0-9]),不合規的 id 原本會被
    靜默略過 → 該 migration「寫了等於沒寫」,schema 靜默漂移。多 head /
    多 base / 斷鏈同理:原本只 warning,實際只套其中一條鏈。
    """


def get_external_base_dir() -> Path:
    """Get the base directory for external files (config, versions, data, etc.)

    Uses `config/` as the marker directory — config and versions always live
    as siblings under the same base in every deployment mode (dev / Nuitka
    standalone / Nuitka onefile / Docker). So wherever config is, that's the base.

    Delegates the actual path resolution (including the Nuitka onefile +
    /proc/self/exe handling) to `src.utils.runtime_paths.resolve_external_dir`.

    Returns:
        The base path where external folders live, or `project_root` as a
        last-resort fallback if nothing could be resolved.
    """
    config_dir = resolve_external_dir("config", dev_root=project_root)
    if config_dir is not None:
        return config_dir.parent
    return project_root


def get_migrate_dir() -> Path:
    """Get the migrate directory path (contains alembic logic)"""
    return Path(__file__).parent / "migrate"


def get_versions_dir() -> Path:
    """Get the versions directory path (contains migration files)
    
    External folder - not packaged with the application.
    """
    external_base = get_external_base_dir()
    return external_base / "versions"


def get_config_dir() -> Path:
    """Get the config directory path"""
    external_base = get_external_base_dir()
    return external_base / "config"


class DatabaseMigrator:
    """Database migration manager using Alembic Python API
    
    This class provides a pure Python implementation of all migration operations.
    Uses Alembic Python API directly - works in both development and packaged mode.
    
    Structure:
    - db/migrate/ - Alembic logic (packaged with app)
    - versions/   - Migration files (external, not packaged)
    """
    
    def __init__(self):
        self.project_root = project_root
        self.external_base = get_external_base_dir()
        self.versions_dir = get_versions_dir()

        # Get database URL from config
        self.db_conf = Config.get_database_config()
        self.db_url = getattr(self.db_conf, 'url')
        self._engine = create_engine(self.db_url)

        logger.debug(f"External base directory: {self.external_base}")
        logger.debug(f"Versions directory: {self.versions_dir}")

        # Ensure versions directory exists
        if not self.versions_dir.exists():
            logger.warning(f"Versions directory not found, creating: {self.versions_dir}")
            self.versions_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_current_revision(self) -> Optional[str]:
        """Get current database revision"""
        try:
            with self._engine.connect() as conn:
                context = MigrationContext.configure(conn)
                return context.get_current_revision()
        except Exception as e:
            logger.error(f"Failed to get current revision: {e}")
            return None
    
    @staticmethod
    def _discover_revisions(versions_dir: Path) -> List[Tuple[str, Optional[str], Path]]:
        """解析 versions/*.py 並建立**經完整性校驗**的有序 migration 鏈。

        三重防護(違者 raise MigrationChainError,絕不靜默):
        1. 每個非 `__` 開頭的 .py 都必須解析出 revision(regex 只認 [a-f0-9];
           id 帶底線等字元的檔案原本會被靜默跳過 —— 寫了等於沒寫)
        2. 恰好一個 base(down_revision=None)、恰好一個 head — 多 base /
           分叉(多 head)一律報錯,不得只走其中一條鏈
        3. 鏈必須涵蓋所有檔案 — down 指向不存在 rev 的孤兒即斷鏈

        Returns:
            [(revision, down_revision, file_path), ...] base → head 有序;
            空目錄回空 list。
        """
        version_files = [
            f for f in sorted(versions_dir.glob("*.py"))
            if not f.name.startswith('__')
        ]
        if not version_files:
            return []

        revisions = {}  # revision -> (down_revision, file_path)
        unparseable: List[str] = []
        for vf in version_files:
            content = vf.read_text(encoding='utf-8')
            # Support both formats: revision = '...' and revision: str = '...'
            # (?<!down_):revision 行不匹配時,search 會滑到 down_revision 行
            # 誤把 down 值當 revision — 負向斷言擋掉這個誤匹配
            rev_match = re.search(r"(?<!down_)revision(?:\s*:\s*str)?\s*=\s*['\"]([a-f0-9]+)['\"]", content)
            down_match = re.search(r"down_revision(?:\s*:[^=]+)?\s*=\s*(?:['\"]?([a-f0-9]+)['\"]?|None)", content)
            if not rev_match:
                unparseable.append(vf.name)
                continue
            rev = rev_match.group(1)
            down_rev = down_match.group(1) if down_match and down_match.group(1) else None
            revisions[rev] = (down_rev, vf)
            logger.debug(f"Found migration: {vf.name} -> rev={rev}, down={down_rev}")

        if unparseable:
            raise MigrationChainError(
                f"無法解析 revision 的 migration 檔案:{unparseable} — "
                f"revision id 只能含 [a-f0-9](regex 解析限制),否則會被靜默跳過。"
                f"請改用純 hex 樣式 id(如 20260819cafe01)。"
            )

        all_revs = set(revisions.keys())
        down_revs = set(r[0] for r in revisions.values() if r[0])

        bases = [r for r, (d, _) in revisions.items() if d is None]
        if len(bases) != 1:
            raise MigrationChainError(
                f"migration 鏈必須恰好一個 base(down_revision=None),實得 {len(bases)}:"
                f"{sorted(bases)} — 多 base 表示鏈斷成多段。"
            )
        heads = sorted(all_revs - down_revs)
        if len(heads) != 1:
            raise MigrationChainError(
                f"偵測到多個 head:{heads} — migration 歷史分叉,只會套用其中一條鏈、"
                f"其餘靜默丟失。請把分支 rebase 成線性(改其中一支的 down_revision)。"
            )

        chain: List[Tuple[str, Optional[str], Path]] = []
        current: Optional[str] = bases[0]
        while current:
            down_rev, file_path = revisions[current]
            chain.append((current, down_rev, file_path))
            nxt = [r for r, (d, _) in revisions.items() if d == current]
            current = nxt[0] if nxt else None

        if len(chain) != len(revisions):
            in_chain = {r for r, _, _ in chain}
            orphans = sorted(
                f"{revisions[r][1].name}(down={revisions[r][0]})"
                for r in all_revs - in_chain
            )
            raise MigrationChainError(
                f"斷鏈:{len(revisions) - len(chain)} 個 migration 是 orphan"
                f"(down_revision 指向不存在的 rev):{orphans}"
            )
        return chain

    def _get_head_revision(self) -> Optional[str]:
        """Get head revision from migration files(鏈校驗失敗直接 raise)"""
        chain = self._discover_revisions(self.versions_dir)
        return chain[-1][0] if chain else None
    
    def _get_migration_chain(self) -> List[Tuple[str, Optional[str], Path]]:
        """Get ordered list of migrations from base to head
        
        Returns:
            List of (revision, down_revision, file_path) tuples in order
        """
        # 解析 + 完整性校驗統一走 _discover_revisions;鏈壞掉直接 raise
        # (舊版這裡自帶第二份 regex 且吞例外回空 list — 靜默漂移的另一個來源)
        return self._discover_revisions(self.versions_dir)

    def upgrade(self, revision: str = "head") -> bool:
        """Apply migrations to target revision
        
        Args:
            revision: Target revision (default: "head")
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"🔄 Upgrading database to: {revision}")
            
            current_rev = self._get_current_revision()
            head_rev = self._get_head_revision()
            
            logger.info(f"📍 Current: {current_rev or 'none'}")
            logger.info(f"🎯 Head: {head_rev or 'none'}")
            
            target_rev = head_rev if revision == "head" else revision
            
            if not target_rev:
                logger.info("✅ No migrations to apply")
                return True
            
            if current_rev == target_rev:
                logger.info("✅ Database is already at target revision")
                return True

            # 多實例防護:pg_advisory_lock(session 級,鎖在這條連線上持有)。
            # 多 worker / 滾動部署同時啟動時,只有一個 instance 真正跑 migration,
            # 其餘在此等待;等到後 double-check current(對手可能已升完)。
            with self._engine.connect() as lock_conn:
                lock_conn.execute(
                    text("SELECT pg_advisory_lock(:k)"), {"k": _PG_MIGRATE_LOCK_KEY}
                )
                try:
                    # double-check:等鎖期間別的 instance 可能已把庫升到位
                    current_rev = self._get_current_revision()
                    if current_rev == target_rev:
                        logger.info("✅ Another instance already upgraded to target — skipping")
                        return True

                    # Get migration chain
                    chain = self._get_migration_chain()
                    if not chain:
                        logger.warning("⚠️ No migration files found")
                        return True

                    # Find migrations to apply
                    start_applying = current_rev is None
                    migrations_to_apply = []

                    for rev, down_rev, file_path in chain:
                        if start_applying:
                            migrations_to_apply.append((rev, file_path))
                        elif down_rev == current_rev:
                            start_applying = True
                            migrations_to_apply.append((rev, file_path))

                        if rev == target_rev:
                            break

                    if not migrations_to_apply:
                        logger.info("✅ No migrations to apply")
                        return True

                    logger.info(f"📋 Applying {len(migrations_to_apply)} migration(s)...")

                    for rev, file_path in migrations_to_apply:
                        logger.info(f"  ⏳ Applying: {rev} ({file_path.name})")

                        if not self._execute_upgrade(self._engine, rev, file_path):
                            logger.error(f"  ❌ Failed to apply: {rev}")
                            return False

                        logger.info(f"  ✅ Applied: {rev}")

                    logger.info(f"✅ Successfully upgraded to: {target_rev}")
                    return True
                finally:
                    lock_conn.execute(
                        text("SELECT pg_advisory_unlock(:k)"), {"k": _PG_MIGRATE_LOCK_KEY}
                    )
            
        except Exception as e:
            logger.error(f"❌ Upgrade failed: {e}")
            traceback.print_exc()
            return False
    
    def _execute_upgrade(self, engine: Engine, revision: str, file_path: Path) -> bool:
        """Execute a single migration's upgrade function"""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"migration_{revision}", file_path)
            if not spec or not spec.loader:
                logger.error(f"Cannot load migration module: {file_path}")
                return False
            
            module = importlib.util.module_from_spec(spec)
            
            # Make SQLAlchemy ops available
            from alembic import op
            module.op = op
            module.sa = sqlalchemy
            
            spec.loader.exec_module(module)
            
            # Execute upgrade function within Alembic context
            with engine.begin() as conn:
                # Ensure alembic_version table exists
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS alembic_version (
                        version_num VARCHAR(32) NOT NULL,
                        CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
                    )
                """))
                
                # Configure migration context
                context = MigrationContext.configure(conn)
                
                # Bind op to the connection
                with Operations.context(context):
                    if hasattr(module, 'upgrade'):
                        module.upgrade()
                    else:
                        logger.warning(f"No upgrade function in {file_path}")
                
                # Update alembic_version table
                conn.execute(text("DELETE FROM alembic_version"))
                conn.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                    {"rev": revision}
                )

            return True

        except Exception as e:
            logger.error(f"Failed to execute migration {revision}: {e}")
            traceback.print_exc()
            return False

    def downgrade(self, revision: str = "-1") -> bool:
        """Rollback migrations to target revision
        
        Args:
            revision: Target revision ("-1" for previous, "base" for all)
            
        Returns:
            True if successful
        """
        try:
            logger.warning(f"⚠️ Downgrading database to: {revision}")
            
            current_rev = self._get_current_revision()
            
            if not current_rev:
                logger.info("✅ Database has no revision to downgrade from")
                return True
            
            # Handle relative revision (-1, -2, etc.)
            if revision.startswith("-"):
                steps = int(revision)
                chain = self._get_migration_chain()
                
                current_idx = None
                for i, (rev, _, _) in enumerate(chain):
                    if rev == current_rev:
                        current_idx = i
                        break
                
                if current_idx is None:
                    logger.error(f"Current revision {current_rev} not found in migration chain")
                    return False
                
                target_idx = current_idx + steps
                if target_idx < 0:
                    revision = "base"
                else:
                    revision = chain[target_idx][0]
            
            logger.info(f"📍 Current: {current_rev}")
            logger.info(f"🎯 Target: {revision}")

            # Get migrations to rollback (from current down to target)
            chain = self._get_migration_chain()
            migrations_to_downgrade = []
            found_current = False

            for rev, down_rev, file_path in reversed(chain):
                if rev == current_rev:
                    found_current = True

                if found_current:
                    migrations_to_downgrade.append((rev, down_rev, file_path))
                    # Stop condition: this migration's down_revision is the target
                    # (or target is "base" and down_revision is None)
                    if revision == "base" and down_rev is None:
                        break
                    if down_rev == revision:
                        break

            if not migrations_to_downgrade:
                logger.info("✅ No migrations to downgrade")
                return True

            logger.info(f"📋 Downgrading {len(migrations_to_downgrade)} migration(s)...")

            for rev, down_rev, file_path in migrations_to_downgrade:
                logger.info(f"  ⏳ Downgrading: {rev} ({file_path.name})")

                if not self._execute_downgrade(self._engine, rev, down_rev, file_path):
                    logger.error(f"  ❌ Failed to downgrade: {rev}")
                    return False

                logger.info(f"  ✅ Downgraded: {rev}")

            logger.info(f"✅ Successfully downgraded to: {revision}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Downgrade failed: {e}")
            traceback.print_exc()
            return False
    
    def _execute_downgrade(self, engine: Engine, revision: str, down_revision: Optional[str], file_path: Path) -> bool:
        """Execute a single migration's downgrade function"""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"migration_{revision}", file_path)
            if not spec or not spec.loader:
                logger.error(f"Cannot load migration module: {file_path}")
                return False
            
            module = importlib.util.module_from_spec(spec)
            
            from alembic import op
            module.op = op
            module.sa = sqlalchemy
            
            spec.loader.exec_module(module)
            
            with engine.begin() as conn:
                context = MigrationContext.configure(conn)
                
                with Operations.context(context):
                    if hasattr(module, 'downgrade'):
                        module.downgrade()
                    else:
                        logger.warning(f"No downgrade function in {file_path}")
                
                # Update alembic_version table
                conn.execute(text("DELETE FROM alembic_version"))
                if down_revision:
                    conn.execute(
                        text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                        {"rev": down_revision}
                    )

            return True

        except Exception as e:
            logger.error(f"Failed to execute downgrade {revision}: {e}")
            traceback.print_exc()
            return False

    def stamp(self, revision: str = "head") -> bool:
        """Stamp database with revision without running migrations
        
        Args:
            revision: Revision to stamp (default: "head")
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"🔖 Stamping database at: {revision}")
            
            if revision == "head":
                revision = self._get_head_revision()
                if not revision:
                    logger.warning("No migrations found, nothing to stamp")
                    return True
            
            with self._engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS alembic_version (
                        version_num VARCHAR(32) NOT NULL,
                        PRIMARY KEY (version_num)
                    )
                """))

                conn.execute(text("DELETE FROM alembic_version"))
                conn.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                    {"rev": revision}
                )

            logger.info(f"✅ Successfully stamped at: {revision}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Stamp failed: {e}")
            traceback.print_exc()
            return False

    def check_status(self) -> Tuple[bool, str, str]:
        """Check migration status
        
        Returns:
            Tuple of (is_up_to_date, current_revision, head_revision)
        """
        logger.info("📊 Checking migration status...")
        
        try:
            current_rev = self._get_current_revision() or "none"
            head_rev = self._get_head_revision() or "none"
            
            is_up_to_date = (current_rev == head_rev and current_rev != "none")
            
            print("=" * 50)
            print("DATABASE MIGRATION STATUS")
            print("=" * 50)
            print(f"Current revision: {current_rev}")
            if is_up_to_date:
                print("                 (head)")
            print(f"Latest revision:  {head_rev}")
            print()
            
            if is_up_to_date:
                logger.info("✅ Database is up to date")
            elif current_rev == "none":
                logger.warning("⚠️ Database not initialized")
                print("💡 Run migrations to initialize")
            else:
                logger.warning("⚠️ Database needs migration")
                print("💡 Run migrations to update")
            
            return is_up_to_date, current_rev, head_rev
            
        except Exception as e:
            logger.error(f"❌ Error checking status: {e}")
            return False, "error", "error"

    def auto_migrate(self) -> bool:
        """Automatically apply pending migrations
        
        This is the main entry point for automatic migration handling.
        
        Returns:
            True if successful
        """
        logger.info("🚀 Starting automatic migration process...")
        
        try:
            current_rev = self._get_current_revision()
            head_rev = self._get_head_revision()
            
            logger.info(f"📍 Current revision: {current_rev or 'none'}")
            logger.info(f"🎯 Head revision: {head_rev or 'none'}")
            
            if current_rev == head_rev:
                if current_rev:
                    logger.info("✅ Database is up to date")
                else:
                    logger.warning("⚠️ No migrations found")
                return True
            
            # Apply migrations
            logger.info("⬆️ Applying migrations...")
            if self.upgrade("head"):
                logger.info("✅ Migrations applied successfully")
                return True
            else:
                logger.error("❌ Migration failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Auto migration failed: {e}")
            traceback.print_exc()
            return False

    def show_current_revision(self) -> bool:
        """Show current database revision"""
        logger.info("📍 Current database revision:")
        current = self._get_current_revision()
        print(current if current else "(no revision - database not initialized)")
        return True

    def show_heads(self) -> bool:
        """Show head revisions"""
        logger.info("🎯 Head revisions:")
        head = self._get_head_revision()
        print(head if head else "(no head revision)")
        return True

    # ==================== Alias methods for main.py compatibility ====================
    
    def apply_migrations(self) -> bool:
        """Apply all pending migrations (alias for upgrade('head'))"""
        return self.upgrade("head")
    
    def rollback_migration(self, revision: str = "-1") -> bool:
        """Rollback migration (alias for downgrade)"""
        return self.downgrade(revision)
    
    def initialize_database(self) -> bool:
        """Initialize database - create tables and stamp to head
        
        Used for fresh database setup.
        """
        try:
            logger.info("🔧 Initializing database...")
            
            # Import Base for table creation
            from db.db import Base

            # Create all tables
            logger.info("Creating database tables...")
            Base.metadata.create_all(self._engine)
            
            # Stamp to head revision
            logger.info("Stamping database to head revision...")
            self.stamp("head")
            
            logger.info("✅ Database initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize database: {e}")
            return False
    
    def create_migration(self, message: str) -> bool:
        """產生新的 Alembic migration 檔(autogenerate)。

        僅在 dev 環境可用(需要 Alembic CLI + migrate_dir 存在)。
        Packaged 環境應在打包前就先產 migration。

        Args:
            message: revision 訊息(會變成檔名一部分)。

        Returns:
            True 成功;False = migrate_dir 不存在 / Alembic 失敗。
        """
        try:
            # Use Alembic programmatic API to create a revision (autogenerate)


            logger.info(f"📝 Creating migration: {message}")

            migrate_dir = get_migrate_dir()
            if not migrate_dir.exists():
                logger.error("❌ Migrate directory not found. Cannot create migrations in packaged mode.")
                return False

            # Prepare Alembic Config
            alembic_ini_path = migrate_dir / "alembic.ini"
            if alembic_ini_path.exists():
                alembic_cfg = AlembicConfig(str(alembic_ini_path))
                # alembic.ini already contains script_location (usually %(here)s/alembic)
            else:
                # Create a minimal config object if alembic.ini is missing
                alembic_cfg = AlembicConfig()
                # point script_location to packaged alembic folder
                alembic_cfg.set_main_option("script_location", str(migrate_dir / "alembic"))

            # Ensure Alembic uses the external versions dir and DB URL
            alembic_cfg.set_main_option("version_locations", str(self.versions_dir))
            alembic_cfg.set_main_option("sqlalchemy.url", str(self.db_url))

            # Run alembic revision with autogenerate
            command.revision(alembic_cfg, message=message, autogenerate=True)

            logger.info("✅ Migration created successfully (via Alembic API)")
            return True

        except ImportError:
            logger.error("❌ Alembic package not installed. Install with: pip install alembic")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to create migration: {e}")
            traceback.print_exc()
            return False
    
    def show_migration_history(self) -> bool:
        """Show migration history"""
        try:
            logger.info("📜 Migration history:")
            
            chain = self._get_migration_chain()
            current = self._get_current_revision()
            
            if not chain:
                print("(no migrations found)")
                return True
            
            for rev, down_rev, file_path in chain:
                marker = " <- current" if rev == current else ""
                down_str = down_rev if down_rev else "(base)"
                print(f"  {down_str} -> {rev}  [{file_path.name}]{marker}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to show migration history: {e}")
            return False


def main():
    """Command line interface for database migration"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Database Migration Tool (Pure Python API)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m db.migrate                  # Auto migration (default)
    python -m db.migrate migrate          # Apply pending migrations
    python -m db.migrate status           # Show status
    python -m db.migrate rollback -1      # Rollback one migration
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    subparsers.add_parser("auto", help="Auto-apply migrations")
    subparsers.add_parser("migrate", aliases=["upgrade"], help="Apply pending migrations")
    
    rollback_parser = subparsers.add_parser("rollback", aliases=["downgrade"], help="Rollback migration")
    rollback_parser.add_argument("--revision", "-r", default="-1", help="Revision to rollback to")
    
    subparsers.add_parser("status", help="Show migration status")
    subparsers.add_parser("current", help="Show current revision")
    subparsers.add_parser("heads", help="Show head revisions")
    subparsers.add_parser("init", aliases=["stamp"], help="Initialize database to current state")
    
    args = parser.parse_args()
    
    if not args.command:
        args.command = "auto"
    
    try:
        migrator = DatabaseMigrator()
        success = False
        
        if args.command == "auto":
            success = migrator.auto_migrate()
        elif args.command in ["migrate", "upgrade"]:
            success = migrator.upgrade("head")
        elif args.command in ["rollback", "downgrade"]:
            success = migrator.downgrade(args.revision)
        elif args.command == "status":
            migrator.check_status()
            success = True
        elif args.command == "current":
            success = migrator.show_current_revision()
        elif args.command == "heads":
            success = migrator.show_heads()
        elif args.command in ["init", "stamp"]:
            success = migrator.stamp("head")
        else:
            parser.print_help()
            success = False
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        logger.warning("⚠️ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
