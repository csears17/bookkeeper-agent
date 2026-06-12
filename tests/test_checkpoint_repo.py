from bookkeeper_agent.pipeline.store import CheckpointRepo


def test_get_absent_returns_zero(engine):
    repo = CheckpointRepo(engine)
    assert repo.get("habit@unionstreet.io") == 0


def test_set_then_get(engine):
    repo = CheckpointRepo(engine)
    repo.set("habit@unionstreet.io", 1717200000000)
    assert repo.get("habit@unionstreet.io") == 1717200000000


def test_set_upserts_single_row(engine):
    from bookkeeper_agent.db.base import session_scope
    from bookkeeper_agent.db.models import Checkpoint

    repo = CheckpointRepo(engine)
    repo.set("box", 100)
    repo.set("box", 200)
    assert repo.get("box") == 200
    with session_scope(engine) as s:
        assert s.query(Checkpoint).filter_by(mailbox="box").count() == 1
