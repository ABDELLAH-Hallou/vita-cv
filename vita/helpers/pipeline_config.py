"""Environment-driven routing independent of document generation."""

from dataclasses import dataclass

from vita.helpers.diagnostics import phase
from vita.helpers.env import load_env

STAGE_PREFIXES = {
    "extract": "EXTRACTION", "analyze": "ANALYSIS", "adapt": "ADAPT",
    "review": "REVIEW", "cover": "COVER",
}


@dataclass(frozen=True)
class ModelRoute:
    provider: str | None = None
    model: str | None = None

    def kwargs(self) -> dict:
        result = {"provider": self.provider}
        if self.model:
            result["model"] = self.model
        return result


@dataclass(frozen=True)
class PipelineSettings:
    extraction_enabled: bool
    routes: dict[str, ModelRoute]

    def route(self, stage: str, provider: str | None = None) -> ModelRoute:
        route = self.routes[stage]
        if provider:
            # A CLI provider override must not inherit a different vendor's model.
            model = route.model if not route.provider or provider.lower() == route.provider else None
            return ModelRoute(provider.lower(), model)
        return route


@phase("configuration")
def load_pipeline_settings() -> PipelineSettings:
    env = load_env()
    toggle = env.get("ENABLE_JD_EXTRACTION", "false").strip().lower()
    if toggle not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        raise ValueError("ENABLE_JD_EXTRACTION must be true or false")
    routes = {}
    for stage, prefix in STAGE_PREFIXES.items():
        provider = env.get(f"{prefix}_PROVIDER", "").strip().lower() or None
        model = env.get(f"{prefix}_MODEL", "").strip() or None
        if stage == "extract":
            provider = provider or "gemini"
            if model is None and provider in ("gemini", "google"):
                model = "gemini-2.5-flash"
        if stage == "review":
            analysis = routes["analyze"]
            if provider is None:
                provider = analysis.provider
                model = model or analysis.model
            elif provider == analysis.provider:
                model = model or analysis.model
        routes[stage] = ModelRoute(provider, model)
    return PipelineSettings(toggle in {"true", "1", "yes", "on"}, routes)
