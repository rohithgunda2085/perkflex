"""Settings, read from environment variables. In development they come from perkflex/.env."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # perkflex/
BACKEND = ROOT / "backend"
SQL_DIR = BACKEND / "db" / "sql"
DEFAULT_CA = BACKEND / "db" / "certs" / "global-bundle.pem"

# Real environment variables win over the file, so containers and CI can override .env.
# Loading into os.environ also lets boto3 see AWS_BEARER_TOKEN_BEDROCK and AWS_REGION.
load_dotenv(ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # PostgreSQL (RDS)
    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    # verify (default): TLS with the RDS CA bundle | no-verify: TLS without checks | disable: plain TCP
    db_ssl: str = "verify"
    db_ssl_ca: str = ""
    db_pool_max: int = Field(default=5, ge=1, le=50)
    # Optional search_path, used by tests to run inside a throwaway schema.
    db_schema: str = ""

    # Sessions
    session_secret: str = ""
    session_ttl_seconds: int = 8 * 60 * 60

    # Bedrock
    aws_region: str = "us-east-1"
    bedrock_model_id: str = ""
    # Bedrock Guardrails (optional). With an id set, the traveller's free text is screened before any model call and
    # every Converse call runs under the guardrail. Leave empty to run without one.
    bedrock_guardrail_id: str = ""
    bedrock_guardrail_version: str = "DRAFT"
    # Where the advisor's model loop runs: "local" (inside this API) or "agentcore" (an Amazon Bedrock AgentCore
    # Runtime that receives the context as its payload). The API validates the answer either way.
    advisor_runtime: str = "local"
    agentcore_runtime_arn: str = ""
    agentcore_qualifier: str = ""

    # Email notifications through Amazon SES. Off unless EMAIL_ENABLED is true and EMAIL_FROM is a verified SES identity.
    email_enabled: bool = False
    email_from: str = ""
    email_configuration_set: str = ""
    # The public address of the site (for example the CloudFront URL), used for the confirmation link in the email.
    public_base_url: str = ""

    # API server
    api_host: str = "127.0.0.1"
    api_port: int = 3001
    environment: str = "development"

    # Demo features. DEMO_MODE lets a signed-in user switch to another demo traveller and enables the
    # demo clock. Turn it off for anything real.
    demo_mode: bool = True
    # ISO time that "now" is pinned to for check-in windows. The seed flights are in 2026 and 2027, so the default
    # sits after every check-in opens (latest: 15 Dec 2027 23:40 UTC) and before every departure on 16 Dec 2027.
    # Set DEMO_NOW to an empty value to use the real clock.
    demo_now: str = "2027-12-15T23:59:00+00:00"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
