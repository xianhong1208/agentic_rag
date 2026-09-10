
"""執行期設定熱改(feat/runtime-settings)。

契約:
- 白名單外一律拒絕;型別驗證全有全無(一項錯 → 一項都不寫)
- 就地變更:持 section 參照的消費端(context_generator 持 llm_config)
  改完立刻看得到
- warn 級(embedding 系)附影響警告
- optional 段(rag.asr 可為 None)patch 時自動補建
- service:寫入持久化 + rebind;adapter 未建構時只寫 config(首建吃新值)
- rebind:reranker 可 off→on(修 boot-disabled 永遠 None)、QE cache 必清
- VSM.update_embed_dim:同維度 no-op、換維度清 store cache
"""

from unittest.mock import MagicMock, patch

import pytest

from src.config import runtime_overrides as ro
from src.config.model import ConfigModel


def _mk_config() -> ConfigModel:
    return ConfigModel.model_validate({
        "server": {"host": "0.0.0.0", "port": 1, "transport": "http"},
        "database": {"url": "postgresql://x/y", "echo": False, "pool_size": 1,
                     "max_overflow": 1, "pool_timeout": 1, "pool_recycle": 1},
        "auth": {"enabled": False, "token_server_url": "http://x"},
        "logging": {"level": "INFO", "format": "plain", "file": "x.log",
                    "max_size": "1MB", "backup_count": 1},
        "app": {},
        "modules": {"enabled": []},
        "rag": {
            "embedding": {"provider": "vllm", "model": "intfloat/multilingual-e5-large",
                          "dimension": 1024, "base_url": "http://x/v1"},
            "chunking": {"hierarchy_sizes": [1024, 256], "chunk_overlap": 50},
            "retrieval": {"default_top_k": 10, "default_similarity_cutoff": 0.25,
                          "hybrid_search": True,
                          "auto_merging": {"enabled": True, "merge_threshold": 0.5}},
            "vector_store": {"type": "pgvector", "table_prefix": "vector_store"},
            "llm": {"provider": "vllm", "model": "m", "base_url": "http://x/v1"},
            "rerank": {"enabled": False, "model": "r", "base_url": "http://x"},
            "contextual_retrieval": {"enabled": True},
            "asr": {"enabled": True, "provider": "docling-whisper"},
        },
    })


# ---- runtime_overrides:驗證與就地變更 ---------------------------------------

class TestValidateAndApply:
    def test_whitelist_rejects_unknown_path(self):
        cfg = _mk_config()
        with pytest.raises(ValueError, match="不可熱改"):
            ro.validate_and_apply(cfg, {"database.url": "postgresql://evil"})

    def test_type_error_is_all_or_nothing(self):
        cfg = _mk_config()
        before = cfg.rag.retrieval.default_top_k
        with pytest.raises(ValueError, match="驗證失敗"):
            ro.validate_and_apply(cfg, {
                "rag.retrieval.default_top_k": 99,          # 合法
                "rag.rerank.score_threshold": "not-a-num",  # 非法
            })
        assert cfg.rag.retrieval.default_top_k == before  # 合法項也沒寫

    def test_in_place_mutation_visible_via_held_reference(self):
        # 消費端(如 context_generator)持 section 參照 — 就地改要立刻可見
        cfg = _mk_config()
        llm_ref = cfg.rag.llm
        ro.validate_and_apply(cfg, {"rag.llm.model": "new-model"})
        assert llm_ref.model == "new-model"

    def test_warn_level_returns_warning(self):
        cfg = _mk_config()
        applied, warnings = ro.validate_and_apply(
            cfg, {"rag.embedding.model": "BAAI/bge-m3"})
        assert applied == {"rag.embedding.model": "BAAI/bge-m3"}
        assert warnings and "重建索引" in warnings[0]

    def test_live_level_no_warning(self):
        cfg = _mk_config()
        _, warnings = ro.validate_and_apply(cfg, {"rag.rerank.score_threshold": 0.5})
        assert warnings == []

    def test_optional_section_auto_created(self):
        # rag.asr 未設(None)→ patch 自動補建預設段再寫
        cfg = _mk_config()
        cfg.rag.asr = None
        ro.validate_and_apply(cfg, {"rag.asr.provider": "fireredasr"})
        assert cfg.rag.asr is not None
        assert cfg.rag.asr.provider == "fireredasr"

    def test_coercion_follows_pydantic(self):
        # "12"(字串數字)→ pydantic 寬鬆轉型,與 yaml 行為一致
        cfg = _mk_config()
        applied, _ = ro.validate_and_apply(cfg, {"rag.retrieval.default_top_k": "12"})
        assert applied["rag.retrieval.default_top_k"] == 12


