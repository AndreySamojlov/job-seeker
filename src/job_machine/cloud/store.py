"""DB-слой Experience Cloud: upsert/load позиций, достижений, скиллов.
Порядок upsert: позиции → достижения (FK pid) → скиллы."""

from job_machine.cloud.models import (
    CloudAchievement, CloudPosition, CloudSkill, ExperienceCloud,
)


def upsert_cloud(conn, cloud: ExperienceCloud, candidate_id: str) -> None:
    with conn.cursor() as cur:
        for p in cloud.positions:
            cur.execute(
                "insert into cloud_position (candidate_id, pid, company, title, start_date, "
                "end_date, location, summary, updated_at) values (%s,%s,%s,%s,%s,%s,%s,%s, now()) "
                "on conflict (candidate_id, pid) do update set company=excluded.company, "
                "title=excluded.title, start_date=excluded.start_date, end_date=excluded.end_date, "
                "location=excluded.location, summary=excluded.summary, updated_at=now()",
                (candidate_id, p.pid, p.company, p.title, p.start, p.end, p.location, p.summary))
        for a in cloud.achievements:
            cur.execute(
                "insert into cloud_achievement (candidate_id, aid, pid, text, metric, status, "
                "claims, safe_use, updated_at) values (%s,%s,%s,%s,%s,%s,%s,%s, now()) "
                "on conflict (candidate_id, aid) do update set pid=excluded.pid, text=excluded.text, "
                "metric=excluded.metric, status=excluded.status, claims=excluded.claims, "
                "safe_use=excluded.safe_use, updated_at=now()",
                (candidate_id, a.aid, a.pid, a.text, a.metric, a.status, a.claims, a.safe_use))
        for s in cloud.skills:
            cur.execute(
                "insert into cloud_skill (candidate_id, name, category, framing, evidence, "
                "safe_use, updated_at) values (%s,%s,%s,%s,%s,%s, now()) "
                "on conflict (candidate_id, name) do update set category=excluded.category, "
                "framing=excluded.framing, evidence=excluded.evidence, safe_use=excluded.safe_use, "
                "updated_at=now()",
                (candidate_id, s.name, s.category, s.framing, s.evidence, s.safe_use))


def load_cloud(conn, candidate_id: str) -> ExperienceCloud:
    with conn.cursor() as cur:
        cur.execute("select pid, company, title, start_date, end_date, location, summary "
                    "from cloud_position where candidate_id=%s order by pid", (candidate_id,))
        positions = [CloudPosition(pid=r[0], company=r[1] or "", title=r[2] or "",
                                   start=r[3] or "", end=r[4] or "", location=r[5] or "",
                                   summary=r[6] or "") for r in cur.fetchall()]
        cur.execute("select aid, pid, text, metric, status, claims, safe_use "
                    "from cloud_achievement where candidate_id=%s order by aid", (candidate_id,))
        achievements = [CloudAchievement(aid=r[0], pid=r[1] or "", text=r[2] or "",
                                         metric=r[3] or "", status=r[4] or "", claims=r[5] or "",
                                         safe_use=r[6] or "") for r in cur.fetchall()]
        cur.execute("select name, category, framing, evidence, safe_use "
                    "from cloud_skill where candidate_id=%s order by name", (candidate_id,))
        skills = [CloudSkill(name=r[0], category=r[1] or "", framing=r[2] or "",
                             evidence=r[3] or "", safe_use=r[4] or "") for r in cur.fetchall()]
    return ExperienceCloud(positions=positions, achievements=achievements, skills=skills)
