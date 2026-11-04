import pytest

from producer_exchange.config import PROJECT_ROOT, Settings
from producer_exchange.factory import build_service
from producer_exchange.memory.models import WorkingMemory
from producer_exchange.memory.profile import ProfileRepository
from producer_exchange.memory.store import SqliteDocumentStore
from producer_exchange.memory.working import WorkingMemoryRepository
from producer_exchange.safety.pii import NoopPiiDetector
from producer_exchange.sources.sample import SampleDataset

ME = "P-PE-008"
OTHER = "P-PE-002"


@pytest.fixture
def store():
    return SqliteDocumentStore()


@pytest.fixture
def sources():
    return SampleDataset(PROJECT_ROOT / "data" / "sample").as_sources()


@pytest.fixture
def working(store):
    return WorkingMemoryRepository(store, ttl_seconds=3600)


@pytest.fixture
def profiles(store, sources):
    return ProfileRepository(store, sources.producers)


@pytest.fixture
def make_service(store, sources):
    def _make(model):
        return build_service(Settings(), store=store, sources=sources, model=model, pii=NoopPiiDetector())

    return _make


@pytest.fixture
def memory():
    return WorkingMemory(exchange_id="ex-1", producer_id=ME, language="es")
