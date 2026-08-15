from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModuleContract:
    target_module: str
    link_type: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    lifecycle: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, Any] = field(default_factory=dict)


class IntegrationRegistry:
    """Explicit cross-module bindings; no implicit imports or hidden packet operations."""

    def __init__(self) -> None:
        self.bindings: dict[tuple[str, str], tuple[ModuleContract, Callable[..., Any]]] = {}

    def register(
        self,
        contract: ModuleContract,
        handler: Callable[..., Any],
    ) -> None:
        if not callable(handler):
            raise TypeError("Integration handler must be callable")
        key = (contract.target_module, contract.link_type)
        self.bindings[key] = (contract, handler)

    def resolve(self, target_module: str, link_type: str) -> Callable[..., Any]:
        try:
            return self.bindings[(target_module, link_type)][1]
        except KeyError as exc:
            raise LookupError(f"No integration registered for {target_module}:{link_type}") from exc

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "target_module": contract.target_module,
                "link_type": contract.link_type,
                "inputs": contract.inputs,
                "outputs": contract.outputs,
                "capabilities": contract.capabilities,
                "lifecycle": contract.lifecycle,
                "errors": contract.errors,
            }
            for contract, _handler in self.bindings.values()
        ]
