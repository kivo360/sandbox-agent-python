"""Sandbox providers — integrations for various sandbox backends."""

from sandboxagent.providers.types import SandboxProvider
from sandboxagent.providers.local import LocalProvider, LocalProviderOptions, local
from sandboxagent.providers.e2b import E2BProvider, E2BProviderOptions, e2b
from sandboxagent.providers.modal import ModalProvider, ModalProviderOptions, modal
from sandboxagent.providers.sprites import SpritesProvider, SpritesProviderOptions, sprites
from sandboxagent.providers.daytona import DaytonaProvider, DaytonaProviderOptions, daytona
from sandboxagent.providers.vercel import VercelProvider, VercelProviderOptions, vercel
from sandboxagent.providers.cloudflare import (
    CloudflareProvider,
    CloudflareProviderOptions,
    CloudflareSandboxClient,
    CloudflareSandboxConnection,
    cloudflare,
)
from sandboxagent.providers.docker import DockerProvider, DockerProviderOptions, docker
from sandboxagent.providers.agentcomputer import (
    AgentComputerProvider,
    AgentComputerProviderOptions,
    AgentComputerCreateOverrides,
    AgentComputerApiError,
    agentcomputer,
)
from sandboxagent.providers.computesdk import ComputeSdkProvider, ComputeSdkProviderOptions, computesdk

__all__ = [
    # Base
    "SandboxProvider",
    # Local
    "LocalProvider",
    "LocalProviderOptions",
    "local",
    # E2B
    "E2BProvider",
    "E2BProviderOptions",
    "e2b",
    # Modal
    "ModalProvider",
    "ModalProviderOptions",
    "modal",
    # Sprites
    "SpritesProvider",
    "SpritesProviderOptions",
    "sprites",
    # Daytona
    "DaytonaProvider",
    "DaytonaProviderOptions",
    "daytona",
    # Vercel
    "VercelProvider",
    "VercelProviderOptions",
    "vercel",
    # Cloudflare
    "CloudflareProvider",
    "CloudflareProviderOptions",
    "CloudflareSandboxClient",
    "CloudflareSandboxConnection",
    "cloudflare",
    # Docker
    "DockerProvider",
    "DockerProviderOptions",
    "docker",
    # AgentComputer
    "AgentComputerProvider",
    "AgentComputerProviderOptions",
    "AgentComputerCreateOverrides",
    "AgentComputerApiError",
    "agentcomputer",
    # ComputeSDK
    "ComputeSdkProvider",
    "ComputeSdkProviderOptions",
    "computesdk",
]
