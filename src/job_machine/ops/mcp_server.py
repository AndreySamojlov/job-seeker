"""Operations MCP using existing SSH authorization, without local production secrets."""
from mcp.server.fastmcp import FastMCP
from job_machine.ops.client import RuntimeClient

mcp = FastMCP('job-machine-lab-do')
client = RuntimeClient()

@mcp.tool()
def runtime_status() -> list[dict]:
    """Read deployed image IDs, states and volumes of Job Machine services."""
    return client.status()

@mcp.tool()
def runtime_health(service: str) -> dict:
    """Check an existing service's HTTP health endpoint without changing it."""
    return client.health(service)

@mcp.tool()
def runtime_logs(service: str, lines: int = 40) -> str:
    """Read bounded service logs with best-effort credential/email redaction."""
    return client.logs(service, lines)

@mcp.tool()
def runtime_data(view: str, limit: int = 20, candidate_id: str | None = None,
                 application_id: str | None = None) -> list[dict]:
    """Read live summary/applications/vacancies/triage/events/artifacts/activity. No arbitrary SQL."""
    return client.data(view, limit, candidate_id, application_id)

@mcp.tool()
def runtime_service(action: str, service: str, expected_image: str, execute: bool = False,
                    allow_interruption: bool = False) -> dict:
    """Start/stop/restart an existing service only on explicit operator instruction.

    Inspect status first and provide its exact image ID. No redeploy or volume replacement.
    This changes availability; do not invoke merely to test the tool.
    Stop/restart require allow_interruption: deterministic/agent fill and handoff can
    be interrupted; submission outcome can become unknown. Activity counts are not
    a guarantee that workers are idle.
    """
    return client.service(action, service, expected_image, execute=execute,
                          allow_interruption=allow_interruption)

if __name__ == '__main__':
    mcp.run()
