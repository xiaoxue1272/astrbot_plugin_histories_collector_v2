import asyncio
from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError

from astrbot.api import logger
from data.plugins.astrbot_plugin_histories_collector_v2.config import ESConfig


class ESHelper:
    """Elasticsearch 操作：索引生命周期、模板管理和消息持久化。"""

    _MAX_SAVE_RETRIES = 3
    _RETRY_BASE_DELAY = 1.0

    _ILM_POLICY_BODY = {
        "phases": {
            "hot": {
                "actions": {
                    "rollover": {
                        "max_size": "50gb"
                    }
                }
            }
        }
    }

    def __init__(self, config: ESConfig):
        self._config = config
        self._es_client: AsyncElasticsearch | None = None
        self._alias = config.alias
        self._ilm_policy_name = f"{self._alias}-policy"
        self._use_ik = config.use_ik_analyzer
        self.is_connected: bool = False

    async def initialize(self):
        """验证 ES 连接并建立索引，连接失败不崩溃。"""
        logger.info(f"正在连接 Elasticsearch: {self._config.hosts}")

        es = AsyncElasticsearch(
            self._config.hosts,
            http_compress=True,
            http_auth=(self._config.user, self._config.password),
            sniff_on_start=False,
            request_timeout=30,
        )

        if not await es.ping():
            await es.close()
            logger.error("Elasticsearch 连接失败，插件将启动但不会保存消息。")
            return

        self._es_client = es
        logger.info("Elasticsearch 连接成功。")

        self.is_connected = True
        await self._setup_indices()

    async def _setup_indices(self):
        """创建 ILM 策略、索引模板和初始写入索引。"""
        await self._ensure_ilm_policy()
        await self._ensure_index_template()
        await self._ensure_write_index_exists()

    def _build_index_settings(self) -> dict:
        """构建索引设置，可选启用 IK 分词器。"""
        settings: dict[str, Any] = {
            "number_of_shards": 1,
            "number_of_replicas": 1,
            "index.lifecycle.name": self._ilm_policy_name,
            "index.lifecycle.rollover_alias": self._alias,
        }
        if self._use_ik:
            settings["analysis"] = {
                "analyzer": {
                    "default": {
                        "type": "custom",
                        "char_filter": ["html_strip"],
                        "tokenizer": "ik_max_word",
                        "filter": ["lowercase", "trim"],
                    },
                    "default_search": {
                        "type": "custom",
                        "char_filter": ["html_strip"],
                        "tokenizer": "ik_smart",
                        "filter": ["lowercase", "trim"],
                    },
                }
            }
        return settings

    @staticmethod
    def _build_index_mappings() -> dict:
        """构建 v2 文档 schema 的索引映射。"""
        return {
            "properties": {
                "@timestamp": {"type": "date"},
                "platform": {"type": "keyword"},
                "platform_id": {"type": "keyword"},
                "message_id": {"type": "keyword"},
                "group": {
                    "type": "nested",
                    "properties": {
                        "id": {"type": "keyword"},
                        "name": {"type": "text"},
                    },
                },
                "sender": {
                    "type": "nested",
                    "properties": {
                        "id": {"type": "keyword"},
                        "name": {"type": "text"},
                        "nickname": {"type": "keyword"},
                    },
                },
                "summary": {"type": "text"},
                "types": {"type": "keyword"},
                "messages": {
                    "type": "nested",
                    "dynamic": False,
                    "properties": {
                        "type": {"type": "keyword"},
                        "messages": {
                            "type": "nested",
                        },
                    },
                },
            }
        }

    async def _ensure_ilm_policy(self):
        """创建或更新 ILM 策略，失败不阻塞。"""
        try:
            await self._es_client.ilm.put_lifecycle(
                name=self._ilm_policy_name,
                policy=self._ILM_POLICY_BODY,
            )
            logger.info(f"ILM 策略 '{self._ilm_policy_name}' 已创建/更新。")
        except Exception as e:
            logger.warning(f"ILM 策略创建失败（将在无 ILM 的情况下继续运行）: {e}")

    async def _ensure_index_template(self):
        """创建或更新索引模板。"""
        template_name = f"{self._alias}-template"
        template_body = {
            "index_patterns": f"{self._alias}-*",
            "template": {
                "settings": self._build_index_settings(),
                "mappings": self._build_index_mappings(),
                "aliases": {
                    self._alias: {}
                },
            },
        }
        try:
            await self._es_client.indices.put_index_template(
                name=template_name,
                body=template_body,
            )
            logger.info(f"索引模板 '{template_name}' 已创建/更新。")
        except Exception as e:
            logger.error(f"索引模板创建失败: {e}")
            raise

    async def _ensure_write_index_exists(self):
        """确保可写初始索引存在并绑定到别名。"""
        try:
            alias_info = await self._es_client.indices.get_alias(name=self._alias)
            if alias_info:
                logger.info(
                    f"写入别名 '{self._alias}' 已指向: "
                    f"{list(alias_info.keys())}"
                )
                return
        except NotFoundError:
            pass  # 别名尚不存在，首次部署

        initial_index_name = f"{self._alias}-000001"
        logger.info(f"正在创建初始索引: {initial_index_name}")

        initial_index_body = {
            "settings": self._build_index_settings(),
            "mappings": self._build_index_mappings(),
            "aliases": {
                self._alias: {
                    "is_write_index": True,
                }
            },
        }
        try:
            await self._es_client.indices.create(
                index=initial_index_name,
                body=initial_index_body,
            )
            logger.info(
                f"已创建初始索引 '{initial_index_name}'，"
                f"写入别名 '{self._alias}'。"
            )
        except Exception as e:
            logger.error(f"创建初始索引失败: {e}")
            raise

    async def save_message(self, doc_id: str, doc_body: dict):
        """保存消息文档到 ES，带指数退避重试。

        Args:
            doc_id: Snowflake 生成的唯一文档 ID。
            doc_body: ES 文档字典。

        Raises:
            Exception: 重试次数用尽时抛出。
        """
        if not self._es_client:
            logger.warning("ES 客户端不可用，跳过消息保存。")
            return

        last_exception = None
        for attempt in range(1, self._MAX_SAVE_RETRIES + 1):
            try:
                response = await self._es_client.create(
                    index=self._alias,
                    id=doc_id,
                    document=doc_body,
                    require_alias=True,
                )
                result = response.get("result")
                if result in ("created", "updated"):
                    return
                raise Exception(
                    f"ES 写入返回异常结果: {result}\n"
                    f"响应: {response}\n"
                    f"文档: {doc_body}"
                )
            except Exception as e:
                last_exception = e
                if attempt < self._MAX_SAVE_RETRIES:
                    delay = self._RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        f"ES 保存失败 (第 {attempt}/{self._MAX_SAVE_RETRIES} 次)，"
                        f"{delay}秒后重试: {e}"
                    )
                    await asyncio.sleep(delay)

        logger.error(
            f"ES 保存重试 {self._MAX_SAVE_RETRIES} 次全部失败: {last_exception}"
        )
        raise last_exception

    async def search(self, body: dict) -> Any:
        """执行 ES 搜索查询。

        Args:
            body: 完整 ES 搜索 body，直接透传。size/from 等所有参数均在 body 内。

        Returns:
            ES 搜索结果（ObjectApiResponse）。
        """
        if not self._es_client:
            raise RuntimeError("ES 客户端不可用")
        return await self._es_client.search(index=self._alias, body=body)

    async def close(self):
        """关闭 Elasticsearch 客户端连接。"""
        if self._es_client:
            await self._es_client.close()
