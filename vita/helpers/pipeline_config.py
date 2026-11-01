"""Environment-driven routing independent of document generation."""

from dataclasses import dataclass

from vita.helpers.diagnostics import journal as log_journal
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
            log_journal("configuration.cli_override", stage=stage, cli_provider=provider,
                        configured_provider=route.provider, configured_model=route.model,
                        effective_model=model, explanation="The same CLI provider retains the stage model; a different provider discards a vendor-specific stage model.")
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
        provider_source = "stage_environment" if provider else "provider_registry"
        model_source = "stage_environment" if model else "provider_registry"
        if stage == "extract":
            provider = provider or "gemini"
            if provider_source != "stage_environment":
                provider_source = "built_in_extraction_default"
            if model is None and provider in ("gemini", "google"):
                model = "gemini-2.5-flash"
                model_source = "built_in_extraction_default"
        if stage == "review":
            analysis = routes["analyze"]
            if provider is None:
                provider = analysis.provider
                model = model or analysis.model
                provider_source = "analysis_stage_inheritance"
                if not env.get(f"{prefix}_MODEL", "").strip():
                    model_source = "analysis_stage_inheritance"
            elif provider == analysis.provider:
                model = model or analysis.model
                if not env.get(f"{prefix}_MODEL", "").strip():
                    model_source = "analysis_stage_inheritance"
        routes[stage] = ModelRoute(provider, model)
        log_journal("configuration.stage_route", stage=stage, provider=provider, model=model,
                    provider_source=provider_source, model_source=model_source,
                    provider_variable=f"{prefix}_PROVIDER", model_variable=f"{prefix}_MODEL",
                    explanation="Extraction has its own built-in Gemini model when EXTRACTION_MODEL is unset. This explicit stage model overrides extensions.json later." if model_source == "built_in_extraction_default" else "Stage settings are passed explicitly to the provider resolver.")
    return PipelineSettings(toggle in {"true", "1", "yes", "on"}, routes)
