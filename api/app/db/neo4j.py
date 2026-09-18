from ..config import settings
from neo4j import AsyncGraphDatabase
import logging

logger = logging.getLogger(__name__)


class Neo4jClient:
    def __init__(self):
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
        return self._driver

    async def close(self):
        if self._driver:
            await self._driver.close()
            self._driver = None

    async def verify_connectivity(self):
        await self.driver.verify_connectivity()
        logger.info("Neo4j 连接成功")


neo4j_client = Neo4jClient()
