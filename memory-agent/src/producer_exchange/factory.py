"""Composition root: the only module that chooses concrete backends."""

from strands.models import BedrockModel, Model

from producer_exchange.agent.runner import StageObserver, TurnRunner
from producer_exchange.config import Settings
from producer_exchange.memory.dynamodb import DynamoDBDocumentStore
from producer_exchange.memory.profile import ProfileRepository
from producer_exchange.memory.store import DocumentStore, SqliteDocumentStore
from producer_exchange.memory.working import WorkingMemoryRepository
from producer_exchange.safety.pii import ComprehendPiiDetector, PiiDetector
from producer_exchange.service import ExchangeService
from producer_exchange.sources.base import DataSources
from producer_exchange.sources.sample import SampleDataset


def build_store(settings: Settings) -> DocumentStore:
    if settings.store_backend == "dynamodb":
        return DynamoDBDocumentStore(settings.dynamodb_table, settings.aws_region)
    return SqliteDocumentStore(settings.sqlite_path)


def build_model(settings: Settings) -> Model:
    # Sampling parameters are left unset on purpose: current Claude models reject them.
    return BedrockModel(
        model_id=settings.model_id,
        region_name=settings.aws_region,
        max_tokens=settings.max_output_tokens,
    )


def build_service(
    settings: Settings,
    *,
    store: DocumentStore | None = None,
    sources: DataSources | None = None,
    model: Model | None = None,
    pii: PiiDetector | None = None,
    observer: StageObserver | None = None,
) -> ExchangeService:
    """Wire the service from settings. Any dependency can be replaced, which is how tests stay offline."""
    store = store or build_store(settings)
    sources = sources or SampleDataset(settings.data_dir).as_sources()
    return ExchangeService(
        working=WorkingMemoryRepository(store, settings.working_memory_ttl_seconds),
        profiles=ProfileRepository(store, sources.producers),
        sources=sources,
        runner=TurnRunner(
            model or build_model(settings),
            transcript_window=settings.transcript_window_messages,
            max_stage_runs=settings.max_stage_runs,
            max_model_calls_per_run=settings.max_model_calls_per_run,
            observer=observer,
        ),
        pii=pii or ComprehendPiiDetector(settings.aws_region),
    )
