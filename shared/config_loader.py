"""
shared/config_loader.py — Loads, validates, and returns config as typed dataclasses.
All agents import this at startup.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Optional jsonschema validation — graceful degradation if not installed
try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

_REPO_ROOT = Path(__file__).parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "config.yaml"
_SCHEMA_PATH = _REPO_ROOT / "config" / "config.schema.json"

# --------------------------------------------------------------------------- #
# Typed dataclasses                                                            #
# --------------------------------------------------------------------------- #

@dataclass
class Skills:
    primary: list[str]
    secondary: list[str]
    learning: list[str]


@dataclass
class Profile:
    name: str
    email: str
    linkedin: str
    github: str
    location: str
    bio: str
    skills: Skills
    seniority: str
    target_titles: list[str]
    target_industries: list[str]
    resume_base_path: str
    branding_statement: str
    portfolio: str = ""


@dataclass
class Salary:
    min: int
    max: int
    currency: str


@dataclass
class JobSearchPreferences:
    locations: list[str]
    salary: Salary
    employment_type: list[str]
    seniority_levels: list[str]
    company_blacklist: list[str]
    company_whitelist: list[str]
    preferred_tech_stack: list[str]
    company_size: list[str]
    visa_constraints: str
    relocation: bool
    remote_preference: str
    score_threshold: int


@dataclass
class Platform:
    enabled: bool
    method: str


@dataclass
class Platforms:
    wellfound: Platform
    greenhouse: Platform
    otta: Platform
    serpapi_google_jobs: Platform
    linkedin_apify: Platform
    indeed: Platform


@dataclass
class SendWindow:
    start_hour: int
    end_hour: int
    timezone: str


@dataclass
class WarmUp:
    week_1_max: int
    week_2_max: int
    week_3_plus_max: int


@dataclass
class RecruiterOutreach:
    target_titles: list[str]
    target_seniority: list[str]
    max_contacts_per_day: int
    max_contacts_per_company: int
    personalization_level: str
    mode: str
    follow_up_cadence_days: list[int]
    max_follow_ups: int
    send_window: SendWindow
    warm_up: WarmUp


@dataclass
class EmailRoutingRules:
    job_important_keywords: list[str]
    job_important_domains: list[str]
    networking_keywords: list[str]
    spam_keywords: list[str]
    send_daily_digest: bool
    digest_time: str
    digest_timezone: str
    flag_keywords: list[str]
    classification_confidence_threshold: float


@dataclass
class ProjectRepo:
    name: str
    url: str
    local_path: str
    allowed_tasks: list[str]
    tech_stack: list[str]
    max_lines_changed_per_run: int
    require_pr: bool
    require_tests: bool
    ci_integration: bool = False


@dataclass
class ProjectAutomation:
    repos: list[ProjectRepo]
    schedule: str
    max_session_duration_minutes: int


@dataclass
class AtsRules:
    no_tables: bool
    no_graphics: bool
    standard_section_names: bool
    single_column: bool
    no_headers_footers: bool
    font_constraint: str


@dataclass
class ResumeAutomation:
    target_roles: list[str]
    target_regions: list[str]
    seniority: str
    allowed_templates: list[str]
    output_formats: list[str]
    customization_level: str
    ats_rules: AtsRules
    keywords_to_emphasize: list[str]
    keywords_to_avoid: list[str]
    tone: str
    benchmark_profiles: list[str]
    output_dir: str


@dataclass
class ResearchSources:
    github_trending: bool
    huggingface_papers: bool
    arxiv: bool
    wellfound_jobs: bool
    product_hunt: bool
    reddit_ml: bool
    hacker_news: bool


@dataclass
class ResearchAndDiscovery:
    scan_frequency: str
    sources: ResearchSources
    goals: list[str]
    summary_style: str
    summary_max_items: int
    try_asap_threshold: float
    watch_threshold: float


@dataclass
class DocsConvention:
    changelog: str
    runbook: str
    weekly_report: str


@dataclass
class DocumentationAndGithub:
    automation_repo: str
    primary_repos: list[str]
    docs_convention: DocsConvention
    commit_frequency: str
    commit_style: str
    committable_artifacts: list[str]
    never_commit: list[str]
    auto_update_readme: bool
    profile_readme_repo: str


@dataclass
class RateLimits:
    linkedin_profile_views_per_day: int
    cold_emails_per_day: int
    apollo_api_calls_per_day: int
    hunter_lookups_per_day: int
    serpapi_calls_per_day: int
    github_actions_minutes_per_month: int


@dataclass
class Ethics:
    no_fake_personas: bool
    always_include_unsubscribe: bool
    honor_opt_outs_immediately: bool
    no_purchased_lists: bool
    no_direct_linkedin_scraping: bool


@dataclass
class Constraints:
    daily_time_budget_minutes: int
    rate_limits: RateLimits
    anthropic_api_budget_usd_per_month: float
    ethics: Ethics
    manual_approval_required: list[str]


@dataclass
class MobileCommand:
    agent: str
    params: list[str]
    description: str


@dataclass
class MobileCommands:
    transport: str
    telegram_bot_name: str
    commands: dict[str, MobileCommand]


@dataclass
class Config:
    profile: Profile
    job_search_preferences: JobSearchPreferences
    platforms: Platforms
    recruiter_outreach: RecruiterOutreach
    email_routing_rules: EmailRoutingRules
    project_automation: ProjectAutomation
    resume_automation: ResumeAutomation
    research_and_discovery: ResearchAndDiscovery
    documentation_and_github: DocumentationAndGithub
    constraints: Constraints
    mobile_commands: MobileCommands


# --------------------------------------------------------------------------- #
# Parsing helpers                                                              #
# --------------------------------------------------------------------------- #

def _parse_platform(d: dict) -> Platform:
    return Platform(enabled=d["enabled"], method=d["method"])


def _parse_config(raw: dict[str, Any]) -> Config:
    p = raw["profile"]
    profile = Profile(
        name=p["name"],
        email=p["email"],
        linkedin=p["linkedin"],
        github=p["github"],
        portfolio=p.get("portfolio", ""),
        location=p["location"],
        bio=p["bio"].strip(),
        skills=Skills(**p["skills"]),
        seniority=p["seniority"],
        target_titles=p["target_titles"],
        target_industries=p["target_industries"],
        resume_base_path=p["resume_base_path"],
        branding_statement=p["branding_statement"].strip(),
    )

    j = raw["job_search_preferences"]
    job_prefs = JobSearchPreferences(
        locations=j["locations"],
        salary=Salary(**j["salary"]),
        employment_type=j["employment_type"],
        seniority_levels=j["seniority_levels"],
        company_blacklist=j["company_blacklist"],
        company_whitelist=j["company_whitelist"],
        preferred_tech_stack=j["preferred_tech_stack"],
        company_size=j["company_size"],
        visa_constraints=j["visa_constraints"],
        relocation=j["relocation"],
        remote_preference=j["remote_preference"],
        score_threshold=j["score_threshold"],
    )

    pl = raw["platforms"]
    platforms = Platforms(
        wellfound=_parse_platform(pl["wellfound"]),
        greenhouse=_parse_platform(pl["greenhouse"]),
        otta=_parse_platform(pl["otta"]),
        serpapi_google_jobs=_parse_platform(pl["serpapi_google_jobs"]),
        linkedin_apify=_parse_platform(pl["linkedin_apify"]),
        indeed=_parse_platform(pl["indeed"]),
    )

    ro = raw["recruiter_outreach"]
    outreach = RecruiterOutreach(
        target_titles=ro["target_titles"],
        target_seniority=ro["target_seniority"],
        max_contacts_per_day=ro["max_contacts_per_day"],
        max_contacts_per_company=ro["max_contacts_per_company"],
        personalization_level=ro["personalization_level"],
        mode=ro["mode"],
        follow_up_cadence_days=ro["follow_up_cadence_days"],
        max_follow_ups=ro["max_follow_ups"],
        send_window=SendWindow(**ro["send_window"]),
        warm_up=WarmUp(**ro["warm_up"]),
    )

    er = raw["email_routing_rules"]
    email_rules = EmailRoutingRules(
        job_important_keywords=er["job_important_keywords"],
        job_important_domains=er["job_important_domains"],
        networking_keywords=er["networking_keywords"],
        spam_keywords=er["spam_keywords"],
        send_daily_digest=er["send_daily_digest"],
        digest_time=er["digest_time"],
        digest_timezone=er["digest_timezone"],
        flag_keywords=er["flag_keywords"],
        classification_confidence_threshold=er["classification_confidence_threshold"],
    )

    pa = raw["project_automation"]
    project_auto = ProjectAutomation(
        repos=[
            ProjectRepo(
                name=r["name"],
                url=r["url"],
                local_path=r["local_path"],
                allowed_tasks=r["allowed_tasks"],
                tech_stack=r["tech_stack"],
                max_lines_changed_per_run=r["max_lines_changed_per_run"],
                require_pr=r["require_pr"],
                require_tests=r["require_tests"],
                ci_integration=r.get("ci_integration", False),
            )
            for r in pa["repos"]
        ],
        schedule=pa["schedule"],
        max_session_duration_minutes=pa["max_session_duration_minutes"],
    )

    ra = raw["resume_automation"]
    resume_auto = ResumeAutomation(
        target_roles=ra["target_roles"],
        target_regions=ra["target_regions"],
        seniority=ra["seniority"],
        allowed_templates=ra["allowed_templates"],
        output_formats=ra["output_formats"],
        customization_level=ra["customization_level"],
        ats_rules=AtsRules(**ra["ats_rules"]),
        keywords_to_emphasize=ra["keywords_to_emphasize"],
        keywords_to_avoid=ra["keywords_to_avoid"],
        tone=ra["tone"],
        benchmark_profiles=ra["benchmark_profiles"],
        output_dir=ra["output_dir"],
    )

    rd = raw["research_and_discovery"]
    research = ResearchAndDiscovery(
        scan_frequency=rd["scan_frequency"],
        sources=ResearchSources(**rd["sources"]),
        goals=rd["goals"],
        summary_style=rd["summary_style"],
        summary_max_items=rd["summary_max_items"],
        try_asap_threshold=rd["try_asap_threshold"],
        watch_threshold=rd["watch_threshold"],
    )

    dg = raw["documentation_and_github"]
    docs = DocumentationAndGithub(
        automation_repo=dg["automation_repo"],
        primary_repos=dg["primary_repos"],
        docs_convention=DocsConvention(**dg["docs_convention"]),
        commit_frequency=dg["commit_frequency"],
        commit_style=dg["commit_style"],
        committable_artifacts=dg["committable_artifacts"],
        never_commit=dg["never_commit"],
        auto_update_readme=dg["auto_update_readme"],
        profile_readme_repo=dg["profile_readme_repo"],
    )

    c = raw["constraints"]
    constraints = Constraints(
        daily_time_budget_minutes=c["daily_time_budget_minutes"],
        rate_limits=RateLimits(**c["rate_limits"]),
        anthropic_api_budget_usd_per_month=c["anthropic_api_budget_usd_per_month"],
        ethics=Ethics(**c["ethics"]),
        manual_approval_required=c["manual_approval_required"],
    )

    mc = raw["mobile_commands"]
    mobile = MobileCommands(
        transport=mc["transport"],
        telegram_bot_name=mc["telegram_bot_name"],
        commands={
            k: MobileCommand(agent=v["agent"], params=v["params"], description=v["description"])
            for k, v in mc["commands"].items()
        },
    )

    return Config(
        profile=profile,
        job_search_preferences=job_prefs,
        platforms=platforms,
        recruiter_outreach=outreach,
        email_routing_rules=email_rules,
        project_automation=project_auto,
        resume_automation=resume_auto,
        research_and_discovery=research,
        documentation_and_github=docs,
        constraints=constraints,
        mobile_commands=mobile,
    )


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

_cached_config: Config | None = None


def load_config(path: str | Path | None = None, validate: bool = True) -> Config:
    """Load and return the typed Config object. Results are cached after first call."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    config_path = Path(path) if path else _CONFIG_PATH

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if validate and _HAS_JSONSCHEMA and _SCHEMA_PATH.exists():
        with open(_SCHEMA_PATH) as f:
            schema = json.load(f)
        try:
            jsonschema.validate(instance=raw, schema=schema)
        except jsonschema.ValidationError as e:
            raise ValueError(f"config.yaml validation failed: {e.message}") from e
    elif validate and not _HAS_JSONSCHEMA:
        pass  # silently skip if jsonschema not installed

    _cached_config = _parse_config(raw)
    return _cached_config


def reload_config(path: str | Path | None = None) -> Config:
    """Force reload config (clears cache)."""
    global _cached_config
    _cached_config = None
    return load_config(path)


if __name__ == "__main__":
    cfg = load_config()
    print(f"Loaded config for: {cfg.profile.name}")
    print(f"Target titles: {cfg.profile.target_titles}")
    print(f"Score threshold: {cfg.job_search_preferences.score_threshold}")