class TestEffectiveView:
    def test_secrets_masked(self):
        cfg = _mk_config()
        cfg.rag.rerank.api_key = "super-secret"
        eff = ro.get_effective(cfg)
        assert eff["rag.rerank.api_key"] == "•••"
        assert eff["rag.rerank.score_threshold"] == cfg.rag.rerank.score_threshold

    def test_all_whitelist_paths_resolvable(self):
        # 白名單路徑必須全部指得到 ConfigModel 欄位 — schema 改名時這裡紅
        cfg = _mk_config()
        eff = ro.get_effective(cfg, mask_secrets=False)
        assert set(eff.keys()) == set(ro.EDITABLE.keys())

    def test_rebind_groups_dedup_and_order(self):
        gs = ro.rebind_groups_for([
            "rag.rerank.enabled", "rag.rerank.model", "rag.embedding.model"])
        assert gs == ["rag.embedding", "rag.rerank"]


# ---- service 編排(mock DB)--------------------------------------------------

_SVC = "src.adapter.runtime_settings_service"


class TestService:
    def _with_cfg(self, cfg):
        return patch(f"{_SVC}.Config.get_config_model", return_value=cfg)

    def test_apply_persists_each_key(self):
        cfg = _mk_config()
        from src.adapter import runtime_settings_service as svc
        with self._with_cfg(cfg), \
             patch(f"{_SVC}.RuntimeSettingsDB") as db, \
             patch(f"{_SVC}._rebind") as rb:
            applied, _ = svc.apply_settings(
                {"rag.rerank.score_threshold": 0.4}, updated_by="tok…")
        db.upsert.assert_called_once_with(
            "rag.rerank.score_threshold", 0.4, updated_by="tok…")
        rb.assert_called_once()
        assert cfg.rag.rerank.score_threshold == 0.4

    def test_invalid_patch_never_touches_db(self):
        cfg = _mk_config()
        from src.adapter import runtime_settings_service as svc
        with self._with_cfg(cfg), \
             patch(f"{_SVC}.RuntimeSettingsDB") as db:
            with pytest.raises(ValueError):
                svc.apply_settings({"server.port": 1})
        db.upsert.assert_not_called()

    def test_rebind_noop_when_adapter_not_built(self):
        from src.adapter import runtime_settings_service as svc
        with patch("src.adapter.rag.peek_rag_adapter", return_value=None):
            assert svc._rebind(["rag.rerank.enabled"]) == []

    def test_rebind_dispatches_to_ctx(self):
        from src.adapter import runtime_settings_service as svc
        adapter = MagicMock()
        with patch("src.adapter.rag.peek_rag_adapter", return_value=adapter):
            groups = svc._rebind(["rag.rerank.enabled", "rag.llm.model"])
        adapter._ctx.apply_runtime_changes.assert_called_once_with(groups)
        assert groups == ["rag.llm", "rag.rerank"]

    def test_startup_overlay_skips_invalid_rows(self):
        cfg = _mk_config()
        from src.adapter import runtime_settings_service as svc
        with self._with_cfg(cfg), \
             patch(f"{_SVC}.RuntimeSettingsDB") as db:
            db.load_all.return_value = {
                "rag.retrieval.default_top_k": 15,
                "no.such.path": 1,                      # 白名單改版遺留 → 略過
                "rag.rerank.score_threshold": "junk",   # 壞資料 → 略過
            }
            applied = svc.load_overrides_on_startup()
        assert applied == 1
        assert cfg.rag.retrieval.default_top_k == 15

    def test_reset_without_override_returns_false(self):
        from src.adapter import runtime_settings_service as svc
        with patch(f"{_SVC}.RuntimeSettingsDB") as db:
            db.delete.return_value = False
            assert svc.reset_setting("rag.rerank.score_threshold") is False


