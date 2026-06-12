from bookkeeper_agent.clients import ClientConfig
from bookkeeper_agent.connectors.slack_events import FileDrop
from bookkeeper_agent.pipeline.intake import BillIntake
from bookkeeper_agent.pipeline.slack_drop import build_drop_intake


def _client():
    return ClientConfig(key="habit-pilates", display_name="Habit Pilates", provider="google",
                        mailbox="habit@unionstreet.io", qbo_realm_id="111", autonomy_level=0)


def test_build_drop_intake_binds_client_and_skips_classification():
    drop = FileDrop(file_id="F1", filename="invoice.pdf", mime_type="application/pdf",
                    url_private="https://files.slack.com/x", channel="C-DROPS",
                    user="U1", text="for habit pilates")
    downloaded = {}

    def download(url):
        downloaded["url"] = url
        return b"%PDF-bytes"

    intake = build_drop_intake(drop, _client(), download)
    assert isinstance(intake, BillIntake)
    assert intake.source == "slack-drop"
    assert intake.source_id == "F1"
    assert intake.company_realm == "111"  # from the validated client, not the model
    assert intake.client_key == "habit-pilates"
    assert intake.skip_classification is True
    assert intake.attachments[0].content == b"%PDF-bytes"
    assert intake.attachments[0].mime_type == "application/pdf"
    assert downloaded["url"] == "https://files.slack.com/x"
