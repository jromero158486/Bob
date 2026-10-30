"""Contract that any hospital-specific adapter must implement."""
from abc import ABC, abstractmethod
from collections.abc import Iterable
from backend.app.shared.contracts.evidence import SourceDocument


class SourceAdapter(ABC):
    @abstractmethod
    def load(self) -> Iterable[SourceDocument]:
        """Yield immutable documents. Do not reinterpret clinical assertions."""
        raise NotImplementedError
