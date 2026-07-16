"""
Centralized model loading lifecycle manager.

Coordinates loading of all service models (ASR, TTS, LLM, VAD, etc.)
with consistent lifecycle tracking, concurrent warmup, and Socket.IO status
reporting.
"""

import asyncio
from collections.abc import Callable
from enum import Enum
from typing import Any

from loguru import logger

from animetta.orchestration.socket_events import EVENTS


class ModelLoadState(Enum):
    """Lifecycle state of a single model."""

    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    ERROR = "error"


class ModelSlot:
    """Track a single model's loading lifecycle.

    Wraps an ``asyncio.Event`` so consumers can ``await slot.wait()``
    regardless of whether loading happens eagerly, lazily, or
    concurrently during warmup.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.state = ModelLoadState.UNLOADED
        self.instance: Any | None = None
        self.error: Exception | None = None
        self._event = asyncio.Event()

    def set_loaded(self, instance: Any) -> None:
        """Mark the slot as loaded and store the instance."""
        self.instance = instance
        self.state = ModelLoadState.LOADED
        self._event.set()

    def set_error(self, error: Exception) -> None:
        """Mark the slot as errored and store the exception."""
        self.error = error
        self.state = ModelLoadState.ERROR
        self._event.set()

    async def wait(self, timeout: float = 30.0) -> Any:
        """Wait until loading completes, then return the instance.

        If the slot entered an ERROR state the stored exception is
        re-raised so callers get the original traceback.
        """
        await asyncio.wait_for(self._event.wait(), timeout=timeout)
        if self.state == ModelLoadState.ERROR and self.error is not None:
            raise self.error
        return self.instance


class ModelLoadingManager:
    """Centralized model loading lifecycle manager.

    Services register their *loader function* during init.  The manager
    can then warm up all services concurrently, report progress via
    Socket.IO, and provide a uniform ``await manager.get(name)`` API
    so consumers never need to know whether a model was loaded eagerly,
    lazily, or in a warmup pass.
    """

    def __init__(self, socketio: Any = None) -> None:
        self._slots: dict[str, ModelSlot] = {}
        self._loaders: dict[str, Callable[[], Any]] = {}
        self._service_names: dict[str, str] = {}
        self._socketio = socketio
        # The server performs an early empty warmup and ServiceContext may
        # request another warmup after late registration.  Serialize passes so
        # a loader can never run twice concurrently for the same GPU model.
        self._warmup_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        loader_fn: Callable[[], Any],
        service_name: str = "",
    ) -> Any | None:
        """Register a model and optionally load it immediately if synchronous.

        Parameters
        ----------
        name:
            Unique key used to retrieve this model later via ``get()``.
        loader_fn:
            Callable that returns the model instance (can be sync or async).
        service_name:
            Human-readable label used in log / Socket.IO messages.

        Returns
        -------
        The model instance if *loader_fn* is synchronous and was
        called immediately; ``None`` for async loaders (they will be
        loaded during ``warmup()`` or on first ``get()``).
        """
        logger.info(f"Registering model: {name} ({service_name or name})")

        slot = ModelSlot(name)
        self._slots[name] = slot
        self._loaders[name] = loader_fn
        self._service_names[name] = service_name or name

        if asyncio.iscoroutinefunction(loader_fn):
            # Defer loading — warmup or first get() will handle it.
            return None

        # Synchronous loader — load right now.
        try:
            instance = loader_fn()
            slot.set_loaded(instance)
            self._emit_status(name, "loaded")
            logger.info(f"Model '{name}' loaded synchronously")
            return instance
        except Exception as exc:
            slot.set_error(exc)
            self._emit_status(name, "error", str(exc))
            logger.error(f"Model '{name}' failed to load synchronously: {exc}")
            # Propagate sync errors immediately
            raise exc from exc

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    async def warmup(self) -> None:
        """Start loading *all* registered models concurrently.

        Already-loaded slots are skipped.  Failures in one loader
        do not block the others — each slot records its own
        success / error independently.
        """
        async with self._warmup_lock:
            logger.info(f"Starting warmup for {len(self._slots)} registered model(s)")

            pending = [
                (name, loader_fn)
                for name, loader_fn in self._loaders.items()
                if self._slots[name].state not in {ModelLoadState.LOADED, ModelLoadState.ERROR}
            ]
            if pending:
                results = await asyncio.gather(
                    *(self._load_one(name, loader_fn) for name, loader_fn in pending),
                    return_exceptions=True,
                )
                for (name, _), result in zip(pending, results, strict=True):
                    if isinstance(result, Exception):
                        logger.error(
                            "Warmup exception for '{}': {}",
                            name,
                            type(result).__name__,
                        )

            logger.info("Warmup complete")

    async def _load_one(
        self,
        name: str,
        loader_fn: Callable[..., Any],
    ) -> None:
        """Load a single model and update its slot.

        This method handles both sync and async loaders and is the
        central place for logging / Socket.IO status emissions.
        """
        slot = self._slots[name]
        service_name = self._service_names.get(name, name)

        slot.state = ModelLoadState.LOADING
        self._emit_status(name, "loading")
        logger.info(f"Loading model: {service_name} ({name})")

        try:
            if asyncio.iscoroutinefunction(loader_fn):
                instance = await loader_fn()
            else:
                instance = await asyncio.to_thread(loader_fn)

            slot.set_loaded(instance)
            self._emit_status(name, "loaded")
            logger.info(f"Model '{name}' loaded successfully")

        except Exception as exc:
            slot.set_error(exc)
            self._emit_status(name, "error", str(exc))
            logger.error(f"Model '{name}' failed to load: {exc}")

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    async def get(self, name: str, timeout: float = 30.0) -> Any:
        """Retrieve a loaded model instance, triggering lazy load if needed.

        Raises
        ------
        KeyError
            If *name* was never registered.
        """
        if name not in self._slots:
            raise KeyError(f"Model '{name}' is not registered")

        slot = self._slots[name]

        if slot.state == ModelLoadState.LOADED:
            return slot.instance

        if slot.state == ModelLoadState.UNLOADED:
            # Start loading now (lazy fallback).
            loader_fn = self._loaders[name]
            logger.info(f"Lazy-loading model '{name}' (first access)")
            await self._load_one(name, loader_fn)

        return await slot.wait(timeout=timeout)

    def get_status(self) -> dict[str, str]:
        """Return a snapshot of every registered model and its state.

        Returns
        -------
        dict
            Mapping of ``{name: state_value}`` for all registered services.
        """
        return {name: slot.state.value for name, slot in self._slots.items()}

    async def wait_all(self, timeout: float = 60.0) -> bool:
        """Wait until every registered model is LOADED (or ERROR).

        Returns
        -------
        bool
            ``True`` if all models reached ``LOADED``, ``False`` if
            some models are in ``ERROR`` or timed out.
        """
        if not self._slots:
            return True

        try:
            for name, slot in self._slots.items():
                if slot.state == ModelLoadState.LOADED:
                    continue
                await asyncio.wait_for(slot._event.wait(), timeout=timeout)
        except TimeoutError:
            logger.warning("wait_all timed out")
            return False

        return all(slot.state == ModelLoadState.LOADED for slot in self._slots.values())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit_status(
        self,
        name: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """Emit a model-loading status event via Socket.IO if available."""
        if self._socketio is None:
            return

        service_name = self._service_names.get(name, name)
        payload: dict[str, Any] = {
            "service": service_name,
            "name": name,
            "status": status,
        }
        if error:
            payload["error"] = error

        try:
            asyncio.ensure_future(
                self._socketio.emit(EVENTS["system"]["model_status"]["name"], payload)
            )
        except Exception as exc:
            # Socket.IO failures should never crash the loader.
            logger.debug(f"Failed to emit model_status for '{name}': {exc}")
