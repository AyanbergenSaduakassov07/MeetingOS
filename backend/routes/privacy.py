"""Privacy and data-governance control centre.

Surfaces what is actually true about this install rather than what the docs
say: which providers are cloud and which are local, whether redaction is on and
which rules, where data resides, and a log of what has been sent where.

The provider list is derived from live configuration — the resolved base URL,
whether credentials are present — not from a static table. A settings page that
describes an intended configuration rather than the running one is worse than
no page, because it is believed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config as app_config
from ..auth import configured_key
from ..database import Organization, ProviderCall, get_db
from ..meetings import redaction
from ..meetings.egress_log import LOCAL_HOSTS, host_of
from ..meetings.redaction_rules import ALL_RULES, CATEGORIES, RedactionConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/privacy", tags=["privacy"])

AUDIT_PAGE_SIZE = 50


class ProviderInfo(BaseModel):
    """One configured provider, as it is actually resolved right now."""

    name: str
    role: str  # llm | embedding | transcription
    model: str | None = None
    endpoint_host: str | None = None
    # False only for localhost. Everything else leaves the machine.
    is_cloud: bool = True
    configured: bool = False
    is_default: bool = False


class RuleInfo(BaseModel):
    name: str
    category: str
    description: str
    enabled: bool


class RedactionInfo(BaseModel):
    enabled: bool
    source: str  # "settings" | "environment"
    rules: list[RuleInfo] = []
    categories: list[str] = []
    # Stated plainly on the page, not buried in docs.
    limitations: list[str] = []


class DataResidencyInfo(BaseModel):
    """Informational: single-tenant-per-install, so this describes one machine."""

    data_dir: str
    database: str
    recordings_dir: str
    documents_dir: str
    single_tenant: bool = True
    allowed_inference_hosts: list[str] = []
    notes: list[str] = []


class AuditEntry(BaseModel):
    id: str
    created_at: str | None = None
    provider: str
    model: str | None = None
    operation: str
    endpoint_host: str | None = None
    is_cloud: bool = True
    characters_sent: int | None = None
    items_sent: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    redaction_enabled: bool = False
    redactions_applied: int = 0
    succeeded: bool = True
    error: str | None = None
    meeting_id: str | None = None


class AuditSummary(BaseModel):
    total_calls: int = 0
    cloud_calls: int = 0
    local_calls: int = 0
    failed_calls: int = 0
    characters_sent: int = 0
    calls_without_redaction: int = 0
    distinct_hosts: list[str] = []


class PrivacyOut(BaseModel):
    providers: list[ProviderInfo] = []
    redaction: RedactionInfo
    residency: DataResidencyInfo
    audit_summary: AuditSummary
    recent_calls: list[AuditEntry] = []


def _provider_rows() -> list[ProviderInfo]:
    """Resolve every configured provider from live config."""
    from ..ai import get_embedding_provider, get_llm_provider
    from ..ai.orchestrator import DEFAULT_PROVIDER
    from ..transcription import get_transcription_provider

    rows: list[ProviderInfo] = []
    seen: set[tuple[str, str]] = set()

    def add(provider, role: str) -> None:
        key = (provider.config.name, role)
        if key in seen:
            return
        seen.add(key)
        default_host = {
            "openai": "api.openai.com",
            "anthropic": "api.anthropic.com",
            "whisper_cloud": "api.openai.com",
        }.get(provider.config.name)
        host = host_of(getattr(provider.config, "base_url", None), default=default_host)
        rows.append(
            ProviderInfo(
                name=provider.config.name,
                role=role,
                model=(
                    getattr(provider.config, "embedding_model", None) or provider.config.model
                    if role == "embedding"
                    else provider.config.model
                ),
                endpoint_host=host,
                is_cloud=(host or "") not in LOCAL_HOSTS,
                configured=bool(provider.is_configured()),
                is_default=(role == "llm" and provider.config.name == DEFAULT_PROVIDER),
            )
        )

    for resolver, role in (
        (get_llm_provider, "llm"),
        (get_embedding_provider, "embedding"),
        (get_transcription_provider, "transcription"),
    ):
        try:
            add(resolver(), role)
        except Exception as exc:
            logger.warning("Could not resolve the %s provider: %s", role, exc)
    return rows


def _redaction_info() -> RedactionInfo:
    active = redaction.active_config()
    chosen = set(active.rules)
    return RedactionInfo(
        enabled=active.enabled,
        source="settings" if redaction._active_config is not None else "environment",
        rules=[
            RuleInfo(
                name=rule.name,
                category=rule.category,
                description=rule.description,
                enabled=rule.name in chosen,
            )
            for rule in ALL_RULES
        ],
        categories=list(CATEGORIES),
        limitations=[
            "Names are never redacted. 'Priya will chase the invoice' is the action "
            "item; stripping names would leave nothing to extract. This is a "
            "mitigation, not anonymisation.",
            "Health matching is keyword-based and redacts the surrounding clause. It "
            "will miss euphemism and will sometimes over-match. Over-matching is the "
            "safer error and is what it is tuned for.",
            "Salary matching needs a compensation word near the figure. A pay number "
            "stated with no context word will not be caught.",
            "Documents marked sensitive are redacted whatever this setting says, "
            "and are indexed redacted — so searching one for a redacted span will "
            "not find it.",
            "A meeting that genuinely must not leave this machine needs a local model, not redaction.",
        ],
    )


def _residency_info() -> DataResidencyInfo:
    data_dir = app_config.get_data_dir()
    return DataResidencyInfo(
        data_dir=str(data_dir),
        database=str(data_dir / "meetingos.db"),
        recordings_dir=str(app_config.get_recordings_dir()),
        documents_dir=str(data_dir / "documents"),
        single_tenant=True,
        allowed_inference_hosts=sorted(app_config.allowed_inference_hosts()),
        notes=[
            "Single tenant per install: all data lives under the data directory above.",
            "Recordings and documents are stored unencrypted on this filesystem; "
            "disk encryption is the operator's responsibility.",
            "Customer-managed keys and a full on-prem provider swap are not "
            "implemented. That is the v1 enterprise milestone, not this pass.",
            _access_note(),
        ],
    )


def _access_note() -> str:
    if configured_key() is None:
        return (
            "No API key is set: anything that can reach this port can read every meeting. "
            "Set MEETINGOS_API_KEY before exposing it beyond this machine."
        )
    return (
        "Access requires MEETINGOS_API_KEY. It is one shared key, so everyone holding it "
        "sees every meeting; per-user accounts are on the roadmap."
    )


@router.get("", response_model=PrivacyOut)
async def get_privacy(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> PrivacyOut:
    """Current privacy posture, plus recent outbound calls."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    calls = (
        db.query(ProviderCall)
        .filter(ProviderCall.created_at >= cutoff)
        .order_by(ProviderCall.created_at.desc())
        .limit(AUDIT_PAGE_SIZE)
        .all()
    )
    window = db.query(ProviderCall).filter(ProviderCall.created_at >= cutoff).all()

    summary = AuditSummary(
        total_calls=len(window),
        cloud_calls=sum(1 for c in window if c.is_cloud),
        local_calls=sum(1 for c in window if not c.is_cloud),
        failed_calls=sum(1 for c in window if not c.succeeded),
        characters_sent=sum(c.characters_sent or 0 for c in window),
        calls_without_redaction=sum(1 for c in window if c.is_cloud and not c.redaction_enabled),
        distinct_hosts=sorted({c.endpoint_host for c in window if c.endpoint_host}),
    )

    return PrivacyOut(
        providers=_provider_rows(),
        redaction=_redaction_info(),
        residency=_residency_info(),
        audit_summary=summary,
        recent_calls=[
            AuditEntry(
                id=c.id,
                created_at=c.created_at.isoformat() if c.created_at else None,
                provider=c.provider,
                model=c.model,
                operation=c.operation,
                endpoint_host=c.endpoint_host,
                is_cloud=bool(c.is_cloud),
                characters_sent=c.characters_sent,
                items_sent=c.items_sent,
                input_tokens=c.input_tokens,
                output_tokens=c.output_tokens,
                redaction_enabled=bool(c.redaction_enabled),
                redactions_applied=c.redactions_applied or 0,
                succeeded=bool(c.succeeded),
                error=c.error,
                meeting_id=c.meeting_id,
            )
            for c in calls
        ],
    )