# ---- RAGContext rebind ------------------------------------------------------

class TestCtxRebind:
    def _ctx(self):
        from src.adapter.rag_context import RAGContext
        return RAGContext(
            embedding_provider=MagicMock(), embed_dim=1024, model_name="m",
            chunker_tokenizer_name=None, leaf_chunk_size=256,
            parent_target_tokens=1024, chunk_overlap=50,
            vector_store_manager=MagicMock(), indexer=MagicMock(),
            indexing_service=MagicMock(), auto_merging_enabled=True,
            merge_threshold=0.5, expand_neighbors=2, reranker=None,
            query_engines={"1": MagicMock()},
        )

    def test_rerank_off_to_on_and_cache_cleared(self):
        # boot 時 disabled → reranker None;熱改開啟必須能長出來(修舊缺陷)
        ctx = self._ctx()
        cfg = _mk_config()
        cfg.rag.rerank.enabled = True
        fake = MagicMock()
        with patch("src.adapter.rag_context.Config.get_config_model", return_value=cfg), \
             patch("src.domain.rag.reranker.Reranker") as R:
            R.from_config.return_value = fake
            ctx.apply_runtime_changes(["rag.rerank"])
        assert ctx.reranker is fake
        assert ctx.query_engines == {}  # cache 凍著舊 reranker → 必清

    def test_rerank_disable_sets_none(self):
        ctx = self._ctx()
        ctx.reranker = MagicMock()
        cfg = _mk_config()
        cfg.rag.rerank.enabled = False
        with patch("src.adapter.rag_context.Config.get_config_model", return_value=cfg):
            ctx.apply_runtime_changes(["rag.rerank"])
        assert ctx.reranker is None

    def test_retrieval_scalars_rebound(self):
        ctx = self._ctx()
        cfg = _mk_config()
        cfg.rag.retrieval.auto_merging.merge_threshold = 0.7
        cfg.rag.retrieval.expand_context_neighbors = 9
        with patch("src.adapter.rag_context.Config.get_config_model", return_value=cfg):
            ctx.apply_runtime_changes(["rag.retrieval"])
        assert ctx.merge_threshold == 0.7
        assert ctx.expand_neighbors == 9

    def test_llm_group_rebuilds_indexer(self):
        ctx = self._ctx()
        old_indexer = ctx.indexer
        cfg = _mk_config()
        with patch("src.adapter.rag_context.Config.get_config_model", return_value=cfg), \
             patch("src.adapter.rag_context.HierarchicalIndexer") as HI, \
             patch("src.domain.rag.context_generator.ContextGenerator") as CG:
            CG.from_config.return_value = None
            ctx.apply_runtime_changes(["rag.llm"])
        assert ctx.indexer is HI.return_value
        assert ctx.indexer is not old_indexer

    def test_embedding_group_full_rebind(self):
        ctx = self._ctx()
        cfg = _mk_config()
        pi = {"provider": MagicMock(), "embed_dim": 768, "model_name": "new-m",
              "chunker_tokenizer_name": "new-m", "embed_model": MagicMock()}
        with patch("src.adapter.rag_context.Config.get_config_model", return_value=cfg), \
             patch.object(type(ctx), "_load_embedding_provider", return_value=pi), \
             patch("src.adapter.rag_context.HierarchicalIndexer"), \
             patch("src.domain.rag.context_generator.ContextGenerator") as CG:
            CG.from_config.return_value = None
            ctx.apply_runtime_changes(["rag.embedding"])
        assert ctx.embed_dim == 768 and ctx.model_name == "new-m"
        ctx.vector_store_manager.update_embed_dim.assert_called_once_with(768)
        assert ctx.query_engines == {}


