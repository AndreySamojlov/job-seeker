import asyncio
from job_machine.mcp import server


def test_new_tools_registered():
    tools_list = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools_list}
    assert "set_application_answers" in names
    assert "prepare_application_answers" in names
    assert "regenerate_resume" in names
    assert "refile_application" in names
