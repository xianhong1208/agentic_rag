
"""Health check and monitoring endpoints

Provides endpoints for system health monitoring, cache statistics,
and database connectivity checks.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from typing import Dict, Any
from sqlalchemy import text
from db.db import get_engine
from sqlalchemy.orm import Session
from src.api.router.response import (
    CacheClearResponse,
    ErrorDetailResponse,
    HealthStatusResponse,
)
from src.auth.dependencies import authenticate_request
from src.infrastructure.cache.cache_service import CacheService
from src.log import get_api_logger

logger = get_api_logger()
router = APIRouter(tags=["Health"], prefix="/health")


# Response = {status, timestamp};給 K8s / Docker liveness probe 用,無依賴
@router.get(
    "",
    response_model=HealthStatusResponse,
)
async def health_check():
    """Basic health check.

    Returns:
        Status + ISO timestamp 表示 server 還在跑。
    """
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


# Response = nested dict {status, components{db,pgvector,cache,pool}, overall_healthy}
@router.get("/detailed")
async def detailed_health_check():
    """Comprehensive health check with component status

    Checks:
    - Database connectivity
    - PGVector extension availability
    - Cache service status
    - Overall system health

    Returns:
        Detailed health information for all system components

    Use this for readiness probes or detailed monitoring.
    """
    checks: Dict[str, Any] = {}
    overall_healthy = True

    # 1. Check Database Connectivity
    try:
        engine = get_engine()
        with Session(bind=engine) as session:
            # Try a simple query
            session.execute(text("SELECT 1"))
            checks["database"] = {
                "status": "healthy",
                "message": "Database connection successful"
            }
            logger.debug("Database health check: OK")
    except Exception as e:
        checks["database"] = {
            "status": "unhealthy",
            "error": type(e).__name__
        }
        overall_healthy = False
        logger.error(f"Database health check failed: {e}")

    # 2. Check PGVector Extension
    try:
        engine = get_engine()
        with Session(bind=engine) as session:
            # Check if pgvector extension is installed
            result = session.execute(text(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            ))
            pgvector_installed = result.scalar()

            if pgvector_installed:
                checks["pgvector"] = {
                    "status": "healthy",
                    "message": "PGVector extension is installed"
                }
                logger.debug("PGVector health check: OK")
            else:
                checks["pgvector"] = {
                    "status": "unhealthy",
                    "error": "PGVector extension not found"
                }
                overall_healthy = False
                logger.warning("PGVector extension not installed")
    except Exception as e:
        checks["pgvector"] = {
            "status": "unhealthy",
            "error": type(e).__name__
        }
        overall_healthy = False
        logger.error(f"PGVector health check failed: {e}")

    # 3. Check Cache Service
    try:
        cache = CacheService.get_instance()
        cache_stats = cache.get_stats()

        checks["cache"] = {
            "status": "healthy",
            "stats": cache_stats,
            "message": f"Cache operational with {cache_stats['size']} items"
        }
        logger.debug("Cache health check: OK")
    except Exception as e:
        checks["cache"] = {
            "status": "unhealthy",
            "error": type(e).__name__
        }
        overall_healthy = False
        logger.error(f"Cache health check failed: {e}")

    # 4. Check Database Connection Pool
    try:
        engine = get_engine()
        pool = engine.pool

        checks["connection_pool"] = {
            "status": "healthy",
            "size": pool.size(),
            "checked_in": pool.checked_in_connections(),
            "checked_out": pool.checked_out_connections(),
            "overflow": pool.overflow(),
            "message": "Connection pool operational"
        }
        logger.debug("Connection pool health check: OK")
    except Exception as e:
        checks["connection_pool"] = {
            "status": "degraded",
            "error": type(e).__name__,
            "message": "Unable to retrieve pool stats"
        }
        # Not critical for overall health
        logger.warning(f"Connection pool stats unavailable: {e}")

    # 5. Capability degradation — router/module 啟動載入失敗(M15)
    #    原本這類失敗只記 log、server 照常啟動,/health 卻 healthy、端點靜默 404。
    from src.api.startup_state import get_load_failures
    load_failures = get_load_failures()
    if load_failures:
        checks["capabilities"] = {
            "status": "degraded",
            "failed": load_failures,
            "message": "部分 router/module 啟動載入失敗,對應端點不可用(詳見啟動 log)",
        }
        overall_healthy = False
    else:
        checks["capabilities"] = {"status": "healthy", "message": "All routers/modules loaded"}

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks
    }


# Response = nested cache stats dict {status, stats{size, hit_rate, ...}, message}
@router.get(
    "/cache/stats",
    responses={500: {"model": ErrorDetailResponse}},
)
async def cache_stats():
    """Get cache performance statistics

    Returns cache metrics including:
    - Hit/miss counts and rates
    - Current size and capacity
    - Set/delete operation counts

    Useful for monitoring cache effectiveness.
    """
    try:
        cache = CacheService.get_instance()
        stats = cache.get_stats()

        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cache_stats": stats,
            "recommendations": _get_cache_recommendations(stats)
        }
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": type(e).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


# Response = {status, message, items_removed, timestamp}
# ⚠️ 唯一掛認證的 health 端點:這是寫操作(清全租戶快取,可重複打 = DoS)。
# 其餘 GET(liveness / stats)依內網部署哲學保持開放,監控系統不需配 token。
@router.post(
    "/cache/clear",
    response_model=CacheClearResponse,
    responses={500: {"model": ErrorDetailResponse}},
    dependencies=[Depends(authenticate_request)],
)
async def clear_cache():
    """Clear all cached data

    WARNING: This will force all subsequent requests to hit the database
    until the cache is repopulated. Use sparingly.

    Returns:
        Confirmation message with stats before clearing
    """
    try:
        cache = CacheService.get_instance()
        stats_before = cache.get_stats()

        cache.clear_all()

        logger.info(f"Cache cleared. Items removed: {stats_before['size']}")

        return {
            "status": "success",
            "message": "Cache cleared successfully",
            "items_removed": stats_before['size'],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": type(e).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


# Response = {status, database_stats{table_counts, database_size, active_connections}, timestamp}
@router.get(
    "/database/stats",
    responses={500: {"model": ErrorDetailResponse}},
)
async def database_stats():
    """Get database statistics

    Returns:
    - Table row counts
    - Database size
    - Index usage
    - Connection information

    Useful for monitoring database growth and performance.
    """
    try:
        engine = get_engine()
        stats = {}

        with Session(bind=engine) as session:
            # Get table row counts
            tables = ['Folders', 'Files', 'FileIndices']
            table_counts = {}

            for table in tables:
                result = session.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                table_counts[table] = result.scalar()

            stats['table_counts'] = table_counts

            # Get database size
            result = session.execute(text(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            ))
            stats['database_size'] = result.scalar()

            # Get connection count
            result = session.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            ))
            stats['active_connections'] = result.scalar()

        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database_stats": stats
        }
    except Exception as e:
        logger.error(f"Failed to get database stats: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": type(e).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


def _get_cache_recommendations(stats: Dict[str, Any]) -> list[str]:
    """Generate cache performance recommendations based on stats

    Args:
        stats: Cache statistics dictionary

    Returns:
        List of recommendation strings
    """
    recommendations = []

    # Check hit rate
    hit_rate = stats.get('hit_rate', 0)
    if hit_rate < 50:
        recommendations.append(
            f"Low cache hit rate ({hit_rate}%). Consider increasing cache size or TTL."
        )
    elif hit_rate > 90:
        recommendations.append(
            f"Excellent cache hit rate ({hit_rate}%)! Cache is performing well."
        )

    # Check cache utilization
    size = stats.get('size', 0)
    max_size = stats.get('max_size', 1000)
    utilization = (size / max_size * 100) if max_size > 0 else 0

    if utilization > 90:
        recommendations.append(
            f"Cache is {utilization:.1f}% full. Consider increasing max_size."
        )
    elif utilization < 20:
        recommendations.append(
            f"Cache utilization is low ({utilization:.1f}%). Current max_size may be too large."
        )

    # Check if cache is being used
    total_operations = stats.get('hits', 0) + stats.get('misses', 0)
    if total_operations == 0:
        recommendations.append("Cache has no activity. Ensure caching is enabled in application code.")

    if not recommendations:
        recommendations.append("Cache performance is optimal.")

    return recommendations