# ---- VSM.update_embed_dim ---------------------------------------------------

class TestVsmDimUpdate:
    def _vsm(self):
        from src.domain.rag.vector_store_manager import VectorStoreManager
        with patch("src.domain.rag.vector_store_manager.Config.get_config_model") as g:
            g.return_value.database.url = "postgresql://x/y"
            g.return_value.database.port = 5432
            return VectorStoreManager(embed_dim=1024)

    def test_same_dim_noop_keeps_cache(self):
        vsm = self._vsm()
        vsm._vector_stores["t"] = MagicMock()
        vsm.update_embed_dim(1024)
        assert "t" in vsm._vector_stores

    def test_new_dim_clears_cache(self):
        vsm = self._vsm()
        vsm._vector_stores["t"] = MagicMock()
        vsm.update_embed_dim(768)
        assert vsm._embed_dim == 768
        assert vsm._vector_stores == {}


class TestServiceViewAndReset:
    def _with_cfg(self, cfg):
        return patch(f"{_SVC}.Config.get_config_model", return_value=cfg)

    def test_settings_view_marks_overrides_and_secrets(self):
        cfg = _mk_config()
        from src.adapter import runtime_settings_service as svc
        with self._with_cfg(cfg), patch(f"{_SVC}.RuntimeSettingsDB") as db:
            db.load_all.return_value = {"rag.rerank.score_threshold": 0.4}
            view = svc.get_settings_view()
        by_path = {s["path"]: s for s in view["settings"]}
        assert by_path["rag.rerank.score_threshold"]["overridden"] is True
        assert by_path["rag.rerank.enabled"]["overridden"] is False
        assert by_path["rag.embedding.api_key"]["secret"] is True
        assert by_path["rag.embedding.model"]["level"] == "warn"

    def test_reset_restores_yaml_value_and_rebinds(self, tmp_path):
        cfg = _mk_config()
        cfg.rag.rerank.score_threshold = 0.9  # 現場覆寫中
        yaml_file = tmp_path / "c.yaml"
        yaml_file.write_text(
            "rag:\n  rerank:\n    score_threshold: 0.25\n", encoding="utf-8")
        from src.adapter import runtime_settings_service as svc
        from src.config.config_manager import Config
        with self._with_cfg(cfg), \
             patch(f"{_SVC}.RuntimeSettingsDB") as db, \
             patch(f"{_SVC}._rebind") as rb, \
             patch.object(Config, "_config_path", str(yaml_file)):
            db.delete.return_value = True
            assert svc.reset_setting("rag.rerank.score_threshold") is True
        assert cfg.rag.rerank.score_threshold == 0.25  # 還原 yaml 出廠值
        rb.assert_called_once_with(["rag.rerank.score_threshold"])

    def test_reset_unknown_path_rejected(self):
        from src.adapter import runtime_settings_service as svc
        with pytest.raises(ValueError, match="不可操作"):
            svc.reset_setting("database.url")

    def test_yaml_value_falls_back_to_field_default(self):
        # yaml 裡沒寫該欄位(或檔案讀不到)→ pydantic 欄位宣告預設
        cfg = _mk_config()
        from src.adapter import runtime_settings_service as svc
        from src.config.config_manager import Config
        with self._with_cfg(cfg), patch.object(Config, "_config_path", None):
            v = svc._yaml_value("rag.contextual_retrieval.reasoning_effort")
        from src.config.model import ContextualRetrievalConfig
        assert v == ContextualRetrievalConfig.model_fields["reasoning_effort"].get_default()
