from abc import ABC, abstractmethod


class BaseDataRepository(ABC):
    @abstractmethod
    def load(self) -> dict:
        raise NotImplementedError
