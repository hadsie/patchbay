from __future__ import annotations

from abc import ABC, abstractmethod


class BackendError(Exception):
    pass


class ServiceNotFoundError(BackendError):
    pass


class ServiceActionError(BackendError):
    pass


class BackendUnavailableError(BackendError):
    pass


class ServiceBackend(ABC):
    @abstractmethod
    async def get_state(self, target: str) -> str: ...

    @abstractmethod
    async def start(self, target: str) -> None: ...

    @abstractmethod
    async def stop(self, target: str) -> None: ...

    @abstractmethod
    async def restart(self, target: str) -> None: ...

    @abstractmethod
    async def get_health_info(self, target: str) -> str | None: ...

    @abstractmethod
    async def get_uptime(self, target: str) -> str | None: ...