class RedactionUpdate(BaseModel):
    enabled: bool
    rules: list[str] | None = None


@router.put("/redaction", response_model=RedactionInfo)
async def update_redaction(
    payload: RedactionUpdate = Body(...),
    org_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> RedactionInfo:
    """Turn redaction on or off and choose which rules run.

    Stored on the organization so it survives a restart, and installed as the
    process default immediately.
    """
    organizations = db.query(Organization).limit(2).all()
    if org_id:
        organization = db.query(Organization).filter_by(id=org_id).first()
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {org_id} not found")
    elif len(organizations) == 1:
        organization = organizations[0]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pass org_id explicitly: zero or multiple organizations exist.",
        )

    new_config = RedactionConfig.from_dict({"enabled": payload.enabled, "rules": payload.rules})
    settings = dict(organization.settings or {})
    settings["redaction"] = new_config.to_dict()
    organization.settings = settings
    db.commit()

    redaction.set_active_config(new_config)
    logger.info(
        "Redaction updated for org %s: enabled=%s, %d rule(s)",
        organization.id,
        new_config.enabled,
        len(new_config.rules),
    )
    return _redaction_info()


def load_org_redaction(db: Session) -> None:
    """Install the stored redaction config at startup.

    Falls back to the environment flag when no org has configured one, so an
    install that never opens the privacy page behaves exactly as before.
    """
    try:
        organizations = db.query(Organization).limit(2).all()
        if len(organizations) != 1:
            return
        stored = (organizations[0].settings or {}).get("redaction")
        if stored:
            redaction.set_active_config(RedactionConfig.from_dict(stored))
    except Exception as exc:
        logger.warning("Could not load stored redaction config: %s", exc)
